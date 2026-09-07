# ADR 0009 — Every verb records its attempt, not only its outcome; observation rides the existing event types

- **Status:** Accepted
- **Date:** 2026-07-30
- **Source:** the `verb-telemetry` proposal (settled; removed from the tree by #547, kept in git history)

> **Landed retrospectively on 2026-08-01.** Decided 2026-07-30; the file sat on an unmerged local branch while its breakdown tickets were built and closed, so the decision was in force well before its record was. Nothing below is reconstructed — this is the file as written on the decision date, with only its status reconciled to what shipped. Implemented by #261-#265, all closed.

## Context

The ledger is a faithful record of what succeeded and a near-total blank on what was attempted. Three facts, measured against this repo's `.harness/harness.db` (283 runs, 1,942 events):

- **No live verb writes `duration_ms`.** The column has existed since the initial schema, `EventEmitter.emit()` accepts it (`harness/events/emitter.py:68`), and `harness runs` / `harness status` already render it. Across the six live event types — `review` (380), `checkpoint` (238), `close` (218), `design` (48), `defer` (6), `release` (1) — **zero** rows populate it. Every populated row belongs to the deterministic engine retired in CAL-574.
- **`close` does not stamp `completed_at`.** `_mark_run_closed` flips `status='closed'` and appends the `close` event, nothing more, so 7 of 225 closed runs carry a `completed_at`. `cancel` / `reclaim` do stamp it (18 of 18). Run wall-clock is recoverable only by joining `runs.started_at` against the `close` event payload's `closed_at`.
- **A refused or failed verb writes nothing.** `harness/cli/review.py` has exactly one emit site (line 770), reached only after a verdict parses; `engine_timeout`, a tripped breaker, `no_design`, `no_gate_evidence`, and a malformed engine SUBMIT all raise past it. `close`'s four gate refusals raise before any write. The ledger therefore holds 260 `pass` / 110 `fail` / 10 `defer` verdicts and **no denominator**: verb success rate is not a slow query, it is an unanswerable one.

`design` is the counter-example inside the same codebase. It records failures as first-class events (`status: 'failed'` with a `reason` and `detail`) — which is why its failure rate is a one-line query, 9 of 48 — and carries both `invoked_at` and `designed_at`. That reconstruction is what justified raising `engine_timeout_seconds` 600 → 720 on 2026-07-30. The pattern that made an evidence-based decision possible exists in one verb and was never generalised.

## Decision

**Every verb records its own attempt on every terminal path — success, refusal, and infra failure — as an event carrying a duration and, on a non-success, the structured reason the verb already computes for its exit code.** Observation lives in the existing `runs` / `events` tables; no second store.

Concretely:

- **Outcome rides a field, not a new event type.** A verb's event type stays one per verb (`review`, `close`, `design`, …); a non-success is distinguished by an `outcome` field on that type's payload, following `design`'s existing `status: ok | failed` shape. `EVENT_TYPES` stays closed — CAL-713 deliberately pruned it to the live emitters, and doubling it with `*_refused` members would undo that. This is also the safe choice for the close gate: its query filters `event_type='review' AND json_extract(…,'$.verdict')='pass'`, and a refusal event carries no `verdict` key, so `json_extract` yields NULL and the gate cannot be opened by an observation.
- **Reasons are the existing typed literals.** `RefusalReason`, `FailureReason`, `ENGINE_TIMEOUT_REASON`, and the breaker reasons are already declared. Telemetry reuses them; it must not introduce a parallel vocabulary that can drift from the exit codes it describes.
- **`duration_ms` is required on every terminal event; `review` also gains `invoked_at`.** The duration is the primary datum. The two-timestamp form is kept for the engine-invoking verbs because it survives a verb that dies before writing a duration — the case `design` was actually read for.
- **`close` stamps `completed_at` and `duration_ms` on the `runs` row inside its existing `BEGIN IMMEDIATE` transaction.** This one is run-lifecycle state, not observation, so it belongs in the transaction rather than beside it.
- **Telemetry never changes a verb's exit path.** A failed observation write cannot convert a gate refusal into an error, suppress one, or alter an exit code. `close`'s best-effort worktree teardown is the model: suppressed, and strictly after the decision is made. The `completed_at` stamp above is the deliberate exception, being lifecycle state.

The general rule this sets, which future work must honour: **an observation is subordinate to the thing it observes.** Recording that a verb refused may never affect whether it refused.

## Alternatives rejected

- **A dedicated `verb_invocations` table.** A clean aggregate shape, and it sidesteps both the closed-`EVENT_TYPES` question and the `events.run_id` foreign key. Rejected because `specs/features/run-ledger.md` is explicit that the `runs` + `events` pair **is** the whole audit trail, and the close gate rests on that property. The `promotions` sibling table is not a precedent for this: promotion is a genuinely separate lifecycle gating branch movement, whereas a verb invocation is the *same* lifecycle observed more finely. Two places to look for the truth about one run is a worse trade than one field on an event.
- **Emit to an external sink (OpenTelemetry / statsd / JSON lines).** The industry-standard shape. Rejected on ADR 0001's reasoning — this is a single-operator, always-on-local tool, and standing up a collector to answer questions one SQL query answers is infrastructure with no user. It also puts observation outside the audited record, so a refusal would be visible in a metrics pipeline and absent from the ledger, which is the untruth-by-omission ADR 0008 rejected.
- **Ship the reporting command first, over existing data.** Rejected because any success rate computed today has a denominator that excludes every refusal. The number would be wrong and would look authoritative.
- **A synthetic `runs` row to anchor a run-less refusal.** `defer` already does this (`workflow_name='defer'`, `status='closed'`, no worktree) to satisfy `events.run_id NOT NULL`, and `run-ledger.md` records it as a workaround, not a pattern. Repeating it for every `no_run` refusal would put non-run rows in the `runs` table at volume. Rejected in favour of the limitation below.

## Consequences

- **`close`'s `no_run` refusal stays unrecorded.** It is the one class where genuinely nothing existed to observe — no run, therefore no `run_id` to anchor an event to. Accepted knowingly as a known limitation rather than paid for with synthetic rows. Every other refusal has a resolved run.
- **The already-built duration display stops being blank.** `harness runs` and `harness status` need no change to benefit; they have been selecting and formatting `duration_ms` for the whole life of the verb model.
- **`harness/cli/review.py` is on the `architecture_watchlist` and is already 976 lines.** The ticket adding emits at six raise sites carries a `Watchlist trigger` section and should extract the observation seam rather than inline it six times.
- **No backfill.** Every rate computed after this ships has a discontinuity at the ship date. The reporting command must surface the window it covers rather than implying the whole history.
- **Event volume roughly doubles, and nothing prunes it.** At 6.3 MB for 283 runs that is noise. If aggregate queries slow, the mitigation is an index on `event_type` — not deletion. An audit trail that prunes itself is a separate decision, deliberately not taken here.
- **A visible success rate invites optimising it.** A verb that refuses correctly is doing its job, so the reporting surface must distinguish *refused* (the gate worked) from *failed* (the verb broke). Collapsing them would create pressure toward weaker gates, which is the opposite of what the ledger is for.
