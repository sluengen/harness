"""``harness promote escalate`` — the non-success terminal path (CAL-1118, ADR 0003).

Escalation files or updates a tracker ticket with the promotion evidence and marks
the promotion ``escalated``. Since #328 it reaches the tracker the same way every
other writing verb does — through :func:`harness.tracker.tracker_client` — so the
terminal works on whichever backend ``CONTEXT.md`` → ``tracker:`` selects, instead
of only on Linear. These exercise that contract against real CLI stdout, with the
**seam** (not a backend client) stubbed:

* AC-1 — a first escalation creates a Todo issue carrying the promotion evidence.
* AC-2 — re-running for an already-linked promotion comments on the existing
  ticket instead of creating a second one.
* AC-3 — the promotion row records the escalation ticket id and ``escalated`` state.
* AC-4 — a tracker that cannot be reached (missing credential/config, no tracker at
  all, or an API failure) returns a structured refusal and leaves the row untouched.

The backend-parametrized cases are the point of #328: the same command, the same
assertions, under a Linear-shaped and a GitHub-shaped identifier. A regression to a
direct ``LinearClient`` shows up as the GitHub cases failing.

The **structural** half of that contract moved to
``tests/unit/test_cli_module_boundaries.py`` in #339, where the same rule is
enforced over every module under ``harness/cli/`` rather than over this one file.
Two detectors of one rule drift, and the weaker one goes green while the stronger
is degraded; the named ``promote`` pin lives there now, beside the tree-wide scan.
What stays here is behaviour.
"""

from __future__ import annotations

import asyncio
import inspect
import json
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from harness.cli import app
from harness.cli import promote as promote_cli
from harness.github import GitHubConfigError, GitHubRequestError
from harness.linear import LinearConfigError, LinearRequestError
from harness.state import promotions
from harness.state.promotions import Promotion
from harness.tracker import Tracker
from harness.tracker_errors import TrackerNotFound
from tests._gitutil import init_repo

cli_runner = CliRunner()

#: The two live backends, with a representative ticket identifier for each. Linear
#: hands back a workspace-scoped key; GitHub hands back an issue number. Nothing in
#: the escalate path parses either — the identifier is opaque and round-trips to
#: ``post_comment`` — which is exactly what these parametrized cases pin.
BACKENDS = [
    pytest.param("CAL-9999", "https://linear.app/x/CAL-9999", id="linear"),
    pytest.param("328", "https://github.com/sluengen/harness/issues/328", id="github"),
]


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


class _FakeTracker:
    """A stand-in for whichever backend the factory would have built.

    Implements only the two seam methods escalation calls. It is asserted against
    the ``@runtime_checkable`` :class:`~harness.tracker.Tracker` protocol in
    :func:`test_the_fake_tracker_cannot_drift_from_the_seam`, so this double
    cannot silently drift from the interface the verb depends on.
    """

    def __init__(
        self,
        calls: dict[str, list[Any]],
        *,
        result: dict[str, str],
        raise_on_create: Exception | None,
        raise_on_comment: Exception | None,
    ) -> None:
        self._calls = calls
        self._result = result
        self._raise_on_create = raise_on_create
        self._raise_on_comment = raise_on_comment

    async def create_issue(
        self, *, title: str, description: str, project: str | None
    ) -> dict[str, str]:
        self._calls["create"].append(
            {"title": title, "description": description, "project": project}
        )
        if self._raise_on_create is not None:
            raise self._raise_on_create
        return self._result

    async def post_comment(self, identifier: str, body: str) -> None:
        self._calls["comment"].append({"identifier": identifier, "body": body})
        if self._raise_on_comment is not None:
            raise self._raise_on_comment


