# Harness — Design Specification

**Version:** 0.7
**Status:** Current for §1–2 (the verb model), §4 (core module design), §11 (CLI design), and §16 (non-goals). §3, §5–§10, §12–§15, and §17–§18 described the **retired** deterministic workflow engine — its structure and schema, its migration plan, its open questions, and its acceptance criteria; they are superseded and their bodies are re-homed to [`specs/retired/spec-engine.md`](specs/retired/spec-engine.md), leaving stub pointers here (see the banner at §3).
**Guiding principle:** *The harness is a set of deterministic, audited verbs an agent calls — not a pipeline that drives agents.*

> **Execution model (2026-06).** The harness no longer orchestrates the build. Per proposal [`harness-as-tool`](specs/proposals/harness-as-tool.md) (accepted 2026-06-09; decision recorded in [`specs/architecture-principles.md`](specs/architecture-principles.md)), a single Claude session orchestrates **and** implements, calling four deterministic verbs — `start` / `design` / `review` / `close` — over the SQLite ledger, with process enforcement as a gate inside `close`. §1–2 describe this model; §4 (modules) and §11 (CLI) describe its as-built surface. The deterministic workflow engine (§3, §5–§10, §12–§14) was retired in CAL-574, along with the §15 plan to migrate onto it, the §17 questions it deferred, and the §18 criteria it was to be graded against; that design is re-homed to [`specs/retired/spec-engine.md`](specs/retired/spec-engine.md), leaving stub pointers in those sections. §16 (non-goals) stays live — it is standing policy, not engine design.

---

## Spec index

Subsystem and integration specs live in `specs/`. Read the relevant file before touching a module.

**Current — as-built record (verb model):**

The `feature_specs` layer is on (`CONTEXT.md`), so the canonical as-built record of each current subsystem is a feature spec in `specs/features/` (`templates/feature.md` shape). Read the relevant feature spec before touching its subsystem.

| Feature spec | Covers |
|------|--------|
| [`specs/features/verb-model.md`](specs/features/verb-model.md) | The `start` / `review` / `close` lifecycle and the close gate (the central feature) |
| [`specs/features/run-ledger.md`](specs/features/run-ledger.md) | The SQLite ledger: `runs` / `events`, the open/closed lifecycle, the reviewed-SHA gate datum |
| [`specs/features/worktree-lifecycle.md`](specs/features/worktree-lifecycle.md) | The isolated worktree per run: create off base, cleanup policies, path/branch conventions |
| [`specs/features/cli-surface.md`](specs/features/cli-surface.md) | The fixed command surface: verbs, read/inspection, ops, exit codes, JSON |

**Design references (the model and deeper module detail the feature specs build on):**

The pure deterministic-engine docs (`workflow-schema`, `engine-executor`, `engine-loop`, `ai-node`, `script-node`) were re-homed to [`specs/retired/`](specs/retired/) in CAL-661; CAL-693 completed the relocation — `state-store.md` was **folded into** [`run-ledger.md`](specs/features/run-ledger.md) (the feature spec now carries the full schema reference); `build-workflow.md` / `cli.md` / `worktree-isolation.md` were re-homed to `specs/retired/`; and `hermes-orchestration.md` was **split** — its superseded control half was extracted to [`specs/retired/hermes-control-model.md`](specs/retired/hermes-control-model.md) (CAL-693), then its launcher / trigger / observability half was retired to [`specs/retired/hermes-orchestration.md`](specs/retired/hermes-orchestration.md) when the launcher scaffolding was removed (CAL-712). The one load-bearing piece that half documented — the `--repo` workspace allowlist — survives as `harness.workspace` (SPEC §4.9). All docstring cites were repointed.

| Spec | Covers |
|------|--------|
| [`specs/proposals/harness-as-tool.md`](specs/proposals/harness-as-tool.md) | The accepted model: invert the orchestration boundary; verbs + ledger + gate. **Read first.** |
| [`specs/architecture-principles.md`](specs/architecture-principles.md) | Architecture principles + the orchestration-inversion decision (cross-cutting decision record) |

