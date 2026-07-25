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
* A **reader** that ``json_extract``-s a key imports the field's path/key
  constant from here (:data:`REVIEW_REVIEWED_SHA_PATH`, :data:`REVIEW_VERDICT_PATH`,
  :data:`WORKFLOW_FAILED_REASON_KEY`). Each constant is derived from the model via
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
    """

    run_id: str
    reviewed_sha: str
    verdict: str
    issues: list[str]
    engine: str
    convergence_check_required: bool
    created_at: str
    gate_ran: bool
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
    """Payload of a ``close`` event — the audited record of a landed run."""

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
    project: str
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

    No reader ``json_extract``-s these fields back out today: the review verb's
    ``no_design`` enforcement (#212) keys on the event's *presence*, which is why
    a ``failed`` attempt satisfies it.
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


class ReleaseEventData(BaseModel):
    """Payload of a ``release`` event — the audited record of a decision-sweep
    release (#193): the held ticket, the hold kind it was released from, and
    the Build queue it was bound to. The ``defer`` event's mirror image.

    No reader ``json_extract``-s these fields back out; the payload exists so
    the release is inspectable in the audit trail like every other event."""

    run_id: str
    ticket: str
    project: str
    needs: str
    released_at: str


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
