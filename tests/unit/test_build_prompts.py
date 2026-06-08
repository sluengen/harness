"""Tests for build-workflow prompt templates: implement-ticket.j2 and review-ticket.j2.

These templates are used by workflows/build.yaml and are responsible for
producing prompts that are project-agnostic — they must inject the target
project's CLAUDE.md conventions and verify command rather than hard-coding
harness-specific paths.

Tested behaviours:
* implement-ticket.j2 includes worktree_path, target_claude_md, verify_command.
* implement-ticket.j2 has no harness-specific paths.
* review-ticket.j2 includes target_claude_md and verify_command.
* review-ticket.j2 has no harness-specific paths.
* Both templates raise UndefinedError when the new required vars are absent.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from jinja2 import Environment, FileSystemLoader, StrictUndefined, UndefinedError

PROMPTS_DIR = Path(__file__).resolve().parents[2] / "prompts"


def _env() -> Environment:
    """Jinja2 environment mirroring the runtime."""
    return Environment(
        loader=FileSystemLoader(PROMPTS_DIR),
        undefined=StrictUndefined,
        keep_trailing_newline=True,
        autoescape=False,
    )


def _implement_state(
    *,
    issues: list[str] | None = None,
    target_claude_md: str = "## Conventions\nUse TDD.",
    worktree_path: str = "/tmp/wt",
) -> SimpleNamespace:
    return SimpleNamespace(
        ticket_title="Fix the bug",
        ticket_description="The bug is in auth.py line 42.",
        issues=issues or [],
        target_claude_md=target_claude_md,
        worktree_path=worktree_path,
    )


def _implement_inputs(verify_command: str = "bash scripts/verify.sh") -> dict[str, str]:
    return {"verify_command": verify_command, "linear_id": "HAR-1"}


def _review_state(
    *,
    target_claude_md: str = "## Conventions\nUse TDD.",
    verify_output: str = "All checks passed.",
    diff: str = "",
) -> SimpleNamespace:
    return SimpleNamespace(
        ticket_title="Fix the bug",
        ticket_description="The bug is in auth.py line 42.",
        issues=[],
        target_claude_md=target_claude_md,
        verify_output=verify_output,
        diff=diff,
    )


def _review_inputs(verify_command: str = "bash scripts/verify.sh") -> dict[str, str]:
    return {"verify_command": verify_command, "linear_id": "HAR-1"}


# ---------------------------------------------------------------------------
# implement-ticket.j2 — rendering with required vars
# ---------------------------------------------------------------------------


def test_implement_ticket_renders_without_error() -> None:
    env = _env()
    rendered = env.get_template("implement-ticket.j2").render(
        state=_implement_state(), inputs=_implement_inputs()
    )
    assert rendered.strip(), "implement-ticket.j2 rendered empty"


def test_implement_ticket_includes_worktree_path() -> None:
    """The working-directory instruction must include the actual worktree path."""
    env = _env()
    rendered = env.get_template("implement-ticket.j2").render(
        state=_implement_state(worktree_path="/repo/worktrees/my-wt"),
        inputs=_implement_inputs(),
    )
    assert "/repo/worktrees/my-wt" in rendered, (
        "implement-ticket.j2 must include worktree_path in the working-directory instruction"
    )


def test_implement_ticket_working_directory_near_top() -> None:
    """The working-directory instruction should appear before the ticket body."""
    env = _env()
    rendered = env.get_template("implement-ticket.j2").render(
        state=_implement_state(worktree_path="/the/worktree"),
        inputs=_implement_inputs(),
    )
    wd_pos = rendered.find("/the/worktree")
    ticket_pos = rendered.find("Fix the bug")
    assert wd_pos != -1, "worktree_path not in rendered output"
    assert ticket_pos != -1, "ticket_title not in rendered output"
    assert wd_pos < ticket_pos, (
        "working-directory instruction must appear before the ticket body"
    )


def test_implement_ticket_includes_target_claude_md() -> None:
    """Project CLAUDE.md content must appear verbatim in the rendered prompt."""
    env = _env()
    unique_marker = "## SlateProject Conventions — unique-marker-xyz"
    rendered = env.get_template("implement-ticket.j2").render(
        state=_implement_state(target_claude_md=unique_marker),
        inputs=_implement_inputs(),
    )
    assert unique_marker in rendered, (
        "implement-ticket.j2 must inject target_claude_md content"
    )


def test_implement_ticket_instructs_lint_only() -> None:
    """Implement prompt must direct agent to run lint, not the full verify command.

    The harness runs the full test suite as a separate automated gate; the
    agent should only run a fast lint check before submitting so it does not
    attempt to spin up databases or Docker.
    """
    env = _env()
    rendered = env.get_template("implement-ticket.j2").render(
        state=_implement_state(),
        inputs=_implement_inputs(verify_command="make check"),
    )
    assert "ruff check" in rendered, (
        "implement-ticket.j2 must instruct the agent to run ruff check ."
    )
    assert "make check" not in rendered, (
        "implement-ticket.j2 must not pass verify_command to the agent — "
        "full verification is the harness gate's responsibility"
    )


def test_implement_ticket_no_harness_specific_paths() -> None:
    """No harness-specific skill paths or tool invocations must appear."""
    env = _env()
    rendered = env.get_template("implement-ticket.j2").render(
        state=_implement_state(),
        inputs=_implement_inputs(),
    )
    assert "skills/test-driven-development.md" not in rendered, (
        "implement-ticket.j2 must not reference harness-internal skill paths"
    )
    assert "uv run mypy harness" not in rendered, (
        "implement-ticket.j2 must not hard-code harness-specific verify commands"
    )


def test_implement_ticket_missing_target_claude_md_raises() -> None:
    """UndefinedError when target_claude_md is absent from state."""
    env = _env()
    state_without = SimpleNamespace(
        ticket_title="T",
        ticket_description="D",
        issues=[],
        worktree_path="/tmp",
        # target_claude_md intentionally omitted
    )
    with pytest.raises(UndefinedError):
        env.get_template("implement-ticket.j2").render(
            state=state_without, inputs=_implement_inputs()
        )


def test_implement_ticket_renders_without_verify_command() -> None:
    """Prompt must render cleanly even when verify_command is absent from inputs.

    The agent no longer receives the verify_command — lint-only is hardcoded.
    """
    env = _env()
    inputs_without = {"linear_id": "HAR-1"}  # no verify_command
    rendered = env.get_template("implement-ticket.j2").render(
        state=_implement_state(), inputs=inputs_without
    )
    assert "ruff check" in rendered


# ---------------------------------------------------------------------------
# implement-ticket.j2 — retry path (state.issues populated)
# ---------------------------------------------------------------------------


def test_implement_ticket_retry_section_visible_when_issues_present() -> None:
    """When state.issues is non-empty the open-findings block must appear."""
    env = _env()
    rendered = env.get_template("implement-ticket.j2").render(
        state=_implement_state(issues=["Missing test for edge case X"]),
        inputs=_implement_inputs(),
    )
    assert "Open findings" in rendered
    assert "Missing test for edge case X" in rendered


def test_implement_ticket_retry_section_absent_when_no_issues() -> None:
    """When state.issues is empty the open-findings block must not appear."""
    env = _env()
    rendered = env.get_template("implement-ticket.j2").render(
        state=_implement_state(issues=[]),
        inputs=_implement_inputs(),
    )
    assert "Open findings" not in rendered


def test_implement_ticket_retry_framing_targets_root_cause() -> None:
    """The retry framing must steer the agent to the underlying cause, not a
    literal fix of only the cited example — guards the fix for the
    'agent only actions exactly what is written' failure mode."""
    env = _env()
    rendered = env.get_template("implement-ticket.j2").render(
        state=_implement_state(issues=["auth.py:42 — example finding"]),
        inputs=_implement_inputs(),
    )
    lowered = rendered.lower()
    assert "root cause" in lowered, (
        "retry framing must tell the implementer to fix the root cause, "
        "not just the literal text of the finding"
    )
    assert "class of problem" in lowered, (
        "retry framing must tell the implementer to fix the whole class of "
        "problem a finding points to, not only the cited instance"
    )


# ---------------------------------------------------------------------------
# review-ticket.j2 — rendering with required vars
# ---------------------------------------------------------------------------


def test_review_ticket_renders_without_error() -> None:
    env = _env()
    rendered = env.get_template("review-ticket.j2").render(
        state=_review_state(), inputs=_review_inputs()
    )
    assert rendered.strip(), "review-ticket.j2 rendered empty"


def test_review_ticket_includes_target_claude_md() -> None:
    """Project CLAUDE.md content must appear verbatim in the review prompt."""
    env = _env()
    unique_marker = "## SlateProject Conventions — review-unique-marker-abc"
    rendered = env.get_template("review-ticket.j2").render(
        state=_review_state(target_claude_md=unique_marker),
        inputs=_review_inputs(),
    )
    assert unique_marker in rendered, (
        "review-ticket.j2 must inject target_claude_md content"
    )


def test_review_ticket_includes_verify_command() -> None:
    """The verify command must appear verbatim in the review prompt."""
    env = _env()
    rendered = env.get_template("review-ticket.j2").render(
        state=_review_state(),
        inputs=_review_inputs(verify_command="npm test"),
    )
    assert "npm test" in rendered, (
        "review-ticket.j2 must include the verify_command from inputs"
    )


def test_review_ticket_includes_diff_when_present() -> None:
    """When state.diff is non-empty the diff must be embedded in the prompt.

    The reviewer is read-only (Read/Grep/Glob, no Bash) and cannot run
    git itself, so the harness captures the diff into state and the prompt
    must surface it for review."""
    env = _env()
    unique_diff = "diff --git a/foo.py b/foo.py\n+unique-diff-marker-123"
    rendered = env.get_template("review-ticket.j2").render(
        state=_review_state(diff=unique_diff),
        inputs=_review_inputs(),
    )
    assert "unique-diff-marker-123" in rendered, (
        "review-ticket.j2 must embed state.diff so the read-only reviewer "
        "can see what changed"
    )
    assert "Changes under review" in rendered


def test_review_ticket_omits_diff_section_when_empty() -> None:
    """When state.diff is empty the diff section must not render (no empty fence)."""
    env = _env()
    rendered = env.get_template("review-ticket.j2").render(
        state=_review_state(diff=""),
        inputs=_review_inputs(),
    )
    assert "Changes under review" not in rendered


def test_review_ticket_findings_guidance_demands_self_contained_findings() -> None:
    """The FAIL guidance must tell the reviewer that findings are read by a
    fresh agent with no memory, so each must be self-contained — guards the
    fix for the 'terse one-line findings lose the reviewer's reasoning' mode."""
    env = _env()
    rendered = env.get_template("review-ticket.j2").render(
        state=_review_state(),
        inputs=_review_inputs(),
    )
    lowered = rendered.lower()
    assert "no memory" in lowered, (
        "review findings guidance must warn that the implementer is a fresh "
        "agent with no memory of the review"
    )
    assert "self-contained" in lowered, (
        "review findings guidance must require self-contained, actionable findings"
    )


def test_review_ticket_no_harness_specific_paths() -> None:
    """No harness-specific tool invocations must appear."""
    env = _env()
    rendered = env.get_template("review-ticket.j2").render(
        state=_review_state(), inputs=_review_inputs()
    )
    assert "uv run mypy harness" not in rendered, (
        "review-ticket.j2 must not hard-code harness-specific verify commands"
    )


def test_review_ticket_missing_target_claude_md_raises() -> None:
    """UndefinedError when target_claude_md is absent from state."""
    env = _env()
    state_without = SimpleNamespace(
        ticket_title="T",
        ticket_description="D",
        issues=[],
        # target_claude_md intentionally omitted
    )
    with pytest.raises(UndefinedError):
        env.get_template("review-ticket.j2").render(
            state=state_without, inputs=_review_inputs()
        )


def test_review_ticket_missing_verify_command_raises() -> None:
    """UndefinedError when verify_command is absent from inputs."""
    env = _env()
    inputs_without = {"linear_id": "HAR-1"}  # no verify_command
    with pytest.raises(UndefinedError):
        env.get_template("review-ticket.j2").render(
            state=_review_state(), inputs=inputs_without
        )