The SQLite schema reference (full DDL, migrations) now lives in [`run-ledger.md`](specs/features/run-ledger.md) § Schema reference; the worktree helper reference is the feature spec [`worktree-lifecycle.md`](specs/features/worktree-lifecycle.md) (the engine-era `WorktreeNode` detail is the retired doc below).

**Superseded (retired deterministic engine — historical):**

| Spec | Covers | Status |
|------|--------|--------|
| [`specs/retired/hermes-control-model.md`](specs/retired/hermes-control-model.md) | Engine-era Hermes control model: responsibility boundary, Option A/B/C deployment decision, the Hermes→harness bridge interface | Control half superseded by `harness-as-tool` (CAL-693); the launcher/trigger half is `hermes-orchestration.md` below |
| [`specs/retired/hermes-orchestration.md`](specs/retired/hermes-orchestration.md) | Launcher / trigger runtime topology, the narrow control socket, the launch handle, and the read-only ledger observability a deferred Hermes dispatcher would consume | Launcher/trigger scaffolding removed (CAL-712); kept as **design, not built**. The `--repo` allowlist it documented survives as `harness.workspace` |
| [`specs/retired/build-workflow.md`](specs/retired/build-workflow.md) | Build workflow end-to-end (implement → review loop → merge phase) | Replaced by the `/harness run` verb loop; re-homed to `specs/retired/` (CAL-693) |
| [`specs/retired/cli.md`](specs/retired/cli.md) | Command surface, dynamic subcommands, exit codes, JSON output | Verb surface is now the contract (`commands/harness.md`); re-homed to `specs/retired/` (CAL-693) |
| [`specs/retired/worktree-isolation.md`](specs/retired/worktree-isolation.md) | Engine-era `WorktreeNode` reference: create + the retired cleanup policies | Live behaviour is `worktree-lifecycle.md`; `cleanup` machinery retired (CAL-693) |
| [`specs/retired/workflow-schema.md`](specs/retired/workflow-schema.md) | YAML workflow format, step keys, contracts, inputs | Engine retired (CAL-574); re-homed to `specs/retired/` (CAL-661) |
| [`specs/retired/engine-executor.md`](specs/retired/engine-executor.md) | Per-node execution, contract validation, state writes, snapshots | Engine retired (CAL-574); re-homed to `specs/retired/` (CAL-661) |
| [`specs/retired/engine-loop.md`](specs/retired/engine-loop.md) | Loop blocks, `until:` / `until_bash:`, retry rewind | Engine retired (CAL-574); re-homed to `specs/retired/` (CAL-661) |
| [`specs/retired/ai-node.md`](specs/retired/ai-node.md) | AI node dispatch, structured output, failure modes | Engine retired (CAL-574); re-homed to `specs/retired/` (CAL-661) |
| [`specs/retired/script-node.md`](specs/retired/script-node.md) | Script node subprocess, env, contract | Engine retired (CAL-574); re-homed to `specs/retired/` (CAL-661) |
| [`specs/retired/spec-engine.md`](specs/retired/spec-engine.md) | SPEC.md's own retired-engine sections — §3 (repo structure), §5–§10 (workflow schema, state, merge, identity, worktree, engine), §12–§14 (SQLite schema, Docker, steward example), §15 (migration plan), §17–§18 (open questions, success criteria) | Engine retired (CAL-574); SPEC.md bodies re-homed here, stub pointers left in place (CAL-1010, extended by #271) |

---

## 1. Mission

Give an agent a small set of **deterministic, audited verbs** to drive a ticket end-to-end, and **enforce that review happened** before anything merges. The agent owns *what work gets done and how* (orchestration + implementation); the harness owns *the durable record and the gate*.

Decouple judgement (the agent's: read the ticket, write the code, decide how to fix a finding, when to re-review) from the **audit trail and enforcement** (the harness's: a `runs` ledger, a review verdict bound to a git SHA, a `close` gate that refuses an unreviewed merge).

### Core principles

