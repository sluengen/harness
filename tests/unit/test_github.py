"""The GitHub Projects v2 tracker backend (CAL-1105).

Exercises :class:`harness.github.GitHubClient` — the second ``Tracker`` seam
implementation — against a stubbed GraphQL transport. Each test installs a fake
``_request`` that dispatches on the GraphQL operation name (``query FetchIssue``,
``mutation SetStatus``, …) and returns a canned response, so the tests pin the
*shape* of each query/mutation and the client's handling of the reply without a
network. The live start→review→close proof (AC-1) is a separate manual
demonstration; these unit tests cover the method contracts and error branches.
"""

from __future__ import annotations

import asyncio
import re
import urllib.error
from typing import Any
from unittest.mock import patch

import pytest

from harness.github import (
    GitHubClient,
    GitHubConfigError,
    GitHubNotFound,
    GitHubRequestError,
    github_token,
)
from harness.layers import GitHubSettings
from harness.reclaim_marker import (
    format_handoff_comment,
    format_reclaim_comment,
)
from harness.tracker_errors import (
    TrackerConfigError,
    TrackerNotFound,
    TrackerRequestError,
)

# ---------------------------------------------------------------------------
# Test harness: a fake GraphQL transport dispatching on operation name.
# ---------------------------------------------------------------------------

_OP = re.compile(r"(?:query|mutation)\s+(\w+)")


def _settings(status_field: str = "Status") -> GitHubSettings:
    return GitHubSettings(repo="acme/widgets", project="acme/7", status_field=status_field)


def _client(responses: dict[str, Any], *, settings: GitHubSettings | None = None) -> GitHubClient:
    """A GitHubClient whose ``_request`` returns canned responses by operation name.

    A response value that is an ``Exception`` is raised; a callable is invoked
    with ``variables``; otherwise it is returned verbatim.
    """
    client = GitHubClient(token="tok", settings=settings or _settings())
    calls: list[tuple[str | None, dict[str, Any]]] = []

    async def fake_request(query: str, variables: dict[str, Any]) -> dict[str, Any]:
        match = _OP.search(query)
        op = match.group(1) if match else None
        calls.append((op, variables))
        if op not in responses:
            raise AssertionError(f"unexpected GraphQL operation {op!r}")
        value = responses[op]
        if isinstance(value, Exception):
            raise value
        if callable(value):
            return value(variables)
        return value

    client._request = fake_request  # type: ignore[method-assign]
    client.calls = calls  # type: ignore[attr-defined]
    return client


_PROJECT_META = {
    "data": {
        "user": {
            "projectV2": {
                "id": "PVT_1",
                "title": "Build",
                "field": {
                    "id": "FLD_1",
                    "name": "Status",
                    "options": [
                        {"id": "opt_todo", "name": "Todo"},
                        {"id": "opt_prog", "name": "In Progress"},
                        {"id": "opt_rev", "name": "In Review"},
                        {"id": "opt_done", "name": "Done"},
                    ],
                },
            }
        }
    }
}
_OWNER_USER = {"data": {"repositoryOwner": {"__typename": "User"}}}


def _run(coro: Any) -> Any:
    return asyncio.run(coro)


# ---------------------------------------------------------------------------
# Config + construction
# ---------------------------------------------------------------------------


def test_github_token_reads_the_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GITHUB_TOKEN", "gho_abc")
    assert github_token() == "gho_abc"


def test_github_token_missing_raises_config_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    with pytest.raises(GitHubConfigError, match="GITHUB_TOKEN"):
        github_token()


def test_bad_repo_shape_is_a_config_error() -> None:
    bad = GitHubSettings(repo="acme", project="acme/7", status_field="Status")
    with pytest.raises(GitHubConfigError, match="github.repo"):
        GitHubClient(token="t", settings=bad)


def test_bad_project_number_is_a_config_error() -> None:
    bad = GitHubSettings(repo="a/b", project="acme/notanum", status_field="Status")
    with pytest.raises(GitHubConfigError, match="project number"):
        GitHubClient(token="t", settings=bad)


def test_config_errors_are_tracker_config_errors() -> None:
    """The backend's config error subclasses the agnostic base the verbs catch."""
    assert issubclass(GitHubConfigError, TrackerConfigError)
    assert issubclass(GitHubNotFound, TrackerNotFound)
    assert issubclass(GitHubRequestError, TrackerRequestError)


# ---------------------------------------------------------------------------
# fetch_issue
# ---------------------------------------------------------------------------


