"""CAL-1114 — the ``harness promote`` JSON output contract is typed and locked.

CAL-1113 locked the promote *surface* (command names + flags); this locks the
*data* an orchestrator reads back off the read-path commands, the same way
``test_verb_contract_locked.py`` locks the build verbs' output. Two commands
carry a real contract in v1 (the mechanics for ``start`` / ``continue`` /
``escalate`` land later):

* ``promote status`` emits the typed ``Promotion`` view — its top-level keys are
  locked (AC-2), read from the JSON the production CLI actually echoes.
* ``promote pr`` enforces the PR gate — a promotion that is not ``pr_ready`` with
  a gated SHA is refused with a locked ``reason`` (AC-4); a gate-satisfied
  promotion falls through to ``not_implemented`` (PR push is CAL-1117, out of
  scope here).

Binding to real CLI stdout (not a re-serialized model) means an alias, a
serializer, a field exclusion, or a payload wrap is in scope — not only a renamed
attribute.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import get_args

import pytest
from typer.testing import CliRunner

from harness.cli import app
from harness.cli.promote import PromotionRefusalReason
from harness.state import promotions
from harness.state.promotions import Promotion

cli_runner = CliRunner()


#: The locked top-level keys ``promote status`` emits (the ``Promotion`` view).
#: Adding, dropping, or renaming a key is an output-contract change — a
#: *major*-level event under "Surface is a versioned interface". Update this
#: snapshot only with that deliberate version decision.
EXPECTED_PROMOTION_OUTPUT_KEYS = {
    "promotion_id",
    "repo",
    "from_branch",
    "to_branch",
    "status",
    "created_at",
    "updated_at",
    "worktree_path",
    "promotion_branch",
    "gated_sha",
    "attempts",
    "pr_url",
    "escalation_ticket",
    "evidence",
}

#: The locked ``promote pr`` gate-refusal reasons. Exactly one is emitted in the
#: ``{"reason": ...}`` payload on a gate failure, and an orchestrator branches on
#: it — so the enum is interface (AC-4).
EXPECTED_PROMOTION_REFUSAL_REASONS = {"gate_not_satisfied"}


def _promotion(**overrides: object) -> Promotion:
    base: dict[str, object] = {
        "promotion_id": "p1",
        "repo": "/repo",
        "from_branch": "dev",
        "to_branch": "staging",
        "status": "opened",
        "created_at": "2026-07-17T00:00:00+00:00",
        "updated_at": "2026-07-17T00:00:00+00:00",
    }
    base.update(overrides)
    return Promotion(**base)  # type: ignore[arg-type]


def _seed(tmp_path: Path, promo: Promotion) -> Path:
    """Write ``promo`` into a fresh DB and return its path."""
    db = tmp_path / "harness.db"
    asyncio.run(promotions.insert_promotion(promo, db_path=db))
    return db


def _invoke(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, argv: list[str], db: Path
) -> object:
    monkeypatch.setenv("HARNESS_WORKSPACE_ROOTS", str(tmp_path))
    return cli_runner.invoke(app, [*argv, "--repo", str(tmp_path), "--db", str(db)])


# --- AC-2: promote status emits the locked, typed output ----------------------


def test_status_emits_locked_output_keys(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``promote status`` echoes the typed ``Promotion`` view with exactly its
    locked top-level key set (read from real CLI stdout)."""
    db = _seed(tmp_path, _promotion())
    result = _invoke(tmp_path, monkeypatch, ["promote", "status", "--promotion-id", "p1"], db)
    assert result.exit_code == 0, result.output
    emitted = json.loads(result.output)
    assert set(emitted) == EXPECTED_PROMOTION_OUTPUT_KEYS


def test_status_output_keys_match_the_model() -> None:
    """The locked key set is exactly the ``Promotion`` model's fields — so the
    snapshot cannot silently drift from the model it projects."""
    assert EXPECTED_PROMOTION_OUTPUT_KEYS == set(Promotion.model_fields)


def test_status_unknown_promotion_id_is_not_found(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``promote status`` on an unknown id emits a structured ``not_found`` and
    exits 2 — an orchestrator distinguishes it from a real error."""
    db = _seed(tmp_path, _promotion())
    result = _invoke(
        tmp_path, monkeypatch, ["promote", "status", "--promotion-id", "ghost"], db
    )
    assert result.exit_code == 2, result.output
    payload = json.loads(result.output)
    assert payload["error"] == "not_found"
    assert payload["promotion_id"] == "ghost"


# --- AC-4: promote pr enforces the gate ---------------------------------------


def test_pr_refusal_reason_enum_is_locked() -> None:
    """The ``promote pr`` gate-refusal reason type holds exactly the locked set."""
    assert set(get_args(PromotionRefusalReason)) == EXPECTED_PROMOTION_REFUSAL_REASONS


def test_pr_refused_when_gate_not_satisfied(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``promote pr`` on a non-``pr_ready`` promotion is refused with the locked
    ``gate_not_satisfied`` reason and exit 2 (AC-4)."""
    db = _seed(tmp_path, _promotion(status="opened"))
    result = _invoke(tmp_path, monkeypatch, ["promote", "pr", "--promotion-id", "p1"], db)
    assert result.exit_code == 2, result.output
    payload = json.loads(result.output)
    assert payload["reason"] == "gate_not_satisfied"
    assert payload["reason"] in EXPECTED_PROMOTION_REFUSAL_REASONS
    assert payload["status"] == "opened"


def test_pr_refused_when_pr_ready_but_no_gated_sha(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A ``pr_ready`` promotion with no gated SHA still fails the gate (AC-4)."""
    db = _seed(tmp_path, _promotion(status="pr_ready", gated_sha=None))
    result = _invoke(tmp_path, monkeypatch, ["promote", "pr", "--promotion-id", "p1"], db)
    assert result.exit_code == 2, result.output
    assert json.loads(result.output)["reason"] == "gate_not_satisfied"


def test_pr_gate_satisfied_falls_through_to_not_implemented(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A gate-satisfied ``pr`` is *not* refused: it reaches the (still-stubbed) PR
    push path, which reports ``not_implemented`` (CAL-1117 fills it in)."""
    db = _seed(tmp_path, _promotion(status="pr_ready", gated_sha="abc123"))
    result = _invoke(tmp_path, monkeypatch, ["promote", "pr", "--promotion-id", "p1"], db)
    assert result.exit_code == 2, result.output
    payload = json.loads(result.output)
    assert payload["error"] == "not_implemented"
    assert payload["command"] == "promote pr"


def test_pr_unknown_promotion_id_is_not_found(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``promote pr`` on an unknown id is a structured ``not_found`` (exit 2)."""
    db = _seed(tmp_path, _promotion())
    result = _invoke(
        tmp_path, monkeypatch, ["promote", "pr", "--promotion-id", "ghost"], db
    )
    assert result.exit_code == 2, result.output
    assert json.loads(result.output)["error"] == "not_found"
