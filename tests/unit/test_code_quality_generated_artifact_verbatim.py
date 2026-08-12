"""#402 — ``code-quality`` Part A: read the generated artifact, don't re-derive it.

Part A already bounds what a change may *touch* (*Bound the surface*) and forbids
a helper whose concern a sibling module already handles (*Grep before writing a
helper*). Neither reaches the case where the thing already built is not a helper
but a **committed generated artifact**: a generator computes a fact, writes it to
a file in the tree, and a drift test keeps that file honest. Re-deriving the same
fact from the generator's own source inputs is a duplication no grep for a helper
name will find, because the two copies share no symbol — one is a parser, the
other is a JSON read.

The mechanism is what makes it bite rather than merely offend. The existing drift
test guards the *artifact*; it knows nothing about a second derivation. So the
second derivation has to carry a parallel inventory of its own, hand-maintained,
which learns about a new input only when someone remembers to update it — and
nobody is reminded, because the artifact's own guard is green.

This is a text-parse content guard in the established sibling style
(``test_code_quality_size_limit_response``, #399): it **derives** its subject
span from the heading rather than scanning the skill, and it pins polarity rather
than vocabulary, because a substring guard over prose about parsers and artifacts
is otherwise satisfied by any paragraph on the topic — including one that states
the opposite rule.

Every assertion is scoped to **one sentence**, never the subsection. That is the
correction the review of this ticket forced, and it is the same correction #399
took: a subsection-scoped anchor is satisfied by a commonplace word somewhere
else in the subsection, so it passes while the rule it claims to pin is gone.
Both survivors were measured, not imagined — rows (h) and (j) of the table below
are the mutations that a subsection-scoped ``"only"`` and a subsection-scoped
``"drift test"`` let through.

Acceptance criteria (this ticket):

* **AC-1** — The subsection states the rule (read the committed artifact that
  carries its own drift test, never re-derive the fact from the generator's
  source inputs) and the mechanism that makes it bite (the drift test guards the
  artifact, not your derivation, so a second derivation needs a hand-maintained
  parallel inventory of its own). Proven by
  :func:`test_the_rule_is_read_the_artifact_never_re_derive_it`.
* **AC-2** — The same subsection states the narrow exception (the artifact cannot
  carry the shape you need) *and* its obligation (name what the artifact omits,
  in the change spec). Proven by
  :func:`test_the_exception_is_narrow_and_carries_its_obligation`.
* **AC-3** — The subsection sits inside Part A, positionally between the Part A
  and Part B headings. Proven by :func:`test_the_rule_lives_in_part_a`.

**Mutation table.** Each row was applied to ``skills/code-quality/SKILL.md``,
measured by running this file, and reverted. Nothing here is predicted. Rows (h)
to (l) were added by the review of this ticket; rows (h) and (j) survived the
first version of this guard and are the reason every selector below is a
sentence.

===  ==========================================================  ==================
Row  Mutation                                                    Result
===  ==========================================================  ==================
a    Delete the subsection entirely                              killed (all 3)
b    Rename the heading                                          killed (all 3)
c    Invert the rule ("re-derive the fact … rather than          killed (AC-1)
     reading that artifact")
d    Drop the exception clause                                   killed (AC-2)
e    Drop the change-spec obligation, keep the exception         killed (AC-2)
f    Move the whole subsection into Part B                       killed (AC-3)
g    Replace the rule with an unrelated plausible sentence       killed (AC-1)
     that keeps the section's vocabulary
h    Drop ``only`` from the exception ("write a new parser       killed (AC-2)
     where the artifact cannot carry…")
i    Drop the mechanism sentence                                 killed (AC-1)
j    Drop the drift-test precondition from the rule sentence     killed (AC-1)
k    Rewrite the rule into permission ("re-deriving … is a       killed (AC-1)
     judgement call"), every other AC-1 anchor left in place
l    Redirect the obligation to a code comment ("justify it in   killed (AC-2)
     a code comment; the change spec need not mention it")
===  ==========================================================  ==================

Rows (h), (j) and (l) were each re-measured against the *old*, subsection-scoped
anchor on this same trimmed prose: ``"only"``, ``"drift test"`` and ``"change
spec"`` are all still present in the subsection after their mutation, so each row
would still have survived. The kill comes from the sentence scope, not from the
subsection having got shorter.

**Acknowledged limits.**

* Row (a) and row (b) are indistinguishable to this guard: both surface as "the
  heading is missing". That is deliberate — a renamed heading is a rule this
  guard no longer covers, and failing loudly is the right answer to both.
* AC-2 deliberately pins the exception and its change-spec obligation to one
  sentence. Splitting the same meaning across two sentences is semantically
  equivalent but produces a false red whose message reports a missing
  obligation rather than the sentence coupling. That coupling catches a
  half-dropped rewrite where the exception survives but its obligation does not.
* Any rewrite that preserves the anchors while reversing the sense is invisible
  here, and this is the one class no anchor closes. Row (k) is its *mechanizable*
  member — a permission rewrite that drops the prohibition, which the polarity
  anchor catches. Its adversarial twin does not die: measured, "read that
  artifact if you like; a second parser over the generator's source inputs is
  fine too, and nothing here says never re-derive anything" keeps every AC-1
  anchor inside the selected sentence and passes all three tests. So does the
  general case, also measured: a sentence *added* to the subsection that blesses
  re-derivation ("where reading the artifact is awkward, a second parser is
  fine") leaves every selector and every anchor untouched. The mechanism
  sentence has the same limit. Measured, "the drift test guards the artifact,
  not your derivation, so a second derivation needs a hand-maintained parallel
  inventory of its own, but that parallel inventory is good enough" retains
  ``not your derivation`` and ``parallel inventory`` while reversing the
  mechanism, and it passes all three tests. Killing either class would mean
  pinning the rule's exact wording, which turns any honest rewording red. That
  stays reviewer judgment — the same presence-mechanized / substance-judged line
  Part C draws for the ``size:`` marker.
* AC-3 pins Part A membership, not the subsection's ordinal within Part A.
  Measured: relocating it from after *Grep before writing a helper* to just before
  *Carry-forward, not silent cleanup* leaves all three tests green. Ordering
  inside a part is editorial; the part it lives in is the decided placement,
  because Part A is where a change's surface is bounded.
"""