def test_fetch_issue_returns_compact_dict() -> None:
    client = _client(
        {
            "FetchIssue": {
                "data": {
                    "repository": {
                        "issue": {
                            "id": "I_42",
                            "number": 42,
                            "title": "Fix the thing",
                            "body": "Do it",
                            "url": "https://github.com/acme/widgets/issues/42",
                            "labels": {"nodes": []},
                        }
                    }
                }
            }
        }
    )
    out = _run(client.fetch_issue("#42"))
    assert out == {
        "id": "I_42",
        "identifier": "42",
        "title": "Fix the thing",
        "description": "Do it",
        "url": "https://github.com/acme/widgets/issues/42",
        "labels": [],
    }


def test_fetch_issue_includes_labels() -> None:
    """#177: fetch_issue surfaces label names so the review verb can resolve a
    ticket's model tier off them."""
    client = _client(
        {
            "FetchIssue": {
                "data": {
                    "repository": {
                        "issue": {
                            "id": "I_42",
                            "number": 42,
                            "title": "Fix the thing",
                            "body": "Do it",
                            "url": "https://github.com/acme/widgets/issues/42",
                            "labels": {"nodes": [{"name": "bug"}, {"name": "review:opus"}]},
                        }
                    }
                }
            }
        }
    )
    out = _run(client.fetch_issue("#42"))
    assert out["labels"] == ["bug", "review:opus"]


def test_fetch_issue_missing_repo_raises_not_found() -> None:
    client = _client({"FetchIssue": {"data": {"repository": None}}})
    with pytest.raises(GitHubNotFound, match="repository"):
        _run(client.fetch_issue("42"))


def test_fetch_issue_missing_issue_raises_not_found() -> None:
    client = _client({"FetchIssue": {"data": {"repository": {"issue": None}}}})
    with pytest.raises(GitHubNotFound, match="#42"):
        _run(client.fetch_issue("42"))


def test_non_numeric_identifier_raises_not_found() -> None:
    client = _client({})
    with pytest.raises(GitHubNotFound, match="not a GitHub issue number"):
        _run(client.fetch_issue("CAL-1105"))


# ---------------------------------------------------------------------------
# transitions — Projects v2 single-select status
# ---------------------------------------------------------------------------


def test_transition_adds_to_board_when_absent_then_sets_status() -> None:
    client = _client(
        {
            "OwnerKind": _OWNER_USER,
            "ProjectMeta": _PROJECT_META,
            "IssueItems": {
                "data": {"repository": {"issue": {"id": "I_42", "projectItems": {"nodes": []}}}}
            },
            "AddItem": {"data": {"addProjectV2ItemById": {"item": {"id": "ITEM_9"}}}},
            "SetStatus": {
                "data": {"updateProjectV2ItemFieldValue": {"projectV2Item": {"id": "ITEM_9"}}}
            },
        }
    )
    _run(client.transition_to_in_progress("42"))
    ops = [op for op, _ in client.calls]  # type: ignore[attr-defined]
    assert "AddItem" in ops
    set_vars = next(v for op, v in client.calls if op == "SetStatus")  # type: ignore[attr-defined]
    assert set_vars["optionId"] == "opt_prog"
    assert set_vars["itemId"] == "ITEM_9"
    assert set_vars["fieldId"] == "FLD_1"


def test_transition_uses_existing_board_item() -> None:
    client = _client(
        {
            "OwnerKind": _OWNER_USER,
            "ProjectMeta": _PROJECT_META,
            "IssueItems": {
                "data": {
                    "repository": {
                        "issue": {
                            "id": "I_42",
                            "projectItems": {
                                "nodes": [{"id": "ITEM_5", "project": {"id": "PVT_1"}}]
                            },
                        }
                    }
                }
            },
            "SetStatus": {
                "data": {"updateProjectV2ItemFieldValue": {"projectV2Item": {"id": "ITEM_5"}}}
            },
        }
    )
    _run(client.transition_to_done("42"))
    ops = [op for op, _ in client.calls]  # type: ignore[attr-defined]
    assert "AddItem" not in ops
    set_vars = next(v for op, v in client.calls if op == "SetStatus")  # type: ignore[attr-defined]
    assert set_vars["optionId"] == "opt_done"
    assert set_vars["itemId"] == "ITEM_5"


