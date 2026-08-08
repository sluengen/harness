---
proposal: engine-activity-aware-timeouts
status: accepted
date: 2026-08-06
related: [specs/features/verb-model.md, specs/features/run-ledger.md, specs/proposals/per-engine-timeout-ceiling.md]
---

# Proposal: classify engine inactivity before killing a design or review

> Stream headless-engine activity into the shared runner, so the harness can distinguish a silent session from a slow active one without removing its containment limit.

## Problem / motivation

`design` and `review` each launch a one-shot CLI subprocess through
`harness/cli/_engine.py`. The runner currently collects its output only after
the process exits and kills it at `loop.engine_timeout_seconds` (720 seconds).
That keeps a crashed engine from holding an unattended run and its queue slot
open indefinitely, but elapsed time alone does not establish that a process is
stuck. It also destroys work from a slow, active session and makes a retry buy
the same work again.

The ledger now makes this more than a hypothetical trade-off. As at 2026-08-06,
it records 5 `design` and 17 `review` `engine_timeout` refusals. The review
timeouts are concentrated between 2026-08-04 and 2026-08-06, which is evidence
of an engine or environment incident as well as a reason to retain a kill
switch. The existing repeated-timeout breaker already refuses a third review
attempt at the same SHA; it avoids endless retries but cannot recover work
killed by the first two 720-second ceilings.

Both supported headless CLIs expose runtime events. `claude -p` can emit
`stream-json`; `codex exec --json` emits JSONL lifecycle and item events. The
harness does not consume either stream today.

## Options

**Option A — raise or remove the 720-second limit** · Allow long sessions more
time under the current opaque runner. · This reduces false kills, but a crashed
or API-blocked process again owns the queue until an external operation kills
it. It turns the observed review incident into a longer outage and supplies no
new evidence for future tuning.

**Option B — replace the elapsed-time limit with an inactivity limit now** ·
Stream CLI events and kill only after a period with no activity. · This makes
activity relevant, but picks thresholds without a local distribution, changes
the driver and its policy in one release, and removes the final containment
bound for a process that continues emitting events forever.

**Option C — stage streaming observation, then introduce dual limits** · First
stream and summarise activity while retaining the current 720-second kill.
Use the resulting data to set a no-activity limit and a longer hard ceiling in
a follow-up. · This preserves current containment while the new observation is
proved against real Claude and Codex sessions. It costs one interim release in
which slow active sessions can still be killed.

## Recommendation

Choose **Option C**.

The shared runner should consume each CLI's documented JSONL mode and continue
to retain the complete stdout and stderr required by the existing `SUBMIT:` and
failure parsers. It should classify a valid lifecycle or item event as activity
and keep only a compact terminal summary: stream protocol, first and last
activity offsets, event-kind counts, and whether activity was seen. It must not
persist raw event payloads, reasoning, command text, or partial assistant text.
Those payloads can contain repository content and are unnecessary to decide
whether the engine was producing observable events.

The first change keeps `engine_timeout_seconds=720` as the only termination
policy. A timeout event gains the terminal summary, letting `harness stats`
separate “silent before kill” from “active before kill” for both verbs. The
next change uses that measurement to add two explicit limits:

- `engine_inactivity_seconds`: kill an engine after no accepted activity event
  arrives for the configured interval, with reason `engine_stalled`.
- `engine_hard_timeout_seconds`: retain a longer absolute containment limit,
  with reason `engine_hard_timeout`.

The repeat-timeout breaker remains keyed only on terminal engine failures at a
SHA. It must count both new terminal reasons, because a retry after either a
stall or a hard ceiling buys another uncertain engine attempt. A completed
review verdict remains outside that population.

This is the smallest reversible path. It uses each CLI's native output format,
adds no dependency, keeps the ledger as the audit surface, and does not pretend
that event traffic proves useful work. An activity event only proves that the
engine and CLI are communicating.

## Design

### Engine protocol

`run_engine_subprocess` becomes a streaming driver. It starts the engine with
its selected structured-output flag, reads stdout and stderr concurrently, and
buffers each stream exactly as the current `RunResult` contract requires. It
also sends parsed stdout events to a protocol-specific classifier:

| Engine invocation | Structured mode | Activity rule |
|---|---|---|
| design / Claude review | Claude `stream-json` | A valid stream object whose type is an init, message, tool, or result event. |
| Codex review | `codex exec --json` | A valid event whose type is a thread, turn, item, or error lifecycle event. |