1. **The agent orchestrates; the harness records and gates.** There is **one execution model** — a Claude session runs `start → design → implement → review → (fix → review)* → close`, calling the verbs and doing the implementation itself — with **two triggers**: a human (`/harness run <ticket>`) or Hermes. The harness does not own the build loop and does not spawn its own implementing/reviewing agents.
2. **Determinism lives in the verbs, not the journey.** Each verb (`start`, `design`, `review`, `close`) is a one-shot, audited, reproducible operation over the ledger. The orchestration *between* verbs varies with the agent and is deliberately not reproducible — that trade buys full context retention (the agent that reads the ticket is the one that writes the code) and graceful degradation (a verb failure drops to manual driving).
3. **Enforcement is a gate inside `close`, bound to the reviewed tree.** `review` records the git SHA it reviewed; `close` refuses unless the ledger holds a `start` for the ticket **and** a `verdict=pass` whose reviewed SHA equals the worktree's current HEAD. This closes the stale-pass hole and makes unattended (Hermes-triggered) dispatch trustworthy — when no human is watching, the gate *is* the guarantee that nothing merges unreviewed.
4. **Routing discipline — every git/ticket mutation goes through a verb.** The ledger is a complete audit trail only if nothing hand-rolls a `git merge`/`push` or a Linear mutation for the run lifecycle. The `/harness run` skill forbids it; `close` validates against the ledger as a backstop.
5. **The verb surface is a public contract.** The harness is invoked by humans and by Hermes through the same verbs — the audited lifecycle verbs (`start` / `design` / `review` / `close`) alongside the read/inspection commands and the ops and maintenance verbs; the exact registered set is the §11 command surface, not re-listed here (so this principle cannot go stale the next time a verb is added). Stable flags, stable exit codes, stable JSON output, structured refusals. Each verb runs as a one-shot container exactly as the human's `~/bin/harness` does.
6. **Reproducibility applies to the verbs, not the end-to-end run.** We deliberately give up same-inputs→same-journey reproducibility (the original §2 goal). Autonomy is not a separate deterministic engine — it is Hermes occupying the trigger slot a human would. The container still provides a consistent runtime for each verb.

---

## 2. High-Level Architecture

One execution model, two triggers. A trigger launches a per-session Claude runtime; that session orchestrates and implements, shelling out to one-shot verb containers; the verbs are the only thing that touches the ledger and git/ticket state.

```
┌─────────────────────────────────────────────────────────────────────┐
│  TRIGGER                                                            │
│   • a human  ( /harness run CAL-42 )                                │
│   • Hermes   ( Nous' persistent agent: built-in cron dispatcher )   │
└───────────────────────────┬─────────────────────────────────────────┘
                            │ launch a session for a ticket
                            ▼
┌─────────────────────────────────────────────────────────────────────┐
│  Claude session — orchestrator + implementer  (per-session)         │
│   start → [implement] → review → (fix → review)* → close            │
│   context retained; the agent that reads the ticket writes the code │
└───────────────────────────┬─────────────────────────────────────────┘
                            │ shells out to verbs (one-shot `docker run`)
                            ▼
┌─────────────────────────────────────────────────────────────────────┐
│  Harness: start / design / review / close  +  ledger  +  gate       │
│   • each verb a one-shot container over the host-mounted worktree   │
│   • SQLite ledger (runs/events) at /workspace/.harness/             │
│   • close gate: refuse unless a HEAD-bound passing review exists    │
└─────────────────────────────────────────────────────────────────────┘
```

A human typing `/harness run CAL-42` and Hermes dispatching CAL-42 produce the **identical** execution path. The agent runtime is *per-session* (one Claude per ticket, where context lives); each verb is *per-call* — a one-shot container spawned **outside** the runtime, exactly as `~/bin/harness` is already a `docker run`. The agent must not run inside a verb container; that would make it per-call and reintroduce the lost-context problem.

### Verb lifecycle per run

