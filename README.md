# Highlighter observations agent

A prototype agent that answers plain-English questions about Highlighter observation
data (hazards, issues and assets detected in CCTV, fixed-camera and drone imagery),
for example:

> Which sites had the most unresolved high-severity hazards last month, and is it getting worse?

The agent runs on **AWS Bedrock AgentCore** (harness + Code Interpreter) with Claude
Sonnet 4.6. It reads data through a **mock Highlighter API exposed as MCP tools**, does
its counting and trends in the Code Interpreter sandbox, and answers with its evidence:
the data it used, the code it ran and the output. Writing data (flagging a site) needs a
human to confirm.

Built with Claude Code; the full session is in [docs/transcript.md](docs/transcript.md),
and a short write-up (how it works, how it was tested, what went wrong) is in
[docs/WRITEUP.md](docs/WRITEUP.md).

## How it works

```
 you ── python -m agent.ask "question"
         │
         ▼
 relay (agent/relay.py, runs locally) ──invoke_harness──▶ AgentCore harness (AWS)
         ▲                                                  │  Claude Sonnet 4.6
         │  harness pauses on a data tool call              │  managed agent loop
         │  ("inline function") and hands it to the relay   │
         │                                                  ├─▶ Code Interpreter (AWS sandbox)
         ▼                                                  │     counts, trends, charts
 MCP server (highlighter/mcp_server.py, local, stdio)       │
         │                                                  ▼
         ▼                                        answer + evidence streamed back
 mock Highlighter API (highlighter/mock_api.py) → data/*.json
```

- **Harness**: AWS runs the agent loop from configuration (model, system prompt, tools,
  limits). No hand-written loop.
- **Tools as inline functions**: the data tools aren't hosted anywhere. When the model
  calls one, the harness pauses and returns the call to the local relay, which runs it
  against the local MCP server and sends the result back. This avoids exposing an MCP
  endpoint to the internet (and the Cognito/Gateway setup that would need), gives a
  natural place for the human confirmation on writes, and means every data call is
  logged locally.
- **Code Interpreter** is AgentCore's managed sandbox. It has no access to the tools or
  the internet; the model passes the rows it fetched into its code.
- **Evidence**: each question writes `runs/<time>-<question>.json` (every tool call with
  its input and output, the code run and its output, the answer, token usage) plus the
  raw event stream. `runs/` is gitignored.

## Repository layout

```
flake.nix, flake.lock     Nix dev shell (everything the project needs)
data/                     generated mock dataset (sites, observations, metadata)
scripts/                  dataset generator (generate_dataset.py + datagen/)
highlighter/              tools layer
  interface.py              HighlighterAPI: the contract any backend meets
  schema.py, validation.py  allowed values, input checks (shared)
  mock_api.py               MockHighlighterAPI: the only mock part
  mcp_server.py             MCP tools over any HighlighterAPI
agent/                    the agent
  config.py                 model, limits, names
  system_prompt.md          the agent's instructions
  create_harness.py         create/update the harness (dry run by default)
  relay.py, ask.py          run a question, handle tool calls, save evidence
infra/iam/                least-privilege IAM policy templates
tests/                    API and MCP server tests
docs/transcript.md        Claude Code session transcript
```

## Setup

### 1. Nix dev shell

Needs Nix with flakes enabled (developed on WSL2 Ubuntu 24.04, multi-user install).

```bash
nix develop
```

This gives Python 3.12 with `mcp`, `boto3`, `pandas`, `pytest`, plus `awscli2` and `jq`,
pinned by `flake.lock`. Nothing is installed globally. Everything below runs inside it.

### 2. Tests (no AWS needed)

```bash
python -m pytest -q          # 24 tests: mock API + MCP server
```

### 3. AWS