def _install_fake_tracker(
    monkeypatch: pytest.MonkeyPatch,
    *,
    ticket_id: str = "CAL-9999",
    url: str = "https://linear.app/x/CAL-9999",
    raise_on_create: Exception | None = None,
    raise_on_comment: Exception | None = None,
    config_error: Exception | None = None,
    tracker_less: bool = False,
) -> dict[str, list[Any]]:
    """Patch ``promote.tracker_client`` — the **seam**, not a backend client.

    Patching here rather than at ``LinearClient`` is the whole point of #328: the
    verb must not know which backend it has. ``config_error`` makes the factory
    raise (a missing credential or config block); ``tracker_less`` makes it return
    ``None`` (``tracker: none``).
    """
    calls: dict[str, list[Any]] = {"create": [], "comment": [], "factory": []}
    fake = _FakeTracker(
        calls,
        result={"identifier": ticket_id, "url": url},
        raise_on_create=raise_on_create,
        raise_on_comment=raise_on_comment,
    )

    def _factory(repo_root: Path) -> Any:
        calls["factory"].append(repo_root)
        if config_error is not None:
            raise config_error
        return None if tracker_less else fake

    monkeypatch.setattr(promote_cli, "tracker_client", _factory)
    return calls


def _invoke(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    db: Path,
    extra: list[str] | None = None,
) -> Any:
    init_repo(tmp_path)  # the verbs refuse a --repo that is not a git top-level (#214)
    monkeypatch.setenv("HARNESS_WORKSPACE_ROOTS", str(tmp_path))
    # `extra is None` → default to an explicit --project; `extra == []` →
    # deliberately pass *no* scope flag (so the CONTEXT.md / unset paths are
    # exercised). An `or` would collapse the two — an empty list is falsy.
    flags = ["--project", "Harness v3"] if extra is None else extra
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


@pytest.mark.parametrize(("ticket_id", "url"), BACKENDS)
def test_escalate_creates_issue_and_records_escalated(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, ticket_id: str, url: str
) -> None:
    """The terminal works on either backend — the #328 regression pin.

    Under ``tracker: github`` this failed before #328: the verb reached for
    ``linear_api_key()`` and refused ``blocked`` however the repo was configured.
    """
    db = _seed(tmp_path, _promotion())
    calls = _install_fake_tracker(monkeypatch, ticket_id=ticket_id, url=url)

    result = _invoke(tmp_path, monkeypatch, db)
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)

    # AC-3: the row records the escalation ticket + terminal state.
    assert payload["status"] == "escalated"
    assert payload["escalation_ticket"] == ticket_id
    assert payload["action"] == "created"
    assert payload["escalation_url"] == url

    # AC-1: exactly one issue was created, carrying the promotion evidence.
    assert len(calls["create"]) == 1
    assert calls["comment"] == []
    created = calls["create"][0]
    assert created["project"] == "Harness v3"
    assert "p1" in created["description"]
    assert "needs_ticket" in created["description"]
    assert "promote/2026-07-17-dev-to-staging" in created["description"]

    # AC-3: persisted, not just echoed.
    stored = _read(db, "p1")
    assert stored is not None
    assert stored.status == "escalated"
    assert stored.escalation_ticket == ticket_id


@pytest.mark.parametrize(("ticket_id", "url"), BACKENDS)
def test_escalate_routes_through_the_tracker_seam(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, ticket_id: str, url: str
) -> None:
    """The verb obtains its client from the factory, keyed on the repo root.

    This is the architecture contract #328 restores: backend selection has one
    source of truth (``CONTEXT.md`` → ``tracker:``, read by the factory), so the
    verb never names a backend.
    """
    db = _seed(tmp_path, _promotion())
    calls = _install_fake_tracker(monkeypatch, ticket_id=ticket_id, url=url)

    result = _invoke(tmp_path, monkeypatch, db)
    assert result.exit_code == 0, result.output
    assert len(calls["factory"]) == 1
    assert Path(calls["factory"][0]).resolve() == tmp_path.resolve()


# --- AC-2: re-escalation comments on the existing ticket, no duplicate ---------


@pytest.mark.parametrize(("ticket_id", "url"), BACKENDS)
def test_reescalation_comments_instead_of_duplicating(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, ticket_id: str, url: str
) -> None:
    """The stored identifier round-trips to ``post_comment`` unparsed, so a
    Linear key and a GitHub issue number behave identically."""
    db = _seed(
        tmp_path,
        _promotion(status="escalated", escalation_ticket=ticket_id),
    )
    calls = _install_fake_tracker(monkeypatch, ticket_id=ticket_id, url=url)

    result = _invoke(tmp_path, monkeypatch, db)
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)

    assert payload["action"] == "updated"
    assert payload["escalation_ticket"] == ticket_id  # unchanged
    assert payload["status"] == "escalated"
    # No new issue; a comment on the existing ticket instead.
    assert calls["create"] == []
    assert len(calls["comment"]) == 1
    assert calls["comment"][0]["identifier"] == ticket_id
    assert calls["comment"][0]["body"].startswith("**Re-escalation update**")