1. A trigger launches a Claude session for `<ticket>` and issues `/harness run <ticket>`.
2. **`start <ticket>`** — validate the ticket, transition it to In Progress, create a worktree off the base branch (default `dev`), open a `runs` ledger row (`status=open`, ULID `run_id`). Emits `StartOutput` (run_id, ticket context, worktree path/branch).
3. **implement** — the session writes code + tests in the worktree, test-first, in scope. No verb is involved; the agent uses its own tools.
4. **`review --run-id <id>`** — run codex against the worktree HEAD; record a `review` event carrying `{ verdict, issues, reviewed_sha }` bound to that SHA. The session sees only the bounded verdict; codex's full reasoning stays inside the verb.
   - `fail` → fix the root cause, commit, re-run `review` (the `(fix → review)*` loop). Each review binds to the new HEAD.
   - `defer` → file a follow-up for the out-of-scope finding, then close.
   - `pass` → proceed to close.
5. **`close <ticket> --run-id <id>`** — enforce the gate (a `start` exists **and** a `verdict=pass` whose reviewed SHA == current HEAD), then commit/merge/push, transition the ticket to Done, flip the run to `status=closed`. A gate refusal is structured (`no_run` / `dirty_worktree` / `no_passing_review` / `stale_review`) and is the gate doing its job — never worked around.

The harness never decides what to build or how. The session does; the verbs record it and gate the merge.

---

---

> **§3, §5–§10, §12–§15, and §17–§18 described the retired deterministic workflow engine — their bodies are re-homed to [`specs/retired/spec-engine.md`](specs/retired/spec-engine.md), leaving stub pointers below.** (Exceptions: **§4 *Core Module Design*** and **§11 *CLI Design*** have been rewritten to the as-built verb system — read them as current, and **§16 *Non-Goals*** is standing policy rather than engine design.) The re-homed doc is kept for historical reference and for the mechanics that were **re-homed as verb helpers** (worktree lifecycle, codex dispatch, the SQLite store, git/Linear helpers). The YAML-walking orchestration — `engine/runner|executor|loop|retry`, the node protocol, the workflow schema, contract/derive machinery, and `build*.yaml` — was deleted in CAL-574 (proposal [`harness-as-tool`](specs/proposals/harness-as-tool.md), decision D1). Treat any "the engine walks the workflow / the YAML decides the route" statement in the re-homed doc as superseded by §1–2. The current schema reference is [`specs/features/run-ledger.md`](specs/features/run-ledger.md) § Schema reference; the current command contract is [`commands/harness.md`](commands/harness.md).

---

## 3. Repository Structure

> **Retired — deterministic workflow engine.** Moved to [`specs/retired/spec-engine.md`](specs/retired/spec-engine.md), superseded by the verb model (§1–2; see the status banner at the top of this file).

## 4. Core Module Design

The harness is a small set of modules behind the verb CLI: the verbs, the
worktree lifecycle, the SQLite ledger, the event log, and the Linear and
identity helpers. The deterministic-engine internals this section once
described — the YAML runner and executor, the node protocol, the agent-dispatch
layer, and the workflow loader — were deleted in CAL-574 (see §3's banner and
`tests/unit/test_engine_retired.py`).

### 4.1 `harness.cli` — the verb surface

The Typer app (`harness/cli/__init__.py`) is the public contract. It registers
the audited lifecycle verbs (`start` / `design` / `review` / `close`) — detailed in §4.2–§4.4 —
alongside the read/inspection commands, the mutating ops and maintenance verbs,
and the worktree housekeeping group. The exact registered set, with flags and
exit codes, is the §11 command surface — the single source of truth, locked
against the live app by `test_cli_surface_locked.py`; this section deliberately
does not re-list it, so a verb added later cannot leave a stale partial list
here. Subcommands are split per concern
across `harness/cli/*.py` for readability. Stable flags, stable exit codes,
stable JSON output — see §11.

### 4.2 `harness.cli.start`

Opens a run. Validates the ticket (fetch from Linear, canonicalise the
identifier, refuse a duplicate open run), generates a ULID `run_id` and creates
an isolated git worktree off the base branch (via `harness.worktree`, default
`dev`), inserts the `open` `runs` ledger row, and **transitions the ticket to
*In Progress* last** — it is the only non-local side effect, so if the worktree
or the ledger insert fails nothing has touched Linear (rollback ordering locked
by `test_cli_start.py::test_worktree_failure_leaves_no_db_row_and_no_transition`
and `::test_db_failure_removes_worktree_and_no_transition`). Emits a
`StartOutput` JSON object (`run_id`, ticket, worktree path/branch); the open run
is recorded as the `runs` row, not as an event.

