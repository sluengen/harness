"""Short-duration parsing shared across CLI commands (CAL-1013).

Both ``worktrees cleanup --age`` and ``reclaim --stale --older-than`` accept a
short duration string (``30m`` / ``12h`` / ``7d``). The parser lives here — a
shared ``_``-helper module — so neither command reaches into the other for it.
"""

from __future__ import annotations

import re
from datetime import timedelta

import typer

__all__ = ["_parse_duration"]

_DURATION_RE = re.compile(r"^(?P<value>\d+)\s*(?P<unit>[smhd])$")


def _parse_duration(text: str) -> timedelta:
    """Parse a short duration string. Raises :class:`typer.BadParameter` on
    bad input so the CLI exits 2 with a clear message."""
    match = _DURATION_RE.match(text.strip())
    if not match:
        raise typer.BadParameter(
            f"invalid duration {text!r}; expected forms like '30m', '12h', '7d'"
        )
    value = int(match.group("value"))
    unit = match.group("unit")
    if unit == "s":
        return timedelta(seconds=value)
    if unit == "m":
        return timedelta(minutes=value)
    if unit == "h":
        return timedelta(hours=value)
    return timedelta(days=value)
