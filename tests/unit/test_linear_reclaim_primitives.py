"""Unit tests for the Linear reclamation primitives (CAL-734 + CAL-736).

The run-reclamation fail-safe (proposal ``stale-run-reclamation``) needs three
``LinearClient`` capabilities the client did not have: revert a stranded ticket
to its Todo (``unstarted``) state, mark it with a label, and annotate it with a
comment (CAL-734).  The ``--stale`` sweep (CAL-736) adds a fourth: enumerate the
In-Progress tickets in a project so the sweep can filter them by age.  These
tests pin that surface, mocking the GraphQL boundary (``LinearClient._request``)
exactly as the existing client tests do.
"""

from __future__ import annotations

from typing import Any

import pytest

from harness.linear import LinearClient, LinearNotFound, LinearRequestError

# ---------------------------------------------------------------------------
# transition_to_unstarted — revert to Todo
# ---------------------------------------------------------------------------


async def test_transition_to_unstarted_targets_todo_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """transition_to_unstarted fires issueUpdate against the Todo (unstarted) state."""
    calls: list[dict[str, Any]] = []

    async def fake_request(self: Any, query: str, variables: dict[str, Any]) -> dict[str, Any]:  # noqa: ARG001
        calls.append({"query": query, "variables": variables})
        if "states" in query:
            return {
                "data": {
                    "issue": {
                        "id": "issue-id",
                        "team": {
                            "states": {
                                "nodes": [
                                    {"id": "s-todo", "name": "Todo", "type": "unstarted"},
                                    {"id": "s-ip", "name": "In Progress", "type": "started"},
                                    {"id": "s-backlog", "name": "Backlog", "type": "backlog"},
                                ]
                            }
                        },
                    }
                }
            }
        return {"data": {"issueUpdate": {"success": True}}}

    monkeypatch.setattr(LinearClient, "_request", fake_request)
    client = LinearClient(api_key="fake-key")
    await client.transition_to_unstarted("CAL-734")

    mutation_calls = [c for c in calls if "issueUpdate" in c["query"]]
    assert len(mutation_calls) == 1
    # The Todo (unstarted) state id is chosen, not In Progress or Backlog.
    assert mutation_calls[0]["variables"]["stateId"] == "s-todo"


async def test_transition_to_unstarted_falls_back_to_first_unstarted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With no state literally named 'Todo', the first unstarted state is used."""

    async def fake_request(self: Any, query: str, variables: dict[str, Any]) -> dict[str, Any]:  # noqa: ARG001
        if "states" in query:
            return {
                "data": {
                    "issue": {
                        "id": "issue-id",
                        "team": {
                            "states": {
                                "nodes": [
                                    {"id": "s-upnext", "name": "Up Next", "type": "unstarted"},
                                    {"id": "s-ip", "name": "In Progress", "type": "started"},
                                ]
                            }
                        },
                    }
                }
            }
        return {"data": {"issueUpdate": {"success": True}}}

    monkeypatch.setattr(LinearClient, "_request", fake_request)
    client = LinearClient(api_key="fake-key")
    captured: dict[str, Any] = {}

    async def capture(self: Any, query: str, variables: dict[str, Any]) -> dict[str, Any]:  # noqa: ARG001
        if "issueUpdate" in query:
            captured.update(variables)
        return await fake_request(self, query, variables)

    monkeypatch.setattr(LinearClient, "_request", capture)
    await client.transition_to_unstarted("CAL-734")
    assert captured["stateId"] == "s-upnext"


async def test_transition_to_unstarted_raises_when_no_unstarted_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """transition_to_unstarted raises LinearRequestError when no unstarted state exists."""

    async def fake_request(self: Any, query: str, variables: dict[str, Any]) -> dict[str, Any]:  # noqa: ARG001
        return {
            "data": {
                "issue": {
                    "id": "issue-id",
                    "team": {
                        "states": {
                            "nodes": [
                                {"id": "s-ip", "name": "In Progress", "type": "started"},
                            ]
                        }
                    },
                }
            }
        }

    monkeypatch.setattr(LinearClient, "_request", fake_request)
    client = LinearClient(api_key="fake-key")
    with pytest.raises(LinearRequestError, match="no 'unstarted' workflow state"):
        await client.transition_to_unstarted("CAL-734")


# ---------------------------------------------------------------------------
# apply_label — resolve-or-create a label and add it (additive)
# ---------------------------------------------------------------------------


async def test_apply_label_uses_existing_label(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """apply_label resolves an existing label by name and adds it without creating one."""
    calls: list[dict[str, Any]] = []

    async def fake_request(self: Any, query: str, variables: dict[str, Any]) -> dict[str, Any]:  # noqa: ARG001
        calls.append({"query": query, "variables": variables})
        if "issueLabelCreate" in query:
            raise AssertionError("must not create a label that already exists")
        if "issueAddLabel" in query:
            return {"data": {"issueAddLabel": {"success": True}}}
        # issue + team labels lookup
        return {
            "data": {
                "issue": {
                    "id": "issue-uuid",
                    "team": {
                        "id": "team-uuid",
                        "labels": {
                            "nodes": [
                                {"id": "lbl-other", "name": "bug"},
                                {"id": "lbl-reclaimed", "name": "reclaimed"},
                            ]
                        },
                    },
                }
            }
        }

    monkeypatch.setattr(LinearClient, "_request", fake_request)
    client = LinearClient(api_key="fake-key")
    await client.apply_label("CAL-734", "reclaimed")

    add_calls = [c for c in calls if "issueAddLabel" in c["query"]]
    assert len(add_calls) == 1
    # Resolved at runtime — the existing label id, never a hard-coded UUID.
    assert add_calls[0]["variables"]["labelId"] == "lbl-reclaimed"
    assert add_calls[0]["variables"]["id"] == "issue-uuid"


async def test_apply_label_creates_label_when_absent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """apply_label creates the label on the issue's team when none matches, then adds it."""
    calls: list[dict[str, Any]] = []

    async def fake_request(self: Any, query: str, variables: dict[str, Any]) -> dict[str, Any]:  # noqa: ARG001
        calls.append({"query": query, "variables": variables})
        if "issueLabelCreate" in query:
            return {
                "data": {"issueLabelCreate": {"success": True, "issueLabel": {"id": "lbl-new"}}}
            }
        if "issueAddLabel" in query:
            return {"data": {"issueAddLabel": {"success": True}}}
        return {
            "data": {
                "issue": {
                    "id": "issue-uuid",
                    "team": {"id": "team-uuid", "labels": {"nodes": []}},
                }
            }
        }

    monkeypatch.setattr(LinearClient, "_request", fake_request)
    client = LinearClient(api_key="fake-key")
    await client.apply_label("CAL-734", "reclaimed")

    create_calls = [c for c in calls if "issueLabelCreate" in c["query"]]
    assert len(create_calls) == 1
    assert create_calls[0]["variables"]["name"] == "reclaimed"
    assert create_calls[0]["variables"]["teamId"] == "team-uuid"
    add_calls = [c for c in calls if "issueAddLabel" in c["query"]]
    assert add_calls[0]["variables"]["labelId"] == "lbl-new"