def test_transition_in_review_and_unstarted_map_to_named_options() -> None:
    def make() -> GitHubClient:
        return _client(
            {
                "OwnerKind": _OWNER_USER,
                "ProjectMeta": _PROJECT_META,
                "IssueItems": {
                    "data": {
                        "repository": {
                            "issue": {
                                "id": "I_42",
                                "projectItems": {
                                    "nodes": [{"id": "IT", "project": {"id": "PVT_1"}}]
                                },
                            }
                        }
                    }
                },
                "SetStatus": {
                    "data": {"updateProjectV2ItemFieldValue": {"projectV2Item": {"id": "IT"}}}
                },
            }
        )

    c1 = make()
    _run(c1.transition_to_in_review("42"))
    assert next(v for op, v in c1.calls if op == "SetStatus")["optionId"] == "opt_rev"  # type: ignore[attr-defined]

    c2 = make()
    _run(c2.transition_to_unstarted("42"))
    assert next(v for op, v in c2.calls if op == "SetStatus")["optionId"] == "opt_todo"  # type: ignore[attr-defined]


def test_transition_missing_status_option_raises() -> None:
    meta_no_review = {
        "data": {
            "user": {
                "projectV2": {
                    "id": "PVT_1",
                    "title": "Build",
                    "field": {
                        "id": "FLD_1",
                        "name": "Status",
                        "options": [{"id": "opt_todo", "name": "Todo"}],
                    },
                }
            }
        }
    }
    client = _client({"OwnerKind": _OWNER_USER, "ProjectMeta": meta_no_review})
    with pytest.raises(GitHubRequestError, match="In Progress"):
        _run(client.transition_to_in_progress("42"))


def test_owner_kind_organization_uses_organization_root() -> None:
    org_meta = {"data": {"organization": {"projectV2": _PROJECT_META["data"]["user"]["projectV2"]}}}
    client = _client(
        {
            "OwnerKind": {"data": {"repositoryOwner": {"__typename": "Organization"}}},
            "ProjectMeta": org_meta,
            "IssueItems": {
                "data": {
                    "repository": {
                        "issue": {
                            "id": "I_1",
                            "projectItems": {"nodes": [{"id": "IT", "project": {"id": "PVT_1"}}]},
                        }
                    }
                }
            },
            "SetStatus": {
                "data": {"updateProjectV2ItemFieldValue": {"projectV2Item": {"id": "IT"}}}
            },
        }
    )
    _run(client.transition_to_done("1"))
    # ProjectMeta was resolved through the organization root, not user.
    assert next(v for op, v in client.calls if op == "SetStatus")["optionId"] == "opt_done"  # type: ignore[attr-defined]


def test_missing_board_raises_not_found() -> None:
    client = _client(
        {"OwnerKind": _OWNER_USER, "ProjectMeta": {"data": {"user": {"projectV2": None}}}}
    )
    with pytest.raises(GitHubNotFound, match="board"):
        _run(client.transition_to_in_progress("42"))


def test_missing_status_field_raises_request_error() -> None:
    meta_no_field = {"data": {"user": {"projectV2": {"id": "PVT_1", "title": "B", "field": None}}}}
    client = _client({"OwnerKind": _OWNER_USER, "ProjectMeta": meta_no_field})
    with pytest.raises(GitHubRequestError, match="single-select field"):
        _run(client.transition_to_in_progress("42"))


def test_unknown_owner_raises_not_found() -> None:
    client = _client({"OwnerKind": {"data": {"repositoryOwner": None}}})
    with pytest.raises(GitHubNotFound, match="owner"):
        _run(client.transition_to_in_progress("42"))


# ---------------------------------------------------------------------------
# fetch_issue_project + fetch_reclaimable_issues
# ---------------------------------------------------------------------------


def test_fetch_issue_project_returns_board_title_when_on_board() -> None:
    client = _client(
        {
            "OwnerKind": _OWNER_USER,
            "ProjectMeta": _PROJECT_META,
            "IssueProjects": {
                "data": {
                    "repository": {
                        "issue": {
                            "id": "I_1",
                            "projectItems": {
                                "nodes": [{"project": {"id": "PVT_1", "title": "Build"}}]
                            },
                        }
                    }
                }
            },
        }
    )
    assert _run(client.fetch_issue_project("1")) == "Build"


def test_fetch_issue_project_none_when_not_on_board() -> None:
    client = _client(
        {
            "OwnerKind": _OWNER_USER,
            "ProjectMeta": _PROJECT_META,
            "IssueProjects": {
                "data": {
                    "repository": {
                        "issue": {
                            "id": "I_1",
                            "projectItems": {
                                "nodes": [{"project": {"id": "OTHER", "title": "Elsewhere"}}]
                            },
                        }
                    }
                }
            },
        }
    )
    assert _run(client.fetch_issue_project("1")) is None


