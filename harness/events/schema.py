"""Event type literals — see SPEC §4.7.

The canonical set of event types a **live verb** emits. Defined here as a
``Literal`` so static type-checkers reject typos at call sites and the runtime
emitter can validate against ``EVENT_TYPES`` before writing to the append-only
log.

CAL-713 pruned this to the three live-emitter types after the CAL-574 engine
retirement left 16 unused types reading as supported capability. The retired
deterministic-engine types (``workflow_started`` / ``node_*`` / ``tool_*`` /
``decision_*`` / ``state_changed`` / ``loop_iteration`` / ``retry_attempted``)
are no longer writable — the emitter validates them out.

**Legacy-rows allowance.** Historical rows written by the retired engine may
still carry those types. They read back unchanged: only the emitter validates
``event_type`` (on write); readers (``harness events`` / ``status``) never
re-validate it. So pruning the writable set is safe for the existing ledger.
"""

from __future__ import annotations

from typing import Literal, get_args

EventType = Literal[
    # workflow_failed — emitted by ``harness cancel`` (with ``reason='cancelled'``)
    # to mark an abandoned run; the one workflow-lifecycle type with a live emitter.
    "workflow_failed",
    # Review verb (CAL-571) — codex review of HEAD, verdict bound to reviewed SHA.
    "review",
    # Close verb (CAL-572) — gate passed, run merged/closed, ticket Done.
    "close",
    # Checkpoint verb (CAL-738) — the run branch pushed to origin mid-flight so
    # WIP survives the container dying; the ledger signal ``reclaim`` reads to
    # report a *durable* (resumable) branch rather than a never-pushed local one.
    "checkpoint",
    # Defer verb (CAL-1143) — the unattended Build routine's triage write: a
    # picked ticket judged not-yet-actionable gets a comment + the ``decision``
    # label, and this event records that decision (ticket, reason, timestamp) in
    # the audit trail so triage is auditable like every other verb.
    "defer",
    # Design verb (#211, ADR 0007) — the design stage between ``start`` and
    # implement: a read-only Opus engine produces the change spec's Design
    # section. This event is the recorded **attempt** — ``status='ok'`` with the
    # design's hash and the grounded SHA, or ``status='failed'`` with a reason
    # when the engine did not deliver one (degrade-and-record, D4). Its presence
    # is what the review verb's ``no_design`` enforcement checks.
    "design",
    # Release verb (#193) — the ``/decision`` return path: a held ticket's
    # resolution is written into its change spec, the hold label removed, and
    # the operator unassigned. This event records the release (ticket, kind,
    # timestamp) in the audit trail — the ``defer`` shape, in reverse.
    "release",
    # ``reclaim --undo`` (#254) — a reclamation confirmed to have been a false
    # positive is reversed: the ticket returns to In Progress and the ``cancelled``
    # run row is re-opened. The event is *appended* after the surviving
    # ``workflow_failed{reason: reclaimed}`` — the log keeps the mistake, the row
    # status is authoritative. It is also load-bearing as a **liveness** signal:
    # being the restored run's newest ledger activity, it stops the next hourly
    # ``--stale`` sweep from immediately re-reclaiming the ticket it just restored.
    "reclaim_undone",
]

EVENT_TYPES: frozenset[str] = frozenset(get_args(EventType))
"""Runtime view of the canonical event types — derived from the Literal above
so the two cannot drift. This is the **writable** set the emitter enforces;
historical rows may carry retired-engine types (see the module docstring's
legacy-rows allowance)."""