You need an AWS account with Claude Sonnet 4.6 available on Bedrock in `us-east-1`
(the account must have submitted Anthropic's use-case form).

Two identities, kept separate:

| Identity | Can do |
|---|---|
| Dev user (runs the code) | Bedrock + AgentCore, plus **only** `iam:PassRole` on the harness role, only to AgentCore |
| Harness execution role (AgentCore assumes it) | Call one model (Sonnet 4.6 via the `us.` inference profile), use the AWS-managed Code Interpreter, write its own logs/traces/metrics. Nothing else |

Create the role and the dev user's `PassRole` policy **once, with an admin identity**,
from the templates in `infra/iam/` (they use `<ACCOUNT_ID>` / `<REGION>` placeholders):

```bash
export ACCOUNT_ID=<account id> REGION=us-east-1 ADMIN_PROFILE=<admin profile>
mkdir -p infra/iam/rendered            # gitignored
for f in harness-exec-trust harness-exec-policy dev-user-passrole; do
  sed -e "s/<ACCOUNT_ID>/$ACCOUNT_ID/g" -e "s/<REGION>/$REGION/g" \
    infra/iam/$f.json > infra/iam/rendered/$f.json
done
aws iam create-role --profile $ADMIN_PROFILE --role-name role_for_agentcore \
  --assume-role-policy-document file://infra/iam/rendered/harness-exec-trust.json
aws iam put-role-policy --profile $ADMIN_PROFILE --role-name role_for_agentcore \
  --policy-name role_for_agentcorePolicy --policy-document file://infra/iam/rendered/harness-exec-policy.json
aws iam put-user-policy --profile $ADMIN_PROFILE --user-name <dev user> \
  --policy-name harness_exec_policy --policy-document file://infra/iam/rendered/dev-user-passrole.json
```

`dev-user-passrole.json` names the role `role_for_agentcore`; change both if you use a
different name.

### 4. Create the harness

As the dev user:

```bash
export HIGHLIGHTER_HARNESS_ROLE_ARN=arn:aws:iam::<account id>:role/role_for_agentcore
python -m agent.create_harness            # print the config, change nothing
python -m agent.create_harness --apply    # create (or update) it; takes a few minutes
```

The harness ARN is saved to `.harness.local.json` (gitignored).

## Usage

```bash
python -m agent.ask "Which sites had the most unresolved high-severity hazards last month, and is it getting worse?"
python -m agent.ask -v "..."     # also print the code the agent ran and its output
```

Tool calls print as they happen (`🔧 query_observations({...}) → 17 of 17 rows`). If the
agent calls `flag_site`, the relay shows the site, priority and reason and asks
`Allow this? [y/N]`; the default is no, and with no interactive terminal it declines.
Flags are written to `data/runtime/flags.jsonl` (gitignored).

## The mock dataset

`data/` is generated by `python scripts/generate_dataset.py`: deterministic (fixed seed
and a fixed "now" of 2026-11-07, so "last month" is always October 2026), 12 sites and
3,775 observations from May to November 2026.

Each observation has a site, time, source (CCTV / fixed camera / drone), category
(hazard / issue / asset), type, severity, detector confidence and status (open /
acknowledged / resolved / dismissed). The background is realistic noise: random daily
arrivals, per-site severity, resolution delays by severity, low-confidence false
positives dismissed by a human, drones flying one day a week.

On top of that, known patterns were planted so the agent's answers can be checked:

| Site | Pattern |
|---|---|
| S01 Northgate Substation | Getting worse: high/critical hazards ~5/month → 28 in October; open backlog 5 → 9 → 21 (Aug–Oct) |
| S02 Riverside Solar Farm | Improving |
| S03 Eastport Container Terminal | Most observations, mostly low severity |
| S05 Westfield Construction | Many hazards, fixed quickly |
| S08 Granite Ridge Quarry | Steadily high severity and backlog, not trending |
| S09 Harbour Fuel Depot | One-off spike of 14 incidents, 10–20 October |
| **Traps** | |
| S06 Lakeside Water Treatment | Cameras offline 15 Sep – 31 Oct: zero observations is missing data, not "safe" |
| S12 Southbank Pumping Station | Onboarded 1 September: no earlier baseline |
| S10 Meadow Hill Wind Farm | Drone-only, weekly batches |

The generator logic is in `scripts/datagen/` (site profiles and incidents in `sites.py`).

## Tools

| Tool | Type | Notes |
|---|---|---|
| `list_sites` | read | includes `onboarded_at`, `data_as_of` |
| `get_site` | read | individual cameras/drones |
| `query_observations` | read | filters by site, category, severity, status, type, date range, confidence; paged with `total_matching` / `next_offset`; returns rows, not aggregates |
| `list_flags` | read | |
| `flag_site` | **write** | human confirmation in the relay |

The API filters but doesn't calculate: analysis happens in the sandbox. Invalid filter
values return an error listing the allowed values (rather than an empty result the agent
could read as "zero hazards"), and every response carries `data_as_of` so relative dates
are anchored to the data.

## Access and secrets

- No credentials in the repo; the role ARN comes from an
  environment variable; files containing the account id (`.harness.local.json`,
  `infra/iam/rendered/`) are gitignored.
- The harness only sees its six tools (`allowedTools`); the built-in `shell` and
  `file_operations` tools are off. Harness memory is disabled (each question is its own
  session).
- The execution role is limited to one model profile and the managed Code Interpreter.
  Nobody is granted `bedrock-agentcore:InvokeAgentRuntimeCommand`, which would allow
  shell commands in the session outside the model and `allowedTools`.
- The dev user has broad Bedrock/AgentCore managed policies, which is fine for a
  prototype; production would use a scoped policy.

## Making it real

- **Data**: implement `HighlighterAPI` (`highlighter/interface.py`) against Highlighter's
  real API, e.g. `HttpHighlighterAPI`, and pass it to `build_server()`. The MCP server,
  harness and relay don't change. Needs an API client, credentials (AgentCore Identity or
  Secrets Manager, not env vars) and Highlighter's real status/severity vocabulary.
- **Hosting the tools**: for users other than the developer, run the same MCP server on
  AgentCore Runtime (`python -m highlighter.mcp_server --http` serves `0.0.0.0:8000/mcp`
  with a `/ping` health check), put AgentCore Gateway in front for auth, and switch the
  harness tools from inline functions to `agentcore_gateway`. `flag_site` would then
  need its confirmation moved to an inline function or a lifecycle hook.
- **Data into the sandbox**: today the model copies fetched rows into its code. That
  costs tokens and is where transcription errors could happen (in testing, all copied
  ids matched). With more data, add aggregate tools or write query results straight
  into the sandbox.

## Known limitations

- Large queries make the model copy many rows into one code call; the per-call output
  limit was raised to 16,384 tokens for this.
- Charts are drawn inside the sandbox but the image isn't returned; the agent should
  show results as text tables.
- The agent can still be confidently wrong in its reasoning (see [the write-up](docs/WRITEUP.md)): it treated
  a camera outage as an improvement and used a trend measure that leans towards
  "getting worse".

## Teardown

```bash
aws bedrock-agentcore-control delete-harness --harness-id <id from .harness.local.json>
aws iam delete-user-policy --profile $ADMIN_PROFILE --user-name <dev user> --policy-name harness_exec_policy
aws iam delete-role-policy --profile $ADMIN_PROFILE --role-name role_for_agentcore --policy-name role_for_agentcorePolicy
aws iam delete-role --profile $ADMIN_PROFILE --role-name role_for_agentcore
```

Then deactivate the dev user's access key.
