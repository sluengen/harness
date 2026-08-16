"""Every proposal's ``status:`` is a member of the vocabulary's single home.

**The occurrence this guard cites (#458).** ADR 0015 deleted the runtime and
nothing said so in ``specs/proposals/``. Nineteen proposals carried
``status: accepted`` — the vocabulary's *decided, still buildable* state — while
fourteen of them cited paths the teardown had removed. The vocabulary had no word
for "this died", so nothing had been said, and an agent grounding a ticket
against one of those files inherited instructions targeting deleted code.

Two properties, two assertions, and they have separate exclusive killers:

* the vocabulary is **derived** from its single home (``templates/proposal.md``'s
  ``status:`` line, verified as the only home on #458 — ``spec-authoring`` does
  not restate it), so a word added there is a word proposals may carry, with no
  second list in this module to keep in step;
* every tracked ``specs/proposals/*.md`` carries a status **from that set**, so a
  typo or an invented state fails the gate rather than waiting for a reader.

**The anchor fails loudly.** ADR 0016's rule for a derived guard is that a
derivation which stops resolving must go red, never quiet: a status line this
module could not parse would yield an empty vocabulary, and an empty vocabulary
turns the sweep below into a check that every proposal is a member of nothing —
which is either constantly red or, had the sweep been written the other way
round, constantly green. :func:`status_vocabulary` therefore raises rather than
returning an empty set, and :func:`test_the_status_line_anchor_resolves` pins
membership (never cardinality) so the anchor is proven live independently of the
sweep that consumes it.

**Two assertions added at review, each closing a live survivor.** Every test
above feeds :func:`status_vocabulary` the real template, so neither the fact
that it *derives* nor the fact that its pattern is anchored to line start was
measured by anything: replacing the derivation with a hardcoded copy of today's
words, and dropping the ``^``, each ran live with the whole suite green.
:func:`test_the_vocabulary_is_derived_from_the_text_it_is_given` and
:func:`test_the_status_line_anchor_does_not_open_mid_sentence` feed it synthetic
text instead, which is the only way either property is visible.

This guard reads the **tracked** tree (`tests._gitutil.tracked_files_under`), per
``CONTEXT.md``'s Python conventions: an untracked draft in the working directory
is not yet a proposal the repo publishes.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from tests._gitutil import tracked_files_under

_REPO_ROOT = Path(__file__).resolve().parents[2]
_TEMPLATE_REL = "templates/proposal.md"
_TEMPLATE = _REPO_ROOT / _TEMPLATE_REL

#: The status line in its frontmatter, with the vocabulary in its trailing
#: comment: ``status: draft   # draft | under-decision | accepted | ...``.
#: Anchored to line start so a mention of the word ``status:`` mid-sentence
#: cannot open a match — the counterfeited-delimiter class in ``craft.md``.
_STATUS_LINE = re.compile(
    r"^status:\s*\S+\s*#\s*(?P<vocab>[a-z][a-z-]*(?:\s*\|\s*[a-z][a-z-]*)+)\s*$",
    re.MULTILINE,
)

#: A proposal's own frontmatter status, same anchoring, no trailing comment
#: required.
_PROPOSAL_STATUS = re.compile(r"^status:\s*(?P<status>[a-z][a-z-]*)\s*(?:#.*)?$", re.MULTILINE)


def status_vocabulary(text: str) -> frozenset[str]:
    """The proposal status vocabulary, parsed from the template's status line.

    Raises rather than returning an empty set when the anchor stops resolving:
    a silent empty vocabulary is the defect ADR 0016 names, and every caller
    below would otherwise report something other than what it claims to measure.
    """
    match = _STATUS_LINE.search(text)
    if match is None:
        raise AssertionError(
            f"the proposal status vocabulary anchor no longer resolves in "
            f"{_TEMPLATE_REL}: expected a frontmatter line of the form "
            f"'status: <default>   # a | b | c'. The vocabulary has one home; "
            f"if it moved, re-point this guard at the new one rather than "
            f"letting the derivation go quiet."
        )
    return frozenset(word.strip() for word in match.group("vocab").split("|"))


def proposal_status(text: str) -> str:
    """The ``status:`` a proposal's frontmatter declares.

    Raises on a proposal with no parseable status, for the same reason: a
    proposal that declares nothing must not read as a proposal that declares
    something valid.
    """
    match = _PROPOSAL_STATUS.search(text)
    if match is None:
        raise AssertionError(
            "no parseable 'status:' line in this proposal's frontmatter"
        )
    return match.group("status")


def _tracked_proposals() -> list[Path]:
    return sorted(
        path
        for path in tracked_files_under("specs/proposals")
        if path.suffix == ".md"
    )


def test_the_status_line_anchor_resolves() -> None:
    """The vocabulary derives, is non-empty, and names the lifecycle's own states.

    The membership floor is the three terminal states the template's *Lifecycle*
    paragraph spells out in prose one screen below the status line. Pinning
    membership rather than a count is deliberate — a cardinality floor is
    satisfied forever by the next edit that adds a word and removes another
    (``craft.md`` → *Floors decay into decoration*).
    """
    vocabulary = status_vocabulary(_TEMPLATE.read_text())
    assert vocabulary, f"{_TEMPLATE_REL} yielded an empty status vocabulary"
    assert {"accepted", "rejected", "split"} <= vocabulary, (
        f"{_TEMPLATE_REL}'s status line no longer offers the three terminal "
        f"states its own Lifecycle paragraph names; derived: {sorted(vocabulary)}"
    )


def test_the_vocabulary_is_derived_from_the_text_it_is_given() -> None:
    """The derivation itself, rather than today's answer.

    AC-1 asks for the vocabulary to come from its single home and **not** from a
    copy in the test. Every other assertion in this module is satisfied by a
    hardcoded frozenset of the live words: review replaced the derivation with
    exactly that and the edit ran **live** with the whole suite green. Feeding
    the parser a status line whose words appear nowhere in this repo is what
    makes the derivation, rather than its current output, the thing under test.
    """
    assert status_vocabulary("status: alpha   # alpha | beta | gamma") == frozenset(
        {"alpha", "beta", "gamma"}
    )


def test_the_status_line_anchor_does_not_open_mid_sentence() -> None:
    """The ``^`` anchor's stated purpose, which nothing else measured.

    ``craft.md`` → *A paired delimiter can be counterfeited by prose that
    mentions it*: a sentence merely naming ``status:`` must not get to define
    the vocabulary. Dropping the anchor survived the whole suite before this
    sample, because every other caller feeds the parser the real template,
    whose status line sits at line start either way.
    """
    with pytest.raises(AssertionError):
        status_vocabulary("prose mentioning status: x   # alpha | beta")


def test_superseded_is_in_the_vocabulary() -> None:
    """AC-1: the vocabulary can say a proposal's subject died.

    Separate from the anchor floor above so the two have separate exclusive
    killers: removing ``superseded`` from the template kills only this one, and
    breaking the status line kills only that one.
    """
    vocabulary = status_vocabulary(_TEMPLATE.read_text())
    assert "superseded" in vocabulary, (
        f"{_TEMPLATE_REL}'s status line has no 'superseded' state, so a proposal "
        f"whose machinery was retired has no honest status to carry — the #458 "
        f"defect. Derived vocabulary: {sorted(vocabulary)}"
    )


def test_the_proposal_corpus_is_not_empty() -> None:
    """The sweep's subject floor, in its own function.

    A floor carried inside the sweep vanishes with the set it protects
    (``craft.md`` → *The floor inside the parametrization*).
    """
    assert _tracked_proposals(), (
        "git tracks no specs/proposals/*.md — the status sweep below would pass "
        "over an empty set and measure nothing."
    )


def test_every_tracked_proposal_carries_a_known_status() -> None:
    """No proposal declares a status the vocabulary does not define."""
    vocabulary = status_vocabulary(_TEMPLATE.read_text())
    offenders = {
        path.relative_to(_REPO_ROOT).as_posix(): status
        for path in _tracked_proposals()
        if (status := proposal_status(path.read_text())) not in vocabulary
    }
    assert not offenders, (
        f"these proposals declare a status outside the vocabulary defined at "
        f"{_TEMPLATE_REL} ({sorted(vocabulary)}) — add the state to its single "
        f"home or fix the proposal: {offenders}"
    )
