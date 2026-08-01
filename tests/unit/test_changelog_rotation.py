"""CAL-1011 — the root CHANGELOG.md is rotated at each dev→main release.

``CHANGELOG.md`` was append-only and never rotated: 65 entries under a single
``## [Unreleased]`` heading, 120KB in 410 lines (single lines up to ~1,100
chars). At v3 cadence it reaches megabytes within a year — a context tax on
every agent that opens it. Released entries (everything already on ``main``) are
re-homed to ``CHANGELOG-archive/<year>.md``; the root keeps only the
``## [Unreleased]`` window and a pointer at the archive, and ``RELEASING.md``
documents the rotation so it runs at every release.

These tests are the executable form of the acceptance criteria:

* **Root CHANGELOG bounded** — the root file is under a byte and line ceiling
  well below its pre-rotation size (the *measuring* test for "bounded": the
  ticket frames the problem in KB, so the byte bound is the load-bearing one).
  Since #267 those ceilings are a **ratchet**: entries accumulate in
  ``changelog.d/`` instead, so this file does not change between releases and
  "bounded" tightens to "may not grow". The bound the soft warning used to
  carry moved with the window it guarded, onto ``changelog.d/`` itself.
* **Archive exists** — the released history lives in a git-tracked
  ``CHANGELOG-archive/<year>.md`` carrying every moved entry, and is gone from
  the root; the root points at it.
* **RELEASING.md documents the rotation** — the release checklist names the
  archive and the move-at-release step.
* **Guards green** — the ``[Unreleased]`` window and the freshness-hook /
  presence contract (``test_docs_consistency``) still hold.
"""

from __future__ import annotations

from pathlib import Path

from tests._gitutil import tracked_files_under

_REPO_ROOT = Path(__file__).resolve().parents[2]
_CHANGELOG = _REPO_ROOT / "CHANGELOG.md"
_ARCHIVE_DIR = "CHANGELOG-archive"
_ARCHIVE = _REPO_ROOT / _ARCHIVE_DIR / "2026.md"

#: The root file's ceilings — a **ratchet** since #267, not a headroom budget.
#:
#: Entries no longer accumulate here: a change writes ``changelog.d/<ticket>.md``
#: and only the release fold touches this file, so between releases it does not
#: change at all. That is what lets the bounds become *may-not-grow*. They are
#: the measurement at the #267 baseline (156 lines / 45,923 bytes) plus a small
#: stated allowance — room for a typo fix or a reworded pointer, and nowhere
#: near the ~500–3,000 bytes and 3 lines a real entry costs. A direct append to
#: ``[Unreleased]`` therefore trips the gate.
#:
#: This is the base-independent half of the guard pair. Its sibling,
#: ``scripts/changelog_fragments.py require``, is the direct check but must
#: abstain where the merge base is unknowable (a shallow CI checkout, a detached
#: ``promote`` worktree); the ratchet holds wherever the suite runs.
#:
#: **The release raises them deliberately.** The fold inserts a released section
#: and the rotation moves it to the archive; re-baselining these two constants
#: is a step in ``RELEASING.md``, re-taken on purpose the way
#: ``_RELEASED_SENTINELS`` is.
_ROOT_BYTE_BOUND = 46_500
_ROOT_LINE_BOUND = 160

#: The fragment directory is the unreleased window now, so it carries the risk
#: the old byte soft-warning covered. Two bounds, because they fail differently:
#: too **many** fragments means a release is overdue, while a single overlong
#: fragment is the entry-length problem ``RELEASING.md``'s per-entry budget has
#: always named — it just moved file.
_FRAGMENT_DIRNAME = "changelog.d"
_FRAGMENT_COUNT_BOUND = 40
_FRAGMENT_BYTE_BOUND = 3_000

