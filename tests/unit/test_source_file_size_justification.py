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

This guard turns the rule into a suite gate. It walks every git-tracked *source*
file under every source tree and fails for any file past *that tree's* ceiling
which does not carry a ``size:`` justification comment — the same text-structural form
as ``test_retired_spec_cites`` (CAL-633) and ``test_guidance_footprint``
(CAL-648): a recurring manual find→fix cycle turned into one structural check.

Scope and discriminator:

* **Every tracked source tree, at a ceiling per tree** (``_TREE_CEILINGS``).
  ``scripts/``, ``templates/`` and ``hooks/`` answer to the 500-line hard
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
* **Every tracked source language, classified rather than assumed**
  (``_SOURCE_COMMENT_PREFIXES`` / ``_NON_SOURCE_SUFFIXES``). This is #444. The
  tree derivation above ran over ``git ls-files "*.py"``, so it removed the
  blind spot for *which trees exist* and reproduced it one level down for
  *which languages exist*: a tree holding no Python could not be reported by
  the very check written to prove no tree is unguarded. ``hooks/`` was that
  tree — the repo's only mechanical enforcement, installed into consuming
  repos, and deliberately un-factored (#436 declined a shared ``hooks/lib/``)
  so its files grow rather than split. Three of them sat past the hard limit
  with no recorded decision and nothing had ever asked them for one.

  So the language set is derived the same way the tree set is: every suffix git
  tracks is classified as source (mapped to the line-comment prefix its marker
  takes) or as non-source, and an unclassified suffix fails
  :func:`test_every_tracked_suffix_is_classified`. Adding the first ``.ts``
  file goes red there; classifying it as source then forces its tree into
  ``_TREE_CEILINGS``. Two reds, neither of them silent.

  A file with **no suffix** is classified by shebang against the file itself,
  not exempted: ``bin/harness`` was exactly such a script until #435, and a
  blanket exemption for the empty suffix would re-open this hole for the next
  one. (A source file at the repo *root* answers to no tree and so is still
  unguarded — the derivation drops paths with no directory component. The
  2026-08-01 pm assessment measured that gap, found no instance, and declined
  to file it; this change leaves it where it found it.)
* **Keys on the explicit ``size:`` marker**, the concrete form the rule names —
  not on an incidental ticket cite. ``launcher.py`` already references CAL-579
  as *design provenance*, which is not a size decision and must not satisfy the
  guard. The prose's "or a ticket" alternative stays a reviewer-judgment path;
  the structural gate enforces the strong, unambiguous form so no incidental
  cite anywhere in a long file produces a false green.
* **Requires a reason, on the marker's own line.** ``# size:`` with nothing
  after it does not justify anything, so the marker must be followed by
  non-whitespace *before the line ends*. The line bound is load-bearing rather
  than tidy: the pattern is searched over the whole file, so a whitespace class
  that crossed the newline would let the next line's first character stand in
  for the reason — and every real file supplies a next line, which makes the
  empty-marker rule unfailable everywhere except in a single-line sample.

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

* **AC-3** — no tracked source tree is a blind spot: every top-level directory
  git tracks a source file under answers to some ceiling. Proven by
  :func:`test_every_tracked_source_tree_has_a_ceiling`, which derives the tree
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

Acceptance criteria — the #444 language widening:

* **AC-7** — a tracked ``hooks/*.js`` file past the hard limit with no
  justification is reported. Proven on the real tree by
  :func:`test_over_limit_source_files_carry_a_size_justification` (it failed on
  all three over-limit hooks before their markers landed) and on synthetic
  input by :func:`test_over_ceiling_javascript_without_a_marker_is_an_offender`.
* **AC-8** — the marker is recognised in its language-native form and only
  there: ``// size:`` justifies a ``.js`` file and ``# size:`` a ``.py`` or
  ``.sh`` one, while each form leaves the other language's file unjustified.
  Proven by :func:`test_size_marker_regex_accepts_real_justifications`,
  :func:`test_size_marker_regex_rejects_non_justifications` and
  :func:`test_marker_in_the_wrong_comment_syntax_does_not_justify`. The
  empty-marker half is proven against a *file* rather than a line by
  :func:`test_an_empty_marker_is_not_justified_by_the_next_line`.
* **AC-9** — no tracked suffix is a blind spot: every suffix git tracks is
  classified source or non-source, and an unclassified one fails. Proven by
  :func:`test_every_tracked_suffix_is_classified` for the tree as it stands and
  by :func:`test_an_unclassified_suffix_is_reported` for the reporting
  direction, with the empty-suffix derivation proven by
  :func:`test_extensionless_file_is_source_only_with_a_shebang`.
* **AC-10** — ``hooks/`` is in scope at the hard limit, not the raised one.
  Proven by :func:`test_hooks_tree_answers_to_the_hard_limit`, and the walk that
  enforces it is anchored to a language other than Python by
  :func:`test_the_tree_walk_reaches_javascript_not_only_python`.

The three tests named above as second provers were added at review, from a
mutation table: a shipped marker cut down to a bare ``// size:`` left the guard
green over a 723-line file, and re-narrowing the walk or neutering the suffix
report changed nothing any assertion read. Each closes a direction the criteria
claimed and nothing measured.
"""

from __future__ import annotations

import re
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
#: ``scripts/``, ``templates/`` and ``hooks/`` answer to the hard limit like
#: ``harness/``: build-time tooling, generators and hooks are ordinary logic.
_TREE_CEILINGS = {
    "hooks": _HARD_LIMIT,
    "scripts": _HARD_LIMIT,
    "templates": _HARD_LIMIT,
    "tests": _DECLARATIVE_CEILING,
}

#: Every tracked source suffix, and the line-comment prefix a size marker takes
#: in it. The prefixes are the ones ``code-quality``'s rule names: "``# size:
#: <reason>`` in Python or shell, ``// size: <reason>`` in JS/TS/C".
#:
#: The block form (``/* size: */``, which the same sentence names for CSS) is
#: deliberately not accepted: the repo tracks no language whose only comment
#: form is a block, so accepting it would widen the predicate past any file it
#: could match. Adding such a file lands its suffix in
#: :func:`_unclassified_suffixes` and goes red before it can be over-limit and
#: unseen — which is the property that makes this literal safe to hold.
_SOURCE_COMMENT_PREFIXES = {
    ".py": "#",
    ".sh": "#",
    ".js": "//",
}

