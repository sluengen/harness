"""CODE-1 / CODE-INSIGHT-1 (2026-06-15 code assessment) — the 500-line size rule
is enforced on production source, not just asserted in the skill text.

``code-quality`` Part C requires any file over the 500-line hard limit to carry,
at its top, a language-native ``size: <reason>`` justification comment (or
reference an open tracking ticket); the reviewer **rejects** an over-limit file
with neither. But the existing guard ``test_code_quality_size_justification``
only checks that the *skill* states the rule — nothing scans the source. So
``harness/launcher.py`` grew to 525 lines during CAL-675 with no justification
and slipped through undetected: the rule was enforced by human attention alone,
which is exactly the silent drift it was written to prevent (CAL-666).

This guard turns the rule into a suite gate. It walks the git-tracked ``*.py``
under every source tree and fails for any file past *that tree's* ceiling which
does not carry a ``size:`` justification comment — the same text-structural form
as ``test_retired_spec_cites`` (CAL-633) and ``test_guidance_footprint``
(CAL-648): a recurring manual find→fix cycle turned into one structural check.

Scope and discriminator:

* **Every tracked Python tree, at a ceiling per tree** (``_TREE_CEILINGS``).
  ``scripts/`` and ``templates/`` answer to the 500-line hard
  limit; ``tests/`` answers to Part B's declarative ceiling (1.5x, so 750),
  because a test module's length is substantially *case enumeration* against
  one surface's acceptance criteria rather than accreted logic. A raised
  ceiling, not an exemption: it keeps firing when a test module runs away,
  where an exemption never fires again.

  This scope is #275. The guard originally covered ``harness/`` only and
  deferred ``tests/`` in this very docstring — "a separate decision, not assumed
  here". That decision was never taken, and by the time the 2026-08-01 pm
  assessment revisited it the test tree held **14** files past the declarative
  ceiling with no recorded size decision, while ``scripts/`` had never been in
  scope at all. The deferral outlived its own reasoning, which is why *which
  trees exist* is now derived from the git index rather than left to prose.
* **Keys on the explicit ``size:`` marker**, the concrete form the rule names —
  not on an incidental ticket cite. ``launcher.py`` already references CAL-579
  as *design provenance*, which is not a size decision and must not satisfy the
  guard. The prose's "or a ticket" alternative stays a reviewer-judgment path;
  the structural gate enforces the strong, unambiguous form so no incidental
  cite anywhere in a long file produces a false green.
* **Requires a reason.** ``# size:`` with nothing after it does not justify
  anything, so the marker must be followed by non-whitespace.

Acceptance criteria — the original guard (2026-06-15 assessment, CODE-1):

* **AC-1** — a source file over its tree's ceiling with no ``size:``
  justification fails the guard. Proven by
  :func:`test_over_limit_source_files_carry_a_size_justification` (it failed on
  ``launcher.py`` when the guard covered ``harness/`` only, and failed again on
  all 14 over-ceiling ``tests/`` modules before #275's markers landed; the
  marker regex contract below pins what counts as a justification so an
  incidental cite cannot satisfy it).
* **AC-2** — every over-ceiling file carries a ``# size:`` justification, so the
  guard passes on the current tree. (``launcher.py``, the file that motivated
  this guard, was removed in CAL-712 with the Hermes/launcher scaffolding.)

Acceptance criteria — the #275 scope widening:

* **AC-3** — no tracked Python tree is a blind spot: every top-level directory
  git tracks a ``*.py`` under answers to some ceiling. Proven by
  :func:`test_every_tracked_python_tree_has_a_ceiling`, which derives the tree
  set from the index rather than listing it (#219 / #220 — a hand-written set of
  guarded subjects falls behind silently, and the guard then reads green because
  it never checked).
* **AC-4** — ``tests/`` is in scope *and* at the raised ceiling, not silently
  subjected to the production limit. Proven by
  :func:`test_tests_tree_answers_to_the_declarative_ceiling`.
* **AC-5** — the declarative ceiling is derived from the hard limit (1.5x), not
  a value typed once, so moving one moves both. Proven by
  :func:`test_declarative_ceiling_is_derived_from_the_hard_limit`.
* **AC-6** — this docstring's own scope prose cannot go stale about which trees
  are guarded. Proven by
  :func:`test_docstring_scope_prose_names_every_guarded_tree`, which derives the
  expected mentions from ``_TREE_CEILINGS``. Added because #275's first review
  caught this file still claiming "Production source only" *after* the widening
  — the same stale-deferral defect one section down, and the original deferral
  survived over a year precisely because nothing measured it.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

from tests._gitutil import tracked_files_under

# ``tests/unit/test_*.py`` → ``parents[2]`` is the repo (or worktree) root.
_REPO_ROOT = Path(__file__).resolve().parents[2]

# Part B / Part C of ``code-quality``: the hard limit for a module/file.
_HARD_LIMIT = 500

# Part B's raised ceiling for files that are long *because* they are declarative
# — "their length is field lists, not logic" — defaulting to 1.5x the hard limit.
# Derived from ``_HARD_LIMIT`` rather than typed, so the two cannot drift apart.
_DECLARATIVE_CEILING = _HARD_LIMIT * 3 // 2

#: Every tracked Python tree, and the ceiling it answers to (#275).
#:
#: ``tests/`` sits at the declarative ceiling, not the hard limit: a test
#: module's length is substantially *case enumeration* against one surface's
#: acceptance criteria, which is Part B's declarative argument rather than
#: accreted logic. It is still bounded, and still owes a ``# size:`` marker past
#: the ceiling — a raised ceiling keeps firing on runaway growth where an
#: exemption never fires again.
#:
#: ``scripts/`` and ``templates/`` answer to the hard limit like ``harness/``:
#: build-time tooling and generators are ordinary logic.
_TREE_CEILINGS = {
    "scripts": _HARD_LIMIT,
    "templates": _HARD_LIMIT,
    "tests": _DECLARATIVE_CEILING,
}

# A size justification is a Python comment containing the ``size:`` marker
# followed by a non-empty reason. Harness source is pure Python, so the marker is
# a ``#`` comment. The pattern deliberately does NOT accept a bare ticket cite:
# an incidental ``CAL-579`` provenance reference is not a size decision, and an
# empty ``# size:`` records no reason.
_SIZE_JUSTIFICATION = re.compile(r"#.*\bsize:\s*\S")


def _line_count(path: Path) -> int:
    return len(path.read_text(encoding="utf-8").splitlines())


def _has_size_justification(path: Path) -> bool:
    return bool(_SIZE_JUSTIFICATION.search(path.read_text(encoding="utf-8")))


# The marker contract, pinned by example. ``match`` cases are real size
# justifications the guard MUST accept; ``no-match`` cases are comments (and
# code) it must NOT accept as a justification — most importantly an incidental
# ticket cite, which is what would otherwise let ``launcher.py`` pass untouched.
_MARKER_MATCH = [
    "# size: cohesive launcher concern, kept together",
    "    # size: single concern — split would scatter the gate",
    "x = 1  # size: inline trailing form is fine",
]
_MARKER_NO_MATCH = [
    "# see CAL-579 for the launch decision",  # incidental ticket cite, not a size decision
    "# resize the ring buffer before write",  # 'size' substring, no marker colon
    "size = len(items)",  # code, not a comment marker
    "# size:",  # marker with no reason recorded
    "# size: ",  # marker, trailing whitespace only — still no reason
]


@pytest.mark.parametrize("sample", _MARKER_MATCH)
def test_size_marker_regex_accepts_real_justifications(sample: str) -> None:
    assert _SIZE_JUSTIFICATION.search(sample), f"{sample!r} should count as a size justification"


@pytest.mark.parametrize("sample", _MARKER_NO_MATCH)
def test_size_marker_regex_rejects_non_justifications(sample: str) -> None:
    assert not _SIZE_JUSTIFICATION.search(sample), f"{sample!r} must not count as a justification"


def _tracked_python_trees() -> set[str]:
    """The top-level directories git tracks any ``*.py`` under.

    Derived from the index, not listed (#219 / #220 — a hand-written set of
    guarded subjects silently falls behind the tree, and the guard reads green
    because it never checked rather than because nothing violated it). This is
    what :func:`test_every_tracked_python_tree_has_a_ceiling` compares
    ``_TREE_CEILINGS`` against.
    """
    out = subprocess.run(
        ["git", "ls-files", "*.py"],
        cwd=_REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.split()
    return {rel.split("/", 1)[0] for rel in out if "/" in rel}


def _offenders() -> list[tuple[Path, int, int]]:
    """Every tracked ``.py`` past its tree's ceiling with no ``size:`` marker."""
    found: list[tuple[Path, int, int]] = []
    for tree, ceiling in sorted(_TREE_CEILINGS.items()):
        for path in sorted(tracked_files_under(tree)):
            if path.suffix != ".py":
                continue
            lines = _line_count(path)
            if lines > ceiling and not _has_size_justification(path):
                found.append((path, lines, ceiling))
    return found