#: Distinctive strings from *released* entries — they must live in the archive
#: and be gone from the root. These sentinels pin the **rotation boundary**, so
#: they move at each release: an entry graduates from ``_UNRELEASED_SENTINELS``
#: to here when the ``dev → main`` promotion ships it. Updating them is the
#: deliberate step the release performs, the way the verb-contract lock forces
#: its snapshot to be re-taken on purpose rather than drift.
#:
#: ``18 skills → 12`` is the oldest entry overall; the installer/onboarding
#: realign (CAL-835) was the boundary at the CAL-1011 rotation. The last three
#: are the 2026-07-16 release window (CAL-906 oldest … CAL-1108 newest), which
#: rotated whole.
_RELEASED_SENTINELS = (
    "18 skills → 12",
    "realign the installer/onboarding doc names",
    "ledger-backed spend breakers for the autonomous loop",  # CAL-906
    "a terminal `shipped` status for proposals",  # CAL-1009
    "the cleanup pre-flight is sanctioned",  # CAL-1108
)

#: Distinctive strings from *unreleased* entries (dev-only, newer than the last
#: release) — they must stay in the root ``[Unreleased]`` window.
#:
#: **Empty immediately after a release**, which is the correct state rather than
#: a gap: the promotion rotates the whole window, so nothing is dev-only until
#: the next change lands. The contract the window itself carries is pinned by
#: :func:`test_root_keeps_the_unreleased_window`'s heading assertion, which does
#: not depend on this tuple. Add a sentinel here when an entry should survive a
#: future rotation.
_UNRELEASED_SENTINELS: tuple[str, ...] = ()


# ---------------------------------------------------------------------------
# Root CHANGELOG bounded — the measuring tests.
# ---------------------------------------------------------------------------


def test_root_changelog_is_byte_bounded() -> None:
    """The root file has not grown (the ratchet's byte half)."""
    size = len(_CHANGELOG.read_bytes())
    assert size <= _ROOT_BYTE_BOUND, (
        f"CHANGELOG.md is {size:,} bytes — over the {_ROOT_BYTE_BOUND:,}-byte "
        "ratchet. Since #267 this file does not accumulate: write your entry as "
        f"{_FRAGMENT_DIRNAME}/<ticket>.md instead — "
        "see RELEASING.md 'Changelog fragments'. "
        "If you are running the release fold, re-baseline this constant "
        "deliberately as part of it."
    )


def test_root_changelog_is_line_bounded() -> None:
    """The root file has not grown (the ratchet's line half)."""
    lines = len(_CHANGELOG.read_text(encoding="utf-8").splitlines())
    assert lines <= _ROOT_LINE_BOUND, (
        f"CHANGELOG.md is {lines} lines — over the {_ROOT_LINE_BOUND}-line "
        "ratchet. Since #267 this file does not accumulate: write your entry as "
        f"{_FRAGMENT_DIRNAME}/<ticket>.md instead — "
        "see RELEASING.md 'Changelog fragments'. "
        "If you are running the release fold, re-baseline this constant "
        "deliberately as part of it."
    )


# ---------------------------------------------------------------------------
# The unreleased window moved to changelog.d/ — so the bound moved with it.
# ---------------------------------------------------------------------------


def _fragment_paths() -> list[Path]:
    directory = _REPO_ROOT / _FRAGMENT_DIRNAME
    return sorted(
        p
        for p in directory.iterdir()
        if p.is_file() and p.suffix == ".md" and p.name != "README.md"
    )


def test_unreleased_fragments_are_bounded() -> None:
    """Too many pending fragments means a release is overdue.

    The intent of the retired byte soft-warning, re-homed onto the surface that
    now carries the risk: it fired before a wedged file forced an emergency
    edit, and this fires before a release window grows past what one fold
    should reasonably carry.
    """
    paths = _fragment_paths()
    assert len(paths) <= _FRAGMENT_COUNT_BOUND, (
        f"{_FRAGMENT_DIRNAME}/ holds {len(paths)} fragments — over the "
        f"{_FRAGMENT_COUNT_BOUND} bound. That is a release overdue, not a file "
        "to fold: cut one (RELEASING.md), which folds them into CHANGELOG.md "
        "and empties the directory."
    )


def test_each_fragment_is_byte_bounded() -> None:
    """The per-entry budget, enforced where entries now live.

    ``RELEASING.md`` has asked for ~1,000-byte entries since the fold ran on
    nine consecutive ticks without buying durable headroom. Asking was not
    enough — the newest entries ran 2,000–3,000 bytes each. This is that budget
    with teeth, set at the point where an entry is unambiguously an essay.
    """
    oversized = {
        p.name: len(p.read_bytes())
        for p in _fragment_paths()
        if len(p.read_bytes()) > _FRAGMENT_BYTE_BOUND
    }
    assert not oversized, (
        f"these fragments are over the {_FRAGMENT_BYTE_BOUND:,}-byte per-entry "
        f"budget: {oversized}. Reasoning longer than that belongs in the change "
        "spec, the commit body, or the review record — where it already lives in "
        "full, and where nobody pays a context tax to skip it."
    )