# ---------------------------------------------------------------------------
# issue_is_done (#233) — the read-only verification `close` uses to confirm
# a Done transition actually took.
# ---------------------------------------------------------------------------


def test_issue_is_done_true_when_status_is_done() -> None:
    client = _client(
        {
            "OwnerKind": _OWNER_USER,
            "ProjectMeta": _PROJECT_META,
            "IssueStatus": {
                "data": {
                    "repository": {
                        "issue": {
                            "id": "I_1",
                            "projectItems": {
                                "nodes": [
                                    {
                                        "project": {"id": "PVT_1"},
                                        "fieldValueByName": {"name": "Done"},
                                    }
                                ]
                            },
                        }
                    }
                }
            },
        }
    )
    assert _run(client.issue_is_done("1")) is True


def test_issue_is_done_false_when_status_is_in_review() -> None:
    client = _client(
        {
            "OwnerKind": _OWNER_USER,
            "ProjectMeta": _PROJECT_META,
            "IssueStatus": {
                "data": {
                    "repository": {
                        "issue": {
                            "id": "I_1",
                            "projectItems": {
                                "nodes": [
                                    {
                                        "project": {"id": "PVT_1"},
                                        "fieldValueByName": {"name": "In Review"},
                                    }
                                ]
                            },
                        }
                    }
                }
            },
        }
    )
    assert _run(client.issue_is_done("1")) is False


def test_issue_is_done_false_when_issue_on_no_board_item() -> None:
    """An issue not on the configured board's items at all is simply not done —
    never an error, and never a reason to add it (verification mutates nothing)."""
    client = _client(
        {
            "OwnerKind": _OWNER_USER,
            "ProjectMeta": _PROJECT_META,
            "IssueStatus": {
                "data": {
                    "repository": {
                        "issue": {"id": "I_1", "projectItems": {"nodes": []}}
                    }
                }
            },
        }
    )
    assert _run(client.issue_is_done("1")) is False


def test_issue_is_done_never_mutates_the_board() -> None:
    """The verification read must never add the issue to the board or set its
    status — those mutations are not in the fake's canned responses, so if the
    client called either, the fake's ``AssertionError`` for an unlisted
    operation would fail this test."""
    client = _client(
        {
            "OwnerKind": _OWNER_USER,
            "ProjectMeta": _PROJECT_META,
            "IssueStatus": {
                "data": {
                    "repository": {
                        "issue": {"id": "I_1", "projectItems": {"nodes": []}}
                    }
                }
            },
        }
    )
    _run(client.issue_is_done("1"))
    ops = [op for op, _ in client.calls]  # type: ignore[attr-defined]
    assert "AddItem" not in ops
    assert "SetStatus" not in ops


def test_issue_is_done_raises_not_found_for_missing_issue() -> None:
    client = _client(
        {
            "OwnerKind": _OWNER_USER,
            "ProjectMeta": _PROJECT_META,
            "IssueStatus": {"data": {"repository": {"issue": None}}},
        }
    )
    with pytest.raises(GitHubNotFound):
        _run(client.issue_is_done("1"))


def test_fetch_reclaimable_filters_to_transient_states() -> None:
    items = {
        "data": {
            "user": {
                "projectV2": {
                    "items": {
                        "nodes": [
                            {
                                "content": {"number": 1, "updatedAt": "2026-07-21T00:00:00Z"},
                                "fieldValueByName": {"name": "In Progress"},
                            },
                            {
                                "content": {"number": 2, "updatedAt": "2026-07-21T01:00:00Z"},
                                "fieldValueByName": {"name": "In Review"},
                            },
                            {
                                "content": {"number": 3, "updatedAt": "2026-07-21T02:00:00Z"},
                                "fieldValueByName": {"name": "Done"},
                            },
                            {  # a draft/PR item with no issue content — skipped
                                "content": {},
                                "fieldValueByName": {"name": "In Progress"},
                            },
                            {  # no status set — skipped
                                "content": {"number": 5, "updatedAt": "z"},
                                "fieldValueByName": None,
                            },
                        ]
                    }
                }
            }
        }
    }
    client = _client({"OwnerKind": _OWNER_USER, "ProjectMeta": _PROJECT_META, "Reclaimable": items})
    out = _run(client.fetch_reclaimable_issues(project="Build"))
    assert out == [
        {"identifier": "1", "updated_at": "2026-07-21T00:00:00Z"},
        {"identifier": "2", "updated_at": "2026-07-21T01:00:00Z"},
    ]


