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
reviewed. A mirrored copy would buy no extra binding and add a second prose copy
to keep in sync.

This is a text-parse content guard in the established sibling style
(``test_code_quality_narrowing_worklist``), scoped to the new subsection's own
span: an assertion against the whole file would pass on wording that lives in
another section, which is the same not-actually-checking failure this rule is
about.

Acceptance criteria (this ticket):

* **AC-1** — Part C gains the subsection, stating the derive-from-the-defining-
  artifact obligation and the literal-list prohibition. Proven by
  :func:`test_rule_requires_deriving_the_subject_set`.
* **AC-2** — It states the silent-narrowing failure mode, the completeness
  escape hatch, and the reviewer binding. Proven by
  :func:`test_rule_states_the_failure_mode_and_the_escape_hatch`.
* **AC-3** — The subsection sits in Part C, immediately after the file-size
  rule. Proven by :func:`test_rule_sits_immediately_after_the_size_rule`.
* **AC-4** — The prose is universal: no one stack's vocabulary rides into a
  consuming repo. Proven by :func:`test_rule_is_universal`.

The subsection later gained a third paragraph extending the same rule to the
guard's *matching predicate*: a derived subject set proves only that the guard
looked at every unit, and what counts as a hit is a second, independent place to
narrow. Two guards had already drifted that way — one enumerating every tracked
source and then failing to recognize a prefixed form of the construct it
matched, another scanning every live section and then exempting the one shape
that had gone stale. Both satisfied the rule above in full, because it governs
only *which units are checked*.

Acceptance criteria (the predicate half):

* **AC-1** — The subsection states that the matching predicate is under the same
  rule as the subject set. Proven by
  :func:`test_rule_extends_to_the_matching_predicate`.
* **AC-2** — Every literal in a predicate must be derived or justified against
  the rule's full surface. Proven by
  :func:`test_predicate_literals_are_derived_or_justified`.
* **AC-3** — The reviewer rejects a predicate narrower than its rule. Proven by
  :func:`test_predicate_rule_binds_the_reviewer`.
* **AC-4** — The tell is named, so the failure mode is recognisable rather than
  merely prohibited. Proven by :func:`test_predicate_rule_names_the_tell`.
* **AC-5** — The paragraph selector is a genuine selection, not the whole
  subsection. Proven by :func:`test_predicate_paragraph_is_a_proper_subset`.

Universality (AC-7 of that ticket) is discharged by the **existing**
:func:`test_rule_is_universal`: it is scoped to the subsection, whose span now
contains the new paragraph, so the ban list covers it without a second copy —
verified by mutation, not assumed.

Deliberately **not** re-checked here — three existing guards already own these,
and copying them is the duplication Part A forbids: the skill header/registry
version parity (``test_placeholder_stub_gating``), ``registry.yaml``'s own
self-version parity (``test_guidance_github_source``), and the registered-prose
ticket-ID sweep (``test_distributed_prose_no_repo_ids``).
"""

from __future__ import annotations

from pathlib import Path

# ``tests/unit/test_*.py`` → ``parents[2]`` is the repo (or worktree) root.
_REPO_ROOT = Path(__file__).resolve().parents[2]
_SKILL = _REPO_ROOT / "skills" / "code-quality" / "SKILL.md"

_HEADING = "### A guard derives its subjects; it does not list them"
_SIZE_RULE = "### A file over the hard limit is an auditable choice, not silent drift"
_NEXT_RULE = "### Re-deriving what another layer owns is an auditable choice, not a default"


def _part_c() -> str:
    """The '## Part C' verification section — to end of file."""
    text = _SKILL.read_text(encoding="utf-8")
    start = text.find("## Part C")
    assert start != -1, "code-quality must have a '## Part C' verification section"
    return text[start:]


def _part_c_headings() -> list[str]:
    """Every ``### `` heading inside Part C, in file order.

    Derived from the file rather than named inline, so the position assertion
    dogfoods the rule it pins: a future insertion elsewhere in Part C cannot
    silently invalidate a hardcoded neighbour pair.
    """
    return [
        line.rstrip()
        for line in _part_c().splitlines()
        if line.startswith("### ")
    ]


def _section() -> str:
    """The new subsection's own span — its heading to the next ``### ``.

    Scoped deliberately: an unscoped whole-document search passes on phrasing
    that already exists in a sibling subsection, which would make this guard
    green before the subsection it pins was ever written.
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


