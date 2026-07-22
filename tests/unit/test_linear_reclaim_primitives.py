"""Unit tests for the Linear reclamation primitives (CAL-734 + CAL-736).

The run-reclamation fail-safe (proposal ``stale-run-reclamation``) needs three
``LinearClient`` capabilities the client did not have: revert a stranded ticket
to its Todo (``unstarted``) state, mark it with a label, and annotate it with a
comment (CAL-734).  The ``--stale`` sweep (CAL-736) adds a fourth: enumerate the
active (In Progress / In Review — CAL-1103) tickets in a project so the sweep can
filter them by age.  ``review`` also parks the ticket In Review (CAL-1103), the
fifth transition.  These tests pin that surface, mocking the GraphQL boundary
(``LinearClient._request``) exactly as the existing client tests do.
"""

from __future__ import annotations

import re
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
# transition_to_in_review — the review verb parks the ticket here (CAL-1103)
# ---------------------------------------------------------------------------


async def test_transition_to_in_review_targets_in_review_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """transition_to_in_review picks the **In Review** state, not the other
    ``started`` state (In Progress)."""
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
                                    {"id": "s-ir", "name": "In Review", "type": "started"},
                                    {"id": "s-done", "name": "Done", "type": "completed"},
                                ]
                            }
                        },
                    }
                }
            }
        return {"data": {"issueUpdate": {"success": True}}}

    monkeypatch.setattr(LinearClient, "_request", fake_request)
    client = LinearClient(api_key="fake-key")
    await client.transition_to_in_review("CAL-1103")

    mutation_calls = [c for c in calls if "issueUpdate" in c["query"]]
    assert len(mutation_calls) == 1
    # In Review is chosen, not the sibling started state In Progress.
    assert mutation_calls[0]["variables"]["stateId"] == "s-ir"


