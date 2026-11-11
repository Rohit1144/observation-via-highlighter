"""Relay between the AgentCore harness and the local MCP server.

One question = one harness session:
  1. invoke_harness with the question.
  2. Read the event stream: answer text, tool calls, tool results, token usage.
  3. If the stream ends with stopReason == "tool_use", the harness is waiting on our
     inline functions. Run each pending call against the MCP server (asking the human
     first for write tools), send the results back in the same session, go to 2.
  4. Stop when the agent finishes (or a limit is hit).

Everything is recorded: an evidence file (question, every tool call with its input and
output, code run in the Code Interpreter, final answer, usage) and the raw event stream,
both under runs/ (gitignored).
"""

from __future__ import annotations

import json
import re
import sys
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import boto3
from botocore.exceptions import BotoCoreError, ClientError
from mcp import Client, StdioServerParameters

from . import config

RUNS_DIR = config.REPO_ROOT / "runs"
MAX_HANDOFFS = 25  # safety net on top of the harness's own maxIterations


# --------------------------------------------------------------------------------------
# Stream parsing
# --------------------------------------------------------------------------------------

@dataclass
class Block:
    """One content block (text, toolUse or toolResult) assembled from stream deltas."""
    message_no: int
    role: str
    kind: str = "text"
    text: str = ""
    tool_use_id: str | None = None
    tool_name: str | None = None
    tool_input_raw: str = ""
    result_parts: list = field(default_factory=list)

    def tool_input(self) -> Any:
        try:
            return json.loads(self.tool_input_raw) if self.tool_input_raw else {}
        except json.JSONDecodeError:
            return self.tool_input_raw


@dataclass
class Turn:
    """Everything one invoke_harness call streamed back."""
    blocks: list[Block] = field(default_factory=list)
    stop_reasons: list[str] = field(default_factory=list)
    usage: dict = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)


def read_stream(stream, raw_log, on_text) -> Turn:
    turn = Turn()
    message_no, role = -1, "assistant"
    open_blocks: dict[int, Block] = {}

    for event in stream:
        raw_log.write(json.dumps(event, default=str) + "\n")

        if "messageStart" in event:
            message_no += 1
            role = event["messageStart"].get("role", "assistant")
            open_blocks = {}

        elif "contentBlockStart" in event:
            e = event["contentBlockStart"]
            start = e.get("start", {})
            b = Block(message_no, role)
            if "toolUse" in start:
                b.kind = "toolUse"
                b.tool_use_id = start["toolUse"].get("toolUseId")
                b.tool_name = start["toolUse"].get("name")
            elif "toolResult" in start:
                b.kind = "toolResult"
                b.tool_use_id = start["toolResult"].get("toolUseId")
            open_blocks[e.get("contentBlockIndex", 0)] = b
            turn.blocks.append(b)

        elif "contentBlockDelta" in event:
            e = event["contentBlockDelta"]
            idx = e.get("contentBlockIndex", 0)
            b = open_blocks.get(idx)
            if b is None:  # delta without a start event: treat as text
                b = open_blocks[idx] = Block(message_no, role)
                turn.blocks.append(b)
            delta = e.get("delta", {})
            if "text" in delta:
                b.text += delta["text"]
                if role == "assistant":
                    on_text(delta["text"])
            elif "toolUse" in delta:
                b.tool_input_raw += delta["toolUse"].get("input", "")
            elif "toolResult" in delta:
                b.kind = "toolResult"
                b.result_parts.append(delta["toolResult"])

        elif "messageStop" in event:
            turn.stop_reasons.append(event["messageStop"].get("stopReason", ""))

        elif "metadata" in event:
            for k, v in event["metadata"].get("usage", {}).items():
                if isinstance(v, (int, float)):
                    turn.usage[k] = turn.usage.get(k, 0) + v

        elif "runtimeClientError" in event:
            turn.errors.append(event["runtimeClientError"].get("message", str(event)))

    return turn


