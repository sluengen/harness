#!/usr/bin/env python3
"""Fetch a single Linear ticket by identifier and print JSON to stdout.

Usage:
    python scripts/fetch_linear_ticket.py CAL-497

Output (stdout, matches the workflow contract):
    {"identifier": "CAL-497", "title": "...", "description": "...", "url": "...", "state": "..."}

Reads LINEAR_API_KEY from .env (repo root) if not already in the environment.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path


def _load_dotenv() -> None:
    """Load .env from the repo root into the environment if present."""
    env_path = Path(__file__).resolve().parent.parent / ".env"
    if not env_path.is_file():
        return
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def main(argv: list[str]) -> int:
    if len(argv) != 2 or argv[1].startswith("-"):
        print(f"usage: {argv[0]} <IDENTIFIER>  (e.g. CAL-497)", file=sys.stderr)
        return 2

    identifier = argv[1]
    _load_dotenv()

    # Import after env is loaded so LinearClient picks up LINEAR_API_KEY.
    from harness.tools.linear import LinearAPIError, LinearClient

    try:
        client = LinearClient()
        issue = client.get_issue(identifier)
    except LinearAPIError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1

    print(json.dumps({
        "identifier": issue["identifier"],
        "title": issue["title"],
        "description": issue.get("description") or "",
        "url": issue.get("url") or "",
        "state": issue.get("state", {}).get("name") or "",
        "labels": issue.get("labels") or [],
    }))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
