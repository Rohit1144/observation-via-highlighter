"""Create (or update) the AgentCore harness for the Highlighter agent.

Default is a dry run: print the exact configuration that would be sent, change nothing.
    python -m agent.create_harness            # show config
    python -m agent.create_harness --apply    # create or update in AWS

Tools given to the harness:
- the AWS-managed Code Interpreter (runs in AWS, for counts/trends/charts)
- our MCP server's tools as *inline functions*: the harness pauses on each call and
  hands it to our relay, which runs it against the local MCP server. The definitions
  are read from the MCP server itself, so the harness and server can't drift apart.

`allowedTools` lists exactly those tools (as "@name"), which leaves out the built-in
`shell` and `file_operations` (they're allowed by default).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import time

import boto3
from mcp import Client

from highlighter.mcp_server import build_server

from . import config

SYSTEM_PROMPT_FILE = config.REPO_ROOT / "agent" / "system_prompt.md"
# Fields that UpdateHarness expects as {"optionalValue": ...} (checked against botocore).
UPDATE_WRAPPED_FIELDS = {"memory", "authorizerConfiguration", "environmentArtifact"}


async def _mcp_tools() -> list:
    # In-process client: we only need the tool definitions, not a running server.
    async with Client(build_server()) as client:
        return (await client.list_tools()).tools


def inline_function_tools() -> list[dict]:
    return [
        {
            "type": "inline_function",
            "name": t.name,
            "config": {"inlineFunction": {
                # Collapse docstring indentation/newlines: same text, fewer tokens.
                "description": " ".join((t.description or "").split()),
                "inputSchema": t.input_schema,
            }},
        }
        for t in asyncio.run(_mcp_tools())
    ]


def harness_config() -> dict:
    """Everything except harnessName/executionRoleArn/harnessId, shared by create and update."""
    tools = [{"type": "agentcore_code_interpreter", "name": config.CODE_INTERPRETER_TOOL}]
    tools += inline_function_tools()
    return {
        "model": {"bedrockModelConfig": {
            "modelId": config.MODEL_ID,
            "maxTokens": config.MODEL_MAX_TOKENS,
            "temperature": config.TEMPERATURE,
        }},
        "systemPrompt": [{"text": SYSTEM_PROMPT_FILE.read_text()}],
        "tools": tools,
        # A bare name only matches *built-in* tools (shell, file_operations). Tools we
        # declare (inline functions, code interpreter) need the "@" prefix; bare names
        # silently match nothing and the model gets no tools at all.
        "allowedTools": [f"@{t['name']}" for t in tools],
        "truncation": {"strategy": "sliding_window"},
        # Off: harness memory persists conversations *across* sessions, and every
        # question here is its own session. Without this, AgentCore creates a managed
        # memory resource by default, which the role has no permissions for.
        "memory": {"disabled": {}},
        "maxIterations": config.MAX_ITERATIONS,
        "maxTokens": config.MAX_TOKENS,
        "timeoutSeconds": config.TIMEOUT_SECONDS,
    }


def find_existing(client) -> dict | None:
    token = None
    while True:
        page = client.list_harnesses(**({"nextToken": token} if token else {}))
        for h in page.get("harnesses", []):
            if h["harnessName"] == config.HARNESS_NAME:
                return h
        token = page.get("nextToken")
        if not token:
            return None


def wait_until_ready(client, harness_id: str, timeout_s: int = 600) -> dict:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        h = client.get_harness(harnessId=harness_id)["harness"]
        print(f"  status: {h['status']}")
        if h["status"] == "READY":
            return h
        if h["status"].endswith("FAILED"):
            raise SystemExit(f"Harness {h['status']}: {h.get('failureReason')}")
        time.sleep(10)
    raise SystemExit("Timed out waiting for the harness to become READY.")


def summarise(cfg: dict) -> str:
    """Readable view of the config: full JSON, but with long tool schemas trimmed."""
    view = json.loads(json.dumps(cfg))
    for t in view["tools"]:
        fn = t.get("config", {}).get("inlineFunction")
        if fn:
            props = list(fn["inputSchema"].get("properties", {}))
            fn["inputSchema"] = f"<{len(props)} params: {', '.join(props)}>"
            fn["description"] = fn["description"][:90] + ("..." if len(fn["description"]) > 90 else "")
    view["systemPrompt"] = f"<{len(cfg['systemPrompt'][0]['text'])} chars from agent/system_prompt.md>"
    return json.dumps(view, indent=2)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--apply", action="store_true", help="create/update the harness in AWS")
    parser.add_argument("--full", action="store_true", help="print the full config, untrimmed")
    args = parser.parse_args()

    cfg = harness_config()
    print(json.dumps(cfg, indent=2) if args.full else summarise(cfg))
    if not args.apply:
        print("\nDry run only. Re-run with --apply to create/update the harness.")
        return

    role_arn = config.execution_role_arn()
    client = boto3.client("bedrock-agentcore-control", region_name=config.REGION)
    existing = find_existing(client)
    if existing:
        print(f"\nUpdating harness {existing['harnessId']} ...", flush=True)
        # UpdateHarness wraps these fields as {"optionalValue": ...} (so they can also be
        # cleared); CreateHarness takes them bare.
        update_cfg = {k: ({"optionalValue": v} if k in UPDATE_WRAPPED_FIELDS else v)
                      for k, v in cfg.items()}
        client.update_harness(harnessId=existing["harnessId"], executionRoleArn=role_arn, **update_cfg)
        harness_id = existing["harnessId"]
    else:
        print(f"\nCreating harness {config.HARNESS_NAME} ...", flush=True)
        h = client.create_harness(harnessName=config.HARNESS_NAME, executionRoleArn=role_arn, **cfg)
        harness_id = h["harness"]["harnessId"]

    h = wait_until_ready(client, harness_id)
    config.save_harness_state({
        "harnessId": h["harnessId"], "harnessArn": h["arn"],
        "harnessName": h["harnessName"], "region": config.REGION,
    })
    print(f"READY. Saved to {config.HARNESS_STATE_FILE.name}")


if __name__ == "__main__":
    main()
