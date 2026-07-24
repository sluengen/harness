"""Unit tests for the Linear release primitives (#193, mirroring #191/#192).

``harness release`` (the return-path verb `/decision` drives) needs three
``LinearClient`` capabilities the client did not have: remove a hold label,
unassign the operator, and write a resolution into the issue body — the
"defer shape, in reverse" the proposal calls for. These tests pin that surface,
mocking the GraphQL boundary (``LinearClient._request``) exactly as
``test_linear_reclaim_primitives.py`` does for the outbound half.
"""

from __future__ import annotations

from typing import Any

import pytest

from harness.linear import LinearClient, LinearNotFound, LinearRequestError

# ---------------------------------------------------------------------------
# remove_label — release step 1: drop the hold label
# ---------------------------------------------------------------------------


async def test_remove_label_removes_a_present_label(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """remove_label resolves the issue's own labels and fires issueRemoveLabel
    for a case-insensitive name match."""
    calls: list[dict[str, Any]] = []

    async def fake_request(self: Any, query: str, variables: dict[str, Any]) -> dict[str, Any]:  # noqa: ARG001
        calls.append({"query": query, "variables": variables})
        if "issueRemoveLabel" in query:
            return {"data": {"issueRemoveLabel": {"success": True}}}
        return {
            "data": {
                "issue": {
                    "id": "issue-uuid",
                    "labels": {
                        "nodes": [
                            {"id": "lbl-decision", "name": "decision"},
                            {"id": "lbl-other", "name": "bug"},
                        ]
                    },
                }
            }
        }

    monkeypatch.setattr(LinearClient, "_request", fake_request)
    client = LinearClient(api_key="fake-key")
    await client.remove_label("CAL-193", "decision")

    remove_calls = [c for c in calls if "issueRemoveLabel" in c["query"]]
    assert len(remove_calls) == 1
    assert remove_calls[0]["variables"]["id"] == "issue-uuid"
    assert remove_calls[0]["variables"]["labelId"] == "lbl-decision"


async def test_remove_label_matches_name_case_insensitively(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, Any]] = []

    async def fake_request(self: Any, query: str, variables: dict[str, Any]) -> dict[str, Any]:  # noqa: ARG001
        calls.append({"query": query, "variables": variables})
        if "issueRemoveLabel" in query:
            return {"data": {"issueRemoveLabel": {"success": True}}}
        return {
            "data": {
                "issue": {
                    "id": "issue-uuid",
                    "labels": {"nodes": [{"id": "lbl-d", "name": "Decision"}]},
                }
            }
        }

    monkeypatch.setattr(LinearClient, "_request", fake_request)
    client = LinearClient(api_key="fake-key")
    await client.remove_label("CAL-193", "decision")
    remove_calls = [c for c in calls if "issueRemoveLabel" in c["query"]]
    assert remove_calls[0]["variables"]["labelId"] == "lbl-d"