#: Every tracked suffix that carries no size decision because it is not source.
#: Prose, data and assets: their length is content, not accreted logic, and the
#: rule they would answer to does not exist. Listed rather than assumed so that
#: :func:`test_every_tracked_suffix_is_classified` can tell "decided not to
#: guard this" apart from "never looked at this".
_NON_SOURCE_SUFFIXES = {
    ".html",
    ".json",
    ".lock",
    ".md",
    ".png",
    ".toml",
    ".yaml",
    ".yml",
}


def _size_justification(comment_prefix: str) -> re.Pattern[str]:
    """The size-marker pattern for a language whose line comment is ``prefix``.

    A justification is a comment containing the ``size:`` marker followed by a
    non-empty reason. The pattern deliberately does NOT accept a bare ticket
    cite: an incidental ``CAL-579`` provenance reference is not a size decision,
    and an empty ``# size:`` records no reason.

    Built from the language's own prefix rather than accepting every prefix
    everywhere, so a ``// size:`` line in a Python file — where it is not a
    comment at all — cannot justify anything.

    The run between the marker and its reason is ``[ \\t]``, not ``\\s``. The
    pattern is searched over the *whole file*, and ``\\s`` matches a newline, so
    the wider class let the following line's first character satisfy the reason
    — which every file has. That made the empty-marker rule pass on every real
    file while still failing the single-line samples in ``_MARKER_NO_MATCH``:
    green in the suite, unfailable in the tree.
    """
    return re.compile(rf"{re.escape(comment_prefix)}.*\bsize:[ \t]*\S")


