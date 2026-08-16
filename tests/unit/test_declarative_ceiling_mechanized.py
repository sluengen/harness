"""#232 — the declarative line-ceiling exemption is configured where the limit is
enforced.

``code-quality`` Part B grants declarative files (schemas, type definitions,
token maps) "a higher ceiling" but named no number and no mechanism, while the
same skill (Part C) directs repos to mechanize the hard limit through the
linter's ``max-lines`` where one exists. A repo that follows both instructions
can end up with a flat cap in the linter config, a contract test pinning it, and
a declarative exemption that exists only in this skill's prose — no tool reads
prose, so the exemption surfaces as a surprise gate failure on a commit that has
nothing to do with file size.

**Converted under #459** (ADR 0016, and ``code-quality`` Part C → *A guard over
prose owns structure and negative space, never meaning*). Four functions — six
term pins over one paragraph, plus a Part B/Part C offset assertion — became the
single tripwire below. The offset assertion folds into the anchor: the paragraph
is now sliced *from inside* ``## Part B — Structure``, so a subsection relocated
to Part C stops resolving and the placement claim needs no test of its own
(``craft.md`` → *The text unit is part of the predicate*).

**What this module now asserts.** One tripwire, one rule-home:

* **Anchor** — the declarative-ceiling paragraph of ``### Size``, resolved from
  inside ``## Part B``. The paragraph, not the subsection: ``### Size`` opens
  with the soft/hard limits table, which supplies size vocabulary the exemption
  rule does not own.
* **Term set** — ``overrides`` (the linter mechanism), ``same change`` (when it
  lands) and ``1.5x`` (the default the repo is not left to invent).
* **Polarity** — the negation bound to what it governs: a prose-only exemption
  is ***not** enforceable*. A bare ``not`` over the paragraph would be
  decoration; bound to ``enforceable`` it inverts with the rule (``craft.md`` →
  *Mutate the rule into its opposite, not only out of existence*).

**What it does not prove.** That any repo's linter actually carries the override,
or that 1.5x is the right multiple.
"""

from __future__ import annotations

import re
from pathlib import Path

from tests.unit.test_assurance_filing_rubric import _section

# ``tests/unit/test_*.py`` → ``parents[2]`` is the repo (or worktree) root.
_REPO_ROOT = Path(__file__).resolve().parents[2]
_CODE_QUALITY = _REPO_ROOT / "skills" / "code-quality" / "SKILL.md"

_PART_B = "## Part B — Structure"
_HEADING = "### Size"

#: The words the rule cannot be stated without.
_TERMS = (
    r"\boverrides\b",
    r"\bsame change\b",
    r"\b1\.5\s?x\b",
)

#: The negation **bound to the enforceability it denies**.
_NOT_ENFORCEABLE = re.compile(
    r"\b(?:not|never)\b(?:\W+\w+){0,2}?\W+enforceable\b", re.IGNORECASE
)


def _declarative_ceiling_paragraph() -> str:
    """The declarative-ceiling grant inside ``### Size``, inside ``## Part B``.

    ``_section`` is imported rather than re-spelled, and the two calls are
    nested so Part B membership lives in the anchor instead of a second test.
    """
    text = _CODE_QUALITY.read_text(encoding="utf-8")
    size = _section(_section(text, _PART_B), _HEADING)
    paragraphs = [block.strip() for block in size.split("\n\n") if block.strip()]
    hits = [
        p for p in paragraphs if re.search(r"\bdeclarative files\b", p, re.IGNORECASE)
    ]
    assert hits, (
        f"{_HEADING!r} in Part B no longer grants declarative files a higher "
        "ceiling — the paragraph this guard covers is gone (#232)."
    )
    assert len(hits) == 1, (
        f"{_HEADING!r} states the declarative-files grant in {len(hits)} paragraphs; "
        "this guard's window can no longer tell which one it is pinning."
    )
    return hits[0]


def test_the_declarative_ceiling_exemption_is_mechanized() -> None:
    """One tripwire: the grant is in Part B, names its mechanism, keeps polarity."""
    para = _declarative_ceiling_paragraph()

    missing = [t for t in _TERMS if not re.search(t, para, re.IGNORECASE)]
    assert not missing, (
        "the declarative-ceiling grant no longer carries the terms the rule cannot be "
        f"stated without; missing {missing}. The exemption is declared as a linter "
        "`overrides` entry in the same change that mechanizes the limit, and the "
        f"default ceiling is 1.5x the hard limit (#232). Paragraph read:\n{para}"
    )

    assert _NOT_ENFORCEABLE.search(para), (
        "the grant has lost its polarity: an exemption living only in this skill's "
        "prose must be stated as *not enforceable*. Without the negation bound to "
        "`enforceable`, a paragraph naming `overrides`, `same change` and `1.5x` "
        "while treating the prose exemption as sufficient carries every term above "
        f"and passes (#232). Paragraph read:\n{para}"
    )
