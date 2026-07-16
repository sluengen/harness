"""CAL-1111 — the release-facing docs describe what actually shipped.

The 2026-07-16 release (PR #161) surfaced two doc-currency defects, both in the
pre-release checklist's orbit:

* **The README changelog was a release behind.** ``README.md`` ``## Changelog``
  is written at *era* granularity, and its newest entry was ``2026-06`` — the
  2026-07 era (the AGPL/MIT relicence and the unattended-run posture reaching
  consumers) was unrecorded on the front page of a repo about to go public.
* **``RELEASING.md`` named an artifact that does not exist.** Its pre-release
  checklist said "Version roadmap tables in ``README.md`` and ``CLAUDE.md``
  reflect what shipped vs what's next" — **neither file has ever held a roadmap
  table**. A checklist item that can never be honestly ticked is either skipped
  silently or invites someone to invent a table to satisfy it.

These tests are the executable form of the acceptance criteria:

* **AC-1 — the 2026-07 era is present.** A deliberate-update *sentinel* (the same
  convention as :mod:`tests.unit.test_changelog_rotation`): the newest era is
  pinned by name so a release that forgets to record its era fails the gate. It
  is bumped on purpose at each release, not left to drift.
* **Changelog structure holds.** Era headings are well-formed ``### YYYY-MM — …``
  and listed newest-first, so a new entry cannot be malformed or mis-ordered.
* **AC-2 — no roadmap phantom.** ``RELEASING.md`` carries no roadmap-table
  reference; the phantom checklist item was removed (see the change spec /
  CHANGELOG for why removal, not creation).
* **AC-3 — the checklist references only things that exist.** Every repo-relative
  file path named in a ``RELEASING.md`` checklist item resolves to a tracked
  file, so no sibling phantom hides behind the one the ticket named.

**AC-5 — why month-granular staleness is not mechanically pinned (the escape
hatch the AC provides).** A guard "the README's newest era is not older than the
newest archived entry's window" has no stable month to read: archived entries
are headed by change description + ticket id and carry *no per-entry date*, and
the archive's only date window is the **year** (files are
``CHANGELOG-archive/<year>.md``). A year-granular comparator is too coarse to
catch the one-era lag that is the actual bug — it passes on the exact stale state
this ticket fixes. A month-granular comparator would have to hardcode the current
release month, a literal that must be bumped every release — reintroducing the
manual-maintenance staleness the ticket fights, with false confidence between
bumps. The currency signal genuinely exists only at *release time*, when the
releaser has just gathered the shipped tickets (``RELEASING.md`` step 1), so that
is where the month-currency check belongs and already lives (the pre-release
item, kept honest by AC-2/AC-3). What is worth automating — structure and the
newest-era sentinel — is pinned here.
"""

from __future__ import annotations

import re
from pathlib import Path

from tests._gitutil import tracked_files_under

_REPO_ROOT = Path(__file__).resolve().parents[2]
_README = _REPO_ROOT / "README.md"
_RELEASING = _REPO_ROOT / "RELEASING.md"
_ARCHIVE_DIR = "CHANGELOG-archive"

#: The newest era the README changelog must record. Bumped on purpose at each
#: release that opens a new era — the deliberate-update step, matching the
#: ``_RELEASED_SENTINELS`` convention in ``test_changelog_rotation.py``. A
#: release that forgets its era fails :func:`test_readme_records_the_newest_era`.
_NEWEST_ERA = "2026-07"

#: Matches an *era* heading in the changelog: ``### YYYY-MM — description``. The
#: historical ``### v1.0.0 (2026-05-27) — …`` entry is a version heading, not an
#: era heading, and is deliberately excluded from the ordering invariant.
_ERA_HEADING = re.compile(r"^### (\d{4})-(\d{2}) — ", re.MULTILINE)

