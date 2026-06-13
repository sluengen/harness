"""Shared helpers for the read-side query commands.

The ``status`` / ``logs`` / ``events`` / ``runs`` commands live in sibling
``query_*`` modules; this module holds the small pieces they share so no
concern owns another's helper:

* :func:`_resolve_db_path` — the ``--db`` resolution every command performs.
* :func:`_safe_json_loads` — tolerant JSON decode for the row/event blobs.

SPEC §11 names the commands; ``specs/state-store.md`` documents the row shapes.
All share the same DB resolution path: a ``--db`` flag overriding the default
``$cwd/.harness/harness.db``.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

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


__all__ = [
    "_resolve_db_path",
    "_safe_json_loads",
]
