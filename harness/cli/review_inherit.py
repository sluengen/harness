"""The review stage's inherit path — carry a prior pass instead of re-earning it.

``close``'s gate reads ``review`` events ``WHERE run_id = ?``. A run resumed with
``harness start --resume`` mints a **new** ``run_id`` (deliberately — the spend
breakers need a fresh window), so a predecessor's pass is invisible to it. Even
when the resumed worktree's HEAD is the *exact commit* that passed — the tree
that would merge byte-identical to the tree that was reviewed — the run pays for
a full engine review of an unchanged diff, and the operator pays for the gate run
that precedes it.

ADR 0008's fix is **not** to widen the gate query. Certification may cross a run
boundary only as an event recorded on the *inheriting* run, naming its source and
the evidence it rests on — so gates stay run-scoped and nothing reads across
runs. This module decides whether that inheritance is warranted; the verb records
it.

**The six conditions**, all required (ADR 0008 D3):

1. the run's ``resumed_from`` is set — it recovered a preserved WIP branch.
   Provenance is required, not merely a SHA match: a clean-start run's HEAD could
   coincide with an old pass only through a recreated branch, and gating on
   ``resumed_from`` removes that reasoning entirely rather than weighing it;
2. the run recorded a ``design`` attempt. The short-circuit may skip *work*, never
   a refusal that is about **this** run's own state — and ADR 0007 D3's
   ``no_design`` is exactly that. Declining costs nothing: the normal path then
   raises it precisely as today;
3. the caller supplied no **red** gate evidence (``--gate-exit`` absent, or 0).
   An orchestrator that ran the gate and got red must not have that tree
   certified. HEAD being byte-identical to a green-passed tree makes the red
   result a flake or an environment difference — but ``close`` reads only the
   ledger, so certifying it would land a merge on a tree whose gate is red *now*;
4. the worktree is **clean** and HEAD resolves. The whole safety argument is that
   the certified tree is the reviewed tree; uncommitted edits break that without
   moving HEAD, so a SHA match alone would assert something false;
5. some **other** run **for the same ticket** holds a ``review`` event with
   ``verdict='pass'`` and ``reviewed_sha == HEAD``, and that event is **not
   itself inherited**. Same-ticket because inheritance follows the change spec
   (the rule ADR 0007 D2 sets for the design, which
   :mod:`harness.cli.design_adopt` already applies); another run because a run
   inheriting from itself is a re-review that never reviewed; not-inherited so
   ``inherited_from`` always names a run whose engine actually produced the pass —
   a chain would still be sound, but it makes provenance a walk instead of a read
   and costs nothing to exclude, since the original event stays in the same ledger
   matched by the same ticket and SHA;
6. that source pass satisfies :func:`~harness.cli._review_gate.has_gate_evidence`
   — the identical predicate ``close`` will apply to the event this produces.
   Not belt-and-braces: without it the inherit path hands ``close`` a pass it then
   refuses ``no_gate_evidence``, leaving the run neither reviewed nor closable.

Any of them failing declines, and the verb reviews exactly as before. The
asymmetry is deliberate: declining costs one review cycle, wrongly inheriting
opens the close gate on a tree nothing verified.

Split from :mod:`harness.cli.review` on the :mod:`harness.cli.design_adopt`
precedent — the verb keeps the flow, a cohesive decision gets its own module
rather than pushing a watchlisted verb further past its size justification.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any, NamedTuple, get_args

from pydantic import ValidationError

from harness._git import rev_parse_head
from harness.cli._review_gate import has_gate_evidence
from harness.cli._runs import read_run_resumed_from
from harness.cli.review_protocol import Engine
from harness.close_merge import worktree_porcelain
from harness.events.payloads import (
    REVIEW_INHERITED_FROM_PATH,
    REVIEW_REVIEWED_SHA_PATH,
    REVIEW_VERDICT_PATH,
    ReviewEventData,
)
from harness.state import store

__all__ = ["InheritedReview", "has_gate_evidence", "resolve_inheritance"]

#: The engine names the printed verdict's ``engine`` field may carry. A source
#: payload is ledger data, not a typed value, so one outside this set declines
#: rather than widening :class:`~harness.cli.review.ReviewOutput`'s literal to
#: ``str`` — which every downstream reader would then have to handle.
_KNOWN_ENGINES: frozenset[str] = frozenset(get_args(Engine))

#: Ceiling (seconds) for both git probes, the twin of
#: :data:`harness.cli.reclaim_closable._PROBE_TIMEOUT_SECONDS` and set for the
#: same reason. Both default to no ceiling, which is right for ``close``, where a
#: wedged git should be *visible* rather than silently reinterpreted. Here it must
#: not be: this path is an optimisation on the way to an ordinary review, so a
#: hung probe that blocked would cost the run something a run without the
#: optimisation never risked. Bounded, it degrades to "review normally".
_PROBE_TIMEOUT_SECONDS = 15


class InheritedReview(NamedTuple):
    """A prior pass authenticated and re-bound to this run, ready to record.

    ``source_run_id`` is carried out separately from ``event.inherited_from`` only
    so the verb's stderr note need not reach into the payload for it.
    """

    source_run_id: str
    event: ReviewEventData


async def resolve_inheritance(
    *,
    db_path: Path,
    run_id: str,
    ticket: str | None,
    worktree_path: Path,
    design_recorded: bool,
    gate_exit: int | None,
    created_at: str,
) -> InheritedReview | None:
    """The pass this run may inherit, or ``None`` to review normally.

    Never raises: every failure — an unresumed run, a wedged git probe, an
    unreadable ledger, a malformed payload — is a decline, and a decline is just
    the pre-#259 behaviour. The verb needs no new failure branch.

    The conditions run cheapest-first, and the two that are *about this run* come
    before the two that read another run's work: a run that must be refused
    ``no_design`` or ``gate_failed`` should reach that refusal without a ledger
    sweep first.
    """
    if await read_run_resumed_from(db_path, run_id) is None:
        return None  # (1) clean start: no predecessor whose work this continues.

    if not design_recorded:
        return None  # (2) let the normal path raise no_design, as it does today.

    if gate_exit is not None and gate_exit != 0:
        return None  # (3) the caller's own red gate is never overridden.

    head_sha = await _clean_head(worktree_path)
    if head_sha is None:
        return None  # (4) dirty, or HEAD unreadable: the SHA describes no tree.

    source = await _read_source_pass(
        db_path, ticket=ticket, exclude_run_id=run_id, head_sha=head_sha
    )
    if source is None:
        return None  # (5)/(6) no gate-evidenced pass covers this exact tree.

    source_run_id, payload = source
    return InheritedReview(
        source_run_id=source_run_id,
        # Every field describing *the review* is the source's, carried verbatim:
        # it is the same tree, reviewed by the same engine, behind the same green
        # gate. Only run_id, created_at and inherited_from describe this
        # inheritance. The gate_* copy is the load-bearing one — close applies
        # has_gate_evidence to *this* event, so dropping it would produce a pass
        # close then refuses, wedging the run neither reviewed nor closable.
        event=payload.model_copy(
            update={
                "run_id": run_id,
                "created_at": created_at,
                "inherited_from": source_run_id,
                # Not the source's, and the one apparent exception to the rule
                # above: the advisory asks whether *this* loop's fixes are
                # converging, and the inherit path evaluates no breaker and runs
                # no cycle. (It is False on every pass anyway — it is a fail-path
                # signal — so the exception costs nothing to read.)
                "convergence_check_required": False,
            }
        ),
    )


async def _clean_head(worktree_path: Path) -> str | None:
    """``HEAD`` of a **clean** worktree, or ``None``.

    Both probes are the shared public ones — :func:`harness.close_merge.worktree_porcelain`
    asks the same clean-tree question ``close`` asks before it merges, so "clean"
    means one thing across the two verbs. Both are bounded by
    :data:`_PROBE_TIMEOUT_SECONDS`, so a git call that fails **or hangs** answers
    ``None`` and declines: every uncertainty resolves toward reviewing.

    Composing the two here rather than sharing a helper with
    ``reclaim_closable``'s equivalent is deliberate: :mod:`harness._git`
    cannot host it (``close_merge`` already imports ``_git``, so the import would
    cycle) and hoisting it into ``close_merge`` would put a review-path probe in
    the merge module. What must never drift — *what counts as certified* — is
    single-sourced in :mod:`harness.cli._review_gate`; this is a two-call
    composition, not a rule.
    """
    try:
        if await asyncio.to_thread(
            worktree_porcelain, worktree_path, timeout=_PROBE_TIMEOUT_SECONDS
        ):
            return None
        return await asyncio.to_thread(
            rev_parse_head, worktree_path, timeout=_PROBE_TIMEOUT_SECONDS
        )
    except Exception:  # noqa: BLE001 — a git failure or a fired timeout declines.
        return None


async def _read_source_pass(
    db_path: Path,
    *,
    ticket: str | None,
    exclude_run_id: str,
    head_sha: str,
) -> tuple[str, ReviewEventData] | None:
    """The ``(run_id, payload)`` of a gate-evidenced ``pass`` bound to ``head_sha``.

    Scoped to **other runs for the same ticket** and to engine-produced events
    (condition 5), newest first by ``id`` — the append order every other ledger
    reader treats as authoritative.

    The gate-evidence rule (condition 6) is applied in Python rather than as a
    ``WHERE`` clause because it is :func:`has_gate_evidence`'s rule, and there is
    exactly one of it: a second copy expressed in SQL is precisely how ``close``'s
    gate would stop meaning one thing.

    A DB that cannot be read, or a payload that does not validate as a
    :class:`~harness.events.payloads.ReviewEventData`, yields ``None`` — an
    unreadable source has no opinion.
    """
    if ticket is None or not db_path.exists():
        return None
    async with (
        store.connect(db_path) as conn,
        conn.execute(
            # The json paths are the single-sourced payload-key constants
            # (CAL-1012), passed as bound parameters — SQLite accepts a bound
            # json_extract path, so this reader holds no raw path literal.
            "SELECT e.run_id, e.data_json FROM events e "
            "JOIN runs r ON r.run_id = e.run_id "
            "WHERE e.event_type = 'review' AND r.ticket = ? AND e.run_id != ? "
            "AND json_extract(e.data_json, ?) = 'pass' "
            "AND json_extract(e.data_json, ?) = ? "
            "AND json_extract(e.data_json, ?) IS NULL "
            "ORDER BY e.id DESC",
            (
                ticket,
                exclude_run_id,
                REVIEW_VERDICT_PATH,
                REVIEW_REVIEWED_SHA_PATH,
                head_sha,
                REVIEW_INHERITED_FROM_PATH,
            ),
        ) as cur,
    ):
        rows = await cur.fetchall()

    for row in rows:
        payload = _parse_payload(row[1])
        if payload is None or payload.engine not in _KNOWN_ENGINES:
            continue
        if has_gate_evidence(payload.gate_ran, payload.gate_reason):
            return (str(row[0]), payload)
    return None


def _parse_payload(raw: Any) -> ReviewEventData | None:
    """A recorded ``review`` payload as its typed model, or ``None``.

    Validating rather than indexing a ``dict`` is what makes the field-by-field
    copy above safe: a payload missing a field the copy assumes — an event from a
    harness that predates it — declines here instead of producing a half-built
    certification.
    """
    if raw is None:
        return None
    try:
        return ReviewEventData.model_validate(json.loads(str(raw)))
    except (json.JSONDecodeError, ValidationError):
        return None
