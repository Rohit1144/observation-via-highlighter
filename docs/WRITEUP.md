# Write-up

## How it works

A question goes to an **AgentCore harness** running Claude Sonnet 4.6. AWS runs the agent
loop from configuration: model, system prompt, tools and limits. The harness has two kinds
of tools:

- **Highlighter data tools** (`list_sites`, `query_observations`, `flag_site`, ...) from a
  mock Highlighter API wrapped in an MCP server. They're registered as *inline functions*:
  when the model calls one, the harness pauses and a small local relay runs it against the
  MCP server and sends the result back. Nothing is exposed to the internet, and every
  data call is logged.
- **AgentCore Code Interpreter**, a managed sandbox where the agent does the counting,
  trends and charts.

The answer comes back with its evidence (tool calls and filters, rows returned, code run,
output), and each run is saved to an evidence file. `flag_site` is the one write action;
the relay asks a human to confirm it, and defaults to no.

The mock API sits behind an interface (`HighlighterAPI`). Making it real means
implementing that interface against Highlighter's API; the MCP server and agent stay the
same.

## How I tested it

- **Tools against the raw data.** 24 tests check the mock API and MCP server against
  numbers read directly from the dataset (filters, month boundaries, paging, error
  messages, flags). If the agent gets a number wrong, it's the agent, not the tools.
- **A dataset with known answers.** The generated data has planted patterns (one site
  clearly getting worse, one improving, one noisy but low-severity, a one-off spike) and
  traps (a site whose cameras were offline for six weeks, a site added part-way through).
- **The agent against my own calculation.** For the example question I recomputed the
  answer in pandas and compared. I also checked that every observation id the agent
  typed into its code was one the tools had actually returned.
- **Questions the data can't answer**, such as "what caused the hazards at Northgate?",
  and a find-and-flag request to exercise the confirmation step.

## What it got right, and what it got wrong

On the example question, the agent's counts matched mine exactly, and all 29 rows it
copied into its code were correct. It stated its definitions (what counts as high
severity and unresolved) and correctly identified the worst site. For the "cause"
question it said the data has no cause field, though only after pulling all 153 rows for
that site, which wasted tokens.

Where it went wrong, it was confident about it:

- It reported the site with the camera outage as **improving** (2 → 0), even with an
  instruction in the prompt to check coverage.
- Its trend measure ("raised this month and still open") naturally rises for recent
  months, so it overstated "getting worse" for one site.
- It said it had produced a chart. The image never left the sandbox.
- When the tool configuration was wrong (see below), it **made up a tool call and five
  sites that don't exist**, then answered with a neat "Evidence" section. I added a check
  to the relay that flags this.

None of this was fixed in the prompt, since the brief asked for a prototype; they're
documented as findings.

## What the assistant (Claude Code) got wrong, and what surprised me

- It didn't know about **AgentCore harness** (released mid-2026) and first proposed
  writing the agent loop by hand. I pointed it out; it read the docs and switched.
- It removed Memory permissions from AWS's sample policy, assuming memory wasn't used.
  The harness **creates managed memory by default**, so the first run failed with
  AccessDenied. We turned memory off.
- It wrote `allowedTools` with plain tool names. Those only match *built-in* tools, so
  the model got no tools at all, which caused the fabricated answer above. I found the
  fix (`@name`) in the AWS console's warning.
- Smaller ones: an async/sync mix-up in the relay, and `update_harness` taking a
  different shape from `create_harness` for some fields.
- It also caught things I would have missed: the original `.gitignore` had leading
  spaces, so `.env` wasn't actually ignored, and the IAM policy needed model ARNs without
  an account id.

What surprised me most was how *plausible* the wrong answers were. The fabricated one
looked as complete as a real one. The only reliable defence was checking against numbers
I computed myself, and watching small signals like the token count (678 input tokens
meant no tool definitions had been sent).

## Limitations

- The model copies fetched rows into its code. It worked here (no transcription errors),
  but it's expensive and doesn't scale. Aggregate tools or loading data straight into
  the sandbox would fix it.
- Charts don't come back as images.
- For other users, the tools would be hosted (AgentCore Runtime behind Gateway) rather
  than run through a local relay.
- Nix runs on WSL, not NixOS.
