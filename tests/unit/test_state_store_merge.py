"""Tests for H-010 — type-driven merge state store.

See SPEC §4.8 (state store responsibilities), §7 (merge semantics +
notes bounding), §12 (events row).

The unit under test is the pair of module-level helpers
:func:`harness.state.store.read_state` and
:func:`harness.state.store.update_state`. They are the engine's only
sanctioned read/write path for ``runs.state_json``.

Tests cover three groups:

* read path (AC1..AC3)
* update path — basic merge dispatch (AC4..AC10)
* update path — notes bounding (AC11..AC14)
* events emission (AC15..AC17)
* concurrency / single-transaction read-modify-write (AC18)
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime
from pathlib import Path
from typing import Any

import aiosqlite
import pytest
from pydantic import Field, create_model

from harness.state import store
from harness.state.schema import BaseState
from harness.state.store import (
    NOTES_MAX_CHARS,
    NOTES_MAX_ENTRIES,
    StateStoreError,
    read_state,
    update_state,
)

# ---------------------------------------------------------------------------
# Fixtures + helpers
# ---------------------------------------------------------------------------


def _base_state_kwargs() -> dict[str, object]:
    """Minimum valid kwargs for BaseState — used to construct the
    initial state_json payload before insert."""
    return {
        "run_id": "R1",
        "workflow_name": "wf",
        "base_branch": "staging",
        "artifacts_dir": "/tmp/x",
        "started_at": datetime(2026, 5, 8, 12, 0, 0).isoformat(),
        "notes": [],
    }


def _make_schema(**extra: Any) -> type[BaseState]:
    """Build a derived state schema on the fly.

    Each ``extra`` entry is ``name=(annotation, default)`` exactly the
    way :func:`pydantic.create_model` wants it. Returns a subclass of
    BaseState so the merge code sees the same shape it does in
    production (where H-009 builds derived classes via ``create_model``).
    """
    cls: type[BaseState] = create_model(  # type: ignore[call-overload]
        "DerivedState",
        __base__=BaseState,
        **extra,
    )
    return cls


async def _init_db_with_run(
    db_path: Path, run_id: str = "R1", state: dict[str, object] | None = None
) -> None:
    await store.init_db(db_path)
    payload = state if state is not None else _base_state_kwargs()
    async with store.connect(db_path) as conn:
        await conn.execute(
            "INSERT INTO runs (run_id, workflow_name, workflow_version, status, "
            "state_json, inputs_json, started_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (run_id, "wf", 1, "running", json.dumps(payload), "{}", "2026-05-08T00:00:00Z"),
        )
        await conn.commit()


async def _read_state_json(db_path: Path, run_id: str = "R1") -> dict[str, object]:
    async with store.connect(db_path) as conn, conn.execute(
        "SELECT state_json FROM runs WHERE run_id = ?", (run_id,)
    ) as cur:
        row = await cur.fetchone()
        assert row is not None
        return json.loads(row[0])  # type: ignore[no-any-return]


async def _count_events(db_path: Path) -> int:
    async with aiosqlite.connect(db_path) as conn, conn.execute(
        "SELECT COUNT(*) FROM events"
    ) as cur:
        row = await cur.fetchone()
        assert row is not None
        return int(row[0])


async def _fetch_events(db_path: Path) -> list[dict[str, Any]]:
    async with aiosqlite.connect(db_path) as conn:
        conn.row_factory = aiosqlite.Row
        async with conn.execute(
            "SELECT run_id, event_type, data_json FROM events ORDER BY id"
        ) as cur:
            return [dict(r) for r in await cur.fetchall()]


# ---------------------------------------------------------------------------
# AC1..AC3 — read path
# ---------------------------------------------------------------------------


async def test_ac1_read_state_for_missing_run_raises(tmp_path: Path) -> None:
    db_path = tmp_path / "h.db"
    await store.init_db(db_path)
    schema = _make_schema()
    with pytest.raises(StateStoreError, match="ghost"):
        await read_state("ghost", schema, db_path=db_path)


async def test_ac2_read_state_round_trips_full_state(tmp_path: Path) -> None:
    db_path = tmp_path / "h.db"
    payload = _base_state_kwargs() | {"notes": ["seed-1", "seed-2"]}
    await _init_db_with_run(db_path, state=payload)
    schema = _make_schema()
    s = await read_state("R1", schema, db_path=db_path)
    assert s.run_id == "R1"
    assert s.workflow_name == "wf"
    assert s.base_branch == "staging"
    assert s.notes == ["seed-1", "seed-2"]


async def test_ac3_read_state_invalid_payload_raises(tmp_path: Path) -> None:
    db_path = tmp_path / "h.db"
    # state_json missing required fields -> validation must fail.
    bad: dict[str, object] = {"run_id": "R1"}
    await _init_db_with_run(db_path, state=bad)
    schema = _make_schema()
    with pytest.raises(StateStoreError):
        await read_state("R1", schema, db_path=db_path)


# ---------------------------------------------------------------------------
# AC4..AC9 — update path: scalar overwrite, list append, unknown, validation
# ---------------------------------------------------------------------------


async def test_ac4_scalar_overwrite_last_writer_wins(tmp_path: Path) -> None:
    db_path = tmp_path / "h.db"
    payload = _base_state_kwargs() | {"foo": "baseline"}
    await _init_db_with_run(db_path, state=payload)
    schema = _make_schema(foo=(str | None, None))

    new = await update_state("R1", schema, db_path=db_path, foo="bar")
    assert new.foo == "bar"  # type: ignore[attr-defined]
    persisted = await _read_state_json(db_path)
    assert persisted["foo"] == "bar"


async def test_ac5_list_append_does_not_replace(tmp_path: Path) -> None:
    db_path = tmp_path / "h.db"
    payload = _base_state_kwargs() | {"items": ["a", "b"]}
    await _init_db_with_run(db_path, state=payload)
    schema = _make_schema(items=(list[str], Field(default_factory=list)))

    new = await update_state("R1", schema, db_path=db_path, items=["x"])
    assert new.items == ["a", "b", "x"]  # type: ignore[attr-defined]
    persisted = await _read_state_json(db_path)
    assert persisted["items"] == ["a", "b", "x"]


async def test_ac6_consecutive_updates_chain_appends(tmp_path: Path) -> None:
    db_path = tmp_path / "h.db"
    payload = _base_state_kwargs() | {"items": ["a"]}
    await _init_db_with_run(db_path, state=payload)
    schema = _make_schema(items=(list[str], Field(default_factory=list)))

    await update_state("R1", schema, db_path=db_path, items=["b"])
    await update_state("R1", schema, db_path=db_path, items=["c"])

    persisted = await _read_state_json(db_path)
    assert persisted["items"] == ["a", "b", "c"]


async def test_ac7_multi_field_update_is_atomic(tmp_path: Path) -> None:
    db_path = tmp_path / "h.db"
    payload = _base_state_kwargs() | {"foo": "x", "items": ["a"]}
    await _init_db_with_run(db_path, state=payload)
    schema = _make_schema(
        foo=(str | None, None),
        items=(list[str], Field(default_factory=list)),
    )

    new = await update_state("R1", schema, db_path=db_path, foo="y", items=["b"])
    assert new.foo == "y"  # type: ignore[attr-defined]
    assert new.items == ["a", "b"]  # type: ignore[attr-defined]


async def test_ac8_unknown_field_raises(tmp_path: Path) -> None:
    db_path = tmp_path / "h.db"
    await _init_db_with_run(db_path)
    schema = _make_schema()  # only BaseState fields
    with pytest.raises(StateStoreError, match="unknown"):
        await update_state("R1", schema, db_path=db_path, no_such_field=1)


async def test_ac9_invalid_value_type_raises(tmp_path: Path) -> None:
    db_path = tmp_path / "h.db"
    payload = _base_state_kwargs() | {"foo": None}
    await _init_db_with_run(db_path, state=payload)
    # foo is declared str|None — passing 42 must fail re-validation.
    schema = _make_schema(foo=(str | None, None))
    with pytest.raises(StateStoreError):
        await update_state("R1", schema, db_path=db_path, foo=42)
    # state should not have been mutated.
    persisted = await _read_state_json(db_path)
    assert persisted["foo"] is None


# ---------------------------------------------------------------------------
# AC10 — dict reject (deferred to v1.5)
# ---------------------------------------------------------------------------


async def test_ac10_dict_field_rejected_with_v15_message(tmp_path: Path) -> None:
    db_path = tmp_path / "h.db"
    payload = _base_state_kwargs() | {"my_dict": {}}
    await _init_db_with_run(db_path, state=payload)
    schema = _make_schema(
        my_dict=(dict[str, str], Field(default_factory=dict)),
    )
    with pytest.raises(StateStoreError, match="v1.5"):
        await update_state("R1", schema, db_path=db_path, my_dict={"k": "v"})


# ---------------------------------------------------------------------------
# AC11..AC14 — notes bounding (notes-only, not other list fields)
# ---------------------------------------------------------------------------


async def test_ac11_notes_under_caps_all_kept(tmp_path: Path) -> None:
    db_path = tmp_path / "h.db"
    await _init_db_with_run(db_path)
    schema = _make_schema()

    batch = [f"n{i}" for i in range(50)]
    new = await update_state("R1", schema, db_path=db_path, notes=batch)
    assert new.notes == batch
    assert len(new.notes) == 50


async def test_ac12_notes_entry_count_cap_drops_oldest(tmp_path: Path) -> None:
    """If only the entry-count cap fires, drop oldest until exactly
    NOTES_MAX_ENTRIES."""
    db_path = tmp_path / "h.db"
    seed = [f"old-{i}" for i in range(80)]
    payload = _base_state_kwargs() | {"notes": seed}
    await _init_db_with_run(db_path, state=payload)
    schema = _make_schema()

    incoming = [f"new-{i}" for i in range(50)]
    new = await update_state("R1", schema, db_path=db_path, notes=incoming)
    assert len(new.notes) == NOTES_MAX_ENTRIES
    # 80 + 50 = 130 -> drop oldest 30; remaining oldest is "old-30".
    assert new.notes[0] == "old-30"
    assert new.notes[-1] == "new-49"


async def test_ac13_notes_char_budget_cap_drops_oldest(tmp_path: Path) -> None:
    """When the character-budget alone would fire (under the entry cap),
    drop oldest entries until under the char budget. Whole entries, not
    partial."""
    db_path = tmp_path / "h.db"
    # 30 entries of 2 KB each = 60 KB total. Char-budget fires; entry-count doesn't.
    big = "x" * 2_000
    seed = [f"old-{i:02d}-{big}" for i in range(30)]
    payload = _base_state_kwargs() | {"notes": seed}
    await _init_db_with_run(db_path, state=payload)
    schema = _make_schema()

    new = await update_state("R1", schema, db_path=db_path, notes=[])
    total_chars = sum(len(n) for n in new.notes)
    assert total_chars <= NOTES_MAX_CHARS
    # Entry count must remain under NOTES_MAX_ENTRIES; original 30 is already
    # under, but char-budget should have dropped some oldest entries.
    assert len(new.notes) < 30
    # Newest entry preserved.
    assert new.notes[-1].startswith("old-29")


async def test_ac14_bounding_only_applies_to_notes(tmp_path: Path) -> None:
    """A workflow-declared list[str] field other than `notes` appends
    without caps."""
    db_path = tmp_path / "h.db"
    seed_warnings = [f"w-{i}" for i in range(150)]
    payload = _base_state_kwargs() | {"warnings": seed_warnings}
    await _init_db_with_run(db_path, state=payload)
    schema = _make_schema(
        warnings=(list[str], Field(default_factory=list)),
    )

    incoming = [f"new-{i}" for i in range(50)]
    new = await update_state(
        "R1",
        schema,
        db_path=db_path,
        warnings=incoming,
        notes=[f"note-{i}" for i in range(150)],
    )
    # warnings: no cap, full append.
    assert new.warnings == seed_warnings + incoming  # type: ignore[attr-defined]
    assert len(new.warnings) == 200  # type: ignore[attr-defined]
    # notes: capped to NOTES_MAX_ENTRIES.
    assert len(new.notes) == NOTES_MAX_ENTRIES


# ---------------------------------------------------------------------------
# AC15..AC17 — event emission
# ---------------------------------------------------------------------------


async def test_ac15_successful_update_emits_state_changed(tmp_path: Path) -> None:
    db_path = tmp_path / "h.db"
    payload = _base_state_kwargs() | {"foo": "x"}
    await _init_db_with_run(db_path, state=payload)
    schema = _make_schema(foo=(str | None, None))

    await update_state("R1", schema, db_path=db_path, foo="y")
    events = await _fetch_events(db_path)
    assert len(events) == 1
    assert events[0]["run_id"] == "R1"
    assert events[0]["event_type"] == "state_changed"
    data = json.loads(events[0]["data_json"])
    # We persist the changed field names — easy filter target downstream.
    assert "fields" in data
    assert sorted(data["fields"]) == ["foo"]


async def test_ac16_failed_update_does_not_emit(tmp_path: Path) -> None:
    db_path = tmp_path / "h.db"
    await _init_db_with_run(db_path)
    schema = _make_schema()
    before = await _count_events(db_path)
    with pytest.raises(StateStoreError):
        await update_state("R1", schema, db_path=db_path, no_such_field=1)
    after = await _count_events(db_path)
    assert after == before


async def test_ac17_emit_event_false_suppresses_event(tmp_path: Path) -> None:
    db_path = tmp_path / "h.db"
    payload = _base_state_kwargs() | {"foo": None}
    await _init_db_with_run(db_path, state=payload)
    schema = _make_schema(foo=(str | None, None))
    before = await _count_events(db_path)
    await update_state("R1", schema, db_path=db_path, emit_event=False, foo="z")
    after = await _count_events(db_path)
    assert after == before


# ---------------------------------------------------------------------------
# AC18 — concurrency: parallel disjoint-field writes both land
# ---------------------------------------------------------------------------


async def test_ac18_parallel_disjoint_writes_both_land(tmp_path: Path) -> None:
    db_path = tmp_path / "h.db"
    payload = _base_state_kwargs() | {"foo": None, "bar": None}
    await _init_db_with_run(db_path, state=payload)
    schema = _make_schema(
        foo=(str | None, None),
        bar=(str | None, None),
    )

    await asyncio.gather(
        update_state("R1", schema, db_path=db_path, foo="A"),
        update_state("R1", schema, db_path=db_path, bar="B"),
    )
    persisted = await _read_state_json(db_path)
    assert persisted["foo"] == "A"
    assert persisted["bar"] == "B"


# ---------------------------------------------------------------------------
# AC19..AC22 — per-write merge override (H-1.5-004)
# ---------------------------------------------------------------------------


async def test_ac19_merge_replace_on_list_overwrites_instead_of_appending(
    tmp_path: Path,
) -> None:
    """merge_overrides={"items": "replace"} forces an overwrite on a list field
    instead of the default append behaviour."""
    db_path = tmp_path / "h.db"
    payload = _base_state_kwargs() | {"items": ["existing-a", "existing-b"]}
    await _init_db_with_run(db_path, state=payload)
    schema = _make_schema(items=(list[str], Field(default_factory=list)))

    new = await update_state(
        "R1",
        schema,
        db_path=db_path,
        merge_overrides={"items": "replace"},
        items=["fresh"],
    )
    assert new.items == ["fresh"]  # type: ignore[attr-defined]
    persisted = await _read_state_json(db_path)
    assert persisted["items"] == ["fresh"]


async def test_ac20_merge_replace_on_list_with_empty_incoming_replaces_all(
    tmp_path: Path,
) -> None:
    """merge_overrides replace with an empty list clears the field."""
    db_path = tmp_path / "h.db"
    payload = _base_state_kwargs() | {"items": ["a", "b", "c"]}
    await _init_db_with_run(db_path, state=payload)
    schema = _make_schema(items=(list[str], Field(default_factory=list)))

    new = await update_state(
        "R1",
        schema,
        db_path=db_path,
        merge_overrides={"items": "replace"},
        items=[],
    )
    assert new.items == []  # type: ignore[attr-defined]


async def test_ac21_merge_replace_on_scalar_still_overwrites(
    tmp_path: Path,
) -> None:
    """merge_overrides replace on a scalar field behaves the same as the default
    overwrite — no error, incoming value wins."""
    db_path = tmp_path / "h.db"
    payload = _base_state_kwargs() | {"foo": "old"}
    await _init_db_with_run(db_path, state=payload)
    schema = _make_schema(foo=(str | None, None))

    new = await update_state(
        "R1",
        schema,
        db_path=db_path,
        merge_overrides={"foo": "replace"},
        foo="new",
    )
    assert new.foo == "new"  # type: ignore[attr-defined]


async def test_ac22_no_merge_override_list_still_appends(tmp_path: Path) -> None:
    """Without merge_overrides (or None), list fields still append as per
    the type-driven default."""
    db_path = tmp_path / "h.db"
    payload = _base_state_kwargs() | {"items": ["existing"]}
    await _init_db_with_run(db_path, state=payload)
    schema = _make_schema(items=(list[str], Field(default_factory=list)))

    new = await update_state(
        "R1",
        schema,
        db_path=db_path,
        merge_overrides=None,
        items=["appended"],
    )
    assert new.items == ["existing", "appended"]  # type: ignore[attr-defined]
