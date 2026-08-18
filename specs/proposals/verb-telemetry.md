---
proposal: verb-telemetry
status: shipped             # draft | under-decision | accepted | shipped | rejected | split
date: 2026-07-30
related: [specs/features/run-ledger.md, specs/features/verb-model.md, specs/decisions/0009-verb-attempt-telemetry.md, specs/proposals/rebase-stable-certification.md]
---

# Proposal: the ledger records attempts and durations, not just outcomes

> **Landed retrospectively on 2026-08-01.** Decided 2026-07-30; the file sat on an unmerged local branch while its breakdown tickets were built and closed, so the decision was in force well before its record was. Nothing below is reconstructed — this is the file as written on the decision date, with only its status reconciled to what shipped.

> Verb success rates and latencies are not merely hard to query — they are structurally unrecorded, because a verb that refuses or times out writes no event at all and no live verb stamps a duration.

## Problem / motivation

The ledger is a faithful record of what *succeeded* and a near-total blank on what was *attempted*. Three concrete gaps, each verified against this repo's `.harness/harness.db` (283 runs, 1,942 events):

### 1. No live verb records a duration

The `events` table has had a `duration_ms` column since the initial schema, `EventEmitter.emit()` already accepts a `duration_ms` argument (`harness/events/emitter.py:68`), and both `harness runs` and `harness status` already `SELECT` and render it (`harness/cli/query_runs.py:36`, `query_status.py:81`). The display layer is built and permanently blank:

| Event type | Rows | With `duration_ms` |
|---|---|---|
| `review` | 380 | **0** |
| `checkpoint` | 238 | **0** |
| `close` | 218 | **0** |
| `design` | 48 | **0** |
| `defer` | 6 | **0** |
| `release` | 1 | **0** |
| `node_completed` (retired engine) | 382 | 382 |
| `workflow_completed` (retired engine) | 10 | 10 |

Every populated row belongs to the deterministic engine retired in CAL-574. The verb model inherited the column and never wrote to it.

### 2. Run wall-clock is not recorded either

`harness close`'s `_mark_run_closed` sets `status='closed'` and appends the `close` event — it never stamps `completed_at` or `duration_ms` on the `runs` row (`harness/cli/close.py:457`). Result: **7 of 225 closed runs have a `completed_at`**. (`cancel` / `reclaim` do stamp it — 18 of 18 cancelled rows have one — so the omission is specific to the success path.) Run duration is recoverable only by joining `runs.started_at` against the `close` event payload's `closed_at` field. That is archaeology by JSON extraction, and it is the *good* case.

### 3. A refused or failed verb leaves no trace at all

`harness/cli/review.py` has exactly **one** emit site (line 770), and it is reached only after a verdict has been parsed. Every other exit path raises `_ReviewError` and returns without writing anything: `engine_timeout` (lines 682, 719), a tripped spend breaker (527), `no_design`, `no_gate_evidence`, a malformed engine SUBMIT (241). `close` is the same — all four gate refusals (`no_run`, `dirty_worktree`, `no_passing_review`, `stale_review`) raise before any write.

So the ledger holds 260 `pass`, 110 `fail`, and 10 `defer` verdicts, and **no denominator**. "How often does `review` succeed?" is not a slow query; it is an unanswerable one. Same for "how often does `close` refuse, and why", and "how often does the review engine time out" — the last being a question the operating record shows was asked repeatedly and answered by reading prose notes.

**`design` is the counter-example inside the same codebase.** It records its failures as first-class events (`status: 'failed'`, plus a `reason` and `detail`), which is why its failure rate is a one-line query: **9 of 48, 18.8%**. It also carries both `invoked_at` and `designed_at`, so its latency is reconstructable — that reconstruction is exactly what justified raising `engine_timeout_seconds` from 600 to 720 on 2026-07-30. The pattern that made that decision possible exists in one verb and was never generalised. `review`, by contrast, carries only `created_at`, so **review engine latency cannot be measured at all** — not reconstructed, not approximated.

### Why now

The cost has stopped being hypothetical. Every operational judgement about the loop — is the design verb worth its spend, is the timeout ceiling right, are review cycles converging, how often does a run need recovery — has been made by reading a hand-maintained prose ledger and re-deriving numbers with ad-hoc SQL. And the companion proposal (`rebase-stable-certification`) is currently **unsizeable**: its central quantity is how often `close` refuses with `stale_review`, and that refusal is never recorded. Telemetry is a precondition for deciding that proposal, not a nice-to-have beside it.