def result_text(block: Block) -> str:
    """Best-effort flattening of a toolResult block's content into text."""
    out = []
    for part in block.result_parts:
        if isinstance(part, list):
            parts = part
        elif isinstance(part, dict) and isinstance(part.get("content"), list):
            parts = part["content"]
        else:
            parts = [part]
        for p in parts:
            if isinstance(p, dict) and "text" in p:
                out.append(p["text"])
            elif isinstance(p, dict) and "json" in p:
                out.append(json.dumps(p["json"]))
            else:
                out.append(json.dumps(p, default=str))
    return "".join(out)


# --------------------------------------------------------------------------------------
# Running inline tools
# --------------------------------------------------------------------------------------

def confirm_write(name: str, args: dict) -> bool:
    """Human-in-the-loop gate for tools that change data. Defaults to No."""
    print(f"\n\n⚠️  The agent wants to run a WRITE action: {name}")
    for k, v in args.items():
        print(f"     {k}: {v}")
    if not sys.stdin.isatty():
        print("   (no interactive terminal: declining)")
        return False
    return input("   Allow this? [y/N] ").strip().lower() == "y"


async def run_inline_tool(mcp: Client, name: str, args: dict) -> tuple[str, str]:
    """Returns (status, text) where status is 'success' or 'error'."""
    if name in config.WRITE_TOOLS and not confirm_write(name, args):
        return "error", ("DECLINED: the human reviewer did not approve this action. "
                         "It was not executed. Do not retry; tell the user it was declined.")
    result = await mcp.call_tool(name, args)
    text = "".join(c.text for c in result.content if getattr(c, "text", None))
    return ("error" if result.is_error else "success"), text


def _summary(name: str, status: str, text: str) -> str:
    if status != "success":
        return f"{status}: {text[:120]}"
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return f"{len(text)} chars"
    if "total_matching" in data:
        more = f", next_offset={data['next_offset']}" if data.get("next_offset") is not None else ""
        return f"{data['returned']} of {data['total_matching']} rows{more}"
    if "sites" in data:
        return f"{len(data['sites'])} sites"
    return ", ".join(data)[:120]


# --------------------------------------------------------------------------------------
# The loop
# --------------------------------------------------------------------------------------