async def test_transition_to_in_review_raises_when_no_started_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No ``started`` state configured → LinearRequestError (not a silent no-op)."""

    async def fake_request(self: Any, query: str, variables: dict[str, Any]) -> dict[str, Any]:  # noqa: ARG001
        return {
            "data": {
                "issue": {
                    "id": "issue-id",
                    "team": {
                        "states": {
                            "nodes": [
                                {"id": "s-todo", "name": "Todo", "type": "unstarted"},
                            ]
                        }
                    },
                }
            }
        }

    monkeypatch.setattr(LinearClient, "_request", fake_request)
    client = LinearClient(api_key="fake-key")
    with pytest.raises(LinearRequestError, match="no 'started' workflow state"):
        await client.transition_to_in_review("CAL-1103")


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


async def test_assign_to_viewer_sets_assignee(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """assign_to_viewer resolves the viewer + issue ids then fires issueUpdate
    with the viewer as assigneeId — agents authenticate with the operator's key,
    so `viewer` IS the operator (the machine-readable "a human holds this" signal)."""
    calls: list[dict[str, Any]] = []

    async def fake_request(self: Any, query: str, variables: dict[str, Any]) -> dict[str, Any]:  # noqa: ARG001
        calls.append({"query": query, "variables": variables})
        if "issueUpdate" in query:
            return {"data": {"issueUpdate": {"success": True}}}
        return {"data": {"viewer": {"id": "viewer-uuid"}, "issue": {"id": "issue-uuid"}}}

    monkeypatch.setattr(LinearClient, "_request", fake_request)
    client = LinearClient(api_key="fake-key")
    await client.assign_to_viewer("CAL-1167")

    update_calls = [c for c in calls if "issueUpdate" in c["query"]]
    assert len(update_calls) == 1
    assert update_calls[0]["variables"]["id"] == "issue-uuid"
    assert update_calls[0]["variables"]["assigneeId"] == "viewer-uuid"


async def test_assign_to_viewer_raises_when_unsuccessful(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """assign_to_viewer raises LinearRequestError when issueUpdate does not report success."""

    async def fake_request(self: Any, query: str, variables: dict[str, Any]) -> dict[str, Any]:  # noqa: ARG001
        if "issueUpdate" in query:
            return {"data": {"issueUpdate": {"success": False}}}
        return {"data": {"viewer": {"id": "viewer-uuid"}, "issue": {"id": "issue-uuid"}}}

    monkeypatch.setattr(LinearClient, "_request", fake_request)
    client = LinearClient(api_key="fake-key")
    with pytest.raises(LinearRequestError, match="did not report success"):
        await client.assign_to_viewer("CAL-1167")


async def test_assign_to_viewer_raises_not_found_for_null_issue(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """assign_to_viewer raises LinearNotFound when the issue does not exist."""

    async def fake_request(self: Any, query: str, variables: dict[str, Any]) -> dict[str, Any]:  # noqa: ARG001
        return {"data": {"viewer": {"id": "viewer-uuid"}, "issue": None}}

    monkeypatch.setattr(LinearClient, "_request", fake_request)
    client = LinearClient(api_key="fake-key")
    with pytest.raises(LinearNotFound):
        await client.assign_to_viewer("CAL-999")


async def test_assign_to_viewer_raises_when_viewer_unresolved(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """assign_to_viewer raises LinearRequestError when the API key resolves no viewer."""

    async def fake_request(self: Any, query: str, variables: dict[str, Any]) -> dict[str, Any]:  # noqa: ARG001
        return {"data": {"viewer": None, "issue": {"id": "issue-uuid"}}}

    monkeypatch.setattr(LinearClient, "_request", fake_request)
    client = LinearClient(api_key="fake-key")
    with pytest.raises(LinearRequestError, match="viewer"):
        await client.assign_to_viewer("CAL-1167")


# ---------------------------------------------------------------------------
# fetch_reclaimable_issues — enumerate the sweep candidates (CAL-736 / CAL-1103)
# ---------------------------------------------------------------------------


async def test_fetch_reclaimable_issues_returns_identifier_and_updated_at(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Returns one ``{identifier, updated_at}`` per reclaimable issue, scoped to the
    project name and BOTH transient started states — In Progress **and** In Review
    (CAL-1103 parks reviewed tickets In Review, so the sweep must reach them)."""
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
    issues = await client.fetch_reclaimable_issues(project="Harness v3")

    assert issues == [
        {"identifier": "CAL-700", "updated_at": "2026-06-15T10:00:00.000Z"},
        {"identifier": "CAL-701", "updated_at": "2026-06-16T09:30:00.000Z"},
    ]
    # Scoped to the project name passed in, and to BOTH transient started states
    # by name — a dead orchestrator can strand a ticket in either (CAL-1103).
    assert captured["variables"]["project"] == "Harness v3"
    assert "In Progress" in captured["query"]
    assert "In Review" in captured["query"]
    assert "project" in captured["query"]


async def test_fetch_reclaimable_issues_empty_when_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No reclaimable issues → an empty list (a clean no-op for the sweep)."""

    async def fake_request(self: Any, query: str, variables: dict[str, Any]) -> dict[str, Any]:  # noqa: ARG001
        return {"data": {"issues": {"nodes": []}}}

    monkeypatch.setattr(LinearClient, "_request", fake_request)
    client = LinearClient(api_key="fake-key")
    assert await client.fetch_reclaimable_issues(project="Harness v3") == []


async def test_fetch_reclaimable_issues_unscoped_filters_by_team(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With no project (the whole-queue mode, #174) the sweep filters by the client's
    team key — ``repo.linear`` — so a Linear team running several projects is swept
    whole. Filtering by team (not the bare workspace) is what keeps an unscoped query
    from sweeping every team in the workspace (the proposal's stated risk)."""
    captured: dict[str, Any] = {}

    async def fake_request(self: Any, query: str, variables: dict[str, Any]) -> dict[str, Any]:  # noqa: ARG001
        captured["query"] = query
        captured["variables"] = variables
        return {
            "data": {
                "issues": {
                    "nodes": [
                        {"identifier": "CAL-700", "updatedAt": "2026-06-15T10:00:00.000Z"},
                    ]
                }
            }
        }

    monkeypatch.setattr(LinearClient, "_request", fake_request)
    client = LinearClient(api_key="fake-key", team="CAL")
    issues = await client.fetch_reclaimable_issues(project=None)

    assert issues == [{"identifier": "CAL-700", "updated_at": "2026-06-15T10:00:00.000Z"}]
    # Scoped to the team key and both transient started states — and NOT by project.
    assert captured["variables"] == {"team": "CAL"}
    assert "team" in captured["query"]
    assert "project" not in captured["query"]
    assert "In Progress" in captured["query"]
    assert "In Review" in captured["query"]