Unknown or malformed JSON remains captured output but does not refresh
activity. A classifier must tolerate new event fields and unknown event types;
only the documented envelope and a known activity type determine liveness.
That prevents a CLI upgrade from turning one unfamiliar field into a false
stall, while preventing arbitrary text from keeping a dead process alive.

The command builders own which structured-output flag each engine needs. The
runner owns stream reading, process shutdown, buffering, summary collection,
and timeout mechanics. `design` and `review` continue to own command-specific
output parsing and their distinct terminal outcomes.

### Terminal record

`RunResult` gains an optional, typed `EngineActivitySummary`. It is produced
only by the real runner; test runners may omit it. The summary is attached to
the existing terminal `design` or `review` event, including infra failures,
without changing the close gate or review-cycle counter. It contains bounded,
non-content fields only:

```text
stream_protocol: "claude_stream_json" | "codex_jsonl" | null
activity_seen: bool
first_activity_ms: int | null
last_activity_ms: int | null
activity_event_counts: { <known-kind>: int }
```

The event keeps `duration_ms` as the invocation duration. Its activity summary
is an observation, so a failure to summarise or persist it cannot change a
verb's exit code, verdict, or kill behavior.

### Future policy scenarios

The policy change does not land until the first change has evidence. Its
contract is fixed now so that the observation fields answer its questions.

- GIVEN an engine emits recognised activity throughout a slow invocation, WHEN
  it passes the former 720-second mark but is below the hard ceiling, THEN it
  continues and the terminal event records its activity summary.
- GIVEN an engine emits no recognised activity for the configured inactivity
  interval, WHEN the interval expires, THEN the runner kills and reaps it and
  the verb records `reason="engine_stalled"`.
- GIVEN an engine continues to emit activity beyond the hard ceiling, WHEN that
  ceiling expires, THEN the runner kills and reaps it and the verb records
  `reason="engine_hard_timeout"`.
- GIVEN a retry at the same review SHA already has two recorded terminal engine
  failures from the set `{engine_stalled, engine_hard_timeout}`, WHEN review is
  invoked again, THEN the repeat breaker refuses before spawning an engine.

## Decisions

| Decision | Who decides | Recorded in |
|---|---|---|
| Accept the staged observation-first rollout, rather than changing timeout policy in the same release. | user | Accepted 2026-08-07 in this proposal |
| Set the inactivity and hard-limit defaults after the first release has a stated sample window and review of its timeout summaries. | user | follow-up change spec and `CONTEXT.md` |
| Treat only documented JSONL lifecycle events as activity, never raw bytes or process existence. | user | accepted first change spec; `verb-model.md` as-built record |

This is a consequential shared engine-protocol contract, but it governs the
engine-invocation feature rather than the repository's broader architecture. It
does not need a standalone ADR.

## Breakdown

If accepted, create these tracker issues in order:

1. **Stream engine activity into terminal telemetry** — add structured-output
   command flags, concurrent stream collection, typed bounded activity summaries,
   terminal-event persistence, stats reporting, and unit tests using synthetic
   JSONL plus one opt-in CLI compatibility test per installed engine. Retain the
   720-second timeout and the existing repeat-timeout behavior.
2. **Make engine termination activity-aware** — after the first issue supplies a
   stated sample, add configurable inactivity and hard limits, `engine_stalled`
   and `engine_hard_timeout` reason contracts, repeat-breaker coverage, docs,
   and measuring tests for both thresholds.

## Risks / unknowns

- The CLIs can change event schemas. The first issue must pin a small accepted
  envelope and keep unknown events observable but non-authoritative.
- Claude and Codex may emit events at different cadences. The first issue must
  report summaries by engine and protocol; shared defaults require evidence from
  both, not an assumption that they behave alike.
- An engine can emit events while making no useful progress. The hard ceiling
  remains necessary; activity suppresses an inactivity kill, not all limits.
- Streaming partial output increases memory and sensitive-output exposure if it
  is logged carelessly. Buffering remains bounded as it is today, and terminal
  telemetry stores counts and offsets only.
- The existing raw `SUBMIT:` parser expects plain output. The first issue must
  prove that the structured modes preserve a recoverable final verdict/design
  artifact before making them the default invocation path.

---

**Lifecycle.** Accepted 2026-08-07. Create its two tracker issues in order;
the feature-spec reviewer records the delivered behavior. If implementation
finds the scope indivisible, replace this proposal with smaller proposals.