def _has_shebang(path: Path) -> bool:
    """Does this path name a regular file whose first two bytes are ``#!``?

    ``is_file`` first, because ``git ls-files`` lists symlinks: the 21 tracked
    extensionless paths are all links into ``.claude/`` and ``.codex/`` that
    resolve to directories, and reading one raises rather than returning bytes.
    """
    if not path.is_file():
        return False
    with path.open("rb") as handle:
        return handle.readline(2) == b"#!"


def _comment_prefix(path: Path) -> str | None:
    """The comment prefix a size marker takes in ``path``, or ``None``: not source.

    The one classifier. ``_offenders``, the tree derivation and the synthetic
    controls all route through it, so no test can prove a property of a path
    production never takes.

    An unclassified suffix answers ``None`` — invisible here, and loud in
    :func:`test_every_tracked_suffix_is_classified`, which is the check that
    exists to catch it.

    The shebang branch answers ``#``: it assumes an interpreter whose comment is
    ``#`` (``sh``, ``bash``, ``python``), which every extensionless script this
    repo has tracked was. The error is one-directional — a ``#!/usr/bin/env
    node`` script would be asked for a ``# size:`` marker it cannot write, and
    would be *reported*, not silently skipped.
    """
    suffix = path.suffix
    if suffix in _SOURCE_COMMENT_PREFIXES:
        return _SOURCE_COMMENT_PREFIXES[suffix]
    if suffix == "":
        return "#" if _has_shebang(path) else None
    return None


def _line_count(path: Path) -> int:
    return len(path.read_text(encoding="utf-8").splitlines())


def _has_size_justification(path: Path, comment_prefix: str) -> bool:
    text = path.read_text(encoding="utf-8")
    return bool(_size_justification(comment_prefix).search(text))


def _offending(path: Path, ceiling: int) -> tuple[int, int] | None:
    """``(lines, ceiling)`` if ``path`` is over its ceiling and unjustified.

    The whole per-file rule in one place, so the synthetic controls exercise the
    same code the tree walk does rather than a re-statement of it.
    """
    prefix = _comment_prefix(path)
    if prefix is None:
        return None
    lines = _line_count(path)
    if lines > ceiling and not _has_size_justification(path, prefix):
        return (lines, ceiling)
    return None


# The marker contract, pinned by example, one language per case. ``match`` cases
# are real size justifications the guard MUST accept; ``no-match`` cases are
# comments (and code) it must NOT accept as a justification — most importantly
# an incidental ticket cite, which is what would otherwise let ``launcher.py``
# pass untouched.
_MARKER_MATCH = [
    ("#", "# size: cohesive launcher concern, kept together"),
    ("#", "    # size: single concern — split would scatter the gate"),
    ("#", "x = 1  # size: inline trailing form is fine"),
    ("//", "// size: self-contained hook, no shared lib by decision"),
    ("//", "    // size: single concern — split would scatter the gate"),
    ("//", "const x = 1;  // size: inline trailing form is fine"),
]
_MARKER_NO_MATCH = [
    ("#", "# see CAL-579 for the launch decision"),  # incidental cite, not a size decision
    ("#", "# resize the ring buffer before write"),  # 'size' substring, no marker colon
    ("#", "size = len(items)"),  # code, not a comment marker
    ("#", "# size:"),  # marker with no reason recorded
    ("#", "# size: "),  # marker, trailing whitespace only — still no reason
    ("//", "// see CAL-579 for the launch decision"),
    ("//", "// resize the ring buffer before write"),
    ("//", "const size = items.length;"),
    ("//", "// size:"),
    ("//", "// size: "),
]

