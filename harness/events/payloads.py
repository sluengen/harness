"""Typed payload contracts for events that carry structured ``data_json``.

Each event type in :mod:`harness.events.schema` may carry a JSON payload. That
payload's shape was an *implicit* contract: the verb that emits the event built
a bare ``dict`` literal, and a reader in another module ``json_extract``-ed a key
back out by raw string. The two ends were coupled through matching string
literals in different files, so a key rename on one side silently broke the
other. The worst case is the close gate — the load-bearing lifecycle enforcement
— which reads ``$.reviewed_sha`` / ``$.verdict`` out of a ``review`` event: a
rename there turned every close into ``no_passing_review``, fail-safe but
undiagnosable from types (CAL-1012).

These models are the single source of each payload's shape:

* An **emitter** builds the model and dumps it (``model_dump``) instead of a bare
  literal, so a field rename breaks the writer's keyword arguments statically
  (mypy), not at runtime.
* A **reader** that ``json_extract``-s a key, **or reads an already-parsed
  payload dict**, imports the field's path/key constant from here
  (:data:`REVIEW_REVIEWED_SHA_PATH`, :data:`REVIEW_VERDICT_PATH`,
  :data:`WORKFLOW_FAILED_REASON_KEY`, :data:`DESIGN_STATUS_KEY`). A ``*_PATH``
  constant is the ``$.<field>`` form for a SQL reader; a ``*_KEY`` constant is
  the bare field name for a reader that indexes the parsed ``dict``. Each is
  derived from the model via
  :func:`_field_path` / :func:`_field_name`, which raise at import if the field is
  gone — so the raw key string lives in exactly one place, tied to the model, and
  a rename can no longer let writer and reader drift.

The field names are the JSON keys (no Pydantic aliases), so ``$.<field>`` is the
SQLite ``json_extract`` path for a top-level field.
"""

from __future__ import annotations

from pydantic import BaseModel

# size: the single home for every event payload's shape — the whole point of
# the module (see the docstring). Splitting it per-verb would put a writer's
# model and its reader's derived path constant in different files, which is
# exactly the drift these declarations exist to prevent. Length here is
# declarations and their rationale, not logic.

#: The two values of the ``review`` payload's ``outcome`` discriminator (#262).
#: Defined above the models because they are the field *defaults* — spelling the
#: literal in the model and again in the constant is the exact writer/reader
#: drift this module exists to prevent.
#:
#: ``ok`` — a verdict was produced. The default on :class:`ReviewEventData`, so a
#: row written before #262 reads as what it in fact was rather than as unknown.
REVIEW_OUTCOME_OK = "ok"
#: ``failed`` — the verb ended without a verdict (the terminal paths #262 records).
REVIEW_OUTCOME_FAILED = "failed"

#: The one ``reason`` #262 adds to the verb's existing literals, for the raise
#: sites that carry none of their own (a failed HEAD read, an engine that could
#: not be invoked). Without it those paths record a NULL reason and collapse
#: together in the aggregate they exist to make readable.
REVIEW_UNEXPECTED_REASON = "unexpected_error"

#: The two ways **either** engine verb can fail to get a verdict out of its
#: engine's ``SUBMIT`` contract. ``design`` had them first; ``review`` classifies
#: the same failure the same way from #270, which makes this the second copy and
#: therefore the moment to extract (``code-quality``'s extract-on-the-second-copy
#: rule). They live here, beside the outcome discriminators, so the two verbs
#: cannot drift into two spellings of one fact — the same reason
#: :data:`REVIEW_UNEXPECTED_REASON` and :data:`CLOSE_UNEXPECTED_REASON` share a
#: value rather than each declaring their own.
#:
#: They are kept **distinct from each other** because they mean different things
#: to an operator reading the ledger: ``no_submit`` says the engine never reached
#: its contract (it was cut off, rambled, or refused), ``malformed_submit`` says
#: it tried and emitted garbage. Collapsing them would make "did the reviewer
#: stop submitting, or start submitting badly?" unanswerable in exactly the
#: aggregate #262 and #265 exist to serve.
NO_SUBMIT_REASON = "no_submit"
MALFORMED_SUBMIT_REASON = "malformed_submit"