#: Matches a repo-relative file path (real extension, no ``<placeholder>``)
#: anywhere inside a backticked span, so a checklist item's file references can
#: be verified to exist.
_FILE_REF = re.compile(r"`[^`]*?([\w./-]+\.(?:md|py|yml|yaml|sh|toml))")


def _changelog_section() -> str:
    """The body of the README's ``## Changelog`` section (to its next H2)."""
    text = _README.read_text(encoding="utf-8")
    start = text.index("\n## Changelog")
    rest = text[start + 1 :]
    nxt = re.search(r"^## (?!Changelog)", rest[len("## Changelog") :], re.MULTILINE)
    return rest if nxt is None else rest[: len("## Changelog") + nxt.start()]


def _era_months() -> list[tuple[int, int]]:
    """(year, month) of each era heading, in document order (newest first)."""
    return [(int(y), int(m)) for y, m in _ERA_HEADING.findall(_changelog_section())]


# ---------------------------------------------------------------------------
# AC-1 / structure — the changelog records the newest era, well-formed.
# ---------------------------------------------------------------------------


def test_readme_records_the_newest_era() -> None:
    """The README changelog carries a ``### <_NEWEST_ERA> — …`` era heading."""
    section = _changelog_section()
    assert re.search(rf"^### {re.escape(_NEWEST_ERA)} — ", section, re.MULTILINE), (
        f"README.md ## Changelog is missing the {_NEWEST_ERA} era. Add an era "
        "entry (era granularity, newest first) covering what shipped in that "
        f"window, and bump _NEWEST_ERA. See RELEASING.md's pre-release checklist."
    )


def test_readme_changelog_has_era_headings() -> None:
    """At least one well-formed era heading exists (the section is non-empty)."""
    assert _era_months(), (
        "README.md ## Changelog has no '### YYYY-MM — …' era heading — the "
        "changelog must be written at era granularity."
    )


def test_readme_changelog_eras_are_newest_first() -> None:
    """Era headings are in strictly descending chronological order."""
    months = _era_months()
    assert months == sorted(months, reverse=True) and len(set(months)) == len(months), (
        f"README.md ## Changelog eras are not newest-first / unique: {months}. "
        "Insert a new era at the top of the section."
    )


# ---------------------------------------------------------------------------
# AC-2 — the roadmap-table phantom is gone.
# ---------------------------------------------------------------------------


def test_releasing_has_no_roadmap_phantom() -> None:
    """``RELEASING.md`` references no roadmap table (the phantom was removed).

    Neither ``README.md`` nor ``CLAUDE.md`` has ever held a roadmap table, and
    ``CLAUDE.md`` is a derived copy of universal distributed guidance
    (``process/harness.md``), so a harness roadmap does not belong there. The
    checklist item was removed rather than satisfied by inventing tables. If a
    real roadmap is ever introduced, create the tables *and* update this guard
    deliberately.
    """
    assert "roadmap" not in _RELEASING.read_text(encoding="utf-8").lower(), (
        "RELEASING.md references a roadmap — but no roadmap table exists in "
        "README.md or CLAUDE.md. Remove the phantom checklist item (AC-2), or "
        "create real tables and update this guard on purpose."
    )


# ---------------------------------------------------------------------------
# AC-3 — every checklist file reference resolves to a tracked file.
# ---------------------------------------------------------------------------


def test_releasing_checklist_references_exist() -> None:
    """Each repo-relative file path named in a ``- [ ]`` item exists and is tracked."""
    tracked = tracked_files_under(".")
    missing: list[str] = []
    for line in _RELEASING.read_text(encoding="utf-8").splitlines():
        if not line.lstrip().startswith("- [ ]"):
            continue
        for ref in _FILE_REF.findall(line):
            if (_REPO_ROOT / ref).resolve() not in tracked:
                missing.append(ref)
    assert not missing, (
        f"RELEASING.md checklist items reference files that do not exist: "
        f"{missing}. A checklist item must point at something a releaser can "
        "actually verify (AC-3)."
    )
