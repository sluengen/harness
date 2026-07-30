"""The design stage's adopt path — inherit a prior design instead of buying one.

A reclaimed ticket re-picked with ``harness start --resume`` mints a **new**
``run_id`` (deliberately — the spend breakers need a fresh window), and
``review``'s design gate is run-scoped. So the resumed run had to re-pay for an
Opus call producing a design that was already on the ticket, and — worse — was
handed working code produced against a design it was then forbidden to see,
re-deriving intent mid-build. That is the exact failure ADR 0007 exists to
prevent.

ADR 0008's fix is **not** to widen the gate query. Certification may cross a run
boundary only as an event recorded on the *inheriting* run, naming its source and
the evidence it rests on — so gates stay run-scoped and nothing reads across
runs. This module decides whether that inheritance is warranted; the verb records
it.

**The four conditions**, all required (ADR 0008, proposal F2):

1. the run's ``resumed_from`` is set — it recovered a preserved WIP branch;
2. the ticket carries a design comment the parser can recover;
3. the recomputed content hash of the recovered text equals the hash the comment
   states — the comment is mutable, so its claim is checked, not trusted;
4. that hash matches a ``status='ok'`` ``design`` event on another run **for the
   same ticket** — so adoption rests on a recorded event, not on comment text
   alone (ADR 0008 clause (a): verifiable from another recorded event).

Any of them failing declines, and the verb runs the engine exactly as before.
The asymmetry is deliberate: declining costs one Opus call, wrongly adopting
hands the session a design that does not describe the tree.

Split from :mod:`harness.cli.design` on the :mod:`harness.cli.design_tracker`
precedent — the verb keeps the flow, a cohesive concern gets its own module
rather than pushing the verb further past its size justification.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, NamedTuple

from harness.cli.design_protocol import design_content_hash
from harness.cli.design_tracker import fetch_prior_design, read_run_resumed_from
from harness.events.payloads import (
    DESIGN_HASH_PATH,
    DESIGN_STATUS_PATH,
    DesignEventData,
)
from harness.state import store

__all__ = ["AdoptedDesign", "resolve_adoption"]


class AdoptedDesign(NamedTuple):
    """A design recovered and authenticated, ready for the verb to record.

    ``design_markdown`` is the recovered text — the whole point of adopting
    rather than merely satisfying the gate, since it is what the build session
    implements against. ``event`` is the ``design`` payload to append, already
    carrying the source's provenance.
    """

    design_markdown: str
    event: DesignEventData


async def resolve_adoption(
    *,
    repo_root: Path,
    db_path: Path,
    run_id: str,
    ticket: str | None,
    invoked_at: str,
) -> AdoptedDesign | None:
    """The design this run may inherit, or ``None`` to run the engine.

    Never raises: every failure — an unresumed run, an unreadable ticket, an
    edited comment, a hash with no recorded event behind it — is a decline, and a
    decline is just the pre-#258 behaviour. The verb needs no new failure branch.
    """
    if await read_run_resumed_from(db_path, run_id) is None:
        return None  # (1) clean start: the tree that design described is gone.

    parsed = await fetch_prior_design(repo_root, ticket)
    if parsed is None or parsed.design_hash is None:
        return None  # (2) nothing recoverable, or nothing to authenticate against.

    if design_content_hash(parsed.design_markdown) != parsed.design_hash:
        return None  # (3) the comment body no longer hashes to its own claim.

    source = await _read_source_design_event(
        db_path, ticket=ticket, exclude_run_id=run_id, design_hash=parsed.design_hash
    )
    if source is None:
        return None  # (4) the claim rests on no recorded design event.

    source_run_id, payload = source
    return AdoptedDesign(
        design_markdown=parsed.design_markdown,
        # Every field describing *the design* is the source's, carried verbatim:
        # it is the same design, produced by the same engine, against the same
        # tree. Only run_id, invoked_at and inherited_from describe this
        # adoption. Re-stamping grounded_sha to the resumed HEAD in particular
        # would assert a study that never happened.
        event=DesignEventData(
            run_id=run_id,
            status="ok",
            engine=str(payload.get("engine") or ""),
            model=str(payload.get("model") or ""),
            designed_at=str(payload.get("designed_at") or ""),
            invoked_at=invoked_at,
            design_hash=parsed.design_hash,
            grounded_sha=payload.get("grounded_sha"),
            inherited_from=source_run_id,
        ),
    )


async def _read_source_design_event(
    db_path: Path,
    *,
    ticket: str | None,
    exclude_run_id: str,
    design_hash: str,
) -> tuple[str, dict[str, Any]] | None:
    """The ``(run_id, payload)`` of a recorded ``ok`` design with this hash.

    Scoped to **other runs for the same ticket**: inheritance follows the change
    spec (ADR 0007 D2 — the design "lives and dies with the change spec"), so a
    hash recorded against a different ticket is not a source however well it
    matches. Excluding this run matters too — without it a re-run of ``design``
    on an already-adopted run would find its own event and inherit from itself.

    Newest-first by ``id`` (append order), the authority rule every other design
    reader uses. A DB that cannot be read yields ``None``, which declines —
    fail-safe toward running the engine.
    """
    if ticket is None or not db_path.exists():
        return None
    async with (
        store.connect(db_path) as conn,
        conn.execute(
            # The json paths are the single-sourced payload-key constants, passed
            # as bound parameters — SQLite accepts a bound json_extract path, so
            # this reader holds no raw ``$.<key>`` literal (the CAL-1012 rule).
            "SELECT e.run_id, e.data_json FROM events e "
            "JOIN runs r ON r.run_id = e.run_id "
            "WHERE e.event_type = 'design' AND r.ticket = ? AND e.run_id != ? "
            "AND json_extract(e.data_json, ?) = 'ok' "
            "AND json_extract(e.data_json, ?) = ? "
            "ORDER BY e.id DESC LIMIT 1",
            (ticket, exclude_run_id, DESIGN_STATUS_PATH, DESIGN_HASH_PATH, design_hash),
        ) as cur,
    ):
        row = await cur.fetchone()
    if row is None or row[1] is None:
        return None
    try:
        payload = json.loads(str(row[1]))
    except json.JSONDecodeError:
        return None
    return (str(row[0]), payload) if isinstance(payload, dict) else None
