#!/usr/bin/env python3
"""Write release-notes markdown — the ``write-file`` step of the
release-notes workflow.

Reads ``release_notes`` from the run's ``state_json`` (the
``summarise`` step wrote it), writes to a dated markdown file
(or ``--output-path`` if non-empty), and prints
``{"output_path": "<abs path>"}`` to stdout so ScriptNode's
``contract_override`` validates against the workflow's declared
``contract: { output_path: string }``.

Stdlib only.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, NoReturn

_DB_PATH = Path(".harness") / "harness.db"


def main(argv: list[str]) -> int:
    args = _parse_args(argv)
    state = _read_state(args.run_id)
    release_notes = state.get("release_notes")
    if not isinstance(release_notes, str) or not release_notes.strip():
        _die(5, "state.release_notes missing or empty")

    if args.output_path:
        out_path = Path(args.output_path).resolve()
    else:
        today = datetime.now(UTC).strftime("%Y-%m-%d")
        out_path = Path(f"release-notes-{today}.md").resolve()

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(release_notes)
    print(json.dumps({"output_path": str(out_path)}))
    return 0


def _parse_args(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="write_release_notes")
    p.add_argument("--run-id", required=True)
    p.add_argument("--output-path", default="")
    return p.parse_args(argv)


def _read_state(run_id: str) -> dict[str, Any]:
    if not _DB_PATH.is_file():
        _die(2, f"db not found at {_DB_PATH.resolve()}")
    conn = sqlite3.connect(_DB_PATH)
    try:
        row = conn.execute(
            "SELECT state_json FROM runs WHERE run_id = ?", (run_id,)
        ).fetchone()
    finally:
        conn.close()
    if row is None:
        _die(3, f"no run with run_id={run_id!r}")
    try:
        parsed = json.loads(row[0])
    except (TypeError, json.JSONDecodeError) as exc:
        _die(4, f"state_json invalid: {exc}")
    if not isinstance(parsed, dict):
        _die(4, f"state_json must be an object, got {type(parsed).__name__}")
    return dict(parsed)


def _die(code: int, message: str) -> NoReturn:
    print(f"write_release_notes: {message}", file=sys.stderr)
    sys.exit(code)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