### 4.3 `harness.cli.review`

Reviews the worktree's current HEAD with the configured reviewer (codex).
Captures `git rev-parse HEAD` as `reviewed_sha`, runs codex against the
worktree, scans stdout for the single `SUBMIT: <json>` line, and appends a
`review` event whose verdict (`pass` / `fail` / `defer`) is **bound to that
SHA** — the load-bearing detail behind decision D2 (the close gate refuses a
pass whose SHA ≠ HEAD). Prints only the bounded verdict; the reviewer's full
reasoning stays inside the verb.

### 4.4 `harness.cli.close`

Enforces the gate, then merges the **already-committed** HEAD to the base
branch, pushes, transitions the ticket to *Done*, and finalizes the run. It does
**not** auto-commit: a dirty worktree is refused outright, because uncommitted
edits are not in HEAD and so were never reviewed (`stale_review` catches a
commit *after* review; only the clean-tree check catches an edit *without*
committing — CAL-586). The gate refuses unless a `start` row exists, the
worktree is clean, and a `verdict=pass` reviewed-SHA equals HEAD; a refusal
exits 2 with exactly one structured `reason` — `no_run` / `dirty_worktree` /
`no_passing_review` / `stale_review` (locked by
`test_cli_close.py::test_dirty_worktree_refused_when_uncommitted_edits` and
the gate tests). The verb never works around its own gate.

### 4.5 `harness.worktree`

Git worktree creation off a base branch. Re-homed from the retired engine as a
verb helper; only `create` survives — the engine-era `cleanup` `CleanupPolicy`
machinery was retired in CAL-693 (no live caller — `start` rollback / `close`
merge / `worktrees cleanup` use direct git). See
[`specs/features/worktree-lifecycle.md`](specs/features/worktree-lifecycle.md)
(the engine-era `WorktreeNode` detail is [`specs/retired/worktree-isolation.md`](specs/retired/worktree-isolation.md)).

### 4.6 `harness.state.store`

The SQLite ledger via `aiosqlite`. The `runs` / `events` tables are the whole
audit trail; the connection is a managed resource (`@asynccontextmanager`, see
CONTEXT.md). All run-lifecycle state goes through the store so the ledger
reflects reality and the close gate can validate against it (D5). The schema and
the open/closed run lifecycle live in
[`specs/features/run-ledger.md`](specs/features/run-ledger.md) § Schema reference
(the current schema reference).

### 4.7 `harness.events.emitter`

Append-only event-log writer over the `events` table. `review` appends a
`review` event (carrying `reviewed_sha` + verdict), `close` appends a `close`
event, and `checkpoint` appends a `checkpoint` event (the run-branch push that
makes WIP durable, CAL-738); `start` emits **no** event — the open run is
recorded as the `runs` row itself. So the audit trail is the `runs` row **plus**
its events, not the events alone. Event types live in `harness.events.schema`.

### 4.8 `harness.linear`, `harness.identity`

`harness.linear` is the Linear GraphQL client `start` and `close` use to fetch a
ticket and transition its state. `harness.identity` generates the run ID (a
ULID) and propagates it across the verbs.

### 4.9 `harness.workspace`

