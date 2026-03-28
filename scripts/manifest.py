#!/usr/bin/env python3
"""
manifest.py — CLI for reading and updating manifest.yaml without stripping comments.

All writes use targeted line replacement to preserve the file's comment structure.

Usage:
    python scripts/manifest.py show <task-id>
    python scripts/manifest.py status <task-id> <new-status>
    python scripts/manifest.py assign <task-id> <agent>
    python scripts/manifest.py clear <task-id>
    python scripts/manifest.py check-deps <task-id>
    python scripts/manifest.py list-ids
"""

import argparse
import re
import sys
from datetime import date
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).parent.parent
DEFAULT_MANIFEST = REPO_ROOT / "manifest.yaml"

VALID_STATUSES = {
    "backlog",
    "ready_for_spec",
    "specifying",
    "ready_for_design",
    "designing",
    "ready_for_dev",
    "building",
    "ready_for_review",
    "reviewing",
    "ready_for_deploy",
    "done",
}


# ---------------------------------------------------------------------------
# YAML read (pyyaml, data only — no writes via this path)
# ---------------------------------------------------------------------------

def load_manifest(path: Path) -> dict:
    with open(path) as f:
        return yaml.safe_load(f)


def find_task(manifest: dict, task_id: str) -> dict | None:
    for task in manifest.get("tasks", []):
        if task.get("id") == task_id:
            return task
    return None


# ---------------------------------------------------------------------------
# Comment-preserving line replacement
#
# Strategy: scan line-by-line through the raw file. When we're inside the
# target task's block (between "  - id: <task-id>" and the next "  - id: "
# or end-of-file), do targeted line substitution.
# ---------------------------------------------------------------------------

def _in_task_block(lines: list[str], task_id: str) -> tuple[int, int]:
    """Return (start, end) line indices (exclusive end) for the given task block."""
    start = None
    id_pattern = re.compile(r"^  - id:\s*" + re.escape(task_id) + r"\s*$")
    next_task_pattern = re.compile(r"^  - id:\s*\S")

    for i, line in enumerate(lines):
        if id_pattern.match(line):
            start = i
        elif start is not None and next_task_pattern.match(line) and i > start:
            return start, i

    if start is not None:
        return start, len(lines)
    return -1, -1


def _replace_field_in_block(
    lines: list[str],
    start: int,
    end: int,
    field: str,
    new_value: str,
) -> tuple[list[str], bool]:
    """Replace '    field: <anything>' within the block. Returns (lines, replaced)."""
    pattern = re.compile(r"^    " + re.escape(field) + r":\s*.*$")
    for i in range(start, end):
        if pattern.match(lines[i]):
            lines[i] = f"    {field}: {new_value}"
            return lines, True
    return lines, False


def _insert_after_field(
    lines: list[str],
    start: int,
    end: int,
    after_field: str,
    new_field: str,
    new_value: str,
) -> list[str]:
    """Insert '    new_field: value' after the first occurrence of after_field in the block."""
    pattern = re.compile(r"^    " + re.escape(after_field) + r":\s*")
    for i in range(start, end):
        if pattern.match(lines[i]):
            lines.insert(i + 1, f"    {new_field}: {new_value}")
            return lines
    return lines


def read_raw(path: Path) -> list[str]:
    return path.read_text().splitlines()


def write_raw(path: Path, lines: list[str]) -> None:
    path.write_text("\n".join(lines) + "\n")


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

def cmd_show(args: argparse.Namespace) -> int:
    manifest = load_manifest(args.manifest)
    task = find_task(manifest, args.task_id)
    if task is None:
        print(f"Error: task '{args.task_id}' not found.", file=sys.stderr)
        return 1

    print(f"\nTask: {task.get('name', args.task_id)}")
    print(f"  id:          {task.get('id')}")
    print(f"  status:      {task.get('status')}")
    print(f"  priority:    {task.get('priority', '—')}")
    print(f"  assigned_to: {task.get('assigned_to') or '—'}")
    print(f"  product:     {task.get('product', '—')}")
    if task.get("completed_date"):
        print(f"  completed:   {task['completed_date']}")
    if task.get("depends_on"):
        print(f"  depends_on:  {', '.join(task['depends_on'])}")
    if task.get("description"):
        desc = task["description"].strip().replace("\n", " ")
        if len(desc) > 120:
            desc = desc[:117] + "..."
        print(f"  description: {desc}")
    print()
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    new_status = args.new_status
    if new_status not in VALID_STATUSES:
        valid = ", ".join(sorted(VALID_STATUSES))
        print(f"Error: '{new_status}' is not a valid status. Valid: {valid}", file=sys.stderr)
        return 1

    manifest = load_manifest(args.manifest)
    task = find_task(manifest, args.task_id)
    if task is None:
        print(f"Error: task '{args.task_id}' not found.", file=sys.stderr)
        return 1

    old_status = task.get("status")
    lines = read_raw(args.manifest)
    start, end = _in_task_block(lines, args.task_id)
    if start == -1:
        print(f"Error: could not locate task block for '{args.task_id}'.", file=sys.stderr)
        return 1

    lines, replaced = _replace_field_in_block(lines, start, end, "status", new_status)
    if not replaced:
        print("Error: 'status' field not found in task block.", file=sys.stderr)
        return 1

    # Auto-actions on done: clear assigned_to, set completed_date
    if new_status == "done":
        lines, _ = _replace_field_in_block(lines, start, end, "assigned_to", "null")
        today = date.today().isoformat()
        lines, found = _replace_field_in_block(lines, start, end, "completed_date", f'"{today}"')
        if not found:
            lines = _insert_after_field(lines, start, end, "status", "completed_date", f'"{today}"')

    write_raw(args.manifest, lines)
    print(f"{args.task_id}: {old_status} → {new_status}")
    if new_status == "done":
        print(f"  assigned_to cleared, completed_date set to {date.today().isoformat()}")
    return 0


