"""``harness.promotion_escalation`` — deterministic escalation content (CAL-1118).

The content half of ``harness promote escalate`` — the analogue of
``promotion_pr.build_pr_body`` for the terminal escalate path. These lock that the
rendered Linear ticket carries the evidence the proposal requires (promotion id,
endpoints, branch/worktree, conflict files, gate summary, next action) and that
every section degrades to an explicit ``_none_`` rather than vanishing.
"""

from __future__ import annotations

from harness.promotion_escalation import (
    build_escalation_body,
    build_escalation_title,
    escalation_next_action,
)
from harness.state.promotions import Promotion


def _promo(**overrides: object) -> Promotion:
    base: dict[str, object] = {
        "promotion_id": "p-esc-1",
        "repo": "/repo",
        "from_branch": "dev",
        "to_branch": "staging",
        "status": "needs_ticket",
        "created_at": "2026-07-17T00:00:00+00:00",
        "updated_at": "2026-07-17T00:00:00+00:00",
        "promotion_branch": "promote/2026-07-17-dev-to-staging",
        "worktree_path": "/repo/.worktrees/harness/p-esc-1",
        "evidence": "FAILED tests/test_x.py::test_y",
    }
    base.update(overrides)
    return Promotion(**base)  # type: ignore[arg-type]


def test_title_names_status_and_endpoints() -> None:
    title = build_escalation_title(_promo())
    assert "dev" in title and "staging" in title
    assert "needs_ticket" in title


def test_body_carries_the_full_evidence() -> None:
    body = build_escalation_body(
        _promo(), conflict_files=("app/models.py", "app/auth.py")
    )
    # Promotion identity + endpoints.
    assert "p-esc-1" in body
    assert "needs_ticket" in body
    assert "dev" in body and "staging" in body
    # Branch + worktree to inspect.
    assert "promote/2026-07-17-dev-to-staging" in body
    assert "/repo/.worktrees/harness/p-esc-1" in body
    # Conflict files.
    assert "app/models.py" in body and "app/auth.py" in body
    # Gate summary evidence.
    assert "FAILED tests/test_x.py::test_y" in body
    # The next human action for this status.
    assert escalation_next_action("needs_ticket") in body


def test_body_degrades_empty_sections_to_none() -> None:
    """No conflict files and no gate evidence render as explicit ``_none_`` markers,
    so the body shape is stable regardless of how sparse the promotion is."""
    body = build_escalation_body(
        _promo(evidence=None, promotion_branch=None, worktree_path=None),
        conflict_files=(),
    )
    assert "_none_" in body


def test_next_action_is_status_specific() -> None:
    assert escalation_next_action("needs_ticket") != escalation_next_action("blocked")
    # An unknown status still yields a non-empty, generic instruction.
    assert escalation_next_action("something_else").strip()