#: The three values of the ``close`` payload's ``outcome`` discriminator (#263),
#: defined above the models for the same reason as ``review``'s: they are the
#: field *defaults*, and spelling the literal twice is the writer/reader drift
#: this module exists to prevent.
#:
#: They are the verb's own **exit codes**, named — ``0`` / ``2`` / ``1``. Keying
#: on the exit code rather than on which ``reason`` fired is what stops the two
#: from drifting: a ``reason`` added later cannot land on the wrong side of a
#: membership table, because there is no table.
#:
#: ``ok`` (exit 0) — the merge landed, the ticket was confirmed Done, the run
#: closed. The default on :class:`CloseEventData`, so a row written before #263
#: reads as what it in fact was: every historical ``close`` event is a landed
#: close. The same string as :data:`REVIEW_OUTCOME_OK` deliberately, so
#: "attempts vs successes" across verbs stays one predicate.
CLOSE_OUTCOME_OK = "ok"
#: ``refused`` (exit 2) — the gate declined **before any side effect**. Nothing
#: happened, which is exactly what separates it from ``failed``.
CLOSE_OUTCOME_REFUSED = "refused"
#: ``failed`` (exit 1) — the verb ended in error. The merge may or may not have
#: landed; ``merged_sha`` answers that, not this field.
CLOSE_OUTCOME_FAILED = "failed"

#: ``close``'s counterpart to :data:`REVIEW_UNEXPECTED_REASON`, for the raise
#: sites carrying no ``reason`` of their own (an unreadable HEAD, a merge
#: conflict, a rejected push, a failed ledger write, an unconfigured tracker).
#: Same value as ``review``'s deliberately: one vocabulary across the telemetry
#: family, so a cross-verb aggregate reads one literal.
CLOSE_UNEXPECTED_REASON = "unexpected_error"


class ReviewEventData(BaseModel):
    """Payload of a ``review`` event.

    The close gate (:func:`harness.cli.close._evaluate_gate`) reads
    ``reviewed_sha`` + ``verdict`` back out of this payload to decide whether the
    worktree HEAD is covered by a pass — the load-bearing lifecycle coupling. The
    three ``str | None`` fields mirror the verb's ``if x is not None`` optional
    keys: dump with ``model_dump(exclude_none=True)`` so an unset optional stays
    absent from the JSON exactly as before.

    The ``gate_*`` fields are the verify-gate evidence (CAL-1082) — what makes a
    recorded ``pass`` mean "the gate ran and was green" rather than "a reviewer
    read the diff". The orchestrator runs the gate and reports the result; the
    verb records it here, bound to ``reviewed_sha``. They are **flat**, not
    nested under a sub-object, because
    :func:`_field_path` derives only top-level ``$.<field>`` paths and the close
    gate reads one of them. ``gate_ran`` is a non-optional bool, so it survives
    ``exclude_none=True`` and is always present on a new event; on a *pre-existing*
    event the key is simply absent, ``json_extract`` returns ``NULL``, and the
    close backstop reads that as "no evidence" and refuses. Fail-safe, no
    migration.

    ``design_context`` (#212) is the same shape for the design linkage: a
    non-optional bool recording whether this review actually saw the run's
    design. A review can legitimately run without it (the design stage failed,
    or the caller supplied no ``--design-file``), so it is *recorded* rather
    than warned about — which makes "did the linkage stop working?" a ledger
    question instead of a console-noise one. Nothing gates on it: it is audit,
    where the enforcement lives on the ``design`` event's presence.

    ``design_context_reason`` (AC-1, #247) is the machine-readable *why* behind
    a ``False`` ``design_context``: one of the
    :data:`~harness.cli.review_protocol.DesignContextReason` values
    (``design_failed`` / ``not_supplied`` / ``unreadable`` / ``hash_mismatch``).
    Optional and absent whenever ``design_context`` is ``True`` — a success has
    no reason to record — and on any event written before this field existed.
    Distinguishing the reasons closes the gap where "never passed
    ``--design-file``" and "passed one the container could not read" recorded
    identically: before, only the stderr warning (easy to miss in captured
    output) told the two apart, and only for the read-failure case.

    ``inherited_from`` (#259) is the ``run_id`` of the run whose passing review
    this event carries forward, set only when ``harness review`` took ADR 0008's
    inherit path — a resumed run whose HEAD is the exact commit a predecessor
    already passed. On an inherited event every field describing *the review* is
    the source's, carried verbatim: ``reviewed_sha`` (the SHA binding the close
    gate rests on), the ``gate_*`` evidence (without which ``close`` refuses the
    inherited pass ``no_gate_evidence``), and the ``engine`` that produced the
    verdict. Only ``run_id``, ``created_at`` and this field describe the
    inheritance.

    It is also what keeps the spend breakers honest: ``review``'s cycle counter
    excludes events carrying it (:data:`REVIEW_INHERITED_FROM_PATH`), because an
    inherited pass runs no engine and so spends nothing there is a budget for.

    ``outcome`` (#262) is the discriminator that makes this event type's
    *denominator* readable: :data:`REVIEW_OUTCOME_OK` on this model — a verdict
    was produced — against :data:`REVIEW_OUTCOME_FAILED` on
    :class:`ReviewRefusalEventData`, which records the terminal paths that write
    no verdict. It defaults to ``ok`` rather than being required so a row written
    before the field existed validates as what it in fact was: every historical
    ``review`` event is a parsed verdict.

    ``invoked_at`` and ``duration_ms`` (#262) are the latency pair, mirroring
    ``design``'s: ``invoked_at`` is when the verb began work on this run
    (captured after run resolution, before any breaker or gate check), and
    ``duration_ms`` is whole milliseconds from there to ``created_at``. Both are
    optional and absent on a pre-#262 row, and on an **inherited** event they are
    the source's like every other field describing that review — an inherited
    pass runs no engine, so minting a fresh duration for it would record time
    nothing spent.
    """

    run_id: str
    reviewed_sha: str
    verdict: str
    issues: list[str]
    engine: str
    convergence_check_required: bool
    created_at: str
    gate_ran: bool
    outcome: str = REVIEW_OUTCOME_OK
    invoked_at: str | None = None
    duration_ms: int | None = None
    design_context: bool = False
    design_context_reason: str | None = None
    gate_command: str | None = None
    gate_exit_code: int | None = None
    gate_reason: str | None = None
    gate_output_tail: str | None = None
    fallback_from: str | None = None
    commit_message: str | None = None
    deferred_brief: str | None = None
    inherited_from: str | None = None