def _paragraphs() -> list[str]:
    """The subsection's paragraphs, blank-line separated, in file order."""
    return [block.strip() for block in _section().split("\n\n") if block.strip()]


def _predicate_paragraph() -> str:
    """The span of the subsection that states the matching-predicate half.

    Selected by content rather than by index: ``_paragraphs()[-1]`` is the
    hardcoded-position brittleness the placement test above was deliberately
    rewritten to avoid, and a later insertion would silently redirect the span.

    The selector dogfoods the rule it pins — ``"predicate" in block`` is itself a
    hand-written predicate over a derived subject set. It is legitimate under the
    rule's own escape hatch because it carries completeness assertions in both
    directions: non-empty here, and proper-subset in
    :func:`test_predicate_paragraph_is_a_proper_subset`. Move the paragraph or
    drop the word and the guard fails loudly naming the reason, rather than
    silently checking nothing.
    """
    hits = [block for block in _paragraphs() if "predicate" in block]
    assert hits, (
        "no paragraph of the guard subsection mentions the matching predicate — "
        "the rule's second half is missing. A derived subject set proves only "
        "that the guard looked at every unit; what counts as a hit is a second "
        "place to narrow, and the subsection must say so"
    )
    return "\n\n".join(hits)


def test_rule_requires_deriving_the_subject_set() -> None:
    """The obligation and the prohibition are both stated (AC-1)."""
    section = _section()

    assert "derive" in section or "compute" in section, (
        "the rule must state that the guard *derives* (or computes) its subject "
        "set, not merely that a hand-written list is undesirable"
    )
    assert "git ls-files" in section, (
        "the rule must name `git ls-files` as a concrete deriving artifact — the "
        "acceptance criterion names it, and it is the one example universal to "
        "every consuming repo whatever its stack"
    )
    assert "registry" in section and "constants" in section, (
        "the rule must name the other two deriving artifacts (a registry of "
        "registered units, a constants module) so the obligation reads as a "
        "general shape rather than a single trick"
    )
    assert "literal list" in section, (
        "the rule must prohibit the literal list in the test body by name — that "
        "is the construct being banned, and naming it is what makes the rule "
        "checkable at review"
    )


def test_rule_states_the_failure_mode_and_the_escape_hatch() -> None:
    """Why a hand-list is worse than an incomplete one, and the way out (AC-2)."""
    section = _section()

    assert "narrow" in section, (
        "the rule must state that a hand-written list silently *narrows* to the "
        "surface that existed the day it was written — the failure mode, without "
        "which the rule reads as mere style preference"
    )
    assert "green" in section, (
        "the rule must state that the guard then reports *green* for everything "
        "added since — a guard that passes because it stopped looking is the "
        "specific harm here"
    )
    assert "completeness" in section, (
        "the rule must give the escape hatch for a genuinely underivable set: "
        "the test asserts its own completeness against the deriving source"
    )
    assert "diverge" in section, (
        "the escape hatch must state that the test *fails when the two diverge* "
        "— an unenforced completeness claim is the same silent narrowing again"
    )
    assert "reject" in section, (
        "the rule must bind at review with an explicit rejection clause, matching "
        "its two neighbouring Part C subsections; without it the rule binds only "
        "on the author's own discipline"
    )


