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

#: The root file's ceilings. Pre-rotation it was 410 lines / 120,212 bytes; the
#: rotated root holds only the current release cycle's ``[Unreleased]`` window
#: (~88 lines / ~22KB), so both bounds fail on the old file and pass on the new
#: with a full release cycle of headroom (~14–20 more entries) before the next
#: release must rotate. The byte bound is the direct measure of the context tax
#: the ticket names ("115KB", "megabytes within a year").
_ROOT_BYTE_BOUND = 60_000
_ROOT_LINE_BOUND = 250

#: A soft-warning threshold below the hard byte gate (80% of it) — CAL-1182 hit
#: 9 bytes of headroom against the hard bound, then regrew to a second
#: near-miss within four days (#195) because nothing failed the gate until it
#: was already nearly wedged. This threshold turns a routine Build tick's
#: check into an actionable, self-explaining failure well before that point,
#: naming the fold recipe (``RELEASING.md`` "Between-release CHANGELOG fold")
#: so the fix is a pointer away rather than an emergency edit.
_ROOT_SOFT_WARNING_BOUND = 48_000

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
    """The root file is under the byte ceiling (the context-tax measure)."""
    size = len(_CHANGELOG.read_bytes())
    assert size <= _ROOT_BYTE_BOUND, (
        f"CHANGELOG.md is {size:,} bytes — over the {_ROOT_BYTE_BOUND:,}-byte "
        f"ceiling. Rotate released entries to {_ARCHIVE_DIR}/<year>.md, keeping "
        "only the [Unreleased] window (see RELEASING.md)."
    )


def test_root_changelog_is_line_bounded() -> None:
    """The root file is under the line ceiling."""
    lines = len(_CHANGELOG.read_text(encoding="utf-8").splitlines())
    assert lines <= _ROOT_LINE_BOUND, (
        f"CHANGELOG.md is {lines} lines — over the {_ROOT_LINE_BOUND}-line "
        f"ceiling. Rotate released entries to {_ARCHIVE_DIR}/<year>.md."
    )


def test_root_changelog_soft_warning_threshold() -> None:
    """Fail well before the hard gate, naming the fold recipe by section."""
    size = len(_CHANGELOG.read_bytes())
    assert size <= _ROOT_SOFT_WARNING_BOUND, (
        f"CHANGELOG.md is {size:,} bytes — over the {_ROOT_SOFT_WARNING_BOUND:,}-byte "
        f"soft-warning threshold (80% of the {_ROOT_BYTE_BOUND:,}-byte hard gate). "
        "Fold older [Unreleased] entries to a rolling summary now — see "
        "RELEASING.md 'Between-release CHANGELOG fold'."
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
