"""``spec-authoring``: file size is never an AC; renegotiation lives on the ticket.

From proposal ``size-criterion-process`` (accepted 2026-07-17). A prior ticket
shipped Done against the criterion "review.py under 500 lines" while the file
stood at 759: a raw line count landed as an acceptance criterion with no
measuring test, and the builder's correct renegotiation lived only in a commit
body where the tracker could not see it.

**What this module asserts, after #459.** One tripwire over one rule-home. The
home is ``skills/spec-authoring/SKILL.md`` → ``## Change spec``, sliced to the
paragraph carrying each half of the rule, and the assertion is a small term set
the half cannot be stated without plus — for the half that has one — the
negation token inside that paragraph. It does **not** assert that the prose says
the right thing; per ADR 0016 that is the review gate's job, because no regex
reads meaning and a pinned sentence is brittle and vacuous at once.

Craft class this conversion answers (`review-discipline` → ``craft.md``, and
``code-quality`` Part C → *A guard over prose owns structure and negative space,
never meaning*): the two functions this replaced pinned
``"file size is never an acceptance criterion"`` as a literal and then checked
five more bare containments across the whole section. Occurrence: the literal
broke on any rewording that preserved the rule exactly, while an edit inverting
the rule in the next sentence left both green.

**Polarity is asymmetric between the two halves, and the docstring says so
rather than faking one.** The size half has a direction — a size target is
*never* an acceptance criterion — so the negation is asserted anchored to the
noun it governs. The renegotiation half is a plain obligation (comment, amend
there, then build), so there is no negation to read; its terms are asserted
without one instead of leaning on a bare ``"not" in paragraph``, which almost
any English paragraph satisfies.
"""

from __future__ import annotations

import re
from pathlib import Path

# ``tests/unit/test_*.py`` → ``parents[2]`` is the repo (or worktree) root.
_REPO_ROOT = Path(__file__).resolve().parents[2]
_SKILL = _REPO_ROOT / "skills" / "spec-authoring" / "SKILL.md"

#: The size half's direction, anchored to the noun it governs. A bare negation
#: anywhere in the paragraph would be decoration; what the rule says is that the
#: *criterion* is the thing a size target may never be.
_NEVER_A_CRITERION = re.compile(
    r"\b(?:never|not|no)\b(?:\W+\w+){0,6}?\W+acceptance criteri\w+"
    r"|\bacceptance criteri\w+(?:\W+\w+){0,6}?\W+\b(?:never|not|no)\b",
    re.IGNORECASE,
)


def _skill_text() -> str:
    return _SKILL.read_text(encoding="utf-8")


def _change_spec_section() -> str:
    """The ``## Change spec`` section, bounded by the next top-level heading.

    Matched as a whole heading (``^## Change spec`` with a word boundary), not
    as a substring: ``text.find("## Change spec")`` — what this used before #459
    — also resolves against ``## Change specification``, so a renamed section
    still handed back a section and the anchor was not one.
    """
    text = _skill_text()
    m = re.search(r"^##\s+Change spec\b", text, re.MULTILINE)
    assert m, "spec-authoring must have a '## Change spec' section"
    rest = text[m.end() :]
    nxt = re.search(r"^##\s+", rest, re.MULTILINE)
    return rest[: nxt.start()] if nxt else rest


def _paragraph_carrying(term: str) -> str:
    """The one paragraph of ``## Change spec`` carrying ``term``.

    The reading window is a paragraph, not the section: "done", "ticket" and
    "criterion" all recur across the section's other conditional rules, so a
    section-wide conjunction would be satisfied by paragraphs that say nothing
    about size at all — the over-wide unit ``craft.md`` → *The text unit is part
    of the predicate* names.
    """
    hits = [p for p in _change_spec_section().split("\n\n") if term in p.lower()]
    assert len(hits) == 1, (
        f"spec-authoring's '## Change spec' section has {len(hits)} paragraphs "
        f"carrying {term!r}; the size-criterion rule is one paragraph and its "
        f"renegotiation protocol is another"
    )
    return hits[0].lower()


def test_the_size_criterion_rule_has_a_home() -> None:
    """A size target is never an AC; the structural outcome is what a spec states.

    Two conjuncts and a negation. ``structural outcome`` is the sanctioned
    alternative — without it the paragraph forbids something and offers nothing,
    which is the shape a spec author works around rather than follows.
    """
    paragraph = _paragraph_carrying("file size")
    assert _NEVER_A_CRITERION.search(paragraph), (
        "spec-authoring's file-size paragraph no longer states that a size "
        "target is *never* an acceptance criterion. Term co-occurrence has no "
        "direction: without the negation beside the noun, a paragraph that "
        "permitted a raw line count as a criterion would read the same to this "
        "guard."
    )
    assert "structural outcome" in paragraph, (
        "the rule must name the structural-outcome alternative a size target is "
        "a proxy for; a prohibition with no sanctioned form is routed around"
    )


def test_the_renegotiation_protocol_has_a_home() -> None:
    """A criterion found wrong mid-build is renegotiated on the ticket, before Done.

    **No polarity is asserted here, and that is deliberate.** The rule is an
    obligation — comment with the evidence, amend the criterion there, build to
    the amended spec — so it carries no negation that a rewording could not
    drop while keeping the rule. Asserting a bare ``"not"`` over the paragraph
    would be decoration rather than a direction, per ADR 0016.
    """
    paragraph = _paragraph_carrying("renegotiat")
    for term, why in (
        ("ticket", "the renegotiation is recorded on the ticket, where the "
                   "canonical record can see it"),
        ("done", "it happens before any Done claim, or the record everyone "
                 "reads after the work is already wrong"),
        ("commit body", "a commit-body-only argument is called out as leaving "
                        "the tracker's criterion wrong"),
    ):
        assert term in paragraph, (
            f"spec-authoring's renegotiation paragraph no longer names {term!r} — {why}"
        )
