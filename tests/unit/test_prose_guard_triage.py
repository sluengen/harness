"""#459 — the prose-guard triage record still describes the tree it triaged.

ADR 0016 (`specs/decisions/0016-tests-own-structure-and-negative-space.md`)
carries a table bucketing every guard module tracked at `5194fb3` as **KEEP**,
**CONVERT** or **DELETE**. This guard binds that record to the tracked tree in
both directions:

* **The deletions happened, and stay happened.** Every DELETE row names a module
  absent from the git index. Absence is read from `git ls-files`, never from the
  working directory — a `.pyc` under `__pycache__`, an editor backup or an
  untracked leftover must not read as a surviving module
  (`craft.md`, *Assert absence from the git index, never by grep*).
* **Nothing else went with them — the did-not-delete-too-much floor.** Every
  KEEP and CONVERT row names a module still in the index. The floor pins
  **membership**, not a count: a surviving-module *number* is something the next
  deletion silently lowers, whereas a named set fails on the specific deletion
  that should not have happened (`craft.md`, *Floors decay into decoration*).

The table is a **frozen historical record** of one triage on one tree, which is
why its totals are pinned exactly rather than as a `>=` floor. A floor decays
into decoration when its subject legitimately grows or shrinks; this subject
does neither. A new guard module written next month does not belong in a table
dated 2026-08-16 and is deliberately not required to appear in it — the
correspondence asserted here runs from the record to the tree, not back.

`test_the_row_parser_finds_a_row_it_is_given` is the positive control. Without
it a parser that silently matched nothing would make both sweeps above
constant-true over an empty set — the empty-subject-set class — and the guard
would read green while measuring nothing.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tests._gitutil import tracked_files_under  # noqa: E402

_REPO_ROOT = Path(__file__).resolve().parents[2]
_RECORD = _REPO_ROOT / "specs" / "decisions" / "0016-tests-own-structure-and-negative-space.md"

#: One row of the triage table: `| \`test_x.py\` | **BUCKET** | reason |`.
_ROW = re.compile(r"^\|\s*`(test_[a-z0-9_]+\.py)`\s*\|\s*\*\*(KEEP|CONVERT|DELETE)\*\*\s*\|")

#: The triage's own totals, pinned exactly because the record is frozen: it
#: describes one tree at one commit and is never re-run.
_EXPECTED = {"KEEP": 66, "CONVERT": 66, "DELETE": 5}


def _rows(text: str) -> list[tuple[str, str]]:
    """Every `(module, bucket)` the record's table declares, in file order.

    A list rather than a mapping, deliberately. Keying by module name made a
    duplicated row invisible: a second row for the same module overwrote the
    first, so a module recorded in two buckets at once read as whichever came
    last, and the totals stayed correct while the record contradicted itself.
    Mutation found this — see `test_no_module_is_bucketed_twice`.
    """
    return [
        (match.group(1), match.group(2))
        for match in (_ROW.match(line) for line in text.splitlines())
        if match
    ]


def _modules_in(rows: list[tuple[str, str]], *buckets: str) -> set[str]:
    return {name for name, bucket in rows if bucket in buckets}


def _tracked_guard_modules() -> set[str]:
    return {path.name for path in tracked_files_under("tests/unit")}


def test_the_row_parser_finds_a_row_it_is_given() -> None:
    """Positive control: the predicate the two sweeps rely on can actually fire.

    Exercises `_rows` itself rather than re-implementing its regex, so a parser
    that stops matching the record's real formatting is caught here instead of
    silently emptying the subject set below.
    """
    synthetic = "\n".join(
        [
            "| Module | Bucket | Reason |",
            "|---|---|---|",
            "| `test_synthetic_example.py` | **DELETE** | a row invented by this control |",
            "| `test_another_example.py` | **KEEP** | and a second bucket |",
            "not a table row at all",
        ]
    )
    assert _rows(synthetic) == [
        ("test_synthetic_example.py", "DELETE"),
        ("test_another_example.py", "KEEP"),
    ]


def test_the_record_carries_the_triage_it_claims_to() -> None:
    """The table is intact — exact totals, because the record is frozen."""
    rows = _rows(_RECORD.read_text(encoding="utf-8"))
    counts = {bucket: sum(1 for _, value in rows if value == bucket) for bucket in _EXPECTED}
    assert counts == _EXPECTED, (
        f"the ADR 0016 triage table no longer holds the triage it recorded: {counts}. "
        "It describes one tree at one commit and does not change; a differing count "
        "means the table was edited or the parser stopped reading it."
    )


def test_every_deleted_guard_is_absent_from_the_index() -> None:
    """Each DELETE row names a module git no longer tracks."""
    rows = _rows(_RECORD.read_text(encoding="utf-8"))
    deleted = _modules_in(rows, "DELETE")
    tracked = _tracked_guard_modules()
    survivors = sorted(deleted & tracked)
    assert not survivors, (
        "ADR 0016 records these guard modules as deleted, but they are still tracked:\n  "
        + "\n  ".join(survivors)
    )


def test_no_kept_or_converted_guard_was_deleted_with_them() -> None:
    """The did-not-delete-too-much floor, pinned by membership."""
    rows = _rows(_RECORD.read_text(encoding="utf-8"))
    surviving = _modules_in(rows, "KEEP", "CONVERT")
    tracked = _tracked_guard_modules()
    missing = sorted(surviving - tracked)
    assert not missing, (
        "ADR 0016 bucketed these guard modules to survive the triage, but they are no "
        "longer tracked. A deletion beyond the recorded one is a decision, so it "
        "amends the record rather than passing quietly:\n  " + "\n  ".join(missing)
    )


def test_no_module_is_bucketed_twice() -> None:
    """No module appears in the table more than once.

    A record that buckets one module as both KEEP and DELETE contradicts itself,
    and neither sweep above can see it: whichever row is read second decides.
    The first version of this guard collapsed rows into a mapping and had
    exactly that blind spot — a mutation renaming a DELETE row onto a module
    that already had a KEEP row was absorbed silently (#459).
    """
    rows = _rows(_RECORD.read_text(encoding="utf-8"))
    seen: dict[str, str] = {}
    duplicates: list[str] = []
    for name, bucket in rows:
        if name in seen:
            duplicates.append(f"{name}: {seen[name]} and {bucket}")
        seen[name] = bucket
    assert not duplicates, (
        "the ADR 0016 triage table buckets these modules more than once:\n  "
        + "\n  ".join(duplicates)
    )