from __future__ import annotations

import re
from pathlib import Path

# ``tests/unit/test_*.py`` → ``parents[2]`` is the repo (or worktree) root.
_REPO_ROOT = Path(__file__).resolve().parents[2]
_SKILL = _REPO_ROOT / "skills" / "code-quality" / "SKILL.md"

_HEADING = "### Read the generated artifact, don't re-derive it"

# The two part headings this guard's placement assertion is measured against,
# cited verbatim so a rename of either breaks this guard loudly rather than
# leaving it comparing offsets against nothing.
_PART_A = "## Part A — Scope"
_PART_B = "## Part B — Structure"


def _skill_text() -> str:
    return _SKILL.read_text(encoding="utf-8")


def _section() -> str:
    """The subsection's own span — its heading to the next ``### ``.

    Derived, never scanned for: an assertion against the whole skill passes on
    wording that lives in another subsection, which would make this guard green
    before the rule it pins was ever written.
    """
    text = _skill_text()
    start = text.find(_HEADING)
    assert start != -1, (
        f"code-quality must carry the subsection {_HEADING!r} — the rule that a fact "
        "already written to a committed generated artifact is read from it, not "
        "re-derived from the generator's source inputs (#402). If the heading was "
        "renamed, update _HEADING here so this guard keeps covering the rule"
    )
    rest = text[start + len(_HEADING) :]
    end = rest.find("\n### ")
    section = rest if end == -1 else rest[:end]
    assert section.strip(), (
        f"the subsection {_HEADING!r} is empty — a heading with no rule under it "
        "states nothing"
    )
    return section


def _sentences() -> list[str]:
    """The subsection's sentences, lowercased.

    Split on the full stop only, so a semicolon-joined rule ("read that
    artifact; never re-derive the fact…") stays the single unit it reads as.
    """
    sentences = [s.strip().lower() for s in re.split(r"(?<=\.)\s+", _section()) if s.strip()]
    # Floor: a mis-parse returns the whole subsection as one blob, or nothing.
    # Set below the four sentences actually there — the rule, its mechanism, its
    # exception and its evidence — so that dropping one is reported by the
    # selector that loses its sentence, not swallowed by this precondition.
    assert len(sentences) >= 3, (
        f"expected the subsection to split into its sentences, got {len(sentences)}"
    )
    return sentences


def _sentence_stating(marker: str, *, what: str) -> str:
    """The one sentence carrying ``marker``.

    Sentence, not subsection. Measured on review of this ticket: a
    subsection-scoped ``"only"`` is satisfied by the mechanism's "told about a
    new input *only* when someone remembers", so deleting ``only`` from the
    exception — turning a narrow exit into permission — left the first version
    of this guard green (row (h)). A subsection-scoped ``"drift test"`` was
    satisfied by the evidence clause the same way (row (j)). Both anchors now
    live inside the sentence that is supposed to carry them.
    """
    matches = [s for s in _sentences() if marker in s]
    assert matches, (
        f"the subsection must carry a sentence stating {what}; this guard selects it "
        f"on {marker!r} and no sentence contains that phrase (#402)"
    )
    assert len(matches) == 1, (
        f"{what} must be stated in one sentence, not spread across {len(matches)} — "
        "every assertion about it is scoped to that sentence, and a second match "
        "means this guard can no longer tell which one it is pinning"
    )
    return matches[0]


def _rule_sentence() -> str:
    """The sentence that states the rule, both halves of it."""
    return _sentence_stating("read that artifact", what="the rule itself")