def test_fetch_reclaimable_unscoped_is_the_same_board_sweep() -> None:
    """AC-3 (#174): the board itself *is* the queue, so ``project=None`` sweeps
    exactly the same board as any project value — the unset path is the GitHub
    backend's current behaviour, unchanged by the seam widening."""
    items = {
        "data": {
            "user": {
                "projectV2": {
                    "items": {
                        "nodes": [
                            {
                                "content": {"number": 1, "updatedAt": "2026-07-21T00:00:00Z"},
                                "fieldValueByName": {"name": "In Progress"},
                            },
                        ]
                    }
                }
            }
        }
    }
    client = _client(
        {"OwnerKind": _OWNER_USER, "ProjectMeta": _PROJECT_META, "Reclaimable": items}
    )
    assert _run(client.fetch_reclaimable_issues(project=None)) == [
        {"identifier": "1", "updated_at": "2026-07-21T00:00:00Z"},
    ]


# ---------------------------------------------------------------------------
# apply_label, post_comment, assign_to_viewer, create_issue
# ---------------------------------------------------------------------------


def test_apply_label_uses_existing_label() -> None:
    client = _client(
        {
            "IssueAndLabel": {
                "data": {
                    "repository": {
                        "id": "R_1",
                        "issue": {"id": "I_1"},
                        "label": {"id": "L_dec"},
                    }
                }
            },
            "AddLabel": {"data": {"addLabelsToLabelable": {"labelable": {"id": "I_1"}}}},
        }
    )
    _run(client.apply_label("1", "decision"))
    add = next(v for op, v in client.calls if op == "AddLabel")  # type: ignore[attr-defined]
    assert add["labelIds"] == ["L_dec"]


def test_apply_label_creates_when_missing() -> None:
    client = _client(
        {
            "IssueAndLabel": {
                "data": {"repository": {"id": "R_1", "issue": {"id": "I_1"}, "label": None}}
            },
            "CreateLabel": {"data": {"createLabel": {"label": {"id": "L_new"}}}},
            "AddLabel": {"data": {"addLabelsToLabelable": {"labelable": {"id": "I_1"}}}},
        }
    )
    _run(client.apply_label("1", "reclaimed"))
    ops = [op for op, _ in client.calls]  # type: ignore[attr-defined]
    assert "CreateLabel" in ops
    add = next(v for op, v in client.calls if op == "AddLabel")  # type: ignore[attr-defined]
    assert add["labelIds"] == ["L_new"]


def test_apply_label_missing_issue_raises_not_found() -> None:
    client = _client(
        {"IssueAndLabel": {"data": {"repository": {"id": "R_1", "issue": None, "label": None}}}}
    )
    with pytest.raises(GitHubNotFound):
        _run(client.apply_label("1", "decision"))


def test_post_comment_addresses_the_issue_node() -> None:
    client = _client(
        {
            "IssueNode": {"data": {"repository": {"issue": {"id": "I_1"}}}},
            "AddComment": {"data": {"addComment": {"commentEdge": {"node": {"id": "C_1"}}}}},
        }
    )
    _run(client.post_comment("1", "hello"))
    add = next(v for op, v in client.calls if op == "AddComment")  # type: ignore[attr-defined]
    assert add == {"subjectId": "I_1", "body": "hello"}


def test_assign_to_viewer_assigns_the_token_user() -> None:
    client = _client(
        {
            "ViewerAndIssue": {
                "data": {"viewer": {"id": "U_me"}, "repository": {"issue": {"id": "I_1"}}}
            },
            "AssignIssue": {"data": {"addAssigneesToAssignable": {"assignable": {"id": "I_1"}}}},
        }
    )
    _run(client.assign_to_viewer("1"))
    assign = next(v for op, v in client.calls if op == "AssignIssue")  # type: ignore[attr-defined]
    assert assign["assigneeIds"] == ["U_me"]


def test_assign_to_viewer_no_viewer_raises() -> None:
    client = _client(
        {"ViewerAndIssue": {"data": {"viewer": None, "repository": {"issue": {"id": "I_1"}}}}}
    )
    with pytest.raises(GitHubRequestError, match="viewer"):
        _run(client.assign_to_viewer("1"))


def test_create_issue_creates_and_adds_to_board() -> None:
    client = _client(
        {
            "RepoId": {"data": {"repository": {"id": "R_1"}}},
            "CreateIssue": {
                "data": {
                    "createIssue": {
                        "issue": {
                            "id": "I_new",
                            "number": 99,
                            "url": "https://github.com/acme/widgets/issues/99",
                        }
                    }
                }
            },
            "OwnerKind": _OWNER_USER,
            "ProjectMeta": _PROJECT_META,
            "AddItem": {"data": {"addProjectV2ItemById": {"item": {"id": "IT_new"}}}},
        }
    )
    out = _run(
        client.create_issue(team_key="CAL", project_name=None, title="T", description="B")
    )
    assert out == {"identifier": "99", "url": "https://github.com/acme/widgets/issues/99"}
    ops = [op for op, _ in client.calls]  # type: ignore[attr-defined]
    assert "AddItem" in ops  # the new issue lands on the board (the queue)