async def test_fetch_reclaimable_issues_unscoped_without_team_raises() -> None:
    """No project AND no team is unscopeable — refuse rather than sweep the whole
    workspace. In the real path ``tracker_client`` always threads ``repo.linear``;
    this guards a direct construction that forgot it. The guard fires before any
    request, so no transport stub is needed."""
    client = LinearClient(api_key="fake-key")  # constructed without a team
    with pytest.raises(LinearRequestError, match="team"):
        await client.fetch_reclaimable_issues(project=None)


# ---------------------------------------------------------------------------
# fetch_resume_branch — the preserved branch a reclaimed ticket resumes from
# (CAL-739, the read side of the reclaim-comment contract)
# ---------------------------------------------------------------------------


def _resume_issue(labels: list[str], comments: list[str]) -> dict[str, Any]:
    """A GraphQL ``issue`` payload with the given label names and comment bodies."""
    return {
        "data": {
            "issue": {
                "labels": {"nodes": [{"name": n} for n in labels]},
                "comments": {
                    "nodes": [
                        {"body": b, "createdAt": f"2026-06-16T00:0{i}:00.000Z"}
                        for i, b in enumerate(comments)
                    ]
                },
            }
        }
    }


async def test_fetch_resume_branch_returns_branch_from_latest_reclaim_comment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A reclaimed ticket whose latest reclaim comment names a branch returns it.

    The *latest* reclaim comment wins — a ticket reclaimed twice carries the
    freshest branch, so the most recent comment is authoritative.
    """
    from harness.reclaim_marker import format_reclaim_comment

    old = format_reclaim_comment("R1", "harness/old", when="2026-06-16T00:00:00Z")
    new = format_reclaim_comment("R2", "harness/new", when="2026-06-16T00:02:00Z")

    async def fake_request(self: Any, query: str, variables: dict[str, Any]) -> dict[str, Any]:  # noqa: ARG001
        return _resume_issue(["reclaimed"], [old, "an unrelated comment", new])

    monkeypatch.setattr(LinearClient, "_request", fake_request)
    client = LinearClient(api_key="fake-key")
    assert await client.fetch_resume_branch("CAL-739") == "harness/new"


async def test_fetch_resume_branch_none_without_reclaimed_label(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No ``reclaimed`` label → None even if a comment names a branch: the label
    is the structured gate that the ticket is a reclamation re-pick."""
    from harness.reclaim_marker import format_reclaim_comment

    body = format_reclaim_comment("R1", "harness/x", when="2026-06-16T00:00:00Z")

    async def fake_request(self: Any, query: str, variables: dict[str, Any]) -> dict[str, Any]:  # noqa: ARG001
        return _resume_issue(["Feature"], [body])

    monkeypatch.setattr(LinearClient, "_request", fake_request)
    client = LinearClient(api_key="fake-key")
    assert await client.fetch_resume_branch("CAL-739") is None