# --- AC-4: every unreachable-tracker path refuses and leaves the row untouched --


@pytest.mark.parametrize(
    "config_error",
    [
        pytest.param(
            LinearConfigError("LINEAR_API_KEY environment variable is not set"),
            id="linear-credential",
        ),
        pytest.param(
            GitHubConfigError("GITHUB_TOKEN environment variable is not set"),
            id="github-credential",
        ),
        pytest.param(
            GitHubConfigError("CONTEXT.md has no github: block"),
            id="github-config-block",
        ),
    ],
)
def test_missing_tracker_configuration_returns_blocked(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, config_error: Exception
) -> None:
    """Any ``TrackerConfigError`` — either backend, credential or config block —
    is the one ``blocked`` terminal, and the row is untouched.

    Before #328 only the Linear credential produced this; a GitHub repo could not
    reach the check at all.
    """
    db = _seed(tmp_path, _promotion())
    calls = _install_fake_tracker(monkeypatch, config_error=config_error)

    result = _invoke(tmp_path, monkeypatch, db)
    assert result.exit_code == 2, result.output
    payload = json.loads(result.output)
    assert payload["reason"] == "blocked"
    assert calls["create"] == []

    # The promotion row is left exactly as it was — escalation did not happen.
    stored = _read(db, "p1")
    assert stored is not None
    assert stored.status == "needs_ticket"
    assert stored.escalation_ticket is None


def test_a_config_error_raised_lazily_by_the_client_is_still_blocked(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A ``TrackerConfigError`` raised from ``create_issue`` — not from the
    factory — is still the ``blocked`` refusal, not a raw traceback.

    ``LinearClient.create_issue`` raises lazily when the client carries no team
    (``repo.linear`` unset), because that is a backend fact the client owns and a
    neutral verb must not pre-check. So the config error can surface at *either*
    of two points, and only wrapping the factory call left this one crashing with
    exit 1 — which the seam-stubbed cases above could not see, since a stub that
    raises from the factory never exercises the second path.
    """
    db = _seed(tmp_path, _promotion())
    _install_fake_tracker(
        monkeypatch,
        raise_on_create=LinearConfigError("no Linear team configured"),
    )

    result = _invoke(tmp_path, monkeypatch, db)
    assert result.exit_code == 2, result.output
    assert json.loads(result.output)["reason"] == "blocked"

    stored = _read(db, "p1")
    assert stored is not None
    assert stored.status == "needs_ticket"
    assert stored.escalation_ticket is None


def test_tracker_less_repo_refuses_and_carries_the_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``tracker: none`` — there is nowhere to file, so the payload carries the
    rendered evidence and the row does **not** advance to ``escalated``.

    Recording ``escalated`` with a null ticket would make the ledger claim a
    ticket is waiting for a human when none exists (``commands/promote.md``); the
    exit-0 ``skipped_no_tracker`` shape ``defer`` uses is wrong here too, because
    there the write only decorates a ticket that already exists, whereas here the
    escalation *is* the terminal.
    """
    db = _seed(tmp_path, _promotion())
    calls = _install_fake_tracker(monkeypatch, tracker_less=True)

    result = _invoke(tmp_path, monkeypatch, db)
    assert result.exit_code == 2, result.output
    payload = json.loads(result.output)
    assert payload["reason"] == "no_tracker"
    assert calls["create"] == [] and calls["comment"] == []

    # The evidence has nowhere else to go, so the refusal carries it.
    assert "p1" in payload["escalation_body"]
    assert "promote/2026-07-17-dev-to-staging" in payload["escalation_body"]
    assert payload["escalation_title"]

    stored = _read(db, "p1")
    assert stored is not None
    assert stored.status == "needs_ticket"
    assert stored.escalation_ticket is None


@pytest.mark.parametrize(
    "failure",
    [
        pytest.param(LinearRequestError("Linear API HTTP 500"), id="linear-request"),
        pytest.param(GitHubRequestError("GitHub API HTTP 502"), id="github-request"),
        pytest.param(TrackerNotFound("issue 328 not found"), id="not-found"),
    ],
)
def test_tracker_failure_surfaces_structured_refusal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: Exception
) -> None:
    """A tracker failure during create is a structured refusal (never a raw
    traceback) on either backend, and the row stays unescalated."""
    db = _seed(tmp_path, _promotion())
    _install_fake_tracker(monkeypatch, raise_on_create=failure)

    result = _invoke(tmp_path, monkeypatch, db)
    assert result.exit_code == 2, result.output
    assert json.loads(result.output)["reason"] == "escalation_failed"
    stored = _read(db, "p1")
    assert stored is not None
    assert stored.status == "needs_ticket"
    assert stored.escalation_ticket is None