def test_create_issue_missing_repo_raises_not_found() -> None:
    client = _client({"RepoId": {"data": {"repository": None}}})
    with pytest.raises(GitHubNotFound, match="repository"):
        _run(client.create_issue(team_key="CAL", project_name=None, title="T", description="B"))


# ---------------------------------------------------------------------------
# remove_label, unassign_viewer, update_issue_body — the release primitives
# (#193, the ``defer`` shape in reverse: apply_label/assign_to_viewer/
# post_comment's mirror image)
# ---------------------------------------------------------------------------


def test_remove_label_removes_a_present_label() -> None:
    client = _client(
        {
            "IssueLabels": {
                "data": {
                    "repository": {
                        "issue": {
                            "id": "I_1",
                            "labels": {"nodes": [{"id": "L_dec", "name": "decision"}]},
                        }
                    }
                }
            },
            "RemoveLabel": {
                "data": {"removeLabelsFromLabelable": {"labelable": {"id": "I_1"}}}
            },
        }
    )
    _run(client.remove_label("1", "decision"))
    remove = next(v for op, v in client.calls if op == "RemoveLabel")  # type: ignore[attr-defined]
    assert remove == {"labelableId": "I_1", "labelIds": ["L_dec"]}


def test_remove_label_matches_name_case_insensitively() -> None:
    client = _client(
        {
            "IssueLabels": {
                "data": {
                    "repository": {
                        "issue": {
                            "id": "I_1",
                            "labels": {"nodes": [{"id": "L_dec", "name": "Decision"}]},
                        }
                    }
                }
            },
            "RemoveLabel": {
                "data": {"removeLabelsFromLabelable": {"labelable": {"id": "I_1"}}}
            },
        }
    )
    _run(client.remove_label("1", "decision"))
    remove = next(v for op, v in client.calls if op == "RemoveLabel")  # type: ignore[attr-defined]
    assert remove["labelIds"] == ["L_dec"]


def test_remove_label_is_a_noop_when_absent() -> None:
    """A ticket already missing the label is a clean no-op — idempotent release."""
    client = _client(
        {
            "IssueLabels": {
                "data": {"repository": {"issue": {"id": "I_1", "labels": {"nodes": []}}}}
            },
            "RemoveLabel": AssertionError("must not fire for an absent label"),
        }
    )
    _run(client.remove_label("1", "decision"))  # no raise
    ops = [op for op, _ in client.calls]  # type: ignore[attr-defined]
    assert "RemoveLabel" not in ops


def test_remove_label_missing_issue_raises_not_found() -> None:
    client = _client(
        {"IssueLabels": {"data": {"repository": {"issue": None}}}}
    )
    with pytest.raises(GitHubNotFound):
        _run(client.remove_label("1", "decision"))


def test_unassign_viewer_clears_the_assignee() -> None:
    client = _client(
        {
            "ViewerAndIssue": {
                "data": {"viewer": {"id": "U_me"}, "repository": {"issue": {"id": "I_1"}}}
            },
            "UnassignIssue": {
                "data": {"removeAssigneesFromAssignable": {"assignable": {"id": "I_1"}}}
            },
        }
    )
    _run(client.unassign_viewer("1"))
    unassign = next(v for op, v in client.calls if op == "UnassignIssue")  # type: ignore[attr-defined]
    assert unassign == {"assignableId": "I_1", "assigneeIds": ["U_me"]}


def test_unassign_viewer_no_viewer_raises() -> None:
    client = _client(
        {"ViewerAndIssue": {"data": {"viewer": None, "repository": {"issue": {"id": "I_1"}}}}}
    )
    with pytest.raises(GitHubRequestError, match="viewer"):
        _run(client.unassign_viewer("1"))


def test_unassign_viewer_missing_issue_raises_not_found() -> None:
    client = _client(
        {"ViewerAndIssue": {"data": {"viewer": {"id": "U_me"}, "repository": {"issue": None}}}}
    )
    with pytest.raises(GitHubNotFound):
        _run(client.unassign_viewer("1"))


