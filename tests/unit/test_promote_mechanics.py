"""Promotion mechanics library — conflict classification + branch naming (CAL-1115).

The git-touching halves of :mod:`harness.promotion` (fetch, worktree create,
merge attempt) are exercised end-to-end through the CLI in
``test_cli_promote_start.py`` against a real throw-away repo. This module unit-tests
the two pure, deterministic pieces that carry a *measurable* rule:

* :func:`classify_conflicts` — the ADR 0003 repair-authority policy: a bounded,
  low-semantic conflict is ``agent_may_fix``; anything touching a sensitive file
  kind, or spanning more than :data:`MAX_REPAIRABLE_CONFLICT_FILES` files, is
  ``needs_ticket``. The file-count bound is a quantity, so it gets a measuring
  test (``code-quality`` Part C).
* :func:`promotion_branch_name` — the deterministic ``promote/<date>-<from>-to-<to>``
  name from the design record.
"""

from __future__ import annotations

from datetime import date

import pytest

from harness import promotion

# --- classify_conflicts: the file-count bound (measuring test) ----------------


def test_small_plain_conflict_is_agent_may_fix() -> None:
    """A handful of ordinary source/doc conflicts is a bounded, in-policy repair."""
    files = ["README.md", "docs/guide.md", "src/util.py"]
    assert promotion.classify_conflicts(files) == "agent_may_fix"


def test_conflict_at_the_file_threshold_is_still_agent_may_fix() -> None:
    """Exactly :data:`MAX_REPAIRABLE_CONFLICT_FILES` plain files stays repairable —
    the bound is inclusive."""
    files = [f"src/mod_{i}.py" for i in range(promotion.MAX_REPAIRABLE_CONFLICT_FILES)]
    assert len(files) == promotion.MAX_REPAIRABLE_CONFLICT_FILES
    assert promotion.classify_conflicts(files) == "agent_may_fix"


def test_conflict_over_the_file_threshold_needs_a_ticket() -> None:
    """One file past the bound tips a merge out of local repair authority (ADR 0003
    'conflicts over the file threshold')."""
    files = [f"src/mod_{i}.py" for i in range(promotion.MAX_REPAIRABLE_CONFLICT_FILES + 1)]
    assert len(files) > promotion.MAX_REPAIRABLE_CONFLICT_FILES
    assert promotion.classify_conflicts(files) == "needs_ticket"


@pytest.mark.parametrize(
    "path",
    [
        "db/migrations/0007_add_column.py",
        "app/auth/session.py",
        "billing/payment_gateway.rb",
        "infra/deploy.sh",
        "scripts/release.py",
        "app/security/policy.py",
        "package-lock.json",
        "uv.lock",
        "Cargo.lock",
    ],
)
def test_sensitive_file_kinds_force_a_ticket(path: str) -> None:
    """A conflict touching a migration, an auth/payment/security/release/deploy
    script, or a dependency lockfile escalates regardless of how few files —
    over-escalation is safe for a release gate (ADR 0003 repair authority)."""
    assert promotion.classify_conflicts([path]) == "needs_ticket"


def test_no_conflicts_is_agent_may_fix() -> None:
    """The empty set is trivially in-policy (the classifier is only called on a
    real conflict, but it must not crash on the degenerate input)."""
    assert promotion.classify_conflicts([]) == "agent_may_fix"


# --- promotion_branch_name ----------------------------------------------------


def test_branch_name_follows_the_design_shape() -> None:
    """``promote/<date>-<from>-to-<to>`` — the name recorded in ADR 0003's design."""
    name = promotion.promotion_branch_name("dev", "staging", day=date(2026, 7, 17))
    assert name == "promote/2026-07-17-dev-to-staging"


def test_branch_name_slugs_slashes_in_branch_components() -> None:
    """A branch with a ``/`` in its name yields a valid single-segment-per-side
    promotion branch (no accidental nested ref)."""
    name = promotion.promotion_branch_name("release/1.x", "main", day=date(2026, 7, 17))
    assert name == "promote/2026-07-17-release-1.x-to-main"
