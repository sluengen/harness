"""CAL-1155 — ``code-quality`` Part C: marker *presence* is mechanized; *substance* is judged.

From proposal ``size-criterion-process`` (accepted 2026-07-17). The existing
Part C size rule (CAL-666) requires an over-limit file to carry a ``size:``
justification or a ticket. This amendment records the division of labour the
proposal draws: marker *presence* on an over-limit file is mechanically
checkable — a repo test walks the tree, counts lines, and fails any over-limit
file carrying neither — while marker *substance* (is the reason a real cohesion
argument or a rubber stamp?) stays reviewer judgment, audited by the steward on
assessment passes.

This guard is a text-parse content check in the style of
``test_code_quality_size_justification`` (CAL-666): it reads the as-built
guidance and asserts the note is present in the Part C verification gate, so a
future re-edit cannot silently drop it.

Acceptance criteria (this ticket):

* **AC-1** — Part C states that marker presence on over-limit files is
  mechanically checked (a tree-walking test). Proven by
  :func:`test_marker_presence_is_mechanized`.
* **AC-2** — Part C states that marker substance stays reviewer judgment,
  audited by the steward. Proven by :func:`test_marker_substance_is_reviewer_judgment`.
"""

from __future__ import annotations

from pathlib import Path

# ``tests/unit/test_*.py`` → ``parents[2]`` is the repo (or worktree) root.
_REPO_ROOT = Path(__file__).resolve().parents[2]
_SKILL = _REPO_ROOT / "skills" / "code-quality" / "references" / "specialized-verification.md"


def _part_c() -> str:
    """The '## Part C' verification section — to end of file."""
    text = _SKILL.read_text(encoding="utf-8")
    start = text.find("## Part C")
    assert start != -1, "code-quality must have a '## Part C' verification section"
    return text[start:]


def test_marker_presence_is_mechanized() -> None:
    """Part C states marker presence is mechanically checked by a tree-walking test (AC-1)."""
    part_c = _part_c()
    lower = part_c.lower()
    assert "presence" in lower, (
        "Part C must distinguish marker *presence* (proposal size-criterion-process)"
    )
    # The mechanism is a test that walks the source tree.
    assert "walk" in lower, (
        "Part C must state that a repo test walks the tree to check marker presence"
    )
    assert "mechaniz" in lower or "mechanical" in lower, (
        "Part C must state that presence-checking is mechanized (gate-time), not "
        "left to the reviewer to remember"
    )


def test_marker_substance_is_reviewer_judgment() -> None:
    """Part C states marker substance stays reviewer judgment, steward-audited (AC-2)."""
    part_c = _part_c()
    lower = part_c.lower()
    assert "substance" in lower, (
        "Part C must name marker *substance* as the part a test cannot score"
    )
    assert "steward" in lower, (
        "Part C must state the steward audits marker substance on assessment passes"
    )