`harness.workspace` gates every verb's `--repo` through one shared adapter: the
`HARNESS_WORKSPACE_ROOTS` allowlist (CAL-584), which fails closed when unset,
then a git-top-level check (#214, distinct `NotAGitTopLevel`) so a verb invoked
below the root refuses instead of planting state under the wrong one. Both exit 2.

(The narrow host launcher control socket and the autonomous-dispatch *trigger*
stand-in that once shared this section were the deferred Hermes scaffolding,
removed in CAL-712. Their design is archived at
[`specs/retired/hermes-orchestration.md`](specs/retired/hermes-orchestration.md);
the autonomous dispatcher itself is deferred until the Build loop is built.)
---

## 5. YAML Workflow Schema

> **Retired — deterministic workflow engine.** Moved to [`specs/retired/spec-engine.md`](specs/retired/spec-engine.md), superseded by the verb model (§1–2; see the status banner at the top of this file).

## 6. State Schema (derived)

> **Retired — deterministic workflow engine.** Moved to [`specs/retired/spec-engine.md`](specs/retired/spec-engine.md), superseded by the verb model (§1–2; see the status banner at the top of this file).

## 7. State Merge Semantics

> **Retired — deterministic workflow engine.** Moved to [`specs/retired/spec-engine.md`](specs/retired/spec-engine.md), superseded by the verb model (§1–2; see the status banner at the top of this file).

## 8. Run ID and Identity

> **Retired — deterministic workflow engine.** Moved to [`specs/retired/spec-engine.md`](specs/retired/spec-engine.md), superseded by the verb model (§1–2; see the status banner at the top of this file).

## 9. Worktree Isolation

> **Retired — deterministic workflow engine.** Moved to [`specs/retired/spec-engine.md`](specs/retired/spec-engine.md), superseded by the verb model (§1–2; see the status banner at the top of this file).

## 10. Execution Engine Details

> **Retired — deterministic workflow engine.** Moved to [`specs/retired/spec-engine.md`](specs/retired/spec-engine.md), superseded by the verb model (§1–2; see the status banner at the top of this file).

## 11. CLI Design

### Command surface

```
# Audited verbs — one-shot, ledger-backed; the orchestrating agent calls these
harness start  <ticket>   [--base <b>] [--resume] [--repo <p>] [--db <p>] [--json]   # --resume: a reclaimed ticket with a checkpoint-pushed WIP branch continues from it (fetch + base the worktree on it); falls back to a clean start (CAL-739)
harness design            [--run-id <id>] [--model <alias>] [--repo <p>] [--db <p>] [--json]   # the design stage between start and implement (ADR 0007): a read-only Opus engine produces the change spec's Design section, recorded as a marked ticket comment + a `design` ledger event. --model overrides the unconditional Opus default (host/testing)
harness review            [--run-id <id>] [--repo <p>] [--db <p>] [--json]
harness close  <ticket>   [--run-id <id>] [--repo <p>] [--db <p>] [--json]
harness checkpoint        [--run-id <id>] [--repo <p>] [--db <p>] [--json]   # push the run branch to origin so committed WIP survives the container dying (CAL-738); pushes only the feature branch — never merges, so the close gate is untouched

# Read / inspection — never mutate state
harness status    [<run-id>]              [--run-id <id>] [--json]
harness logs      [<run-id>]              [--run-id <id>] [--follow] [--node <id>]
harness events    [<run-id>]              [--run-id <id>] [--type <event_type>] [--json] [--after-id <n>]
harness runs                              [--limit <n>]
harness stats                             [--since <dur>] [--db <p>] [--json]   # the aggregate reader over the whole ledger (#265): per-verb attempts split ok/refused/failed, verb + run latency (median and max), review cycles per run, recovery counts, engine verdicts. Read-only — opened `mode=ro`, so it cannot write. Retired-engine rows (CAL-574) are excluded and reported separately, and the covered window is stated rather than implied
harness worktrees list                    [--json]
harness worktrees cleanup                 [--age <duration>] [--merged] [--force] [--db <p>]

# Ops
harness cancel    <run-id>                    # abandon an in-flight run (close without merge)
harness reclaim   [<run-id>] [--ticket <id>] [--stale --project <name> [--older-than <dur>]] [--undo] [--db <p>] [--json]   # revert a stranded ticket to Todo + reconcile the ledger; --stale sweeps the project's In-Progress tickets idle past the threshold (default from `loop.wall_clock_budget_minutes`, shared with review's wall-clock breaker — #260; idle = tracker updatedAt, the ledger's last activity, AND the run worktree's newest tracked-file mtime — #254), reporting a third outcome `closable` for an idle run whose clean worktree HEAD already carries a gate-evidenced passing review — it was never stranded, only unfinished, so it is left open for `close` rather than reverted (#255); --undo reverses a reclaim confirmed to be a false positive (ticket back to In Progress, label dropped, run row re-opened)
harness defer     <ticket> --reason <text> [--reason-file <p>] [--db <p>] [--json]   # triage: post a comment + additively apply the `decision` label on a Build-queue ticket (`repo.project` when set, else the whole tracker queue — #248); record a defer event (CAL-1143)
harness release   <ticket> --resolution <text> [--resolution-file <p>] [--needs <kind>] [--db <p>] [--json]   # decision-sweep return write: write the resolution into the change spec + remove the hold label + unassign the operator on a Build-queue ticket (`repo.project` when set, else the whole tracker queue — #248); record a release event (#193)
harness doctor                                # system health checks
harness version                           [--json]

# Promotion lifecycle — move dev -> staging -> main (ADR 0003); v1 surface, mechanics land per CAL-1114+
harness promote start     [--repo <p>] [--from <b>] [--to <b>] [--json]   # open a promotion: merge --from into --to and classify
harness promote continue  [--promotion-id <id>] [--repo <p>] [--json]   # resume an agent_may_fix promotion after one bounded repair
harness promote status    [--promotion-id <id>] [--repo <p>] [--json]   # read a promotion by id: typed ledger view
harness promote pr        [--promotion-id <id>] [--repo <p>] [--json]   # success finalizer: push the promotion branch + open the PR (gated)
harness promote escalate  [--repo <p>] [--json]   # non-success terminal: file/update a Linear ticket
```

There is no `harness promote verify` in v1: the gate runs inside `start` / `continue`, never a standalone pause point (ADR 0003; rationale in [`cli-surface.md`](specs/features/cli-surface.md)).

#### Harness-as-tool verbs

`start` / `design` / `review` / `close` are the audited, one-shot verbs an
orchestrating agent calls over the SQLite ledger — see `specs/proposals/harness-as-tool.md` and ADR 0007 for the design stage.

**`harness review`** runs the configured reviewer (codex) against the worktree's
current HEAD and records a `review` event bound to the exact SHA reviewed — the
load-bearing correctness detail behind decision **D2** (the `close` gate
refuses a pass whose SHA ≠ HEAD, so a stale pass cannot be reused).

- Resolves *the current run* — the `status='open'` run whose `worktree_path`
  equals `--repo` (CWD by default), or the run named by `--run-id`. No open run
  resolved → exit 2.
- Captures `git rev-parse HEAD` in that worktree as `reviewed_sha`.
- Invokes `codex exec --dangerously-bypass-approvals-and-sandbox --ephemeral -`
  with the review prompt on stdin and scans stdout for the first `SUBMIT: <json>`
  line. The JSON carries `verdict` (`pass`|`fail`|`defer`), `issues[]`, and
  optional `commit_message` / `deferred_brief`. A missing, malformed, or
  unknown-verdict SUBMIT line means the reviewer delivered **no verdict**, so it
  is an infra failure, not a rejected diff (#270): exit 3 with `reason` of
  `no_submit` (no `SUBMIT:` line anywhere) or `malformed_submit` (one was seen
  but none parsed), recorded as a refusal carrying no `verdict`. It consumes no
  review cycle and leaves the ticket In Review — the same classification the
  engine timeout and the sandbox walls already carry, on the same principle that
  an engine which never reviewed the diff produced no verdict. The verb still
  never raises on a bad reviewer; it records the failure.
- Appends a `review` event (`harness.events.schema` event type `review`) whose
  `data_json` holds `run_id`, `reviewed_sha`, `verdict`, `issues`, optional
  `commit_message` / `deferred_brief`, and `created_at`.
- **Context economy:** prints only the bounded verdict — `verdict`, `issues`,
  `reviewed_sha`, `run_id`. Codex's full stdout / reasoning stays inside the
  verb and never enters the printed or returned JSON, keeping the agent's
  context budget bounded. A recorded `fail` is still a *successful review*
  (exit 0); deciding what to do with a verdict is the agent's job, not the
  verb's. Exit codes mirror `start`: 0 success, 1 unexpected error, 2 no open
  run resolved.

### Fixed verb surface (no dynamic subcommands)

The surface above is **fixed**. There is no per-workflow dynamic subcommand
generation: each verb is a hand-written Typer command with a stable flag set,
and adding behaviour means adding or changing a verb, not loading YAML at
invocation. The authoritative, agent-facing contract for the verbs the
orchestrating session drives is [`commands/harness.md`](commands/harness.md);
the registered command set is wired in `harness/cli/__init__.py`.

### Exit codes (stable contract)

| Code | Meaning |
|------|---------|
| 0 | Command succeeded |
| 1 | Unexpected error (git failure, DB error, Linear error) |
| 2 | Invocation error or gate refusal (bad flags, unknown run-id, gate not satisfied) |
| 130 | SIGINT (user cancelled) |

### JSON output

`status` and `events` expose `--json` for machine consumers; `logs` is the
human-readable timeline (use `events --json` for its machine-readable form) and
`runs` prints a summary table. The verbs (`start` / `design` / `review` / `close`) also
take `--json`. Flag names and JSON keys are part of the public contract — no
breaking changes without a major version bump.

### Examples

```bash
# Open a run for a ticket (transitions it to In Progress, creates the worktree)
harness start CAL-123

# Review the worktree HEAD — the verdict binds to the reviewed SHA
harness review --run-id 01J...

# Close through the gate (merge/push, transition the ticket to Done)
harness close CAL-123 --run-id 01J...

# Inspect a run without mutating it
harness status 01J... --json | jq .status
```

---

## 12. SQLite Schema

> **Retired — deterministic workflow engine.** Moved to [`specs/retired/spec-engine.md`](specs/retired/spec-engine.md), superseded by the verb model (§1–2; see the status banner at the top of this file).

## 13. Docker Setup

> **Retired — deterministic workflow engine.** Moved to [`specs/retired/spec-engine.md`](specs/retired/spec-engine.md), superseded by the verb model (§1–2; see the status banner at the top of this file).

## 14. Example Workflow: Steward (smallest end-to-end)

> **Retired — deterministic workflow engine.** Moved to [`specs/retired/spec-engine.md`](specs/retired/spec-engine.md), superseded by the verb model (§1–2; see the status banner at the top of this file).

## 15. Migration Plan

> **Retired — deterministic workflow engine.** Moved to [`specs/retired/spec-engine.md`](specs/retired/spec-engine.md), superseded by the verb model (§1–2; see the status banner at the top of this file).

---

## 16. Non-Goals (Important)

Explicit list of things this project does **not** do, even on request:

- Full DAG engine. v1 is linear + loop. DAG comes only when a real workflow needs it and a YAML hack would be uglier than parallel-step support.
- Web UI / dashboard. CLI + JSON output is enough.
- Workflow visual builder.
- Long-running daemon / server. The CLI runs, completes, exits. State persists in SQLite.
- Multi-tenancy / multi-project state in one DB. One DB per project mount.
- Built-in scheduling. Cron / launchd / systemd does that. The harness is invoked by them.
- LLM-driven workflow generation.
- General-purpose agent framework. The harness is a set of deterministic verbs an agent calls, not a framework that runs agents. If a use case wants an autonomous agent that spawns its own work, this isn't the tool.

---

## 17. Open Questions (deferred decisions)

> **Retired — deterministic workflow engine.** Moved to [`specs/retired/spec-engine.md`](specs/retired/spec-engine.md), superseded by the verb model (§1–2; see the status banner at the top of this file).

---

## 18. Success Criteria

> **Retired — deterministic workflow engine.** Moved to [`specs/retired/spec-engine.md`](specs/retired/spec-engine.md), superseded by the verb model (§1–2; see the status banner at the top of this file).

---

## Appendix A — Inspirations and design ancestry

- [Archon](https://github.com/coleam00/Archon) — workflow concepts (DAG node types, fresh-context loops, worktree-per-run, per-tool-call event log). This spec lifts the *ideas*; the *code* is greenfield Python.
- Anthropic's "harness design" essay — the bounded-LLM-as-function principle.
- Pydantic 2's strict mode — model for "validate at the boundary, trust within."
- Temporal — for the "deterministic engine, stateful inputs" mental model (we don't need the durable-execution machinery, but the conceptual split is the same).