def test_update_issue_body_sets_the_body() -> None:
    client = _client(
        {
            "IssueNode": {"data": {"repository": {"issue": {"id": "I_1"}}}},
            "UpdateIssueBody": {"data": {"updateIssue": {"issue": {"id": "I_1"}}}},
        }
    )
    _run(client.update_issue_body("1", "## Resolution\n\nGo with option A."))
    update = next(v for op, v in client.calls if op == "UpdateIssueBody")  # type: ignore[attr-defined]
    assert update == {"id": "I_1", "body": "## Resolution\n\nGo with option A."}


def test_update_issue_body_raises_when_no_result() -> None:
    client = _client(
        {
            "IssueNode": {"data": {"repository": {"issue": {"id": "I_1"}}}},
            "UpdateIssueBody": {"data": {"updateIssue": None}},
        }
    )
    with pytest.raises(GitHubRequestError):
        _run(client.update_issue_body("1", "body"))


def test_update_issue_body_missing_issue_raises_not_found() -> None:
    client = _client({"IssueNode": {"data": {"repository": {"issue": None}}}})
    with pytest.raises(GitHubNotFound):
        _run(client.update_issue_body("1", "body"))


# ---------------------------------------------------------------------------
# resume / handoff markers (AC-3) — issue comments
# ---------------------------------------------------------------------------


def _marked_issue(*, labels: list[str], comments: list[str]) -> dict[str, Any]:
    return {
        "data": {
            "repository": {
                "issue": {
                    "labels": {"nodes": [{"name": n} for n in labels]},
                    "comments": {
                        "nodes": [
                            {"body": b, "createdAt": f"2026-07-21T00:0{i}:00Z"}
                            for i, b in enumerate(comments)
                        ]
                    },
                }
            }
        }
    }


def test_fetch_resume_branch_reads_latest_reclaim_comment() -> None:
    comment = format_reclaim_comment("RUN-1", "wip/recovered", when="2026-07-21T00:00:00Z")
    client = _client({"MarkedBranch": _marked_issue(labels=["reclaimed"], comments=[comment])})
    assert _run(client.fetch_resume_branch("1")) == "wip/recovered"


def test_fetch_resume_branch_requires_the_reclaimed_label() -> None:
    comment = format_reclaim_comment("RUN-1", "wip/recovered", when="2026-07-21T00:00:00Z")
    client = _client({"MarkedBranch": _marked_issue(labels=[], comments=[comment])})
    assert _run(client.fetch_resume_branch("1")) is None


def test_fetch_handoff_branch_reads_the_handoff_marker() -> None:
    comment = format_handoff_comment("RUN-1", "wip/handoff", when="2026-07-21T00:00:00Z")
    client = _client({"MarkedBranch": _marked_issue(labels=[], comments=[comment])})
    assert _run(client.fetch_handoff_branch("1")) == "wip/handoff"


def test_handoff_does_not_read_a_reclaim_comment() -> None:
    reclaim = format_reclaim_comment("RUN-1", "wip/recovered", when="2026-07-21T00:00:00Z")
    client = _client({"MarkedBranch": _marked_issue(labels=["reclaimed"], comments=[reclaim])})
    assert _run(client.fetch_handoff_branch("1")) is None


def test_latest_marker_wins() -> None:
    older = format_reclaim_comment("RUN-1", "wip/old", when="2026-07-20T00:00:00Z")
    newer = format_reclaim_comment("RUN-1", "wip/new", when="2026-07-21T00:00:00Z")
    # _marked_issue stamps createdAt in list order, so the second is newest.
    client = _client({"MarkedBranch": _marked_issue(labels=["reclaimed"], comments=[older, newer])})
    assert _run(client.fetch_resume_branch("1")) == "wip/new"


# ---------------------------------------------------------------------------
# The HTTP helper — GraphQL errors and transport failures become boundary errors
# ---------------------------------------------------------------------------


def test_graphql_errors_become_request_error() -> None:
    client = GitHubClient(token="t", settings=_settings())
    payload = '{"errors": [{"message": "Bad credentials"}]}'
    with patch("urllib.request.urlopen") as urlopen:
        urlopen.return_value.__enter__.return_value.read.return_value = payload.encode()
        with pytest.raises(GitHubRequestError, match="Bad credentials"):
            _run(client._request("query X { a }", {}))


def test_http_error_becomes_request_error() -> None:
    client = GitHubClient(token="t", settings=_settings())
    err = urllib.error.HTTPError("u", 401, "Unauthorized", {}, None)  # type: ignore[arg-type]
    with (
        patch("urllib.request.urlopen", side_effect=err),
        pytest.raises(GitHubRequestError, match="HTTP 401"),
    ):
        _run(client._request("query X { a }", {}))