class ReviewRefusalEventData(BaseModel):
    """Payload of a ``review`` event that ended **without** a verdict (#262).

    ``review`` used to write an event only when a verdict parsed, so every other
    terminal path — an engine timeout, a tripped spend breaker, ``no_design``,
    ``no_gate_evidence``, a red gate, the sandbox wall — left no trace at all.
    The ledger held verdicts and no denominator: "how often does review succeed?"
    was unanswerable rather than merely slow. This is the row those paths write.

    **The same ``event_type``, a second model.** ADR 0009 keeps the type
    ``review`` and discriminates on ``outcome``, exactly as ``design`` does on
    ``status``. What differs from ``design`` is the *shape* of the split:
    ``design``'s two shapes fit one model because only two optional fields vary,
    whereas the fields a refusal cannot have — ``reviewed_sha``, ``verdict``,
    ``issues``, ``engine``, ``gate_ran`` — are precisely the ones the close gate
    and the inherit resolver read. Loosening those to ``str | None`` on
    :class:`ReviewEventData` to accommodate a shape that never carries them would
    re-open the CAL-1012 hazard the typed contract exists to close: nothing would
    then catch a *success* written without the SHA the gate binds to. So the
    required fields stay required, and the refusal shape lives here.

    Carrying **no ``verdict`` key** is what keeps the close gate exactly as wide
    as it was: :func:`~harness.cli._review_gate.certify_head` filters
    ``json_extract(data_json, '$.verdict') = 'pass'``, which a missing key
    answers ``NULL`` — so a refusal row can never satisfy it, whatever its
    ``reason``. That is enforcement by absence, and it is pinned by test rather
    than left to inspection.

    ``reason`` is the verb's own machine-readable literal — ``engine_timeout``,
    ``sandbox_init_failure``, ``no_design``, ``no_gate_evidence``,
    ``gate_failed``, ``review_cycle_ceiling``, ``wall_clock_budget`` — not a new
    vocabulary. The one addition is :data:`REVIEW_UNEXPECTED_REASON`, for the
    raise sites that carry no ``reason`` of their own (a failed HEAD read, an
    engine that could not be invoked); without it those paths would record a
    ``NULL`` reason and be indistinguishable from each other in the aggregate.
    ``detail`` is the human specifics, the same ``reason``-to-branch-on /
    message-to-diagnose-from split :class:`~harness.cli._verb.VerbError` makes.
    """

    run_id: str
    outcome: str = REVIEW_OUTCOME_FAILED
    reason: str
    detail: str
    created_at: str
    invoked_at: str | None = None
    duration_ms: int | None = None