# The cross-language pairs: a marker written in the *other* language's comment
# syntax. In a Python file ``// size: …`` is a syntax error, not a decision; in
# a JavaScript file ``# size: …`` is likewise not a comment. Accepting either
# would mean the guard keys on the word rather than on a real comment.
_MARKER_WRONG_SYNTAX = [
    ("#", "// size: JS comment form in a Python file"),
    ("//", "# size: Python comment form in a JavaScript file"),
]


@pytest.mark.parametrize(("prefix", "sample"), _MARKER_MATCH)
def test_size_marker_regex_accepts_real_justifications(prefix: str, sample: str) -> None:
    """Both language-native marker forms count as justifications (AC-8)."""
    assert _size_justification(prefix).search(sample), (
        f"{sample!r} should count as a size justification in a {prefix!r}-comment language"
    )


@pytest.mark.parametrize(("prefix", "sample"), _MARKER_NO_MATCH)
def test_size_marker_regex_rejects_non_justifications(prefix: str, sample: str) -> None:
    assert not _size_justification(prefix).search(sample), (
        f"{sample!r} must not count as a justification"
    )


@pytest.mark.parametrize(("prefix", "sample"), _MARKER_WRONG_SYNTAX)
def test_marker_in_the_wrong_comment_syntax_does_not_justify(prefix: str, sample: str) -> None:
    """A marker in another language's comment syntax justifies nothing (AC-8)."""
    assert not _size_justification(prefix).search(sample), (
        f"{sample!r} is not a comment in a {prefix!r}-comment language, so it "
        "records no size decision there"
    )


def _tracked_files() -> set[Path]:
    """Every file git tracks, absolute."""
    return tracked_files_under(".", repo_root=_REPO_ROOT)


def _unclassified_suffixes() -> set[str]:
    """Tracked suffixes that are neither classified source nor classified non-source.

    The empty suffix is absent by construction rather than by exemption: it is
    classified per-file in :func:`_comment_prefix`, by shebang.
    """
    known = set(_SOURCE_COMMENT_PREFIXES) | _NON_SOURCE_SUFFIXES | {""}
    return {path.suffix for path in _tracked_files()} - known


def _tracked_source_trees() -> set[str]:
    """The top-level directories git tracks any *source* file under.

    Derived from the index, not listed (#219 / #220 — a hand-written set of
    guarded subjects silently falls behind the tree, and the guard reads green
    because it never checked rather than because nothing violated it). Derived
    over :func:`_comment_prefix` rather than over ``*.py`` (#444), so the answer
    widens with the language set instead of being fixed to one language. This is
    what :func:`test_every_tracked_source_tree_has_a_ceiling` compares
    ``_TREE_CEILINGS`` against.
    """
    trees: set[str] = set()
    for path in _tracked_files():
        if _comment_prefix(path) is None:
            continue
        parts = path.relative_to(_REPO_ROOT).parts
        if len(parts) > 1:
            trees.add(parts[0])
    return trees


def _offenders(ceilings: dict[str, int] | None = None) -> list[tuple[Path, int, int]]:
    """Every tracked source file past its tree's ceiling with no ``size:`` marker.

    ``ceilings`` defaults to ``_TREE_CEILINGS``. A test overrides it to observe
    which languages the walk *reaches*, which the real-tree verdict cannot show
    once every over-ceiling file carries a marker: from then on the walk reports
    nothing whether or not it still reads anything but Python.
    """
    found: list[tuple[Path, int, int]] = []
    for tree, ceiling in sorted((_TREE_CEILINGS if ceilings is None else ceilings).items()):
        for path in sorted(tracked_files_under(tree, repo_root=_REPO_ROOT)):
            offence = _offending(path, ceiling)
            if offence is not None:
                found.append((path, *offence))
    return found