def test_a_stale_cross_backend_identifier_refuses_rather_than_refiling(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A promotion escalated under Linear, then re-escalated after the repo
    switched to GitHub: the stored key resolves to no issue, so the comment
    fails and the row keeps its prior state — nothing is silently re-filed as a
    duplicate under the new backend."""
    db = _seed(tmp_path, _promotion(status="escalated", escalation_ticket="CAL-9999"))
    calls = _install_fake_tracker(
        monkeypatch, raise_on_comment=TrackerNotFound("issue CAL-9999 not found")
    )

    result = _invoke(tmp_path, monkeypatch, db)
    assert result.exit_code == 2, result.output
    assert json.loads(result.output)["reason"] == "escalation_failed"
    assert calls["create"] == []  # never re-filed

    stored = _read(db, "p1")
    assert stored is not None
    assert stored.escalation_ticket == "CAL-9999"


# --- Supporting behaviour -----------------------------------------------------


def test_unknown_promotion_id_is_not_found(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db = _seed(tmp_path, _promotion())
    _install_fake_tracker(monkeypatch)
    init_repo(tmp_path)  # the verbs refuse a --repo that is not a git top-level (#214)
    monkeypatch.setenv("HARNESS_WORKSPACE_ROOTS", str(tmp_path))
    result = cli_runner.invoke(
        app,
        [
            "promote", "escalate", "--promotion-id", "ghost",
            "--repo", str(tmp_path), "--db", str(db),
        ],
    )
    assert result.exit_code == 2, result.output
    assert json.loads(result.output)["error"] == "not_found"


def test_scope_resolved_from_context_md_when_the_flag_is_absent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """With no ``--project``, the scope comes from CONTEXT.md ``repo.project``."""
    (tmp_path / "CONTEXT.md").write_text(
        "repo:\n  name: x\n  project: Harness v3\ntracker: github\n"
    )
    db = _seed(tmp_path, _promotion())
    calls = _install_fake_tracker(monkeypatch)

    result = _invoke(tmp_path, monkeypatch, db, extra=[])  # no --project
    assert result.exit_code == 0, result.output
    assert calls["create"][0]["project"] == "Harness v3"


def test_an_unset_scope_is_not_a_refusal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No ``--project`` and no CONTEXT.md ``repo.project`` still escalates.

    The scope is nullable (#174/#248): unset means the backend's natural queue,
    not an error. The old ``unresolved_target`` refusal is retired with #328 —
    it fired on a missing Linear *team*, a backend fact that now lives inside the
    Linear client as config rather than being re-derived in a neutral verb.
    """
    db = _seed(tmp_path, _promotion())
    calls = _install_fake_tracker(monkeypatch)

    result = _invoke(tmp_path, monkeypatch, db, extra=[])  # no flags, no CONTEXT.md
    assert result.exit_code == 0, result.output
    assert calls["create"][0]["project"] is None


@pytest.mark.parametrize("method", ["create_issue", "post_comment"])
def test_the_fake_tracker_cannot_drift_from_the_seam(method: str) -> None:
    """Anti-drift: the double's methods match the seam's, parameter for parameter.

    Without this, a seam signature change would leave every case above green
    while the real clients no longer match — the double would be pinning a
    contract nothing implements. An ``isinstance(fake, Tracker)`` check cannot do
    this job twice over: the fake deliberately implements only the two methods
    escalation calls (so it would fail the protocol on the other sixteen), and
    ``@runtime_checkable`` compares method *presence*, never signatures — which
    is precisely the drift being guarded against here.
    """
    assert inspect.signature(getattr(_FakeTracker, method)) == inspect.signature(
        getattr(Tracker, method)
    )