# ---------------------------------------------------------------------------
# Archive exists — the released history is re-homed, tracked, and complete.
# ---------------------------------------------------------------------------


def test_archive_exists_and_is_tracked() -> None:
    """``CHANGELOG-archive/2026.md`` is a git-tracked file (the root points at it)."""
    assert _ARCHIVE.resolve() in tracked_files_under(_ARCHIVE_DIR), (
        f"{_ARCHIVE_DIR}/2026.md must be a git-tracked file — it holds the "
        "released CHANGELOG history moved out of the root file."
    )


def test_archive_has_a_history_header() -> None:
    """The archive opens with a header marking it as archived history."""
    head = _ARCHIVE.read_text(encoding="utf-8").splitlines()[:8]
    joined = "\n".join(head).lower()
    assert head and head[0].startswith("# "), (
        f"{_ARCHIVE_DIR}/2026.md must open with an H1 header."
    )
    assert "archive" in joined and "changelog" in joined, (
        f"{_ARCHIVE_DIR}/2026.md's header must mark it as the CHANGELOG archive "
        "so a reader knows it is history, not current guidance."
    )


def test_archive_holds_released_history() -> None:
    """Every released sentinel lives in the archive (nothing was lost)."""
    text = _ARCHIVE.read_text(encoding="utf-8")
    for sentinel in _RELEASED_SENTINELS:
        assert sentinel in text, (
            f"{_ARCHIVE_DIR}/2026.md is missing released history ({sentinel!r}) — "
            "the rotation must move released entries, not drop them."
        )


# ---------------------------------------------------------------------------
# The root keeps the [Unreleased] window and points at the archive.
# ---------------------------------------------------------------------------


def test_released_history_is_gone_from_root() -> None:
    """The released entries no longer bloat the root file."""
    text = _CHANGELOG.read_text(encoding="utf-8")
    for sentinel in _RELEASED_SENTINELS:
        assert sentinel not in text, (
            f"CHANGELOG.md still contains released history ({sentinel!r}); it "
            f"must move to {_ARCHIVE_DIR}/2026.md."
        )


def test_root_keeps_the_unreleased_window() -> None:
    """The root keeps ``## [Unreleased]`` and its dev-only entries."""
    text = _CHANGELOG.read_text(encoding="utf-8")
    assert "## [Unreleased]" in text, (
        "CHANGELOG.md must keep the ## [Unreleased] section — new entries and the "
        "SOURCE-mode freshness-hook reminder both point at it."
    )
    for sentinel in _UNRELEASED_SENTINELS:
        assert sentinel in text, (
            f"CHANGELOG.md dropped an unreleased entry ({sentinel!r}) — only "
            "released entries rotate to the archive."
        )


def test_root_points_at_the_archive() -> None:
    """The root file names the archive so a reader can find the history."""
    text = _CHANGELOG.read_text(encoding="utf-8")
    assert _ARCHIVE_DIR in text, (
        f"CHANGELOG.md must point at {_ARCHIVE_DIR}/ so the moved history is "
        "discoverable from the root file."
    )


# ---------------------------------------------------------------------------
# RELEASING.md documents the rotation.
# ---------------------------------------------------------------------------


def test_releasing_documents_the_rotation() -> None:
    """``RELEASING.md`` names the archive and the move-at-release step."""
    text = (_REPO_ROOT / "RELEASING.md").read_text(encoding="utf-8")
    assert _ARCHIVE_DIR in text, (
        f"RELEASING.md must name {_ARCHIVE_DIR}/ — the rotation target."
    )
    lowered = text.lower()
    assert "[unreleased]" in lowered and (
        "rotat" in lowered or "archive" in lowered
    ), (
        "RELEASING.md must document the changelog rotation step (move the "
        "[Unreleased] entries into the archive at each dev→main release)."
    )