class CheckpointEventData(BaseModel):
    """Payload of a ``checkpoint`` event — the durable-WIP signal ``reclaim``
    reads (by event *presence*; the fields record the pushed branch/SHA)."""

    run_id: str
    branch: str
    pushed_sha: str
    pushed_at: str


class WorkflowFailedEventData(BaseModel):
    """Payload of a ``workflow_failed`` event (abandon / reclaim).

    ``harness status`` reads ``reason`` back out as ``failure_reason``
    (:func:`harness.cli.query_status._fetch_enriched_status`)."""

    reason: str


class CloseEventData(BaseModel):
    """Payload of a ``close`` event — the audited record of a landed run.

    No ``ticket_done`` field (#233): the confirmation is carried by a
    ``close`` event with ``outcome='ok'`` — which can only be written once the
    tracker transition is confirmed (or the repo is tracker-less) — and the
    tracker-less case is derivable from ``CONTEXT.md`` → ``tracker:``. Adding a
    field would change a locked payload for information already implied.

    That claim used to rest on the event's bare *existence*, because a landed
    close was the only thing that wrote one. #263 puts refusals under the same
    event type, so the discriminator is what keeps the claim exactly as narrow
    as it was — and the refusal shape omits ``merged_sha`` entirely, so a reader
    that keys on the merged SHA rather than on ``outcome`` cannot be widened by
    one either.

    ``outcome`` (#263) defaults to :data:`CLOSE_OUTCOME_OK` rather than being
    required, so a row written before the field existed validates as what it in
    fact was.

    ``invoked_at`` and ``duration_ms`` (#263) are the latency pair, mirroring
    ``review``'s: ``invoked_at`` is when the verb began work on this run
    (captured after run resolution, before the HEAD read or any gate check) and
    ``duration_ms`` is whole milliseconds from there to ``closed_at``. This is
    the **verb's** own latency and is not ``runs.duration_ms`` (#261), which
    measures the whole run's life from ``started_at``: one answers "how long
    does closing take", the other "how long did this ticket take".
    """

    run_id: str
    ticket: str
    merged_sha: str
    closed_at: str
    outcome: str = CLOSE_OUTCOME_OK
    invoked_at: str | None = None
    duration_ms: int | None = None