def cmd_assign(args: argparse.Namespace) -> int:
    manifest = load_manifest(args.manifest)
    task = find_task(manifest, args.task_id)
    if task is None:
        print(f"Error: task '{args.task_id}' not found.", file=sys.stderr)
        return 1

    lines = read_raw(args.manifest)
    start, end = _in_task_block(lines, args.task_id)
    if start == -1:
        print(f"Error: could not locate task block for '{args.task_id}'.", file=sys.stderr)
        return 1

    lines, replaced = _replace_field_in_block(lines, start, end, "assigned_to", args.agent)
    if not replaced:
        print("Error: 'assigned_to' field not found in task block.", file=sys.stderr)
        return 1

    write_raw(args.manifest, lines)
    print(f"{args.task_id}: assigned_to → {args.agent}")
    return 0


def cmd_clear(args: argparse.Namespace) -> int:
    manifest = load_manifest(args.manifest)
    task = find_task(manifest, args.task_id)
    if task is None:
        print(f"Error: task '{args.task_id}' not found.", file=sys.stderr)
        return 1

    lines = read_raw(args.manifest)
    start, end = _in_task_block(lines, args.task_id)
    if start == -1:
        print(f"Error: could not locate task block for '{args.task_id}'.", file=sys.stderr)
        return 1

    lines, replaced = _replace_field_in_block(lines, start, end, "assigned_to", "null")
    if not replaced:
        print("Error: 'assigned_to' field not found in task block.", file=sys.stderr)
        return 1

    write_raw(args.manifest, lines)
    print(f"{args.task_id}: assigned_to cleared")
    return 0


def cmd_check_deps(args: argparse.Namespace) -> int:
    manifest = load_manifest(args.manifest)
    task = find_task(manifest, args.task_id)
    if task is None:
        print(f"Error: task '{args.task_id}' not found.", file=sys.stderr)
        return 1

    deps = task.get("depends_on") or []
    if not deps:
        print(f"{args.task_id}: no dependencies.")
        return 0

    done_ids = {t["id"] for t in manifest.get("tasks", []) if t.get("status") == "done"}
    all_clear = True
    for dep in deps:
        dep_task = find_task(manifest, dep)
        if dep_task is None:
            print(f"  MISSING  {dep} (not found in manifest)")
            all_clear = False
        elif dep not in done_ids:
            status = dep_task.get("status", "unknown")
            print(f"  BLOCKED  {dep} ({status})")
            all_clear = False
        else:
            print(f"  OK       {dep}")

    if all_clear:
        print(f"\n{args.task_id}: all dependencies satisfied.")
        return 0
    else:
        print(f"\n{args.task_id}: blocked — resolve dependencies above before starting.")
        return 1


def cmd_list_ids(args: argparse.Namespace) -> int:
    manifest = load_manifest(args.manifest)
    tasks = manifest.get("tasks", [])
    if not tasks:
        print("No tasks found.")
        return 0

    for task in tasks:
        tid = task.get("id", "?")
        status = task.get("status", "?")
        name = task.get("name", "")
        print(f"  {tid:<30} {status:<20} {name}")
    return 0


# ---------------------------------------------------------------------------
# CLI wiring
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Read and update manifest.yaml (comment-preserving).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Commands:
  show <task-id>                    Print task details
  status <task-id> <new-status>     Update task status (auto-handles done cleanup)
  assign <task-id> <agent>          Set assigned_to
  clear <task-id>                   Clear assigned_to (set to null)
  check-deps <task-id>              Verify all depends_on tasks are done
  list-ids                          List all task IDs with status
        """,
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        default=DEFAULT_MANIFEST,
        help="Path to manifest.yaml (default: repo root)",
    )
    subparsers = parser.add_subparsers(dest="command", metavar="command")

    p_show = subparsers.add_parser("show", help="Print task details")
    p_show.add_argument("task_id")

    p_status = subparsers.add_parser("status", help="Update task status")
    p_status.add_argument("task_id")
    p_status.add_argument("new_status")

    p_assign = subparsers.add_parser("assign", help="Set assigned_to")
    p_assign.add_argument("task_id")
    p_assign.add_argument("agent")

    p_clear = subparsers.add_parser("clear", help="Clear assigned_to")
    p_clear.add_argument("task_id")

    p_deps = subparsers.add_parser("check-deps", help="Check dependency status")
    p_deps.add_argument("task_id")

    subparsers.add_parser("list-ids", help="List all task IDs with status")

    args = parser.parse_args()

    if args.command is None:
        parser.print_help()
        sys.exit(0)

    if not args.manifest.exists():
        print(f"Error: manifest not found at {args.manifest}", file=sys.stderr)
        sys.exit(1)

    dispatch = {
        "show": cmd_show,
        "status": cmd_status,
        "assign": cmd_assign,
        "clear": cmd_clear,
        "check-deps": cmd_check_deps,
        "list-ids": cmd_list_ids,
    }

    sys.exit(dispatch[args.command](args))


if __name__ == "__main__":
    main()
