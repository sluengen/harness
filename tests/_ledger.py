"""Shared test ledger seeders.

:func:`seed_design_event` appends one ``design`` event to a run.
:func:`seed_premigration_ledger` builds a ledger as it stood before #352.

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

import aiosqlite

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
    inherited_from: str | None = None,
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
        # #258's adopt shape: additive to the ``ok`` payload, naming the run
        # whose design this one recovered rather than produced (#352 needs it
        # to seed a complex run whose design was adopted, not engine-made).
        inherited_from=inherited_from,
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


#: The ``runs`` table exactly as it stood **before** #352 added ``assurance`` and
#: ``assurance_reason``. ``CREATE TABLE IF NOT EXISTS`` cannot express a column
#: drop, so the old shape is written out; this is what every existing checkout's
#: ledger looks like on the first verb invocation after upgrading.
_PREMIGRATION_RUNS_DDL = (
    "CREATE TABLE runs ("
    "run_id TEXT PRIMARY KEY, workflow_name TEXT NOT NULL, "
    "workflow_version INTEGER NOT NULL, status TEXT NOT NULL, "
    "state_json TEXT NOT NULL, inputs_json TEXT NOT NULL, "
    "base_branch TEXT, worktree_branch TEXT, exit_code INTEGER, "
    "started_at TEXT NOT NULL, completed_at TEXT, duration_ms INTEGER, "
    "pid INTEGER, ticket TEXT, worktree_path TEXT, resumed_from TEXT)"
)

_PREMIGRATION_EVENTS_DDL = (
    "CREATE TABLE events ("
    "id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT NOT NULL "
    "REFERENCES runs(run_id) ON DELETE CASCADE, node_id TEXT, "
    "event_type TEXT NOT NULL, timestamp TEXT NOT NULL, duration_ms INTEGER, "
    "data_json TEXT NOT NULL DEFAULT '{}')"
)


def seed_premigration_ledger(
    db_path: Path,
    *,
    run_id: str,
    worktree_path: str,
    ticket: str,
    started_at: str,
) -> None:
    """A ledger with one open run and **no** assurance columns (#352).

    The fixture that catches the defect a migration test cannot: ``_migrate``
    runs only from ``store.init_db``, and a test that calls ``init_db`` itself
    has already healed the ledger before the verb ever reads it. Driving a verb
    against *this* is what exercises the real ordering — whether the first read
    of a new column happens before or after the migration that adds it.
    """
    db_path.parent.mkdir(parents=True, exist_ok=True)

    async def _build() -> None:
        async with aiosqlite.connect(db_path) as conn:
            await conn.execute(_PREMIGRATION_RUNS_DDL)
            await conn.execute(_PREMIGRATION_EVENTS_DDL)
            await conn.execute(
                "INSERT INTO runs (run_id, workflow_name, workflow_version, status, "
                "state_json, inputs_json, base_branch, worktree_path, worktree_branch, "
                "ticket, started_at) "
                "VALUES (?, '', 0, 'open', '{}', '{}', 'dev', ?, ?, ?, ?)",
                (run_id, worktree_path, f"harness/{run_id}", ticket, started_at),
            )
            await conn.commit()

    run_sync(_build())
