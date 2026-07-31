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
    """

    run_id: str
    reviewed_sha: str
    verdict: str
    issues: list[str]
    engine: str
    convergence_check_required: bool
    created_at: str
    gate_ran: bool
    design_context: bool = False
    design_context_reason: str | None = None
    gate_command: str | None = None
    gate_exit_code: int | None = None
    gate_reason: str | None = None
    gate_output_tail: str | None = None
    fallback_from: str | None = None
    commit_message: str | None = None
    deferred_brief: str | None = None


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

    No ``ticket_done`` field (#233): the event's *existence* now carries the
    confirmation — a ``close`` event can only be written once the tracker
    transition is confirmed (or the repo is tracker-less) — and the
    tracker-less case is derivable from ``CONTEXT.md`` → ``tracker:``. Adding a
    field would change a locked payload for information already implied.
    """

    run_id: str
    ticket: str
    merged_sha: str
    closed_at: str


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
