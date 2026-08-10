"""#399 — ``code-quality`` Part C: how a tripped size limit may be answered.

Part C's *A file over the hard limit is an auditable choice, not silent drift*
establishes the enforcement ordering (linter → walker → steward) and the
``size:`` marker contract. Every one of its rules governs a file that **is**
over the limit; none of them reaches a file shaved to just under one.

That gap has a predictable exploit, because a line-count gate is cheapest to
satisfy by removing declarations: merging two named units is always cheaper
than separating three concerns. In a consuming repo a 459-line route component
tripped a mechanized crowded-threshold guard, and the next commit brought it to
exactly 450 by deleting a named component and inlining its body into its
caller — gate green, three mixed concerns unchanged, one fewer named unit than
before. The rule traded away to satisfy Part C's was Part B's *Compose, don't
inline*, in the same skill, and nothing said that was the wrong move.

No test can score the judgment — a legitimate simplification and a threshold
shave are indistinguishable to a line counter, which is why Part C already
separates mechanized presence from judged substance. So the rule is stated and
what is mechanized is that the statement stays here. This guard is a
text-parse content check in the style of
``test_code_quality_linter_first_size_enforcement`` (#185) and
``test_code_quality_marker_presence_mechanized`` (CAL-1155), with two
properties that keep it from being a substring rubber stamp: it **derives** its
subject section from the heading rather than scanning the whole skill, and it
requires the rule and its prohibition to live in **one paragraph**, so a
half-dropped rewrite fails.

Acceptance criteria (this ticket):

* **AC-1** — The size subsection states that a tripped limit is answered in
  exactly two ways: split the file by concern, or record the exemption on it.
  Proven by :func:`test_a_tripped_limit_has_exactly_two_legitimate_answers`.
* **AC-2** — The same paragraph states that reducing the line count in place is
  not one of them, naming the inlining of a named unit back into its caller,
  and ties it to Part B's *Compose, don't inline*. Proven by
  :func:`test_reducing_the_count_in_place_is_not_one_of_them`.
* **AC-3** — The subsection gives the reviewer the instrument: read the diff
  that brought the file under the limit, not just the new count, and treat a
  green gate bought by merging named units as a finding. Proven by
  :func:`test_the_reviewer_reads_the_diff_that_brought_the_file_under`.
"""

from __future__ import annotations

import re
from pathlib import Path

# ``tests/unit/test_*.py`` → ``parents[2]`` is the repo (or worktree) root.
_REPO_ROOT = Path(__file__).resolve().parents[2]
_SKILL = _REPO_ROOT / "skills" / "code-quality" / "SKILL.md"

_HEADING = "### A file over the hard limit is an auditable choice, not silent drift"

# Part B's composition rule, cited verbatim so a rename there breaks this guard
# rather than leaving it pointing at a heading that no longer exists.
_PART_B_RULE = "### Compose, don't inline"


def _size_section() -> str:
    """The Part C size subsection — its heading to the next ``###``."""
    text = _SKILL.read_text(encoding="utf-8")
    start = text.find(_HEADING)
    assert start != -1, (
        f"code-quality must carry the size subsection {_HEADING!r}; the size-limit "
        "response rule (#399) has no home without it"
    )
    rest = text[start + len(_HEADING) :]
    end = rest.find("\n### ")
    section = rest if end == -1 else rest[:end]
    assert section.strip(), "the size subsection must not be empty"
    return section


def _paragraphs() -> list[str]:
    """The subsection's paragraphs, blank-line separated."""
    paragraphs = [p.strip() for p in _size_section().split("\n\n") if p.strip()]
    # Floor: the subsection carried three paragraphs (marker contract,
    # presence-vs-substance, linter-first) before this rule was added, so a
    # split that returns fewer than that has parsed the wrong thing.
    assert len(paragraphs) >= 3, (
        f"expected the size subsection to split into its paragraphs, got "
        f"{len(paragraphs)}"
    )
    return paragraphs


def _answer_paragraph() -> str:
    """The one paragraph stating how a tripped limit may be answered."""
    candidates = [p for p in _paragraphs() if "split" in p.lower()]
    assert candidates, (
        "the size subsection must carry a paragraph naming *splitting the file* as "
        "a legitimate answer to a tripped limit (#399) — none of its paragraphs "
        "mentions splitting at all"
    )
    assert len(candidates) == 1, (
        "the answer rule must live in one paragraph, not be spread across "
        f"{len(candidates)}; a half-dropped rewrite is what this guard exists to "
        "catch"
    )
    return candidates[0]


def test_a_tripped_limit_has_exactly_two_legitimate_answers() -> None:
    """The subsection names both legitimate answers, together (AC-1)."""
    paragraph = _answer_paragraph()
    lower = paragraph.lower()
    assert "size:" in lower, (
        "the answer paragraph must name recording the `size:` exemption as the "
        "second legitimate answer, alongside splitting — naming only the split "
        "leaves the honest move for a file that should stay long unstated"
    )
    assert "concern" in lower, (
        "the answer paragraph must say the split is *by concern*; splitting a file "
        "anywhere to get under a number is the same trade this rule forbids"
    )


def test_reducing_the_count_in_place_is_not_one_of_them() -> None:
    """The same paragraph forbids shaving the count, and says why (AC-2)."""
    paragraph = _answer_paragraph()
    lower = paragraph.lower()
    assert "in place" in lower, (
        "the answer paragraph must state that a size limit is never answered by "
        "reducing the line count *in place* — the exploit a line-count gate is "
        "cheapest to satisfy by (#399)"
    )
    # ``inlining``, not ``inlin``: the paragraph cites Part B's *Compose, don't
    # inline* by name two clauses later, so the shorter stem is satisfied by the
    # citation alone and would pin nothing about the forbidden move.
    assert "inlining" in lower, (
        "the answer paragraph must name the concrete move it forbids: inlining a "
        "named component, function, or type back into its caller"
    )
    assert _PART_B_RULE.removeprefix("### ").lower() in lower, (
        f"the answer paragraph must tie the prohibition to Part B's "
        f"{_PART_B_RULE!r} — that is the rule being traded away to satisfy this "
        "one, and naming it is what makes the trade visible"
    )
    # The cited Part B rule must actually exist, or the tie above points nowhere.
    assert _PART_B_RULE in _SKILL.read_text(encoding="utf-8"), (
        f"Part B must still carry {_PART_B_RULE!r}; the size-limit response rule "
        "cites it by name"
    )


def test_the_reviewer_reads_the_diff_that_brought_the_file_under() -> None:
    """The subsection gives the reviewer a diff-reading instrument (AC-3)."""
    section = _size_section()
    lower = section.lower()
    # Word-boundary: the subsection already says "checked differently", so a bare
    # "diff" substring is satisfied before this rule is written at all.
    assert re.search(r"\bdiff\b", lower), (
        "the size subsection must tell the reviewer to read the *diff* that brought "
        "a file under the limit, not just its new count — the count alone cannot "
        "distinguish a split from a shave (#399)"
    )
    assert "finding" in lower, (
        "the size subsection must state that a green gate bought by merging named "
        "units is a *finding*, so the reviewer knows the rule is enforced at review "
        "rather than merely described"
    )
