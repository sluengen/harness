"""Shared test ledger seeders.

:func:`seed_design_event` appends one ``design`` event to a run.

Since #212 ``review`` refuses a run with no recorded design attempt
(``reason=no_design``, ADR 0007 D3), so every test that drives a review through
to its engine has to seed one first — a need that landed in four test modules at
once, which is why the helper lives here rather than being pasted into each. It
is the ``tests/_gitutil.init_repo`` pattern: a precondition the verbs gained,
satisfied in one place.

Seeding the ``ok`` shape by default is deliberate. A test that says nothing
about the design stage wants the stage to be a non-event, and ``ok`` is what a
healthy run records; the tests that care about the *other* shapes ask for them
explicitly (``status="failed"``, or no call at all for the refusal itself), in
``test_review_design_linkage.py``.
"""

from __future__ import annotations

from pathlib import Path

from harness.events.payloads import DesignEventData
from harness.state import store
from tests._asyncutil import run_sync

DEFAULT_DESIGNED_AT = "2026-07-26T00:00:00Z"


def seed_design_event(
    db_path: Path,
    run_id: str,
    *,
    status: str = "ok",
    design_hash: str | None = None,
    grounded_sha: str = "basesha",
    timestamp: str = DEFAULT_DESIGNED_AT,
    duration_ms: int | None = None,
) -> None:
    """Append one ``design`` event for ``run_id``, satisfying ``review``'s check.

    ``duration_ms`` seeds the event **column** (#264) — the verb's own latency.
    It defaults to ``None``, the shape every row written before #264 carries, so
    existing fixtures are unaffected.

    ``status="ok"`` records a produced design (``design_hash`` identifies it —
    pass :func:`~harness.cli.design_protocol.design_content_hash` of the text a
    test will hand to ``--design-file``); ``status="failed"`` records an
    attempt that produced none, which satisfies the check just the same
    (ADR 0007 D4).

    The payload is built through :class:`~harness.events.payloads.DesignEventData`
    rather than a dict literal, so a field rename breaks these fixtures at type
    level exactly as it breaks the verb.
    """
    data = DesignEventData(
        run_id=run_id,
        status=status,
        engine="claude",
        model="opus",
        designed_at=timestamp,
        design_hash=design_hash if status == "ok" else None,
        grounded_sha=grounded_sha if status == "ok" else None,
        reason=None if status == "ok" else "engine_timeout",
        detail=None if status == "ok" else "the engine was killed",
    )

    async def _insert() -> None:
        async with store.connect(db_path) as conn:
            await conn.execute(
                "INSERT INTO events "
                "(run_id, event_type, timestamp, duration_ms, data_json) "
                "VALUES (?, 'design', ?, ?, ?)",
                (
                    run_id,
                    timestamp,
                    duration_ms,
                    data.model_dump_json(exclude_none=True),
                ),
            )
            await conn.commit()

    run_sync(_insert())
