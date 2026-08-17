"""CAL-1089 — ``assessments/`` stays a live index, not a growing pile.

The retention convention (`templates/assessment.md`, `commands/assess.md`, landed
CAL-971) keeps only the **latest report per scope** plus **any report with an open
finding**; every superseded report folds into a rolling one-line-per-report
``assessments/LOG.md``. On its first opportunity the convention went unapplied —
the 2026-07-15 pass was unattended and could not run its own committing/compaction
step — so the directory grew to 29 report files with **no ``LOG.md`` at all**.

These tests are the executable form of the *tracker-independent* half of the rule.
They deliberately do **not** try to mechanise the whole convention:

* The rule's load-bearing discriminator — *is this report's finding still open?* —
  is **live tracker state**, not anything on disk. CAL-937 (the finding that keeps
  ``2026-07-02-code.md``) flipped Backlog→Canceled between this ticket being filed
  and being built. A pure unit test must not reach the tracker, so it cannot
  soundly decide which reports are foldable. That half stays a prose convention an
  agent applies each pass.
* What *is* mechanisable, and was the actual failure, is structural: ``LOG.md``
  must **exist** and be well-formed once folding has happened, and a report must be
  either kept-as-a-file **or** folded-into-``LOG.md`` — never silently both or
  neither. That is what these guards pin.

The keep-set is intentionally **not** hardcoded here — today's latest report per
scope becomes tomorrow's folded line, so pinning specific filenames would make the
guard a lie the day the next pass runs.
"""

from __future__ import annotations

import re

from tests._gitutil import tracked_files_under
from tests.unit._prose import REPO_ROOT

_ASSESSMENTS = REPO_ROOT / "assessments"
_LOG = _ASSESSMENTS / "LOG.md"

# A folded entry: ``- <YYYY-MM-DD> · <scope> · <one-clause verdict> · findings: <…>``
# The middle-dot ``·`` (U+00B7) separates the four fields, per the documented format.
_ENTRY = re.compile(
    r"^- (?P<date>\d{4}-\d{2}-\d{2}) · (?P<scope>[a-z0-9-]+) · .+ · findings: .+$"
)


def _tracked_report_stems() -> set[str]:
    """The ``<date>-<scope>`` stems of the report files git tracks in ``assessments/``.

    Excludes ``LOG.md`` (the fold target, not a report) and the ``README`` /
    index prose, if any.
    """
    stems: set[str] = set()
    for path in tracked_files_under("assessments"):
        if path.suffix != ".md" or path.name == "LOG.md":
            continue
        if re.match(r"\d{4}-\d{2}-\d{2}-", path.stem):
            stems.add(path.stem)
    return stems


def _log_entry_lines() -> list[str]:
    return [
        line
        for line in _LOG.read_text().splitlines()
        if line.startswith("- ")
    ]


def test_log_exists_and_is_tracked() -> None:
    """The headline failure: ``assessments/LOG.md`` must exist in the tracked tree."""
    tracked = tracked_files_under("assessments")
    assert _LOG.resolve() in tracked, (
        "assessments/LOG.md is missing — the retention convention requires a rolling "
        "one-line-per-report fold target (see templates/assessment.md)."
    )


def test_log_has_entries() -> None:
    """A ``LOG.md`` that exists but folds nothing is the failure wearing a hat."""
    assert _log_entry_lines(), "assessments/LOG.md carries no folded-report entries."


def test_log_entries_are_well_formed() -> None:
    """Every fold line matches the documented four-field format."""
    malformed = [line for line in _log_entry_lines() if not _ENTRY.match(line)]
    assert not malformed, (
        "assessments/LOG.md entries must be "
        "'- <YYYY-MM-DD> · <scope> · <verdict> · findings: <…>'. "
        f"Malformed: {malformed}"
    )


def test_no_report_is_both_kept_and_folded() -> None:
    """A report is either kept as a file or folded into ``LOG.md`` — never both.

    Catches the inconsistency where a fold line is written but the file was not
    removed (or vice versa): the directory would claim to be a live index while
    still carrying the superseded copy.
    """
    folded = {
        f"{m.group('date')}-{m.group('scope')}"
        for line in _log_entry_lines()
        if (m := _ENTRY.match(line))
    }
    overlap = folded & _tracked_report_stems()
    assert not overlap, (
        "these reports are folded into LOG.md yet still present as files "
        f"(remove the file or the fold line): {sorted(overlap)}"
    )
