"""``ci.yml`` runs on the ``dev`` integration branch, not only ``main`` (CAL-1030).

The harness merges every closed run straight to ``dev`` (the ``close`` verb's
direct push) and cuts a release PR from ``dev`` to ``main``. With CI triggering
only on ``main``, the whole suite runs **once per release**: the first hermetic
clean-clone check of many merged runs, and the first chance to catch merge skew
between concurrently-landed runs, both arrive at release time. Triggering on
``dev`` moves that signal to each merge — the ``push: dev`` run verifies the
merged state (including the close verb's direct pushes), and the ``pull_request``
run covers dev-targeted PRs.

Parsed as text (PyYAML is not a project dependency), matching
``test_ci_workflow_permissions.py`` and ``test_release_workflow.py``. That is
enough to catch the regression this targets — a trigger that drops ``dev`` —
without pretending to evaluate GitHub's event resolution.

*Source:* CAL-1030 (enable CI-on-dev; decision by Scott, interactive session
2026-07-18).
"""

from __future__ import annotations

import re
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_CI_WORKFLOW = _REPO_ROOT / ".github" / "workflows" / "ci.yml"

#: The branches CI must fire on: ``main`` (releases) and ``dev`` (every merge).
_REQUIRED_BRANCHES = ("main", "dev")


def _branches_for(trigger: str, text: str) -> str:
    """Return the ``branches: [...]`` list declared under ``<trigger>:`` in ``on:``.

    Anchors on the two-space-indented trigger key and reads the branches list on
    the next indented line, so it pins the branches of *that* trigger rather than
    matching a stray ``branches:`` elsewhere in the file.
    """
    match = re.search(rf"^  {trigger}:\n +branches:\s*(\[.*?\])", text, re.M)
    assert match, (
        f"ci.yml declares no `branches:` list under `{trigger}:` — cannot enforce "
        "the dev trigger (CAL-1030)."
    )
    return match.group(1)


def test_ci_push_triggers_on_main_and_dev() -> None:
    """``push`` fires on both ``main`` and ``dev`` (the merge-skew catcher)."""
    branches = _branches_for("push", _CI_WORKFLOW.read_text())
    for branch in _REQUIRED_BRANCHES:
        assert branch in branches, (
            f"ci.yml `push` trigger omits `{branch}` (got {branches}); the "
            "`push: dev` trigger verifies each merged state, so the suite no "
            "longer waits for the release PR (CAL-1030)."
        )


def test_ci_pull_request_triggers_on_main_and_dev() -> None:
    """``pull_request`` fires on both ``main`` and ``dev`` (dev-targeted PRs)."""
    branches = _branches_for("pull_request", _CI_WORKFLOW.read_text())
    for branch in _REQUIRED_BRANCHES:
        assert branch in branches, (
            f"ci.yml `pull_request` trigger omits `{branch}` (got {branches}) "
            "— a dev-targeted PR must run CI before it lands (CAL-1030)."
        )
