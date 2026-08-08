"""CAL-1011 — the root CHANGELOG.md is rotated at each dev→main release.

``CHANGELOG.md`` was append-only and never rotated: 65 entries under a single
``## [Unreleased]`` heading, 120KB in 410 lines (single lines up to ~1,100
chars). At v3 cadence it reaches megabytes within a year — a context tax on
every agent that opens it. Released entries (everything already on ``main``) are
re-homed to ``CHANGELOG-archive/<year>.md``; the root keeps only the
``## [Unreleased]`` window and a pointer at the archive, and ``RELEASING.md``
documents the rotation so it runs at every release.

These tests are the executable form of the acceptance criteria:

* **Root CHANGELOG bounded** — the root file's byte and line ceilings, and the
  ``changelog.d/`` count bound, are **cadence** bounds and no longer live here.
  #350 moved them to ``scripts/cadence.py``, which the release path enforces and
  the gate merely reports: they fail because of *accumulated repo state*, which
  no single change caused and none can fix, so a breach used to turn
  ``verify.sh`` red on the integration branch and halt every unrelated ticket.
  What stays here is the per-change half — see the next bullet.
* **The unreleased window carries no new entries** — the base-independent
  replacement for what the byte/line ratchet used to catch *in passing*: a
  change appending under ``## [Unreleased]``. It is a genuine correctness bound
  (only a diff can raise the count, and that diff can always fix it), and it
  holds wherever the suite runs. Since #324 it is the **only** per-change
  changelog guard: the fragment system that gave a change somewhere else to
  write is deleted, and a release derives its entries from the commit range, so
  this window stays empty between releases rather than being emptied by a fold.
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

#: How many ``### `` entries may sit under ``## [Unreleased]``.
#:
#: The per-change half of what the retired byte/line ratchet used to do. Since
#: #324 a change writes **no** changelog artifact — the release derives its
#: entries from the commit range (ADR 0014) — so this window does not grow at
#: all between releases, and a change that appends here is re-opening the shared
#: insertion point ADR 0010 removed. Only a diff can raise this count, and the
#: diff that raised it can always fix it (put the text in the commit body, where
#: the release reads it from) — that is what makes it a **correctness** bound and
#: keeps it in the gate, unlike the size ratchets #350 moved to
#: ``scripts/cadence.py``.
#:
#: It was the base-independent half of a pair, and is now the whole of it: its
#: sibling ``scripts/changelog_fragments.py require`` needed a merge base and
#: abstained where one could not be resolved (a shallow CI checkout, a detached
#: ``promote`` worktree). This holds wherever the suite runs, which is why it is
#: the half that survived the deletion.
#:
#: **It only ever moves down.** The release rotation empties the window, so
#: re-baselining this constant is housekeeping that can never block anyone — the
#: property that disqualifies it from being a cadence bound.
_UNRELEASED_ENTRY_COUNT = 0

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
# The unreleased window carries no new entries — the per-change measuring test.
# ---------------------------------------------------------------------------


def _unreleased_window() -> list[str]:
    """The lines under ``## [Unreleased]``, up to the next ``## `` heading."""
    lines = _CHANGELOG.read_text(encoding="utf-8").splitlines()
    start = next(
        (i for i, line in enumerate(lines) if line.startswith("## [Unreleased]")),
        None,
    )
    assert start is not None, "CHANGELOG.md has lost its ## [Unreleased] heading"
    end = next(
        (i for i, line in enumerate(lines[start + 1 :], start + 1) if line.startswith("## ")),
        len(lines),
    )
    return lines[start:end]


def test_unreleased_window_carries_no_new_entries() -> None:
    """A change records its entry in its commit; it does not append here.

    The base-independent guard, and since #324 the only per-change changelog
    guard: its former sibling ``changelog_fragments.py require`` needed a merge
    base and abstained without one (a shallow checkout, a detached ``promote``
    worktree). This holds wherever the suite runs.
    """
    entries = [line for line in _unreleased_window() if line.startswith("### ")]
    assert len(entries) <= _UNRELEASED_ENTRY_COUNT, (
        f"CHANGELOG.md's [Unreleased] window holds {len(entries)} entries — over "
        f"the {_UNRELEASED_ENTRY_COUNT} this file is pinned at. Since #324 a "
        "change does not append here at all: write the entry as the commit body, "
        "which is what the release assembles from (ADR 0014). The release "
        "rotation empties this window, so this constant is only ever re-baselined "
        "downward."
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
