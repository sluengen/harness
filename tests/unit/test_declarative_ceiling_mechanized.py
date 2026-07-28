"""#232 — the declarative line-ceiling exemption must be configured where the
limit is enforced.

``code-quality`` Part B grants declarative files (schemas, type definitions,
token maps) "a higher ceiling" but named no number and no mechanism, while the
same skill (Part C) directs repos to mechanize the hard limit through the
linter's ``max-lines`` where one exists. A repo that follows both instructions
can end up with a flat cap in the linter config, a contract test pinning it,
and a declarative exemption that exists only in this skill's prose — no tool
reads prose, so the exemption surfaces as a surprise gate failure on a commit
that has nothing to do with file size.

This guard is a text-parse content check in the style of
``test_fetch_untrusted_urls_checklist`` (CAL-829) and
``test_code_quality_linter_first_size_enforcement`` (#185): it reads the
as-built guidance and asserts the requirement is present, so a later re-edit
cannot silently drop it.

Acceptance criteria (this ticket):

* **AC-1** — Part B's declarative-ceiling line requires the exemption be
  declared as a linter ``overrides`` entry *in the same change* that
  mechanizes the file-size limit. Proven by
  :func:`test_exemption_must_be_configured_as_an_overrides_entry`.
* **AC-2** — the line states a prose-only exemption is not enforceable and
  will surface as a gate failure unrelated to the file-size change. Proven by
  :func:`test_prose_only_exemption_is_not_enforceable`.
* **AC-3** — the line names a default ceiling (1.5x the hard limit) so a repo
  is not left to invent its own number. Proven by
  :func:`test_default_ceiling_is_named`.
* **AC-4** — the requirement lives in Part B — Structure, alongside the
  declarative-ceiling grant it extends, not in Part C. Proven by
  :func:`test_requirement_is_in_part_b`.
"""

from __future__ import annotations

import re
from pathlib import Path

# ``tests/unit/test_*.py`` → ``parents[2]`` is the repo (or worktree) root.
_REPO_ROOT = Path(__file__).resolve().parents[2]
_CODE_QUALITY = _REPO_ROOT / "skills" / "code-quality" / "SKILL.md"


def _declarative_ceiling_para() -> str:
    """The paragraph following the '### Size' table — the declarative-ceiling grant."""
    text = _CODE_QUALITY.read_text(encoding="utf-8")
    m = re.search(r"^### Size\s*$", text, re.MULTILINE)
    assert m, "code-quality Part B must carry a '### Size' subsection"
    rest = text[m.end() :]
    end = re.search(r"^#{2,3} ", rest, re.MULTILINE)
    section = rest[: end.start()] if end else rest
    idx = section.lower().index("declarative files")
    return section[idx:]


def test_exemption_must_be_configured_as_an_overrides_entry() -> None:
    """The exemption is declared as a linter overrides entry, in the same change (AC-1)."""
    para = _declarative_ceiling_para().lower()
    assert "overrides" in para, (
        "the declarative-ceiling grant must require the exemption be declared as "
        "an `overrides` entry in the linter config (#232 AC-1)."
    )
    assert "same change" in para, (
        "the declarative-ceiling grant must require the overrides entry land in "
        "the same change that mechanizes the file-size limit (#232 AC-1)."
    )


def test_prose_only_exemption_is_not_enforceable() -> None:
    """A prose-only exemption is called out as unenforceable and a gate-failure risk (AC-2)."""
    para = _declarative_ceiling_para().lower()
    assert "not enforceable" in para, (
        "the declarative-ceiling grant must state that an exemption living only "
        "in this skill's prose is not enforceable (#232 AC-2)."
    )
    assert "gate failure" in para, (
        "the declarative-ceiling grant must warn that an unmechanized exemption "
        "surfaces as a gate failure on an unrelated commit (#232 AC-2)."
    )


def test_default_ceiling_is_named() -> None:
    """A default declarative ceiling (1.5x the hard limit) is named (AC-3)."""
    para = _declarative_ceiling_para().lower()
    assert "1.5x" in para or "1.5 x" in para, (
        "the declarative-ceiling grant must name a default ceiling (1.5x the "
        "hard limit) so an adopting repo does not invent its own number (#232 AC-3)."
    )
    assert "sets its own" in para or "set its own" in para, (
        "the default must be explicit that a repo may override it with its own "
        "number (#232 AC-3)."
    )


def test_requirement_is_in_part_b() -> None:
    """The requirement lives in Part B, beside the grant it extends, not Part C (AC-4)."""
    text = _CODE_QUALITY.read_text(encoding="utf-8")
    part_b = text.index("## Part B")
    part_c = text.index("## Part C", part_b)
    heading = text.index("### Size", part_b)
    assert part_b < heading < part_c, (
        "the declarative-ceiling exemption requirement must sit inside Part B — "
        "Structure, alongside the '### Size' table it extends (#232 AC-4)."
    )
