"""``code-quality`` Part C: a guard derives its subjects; it does not list them.

A structural guard test whose scope is a hardcoded list keeps passing while the
surface it guards grows past it, and nothing anywhere reports that it stopped
covering anything. An assessment pass named the shape after three instances had
accumulated: a command-boundary guard four modules behind across three separate
additions, a payload-key guard that never saw a third reader module arrive, and
four tree-walking guards whose hand-rolled skip lists had to be replaced by the
tracked file set.

The rule lives in ``code-quality`` rather than ``review-discipline`` because
``agents/dev.md`` and ``agents/reviewer.md`` both point at this one file, so a
single home binds the rule when a guard is written *and* again when it is
reviewed.

**What this module asserts, after #459.** ADR 0016 (*tests own structure and
negative space; the reviewer owns meaning*) collapsed eight prose predicates over
this one subsection into a single tripwire. What remains is structure plus
polarity:

* the subsection **exists inside Part C** — the slicer resolves the heading from
  ``## Part C`` onward and fails loudly when it does not, which is the placement
  claim the old ordinal-neighbour test spelled out separately;
* a small term set the rule cannot be stated without (a derivation verb,
  ``git ls-files``, ``literal list``, ``matching predicate``, ``reject``);
* the **negation anchored to the construct it governs** — *never a literal list*
  — which is the half that survives an inversion. A bare co-occurrence of those
  terms is satisfied by a paragraph recommending the literal list, so the
  anchored negation is the only assertion here that reads a direction.
  Occurrence it cites (``code-quality`` Part C, *A new guard cites the occurrence
  it prevents*): the eight predicates this replaced all passed on prose that
  named every term while the rule stayed intact — none of them could have failed
  on the rule being reversed, and each of them failed on a rewording that kept it.

:func:`test_rule_is_universal` is unchanged: it is a **negative-space** sweep (no
one stack's vocabulary rides into a consuming repo), which ADR 0016 exempts and
keeps byte-for-byte.

Deliberately **not** re-checked here — three existing guards already own these,
and copying them is the duplication Part A forbids: the skill header/registry
version parity (``test_placeholder_stub_gating``), ``registry.yaml``'s own
self-version parity (``test_guidance_github_source``), and the registered-prose
ticket-ID sweep (``test_distributed_prose_no_repo_ids``).
"""

from __future__ import annotations

import re

from tests.unit._prose import REPO_ROOT

_SKILL = REPO_ROOT / "skills" / "code-quality" / "references" / "specialized-verification.md"

_HEADING = "### A guard derives its subjects; it does not list them"

#: The derivation obligation, stated with either verb the rule uses.
_DERIVES = re.compile(r"\bderiv\w*\b|\bcomput\w*\b", re.IGNORECASE)

#: The prohibition, **anchored to the construct it governs**. A window merely
#: containing a negation somewhere and ``literal list`` somewhere states nothing —
#: almost any English paragraph carries a negation. Four words is the gap every
#: legitimate spelling keeps ("never a literal list", "not a literal list in the
#: test body"); further off, the negation governs something else.
_NEVER_A_LITERAL_LIST = re.compile(
    r"\b(?:never|not|no)\b(?:\W+\w+){0,4}?\W+literal list\b", re.IGNORECASE
)


def _part_c() -> str:
    """The '## Part C' verification section — to end of file."""
    text = _SKILL.read_text(encoding="utf-8")
    start = text.find("## Part C")
    assert start != -1, "code-quality must have a '## Part C' verification section"
    return text[start:]


def _section() -> str:
    """The subsection's own span — its heading to the next ``### ``.

    Scoped deliberately, and scoped **from Part C**: an unscoped whole-document
    search passes on phrasing that already exists in a sibling subsection, which
    would make this guard green before the subsection it pins was ever written,
    and the placement claim (this rule belongs in the verification part) is
    carried by where the slicer starts looking rather than by a separate ordinal
    assertion an insertion can invalidate.
    """
    part_c = _part_c()
    start = part_c.find(_HEADING)
    assert start != -1, (
        f"code-quality Part C must carry the subsection {_HEADING!r} — the rule "
        "that a guard computes its subject set from the artifact defining it"
    )
    rest = part_c[start + len(_HEADING) :]
    end = rest.find("\n### ")
    return (rest if end == -1 else rest[:end]).lower()


def test_the_derivation_rule_is_stated_in_its_home() -> None:
    """One tripwire for one rule-home: anchor, term set, and the negation (#459)."""
    section = _section()
    assert section.strip(), f"the subsection {_HEADING!r} is empty"

    assert _DERIVES.search(section), (
        "the rule must state that the guard *derives* (or computes) its subject "
        "set from the artifact that defines it"
    )
    assert "git ls-files" in section, (
        "the rule must name `git ls-files` as a concrete deriving artifact — the "
        "one example universal to every consuming repo whatever its stack"
    )
    assert _NEVER_A_LITERAL_LIST.search(section), (
        "the rule must *prohibit* the literal list, not merely mention it. The "
        "negation has to sit next to the construct it governs: a subsection "
        "naming derivation, `git ls-files` and literal lists while recommending "
        "the literal list satisfies every other assertion here"
    )
    assert "matching predicate" in section, (
        "the rule must extend to the guard's *matching predicate* — a derived "
        "subject set proves only that the guard looked at every unit, and what "
        "counts as a hit is a second, independent place to narrow"
    )
    assert "reject" in section, (
        "the rule must bind at review with an explicit rejection clause, matching "
        "its neighbouring Part C subsections; without it the rule binds only on "
        "the author's own discipline"
    )


def test_rule_is_universal() -> None:
    """No single stack's vocabulary rides into a consuming repo (AC-4)."""
    section = _section()

    assert "set" in section, (
        "the rule must be stated over a *set* of files, modules, or keys — the "
        "abstraction that makes it apply beyond the instances that prompted it"
    )

    # `git` is a deliberate carve-out from this ban list, not an oversight:
    # `git ls-files` is named in the acceptance criterion, and git is universal
    # in a way a test runner or a web framework is not. Do not add it here.
    for leaked in ("typer", "pytest", "python", "sqlite", "linear", "harness"):
        assert leaked not in section, (
            f"the rule leaks {leaked!r} into prose the installer copies verbatim "
            "into third-party repos — state the rule in artifacts every repo "
            "has, not in this one's stack"
        )