def test_non_json_body_becomes_request_error() -> None:
    client = GitHubClient(token="t", settings=_settings())
    with patch("urllib.request.urlopen") as urlopen:
        urlopen.return_value.__enter__.return_value.read.return_value = b"<html>nope"
        with pytest.raises(GitHubRequestError, match="non-JSON"):
            _run(client._request("query X { a }", {}))


def test_unreachable_api_becomes_request_error() -> None:
    client = GitHubClient(token="t", settings=_settings())
    with (
        patch("urllib.request.urlopen", side_effect=urllib.error.URLError("down")),
        pytest.raises(GitHubRequestError, match="unreachable"),
    ):
        _run(client._request("query X { a }", {}))


# ---------------------------------------------------------------------------
# Mutation "no result" branches — a mutation that returns an empty payload
# raises a boundary error rather than silently succeeding.
# ---------------------------------------------------------------------------


def test_set_status_no_item_raises() -> None:
    client = _client(
        {
            "OwnerKind": _OWNER_USER,
            "ProjectMeta": _PROJECT_META,
            "IssueItems": {
                "data": {
                    "repository": {
                        "issue": {
                            "id": "I",
                            "projectItems": {"nodes": [{"id": "IT", "project": {"id": "PVT_1"}}]},
                        }
                    }
                }
            },
            "SetStatus": {"data": {"updateProjectV2ItemFieldValue": {"projectV2Item": None}}},
        }
    )
    with pytest.raises(GitHubRequestError, match="updateProjectV2ItemFieldValue"):
        _run(client.transition_to_done("1"))


def test_add_to_board_no_item_raises() -> None:
    client = _client(
        {
            "OwnerKind": _OWNER_USER,
            "ProjectMeta": _PROJECT_META,
            "IssueItems": {
                "data": {"repository": {"issue": {"id": "I", "projectItems": {"nodes": []}}}}
            },
            "AddItem": {"data": {"addProjectV2ItemById": {"item": None}}},
        }
    )
    with pytest.raises(GitHubRequestError, match="addProjectV2ItemById"):
        _run(client.transition_to_in_progress("1"))


def test_apply_label_no_labelable_raises() -> None:
    client = _client(
        {
            "IssueAndLabel": {
                "data": {"repository": {"id": "R", "issue": {"id": "I"}, "label": {"id": "L"}}}
            },
            "AddLabel": {"data": {"addLabelsToLabelable": {"labelable": None}}},
        }
    )
    with pytest.raises(GitHubRequestError, match="addLabelsToLabelable"):
        _run(client.apply_label("1", "decision"))


def test_create_label_no_label_raises() -> None:
    client = _client(
        {
            "IssueAndLabel": {
                "data": {"repository": {"id": "R", "issue": {"id": "I"}, "label": None}}
            },
            "CreateLabel": {"data": {"createLabel": {"label": None}}},
        }
    )
    with pytest.raises(GitHubRequestError, match="createLabel"):
        _run(client.apply_label("1", "new"))


def test_post_comment_no_comment_raises() -> None:
    client = _client(
        {
            "IssueNode": {"data": {"repository": {"issue": {"id": "I"}}}},
            "AddComment": {"data": {"addComment": {"commentEdge": {"node": None}}}},
        }
    )
    with pytest.raises(GitHubRequestError, match="addComment"):
        _run(client.post_comment("1", "hi"))


def test_assign_no_assignable_raises() -> None:
    client = _client(
        {
            "ViewerAndIssue": {
                "data": {"viewer": {"id": "U"}, "repository": {"issue": {"id": "I"}}}
            },
            "AssignIssue": {"data": {"addAssigneesToAssignable": {"assignable": None}}},
        }
    )
    with pytest.raises(GitHubRequestError, match="addAssigneesToAssignable"):
        _run(client.assign_to_viewer("1"))


def test_create_issue_no_issue_raises() -> None:
    client = _client(
        {
            "RepoId": {"data": {"repository": {"id": "R"}}},
            "CreateIssue": {"data": {"createIssue": {"issue": None}}},
        }
    )
    with pytest.raises(GitHubRequestError, match="createIssue"):
        _run(client.create_issue(team_key="C", project_name=None, title="T", description="B"))


def test_assign_missing_issue_raises_not_found() -> None:
    client = _client(
        {"ViewerAndIssue": {"data": {"viewer": {"id": "U"}, "repository": {"issue": None}}}}
    )
    with pytest.raises(GitHubNotFound):
        _run(client.assign_to_viewer("1"))