async def ask(question: str, verbose: bool = False) -> dict:
    state = config.load_harness_state()
    client = boto3.client("bedrock-agentcore", region_name=state["region"])
    session_id = str(uuid.uuid4())
    started = datetime.now(timezone.utc)
    run_id = started.strftime("%Y%m%dT%H%M%SZ") + "-" + re.sub(r"[^a-z0-9]+", "-", question.lower())[:40].strip("-")
    RUNS_DIR.mkdir(exist_ok=True)
    raw_path = RUNS_DIR / f"{run_id}.events.jsonl"

    inline_names = {"list_sites", "get_site", "query_observations", "flag_site", "list_flags"}
    evidence: dict[str, Any] = {
        "run_id": run_id, "question": question, "session_id": session_id,
        "harness": state["harnessName"], "model": config.MODEL_ID,
        "started_at": started.isoformat(), "steps": [], "answer": "",
        "stop_reasons": [], "usage": {}, "errors": [],
    }
    answered_ids: set[str] = set()
    all_blocks: list[Block] = []

    def on_text(t: str) -> None:
        print(t, end="", flush=True)

    server = StdioServerParameters(command=config.MCP_SERVER_COMMAND[0], args=config.MCP_SERVER_COMMAND[1:])
    # open() is a plain (sync) context manager, so it can't share the `async with`.
    async with Client(server) as mcp:
      with open(raw_path, "w") as raw_log:
        messages = [{"role": "user", "content": [{"text": question}]}]
        for handoff in range(MAX_HANDOFFS + 1):
            t0 = time.time()
            try:
                resp = client.invoke_harness(harnessArn=state["harnessArn"],
                                             runtimeSessionId=session_id, messages=messages)
                turn = read_stream(resp["stream"], raw_log, on_text)
            except (BotoCoreError, ClientError) as e:
                # e.g. an AccessDenied inside the harness arrives as an EventStreamError.
                print(f"\n❌ {type(e).__name__}: {e}")
                evidence["errors"].append(f"{type(e).__name__}: {e}")
                break
            all_blocks += turn.blocks
            evidence["stop_reasons"] += turn.stop_reasons
            evidence["errors"] += turn.errors
            for k, v in turn.usage.items():
                evidence["usage"][k] = evidence["usage"].get(k, 0) + v

            # Record harness-executed tools (Code Interpreter) and their results.
            for b in turn.blocks:
                if b.kind == "toolResult" and b.tool_use_id:
                    answered_ids.add(b.tool_use_id)
            for b in turn.blocks:
                if b.kind == "toolUse" and b.tool_name not in inline_names:
                    res = next((r for r in turn.blocks if r.kind == "toolResult" and r.tool_use_id == b.tool_use_id), None)
                    output = result_text(res) if res else None
                    evidence["steps"].append({"tool": b.tool_name, "executed_by": "harness",
                                              "input": b.tool_input(), "output": output})
                    print(f"\n  ⚙️  {b.tool_name} ran in AWS" + (f"\n{json.dumps(b.tool_input(), indent=2)[:1500]}\n  ↳ {str(output)[:800]}" if verbose else ""))

            if turn.errors:
                print(f"\n❌ harness error: {turn.errors}")
                break
            if not turn.stop_reasons or turn.stop_reasons[-1] != "tool_use":
                break

            # The harness is waiting on our inline functions.
            pending = [b for b in turn.blocks
                       if b.kind == "toolUse" and b.tool_name in inline_names
                       and b.tool_use_id not in answered_ids]
            if not pending:
                print("\n⚠️ stopReason=tool_use but no pending inline call found; stopping.")
                break
            results = []
            for b in pending:
                args = b.tool_input() if isinstance(b.tool_input(), dict) else {}
                t1 = time.time()
                status, text = await run_inline_tool(mcp, b.tool_name, args)
                summary = _summary(b.tool_name, status, text)
                print(f"\n  🔧 {b.tool_name}({json.dumps(args)[:200]}) → {summary}")
                evidence["steps"].append({"tool": b.tool_name, "executed_by": "relay (local MCP)",
                                          "input": args, "status": status, "output": text,
                                          "seconds": round(time.time() - t1, 2)})
                answered_ids.add(b.tool_use_id)
                results.append({"toolResult": {"toolUseId": b.tool_use_id,
                                               "content": [{"text": text}], "status": status}})
            messages = [{"role": "user", "content": results}]
        else:
            print(f"\n⚠️ stopped after {MAX_HANDOFFS} handoffs")

    # Final answer = text of the last assistant message that has any text.
    texts = [b for b in all_blocks if b.kind == "text" and b.role == "assistant" and b.text.strip()]
    if texts:
        evidence["answer"] = texts[-1].text
    # Guard: a model with no (or ignored) tools can write a fake tool call and fake
    # data as plain text, then answer confidently from it. Flag it loudly.
    all_text = "".join(b.text for b in texts)
    evidence["warnings"] = []
    if re.search(r"<tool_(call|response|use|result)>", all_text):
        evidence["warnings"].append("FABRICATED_TOOL_CALL: answer contains tool-call markup "
                                    "written as text; its data did not come from our tools.")
    if not evidence["steps"]:
        evidence["warnings"].append("NO_TOOL_CALLS: the agent answered without calling any tool.")
    for w in evidence["warnings"]:
        print(f"\n🚩 {w}")

    evidence["finished_at"] = datetime.now(timezone.utc).isoformat()
    evidence_path = RUNS_DIR / f"{run_id}.json"
    evidence_path.write_text(json.dumps(evidence, indent=2, default=str) + "\n")
    print(f"\n\n📁 evidence: {evidence_path.relative_to(config.REPO_ROOT)}"
          f"  (raw events: {raw_path.name})  usage: {evidence['usage']}")
    return evidence