## Options

**Option A — every verb records its own attempt and duration, in the existing tables.** Generalise the `design` pattern: each verb emits a terminal event on *every* path — success, refusal, infra failure — carrying `duration_ms` and, on a non-success, the structured `reason` it already computes for its exit code. `close` additionally stamps `completed_at` + `duration_ms` on the `runs` row inside its existing transaction. · *Trade-offs:* no new store, no new schema; the emitter, the column, and the readers all already exist. Roughly doubles event volume (the DB is 6.3 MB for 283 runs, so this is noise). Two real design questions it forces: the closed `EVENT_TYPES` set needs either new members or a status field on existing types, and `events.run_id` is `NOT NULL` with an FK to `runs`, so a refusal with no resolved run (`no_run`) has nothing to anchor to.

**Option B — a dedicated `verb_invocations` table.** A sibling table like `promotions`: one row per verb invocation, with verb, run, ticket, outcome, reason, duration, engine. · *Trade-offs:* a clean shape for aggregate querying, and it sidesteps the FK problem (no `runs` dependency) and the closed-event-type problem. But it splits the audit trail in two, and `close`'s gate would then have two places to look for the truth about a run. `run-ledger.md` is explicit that the `runs` + `events` pair **is** the whole audit trail; a second lifecycle store weakens the property the close gate rests on. The `promotions` precedent argues *for* separation only because promotion is a genuinely different lifecycle — verb invocations are not, they are the same lifecycle observed more finely.

**Option C — emit to an external sink** (OpenTelemetry, statsd, or JSON lines to a file) and aggregate outside SQLite. · *Trade-offs:* the industry-standard shape, and it keeps the ledger lean. Rejected in spirit by ADR 0001's reasoning: this is a single-operator, always-on-local tool, and standing up a collector to answer questions a SQL query can answer is infrastructure without a user. It also puts telemetry outside the audited record, so a refusal would be observable in the metrics pipeline but absent from the ledger — the same untruth-by-omission ADR 0008 rejected.

**Option D — a reporting command over what already exists** (`harness stats` / `harness runs --summary`). Aggregate durations from timestamp arithmetic, verdict mixes, recovery counts. · *Trade-offs:* immediately useful for the three or four questions the existing data *can* answer, and it is where the value is ultimately consumed. On its own it cannot invent the missing denominator, and building the reader first risks encoding "success rate = passes / recorded reviews", which is wrong and would look authoritative.

## Recommendation

**Take A, then D. Reject B and C.**

A first, because it is the only option that fixes the actual defect — the record is incomplete — and it does so entirely within seams that already exist. The column, the emitter argument, the two readers, and a working precedent (`design`) are all in place; what is missing is that five verbs never pass the argument and four exit paths never emit. That is the smallest change that makes the questions answerable, which is the `engineering-principles` test.

D second, and deliberately second. A summary command built before A would compute rates over a denominator that excludes every refusal, and present the result as fact. Once A lands, D is arithmetic over an honest record.

B is rejected because the ledger's single-source property is load-bearing for the close gate, and verb invocations are the same lifecycle rather than a sibling one. C is rejected as infrastructure for a scale this tool does not have, and because it would place part of the record outside the audited store.

Two constraints the implementation must honour:

- **Telemetry must never change a verb's exit path.** A failed telemetry write cannot convert a gate refusal into an error, and cannot suppress one. `close`'s worktree teardown is the model — best-effort, exception-suppressed, strictly after the decision is made. The exception is `close`'s own `completed_at` stamp, which belongs *inside* the existing `BEGIN IMMEDIATE` transaction because it is run-lifecycle state, not observation.
- **Recorded reasons must be the structured ones the verbs already have.** `RefusalReason`, `FailureReason`, `ENGINE_TIMEOUT_REASON`, and the breaker reasons are existing typed literals. Telemetry reuses them; it does not invent a parallel vocabulary that can drift from the exit codes.

## Open decisions

All resolved 2026-07-30. The three architect decisions are recorded in [ADR 0009](../decisions/0009-verb-attempt-telemetry.md); the two operator-facing ones were judgement calls taken with the recommendation and are noted as such.