async def test_apply_label_matches_name_case_insensitively(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A label differing only in case is reused, not duplicated."""
    calls: list[dict[str, Any]] = []

    async def fake_request(self: Any, query: str, variables: dict[str, Any]) -> dict[str, Any]:  # noqa: ARG001
        calls.append({"query": query, "variables": variables})
        if "issueLabelCreate" in query:
            raise AssertionError("must not create when a case-variant label exists")
        if "issueAddLabel" in query:
            return {"data": {"issueAddLabel": {"success": True}}}
        return {
            "data": {
                "issue": {
                    "id": "issue-uuid",
                    "team": {
                        "id": "team-uuid",
                        "labels": {"nodes": [{"id": "lbl-r", "name": "Reclaimed"}]},
                    },
                }
            }
        }

    monkeypatch.setattr(LinearClient, "_request", fake_request)
    client = LinearClient(api_key="fake-key")
    await client.apply_label("CAL-734", "reclaimed")
    add_calls = [c for c in calls if "issueAddLabel" in c["query"]]
    assert add_calls[0]["variables"]["labelId"] == "lbl-r"


async def test_apply_label_raises_when_create_returns_no_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """apply_label raises LinearRequestError when label creation returns no label id."""

    async def fake_request(self: Any, query: str, variables: dict[str, Any]) -> dict[str, Any]:  # noqa: ARG001
        if "issueLabelCreate" in query:
            # success reported but no issueLabel id returned.
            return {"data": {"issueLabelCreate": {"success": True, "issueLabel": None}}}
        if "issueAddLabel" in query:
            raise AssertionError("must not add a label that was never created")
        return {
            "data": {
                "issue": {
                    "id": "issue-uuid",
                    "team": {"id": "team-uuid", "labels": {"nodes": []}},
                }
            }
        }

    monkeypatch.setattr(LinearClient, "_request", fake_request)
    client = LinearClient(api_key="fake-key")
    with pytest.raises(LinearRequestError, match="did not return a label"):
        await client.apply_label("CAL-734", "reclaimed")


async def test_apply_label_raises_when_add_unsuccessful(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """apply_label raises LinearRequestError when issueAddLabel does not report success."""

    async def fake_request(self: Any, query: str, variables: dict[str, Any]) -> dict[str, Any]:  # noqa: ARG001
        if "issueAddLabel" in query:
            return {"data": {"issueAddLabel": {"success": False}}}
        return {
            "data": {
                "issue": {
                    "id": "issue-uuid",
                    "team": {
                        "id": "team-uuid",
                        "labels": {"nodes": [{"id": "lbl-r", "name": "reclaimed"}]},
                    },
                }
            }
        }

    monkeypatch.setattr(LinearClient, "_request", fake_request)
    client = LinearClient(api_key="fake-key")
    with pytest.raises(LinearRequestError, match="did not report success"):
        await client.apply_label("CAL-734", "reclaimed")


async def test_apply_label_raises_not_found_for_null_issue(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """apply_label raises LinearNotFound when the issue does not exist."""

    async def fake_request(self: Any, query: str, variables: dict[str, Any]) -> dict[str, Any]:  # noqa: ARG001
        return {"data": {"issue": None}}

    monkeypatch.setattr(LinearClient, "_request", fake_request)
    client = LinearClient(api_key="fake-key")
    with pytest.raises(LinearNotFound):
        await client.apply_label("CAL-999", "reclaimed")


# ---------------------------------------------------------------------------
# post_comment — annotate an issue
# ---------------------------------------------------------------------------


async def test_post_comment_creates_comment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """post_comment resolves the issue id then fires commentCreate with the body."""
    calls: list[dict[str, Any]] = []

    async def fake_request(self: Any, query: str, variables: dict[str, Any]) -> dict[str, Any]:  # noqa: ARG001
        calls.append({"query": query, "variables": variables})
        if "commentCreate" in query:
            return {"data": {"commentCreate": {"success": True}}}
        return {"data": {"issue": {"id": "issue-uuid"}}}

    monkeypatch.setattr(LinearClient, "_request", fake_request)
    client = LinearClient(api_key="fake-key")
    await client.post_comment("CAL-734", "reclaimed after 90m idle")

    comment_calls = [c for c in calls if "commentCreate" in c["query"]]
    assert len(comment_calls) == 1
    assert comment_calls[0]["variables"]["issueId"] == "issue-uuid"
    assert comment_calls[0]["variables"]["body"] == "reclaimed after 90m idle"


async def test_post_comment_raises_when_unsuccessful(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """post_comment raises LinearRequestError when commentCreate does not report success."""

    async def fake_request(self: Any, query: str, variables: dict[str, Any]) -> dict[str, Any]:  # noqa: ARG001
        if "commentCreate" in query:
            return {"data": {"commentCreate": {"success": False}}}
        return {"data": {"issue": {"id": "issue-uuid"}}}

    monkeypatch.setattr(LinearClient, "_request", fake_request)
    client = LinearClient(api_key="fake-key")
    with pytest.raises(LinearRequestError, match="did not report success"):
        await client.post_comment("CAL-734", "body")


async def test_post_comment_raises_not_found_for_null_issue(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """post_comment raises LinearNotFound when the issue does not exist."""

    async def fake_request(self: Any, query: str, variables: dict[str, Any]) -> dict[str, Any]:  # noqa: ARG001
        return {"data": {"issue": None}}

    monkeypatch.setattr(LinearClient, "_request", fake_request)
    client = LinearClient(api_key="fake-key")
    with pytest.raises(LinearNotFound):
        await client.post_comment("CAL-999", "body")


# ---------------------------------------------------------------------------
# fetch_in_progress_issues — enumerate the sweep candidates (CAL-736)
# ---------------------------------------------------------------------------


async def test_fetch_in_progress_issues_returns_identifier_and_updated_at(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Returns one ``{identifier, updated_at}`` per In-Progress issue, scoped to the
    project name and the **In Progress** state (so In Review is never swept)."""
    captured: dict[str, Any] = {}

    async def fake_request(self: Any, query: str, variables: dict[str, Any]) -> dict[str, Any]:  # noqa: ARG001
        captured["query"] = query
        captured["variables"] = variables
        return {
            "data": {
                "issues": {
                    "nodes": [
                        {"identifier": "CAL-700", "updatedAt": "2026-06-15T10:00:00.000Z"},
                        {"identifier": "CAL-701", "updatedAt": "2026-06-16T09:30:00.000Z"},
                    ]
                }
            }
        }

    monkeypatch.setattr(LinearClient, "_request", fake_request)
    client = LinearClient(api_key="fake-key")
    issues = await client.fetch_in_progress_issues(project="Harness v3")

    assert issues == [
        {"identifier": "CAL-700", "updated_at": "2026-06-15T10:00:00.000Z"},
        {"identifier": "CAL-701", "updated_at": "2026-06-16T09:30:00.000Z"},
    ]
    # Scoped to the project name passed in, and to the In Progress state by name —
    # the other ``started`` state (In Review, a legitimate handoff) is excluded.
    assert captured["variables"]["project"] == "Harness v3"
    assert "In Progress" in captured["query"]
    assert "project" in captured["query"]


async def test_fetch_in_progress_issues_empty_when_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No In-Progress issues → an empty list (a clean no-op for the sweep)."""

    async def fake_request(self: Any, query: str, variables: dict[str, Any]) -> dict[str, Any]:  # noqa: ARG001
        return {"data": {"issues": {"nodes": []}}}

    monkeypatch.setattr(LinearClient, "_request", fake_request)
    client = LinearClient(api_key="fake-key")
    assert await client.fetch_in_progress_issues(project="Harness v3") == []
