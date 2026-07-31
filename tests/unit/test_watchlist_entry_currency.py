"""#272 — a ``CONTEXT.md`` watchlist note must not contradict the file it describes.

The ``/assess code`` pass of 2026-08-01 found ``CONTEXT.md``'s
``architecture_watchlist`` entry for ``harness/cli/close.py`` claiming the file
*"retired the ``# size:`` justification (now ~450 lines)"* while the file was 531
lines and carried a marker #263 had re-added. Three tickets (#262, #263, #270)
touched the two watchlisted files after the entries were last hand-edited and none
refreshed the prose.

The existing arm guards pin *membership* — that each gravity well is on the list
(``test_review_watchlist_entry.py``, CAL-1014) and that its note names its concern
mix (``test_close_watchlist_entry.py``, CAL-1139). Neither reads the file the note
describes, so a note could say anything about it and stay green. These guards close
that gap by checking the note against the tree:

1. **The retirement claim** — a note may not say the marker was retired while the
   file still carries one.
2. **The decomposition** — a note must name every extracted sibling module, derived
   from the filesystem rather than from a hand-written list, so the check cannot go
   stale the way the prose it guards did.

Both are *conditional and derived*. Neither pins a line count or a module name as a
literal: a hardcoded number is exactly what rotted here, and a guard that needs
editing on every extraction manufactures the churn this ticket removes.

The helpers are imported from the guards that already own them rather than recopied
— the repo sanctions cross-module test imports
(``test_design_verb_lifecycle_documented.py:37``), and a fourth private copy of the
entry parser or the marker pattern could drift and produce a confident false green.
"""

from __future__ import annotations

import fnmatch
import re
from pathlib import Path

import pytest

from tests._gitutil import tracked_files_under
from tests.unit.test_close_watchlist_entry import _watchlist_entries
from tests.unit.test_source_file_size_justification import _SIZE_JUSTIFICATION

REPO_ROOT = Path(__file__).resolve().parents[2]
CONTEXT = REPO_ROOT / "CONTEXT.md"

#: A note claims the ``# size:`` marker is gone. Two orderings of one clause, over a
#: window bounded by sentence/clause punctuation so a retirement verb in one clause
#: cannot bind to a ``size:`` mention in the next. Keyed on the literal ``size:``
#: token — the same key :data:`_SIZE_JUSTIFICATION` uses — so prose about a file's
#: size in the abstract does not arm the check. ``split out`` and ``extracted`` are
#: deliberately absent: recording an extraction is what the note is *for*.
_RETIREMENT_VERB = r"(?:retir\w*|dropp?\w*|remov\w*|no longer)"
_RETIREMENT_CLAIM = re.compile(
    rf"{_RETIREMENT_VERB}[^.;]{{0,60}}size:|size:[^.;]{{0,60}}{_RETIREMENT_VERB}",
    re.IGNORECASE,
)

#: Phrasings that must arm the check. The first is the exact string that shipped and
#: went stale — the regression this module exists for.
_CLAIM_MATCH = [
    "All three retired the `# size:` justification (now ~450 lines)",
    "retired its `# size:` marker",
    "the # size: justification was dropped",
    "no longer carries a # size: marker",
    "RETIRED THE # SIZE: JUSTIFICATION",
    "the # size: marker was removed in CAL-1154",
]

#: Phrasings that must not arm it. The first is this ticket's own replacement
#: wording, pinned so the fix's text is itself a test case.
_CLAIM_NO_MATCH = [
    "carries a `# size:` marker — see it for the current decomposition",
    "the git integrate/merge/push concern split out to close_merge.py",
    "a note about the file's size and its churn",
    "retired the CAL-1151 unsafe-base precondition",
    "extracted to review_protocol.py; the marker records the rest",
]


def _normalized_notes() -> list[tuple[str, str]]:
    """``(glob, note)`` pairs with each note's whitespace collapsed to one space.

    The window in :data:`_RETIREMENT_CLAIM` counts characters, so a note wrapped
    across lines would otherwise measure differently from the same note on one.
    """
    return [
        (glob, re.sub(r"\s+", " ", note).strip())
        for glob, note in _watchlist_entries(CONTEXT.read_text(encoding="utf-8"))
    ]


def _tracked_matches(glob: str) -> list[Path]:
    """Repo-relative tracked paths matching a watchlist glob.

    Entries are written as ``fnmatch`` globs, so the glob is resolved rather than
    assumed literal — otherwise the guard would quietly stop checking the first
    time someone writes ``harness/cli/*.py``.
    """
    return sorted(
        rel
        for rel in (
            path.relative_to(REPO_ROOT) for path in tracked_files_under(".")
        )
        if fnmatch.fnmatch(str(rel), glob)
    )