class CloseFailureEventData(BaseModel):
    """Payload of a ``close`` event that did **not** land the close (#263).

    ``close`` wrote an event only on success, so all five gate refusals —
    ``dirty_worktree``, ``no_passing_review``, ``stale_review``,
    ``no_gate_evidence``, and the untagged unconfigured-tracker exit — and the
    post-merge ticket failures left no trace. The ledger held landed merges and
    no denominator, which is why ADR 0010 had to accept a 24-excess-pass *upper
    bound* for the ``stale_review`` rate instead of measuring it. This is the row
    that produces the number.

    **The same ``event_type``, a second model** — ``review``'s split (#262), for
    the same reason applied to a different reader. The argument is weaker here
    on inspection, since no code reader ``json_extract``-s ``merged_sha`` today,
    and it still lands the same way: ``merged_sha`` is the *only* field that
    answers "did this run actually land?", so making it optional on the success
    shape would leave nothing — not mypy, not Pydantic — to catch a success
    written without it, and its absence would then be ambiguous between "refused"
    and "success that forgot". Two models make that ambiguity impossible, and
    give ``reason`` / ``detail`` the same protection in the other direction.

    Here ``merged_sha`` is optional, and **present iff the merge landed**: absent
    on every gate refusal, set on the two post-merge ticket failures and on a
    ledger-write failure after the merge. That, not ``outcome``, is what stops
    the ledger reporting a landed merge as a blocked one.

    ``reason`` is the verb's own machine-readable literal — a
    :data:`~harness.cli.close.RefusalReason` or a
    :data:`~harness.cli.close.FailureReason` — not a new vocabulary. The one
    addition is :data:`CLOSE_UNEXPECTED_REASON`, for the raise sites that carry
    no ``reason`` of their own; without it those paths would record a ``NULL``
    and be indistinguishable from each other. ``detail`` is the human specifics:
    the same ``reason``-to-branch-on / message-to-diagnose-from split
    :class:`~harness.cli._verb.VerbError` makes. It is written to the ledger
    only — never to ``CloseOutput`` or the printed refusal JSON — so the verb's
    context-economy guarantee is unchanged.

    ``created_at`` rather than the arguably more honest ``recorded_at``: it is
    the field :class:`ReviewRefusalEventData` already uses for the same instant,
    and two sibling telemetry shapes naming one quantity differently is the
    reader drift this module exists to prevent.

    ``no_run`` never reaches here. ``events.run_id`` is ``NOT NULL`` with a
    foreign key to ``runs``, and that refusal has resolved no run to anchor a row
    to; ADR 0009 accepts the gap rather than paying for it with synthetic
    ``runs`` rows. It is the one hole in the denominator, so the measured rate is
    *per resolved-run close attempt*.
    """

    run_id: str
    ticket: str
    #: No default: the writer must choose ``refused`` (exit 2) or ``failed``
    #: (exit 1) rather than inheriting whichever happened to be listed first.
    outcome: str
    reason: str
    detail: str
    created_at: str
    merged_sha: str | None = None
    invoked_at: str | None = None
    duration_ms: int | None = None


class DeferEventData(BaseModel):
    """Payload of a ``defer`` event — the audited record of a triage deferral
    (CAL-1143): the ticket set aside, why, and the Build queue it was bound to.

    No reader ``json_extract``-s these fields back out (unlike ``review``, whose
    ``reviewed_sha``/``verdict`` the close gate reads); the payload exists so the
    triage decision is inspectable in the audit trail like every other event."""

    run_id: str
    ticket: str
    reason: str
    #: The effective Build-queue scope: ``repo.project`` when configured, else the
    #: ticket's own project as the backend reports it, else ``None`` — nullable
    #: since #248 made the two triage verbs work on an unscoped repo.
    project: str | None
    needs: str
    deferred_at: str


