"""Task work must not accumulate disposable host resources.

The operator reported an agent-session cleanup that recovered roughly 100 GB of
leftover Docker images and volumes on 2026-08-27. The workflow already required
isolated worktrees, but its cleanup contract did not make the corresponding
resource lifecycle explicit: task branches remained after merge, and temporary
container and simulator artifacts were only implied by one Compose example.

This is a structural guard over the canonical workflow sources. It protects the
required teardown surface, not whether the prose explains every command.
"""

from __future__ import annotations

from tests._gitutil import indexed_text


def test_isolation_guidance_names_task_teardown_and_its_resource_classes() -> None:
    """A completed task has one canonical cleanup procedure for every worktree."""
    guidance = indexed_text("skills/worktree-isolation/SKILL.md")

    for required in (
        "## Cleanup",
        "git worktree remove",
        "git worktree prune",
        "git branch -d",
        "Docker",
        "iOS simulator",
        "only resources it owns",
    ):
        assert required in guidance, f"cleanup guidance must name {required!r}"


def test_build_delegates_successful_task_cleanup_to_the_isolation_contract() -> None:
    """The shipping path cannot omit the cleanup contract after it pushes."""
    build = indexed_text("commands/build.md")

    assert "worktree-isolation" in build
    assert "cleanup procedure" in build
