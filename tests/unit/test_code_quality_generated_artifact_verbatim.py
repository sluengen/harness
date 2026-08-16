"""#402 — ``code-quality`` Part A: read the generated artifact, don't re-derive it.

Part A already bounds what a change may *touch* (*Bound the surface*) and forbids
a helper whose concern a sibling module already handles (*Grep before writing a
helper*). Neither reaches the case where the thing already built is not a helper
but a **committed generated artifact**: a generator computes a fact, writes it to
a file in the tree, and a drift test keeps that file honest. Re-deriving the same
fact from the generator's own source inputs is a duplication no grep for a helper
name will find, because the two copies share no symbol — one is a parser, the
other is a JSON read. The mechanism is what makes it bite: the drift test guards
the *artifact* and knows nothing about a second derivation, so the second
derivation carries a hand-maintained parallel inventory that learns about a new
input only when someone remembers.

**Converted under #459** (ADR 0016, and ``code-quality`` Part C → *A guard over
prose owns structure and negative space, never meaning*). Three tests carrying
eight phrase anchors across three sentences — a sentence splitter, a
one-sentence-per-anchor selector, and a Part A/Part B offset assertion — became
the single tripwire below.

The old module's own docstring had already argued its way to the edge of this
decision: it recorded, from measurement, that a sentence *added* to the
subsection blessing re-derivation left every selector and every anchor untouched,
and that killing that class would mean pinning the rule's exact wording, which
turns any honest rewording red. That is ADR 0016's finding, reached one
subsection at a time. What ADR 0016 adds is that the *cost* of those anchors was
being paid on every edit for assurance the module itself documented as absent.
The #402 mutation table is retired with the assertions it measured; nothing below
carries a prediction from it.

**What this module now asserts.** One tripwire, one rule-home:

* **Anchor** — ``### Read the generated artifact, don't re-derive it`` resolves
  *from inside* ``## Part A — Scope``. The nesting is the placement claim, so the
  offset assertion is gone: a subsection relocated to Part B or Part C stops
  resolving. (The old guard already recorded that ordering *within* Part A is
  editorial and deliberately unpinned; that stays true.)
* **Term set** — ``drift test`` (the precondition that makes the artifact
  trustworthy) and ``source inputs`` (what is not re-derived from). Without the
  second the rule reads as a ban on parsing in general rather than on parsing
  what a generator has already parsed.
* **Polarity** — ``never re-derive``, as a bound phrase rather than a bare
  negation. This is the anchor that inverts with the rule: a subsection
  discussing artifacts, generators and parsers carries the same vocabulary while
  permitting exactly what the rule forbids (``craft.md`` → *Mutate the rule into
  its opposite, not only out of existence*).

**What it does not prove.** That the exception clause is still narrow, or that
its change-spec obligation survives. Those were pinned sentence-by-sentence
before and are now the reviewer's — as is any rewrite that keeps ``never
re-derive`` while blessing re-derivation in the sentence after it, which no regex
separates from the rule.
"""

from __future__ import annotations

import re
from pathlib import Path

from tests.unit.test_assurance_filing_rubric import _section

# ``tests/unit/test_*.py`` → ``parents[2]`` is the repo (or worktree) root.
_REPO_ROOT = Path(__file__).resolve().parents[2]
_SKILL = _REPO_ROOT / "skills" / "code-quality" / "SKILL.md"

_PART_A = "## Part A — Scope"
_HEADING = "### Read the generated artifact, don't re-derive it"

#: The words the rule cannot be stated without.
_TERMS = (r"\bdrift test\b", r"\bsource inputs\b")

#: The polarity, bound to the verb it governs.
_NEVER_RE_DERIVE = re.compile(r"\bnever\s+re-derive\b", re.IGNORECASE)


def _rule() -> str:
    """The subsection, sliced from inside ``## Part A — Scope``.

    ``_section`` is imported rather than re-spelled, and the two calls are
    nested so the placement claim lives in the anchor instead of a second test.
    """
    text = _SKILL.read_text(encoding="utf-8")
    return _section(_section(text, _PART_A), _HEADING)


def test_the_read_the_artifact_rule_has_a_home() -> None:
    """One tripwire: the rule is in Part A, names its terms, keeps its polarity."""
    rule = _rule()
    assert rule.strip(), (
        f"{_HEADING!r} is empty — a heading with no rule under it states nothing "
        "(#402)."
    )

    missing = [t for t in _TERMS if not re.search(t, rule, re.IGNORECASE)]
    assert not missing, (
        f"{_HEADING!r} no longer carries the terms the rule cannot be stated without; "
        f"missing {missing}. The artifact is trusted because it carries its own "
        "*drift test*, and what is not re-derived is the generator's *source inputs* "
        f"(#402). Section read:\n{rule}"
    )

    assert _NEVER_RE_DERIVE.search(rule), (
        "the rule has lost its polarity: the fact must be stated as *never* "
        "re-derived. A subsection that discusses artifacts, generators and parsers "
        "carries every term above while permitting exactly what this rule forbids "
        f"(#402). Section read:\n{rule}"
    )
