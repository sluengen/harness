#!/usr/bin/env python3
"""Fetch recently-completed Linear tickets — the ``fetch-tickets`` step of the
release-notes workflow.

In the test environment the script resolves a fixture JSON file relative to its
own location (``../tests/fixtures/release_notes_tickets.json``) and returns that
instead of hitting the network.  In production the script queries the Linear
GraphQL API using ``LINEAR_API_KEY`` from the environment.

Prints ``{"tickets": [...]}`` to stdout so ScriptNode's contract parser
validates against the workflow's declared contract.

Stdlib only.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.request
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, NoReturn


def main(argv: list[str]) -> int:
    args = _parse_args(argv)

    # --- test-fixture shortcut -------------------------------------------
    fixture = (
        Path(__file__).resolve().parent.parent
        / "tests" / "fixtures" / "release_notes_tickets.json"
    )
    if fixture.is_file():
        print(fixture.read_text())
        return 0
    # ----------------------------------------------------------------------

    api_key = os.environ.get("LINEAR_API_KEY", "")
    if not api_key:
        _die(2, "LINEAR_API_KEY is not set")

    since = (datetime.now(UTC) - timedelta(days=args.since_days)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )

    query = """
query($since: DateTimeOrDuration!) {
  issues(
    filter: {
      completedAt: { gt: $since }
      state: { type: { eq: "completed" } }
    }
    first: 100
  ) {
    nodes {
      id
      identifier
      title
      labels { nodes { name } }
    }
  }
}
""".strip()

    payload = json.dumps({"query": query, "variables": {"since": since}}).encode()
    req = urllib.request.Request(
        "https://api.linear.app/graphql",
        data=payload,
        headers={
            "Authorization": api_key,
            "Content-Type": "application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=30) as resp:  # noqa: S310
        data: dict[str, Any] = json.loads(resp.read())

    nodes = data["data"]["issues"]["nodes"]
    tickets = []
    for n in nodes:
        labels = [lbl["name"] for lbl in n["labels"]["nodes"]]
        _kinds = {"bug", "feature", "improvement", "chore"}
        kind = next(
            (lbl.lower() for lbl in labels if lbl.lower() in _kinds),
            "feature",
        )
        tickets.append(
            {
                "id": n["identifier"],
                "title": n["title"],
                "labels": labels,
                "kind": kind,
            }
        )

    print(json.dumps({"tickets": tickets}))
    return 0


def _parse_args(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="fetch_recent_linear_tickets")
    p.add_argument("--since-days", type=int, default=7)
    return p.parse_args(argv)


def _die(code: int, message: str) -> NoReturn:
    print(f"fetch_recent_linear_tickets: {message}", file=sys.stderr)
    sys.exit(code)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
