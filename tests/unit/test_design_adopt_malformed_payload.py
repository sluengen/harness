"""``resolve_adoption`` declines a malformed ledger payload instead of raising.

The adopt path (#258, ADR 0008 D1) is fail-safe toward the status quo: every
condition it cannot satisfy returns ``None`` and the run pays for an engine call
it would rather have skipped. That is the whole contract — the function is
documented "never raises" — and it is a contract about *inputs it does not
control*, since a ``design`` event payload is JSON in a SQLite column that older
schemas, hand edits, and future writers all reach.

Split out of ``test_design_adopt.py``: that module tests the adopt *decision*
(did this run resume, does the comment authenticate, is there a source event),
while these two test the reader's tolerance of the row it decided to read. The
split is what keeps the parent module under its line ceiling.

Nullable provenance is what made this reachable. ``model`` and ``grounded_sha``
are typed ``str | None`` and were read straight off the payload, so a non-string
became a pydantic ``ValidationError`` — an unclassified exit 1 out of the one
reader whose entire job is to decline quietly.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from harness.state import store
from tests._asyncutil import run_sync
from tests.unit.test_design_adopt import (
    _RUN_ID,
    _SOURCE_RUN_ID,
    _allow_tmp_workspace,
    _EngineSpy,
    _invoke,
    _prior_comment,
    _seed_resumed_run,
    _seed_source_design,
    _tracker_stub,
    db_path,
    design_events,
    repo,
)

# Re-exported so pytest resolves them here: fixtures are looked up in the
# module namespace, and ``_allow_tmp_workspace`` is autouse — without it every
# invocation below is refused by the workspace allowlist rather than reaching
# the reader under test, which would make both tests pass for the wrong reason.
__all__ = ["_allow_tmp_workspace", "db_path", "repo"]


def test_a_malformed_model_in_the_source_payload_declines_rather_than_raising(
    repo: Path, db_path: Path
) -> None:
    """``resolve_adoption`` documents "never raises", and this is what holds it to it.

    Before nullable provenance the field was built with ``str(... or "")``, which
    was total over any JSON value. Passing ``payload.get("model")`` straight into
    a ``str | None`` pydantic field made a non-string row a ``ValidationError`` —
    an unclassified exit 1 out of the one reader whose whole contract is that a
    bad prior design declines to the engine path instead of wedging the run.
    """
    _seed_resumed_run(db_path, repo)
    _seed_source_design(db_path, engine="codex", model=17)

    result = _invoke(repo, db_path, _EngineSpy(), _tracker_stub(_prior_comment()))

    assert result.exit_code == 0, result.output
    adopted = [e for e in design_events(db_path) if e["run_id"] == _RUN_ID][0]
    # Declining the unusable value, not inventing one: the key is simply absent,
    # the same shape a genuine Codex default produces.
    assert "model" not in adopted["data"]


def test_a_malformed_grounded_sha_declines_the_same_way(
    repo: Path, db_path: Path
) -> None:
    """The second half of the same defect class, one line from the first.

    ``grounded_sha`` is the other ``str | None`` field read straight off the
    payload, so the "never raises" contract was broken on two fields, not one.
    Tested separately rather than folded into the ``model`` case: a single
    fixture carrying both malformed values would stay green if the coercion were
    applied to only one of them.
    """
    _seed_resumed_run(db_path, repo)
    _seed_source_design(db_path)
    run_sync(_corrupt_source_field(db_path, "grounded_sha", ["not", "a", "sha"]))

    result = _invoke(repo, db_path, _EngineSpy(), _tracker_stub(_prior_comment()))

    assert result.exit_code == 0, result.output
    adopted = [e for e in design_events(db_path) if e["run_id"] == _RUN_ID][0]
    assert "grounded_sha" not in adopted["data"]


async def _corrupt_source_field(db_path: Path, key: str, value: Any) -> None:
    """Rewrite one key of the seeded source event's payload to a non-string."""
    async with store.connect(db_path) as conn:
        async with conn.execute(
            "SELECT id, data_json FROM events WHERE event_type = 'design' "
            "AND run_id = ? ORDER BY id DESC LIMIT 1",
            (_SOURCE_RUN_ID,),
        ) as cur:
            row = await cur.fetchone()
        assert row is not None, "the source design event must exist to be corrupted"
        data = json.loads(str(row[1]))
        data[key] = value
        await conn.execute(
            "UPDATE events SET data_json = ? WHERE id = ?", (json.dumps(data), row[0])
        )
        await conn.commit()
