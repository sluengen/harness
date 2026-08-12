<!-- guidance:harness-routine-build@0.1.0 -->
# /harness routine build

This unattended, always-on-local-trigger routine pulls the next actionable Todo ticket. Version the logic, not the schedule. Never pass `--attended`. Resolve optional `repo.project` from `CONTEXT.md`; when absent, use the configured provider's whole queue and omit `--project`.

Primary: `/harness run <TICKET>` through `~/bin/harness`. Fallback when the harness tool is unavailable: `/build <TICKET>`. The harness repo uses the primary. Optional off-machine execution is a Claude cloud routine, not GitHub Actions; a target whose gate needs Xcode/macOS stays local or on a macOS runner (ADR 0001).

## Step 0 — recover before picking

```bash
harness reclaim --stale --project "<repo.project>" --json   # project set
harness reclaim --stale --json                              # project absent
```

Run first, before the pick. The unattended threshold is `loop.wall_clock_budget_minutes`; attended runs use `loop.attended_idle_minutes`. `--json` is required because the drain consumes `closable`. The sweep unblocks the backlog, is idempotent and safe each tick, and checks In Progress and In Review. A ticket is reclaimed only when tracker activity, ledger activity, and tracked-worktree mtimes are stale/unreachable. Local clocks may spare a tracker-stale run, never condemn one.

The sweep reverts dead runs to Todo except a clean open run whose HEAD already has a passing review with verify-gate evidence. It reports that run in `closable`, without tracker or ledger mutation. Liveness is checked before closability, so a live paused session is skipped. Uncertainty means not closable. The sweep classifies; it never closes.

Checkpoint before long design/gate stretches and after green increments so live work produces ledger activity.

Drain `closable` once, before cleanup, serialized from the main repo root through the same wrapper:

```bash
harness close <ticket> --run-id <run_id>
```

`close` is the only mechanism (`resume-earned-stages` D2). The drain is bounded: never re-sweep. Record each closed/refused ticket and continue; no retry, reclaim, force, or hand merge. D5 permits no compensating mutation, and the next tick reclassifies. Report what step 0 closed: ticket, run id, and outcome.

Then clean merged/orphaned worktrees. This ordering is load-bearing: `--age` acts on mtime and could delete the idle worktree `close` needs.

```bash
harness worktrees cleanup --merged --age 7d
```

Cleanup is best-effort and idempotent. It preserves recent/unmerged/dirty/stashed/open work unless `--force`; do not force in the routine.

## Pick the next ticket and run

1. Invoke `work-discovery`; it solely owns Todo ranking and held/deferred skips.
2. Apply its actionability test. For missing human input, run `harness defer <TICKET> --reason <text> [--needs decision|input|operator]`, which comments, labels, assigns the operator, and records the hold. Re-pick.
3. Run `/harness run <TICKET>` without `--attended`, or `/build <TICKET>` only when the harness tool is absent.
4. For a `reclaimed` ticket, inspect `git status`, tracked-file mtimes, and handoff comments before trusting the time heuristic. If the predecessor is alive, run `harness reclaim --undo <run-id>`, leave it alone, and pick another ticket. Otherwise start with `harness start <TICKET> --resume`; missing preserved WIP safely falls back to a clean integration-branch start. Re-orient from `git log` and the diff.
5. Resolve the integration branch from `CONTEXT.md` rather than hardcoding it.
6. If no wholly actionable Todo remains, run `/harness routine quality`; if it finds nothing, exit cleanly.

With no harness tool, the tracker-neutral fallback performs the equivalent pre-flight through the `tracker` skill, reverting stale In Progress/In Review items to Todo before the pick. It has no `closable` drain because no ledger/close verb exists; never hand-roll that merge.
