"""``LinearClient.create_issue`` — file a Todo issue for promotion escalation (CAL-1118).

Escalation (``harness promote escalate``) needs the client to create a Linear
issue: resolve the team by key, the Todo (``unstarted``) state, and the project by
name (all at runtime, never a hard-coded UUID), then fire ``issueCreate`` and
return the new issue's ``{identifier, url}``. These pin that surface, mocking the
GraphQL boundary (``LinearClient._request``) as the existing client tests do.
"""

from __future__ import annotations

from typing import Any

import pytest

from harness.linear import (
    LinearClient,
    LinearConfigError,
    LinearNotFound,
    LinearRequestError,
)

_TEAM_NODE = {
    "id": "team-uuid",
    "states": {
        "nodes": [
            {"id": "s-backlog", "name": "Backlog", "type": "backlog"},
            {"id": "s-todo", "name": "Todo", "type": "unstarted"},
            {"id": "s-ip", "name": "In Progress", "type": "started"},
        ]
    },
    "projects": {"nodes": [{"id": "proj-uuid", "name": "Harness v3"}]},
}


def _team_reply(node: dict[str, Any] | None = _TEAM_NODE) -> dict[str, Any]:
    nodes = [node] if node is not None else []
    return {"data": {"teams": {"nodes": nodes}}}


def _create_reply(*, success: bool = True, issue: dict[str, Any] | None = None) -> dict[str, Any]:
    return {"data": {"issueCreate": {"success": success, "issue": issue}}}


async def test_create_issue_resolves_team_todo_project_and_returns_identifier(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A create resolves the team id, the Todo state, and the project id, then
    fires ``issueCreate`` with all three and returns the new ``{identifier, url}``."""
    calls: list[dict[str, Any]] = []

    async def fake_request(self: Any, query: str, variables: dict[str, Any]) -> dict[str, Any]:  # noqa: ARG001
        calls.append({"query": query, "variables": variables})
        if "teams(" in query:
            return _team_reply()
        return _create_reply(
            issue={"identifier": "CAL-9999", "url": "https://linear.app/x/CAL-9999"}
        )

    monkeypatch.setattr(LinearClient, "_request", fake_request)
    client = LinearClient(api_key="fake-key", team="CAL")
    result = await client.create_issue(
        project="Harness v3", title="T", description="D"
    )

    assert result == {"identifier": "CAL-9999", "url": "https://linear.app/x/CAL-9999"}
    create_vars = next(c["variables"] for c in calls if "issueCreate" in c["query"])
    assert create_vars["teamId"] == "team-uuid"
    assert create_vars["stateId"] == "s-todo"  # the Todo (unstarted) state, not Backlog
    assert create_vars["projectId"] == "proj-uuid"
    assert create_vars["title"] == "T"
    assert create_vars["description"] == "D"


async def test_create_issue_without_project_omits_project_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``project_name=None`` files a Todo issue with no project (``projectId`` null)."""
    captured: dict[str, Any] = {}

    async def fake_request(self: Any, query: str, variables: dict[str, Any]) -> dict[str, Any]:  # noqa: ARG001
        if "teams(" in query:
            return _team_reply()
        captured.update(variables)
        return _create_reply(issue={"identifier": "CAL-1", "url": "u"})

    monkeypatch.setattr(LinearClient, "_request", fake_request)
    client = LinearClient(api_key="fake-key", team="CAL")
    await client.create_issue(
        project=None, title="T", description="D"
    )
    assert captured["projectId"] is None


async def test_create_issue_unknown_team_raises_not_found(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No team with the given key → ``LinearNotFound`` (before any mutation)."""

    async def fake_request(self: Any, query: str, variables: dict[str, Any]) -> dict[str, Any]:  # noqa: ARG001
        assert "issueCreate" not in query, "must not mutate when the team is unknown"
        return _team_reply(node=None)

    monkeypatch.setattr(LinearClient, "_request", fake_request)
    client = LinearClient(api_key="fake-key", team="NOPE")
    with pytest.raises(LinearNotFound):
        await client.create_issue(
            project=None, title="T", description="D"
        )


async def test_create_issue_unknown_project_raises_request_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A ``project_name`` that names no project on the team → ``LinearRequestError``."""

    async def fake_request(self: Any, query: str, variables: dict[str, Any]) -> dict[str, Any]:  # noqa: ARG001
        return _team_reply()

    monkeypatch.setattr(LinearClient, "_request", fake_request)
    client = LinearClient(api_key="fake-key", team="CAL")
    with pytest.raises(LinearRequestError):
        await client.create_issue(
            project="Ghost Project", title="T", description="D"
        )


async def test_create_issue_unsuccessful_mutation_raises_request_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``issueCreate`` reporting no success / no issue → ``LinearRequestError``."""

    async def fake_request(self: Any, query: str, variables: dict[str, Any]) -> dict[str, Any]:  # noqa: ARG001
        if "teams(" in query:
            return _team_reply()
        return _create_reply(success=False, issue=None)

    monkeypatch.setattr(LinearClient, "_request", fake_request)
    client = LinearClient(api_key="fake-key", team="CAL")
    with pytest.raises(LinearRequestError):
        await client.create_issue(
            project=None, title="T", description="D"
        )


async def test_create_issue_without_a_configured_team_raises_config_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A client built with no team (``repo.linear`` unset) refuses before any request.

    Since #328 the team is client config rather than a call argument, so this is
    where a missing one surfaces — a ``LinearConfigError`` (⊂ ``TrackerConfigError``)
    raised *lazily*, from inside ``create_issue``. That is what a neutral caller
    must map to its ``blocked`` refusal; the pin also asserts **no request was
    fired**, since a config gap must not reach the network.
    """
    requested: list[str] = []

    async def fake_request(query: str, variables: dict[str, Any]) -> dict[str, Any]:
        requested.append(query)
        return {}

    client = LinearClient(api_key="fake-key")  # no team
    monkeypatch.setattr(client, "_request", fake_request)

    with pytest.raises(LinearConfigError, match="repo.linear"):
        await client.create_issue(project=None, title="T", description="D")
    assert requested == []