def test_every_tracked_suffix_is_classified() -> None:
    """No tracked suffix is a blind spot (AC-9).

    The check that makes :func:`test_every_tracked_source_tree_has_a_ceiling`
    mean what it says. That test derived its trees from ``git ls-files "*.py"``
    until #444, so it could not report a tree holding no Python — the blind spot
    it exists to close, reproduced one level down in the language set. Deciding
    a suffix is not source is fine; never being asked is not.
    """
    unclassified = _unclassified_suffixes()
    assert not unclassified, (
        "these tracked file suffixes are classified neither as source (with the "
        "comment prefix its `size:` marker takes, in `_SOURCE_COMMENT_PREFIXES`) "
        "nor as non-source (`_NON_SOURCE_SUFFIXES`), so a file over the ceiling "
        f"in one of them would never be caught: {sorted(unclassified)}"
    )


def test_an_unclassified_suffix_is_reported(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The classification check can actually report an offender (AC-9).

    On a tree where every suffix is already classified the check's output is
    empty, so its passing says nothing about whether it can report — the same
    vacuity #444 opened on, one level up. Measured at review: neutering
    :func:`_unclassified_suffixes` to return the empty set killed no test.

    So the production function is fed a tracked set the tree never supplies. The
    substitution is its *input*; the classification under test is still the
    shipped one.
    """
    monkeypatch.setitem(
        globals(),
        "_tracked_files",
        lambda: {tmp_path / "widget.ts", tmp_path / "widget.py", tmp_path / "notes.md"},
    )
    assert _unclassified_suffixes() == {".ts"}


def test_every_tracked_source_tree_has_a_ceiling() -> None:
    """No tracked source tree is a blind spot (AC-3).

    The guard scoped to ``harness/`` alone for over a year and deferred
    ``tests/`` in prose (#275); by the time the deferral was revisited the test
    tree held 14 files past the declarative ceiling, none carrying a recorded
    decision, and ``scripts/`` had never been in scope at all. A ceiling per
    tree is a config choice; *which trees exist* is not, so it is derived.

    Derived over every classified source language since #444, when this same
    test read green over a ``hooks/`` tree holding three over-limit files,
    because its derivation could only see Python.
    """
    missing = _tracked_source_trees() - set(_TREE_CEILINGS)
    assert not missing, (
        "these tracked source trees answer to no ceiling, so an over-limit file "
        "in them would never be caught — add each to `_TREE_CEILINGS` with the "
        f"ceiling it should answer to: {sorted(missing)}"
    )


def test_the_tree_derivation_sees_a_tree_holding_no_python() -> None:
    """The derivation widened, not just the ceiling table (AC-3).

    Without this, narrowing :func:`_tracked_source_trees` back to ``*.py``
    passes every other test in this module: ``_TREE_CEILINGS`` already names
    ``hooks``, so the blind-spot check subtracts to the empty set either way and
    reports green over a derivation that stopped looking. The observable that
    tells the two apart is a tree the derivation can only see through a language
    other than Python — which is what ``hooks/`` is.

    If ``hooks/`` ever holds Python, this test fails rather than silently
    weakening, and the fix is to point it at whatever tree carries that property
    then.
    """
    hook_sources = tracked_files_under("hooks", repo_root=_REPO_ROOT)
    assert hook_sources, "expected a tracked `hooks/` tree"
    assert not [p for p in hook_sources if p.suffix == ".py"], (
        "`hooks/` no longer holds zero Python, so it can no longer stand for "
        "the property this test measures — point it at a tree that does"
    )
    assert "hooks" in _tracked_source_trees()


def test_over_limit_source_files_carry_a_size_justification() -> None:
    """Every over-ceiling tracked source file records a size decision (AC-1, AC-2, AC-7)."""
    offenders = _offenders()
    assert not offenders, (
        "these source files are over their tree's line ceiling with no "
        "`size: <reason>` justification (code-quality Part C) — add a one-line "
        "`size:` comment in the file's own comment syntax (`#` in Python or "
        "shell, `//` in JavaScript) recording why the file may exceed the "
        "ceiling, or split it:\n"
        + "\n".join(
            f"  - {p.relative_to(_REPO_ROOT)}: {lines} lines (ceiling {ceiling})"
            for p, lines, ceiling in offenders
        )
    )


def test_the_tree_walk_reaches_javascript_not_only_python() -> None:
    """The walk's language coverage is anchored, not merely currently green (AC-7).

    :func:`_tracked_source_trees` has such an anchor above; the walk that
    enforces the ceilings had none. Once every over-ceiling hook carries a
    marker, re-adding a ``*.py`` filter to :func:`_offenders` changes nothing
    any assertion reads — measured at review, that mutation survived while the
    walk's behaviour demonstrably changed. Driving the walk at a ceiling every
    file exceeds makes the languages it reaches observable again.
    """
    unmarked_js = [
        path
        for path in tracked_files_under("hooks", repo_root=_REPO_ROOT)
        if path.suffix == ".js" and not _has_size_justification(path, "//")
    ]
    assert unmarked_js, (
        "every tracked hook now records a size decision, so none of them can "
        "stand for a file the walk must report — point this at another tracked "
        "source file in a language other than Python"
    )
    reported = _offenders({"hooks": 1})
    assert any(path.suffix == ".js" for path, _, _ in reported), (
        "the offender walk reported no JavaScript over a `hooks/` tree that is "
        "entirely JavaScript, so it has stopped reading anything but Python — "
        "the defect #444 closed, which the real-tree assertion above cannot see "
        f"on a green tree; reported: {sorted(p.name for p, _, _ in reported)}"
    )


def _over_ceiling_file(tmp_path: Path, name: str, *, marker: str | None = None) -> Path:
    """Write a ``name`` file one line past ``_HARD_LIMIT``, optionally carrying ``marker``.

    Synthetic input for the controls below, which call the same
    :func:`_offending` the tree walk calls — so what they prove is a property of
    the guard rather than of a restatement of it.
    """
    body = [marker] if marker else []
    body += [f"line {n}" for n in range(_HARD_LIMIT + 1 - len(body))]
    path = tmp_path / name
    path.write_text("\n".join(body) + "\n", encoding="utf-8")
    assert _line_count(path) == _HARD_LIMIT + 1
    return path


def test_over_ceiling_javascript_without_a_marker_is_an_offender(tmp_path: Path) -> None:
    """A ``.js`` file past the ceiling with no decision is caught (AC-7).

    The property #444 opened on: every over-ceiling ``hooks/*.js`` file was
    invisible to this guard, because ``_offenders`` skipped any path that was
    not ``.py``.
    """
    path = _over_ceiling_file(tmp_path, "hook.js")
    assert _offending(path, _HARD_LIMIT) == (_HARD_LIMIT + 1, _HARD_LIMIT)


def test_over_ceiling_javascript_with_a_marker_is_not_an_offender(tmp_path: Path) -> None:
    """A recorded ``// size:`` decision justifies an over-ceiling ``.js`` file (AC-8)."""
    path = _over_ceiling_file(tmp_path, "hook.js", marker="// size: cohesive, split would scatter")
    assert _offending(path, _HARD_LIMIT) is None


def test_javascript_marker_in_python_syntax_does_not_justify(tmp_path: Path) -> None:
    """``# size:`` is not a comment in JavaScript, so it justifies nothing there (AC-8).

    The whole-file half of :func:`test_marker_in_the_wrong_comment_syntax_does_not_justify`,
    through the production path: a guard that keyed on the word rather than on a
    real comment would read this file as justified.
    """
    path = _over_ceiling_file(tmp_path, "hook.js", marker="# size: python form in a JS file")
    assert _offending(path, _HARD_LIMIT) == (_HARD_LIMIT + 1, _HARD_LIMIT)


@pytest.mark.parametrize(("name", "marker"), [("hook.js", "// size:"), ("mod.py", "# size:")])
def test_an_empty_marker_is_not_justified_by_the_next_line(
    tmp_path: Path, name: str, marker: str
) -> None:
    """A marker's reason must sit on the marker's own line (AC-8).

    The whole-file half of the ``# size:``/``# size: `` cases in
    ``_MARKER_NO_MATCH``, and the half that was missing: those samples are
    single lines with nothing after them, and the pattern runs over an entire
    file. Found by mutation at review — cutting a shipped hook's marker down to
    a bare ``// size:`` left the guard green over a 723-line file, because the
    ``\\s*`` between marker and reason crossed the newline and the next comment
    line's ``/`` served as the reason. Every real file has a next line, so the
    rule was unfailable in the tree while every line-level control passed.
    """
    path = _over_ceiling_file(tmp_path, name, marker=marker)
    assert _offending(path, _HARD_LIMIT) == (_HARD_LIMIT + 1, _HARD_LIMIT)


def test_a_file_at_the_ceiling_is_not_an_offender(tmp_path: Path) -> None:
    """The ceiling is the limit, not the first offence — a file *at* it passes."""
    path = _over_ceiling_file(tmp_path, "hook.js")
    assert _offending(path, _HARD_LIMIT + 1) is None


def test_non_source_file_is_never_an_offender(tmp_path: Path) -> None:
    """A long prose file records no size decision because it answers to no limit."""
    path = _over_ceiling_file(tmp_path, "spec.md")
    assert _comment_prefix(path) is None
    assert _offending(path, _HARD_LIMIT) is None


def test_extensionless_file_is_source_only_with_a_shebang(tmp_path: Path) -> None:
    """A file with no suffix is classified by shebang, not exempted (AC-9).

    ``bin/harness`` was exactly such a script until #435. Blanket-classifying
    the empty suffix as non-source would re-open this hole for the next one, so
    the empty suffix is the one case decided per file rather than per suffix.

    The sample carries a ``#``-comment interpreter, which is what the branch's
    ``#`` answer assumes and what every extensionless script this repo tracked
    has been.
    """
    script = _over_ceiling_file(tmp_path, "harness", marker="#!/usr/bin/env bash")
    plain = _over_ceiling_file(tmp_path, "LICENSE")

    assert _comment_prefix(script) == "#"
    assert _offending(script, _HARD_LIMIT) == (_HARD_LIMIT + 1, _HARD_LIMIT)
    assert _comment_prefix(plain) is None
    assert _offending(plain, _HARD_LIMIT) is None


def test_a_directory_symlink_is_not_read_as_source(tmp_path: Path) -> None:
    """The empty-suffix branch survives what ``git ls-files`` actually lists (AC-9).

    21 of this repo's 22 tracked extensionless paths are symlinks into
    ``.claude/`` and ``.codex/`` that resolve to directories. Reading one raises
    rather than returning bytes, so the shebang branch checks ``is_file`` first.
    """
    link = tmp_path / "skills"
    link.symlink_to(tmp_path, target_is_directory=True)
    assert _comment_prefix(link) is None


def test_source_and_non_source_suffix_sets_are_disjoint() -> None:
    """A suffix is classified once, so its classification is not order-dependent."""
    both = set(_SOURCE_COMMENT_PREFIXES) & _NON_SOURCE_SUFFIXES
    assert not both, f"these suffixes are classified both source and non-source: {sorted(both)}"


def test_hooks_tree_answers_to_the_hard_limit() -> None:
    """``hooks/`` is scanned, and at the hard limit rather than the raised one (AC-10).

    Pins both halves of #444's ceiling decision separately from the green/red
    state of the tree. A hook is ordinary logic — the raised ceiling is for
    files whose length is case enumeration, which no hook's is.
    """
    assert _TREE_CEILINGS["hooks"] == _HARD_LIMIT
    assert _TREE_CEILINGS["hooks"] < _TREE_CEILINGS["tests"]


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
