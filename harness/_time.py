"""The single home for the ledger's trailing-``Z`` UTC timestamp format.

Event and record timestamps are written as ISO-8601 UTC with a trailing ``Z``
(e.g. ``2026-05-08T17:23:45.123456Z``) — human-readable and round-trippable by
``datetime.fromisoformat`` once the ``Z`` is swapped for ``+00:00`` (SPEC §12;
see ``harness.events.emitter``). This module owns that substitution so the
format has exactly one definition: a change here is a one-file edit, and
``tests/unit/test_time.py`` fails the gate if any other module re-inlines it.

These helpers cover only the ``Z``-form event/record timestamps. The ``runs``
table's own columns are written with a plain ``.isoformat()`` (no ``Z``) on
purpose — that split is intentional and not consolidated here.
"""

from __future__ import annotations

from datetime import UTC, datetime


def iso_z(dt: datetime | None = None) -> str:
    """Format an aware-UTC datetime (default: now) as a trailing-``Z`` ISO string.

    Args:
        dt: An aware UTC datetime. ``None`` uses ``datetime.now(UTC)``.

    Returns:
        ISO-8601 with the ``+00:00`` offset rendered as a trailing ``Z``.
    """
    if dt is None:
        dt = datetime.now(UTC)
    return dt.isoformat().replace("+00:00", "Z")


def parse_iso_z(s: str) -> datetime:
    """Parse a trailing-``Z`` UTC timestamp into an aware datetime.

    The inverse of :func:`iso_z`: swaps the ``Z`` back to ``+00:00`` so
    ``datetime.fromisoformat`` yields a tz-aware UTC value.
    """
    return datetime.fromisoformat(s.replace("Z", "+00:00"))
