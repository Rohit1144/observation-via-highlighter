"""Agent settings, in one place.

Nothing account-specific is committed: the execution role ARN comes from an
environment variable, and the harness ARN (which contains the account id) is saved
to a gitignored local file after the harness is created.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# --- AWS ---------------------------------------------------------------------
REGION = os.environ.get("AWS_REGION", "us-east-1")

# The role AgentCore assumes to run the harness (infra/iam/). Set it with:
#   export HIGHLIGHTER_HARNESS_ROLE_ARN=arn:aws:iam::<account>:role/role_for_agentcore
ROLE_ARN_ENV = "HIGHLIGHTER_HARNESS_ROLE_ARN"

# Must match the workload-identity resource in infra/iam/harness-exec-policy.json
# (harness_highlighter_agent-*). Allowed: [a-zA-Z][a-zA-Z0-9_]{0,39}.
HARNESS_NAME = "highlighter_agent"

# Written by create_harness.py; holds the harness ARN/id. Gitignored.
HARNESS_STATE_FILE = REPO_ROOT / ".harness.local.json"

# --- Model ---------------------------------------------------------------------
# Sonnet 4.6 via the US cross-region inference profile. The execution role is only
# allowed to call this profile, so changing it also means updating the IAM policy.
MODEL_ID = "us.anthropic.claude-sonnet-4-6"
# Max output tokens per model call. Raised from 4096: copying ~150-200 rows into a
# single Code Interpreter call cut the response off mid-way.
MODEL_MAX_TOKENS = 16384
# 0 = as repeatable as possible, which matters when we compare answers against
# our own calculations across runs.
TEMPERATURE = 0.0

# --- Limits (cost control: a runaway loop stops instead of burning tokens) -----
# Model <-> tool round trips per question. A typical answer needs ~6-10:
# list_sites, 1-3 queries (plus paging), 1-3 Code Interpreter runs, final answer.
MAX_ITERATIONS = 20
# Total output-token budget for one invocation.
MAX_TOKENS = 20_000
TIMEOUT_SECONDS = 300

# --- Tools -----------------------------------------------------------------------
CODE_INTERPRETER_TOOL = "code_interpreter"
# How the relay starts our MCP server: as a child process over stdio.
MCP_SERVER_COMMAND = [sys.executable, "-m", "highlighter.mcp_server"]
# Tools that change data. The relay asks the human to confirm before running these.
WRITE_TOOLS = {"flag_site"}


def execution_role_arn() -> str:
    arn = os.environ.get(ROLE_ARN_ENV)
    if not arn:
        raise SystemExit(
            f"Set {ROLE_ARN_ENV} to the harness execution role ARN "
            "(see infra/iam/), e.g. arn:aws:iam::<account>:role/role_for_agentcore"
        )
    return arn


def load_harness_state() -> dict:
    if not HARNESS_STATE_FILE.exists():
        raise SystemExit("No harness yet. Run: python -m agent.create_harness --apply")
    return json.loads(HARNESS_STATE_FILE.read_text())


def save_harness_state(state: dict) -> None:
    HARNESS_STATE_FILE.write_text(json.dumps(state, indent=2) + "\n")