async def test_remove_label_is_a_noop_when_absent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A ticket already missing the label is a clean no-op — idempotent release."""

    async def fake_request(self: Any, query: str, variables: dict[str, Any]) -> dict[str, Any]:  # noqa: ARG001
        if "issueRemoveLabel" in query:
            raise AssertionError("must not fire issueRemoveLabel for an absent label")
        return {
            "data": {
                "issue": {"id": "issue-uuid", "labels": {"nodes": []}},
            }
        }

    monkeypatch.setattr(LinearClient, "_request", fake_request)
    client = LinearClient(api_key="fake-key")
    await client.remove_label("CAL-193", "decision")  # no raise


async def test_remove_label_raises_when_unsuccessful(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_request(self: Any, query: str, variables: dict[str, Any]) -> dict[str, Any]:  # noqa: ARG001
        if "issueRemoveLabel" in query:
            return {"data": {"issueRemoveLabel": {"success": False}}}
        return {
            "data": {
                "issue": {
                    "id": "issue-uuid",
                    "labels": {"nodes": [{"id": "lbl-d", "name": "decision"}]},
                }
            }
        }

    monkeypatch.setattr(LinearClient, "_request", fake_request)
    client = LinearClient(api_key="fake-key")
    with pytest.raises(LinearRequestError, match="did not report success"):
        await client.remove_label("CAL-193", "decision")


async def test_remove_label_raises_not_found_for_null_issue(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_request(self: Any, query: str, variables: dict[str, Any]) -> dict[str, Any]:  # noqa: ARG001
        return {"data": {"issue": None}}

    monkeypatch.setattr(LinearClient, "_request", fake_request)
    client = LinearClient(api_key="fake-key")
    with pytest.raises(LinearNotFound):
        await client.remove_label("CAL-999", "decision")


# ---------------------------------------------------------------------------
# unassign_viewer — release step 2: the load-bearing skip signal
# ---------------------------------------------------------------------------


async def test_unassign_viewer_clears_the_assignee(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, Any]] = []

    async def fake_request(self: Any, query: str, variables: dict[str, Any]) -> dict[str, Any]:  # noqa: ARG001
        calls.append({"query": query, "variables": variables})
        if "issueUpdate" in query:
            return {"data": {"issueUpdate": {"success": True}}}
        return {"data": {"issue": {"id": "issue-uuid"}}}

    monkeypatch.setattr(LinearClient, "_request", fake_request)
    client = LinearClient(api_key="fake-key")
    await client.unassign_viewer("CAL-193")

    update_calls = [c for c in calls if "issueUpdate" in c["query"]]
    assert len(update_calls) == 1
    assert update_calls[0]["variables"]["id"] == "issue-uuid"


async def test_unassign_viewer_raises_when_unsuccessful(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_request(self: Any, query: str, variables: dict[str, Any]) -> dict[str, Any]:  # noqa: ARG001
        if "issueUpdate" in query:
            return {"data": {"issueUpdate": {"success": False}}}
        return {"data": {"issue": {"id": "issue-uuid"}}}

    monkeypatch.setattr(LinearClient, "_request", fake_request)
    client = LinearClient(api_key="fake-key")
    with pytest.raises(LinearRequestError, match="did not report success"):
        await client.unassign_viewer("CAL-193")


async def test_unassign_viewer_raises_not_found_for_null_issue(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_request(self: Any, query: str, variables: dict[str, Any]) -> dict[str, Any]:  # noqa: ARG001
        return {"data": {"issue": None}}

    monkeypatch.setattr(LinearClient, "_request", fake_request)
    client = LinearClient(api_key="fake-key")
    with pytest.raises(LinearNotFound):
        await client.unassign_viewer("CAL-999")


# ---------------------------------------------------------------------------
# update_issue_body — release step 3: the resolution lands in the change spec
# ---------------------------------------------------------------------------


async def test_update_issue_body_sets_the_description(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, Any]] = []

    async def fake_request(self: Any, query: str, variables: dict[str, Any]) -> dict[str, Any]:  # noqa: ARG001
        calls.append({"query": query, "variables": variables})
        if "issueUpdate" in query:
            return {"data": {"issueUpdate": {"success": True}}}
        return {"data": {"issue": {"id": "issue-uuid"}}}

    monkeypatch.setattr(LinearClient, "_request", fake_request)
    client = LinearClient(api_key="fake-key")
    await client.update_issue_body("CAL-193", "## Resolution\n\nGo with option A.")

    update_calls = [c for c in calls if "issueUpdate" in c["query"]]
    assert len(update_calls) == 1
    assert update_calls[0]["variables"]["id"] == "issue-uuid"
    assert update_calls[0]["variables"]["description"] == (
        "## Resolution\n\nGo with option A."
    )


async def test_update_issue_body_raises_when_unsuccessful(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_request(self: Any, query: str, variables: dict[str, Any]) -> dict[str, Any]:  # noqa: ARG001
        if "issueUpdate" in query:
            return {"data": {"issueUpdate": {"success": False}}}
        return {"data": {"issue": {"id": "issue-uuid"}}}

    monkeypatch.setattr(LinearClient, "_request", fake_request)
    client = LinearClient(api_key="fake-key")
    with pytest.raises(LinearRequestError, match="did not report success"):
        await client.update_issue_body("CAL-193", "body")


async def test_update_issue_body_raises_not_found_for_null_issue(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_request(self: Any, query: str, variables: dict[str, Any]) -> dict[str, Any]:  # noqa: ARG001
        return {"data": {"issue": None}}

    monkeypatch.setattr(LinearClient, "_request", fake_request)
    client = LinearClient(api_key="fake-key")
    with pytest.raises(LinearNotFound):
        await client.update_issue_body("CAL-999", "body")