async def test_fetch_resume_branch_none_when_reclaim_preserved_no_branch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A reclaim that preserved no durable WIP (the sentinel) → None, so resume
    degrades to a clean restart (AC-2)."""
    from harness.reclaim_marker import format_reclaim_comment

    body = format_reclaim_comment("R1", None, when="2026-06-16T00:00:00Z")

    async def fake_request(self: Any, query: str, variables: dict[str, Any]) -> dict[str, Any]:  # noqa: ARG001
        return _resume_issue(["reclaimed"], [body])

    monkeypatch.setattr(LinearClient, "_request", fake_request)
    client = LinearClient(api_key="fake-key")
    assert await client.fetch_resume_branch("CAL-739") is None


async def test_fetch_resume_branch_none_when_no_reclaim_comment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The label is present but no comment carries the reclaim marker → None."""

    async def fake_request(self: Any, query: str, variables: dict[str, Any]) -> dict[str, Any]:  # noqa: ARG001
        return _resume_issue(["reclaimed"], ["just chatter", "more chatter"])

    monkeypatch.setattr(LinearClient, "_request", fake_request)
    client = LinearClient(api_key="fake-key")
    assert await client.fetch_resume_branch("CAL-739") is None


# ---------------------------------------------------------------------------
# fetch_handoff_branch — the preserved branch a proactively-handed-off ticket
# continues from (CAL-923). Keyed on the handoff marker, NOT the reclaimed label:
# a proactive handoff keeps the ticket In Progress with no label.
# ---------------------------------------------------------------------------


