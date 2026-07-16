"""``harness promote escalate`` — the non-success terminal path (CAL-1118, ADR 0003).

Escalation files or updates a Linear ticket with the promotion evidence and marks
the promotion ``escalated``. These exercise the four acceptance criteria against
real CLI stdout, with the Linear boundary (``LinearClient`` + ``linear_api_key``)
stubbed:

* AC-1 — a first escalation creates a Todo issue carrying the promotion evidence
  and records nothing was duplicated.
* AC-2 — re-running for an already-linked promotion comments on the existing
  ticket instead of creating a second one.
* AC-3 — the promotion row records the escalation ticket id and ``escalated`` state.
* AC-4 — missing Linear credentials return a structured ``blocked`` result and
  leave the promotion row untouched.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from harness.cli import app
from harness.cli import promote as promote_cli
from harness.linear import LinearConfigError, LinearRequestError
from harness.state import promotions
from harness.state.promotions import Promotion

cli_runner = CliRunner()


def _promotion(**overrides: object) -> Promotion:
    base: dict[str, object] = {
        "promotion_id": "p1",
        "repo": "/repo",
        "from_branch": "dev",
        "to_branch": "staging",
        "status": "needs_ticket",
        "created_at": "2026-07-17T00:00:00+00:00",
        "updated_at": "2026-07-17T00:00:00+00:00",
        "promotion_branch": "promote/2026-07-17-dev-to-staging",
    }
    base.update(overrides)
    return Promotion(**base)  # type: ignore[arg-type]


def _seed(tmp_path: Path, promo: Promotion) -> Path:
    db = tmp_path / "harness.db"
    asyncio.run(promotions.insert_promotion(promo, db_path=db))
    return db


def _read(db: Path, promotion_id: str) -> Promotion | None:
    return asyncio.run(promotions.read_promotion(promotion_id, db_path=db))


def _install_fake_linear(
    monkeypatch: pytest.MonkeyPatch,
    *,
    create_result: dict[str, str] | None = None,
    raise_on_create: Exception | None = None,
    raise_on_comment: Exception | None = None,
) -> dict[str, list[Any]]:
    """Patch ``promote.LinearClient`` + ``linear_api_key``; record create/comment calls."""
    calls: dict[str, list[Any]] = {"create": [], "comment": []}
    result = create_result or {
        "identifier": "CAL-9999",
        "url": "https://linear.app/x/CAL-9999",
    }

    class _Fake:
        def __init__(self, api_key: str) -> None:  # noqa: ARG002
            pass

        async def create_issue(
            self, *, team_key: str, project_name: str | None, title: str, description: str
        ) -> dict[str, str]:
            calls["create"].append(
                {
                    "team_key": team_key,
                    "project_name": project_name,
                    "title": title,
                    "description": description,
                }
            )
            if raise_on_create is not None:
                raise raise_on_create
            return result

        async def post_comment(self, identifier: str, body: str) -> None:
            calls["comment"].append({"identifier": identifier, "body": body})
            if raise_on_comment is not None:
                raise raise_on_comment

    monkeypatch.setattr(promote_cli, "LinearClient", _Fake)
    monkeypatch.setattr(promote_cli, "linear_api_key", lambda: "test-key")
    return calls


def _invoke(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    db: Path,
    extra: list[str] | None = None,
) -> Any:
    monkeypatch.setenv("HARNESS_WORKSPACE_ROOTS", str(tmp_path))
    # `extra is None` → default to explicit team/project flags; `extra == []` →
    # deliberately pass *no* target flags (so the CONTEXT.md / unresolved paths
    # are exercised). An `or` would collapse the two — an empty list is falsy.
    flags = ["--team", "CAL", "--project", "Harness v3"] if extra is None else extra
    argv = [
        "promote",
        "escalate",
        "--promotion-id",
        "p1",
        "--repo",
        str(tmp_path),
        "--db",
        str(db),
        *flags,
    ]
    return cli_runner.invoke(app, argv)


# --- AC-1 + AC-3: first escalation creates a ticket and records escalated ------


def test_escalate_creates_issue_and_records_escalated(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db = _seed(tmp_path, _promotion())
    calls = _install_fake_linear(monkeypatch)

    result = _invoke(tmp_path, monkeypatch, db)
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)

    # AC-3: the row records the escalation ticket + terminal state.
    assert payload["status"] == "escalated"
    assert payload["escalation_ticket"] == "CAL-9999"
    assert payload["action"] == "created"
    assert payload["escalation_url"] == "https://linear.app/x/CAL-9999"

    # AC-1: exactly one issue was created, carrying the promotion evidence.
    assert len(calls["create"]) == 1
    assert calls["comment"] == []
    created = calls["create"][0]
    assert created["team_key"] == "CAL"
    assert created["project_name"] == "Harness v3"
    assert "p1" in created["description"]
    assert "needs_ticket" in created["description"]
    assert "promote/2026-07-17-dev-to-staging" in created["description"]

    # AC-3: persisted, not just echoed.
    stored = _read(db, "p1")
    assert stored is not None
    assert stored.status == "escalated"
    assert stored.escalation_ticket == "CAL-9999"


# --- AC-2: re-escalation comments on the existing ticket, no duplicate ---------


def test_reescalation_comments_instead_of_duplicating(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db = _seed(
        tmp_path,
        _promotion(status="escalated", escalation_ticket="CAL-9999"),
    )
    calls = _install_fake_linear(monkeypatch)

    result = _invoke(tmp_path, monkeypatch, db)
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)

    assert payload["action"] == "updated"
    assert payload["escalation_ticket"] == "CAL-9999"  # unchanged
    assert payload["status"] == "escalated"
    # No new issue; a comment on the existing ticket instead.
    assert calls["create"] == []
    assert len(calls["comment"]) == 1
    assert calls["comment"][0]["identifier"] == "CAL-9999"


# --- AC-4: missing credentials → structured blocked, row untouched ------------


def test_missing_credentials_returns_blocked(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db = _seed(tmp_path, _promotion())

    def _no_key() -> str:
        raise LinearConfigError("LINEAR_API_KEY environment variable is not set")

    monkeypatch.setattr(promote_cli, "linear_api_key", _no_key)

    result = _invoke(tmp_path, monkeypatch, db)
    assert result.exit_code == 2, result.output
    payload = json.loads(result.output)
    assert payload["reason"] == "blocked"

    # The promotion row is left exactly as it was — escalation did not happen.
    stored = _read(db, "p1")
    assert stored is not None
    assert stored.status == "needs_ticket"
    assert stored.escalation_ticket is None


# --- Supporting behaviour -----------------------------------------------------


def test_unknown_promotion_id_is_not_found(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db = _seed(tmp_path, _promotion())
    _install_fake_linear(monkeypatch)
    monkeypatch.setenv("HARNESS_WORKSPACE_ROOTS", str(tmp_path))
    result = cli_runner.invoke(
        app,
        [
            "promote", "escalate", "--promotion-id", "ghost",
            "--repo", str(tmp_path), "--db", str(db), "--team", "CAL",
        ],
    )
    assert result.exit_code == 2, result.output
    assert json.loads(result.output)["error"] == "not_found"


def test_target_resolved_from_context_md_when_flags_absent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """With no ``--team`` / ``--project``, the target comes from CONTEXT.md."""
    (tmp_path / "CONTEXT.md").write_text(
        "repo:\n  linear: CAL\n  project: Harness v3\nlayers:\n  linear: true\n"
    )
    db = _seed(tmp_path, _promotion())
    calls = _install_fake_linear(monkeypatch)

    result = _invoke(tmp_path, monkeypatch, db, extra=[])  # no --team/--project
    assert result.exit_code == 0, result.output
    created = calls["create"][0]
    assert created["team_key"] == "CAL"
    assert created["project_name"] == "Harness v3"


def test_unresolved_target_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No ``--team`` and no CONTEXT.md ``repo.linear`` → a structured refusal, no
    Linear call."""
    db = _seed(tmp_path, _promotion())
    calls = _install_fake_linear(monkeypatch)

    result = _invoke(tmp_path, monkeypatch, db, extra=[])  # no flags, no CONTEXT.md
    assert result.exit_code == 2, result.output
    assert json.loads(result.output)["reason"] == "unresolved_target"
    assert calls["create"] == []


def test_linear_failure_surfaces_structured_refusal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A Linear API failure during create is a structured refusal (never a raw
    traceback), and the promotion row stays unescalated."""
    db = _seed(tmp_path, _promotion())
    _install_fake_linear(
        monkeypatch, raise_on_create=LinearRequestError("Linear API HTTP 500")
    )

    result = _invoke(tmp_path, monkeypatch, db)
    assert result.exit_code == 2, result.output
    assert json.loads(result.output)["reason"] == "escalation_failed"
    stored = _read(db, "p1")
    assert stored is not None
    assert stored.status == "needs_ticket"