def _mechanism_sentence() -> str:
    """The sentence that says why the rule bites rather than merely offends."""
    return _sentence_stating("guards the artifact", what="the rule's mechanism")


def _exception_sentence() -> str:
    """The sentence that opens the one exit, and prices it."""
    return _sentence_stating("a new parser", what="the narrow exception")


def test_the_rule_is_read_the_artifact_never_re_derive_it() -> None:
    """The rule is stated, stated the right way round, and mechanized (AC-1)."""
    rule = _rule_sentence()

    # Polarity, not vocabulary. `artifact`, `generator` and `parser` are the
    # ambient words of any sentence on this topic, including one that permits
    # exactly what this rule forbids; `never re-derive` inverts with the rule.
    assert re.search(r"never\s+re-derive", rule), (
        "the rule sentence must state that the fact is *never* re-derived — a "
        "sentence that merely discusses re-deriving it carries the same vocabulary "
        "and the opposite rule, and so does one that recommends it"
    )
    assert "source inputs" in rule, (
        "the rule sentence must name what is not re-derived from: the generator's "
        "*source inputs*. Without that, the rule reads as a ban on parsing in "
        "general rather than on parsing what a generator has already parsed"
    )
    # The precondition, anchored as the whole phrase and inside the rule
    # sentence: a bare `drift test` anywhere in the subsection is satisfied by
    # the evidence clause, which left the precondition deletable (row (j)).
    assert "committed artifact that carries its own drift test" in rule, (
        "the rule sentence must state its precondition — the artifact is "
        "*committed* and *carries its own drift test*. Without it the rule licenses "
        "reading any generated file, guarded or not, which is worse than the "
        "re-derivation it replaces: an unguarded artifact goes stale silently"
    )

    mechanism = _mechanism_sentence()
    assert "not your derivation" in mechanism, (
        "the mechanism sentence must say the drift test guards the artifact, *not "
        "your derivation* — that asymmetry is the whole reason the rule bites "
        "rather than merely offends"
    )
    assert "parallel inventory" in mechanism, (
        "the mechanism sentence must name the cost the second derivation takes on: "
        "a hand-maintained *parallel inventory* the artifact's guard never checks"
    )


def test_the_exception_is_narrow_and_carries_its_obligation() -> None:
    """The one exit, and what it costs the person taking it (AC-2)."""
    exception = _exception_sentence()

    # `a new parser only where`, not a bare `only`: measured, the bare word is
    # satisfied by the mechanism sentence's "only when someone remembers", so
    # rewriting this sentence to "write a new parser where the artifact cannot
    # carry…" — a narrow exception turned into permission — left the first
    # version of this guard green (row (h)).
    assert "a new parser only where" in exception, (
        "the exception must be stated as narrow — a new parser *only where* the "
        "artifact cannot carry the shape you need. An exception offered as one "
        "option among several is permission"
    )
    assert "cannot carry" in exception, (
        "the exception must be stated in terms of the artifact's own limits — the "
        "artifact *cannot carry* the shape you need. A prohibition with no exit is "
        "unenforceable where the artifact genuinely omits the shape"
    )
    # The whole imperative, not a bare `change spec`: the phrase survives a
    # sentence that names the change spec only to excuse it ("the change spec
    # need not mention it", row (l)).
    assert "justify it in the change spec" in exception, (
        "the exception must carry its obligation: the justification is written into "
        "the *change spec*. An exception nobody has to write down is not audited by "
        "anyone, which is the same as no exception clause at all"
    )
    assert "omits" in exception, (
        "the justification must name what the artifact *omits* — 'the artifact was "
        "not suitable' is not a justification a reviewer can check"
    )


def test_the_rule_lives_in_part_a() -> None:
    """Placement: inside Part A, not Part B or Part C (AC-3)."""
    text = _skill_text()

    part_a = text.find(_PART_A)
    part_b = text.find(_PART_B)
    heading = text.find(_HEADING)

    # Anti-vacuity: each anchor gets its own assertion and its own message, so a
    # rename upstream reports the rename rather than a misleading ordering failure.
    assert part_a != -1, (
        f"code-quality must carry {_PART_A!r}; this guard's placement assertion is "
        "meaningless without it"
    )
    assert part_b != -1, (
        f"code-quality must carry {_PART_B!r}; this guard's placement assertion is "
        "meaningless without it"
    )
    assert heading != -1, (
        f"code-quality must carry the subsection {_HEADING!r} (#402)"
    )
    assert part_a < part_b, (
        f"{_PART_A!r} must precede {_PART_B!r} — the skill's three parts run in the "
        "order it declares (Scope, Structure, Verification)"
    )
    assert part_a < heading < part_b, (
        "the rule must live in Part A — Scope. It bounds what a change writes: "
        "whether the fact you need is already computed and committed decides "
        "whether a second parser belongs in the diff at all. In Part B it reads as "
        "a structural preference and in Part C as a verification step, and neither "
        "reaches the author before the parser is written"
    )
