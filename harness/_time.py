"""The single home for the ledger's trailing-``Z`` UTC timestamp format.

Event and record timestamps are written as ISO-8601 UTC with a trailing ``Z``
(e.g. ``2026-05-08T17:23:45.123456Z``) — human-readable and round-trippable by
``datetime.fromisoformat`` once the ``Z`` is swapped for ``+00:00`` (the format
is co-documented in ``harness.events.emitter``). This module owns that
substitution so the format has exactly one definition: a change here is a
one-file edit, and ``tests/unit/test_time.py`` fails the gate if any other
module re-inlines it.

These helpers cover only the ``Z``-form event/record timestamps. The ``runs``
table's own columns are written with a plain ``.isoformat()`` (no ``Z``) on
purpose — that split is intentional and not consolidated here.

:func:`elapsed_ms` lives here for the same reason: it is the *only* place the two
shapes have to be read as one quantity, and it landed here on its second caller
(``close``'s run-row duration, #261, and ``review``'s per-attempt duration,
#262). ``code-quality`` Part B extracts a sync-critical helper on the second
copy, not the third, and a duration that rounds differently in two verbs would
make the ledger's own latency numbers incomparable.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta


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


def elapsed_ms(start: str | None, end: str) -> int | None:
    """Whole milliseconds from ``start`` to ``end``, or ``None``.

    Both ends are ledger timestamps, but they are not always written in the same
    shape: ``runs.started_at`` is a plain ``.isoformat()`` (``+00:00``) while
    every event clock is :func:`iso_z` (trailing ``Z``) — the split this module
    documents as deliberate. :func:`parse_iso_z` reads both, since swapping ``Z``
    for ``+00:00`` is a no-op on a string that already carries the offset. That is
    the whole reason this helper is shared rather than written per verb: a caller
    that assumed one shape would silently return ``None`` for the other, and a
    duration that is quietly absent reads exactly like one that was never wanted.

    Every failure yields ``None`` rather than raising — a missing start, an
    unparseable end, or one side naive against the other. The duration is
    telemetry, and losing it must never cost a verb the work it had already done
    (ADR 0009: observation is subordinate to the thing observed).
    """
    if start is None:
        return None
    try:
        started = parse_iso_z(start)
        ended = parse_iso_z(end)
    except (TypeError, ValueError):
        return None
    try:
        return (ended - started) // timedelta(milliseconds=1)
    except TypeError:  # one side naive, the other aware
        return None