class DesignEventData(BaseModel):
    """Payload of a ``design`` event — the design stage's recorded attempt (#211).

    ADR 0007 enforces that a design was *attempted and recorded*, not that it
    succeeded, so this payload has two shapes discriminated by ``status``:

    * ``status='ok'`` — ``design_hash`` (the design text's content hash) and
      ``grounded_sha`` (the worktree HEAD the engine studied) are set, ``reason``
      and ``detail`` absent. Together they say *which* design was produced and
      *which tree* it was grounded in.
    * ``status='failed'`` — ``reason`` (a stable machine-readable tag) and
      ``detail`` (the human specifics) are set, the two success fields absent.
      The split mirrors :class:`~harness.cli._verb.VerbError`'s own ``reason`` vs
      ``message``: one to branch on, one to diagnose from. Recording both matters
      because the *only* evidence of which failure happened is what lands here.

    ``engine`` and ``model`` are recorded on **both** shapes — a failed attempt
    should still say what was attempted. Dump with ``model_dump(exclude_none=True)``
    so the fields the other shape does not use stay absent from the JSON rather
    than reading as an explicit ``null``.

    The review verb's ``no_design`` enforcement (#212) keys on the event's
    *presence*, which is why a ``failed`` attempt satisfies it; it then reads
    ``status`` and ``design_hash`` back out (:data:`DESIGN_STATUS_KEY`,
    :data:`DESIGN_HASH_KEY`) to decide whether a design exists to review
    against, and to authenticate the text supplied for it.

    ``inherited_from`` (#258) is **additive to the ``ok`` shape**: the ``run_id``
    of the run whose design this one adopted, set only when ``harness design``
    took ADR 0008's adopt path instead of running the engine. On an adopted
    event every field describing *the design* — ``design_hash``, ``grounded_sha``,
    ``engine``, ``model``, ``designed_at`` — is the source's, carried verbatim,
    because it is the same design produced by the same engine against the same
    tree; only ``run_id``, ``invoked_at`` and this field describe the adoption.
    ``status`` stays ``'ok'`` deliberately: ``resolve_design_gate`` keys on
    ``!= 'ok'``, so a third status value would make every resumed review read an
    inherited design as a *failed* attempt and silently drop it.

    ``submit_excerpt`` and ``stdout_chars`` (#277) are additive to the
    ``failed`` shape and appear only when ``reason`` is ``no_submit`` or
    ``malformed_submit`` — the engine's own output, bounded, so a SUBMIT-parse
    failure is diagnosable from the ledger rather than being one more tally
    mark. The other failure reasons (``engine_timeout``, ``engine_error``,
    ``no_ticket_spec``) have no engine stdout in hand to quote and must stay
    absent rather than record an empty one. They are kept out of ``detail``
    deliberately: that field is human remediation prose, this is bounded
    evidence with a different reader.

    ``invoked_at`` and ``concurrent_prior_at`` (#236) are set on both shapes,
    the concurrent-invocation detector's evidence: ``invoked_at`` is when this
    attempt began (captured before any engine work), and ``concurrent_prior_at``
    — present only when a stray overlapping invocation is detected — is the
    ``timestamp`` of the run's prior ``design`` event that finished *after*
    this one started. A legitimate sequential re-run, whose prior event
    predates ``invoked_at``, never sets it.
    """

    run_id: str
    status: str
    engine: str
    model: str
    designed_at: str
    design_hash: str | None = None
    grounded_sha: str | None = None
    reason: str | None = None
    detail: str | None = None
    invoked_at: str | None = None
    concurrent_prior_at: str | None = None
    inherited_from: str | None = None
    submit_excerpt: str | None = None
    stdout_chars: int | None = None


class ReleaseEventData(BaseModel):
    """Payload of a ``release`` event — the audited record of a decision-sweep
    release (#193): the held ticket, the hold kind it was released from, and
    the Build queue it was bound to. The ``defer`` event's mirror image.

    No reader ``json_extract``-s these fields back out; the payload exists so
    the release is inspectable in the audit trail like every other event."""

    run_id: str
    ticket: str
    #: The effective Build-queue scope — nullable since #248, exactly as
    #: :class:`DeferEventData`'s field.
    project: str | None
    needs: str
    released_at: str


class ReclaimUndoneEventData(BaseModel):
    """Payload of a ``reclaim_undone`` event — a reclaim reversed as a confirmed
    false positive (#254).

    Appended *after* the run's surviving ``workflow_failed{reason: reclaimed}``:
    the ledger is append-only, so the audit trail shows both the reclamation and
    its reversal. Consequence to read deliberately — ``harness status`` on a
    re-opened run reports ``failure_reason='reclaimed'`` (it reads the newest
    ``workflow_failed``) while ``status`` reads ``open``. The **row** is
    authoritative; the log is the history, including the mistake.

    No reader ``json_extract``-s these fields; the payload exists so the reversal
    is inspectable like every other event. The event's *presence* carries two
    meanings on its own: that this run was un-reclaimed (which is how
    ``--undo`` tells a completed reversal from a run that was never cancelled),
    and — being the newest ledger activity — that the restored run is live, so the
    next ``--stale`` sweep cannot immediately re-reclaim it."""

    run_id: str
    ticket: str
    undone_at: str


def _field_name(model: type[BaseModel], field: str) -> str:
    """The model's field name, verified to exist.

    Single-sources the key: a field rename that forgets to update a derived
    constant raises here at import — surfacing the drift as an error instead of a
    silent runtime mis-read.
    """
    if field not in model.model_fields:
        raise ValueError(f"{model.__name__} has no field {field!r}")
    return field


def _field_path(model: type[BaseModel], field: str) -> str:
    """The SQLite ``json_extract`` path (``$.<field>``) for a model field,
    verified to exist (see :func:`_field_name`)."""
    return f"$.{_field_name(model, field)}"