def test_rule_sits_immediately_after_the_size_rule() -> None:
    """Placement inside Part C, derived from the file's own heading order (AC-3)."""
    headings = _part_c_headings()

    # Anti-vacuity: assert each anchor exists on its own, with a distinct
    # message. Without this, an upstream heading rename would fail the ordinal
    # lookup for a reason unrelated to this rule and mislead the next reader.
    assert _HEADING in headings, (
        f"{_HEADING!r} must be a '### ' subsection of Part C — verification is "
        "the right part, because this rule is about what a green run is "
        "evidence *of*"
    )
    assert _SIZE_RULE in headings, (
        f"the anchor subsection {_SIZE_RULE!r} is missing from Part C — this "
        "test's placement assertion is meaningless without it"
    )
    assert _NEXT_RULE in headings, (
        f"the successor subsection {_NEXT_RULE!r} is missing from Part C — this "
        "test's placement assertion is meaningless without it"
    )

    position = headings.index(_HEADING)
    assert position == headings.index(_SIZE_RULE) + 1, (
        "the rule must sit immediately after the file-size subsection: it "
        "generalises that rule's shape — a mechanical presence check plus a "
        "non-mechanizable escape hatch — to every structural guard"
    )
    assert headings[position + 1] == _NEXT_RULE, (
        "the rule must sit immediately before the re-derivation subsection, so "
        "the three auditable-choice rules stay contiguous"
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


def test_rule_extends_to_the_matching_predicate() -> None:
    """The predicate is tied to the subject set, not stated free-floating (AC-1)."""
    paragraph = _predicate_paragraph()

    assert "matching predicate" in paragraph, (
        "the rule must name the *matching predicate* — what counts as a hit — as "
        "the thing it governs; without that name a reviewer cannot tell which "
        "half of a guard the obligation lands on"
    )
    assert "subject set" in paragraph, (
        "the rule must tie the predicate back to the subject set it extends. "
        "Stated on its own it reads as a second, unrelated rule; stated as the "
        "same rule one level in, it inherits the reasoning already written above"
    )


def test_predicate_literals_are_derived_or_justified() -> None:
    """Two exits for a literal in a predicate, and no third (AC-2)."""
    paragraph = _predicate_paragraph()

    assert "literal" in paragraph, (
        "the rule must name the *literal* in the predicate as the construct "
        "under obligation — the same construct the paragraph above bans in the "
        "subject set, which is what makes this one rule rather than two"
    )
    for kind in ("variable name", "separator", "exempt"):
        assert kind in paragraph, (
            f"the rule must name {kind!r} among the kinds of literal a predicate "
            "hides. Enumerating them is what makes the rule checkable: a "
            "reviewer looking for 'a literal' finds nothing, one looking for an "
            "exempted shape or an assumed separator finds the defect"
        )
    assert "derived" in paragraph and "justified" in paragraph, (
        "the rule must give both exits — derive the literal from the same "
        "defining artifact, or justify it — because a prohibition with no exit "
        "is unenforceable where the predicate genuinely cannot be derived"
    )
    assert "full" in paragraph, (
        "the justification must be measured against the rule's *full* surface. "
        "Justified against the surface the author happened to look at is the "
        "same silent narrowing the rule exists to stop"
    )


def test_predicate_rule_binds_the_reviewer() -> None:
    """The rejection clause, and what the predicate is narrower *than* (AC-3)."""
    paragraph = _predicate_paragraph()

    assert "reject" in paragraph, (
        "the rule must bind at review with an explicit rejection clause, matching "
        "its sibling Part C subsections; without it the rule binds only on the "
        "author's own discipline, which is exactly what already failed"
    )
    assert "narrower" in paragraph, (
        "the rejection must name the test the reviewer applies — a predicate "
        "*narrower* than the rule it claims to enforce. 'Reject a bad predicate' "
        "is not a bar anyone can apply"
    )


def test_predicate_rule_names_the_tell() -> None:
    """The failure mode is recognisable, not merely prohibited (AC-4)."""
    paragraph = _predicate_paragraph()

    for token in ("green", "fraction", "invisible", "output"):
        assert token in paragraph, (
            f"the rule must name {token!r} as part of the tell — a green run over "
            "a shrinking fraction of the surface, invisible from the test's own "
            "output. A rule that only prohibits leaves the reader unable to "
            "recognise the defect in front of them, and this one has no symptom"
        )


def test_predicate_paragraph_is_a_proper_subset() -> None:
    """The span is a genuine selection, not the whole subsection (AC-5).

    Anti-vacuity for every assertion above: if the selector ever returned the
    entire subsection, each of them would pass on the two original paragraphs,
    which already carry ``green``, ``narrow``, ``literal`` and ``reject``. That
    is #220's trap recursed one level, and it is the single most likely way to
    get this guard wrong.
    """
    selected = [block for block in _paragraphs() if "predicate" in block]
    total = _paragraphs()

    assert selected, (
        "the predicate paragraph must exist — see _predicate_paragraph()"
    )
    assert len(selected) < len(total), (
        f"the predicate span covers all {len(total)} paragraphs of the "
        "subsection, so every content assertion above is satisfiable by the "
        "subject-set prose that was already there. The predicate rule must be "
        "an addition standing beside the original, not a rewrite of it"
    )
