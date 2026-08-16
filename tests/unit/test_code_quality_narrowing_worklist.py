"""``code-quality`` Part C: a narrowing's worklist is the transitive consumers.

From the 2026-07-16 code assessment (CODE-INSIGHT-1). A batch deliberately
hunting a null-sentinel narrowed it at each render edge and left the coercion
operator as a greppable worklist for a follow-up. The follow-up cleared every
callsite the operator grep returned — and still missed two: one coercion was two
files upstream of the render it fed (grepping the operator finds the coercion,
not the render), and one documented exception was waved through while a new
consumer did arithmetic on the sentinel. Both were findings that survived a pass
built to catch exactly this.

The rule: when a change narrows a nullable at a boundary, the worklist is every
*transitive consumer* of that field, enumerated by following the type to its
readers — not the callsites a grep for the coercion operator returns.

**What this module asserts, after #459.** Under ADR 0016 (*tests own structure
and negative space; the reviewer owns meaning*) the term-set pin and the separate
placement pin collapse into a single tripwire:

* the section **exists inside Part C** — the slicer starts at ``## Part C``, so
  the placement claim rides on where the anchor is looked for;
* the terms the rule cannot be stated without (``worklist``, ``transitive
  consumer``, ``following the type``);
* the **contrast anchored to what it excludes** — *not the callsites*. That is
  the rule's whole content, and it is the only assertion here that reads a
  direction: a section naming worklists, transitive consumers and greps while
  endorsing the callsite grep as the worklist satisfies every term above.
  Occurrence it cites (``code-quality`` Part C, *A new guard cites the occurrence
  it prevents*): the predecessor asserted ``"coercion" in lower and "grep" in
  lower``, which the inverted rule states just as fully as the correct one.

:func:`test_narrowing_worklist_rule_is_universal` is unchanged — a
**negative-space** sweep, which ADR 0016 exempts and keeps byte-for-byte.
"""

from __future__ import annotations

import re
from pathlib import Path

# ``tests/unit/test_*.py`` → ``parents[2]`` is the repo (or worktree) root.
_REPO_ROOT = Path(__file__).resolve().parents[2]
_SKILL = _REPO_ROOT / "skills" / "code-quality" / "references" / "specialized-verification.md"

_HEADING = "### Narrowing a nullable is a whole-call-graph change"

#: The exclusion **anchored to the set it excludes**. A window merely carrying a
#: negation and the word *callsites* somewhere states nothing; the claim is that
#: the callsite grep is not the worklist.
#:
#: The gap is two words, measured rather than chosen: at three, the section's own
#: later sentence — "never its boundary: the callsite that reads the narrowed
#: value" — satisfies the predicate, and inverting the rule leaves it green. Two
#: admits every legitimate spelling of the exclusion ("not the callsites", "not
#: the local callsites") and nothing else in the section.
_NOT_THE_CALLSITES = re.compile(
    r"\b(?:not|never|no)\b(?:\W+\w+){0,2}?\W+callsites?\b", re.IGNORECASE
)


def _skill_text() -> str:
    return _SKILL.read_text(encoding="utf-8")


def _section() -> str:
    """The rule's own section body, sliced from Part C to the next heading.

    Scoped deliberately: an assertion run against the whole file would pass on
    wording that lives in some other section, so it would not prove *this* rule
    is present. Starting the search at ``## Part C`` is what makes the slice
    carry the placement claim as well.
    """
    text = _skill_text()
    part_c = text.find("## Part C")
    assert part_c != -1, "code-quality must have a Part C verification section"
    rest_of_part_c = text[part_c:]
    start = rest_of_part_c.find(_HEADING)
    assert start != -1, (
        "code-quality's Part C verification gate must carry the narrowing-worklist "
        f"rule under the heading {_HEADING!r}"
    )
    rest = rest_of_part_c[start + len(_HEADING) :]
    end = rest.find("\n### ")
    return rest if end == -1 else rest[:end]


def test_the_narrowing_worklist_rule_is_stated_in_its_home() -> None:
    """One tripwire for one rule-home: anchor, term set, and the exclusion (#459)."""
    lower = _section().lower()
    assert lower.strip(), f"the section {_HEADING!r} is empty"

    assert "worklist" in lower, (
        "the rule must name the change's *worklist* — the thing the enumeration "
        "produces — so an agent knows what set it is completing"
    )
    assert "transitive consumer" in lower, (
        "the worklist must be the *transitive consumers* of the narrowed field, "
        "not the local callsites — that transitivity is the whole point"
    )
    assert "following the type" in lower, (
        "the rule must say the consumers are enumerated by *following the type* "
        "to its readers — the mechanism that catches the file the grep misses"
    )
    assert _NOT_THE_CALLSITES.search(lower), (
        "the rule must exclude the callsite set by name, with the negation "
        "anchored to it: a section that names the type-driven enumeration and "
        "then offers the coercion-operator grep as the worklist carries every "
        "other term here and states the opposite rule"
    )


def test_narrowing_worklist_rule_is_universal() -> None:
    """The rule names no single consumer's stack (AC-3).

    The rule was filed from one consumer's defect, in that consumer's terms (a
    coercion in a mobile helper feeding a render two files away). The skill is
    distributed to every repo, so it keys off the type / call graph every
    language has instead — a repo with no mobile client still narrows nullables
    and still has readers to follow the type to. This guard pins that boundary,
    the standing rule for guidance edits born from a single repo.
    """
    section = _section()
    lower = section.lower()

    # Speaks in universal call-graph vocabulary, not a stack's.
    assert "consumer" in lower and "reader" in lower, (
        "the rule must speak in call-graph terms (consumers, readers) that hold "
        "in any language, not one stack's component vocabulary"
    )
    for leak in ("mobile", "react", "expo", "typescript", "http", "endpoint"):
        assert leak not in lower, (
            f"the rule must not name {leak!r}: code-quality is distributed to "
            "every consumer repo, and the originating defect's stack is not a "
            "universal one (the universal/repo boundary)"
        )
