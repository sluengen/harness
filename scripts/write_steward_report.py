#!/usr/bin/env python3
"""Write a steward-review markdown report — the ``write-report`` step
of the steward workflow (SPEC §14).

Invoked by ScriptNode with::

    python scripts/write_steward_report.py --run-id <ulid> --domain <name>

Reads ``findings`` and ``systemic_insights`` from the run's
``state_json`` (the ``assess`` step wrote them), formats a markdown
report under ``.harness/artifacts/<run_id>/steward-report.md``, and
prints ``{"report_path": "<abs path>"}`` to stdout so ScriptNode's
``contract_override`` validates against the workflow's declared
``contract: { report_path: string }``.

Stdlib only — no harness imports, no external deps. The script's CWD
when invoked by the engine is the project root (the directory holding
``.harness/``).
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

_DB_PATH = Path(".harness") / "harness.db"
_ARTIFACTS_ROOT = Path(".harness") / "artifacts"


def main(argv: list[str]) -> int:
    args = _parse_args(argv)
    state = _read_state(args.run_id)
    findings: list[Any] = list(state.get("findings") or [])
    insights: list[Any] = list(state.get("systemic_insights") or [])

    out_dir = _ARTIFACTS_ROOT / args.run_id
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "steward-report.md"
    out_path.write_text(_render(args.run_id, args.domain, findings, insights))

    print(json.dumps({"report_path": str(out_path.resolve())}))
    return 0


def _parse_args(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="write_steward_report",
        description="Render the steward-review markdown report.",
    )
    p.add_argument("--run-id", required=True, help="ULID of the run.")
    p.add_argument(
        "--domain", required=True, help="Steward domain (architecture, harness, ...)."
    )
    return p.parse_args(argv)


def _read_state(run_id: str) -> dict[str, Any]:
    """Return the run's parsed ``state_json``. Fail-fast on any error;
    the engine treats a non-zero exit as a step failure (ScriptNodeError)
    and surfaces our stderr in the resulting message."""
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


def _render(
    run_id: str, domain: str, findings: list[Any], insights: list[Any]
) -> str:
    """Build the markdown body. Plain f-strings — no Jinja."""
    parts: list[str] = [f"# Steward Report: {domain}", "", f"Run: `{run_id}`", ""]
    parts += ["## Findings", ""]
    if not findings:
        parts.append("_No findings recorded._")
    else:
        # Group by severity, preserving first-seen order for stable output.
        by_severity: dict[str, list[dict[str, Any]]] = {}
        order: list[str] = []
        for raw in findings:
            if not isinstance(raw, dict):
                continue
            severity = str(raw.get("severity", "UNCLASSIFIED"))
            if severity not in by_severity:
                by_severity[severity] = []
                order.append(severity)
            by_severity[severity].append(raw)
        for severity in order:
            parts += [f"### {severity}", ""]
            for finding in by_severity[severity]:
                area = str(finding.get("area", "—"))
                description = str(finding.get("description", "—"))
                parts.append(f"- **{area}** — {description}")
            parts.append("")
    parts += ["## Systemic Insights", ""]
    if not insights:
        parts.append("_No systemic insights recorded._")
    else:
        for raw in insights:
            parts.append(f"- {raw}")
    parts += ["", "---", ""]
    timestamp = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    parts.append(f"_Generated {timestamp} for run `{run_id}`._")
    parts.append("")
    return "\n".join(parts)


def _die(code: int, message: str) -> None:
    print(f"write_steward_report: {message}", file=sys.stderr)
    sys.exit(code)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
