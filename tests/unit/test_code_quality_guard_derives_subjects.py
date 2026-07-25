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