def test_every_tracked_python_tree_has_a_ceiling() -> None:
    """No tracked Python tree is a blind spot (AC-3).

    The guard scoped to ``harness/`` alone for over a year and deferred
    ``tests/`` in prose (#275); by the time the deferral was revisited the test
    tree held 14 files past the declarative ceiling, none carrying a recorded
    decision, and ``scripts/`` had never been in scope at all. A ceiling per
    tree is a config choice; *which trees exist* is not, so it is derived.
    """
    missing = _tracked_python_trees() - set(_TREE_CEILINGS)
    assert not missing, (
        "these tracked Python trees answer to no ceiling, so an over-limit file "
        "in them would never be caught — add each to `_TREE_CEILINGS` with the "
        f"ceiling it should answer to: {sorted(missing)}"
    )


def test_over_limit_source_files_carry_a_size_justification() -> None:
    """Every over-ceiling tracked source file records a size decision (AC-1, AC-2)."""
    offenders = _offenders()
    assert not offenders, (
        "these source files are over their tree's line ceiling with no "
        "`# size: <reason>` justification (code-quality Part C) — add a one-line "
        "`# size:` comment recording why the file may exceed the ceiling, or "
        "split it:\n"
        + "\n".join(
            f"  - {p.relative_to(_REPO_ROOT)}: {lines} lines (ceiling {ceiling})"
            for p, lines, ceiling in offenders
        )
    )


