"""CAL-1155 — ``review-discipline`` Stage 1: check the ticket's *current* criteria.

From proposal ``size-criterion-process`` (accepted 2026-07-17). The reviewer's
side of the renegotiation rule: Stage 1 checks the acceptance criteria as they
stand on the ticket *now*, and flags any amendment in the review report. A
criterion renegotiated only in a commit body or PR description — never amended on
the Linear issue — is a Stage 1 FAIL even when the engineering call is right,
because the canonical record (the ticket) is then wrong.

This guard is a text-parse content check in the style of
``test_review_discipline_port_orphan`` (CAL-665): it reads the as-built guidance
and asserts the rule is present in the Stage 1 section, so a future re-edit
cannot silently drop it.

Acceptance criteria (this ticket):

* **AC-1** — Stage 1 reviews against the ticket's *current* criteria and
  surfaces any renegotiation. Proven by
  :func:`test_stage1_checks_current_criteria`.
* **AC-2** — a criterion renegotiated only in a commit body or PR description is
  a Stage 1 FAIL. Proven by
  :func:`test_commit_body_only_renegotiation_is_a_fail`.
"""

from __future__ import annotations

from pathlib import Path

# ``tests/unit/test_*.py`` → ``parents[2]`` is the repo (or worktree) root.
_REPO_ROOT = Path(__file__).resolve().parents[2]
_SKILL = _REPO_ROOT / "skills" / "review-discipline" / "SKILL.md"


def _skill_text() -> str:
    return _SKILL.read_text(encoding="utf-8")


def _stage1_section() -> str:
    """The '### Stage 1' section — up to the next '### Stage 2' heading."""
    text = _skill_text()
    start = text.find("### Stage 1")
    assert start != -1, "review-discipline must have a '### Stage 1' section"
    end = text.find("### Stage 2", start)
    assert end != -1, "review-discipline must have a '### Stage 2' heading after it"
    return text[start:end]


def test_stage1_checks_current_criteria() -> None:
    """Stage 1 reviews against the ticket's current criteria and flags amendment (AC-1)."""
    section = _stage1_section()
    lower = section.lower()
    assert "current" in lower and "criteria" in lower, (
        "Stage 1 must review against the ticket's *current* acceptance criteria "
        "(proposal size-criterion-process)"
    )
    assert "renegotiat" in lower, (
        "Stage 1 must surface any criterion renegotiation in the review report"
    )


def test_commit_body_only_renegotiation_is_a_fail() -> None:
    """A commit-body-only renegotiation is a Stage 1 FAIL (AC-2)."""
    section = _stage1_section()
    lower = section.lower()
    assert "commit body" in lower, (
        "Stage 1 must name the commit-body-only renegotiation it rejects"
    )
    # The verdict is explicit — FAIL is retained verbatim (uppercase) in the rule.
    assert "FAIL" in section, (
        "a criterion renegotiated only in a commit body / PR description must be "
        "stated as a Stage 1 FAIL, even when the engineering call is right"
    )