async def test_fetch_handoff_branch_returns_latest_and_needs_no_label(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A ticket with a handoff comment returns its branch — with **no** ``reclaimed``
    label (a proactive handoff stays In Progress). The latest handoff comment wins."""
    from harness.reclaim_marker import format_handoff_comment

    old = format_handoff_comment("H1", "harness/old", when="2026-07-02T00:00:00Z")
    new = format_handoff_comment("H2", "harness/new", when="2026-07-02T00:02:00Z")

    async def fake_request(self: Any, query: str, variables: dict[str, Any]) -> dict[str, Any]:  # noqa: ARG001
        return _resume_issue([], [old, "an unrelated comment", new])

    monkeypatch.setattr(LinearClient, "_request", fake_request)
    client = LinearClient(api_key="fake-key")
    assert await client.fetch_handoff_branch("CAL-923") == "harness/new"


async def test_fetch_handoff_branch_ignores_a_reclaim_comment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Non-collision at the reader level: a ticket carrying only a death-keyed
    reclaim comment yields None from the handoff reader — the proactive path never
    resumes from a reclamation's branch."""
    from harness.reclaim_marker import format_reclaim_comment

    body = format_reclaim_comment("R1", "harness/reclaimed", when="2026-07-02T00:00:00Z")

    async def fake_request(self: Any, query: str, variables: dict[str, Any]) -> dict[str, Any]:  # noqa: ARG001
        return _resume_issue(["reclaimed"], [body])

    monkeypatch.setattr(LinearClient, "_request", fake_request)
    client = LinearClient(api_key="fake-key")
    assert await client.fetch_handoff_branch("CAL-923") is None


async def test_fetch_handoff_branch_none_when_preserved_no_branch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A handoff that preserved no durable WIP (the sentinel) → None, so resume
    degrades to a clean restart."""
    from harness.reclaim_marker import format_handoff_comment

    body = format_handoff_comment("H1", None, when="2026-07-02T00:00:00Z")

    async def fake_request(self: Any, query: str, variables: dict[str, Any]) -> dict[str, Any]:  # noqa: ARG001
        return _resume_issue([], [body])

    monkeypatch.setattr(LinearClient, "_request", fake_request)
    client = LinearClient(api_key="fake-key")
    assert await client.fetch_handoff_branch("CAL-923") is None


async def test_fetch_handoff_branch_raises_not_found_for_null_issue(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A missing issue raises LinearNotFound, mirroring fetch_resume_branch."""

    async def fake_request(self: Any, query: str, variables: dict[str, Any]) -> dict[str, Any]:  # noqa: ARG001
        return {"data": {"issue": None}}

    monkeypatch.setattr(LinearClient, "_request", fake_request)
    client = LinearClient(api_key="fake-key")
    with pytest.raises(LinearNotFound):
        await client.fetch_handoff_branch("CAL-999")


async def test_fetch_resume_branch_raises_not_found_for_null_issue(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A missing issue raises LinearNotFound (the caller treats it as best-effort)."""

    async def fake_request(self: Any, query: str, variables: dict[str, Any]) -> dict[str, Any]:  # noqa: ARG001
        return {"data": {"issue": None}}

    monkeypatch.setattr(LinearClient, "_request", fake_request)
    client = LinearClient(api_key="fake-key")
    with pytest.raises(LinearNotFound):
        await client.fetch_resume_branch("CAL-999")


# ---------------------------------------------------------------------------
# Pagination window (CAL-1005): on a >20-comment ticket the newest reclaim /
# handoff marker must still land in the fetched window. The earlier queries
# asked for ``comments(first: 20)``; Linear's default connection order is
# oldest-first, so ``first: 20`` returns the *oldest* 20 and the freshest
# marker (posted just before resume) falls off the page. These tests mock the
# GraphQL boundary as a real pagination window would behave, so they are RED
# against ``first:`` and GREEN once the query windows newest-first.
# ---------------------------------------------------------------------------


def _paginating_request(
    labels: list[str], comments: list[str]
) -> Any:
    """A ``_request`` fake that honours the query's ``first:`` / ``last:`` window.

    ``comments`` is the full ordered comment history, oldest-first (index 0 is
    the oldest). Each node's ``createdAt`` increases with its index, so ``max``
    over ``createdAt`` mirrors real recency. The fake reads the ``first: N`` /
    ``last: N`` argument out of the query and returns only that slice — the
    oldest N for ``first``, the newest N for ``last`` — exactly as Linear's
    default-order connection would. This is what makes an unwindowed
    ``first: 20`` query genuinely lose the newest marker in the fixture.
    """
    nodes = [
        {"body": body, "createdAt": f"2026-06-16T00:{i:02d}:00.000Z"}
        for i, body in enumerate(comments)
    ]

    async def fake_request(self: Any, query: str, variables: dict[str, Any]) -> dict[str, Any]:  # noqa: ARG001
        match = re.search(r"comments\((first|last):\s*(\d+)\)", query)
        assert match is not None, f"comments query has no first/last window: {query!r}"
        direction, count_str = match.group(1), match.group(2)
        count = int(count_str)
        window = nodes[:count] if direction == "first" else nodes[-count:]
        return {
            "data": {
                "issue": {
                    "labels": {"nodes": [{"name": n} for n in labels]},
                    "comments": {"nodes": window},
                }
            }
        }

    return fake_request


async def test_fetch_resume_branch_finds_newest_marker_beyond_first_page(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """On a 25-comment ticket, the newest reclaim comment is the last one — it
    must still resolve. With an oldest-first ``first: 20`` window it falls off
    the page and resume degrades to a clean restart (the CAL-1005 bug)."""
    from harness.reclaim_marker import format_reclaim_comment

    marker = format_reclaim_comment(
        "R1", "harness/newest", when="2026-06-16T00:24:00Z"
    )
    comments = [f"chatter {i}" for i in range(24)] + [marker]  # 25 total, marker newest
    monkeypatch.setattr(
        LinearClient, "_request", _paginating_request(["reclaimed"], comments)
    )
    client = LinearClient(api_key="fake-key")
    assert await client.fetch_resume_branch("CAL-1005") == "harness/newest"


async def test_fetch_handoff_branch_finds_newest_marker_beyond_first_page(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The handoff reader has the same window bug: on a 25-comment ticket the
    newest handoff comment (posted just before the rollover) must resolve."""
    from harness.reclaim_marker import format_handoff_comment

    marker = format_handoff_comment(
        "H1", "harness/newest", when="2026-06-16T00:24:00Z"
    )
    comments = [f"chatter {i}" for i in range(24)] + [marker]  # 25 total, marker newest
    monkeypatch.setattr(
        LinearClient, "_request", _paginating_request([], comments)
    )
    client = LinearClient(api_key="fake-key")
    assert await client.fetch_handoff_branch("CAL-1005") == "harness/newest"
