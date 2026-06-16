---
feature: cli-surface
status: implemented
last_updated: 2026-06-16
linear: [CAL-583, CAL-603, CAL-661, CAL-738]
---

# CLI surface — the fixed verb contract

> A fixed set of hand-written commands — audited verbs, read-only inspection, and ops — with stable flags, exit codes, and JSON output, invoked identically by a human and by Hermes.

## Behaviour

The Typer app (`harness/cli/__init__.py`) is the public contract. The surface is **fixed**: there is no per-workflow dynamic subcommand generation (an engine-era idea, retired). Each command is a hand-written Typer command with a stable flag set; adding behaviour means adding or changing a command, not loading YAML at invocation. The authoritative, agent-facing contract for the verbs is [`commands/harness.md`](../../commands/harness.md); the emitted CLI JSON is locked against drift by `test_cli_surface_locked.py` and `test_verb_contract_locked.py`.

### The command surface

```
# Audited verbs — one-shot, ledger-backed; the orchestrating agent calls these
harness start  <ticket>   [--base <b>] [--repo <p>] [--db <p>] [--json/--no-json]
harness review            [--run-id <id>] [--repo <p>] [--db <p>] [--json/--no-json]
harness close  <ticket>   [--run-id <id>] [--repo <p>] [--db <p>] [--json/--no-json]
harness checkpoint        [--run-id <id>] [--repo <p>] [--db <p>] [--json/--no-json]   # push the run branch to origin mid-flight so committed WIP survives the container dying — pushes only the feature branch, never merges

# Read / inspection — never mutate state
harness status    <run-id>                [--db <p>] [--json]
harness logs      <run-id>                [--follow] [--node <id>] [--db <p>]
harness events    <run-id>                [--type <event_type>] [--after-id <n>] [--db <p>] [--json]
harness runs                              [--limit <n>] [--db <p>]
harness worktrees list                    [--repo-root <p>] [--json]

# Maintenance / ops — mutate outside the audited lifecycle
harness cancel    <run-id>                [--db <p>] [--json]      # abandon an in-flight run: marks the ledger row cancelled
harness reclaim   [<run-id>] [--ticket <id>] [--stale --project <name> [--older-than <dur>]] [--db <p>] [--json]   # reclaim a stranded run (single ticket), or --stale sweeps the project for In-Progress tickets idle past the threshold
harness worktrees cleanup                 [--repo-root <p>] [--age <duration>] [--merged]   # remove stale worktrees (git/fs)
harness doctor                            [--db <p>]               # system health checks (read-only)
harness version                           [--json]
```

This block lists each command's public flags as registered today; `harness <cmd> --help` and the agent-facing [`commands/harness.md`](../../commands/harness.md) are the authoritative per-flag reference. The audited verbs (`start` / `review` / `close`) drive the run lifecycle through the gate; their behaviour is the [verb model](verb-model.md). `checkpoint` is a fourth lifecycle verb the orchestrating run calls *between* `start` and `close` — after each green increment it pushes the run's `worktree_branch` to `origin` so committed WIP survives the container dying, and appends a `checkpoint` event bound to the pushed SHA. It pushes **only** the feature branch — never the base, never a merge — so the `close` gate is untouched; the event is the durable-WIP signal `reclaim` reads to report a resumable branch (CAL-738, proposal `stale-run-reclamation` D4). Three maintenance commands also mutate, but **outside** the gated lifecycle: `cancel` writes the [run ledger](run-ledger.md) — it marks an in-flight run `cancelled` (a close-without-merge), stamps `completed_at`, and emits a `workflow_failed` event; `reclaim` recovers a run whose orchestrator died — it reverts the stranded Linear ticket to Todo (with a `reclaimed` label + comment), then reuses `cancel`'s ledger transaction to clear the `open` row (so a fresh `start` is not blocked), while **preserving** the worktree/branch; its `--stale` sweep enumerates a project's In-Progress tickets and reclaims each whose Linear `updatedAt` is idle past `--older-than` (default 90m) — keying on time alone (proposal D2), since a dead run's liveness cannot be observed — reusing the single-ticket path per ticket (the bulk pre-flight the Build routine calls); `worktrees cleanup` mutates git/the filesystem by removing stale worktree directories with `git worktree remove --force` (the branch itself is retained). The read/inspection commands surface the ledger without mutating it. Every command runs as a one-shot container exactly as the human's `~/bin/harness` does.

### Exit codes are a stable contract

| Code | Meaning |
|------|---------|
| 0 | Command succeeded (including a recorded review `fail` — a *successful* review) |
| 1 | Unexpected error (git failure, DB error, Linear error) |
| 2 | Invocation error or gate refusal (bad flags, unknown run-id, gate not satisfied) |
| 130 | SIGINT (user cancelled) |

#### Scenario: a gate refusal exits 2

- GIVEN `harness close` whose gate is not satisfied
- WHEN it runs
- THEN it exits 2 with exactly one structured `reason` (`no_run` / `dirty_worktree` / `no_passing_review` / `stale_review`)

### JSON output is part of the public contract

The verbs (`start` / `review` / `close`) and `status` / `events` / `version` expose `--json` for machine consumers; `logs` is the human-readable timeline (use `events --json` for its machine-readable form) and `runs` prints a summary table. **Flag names and JSON keys are part of the public contract — no breaking changes without a major version bump.**

#### Scenario: inspect a run without mutating it

- GIVEN any run
- WHEN a consumer runs `harness status <run-id> --json`
- THEN it prints the run's state as JSON and touches nothing

## Interface surface

Commands are split per concern across `harness/cli/*.py` for readability and registered in `harness/cli/__init__.py`. The verb output shapes (`StartOutput` / `ReviewOutput` / `CloseOutput`) are defined alongside their verbs and locked by `test_verb_contract_locked.py`; the full registered command set is locked by `test_cli_surface_locked.py`.

## Known limitations

- No dynamic subcommands: the surface only changes by editing a verb, by design (the engine-era YAML-driven subcommand generation was retired in CAL-574).

## Decisions

The verb surface is a public contract (decision; [`specs/architecture-principles.md`](../architecture-principles.md)) — stable flags, exit codes, and JSON, because humans and Hermes invoke the harness through the same commands.

## Cross-references

- [verb-model.md](verb-model.md) — what the audited verbs do
- [run-ledger.md](run-ledger.md) — what the read/inspection commands surface
- [worktree-lifecycle.md](worktree-lifecycle.md) — the `worktrees` housekeeping commands
- [`commands/harness.md`](../../commands/harness.md) — the agent-facing verb contract
