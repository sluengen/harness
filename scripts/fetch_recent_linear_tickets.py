#!/usr/bin/env python3
"""Fetch recent Linear tickets — the ``fetch-tickets`` step of the
release-notes workflow.

v1 ergonomics-test scope: read from a fixture JSON rather than hitting
the Linear API. The shape on stdout is the contract the workflow
declares — a single JSON object with a ``tickets`` array.

Usage::

    python scripts/fetch_recent_linear_tickets.py --since-days 7

Stdlib only. The ``--since-days`` flag is accepted (and recorded in
stderr) but does not currently filter the fixture — the fixture is the
"last week's tickets" by construction.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_FIXTURE = (
    Path(__file__).resolve().parent.parent
    / "tests"
    / "fixtures"
    / "release_notes_tickets.json"
)


def main(argv: list[str]) -> int:
    args = _parse_args(argv)
    print(f"fetch_recent_linear_tickets: since_days={args.since_days}", file=sys.stderr)
    if not _FIXTURE.is_file():
        print(f"fixture missing: {_FIXTURE}", file=sys.stderr)
        return 2
    payload = json.loads(_FIXTURE.read_text())
    if not isinstance(payload, dict) or "tickets" not in payload:
        print("fixture malformed: expected {'tickets': [...]}", file=sys.stderr)
        return 3
    print(json.dumps({"tickets": payload["tickets"]}))
    return 0


def _parse_args(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="fetch_recent_linear_tickets")
    p.add_argument("--since-days", type=int, required=True)
    return p.parse_args(argv)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
