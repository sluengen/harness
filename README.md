# harness

📖 **[Read the one-page guide →](https://sluengen.github.io/harness/)** — the operating model, the verbs, and the guidance at a glance. (This README stays the canonical text; the page is its visual companion.)

An **evidence layer for agent-driven development**: a small set of deterministic,
audited verbs an agent calls while it drives a ticket end-to-end. The agent owns
the judgement work; the harness owns the invariants that keep that work honest.

> Let the agent orchestrate the messy work; make the harness own the evidence.

An AI agent does the judgement work — the code, the fixes, the decisions. The
harness owns only what an audit trail depends on:

- **SHA-bound review verdicts** — a `pass` binds to the exact git SHA it reviewed,
  and the `close` gate refuses to merge anything a fresh review didn't cover.
- **An append-only ledger** — each run's lifecycle (`start` / `design` / `review` / `close`)
  is a row plus an event log in SQLite; that ledger *is* the audit trail.
- **Builder / recorder separation** — the agent that promises delivery is not the
  one that records it, which keeps the canonical record honest.
- **Crash reclamation** — a run whose orchestrator dies mid-flight is detected by a
  time heuristic and reclaimed, so a stalled ticket never wedges the queue.
- **Versioned guidance distribution** — the skills, agents, and commands that
  encode *how work happens here* are version-stamped and distributed from this repo.

It is **dogfooded on its own development**: every change to the harness is built by
running the harness on a ticket, through the same `start → design → review → close` verbs it
ships.

**Status:** verb model (`start` / `design` / `review` / `close`). The earlier deterministic
YAML workflow engine was retired in CAL-574; this README and [`SPEC.md`](./SPEC.md)
§1–2 describe the current model.

## Is this turnkey? No — it's dogfood infrastructure

**This is infrastructure one maintainer runs on their own machine, published to
read and adapt — not a turnkey product.** It assumes a particular setup — an
agent host, a GitHub tracker, this repo's own branch model — and nothing here is
packaged for installation: there is no image, no wrapper, and no console script
to put on PATH (ADR 0015). Treat the whole repo as a worked example to **adapt to
taste**, not a dependency to install unchanged. The concepts — the SHA-bound
gate, the builder/recorder split — are the portable part; the plumbing around
them is not.

## What it does

A single agent session **orchestrates and implements** a ticket — it reads the ticket, writes the code and tests, decides how to fix a review finding, and when to re-review. The harness owns only the **durable record and the gate**: four verbs over a SQLite ledger, and a `close` gate that refuses to merge anything that wasn't reviewed.

- **`start`** — validate the ticket, transition it to *In Progress*, create an isolated git worktree off the base branch (default `dev`), and open a `runs` ledger row.
- **`design`** — on a `complex` run, invoke Claude/Opus by default or native Codex with `--engine codex` in a fresh context, and record the resulting design on the ticket, in the ledger, and on stdout. Simpler assurance levels skip the engine entirely. Claude receives one scoped output-file grant; Codex receives no model-writable path while its CLI captures the final response.
- **`review`** — run the review engine (**Claude by default**; native Codex with `--engine codex`, host-only until ADR 0013's #314 seccomp work lands) against the worktree HEAD and record a verdict (`pass` / `fail` / `defer`) **bound to that git SHA**. Add `--no-fallback` when Claude must never be invoked.
- **`close`** — enforce the gate (a `start` exists **and** a `verdict=pass` whose reviewed SHA equals the current HEAD), then commit / merge / push, transition the ticket to *Done*, and finalize the run.

The agent does what only an agent can do (judgement, code, deciding how to fix a finding). Everything the audit trail depends on — opening the run, binding a review to a SHA, gating the merge — is deterministic verb code.

For the full architectural picture and the "why" of every decision, read [`SPEC.md`](./SPEC.md) (§1–2) and the accepted proposal [`specs/proposals/harness-as-tool.md`](./specs/proposals/harness-as-tool.md). For the verb contract the agent drives, read [`commands/harness.md`](./commands/harness.md).

## The model: one execution path, two triggers

There is **one** execution model — an agent session running `start → design → implement → review → (fix → review)* → close` — designed for **two** trigger slots, one built today and one **design-only**:

- a **human**, via the `/harness run <ISSUE-ID>` command in a supported agent host (the built trigger), or
- **Hermes**, the autonomous dispatcher that *would* occupy the same trigger slot — **design-only**, not built: the launcher was removed in CAL-712 and the design is retired to [`specs/retired/hermes-orchestration.md`](./specs/retired/hermes-orchestration.md).

By design, either trigger produces the identical execution path. The agent runtime is *per-session* (one agent per ticket, where context lives); each verb is *per-call*, invoked from the checkout.

```
trigger ( /harness run CAL-42  |  Hermes† )
   │  launches an agent session for the ticket
   ▼
agent session — orchestrator + implementer
   start → design → [implement] → review → (fix → review)* → close
   │  shells out to verbs
   ▼
harness verbs:  start / design / review / close   +   SQLite ledger   +   close gate
```

† Hermes is **design-only** — not a built trigger. Today only `/harness run` (a human) launches the session; the Hermes slot is retired to [`specs/retired/hermes-orchestration.md`](./specs/retired/hermes-orchestration.md).

### Routing discipline

The ledger is a complete audit trail **only if nothing hand-rolls a `git merge` / `push` or a Linear mutation** for the run lifecycle. Every git and ticket state transition goes through a verb; `close` validates against the ledger as a backstop. A gate refusal is structured (`no_run` / `dirty_worktree` / `no_passing_review` / `stale_review`) and is the gate doing its job — never worked around.

## Quickstart

The honest minimum: clone it and run the tests to see the verbs and the gate
exercised. No turnkey install is promised — to actually *drive* tickets you need
the operator setup under [Install](#install) and [Authentication](#authentication).

```bash
git clone https://github.com/sluengen/harness.git harness
cd harness
uv sync --extra dev          # resolve the dev dependency group (needs uv)
uv run --extra dev pytest    # the full gate: unit + integration tests
```

A verb loop, end to end, is four commands — you (or an agent) do the implementing
in between:

```bash
harness start CAL-42                      # open the run: worktree + ledger row + ticket → In Progress
harness design --run-id <run_id>          # design engine records the change spec's Design section
# ... write code + tests in the worktree, test-first ...
harness review --run-id <run_id>          # a verdict bound to the current HEAD; fix + re-run until pass
harness close CAL-42 --run-id <run_id>    # gate → merge → ticket Done
```

## Install

### Local (development)

```bash
git clone git@github.com:sluengen/harness.git harness
cd harness
uv sync --extra dev
.venv/bin/harness version
```

### As a tool on PATH

```bash
uv tool install .          # installs the `harness` console script on PATH
harness version
```

## Authentication

Harness dispatches review through the Claude CLI by default. Claude auth follows Claude Code's conventions, not the raw Anthropic API:

| Path | Pricing | When |
|---|---|---|
| `claude /login` on the host, then run locally | Subscription | Local development. Credentials read from `~/.claude/` automatically — **no env var needed.** |
| Pass `CLAUDE_CODE_OAUTH_TOKEN` (from `claude setup-token`) | Subscription | CI and other non-interactive contexts. |
| `ANTHROPIC_API_KEY` env var | API rates (per-token) | Fallback when neither OAuth path is convenient. |

For strict native Codex-only operation, authenticate separately with `codex login` and verify it with `harness doctor --engine codex`. No Claude credential is required in that mode.

`LINEAR_API_KEY` lives in a gitignored `.env` at the target repo root; the verbs read it to fetch and transition the ticket. No Linear CLI is involved — all Linear interaction is via the GraphQL API inside the verbs.

## Driving a ticket

The `/harness run <ISSUE-ID>` command orchestrates the whole loop: it calls each verb, you (the session) write the code and tests inline in the worktree, and it acts on each verdict. Add `--codex-only` for the strict native mode. The loop, gate-refusal handling, and routing rules are documented in [`commands/harness.md`](./commands/harness.md).

By hand, the same loop is:

```bash
harness start CAL-42                      # opens the run; prints run_id + worktree_path
harness design --run-id <run_id>          # design engine records the change spec's Design section
cd <worktree_path>                        # implement: write code + tests, test-first
harness review --run-id <run_id>          # review verdict bound to HEAD; fix + re-run until pass
harness close CAL-42 --run-id <run_id>    # gate → commit / merge / push → ticket Done
```

Read commands inspect a run without changing state:

```bash
harness status <run_id>     # terminal-state summary
harness logs   <run_id>     # event timeline
harness events <run_id> --json
harness runs                # list recent runs
harness worktrees           # inspect / clean up run worktrees
harness doctor              # system health checks
```

Run `harness <verb> --help` for the full flag set.

## Using harness on harness (dog-fooding)

harness's own follow-on work flows through harness: each Linear ticket in the *Harness v3* project is built by running `/harness run <ISSUE-ID>`, which exercises the same `start → design → review → close` verbs the tool ships. If the work that improves the harness ships cleanly *through* the harness, self-hosting is validated empirically.

## Repository layout

```
harness/
├── agents/        ← agent role definitions (dev, reviewer, architect, stewards)
├── skills/        ← reusable skills (TDD, scope discipline, review discipline, …)
├── commands/      ← user-invocable slash commands (start, review, ship, /harness …)
├── harness/       ← the Python package: cli/ verbs, state/ ledger, worktree, codex dispatch
├── specs/         ← design specs (SPEC.md is the index); proposals/ for unconfirmed ideas
├── tests/         ← unit + integration tests
├── scripts/       ← verify gate (scripts/verify.sh) and tooling
├── CONTEXT.md     ← agent-facing repo context (read first)
├── SPEC.md        ← design specification (the "why")
└── CLAUDE.md      ← project process for Claude Code
```

`agents/`, `skills/`, `commands/` are agent-agnostic (plain markdown). Claude Code sees them via symlinks under `.claude/`.

## Tech stack

Python 3.11+ · Pydantic 2 · Typer · `aiosqlite` · `anthropic` SDK · `claude_agent_sdk` · Codex CLI · pytest · ruff · mypy · uv

## Related

- **Design ancestry:** Inspired by [Archon](https://github.com/coleam00/Archon) (worktree-per-run, event log) and Anthropic's "build skills, not agents" guidance. Greenfield Python rewrite, not a fork.
- **Read first:** [`CONTEXT.md`](./CONTEXT.md) (agents) · [`SPEC.md`](./SPEC.md) §1–2 (design) · [`commands/harness.md`](./commands/harness.md) (verb contract).

## Contributing & security

Issues and pull requests are welcome and handled on a **best-effort** basis — this
is a single-maintainer, dogfood project. See [`CONTRIBUTING.md`](./CONTRIBUTING.md)
for the contribution stance. To report a security issue, do **not** open a public
issue — follow [`SECURITY.md`](./SECURITY.md) to disclose it privately.

## License

Two licences, split along what gets installed where:

- **The engine** — the `harness` CLI and its tooling — is **AGPL-3.0-only**
  ([`LICENSE`](./LICENSE)). Use it for anything, including commercially; a
  derivative you distribute or run as a network service carries the same
  freedoms. It cannot be taken proprietary.
- **The guidance** — the skills, agents, commands, templates, hooks, process doc
  and settings the installer copies into *your* repo — is **MIT**
  ([`GUIDANCE-MIT.md`](./GUIDANCE-MIT.md)). Install it into any repository,
  including a closed-source one, and it encumbers nothing.

The boundary is not hand-maintained prose: the `files:` block of
[`registry.yaml`](./registry.yaml) *is* the set the installer copies out, so it
defines what is MIT, and a test holds the two in correspondence.

## Changelog

### 2026-07 — relicensed, and the unattended-run posture reaches consumers

- **Relicensed to a two-licence split** (CAL-1078, CAL-1080). The engine — the `harness` CLI and its tooling — is now **AGPL-3.0-only**; the guidance the installer copies into your repo (skills, agents, commands, templates, hooks, process doc, settings) is **MIT**, so it can be installed into a closed-source repo and encumber nothing. The boundary is the `files:` block of [`registry.yaml`](./registry.yaml), held in correspondence by a test; the inbound contribution grant covers patents and right-to-submit. See [`## License`](#license).
- **The unattended-run posture ships to consumers instead of only running here** (CAL-1081, CAL-1087, CAL-1108). The autonomous Build loop may make the tracker writes its own guidance instructs — deferring a not-yet-actionable ticket, reverting a run stranded by a dead orchestrator, running its own worktree housekeeping — each governed by a natural-language `autoMode.allow` allowlist clause that names the write and states the bound that makes it safe. The rule that *an instructed write which is refused is a configuration gap, not a bug in the skill* now travels in the distributed surface rather than living only in this repo's operator lore.

### 2026-06 — execution model inverted (verb model)

- **Orchestration boundary inverted** (proposal [`harness-as-tool`](./specs/proposals/harness-as-tool.md), accepted 2026-06-09). The harness no longer drives the build; a Claude session orchestrates and implements, calling three deterministic verbs.
- **Verbs:** `start` (open run + worktree + ticket → In Progress), `review` (Codex verdict bound to the reviewed SHA), `close` (gate → merge/push → ticket Done). Plus read commands: `status` / `logs` / `events` / `runs` / `worktrees` / `doctor` / `version`.
- **Ledger + gate:** a single SQLite `runs`/`events` ledger is the audit trail; `close` refuses any merge without a HEAD-bound passing review (`no_run` / `dirty_worktree` / `no_passing_review` / `stale_review`).
- **Deterministic YAML workflow engine retired** (CAL-574): the engine runner/executor/loop/retry, the node protocol, the workflow schema, and the `build*.yaml` workflows were deleted. Worktree lifecycle, Codex dispatch, the SQLite store, and the git/Linear helpers were re-homed as verb helpers.

### v1.0.0 (2026-05-27) — historical (deterministic engine)

The original release shipped the deterministic YAML workflow engine (workflow loader, derived state, six node types, three-layer retry, executor, runner), the `claude_agent_sdk` adapter, dynamic per-workflow CLI subcommands, the Docker image, and the AUTHORING.md author guide. It also shipped a Linear webhook intake — a sibling listener that fired the engine on ticket events. The engine was superseded by the verb model above and retired in CAL-574; the webhook listener lingered until it too was retired in CAL-601. This entry is kept for history.
