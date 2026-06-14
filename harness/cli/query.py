"""Read-side query commands — ``status``, ``logs``, ``events``, ``runs``.

This module is the stable import surface for the read-side commands. The
implementations live in focused sibling modules, one per concern, so no file
grows past the code-quality size limit and each command's logic is easy to
locate:

* :mod:`harness.cli.query_status` — ``status`` (+ artifact / failure enrichment)
* :mod:`harness.cli.query_events` — ``events`` and ``logs`` (+ ``--follow``)
* :mod:`harness.cli.query_runs`   — ``runs`` (+ failed-run grouping)
* :mod:`harness.cli._query_common` — the ``--db`` resolution and tolerant
  JSON decode the commands share.

SPEC §11 names the commands; ``specs/features/run-ledger.md`` documents the row shapes.
``harness.cli`` imports the four command callables from here, so Typer
registration is unaffected by the split.
"""

from __future__ import annotations

from harness.cli.query_events import events_command, logs_command
from harness.cli.query_runs import runs_command
from harness.cli.query_status import (
    _ARTIFACT_KEYS,
    _derive_failure_retryable,
    status_command,
)

__all__ = [
    "_ARTIFACT_KEYS",
    "_derive_failure_retryable",
    "events_command",
    "logs_command",
    "runs_command",
    "status_command",
]