#: ``json_extract`` paths the close gate reads from a ``review`` payload.
REVIEW_REVIEWED_SHA_PATH = _field_path(ReviewEventData, "reviewed_sha")
REVIEW_VERDICT_PATH = _field_path(ReviewEventData, "verdict")

#: ``json_extract`` paths the close gate reads for the verify-gate evidence
#: backstop (CAL-1082): a pass whose ``gate_ran`` is absent/false — and whose
#: ``gate_reason`` is not the honest "no gate configured" — is refused.
REVIEW_GATE_RAN_PATH = _field_path(ReviewEventData, "gate_ran")
REVIEW_GATE_REASON_PATH = _field_path(ReviewEventData, "gate_reason")

#: The path ``review``'s cycle counter excludes on (#259): an inherited pass ran
#: no engine, so counting it against the review-cycle ceiling would charge a run
#: for spend it never incurred.
REVIEW_INHERITED_FROM_PATH = _field_path(ReviewEventData, "inherited_from")

#: The ``outcome`` discriminator (#262) and its two values. The path is derived
#: from :class:`ReviewEventData` and the *same* field name is asserted on
#: :class:`ReviewRefusalEventData`, so the two shapes cannot drift apart into
#: separate keys — which would silently split the denominator in half.
REVIEW_OUTCOME_PATH = _field_path(ReviewEventData, "outcome")
_REVIEW_REFUSAL_OUTCOME_PATH = _field_path(ReviewRefusalEventData, "outcome")
if REVIEW_OUTCOME_PATH != _REVIEW_REFUSAL_OUTCOME_PATH:  # pragma: no cover - import guard
    raise ValueError(
        "the review success and refusal payloads must discriminate on the same "
        f"field: {REVIEW_OUTCOME_PATH} != {_REVIEW_REFUSAL_OUTCOME_PATH}"
    )

#: The ``outcome`` discriminator (#263) on the ``close`` payloads, derived and
#: cross-asserted exactly as ``review``'s is: the success and refusal shapes must
#: name the same key, or the denominator this exists to produce would split in
#: two without anything failing.
CLOSE_OUTCOME_PATH = _field_path(CloseEventData, "outcome")
_CLOSE_FAILURE_OUTCOME_PATH = _field_path(CloseFailureEventData, "outcome")
if CLOSE_OUTCOME_PATH != _CLOSE_FAILURE_OUTCOME_PATH:  # pragma: no cover - import guard
    raise ValueError(
        "the close success and failure payloads must discriminate on the same "
        f"field: {CLOSE_OUTCOME_PATH} != {_CLOSE_FAILURE_OUTCOME_PATH}"
    )

#: The path the ``stale_review`` rate query reads (#263) — the measurement this
#: telemetry exists for. Derived from the failure model, which is the only shape
#: that carries a ``reason``.
CLOSE_REASON_PATH = _field_path(CloseFailureEventData, "reason")

#: The payload key ``harness status`` reads from a ``workflow_failed`` payload.
WORKFLOW_FAILED_REASON_KEY = _field_name(WorkflowFailedEventData, "reason")

#: The payload keys ``review``'s design linkage reads from an already-parsed
#: ``design`` payload (#212): ``status`` discriminates the two shapes (a
#: ``failed`` attempt still satisfies the ``no_design`` check, ADR 0007 D4), and
#: ``design_hash`` authenticates the design text the orchestrator hands back
#: before it reaches the review engine's prompt. Bare field names because that
#: gate indexes an already-parsed ``dict`` (#217).
DESIGN_STATUS_KEY = _field_name(DesignEventData, "status")
DESIGN_HASH_KEY = _field_name(DesignEventData, "design_hash")

#: The same two keys as ``json_extract`` paths, for the one reader that *is* SQL:
#: ``design``'s adopt path (#258) selects a prior ``status='ok'`` event by its
#: ``design_hash`` across the ticket's runs. Derived from the same fields as the
#: bare-name constants above, so a rename cannot leave the two readers disagreeing.
DESIGN_STATUS_PATH = _field_path(DesignEventData, "status")
DESIGN_HASH_PATH = _field_path(DesignEventData, "design_hash")