| Decision | Who decided | Outcome | Recorded in |
|---|---|---|---|
| New `EVENT_TYPES` members per verb vs a `status` / `outcome` field on the existing types (the `design` shape) | architect | **An `outcome` field on the existing per-verb event type.** `design` already proved the shape; `EVENT_TYPES` stays closed. | ADR 0009 |
| How to anchor a refusal with no resolved run (`no_run`) | architect | **It stays unrecorded.** No synthetic `runs` rows at volume; recorded as a known limitation. | ADR 0009 |
| Whether `review` gains an `invoked_at` in addition to `duration_ms` | architect | **Both.** `duration_ms` is primary; `invoked_at` mirrors `design`, whose two-timestamp form survives a verb that dies before writing a duration. | ADR 0009 |
| Is `harness stats` a new command or a `--summary` flag on `harness runs`? | assumed | **A new command.** The read surface is already a set of separate nouns (`status` / `logs` / `events` / `runs` / `worktrees` / `doctor`); an aggregate reader is another noun, not a mode of one run's listing. Revisit at item 5 if it reads awkwardly. | `specs/features/cli-surface.md` |
| Retention — does the ledger keep every attempt forever, or does something prune? | assumed | **No pruning.** At 6.3 MB for 283 runs the ledger is nowhere near a size where pruning beats an index. The mitigation if item 5's queries slow is an index on `event_type`, not deletion — an audit trail that prunes itself is a different decision. | Known limitation, `specs/features/run-ledger.md` |

## Sequencing

**This proposal lands first** (operator decision), ahead of [`rebase-stable-certification`](rebase-stable-certification.md). Items 1 and 3 give that proposal the `stale_review` refusal rate its scope was bounded on. Its former "record gate refusals" item is absorbed here as item 3.

## Breakdown

1. **[#261] `close` stamps `completed_at` + `duration_ms` on the run row** — inside the existing `_mark_run_closed` transaction, so a run's wall-clock stops needing a join against the `close` event payload. Smallest item, no new vocabulary, unblocks `harness runs`' already-built duration column for the success path.
2. **[#262] `review` records every terminal path** — a `duration_ms` and `invoked_at` on the passing/failing event, plus `outcome`-bearing events for `engine_timeout`, a tripped breaker, `no_design`, `no_gate_evidence`, and a malformed SUBMIT. The largest item and the one that creates the missing denominator. Tests must cover each refusal path emitting exactly once and never altering the exit code.
3. **[#263] `close` records its gate refusals** — the `RefusalReason` values, with the same never-change-the-exit-path guarantee. This is the item `rebase-stable-certification` is waiting on.
4. **[#264] `design`, `checkpoint`, `defer`, and `release` record `duration_ms`** — mechanical follow-through now the shape is fixed; `design` already records outcome and reason, so it needs only the duration.
5. **[#265] `harness stats`** — the aggregate reader: per-verb success rate and latency distribution, run wall-clock distribution, review cycles per run, recovery counts (`reclaimed` / `cancelled`), engine-failure rates. Ships last, over an honest denominator. Must distinguish *refused* from *failed* in its own output.
6. **Report the measured refusal rate back** — once item 3 has data, record the real `stale_review` rate in `rebase-stable-certification` so its delta-scoped-review item is built (or dropped) on evidence. Not its own ticket: it is the recorded precondition on [#268].

## Risks / unknowns

- **Volume and prune policy are unset.** Doubling event rows is harmless at this scale, but no answer exists for a year-old ledger, and item 6's queries will get slower with no index on `event_type`. The retention decision above is the placeholder; a `(event_type, run_id)` index may be the cheap mitigation.
- **The FK anchoring question could force an ugly shape.** `defer` already invented a synthetic terminal `runs` row to satisfy `events.run_id NOT NULL`, and `run-ledger.md` records that as a workaround, not a pattern. Repeating it for every run-less refusal would put non-run rows in the `runs` table at volume. Accepting that `no_run` stays unrecorded may be the honest answer — it is the one refusal where genuinely nothing existed to observe.
- **Adding emits to `review` touches the architecture watchlist.** `harness/cli/review.py` is on the `architecture_watchlist` and is already 976 lines; item 3 must carry a `Watchlist trigger` section and will likely need the telemetry seam extracted rather than inlined at six raise sites.
- **Measuring the loop changes how the loop is judged.** Once per-verb success rates are visible, they invite optimisation targets. A verb that refuses correctly is doing its job; a "refusal rate" read as a failure metric would push toward weaker gates. Whatever item 6 prints must distinguish *refused* (the gate worked) from *failed* (the verb broke), and the summary's own copy should say so.
- **Historical rows stay blank.** None of this backfills. Every rate computed after this ships has a discontinuity at the ship date, and item 6 should surface the window it covers rather than implying the whole history.
