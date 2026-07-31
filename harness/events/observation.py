"""The never-raises event write — ADR 0009's "observation is subordinate" rule.

A verb records telemetry about its own terminal paths (``review``'s #262,
``close``'s #263). Those writes happen at the worst possible moment: the verb has
already decided to refuse and is in the middle of reporting it. So the rule is
absolute — a telemetry write must never change the exit code, the ``reason`` or
the printed JSON the verb would have produced without it. Losing a row costs a
statistic; letting its failure escape would cost the run its actual answer, and
would replace a well-formed "I refuse" with an unrelated crash that an unattended
orchestrator has no way to interpret.

This module is that rule, in one place. It landed here on its **second** caller
(``review``'s writer, then ``close``'s), which is where ``code-quality`` Part B
extracts a sync-critical helper — and this is exactly the kind that must not be
enforced in two places: an observation write that swallows in one verb and
escapes in the other breaks ADR 0009 unevenly, and the next verb to grow
telemetry would copy whichever version its author happened to read first.

It deliberately does **not** live in :mod:`harness.events.emitter`.
:meth:`~harness.events.emitter.EventEmitter.emit` raises on an unknown event type
and on a foreign-key violation, and those raises are load-bearing — a
swallow-everything sibling one function away is the kind of neighbour a caller
reaches for by accident. A separate module named for the rule keeps the two
contracts un-confusable.
"""

from __future__ import annotations

import contextlib
from pathlib import Path
from typing import Any

from harness.events.emitter import EventEmitter
from harness.events.schema import EventType

__all__ = ["emit_observation"]


async def emit_observation(
    db_path: Path,
    *,
    run_id: str,
    event_type: EventType,
    data: dict[str, Any],
) -> None:
    """Append an observation event. **Never raises** — see the module docstring.

    Args:
        db_path: The run's ledger. A database that will not open is swallowed
            like any other failure.
        run_id: The resolved run the row is keyed to. A caller with no resolved
            run must not call this: ``events.run_id`` is ``NOT NULL`` with a
            foreign key to ``runs``, so there would be nothing to anchor to.
        event_type: The verb's own event type, typed against the canonical set
            so an observation cannot introduce one the emitter would reject — a
            rejection this function would then swallow. Observation rows share
            the type with the verb's success rows and discriminate on a payload
            field, rather than splitting the denominator across two types.
        data: The already-dumped payload.

    The suppression covers **only** this write. It is never wrapped around any
    step of the verb's actual work, so no error the verb was previously
    reporting is swallowed by it.
    """
    # Deliberately broad: see the module docstring.
    with contextlib.suppress(Exception):
        await EventEmitter(db_path).emit(run_id=run_id, event_type=event_type, data=data)
