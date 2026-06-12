"""Z-suffix UTC timestamp helper — format/round-trip contract and a source lock.

CAL-612 (CODE-3). The audit-ledger's ``Z``-suffix UTC timestamp convention
``datetime.now(UTC).isoformat().replace("+00:00", "Z")`` (and its inverse parse)
was hand-written across five production write-sites. A load-bearing serialization
format duplicated that widely silently bifurcates the ledger the moment one copy
drifts. ``harness/_time.py`` is now the single home for the substitution; this
test pins the format contract *and* locks the substitution to that one module so
a re-inlined copy is caught at the gate.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from pathlib import Path

from harness._time import iso_z, parse_iso_z

_REPO_ROOT = Path(__file__).resolve().parents[2]

#: A trailing-``Z`` ISO-8601 UTC timestamp, optional fractional seconds. Matches
#: the form documented in ``harness/events/emitter.py`` (SPEC §12).
_ISO_Z = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?Z$")


def test_iso_z_default_is_now_in_z_form() -> None:
    """``iso_z()`` with no argument formats the current UTC time as trailing-Z."""
    stamp = iso_z()
    assert _ISO_Z.match(stamp), stamp
    assert stamp.endswith("Z")
    assert "+00:00" not in stamp


def test_iso_z_formats_an_explicit_datetime() -> None:
    """``iso_z(dt)`` formats a given aware-UTC datetime, ``Z`` not ``+00:00``."""
    dt = datetime(2026, 5, 8, 17, 23, 45, 123456, tzinfo=UTC)
    assert iso_z(dt) == "2026-05-08T17:23:45.123456Z"


def test_round_trip_is_tz_aware_utc() -> None:
    """``parse_iso_z(iso_z(dt))`` reproduces the source aware-UTC datetime."""
    dt = datetime(2026, 5, 8, 17, 23, 45, 123456, tzinfo=UTC)
    back = parse_iso_z(iso_z(dt))
    assert back == dt
    assert back.tzinfo is not None
    assert back.utcoffset() == timedelta(0)


def test_parse_accepts_the_z_form() -> None:
    """``parse_iso_z`` reads the trailing-Z wire form into an aware datetime."""
    back = parse_iso_z("2026-05-08T17:23:45.123456Z")
    assert back == datetime(2026, 5, 8, 17, 23, 45, 123456, tzinfo=UTC)


def test_z_substitution_lives_only_in_the_time_helper() -> None:
    """No production module outside ``_time.py`` hand-rolls the Z substitution.

    Mirrors the source-grep locks in ``test_cli_surface_locked.py``: the format
    convention must have exactly one home, so a future format change is a
    one-file edit and a re-inlined copy fails the gate.
    """
    forward = 'replace("+00:00", "Z")'
    inverse = 'replace("Z", "+00:00")'
    offenders: list[str] = []
    for path in sorted((_REPO_ROOT / "harness").rglob("*.py")):
        if path.name == "_time.py":
            continue
        text = path.read_text()
        if forward in text or inverse in text:
            offenders.append(str(path.relative_to(_REPO_ROOT)))
    assert offenders == [], (
        "the Z-suffix substitution must live only in harness/_time.py; "
        f"found re-inlined in: {offenders}"
    )
