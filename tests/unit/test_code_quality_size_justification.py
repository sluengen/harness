"""CAL-666 — ``code-quality`` enforces the 500-line hard limit or a justification.

From the 2026-06-13 code assessment (CODE-INSIGHT-002). CODE-002 and CODE-003
(plus two cohesive files declined) showed the 500-line hard limit is treated as
advisory: none of the over-limit files carried the justifying comment
``code-quality`` already calls for, so the steward re-finds the same files each
assessment cycle.

The accepted fix (CAL-666 decision, 2026-06-14) adds to the ``code-quality``
verification gate: a file over the hard limit must carry a one-line
``# size: <reason>`` justification or a tracking ticket, else the reviewer
rejects it.

This guard binds that rule into the skill text so a future re-edit cannot
silently drop it: it is a text-parse content guard in the style of
``test_review_discipline_port_orphan`` (CAL-665),
``test_distributed_skill_cites`` (CAL-654) and ``test_retired_spec_cites``
(CAL-633) — it reads the as-built guidance and asserts the rule is present. It
does not itself measure any file's length; converting silent drift into an
auditable choice on the source tree is the job of the walker test
(``test_source_file_size_justification.py``), which enforces the ``# size:``
marker across ``harness/**``.

Acceptance criteria (this ticket):

* **AC-1** — ``code-quality`` requires a file over the hard limit to carry a
  ``# size: <reason>`` justification or a tracking ticket, with the reviewer
  rejecting one that has neither. Proven by
  :func:`test_code_quality_has_size_justification_rule`.
* **AC-2** — the rule lives in the Part C verification gate. Proven by
  :func:`test_size_rule_is_in_verification_gate`.
"""

from __future__ import annotations

from pathlib import Path

# ``tests/unit/test_*.py`` → ``parents[2]`` is the repo (or worktree) root.
_REPO_ROOT = Path(__file__).resolve().parents[2]
_SKILL = _REPO_ROOT / "skills" / "code-quality" / "references" / "specialized-verification.md"


def _skill_text() -> str:
    return _SKILL.read_text(encoding="utf-8")


def test_code_quality_has_size_justification_rule() -> None:
    """The skill states the over-limit justification rule (AC-1)."""
    text = _skill_text()
    lower = text.lower()
    # The rule names the concrete justification form...
    assert "# size:" in text, (
        "code-quality must name the concrete `# size: <reason>` justification "
        "form for an over-limit file (CAL-666 / CODE-INSIGHT-002)"
    )
    # ...accepts a tracking ticket as the alternative...
    assert "ticket" in lower, (
        "the size rule must accept a tracking ticket as the alternative to a "
        "`# size:` comment"
    )
    # ...and states the reviewer rejects an over-limit file with neither.
    assert "reject" in lower, (
        "the size rule must state the reviewer rejects an over-limit file that "
        "has neither a `# size:` justification nor a tracking ticket"
    )


def test_size_rule_is_in_verification_gate() -> None:
    """The rule sits in the Part C verification gate (AC-2)."""
    text = _skill_text()
    part_c_start = text.find("## Part C")
    assert part_c_start != -1, "code-quality must have a Part C verification section"
    part_c = text[part_c_start:]
    assert "# size:" in part_c, (
        "the over-limit justification rule must live in the Part C verification "
        "gate, where the decision (CAL-666, 2026-06-14) routed it"
    )
