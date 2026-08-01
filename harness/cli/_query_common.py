"""Shared helpers for the read-side query commands.

The ``status`` / ``logs`` / ``events`` / ``runs`` commands live in sibling
``query_*`` modules; this module holds the small pieces they share so no
concern owns another's helper:

* :func:`_resolve_db_path` — the ``--db`` resolution every command performs.
* :func:`_safe_json_loads` — tolerant JSON decode for the row/event blobs.
* :func:`_resolve_run_id` — the positional-vs-``--run-id`` resolution
  ``status`` / ``logs`` / ``events`` share (#245).

SPEC §11 names the commands; ``specs/features/run-ledger.md`` documents the row shapes.
All share the same DB resolution path: a ``--db`` flag overriding the default
``$cwd/.harness/harness.db``.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import typer

from harness.state import store


def _resolve_db_path(db: Path | None) -> Path:
    """Either the explicit ``--db`` or the default
    ``$cwd/.harness/harness.db``."""
    if db is not None:
        return db
    return Path.cwd() / store.DEFAULT_DB_PATH


def _safe_json_loads(raw: Any) -> Any:
    if raw is None:
        return None
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        # Surface as a string rather than crashing the CLI — the row is
        # authoritative, even if its embedded JSON is malformed.
        return raw


def _resolve_run_id(positional: str | None, option: str | None) -> str:
    """The one run id for a read command, from either the positional
    ``RUN_ID`` argument or the ``--run-id`` alias (#245).

    "Supplied" means ``is not None``, never truthiness — ``--run-id ""`` is a
    supplied value, not a silent fallback to the positional. Exits 2 (stderr,
    nothing on stdout) when neither form is given, or when both are given and
    disagree — the confused-deputy case is refused rather than resolved by
    silently preferring one source.
    """
    if positional is not None and option is not None:
        if positional != option:
            typer.echo(
                f"conflicting run ids: {positional!r} (argument) and "
                f"{option!r} (--run-id); pass one, or the same value in both",
                err=True,
            )
            raise typer.Exit(code=2)
        return positional
    resolved = positional if positional is not None else option
    if resolved is None:
        typer.echo(
            "run id required: pass it as an argument or --run-id <id>",
            err=True,
        )
        raise typer.Exit(code=2)
    return resolved


__all__ = [
    "_resolve_db_path",
    "_resolve_run_id",
    "_safe_json_loads",
]