def _carries_size_marker(path: Path) -> bool:
    return bool(_SIZE_JUSTIFICATION.search((REPO_ROOT / path).read_text(encoding="utf-8")))


def _sibling_modules(watchlisted: Path) -> list[str]:
    """Tracked ``<stem>_*.py`` modules — the extractions pulled out of this file.

    Derived from the tree, never listed: ``close.py`` yields ``close_merge``,
    ``close_tracker``, ``close_telemetry`` wherever in the package they sit. That
    naming convention is what the extractions in this repo already follow, and
    deriving it is what keeps this guard from needing an edit on the next one.
    """
    stem = watchlisted.stem
    return sorted(
        path.stem
        for path in (
            p.relative_to(REPO_ROOT) for p in tracked_files_under("harness")
        )
        if path.suffix == ".py" and path.stem.startswith(f"{stem}_")
    )


def test_every_watchlist_glob_resolves_to_a_tracked_file() -> None:
    """Anti-vacuity: a renamed or deleted watchlisted file would otherwise make
    every check below pass by measuring nothing (#272 AC-3)."""
    entries = _normalized_notes()
    assert entries, (
        "CONTEXT.md must define a non-empty `architecture_watchlist.files` — with no "
        "entries the currency guards below assert nothing (#272)."
    )
    unresolved = [glob for glob, _ in entries if not _tracked_matches(glob)]
    assert not unresolved, (
        f"every `architecture_watchlist.files` glob must match at least one tracked "
        f"file, or its note is describing something that no longer exists and the "
        f"currency guards silently measure nothing; unresolved: {unresolved} (#272)."
    )


def test_a_marked_file_is_not_described_as_having_retired_its_marker() -> None:
    """AC-3 — the invariant, not the current text: for every watchlist entry, if a
    file it covers carries a ``# size:`` marker, the note may not claim otherwise.

    Conditional in one direction only. A file with no marker is unconstrained (a
    note may correctly record a past retirement), and a note that never mentions
    the marker cannot violate this — silence is not a false claim.
    """
    offenders = []
    for glob, note in _normalized_notes():
        claim = _RETIREMENT_CLAIM.search(note)
        if claim is None:
            continue
        for rel in _tracked_matches(glob):
            if _carries_size_marker(rel):
                offenders.append((str(rel), claim.group(0)))
    assert not offenders, (
        "a watchlist note claims the `# size:` justification was retired for a file "
        "that still carries one — the note is the record read at the *next* touch, "
        "so a false claim there mis-primes every later session. Offenders "
        f"(file, clause): {offenders}. Fix the CONTEXT.md note, not the marker "
        "(#272 AC-3)."
    )


def test_a_watchlist_note_names_every_extracted_sibling_module() -> None:
    """AC-1/AC-2 — the note must not lag the tree on the file's decomposition.

    This is the other half of what went stale: the ``close.py`` note said "all
    three" after #263 made it four, and the ``review.py`` note never learned about
    #262's ``review_telemetry``. Derived from the filesystem so it stays true
    without edits — pinning the module names as literals would need updating on
    every extraction, which is the churn this ticket exists to remove.
    """
    checked = 0
    missing: list[tuple[str, list[str]]] = []
    for glob, note in _normalized_notes():
        for rel in _tracked_matches(glob):
            siblings = _sibling_modules(rel)
            if not siblings:
                continue
            checked += 1
            absent = [name for name in siblings if name not in note]
            if absent:
                missing.append((str(rel), absent))
    assert checked, (
        "no watchlisted file has any `<stem>_*.py` sibling — this guard would pass "
        "by measuring nothing; check the derivation before assuming it is clean "
        "(#272)."
    )
    assert not missing, (
        "a watchlist note omits a module extracted out of the file it describes, so "
        "the note understates the decomposition a reader uses to judge whether their "
        f"change grew the gravity well. Missing (file, modules): {missing} "
        "(#272 AC-1/AC-2)."
    )


@pytest.mark.parametrize("sample", _CLAIM_MATCH)
def test_retirement_claim_regex_accepts_real_claims(sample: str) -> None:
    """The pinned examples are the readable specification of the heuristic —
    without them the next editor cannot tell which phrasings are caught."""
    assert _RETIREMENT_CLAIM.search(sample), (
        f"{sample!r} claims the size marker is gone and must arm the check (#272)."
    )


@pytest.mark.parametrize("sample", _CLAIM_NO_MATCH)
def test_retirement_claim_regex_rejects_non_claims(sample: str) -> None:
    """Recording an extraction, or discussing size in the abstract, is not a
    retirement claim; arming on those would make the guard unusable."""
    assert not _RETIREMENT_CLAIM.search(sample), (
        f"{sample!r} makes no retirement claim and must not arm the check (#272)."
    )