def test_declarative_ceiling_is_derived_from_the_hard_limit() -> None:
    """The raised ceiling is 1.5x the hard limit, not a number someone typed (AC-5).

    ``code-quality`` Part B states the declarative ceiling as a *multiple* of
    the hard limit. Pinning the relationship rather than the value means moving
    the hard limit moves both, which is the property #234 asked for when it
    required the declarative ceiling to be a configured constant rather than
    prose.
    """
    assert _DECLARATIVE_CEILING == _HARD_LIMIT * 3 // 2 == 750


def test_tests_tree_answers_to_the_declarative_ceiling() -> None:
    """``tests/`` is scanned, and at the raised ceiling rather than the hard one (AC-4).

    Pins the two halves of #275's decision separately from the green/red state
    of the tree: that the test tree is in scope at all, and that being in scope
    does not silently subject it to the 500-line production limit.
    """
    assert _TREE_CEILINGS["tests"] == _DECLARATIVE_CEILING
    assert _TREE_CEILINGS["tests"] > _TREE_CEILINGS["scripts"]


def test_docstring_scope_prose_names_every_guarded_tree() -> None:
    """This module's own docstring cannot go stale about its scope (AC-6).

    The #275 review caught exactly this: the scope widened while the docstring
    above still read "Production source only (``harness/``)" and "``tests/`` is
    left to reviewer judgment for now". That is the same stale-deferral defect
    the ticket exists to close, moved one section down in the same file — and
    the original deferral survived over a year precisely because nothing
    measured it.

    So the prose is measured, and derived: every tree in ``_TREE_CEILINGS`` must
    be named in the docstring. Adding a tree without describing it fails here.
    """
    doc = __doc__ or ""
    unmentioned = [tree for tree in _TREE_CEILINGS if f"``{tree}/``" not in doc]
    assert not unmentioned, (
        "this module's docstring must describe every tree it guards, so its "
        "scope prose cannot drift from `_TREE_CEILINGS` the way the original "
        f"`tests/` deferral did (#275); unmentioned: {sorted(unmentioned)}"
    )
