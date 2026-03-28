#!/usr/bin/env python3
"""
pipeline_status.py — Show the current state of all tasks in manifest.yaml.

Usage:
    python scripts/pipeline_status.py
    python scripts/pipeline_status.py --manifest path/to/manifest.yaml
"""

import argparse
import sys
from datetime import date
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).parent.parent
DEFAULT_MANIFEST = REPO_ROOT / "manifest.yaml"

# Status groupings
IN_PROGRESS_STATUSES = {"specifying", "designing", "building", "reviewing"}
READY_STATUSES = {
    "ready_for_spec",
    "ready_for_design",
    "ready_for_dev",
    "ready_for_review",
    "ready_for_deploy",
}
DONE_STATUS = "done"
BACKLOG_STATUS = "backlog"

STAGE_LABELS = {
    "specifying": "Writing spec",
    "designing": "Designing",
    "building": "Building",
    "reviewing": "Under review",
    "ready_for_deploy": "Awaiting deploy",
    "ready_for_spec": "Waiting for PM",
    "ready_for_design": "Waiting for architect",
    "ready_for_dev": "Waiting for dev",
    "ready_for_review": "Waiting for reviewer",
}

NEXT_AGENT = {
    "ready_for_spec": "PM",
    "ready_for_design": "Architect",
    "ready_for_dev": "Dev",
    "ready_for_review": "Reviewer",
    "ready_for_deploy": "Deploy",
}


def load_manifest(path: Path) -> dict:
    with open(path) as f:
        return yaml.safe_load(f)


def get_done_tasks(manifest: dict) -> set[str]:
    return {t["id"] for t in manifest.get("tasks", []) if t.get("status") == DONE_STATUS}


def is_blocked(task: dict, done_ids: set[str]) -> tuple[bool, str]:
    if task.get("blocked_by"):
        return True, task["blocked_by"]
    for dep in task.get("depends_on") or []:
        if dep not in done_ids:
            return True, f"depends on {dep}"
    return False, ""


def fmt_row(cells: list[str], widths: list[int]) -> str:
    return "| " + " | ".join(c.ljust(w) for c, w in zip(cells, widths)) + " |"


def fmt_table(headers: list[str], rows: list[list[str]]) -> list[str]:
    if not rows:
        return []
    widths = [len(h) for h in headers]
    for row in rows:
        for i, cell in enumerate(row):
            widths[i] = max(widths[i], len(cell))
    lines = [
        fmt_row(headers, widths),
        "|" + "|".join("-" * (w + 2) for w in widths) + "|",
    ]
    for row in rows:
        lines.append(fmt_row(row, widths))
    return lines


def run(manifest_path: Path) -> None:
    manifest = load_manifest(manifest_path)
    tasks = manifest.get("tasks", [])
    done_ids = get_done_tasks(manifest)

    in_progress, ready, blocked, done_recent = [], [], [], []

    for task in tasks:
        status = task.get("status", "")
        tid = task.get("id", "")
        name = task.get("name", tid)
        priority = task.get("priority", "")
        assigned = task.get("assigned_to") or "—"
        completed = task.get("completed_date", "")
        tag = (task.get("artifacts") or {}).get("tag", "—")

        if status in IN_PROGRESS_STATUSES:
            in_progress.append([name, STAGE_LABELS.get(status, status), assigned])

        elif status in READY_STATUSES:
            blocked_flag, reason = is_blocked(task, done_ids)
            if blocked_flag:
                blocked.append([name, reason])
            else:
                next_agent = NEXT_AGENT.get(status, "—")
                ready.append([name, next_agent, priority])

        elif status == DONE_STATUS:
            done_recent.append((completed, name, tag))

        elif status == BACKLOG_STATUS:
            _, reason = is_blocked(task, done_ids)
            blocked.append([name, reason or "backlog — needs prioritisation"])

    done_recent.sort(key=lambda x: x[0] or "", reverse=True)
    done_recent = done_recent[:3]

    today = date.today().isoformat()
    print(f"\n## Pipeline Status — {today}\n")

    if in_progress:
        print("### In Progress")
        for line in fmt_table(["Task", "Stage", "Assigned"], in_progress):
            print(line)
        print()

    if ready:
        print("### Ready to Start")
        for line in fmt_table(["Task", "Next agent", "Priority"], ready):
            print(line)
        print()

    if blocked:
        print("### Blocked / Backlog")
        for line in fmt_table(["Task", "Blocked by"], blocked):
            print(line)
        print()

    if done_recent:
        print("### Recently Shipped")
        rows = [[name, completed, tag] for completed, name, tag in done_recent]
        for line in fmt_table(["Task", "Completed", "Tag"], rows):
            print(line)
        print()

    if not any([in_progress, ready, blocked, done_recent]):
        print("No tasks found.\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="Show pipeline status from manifest.yaml")
    parser.add_argument(
        "--manifest",
        type=Path,
        default=DEFAULT_MANIFEST,
        help="Path to manifest.yaml (default: repo root)",
    )
    args = parser.parse_args()

    if not args.manifest.exists():
        print(f"Error: manifest not found at {args.manifest}", file=sys.stderr)
        sys.exit(1)

    run(args.manifest)


if __name__ == "__main__":
    main()
