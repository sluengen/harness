"""``harness worktrees`` subcommands — list + cleanup.

Scope is deliberately narrow: walk ``<repo_root>/.worktrees/harness/`` on
disk, then for ``cleanup`` reclaim each candidate via the shared
:func:`harness.cli._git.teardown_worktree` primitive (orphan-safe — it falls
back to ``rmtree`` for a directory whose worktree registration is already
pruned, the cruft a plain ``git worktree remove`` cannot touch). The ``start``
verb has its own :class:`harness.worktree.WorktreeNode` helper for run-time
worktree lifecycle; this CLI surface is the operator/routine housekeeping path.

Filters for ``cleanup``:

* ``--age <duration>`` — remove worktrees whose directory mtime is older
  than the supplied duration (``30m``, ``12h``, ``7d``). Reclaims orphaned
  directories regardless of branch; **retains** the branch (an aged worktree may
  hold unmerged work).
* ``--merged`` — remove worktrees whose branch is fully merged into
  ``dev``, ``main``, or ``master`` (the integration/release bases), **and delete
  that merged branch** (local, and on ``origin`` if it was pushed) — it is
  provably integrated, so the branch is dead weight (CAL-767).

Without filters, ``cleanup`` is a no-op (it prints "kept" lines so the
operator sees what would have been candidate). The conservative default
matches the harness rule "never assume uncommitted work is stale".
"""

from __future__ import annotations

import json
import re
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path

import typer

from harness._time import iso_z, parse_iso_z
from harness.cli._git import run_git, teardown_worktree
from harness.identity import WORKTREES_SUBDIR

worktrees_app = typer.Typer(
    help="Inspect or clean up worktrees under .worktrees/harness/",
    no_args_is_help=True,
)


# ---------------------------------------------------------------------------
# Duration parsing — accept ``30m``, ``12h``, ``7d``
# ---------------------------------------------------------------------------


_DURATION_RE = re.compile(r"^(?P<value>\d+)\s*(?P<unit>[smhd])$")


def _parse_duration(text: str) -> timedelta:
    """Parse a short duration string. Raises :class:`typer.BadParameter` on
    bad input so the CLI exits 2 with a clear message."""
    match = _DURATION_RE.match(text.strip())
    if not match:
        raise typer.BadParameter(
            f"invalid duration {text!r}; expected forms like '30m', '12h', '7d'"
        )
    value = int(match.group("value"))
    unit = match.group("unit")
    if unit == "s":
        return timedelta(seconds=value)
    if unit == "m":
        return timedelta(minutes=value)
    if unit == "h":
        return timedelta(hours=value)
    return timedelta(days=value)


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------


def _worktrees_root(repo_root: Path) -> Path:
    return repo_root / WORKTREES_SUBDIR


def _discover_worktrees(repo_root: Path) -> list[dict[str, object]]:
    """Walk ``<repo_root>/.worktrees/harness/`` for child directories.

    Returns a list of ``{"run_id", "path", "last_modified", "branch"}`` —
    one entry per child directory. The branch is inferred via
    ``git worktree list --porcelain`` so we tolerate worktrees that aren't
    on the canonical ``harness/<run_id>`` branch.
    """
    root = _worktrees_root(repo_root)
    if not root.exists():
        return []

    branch_by_path = _git_worktree_branches(repo_root)
    out: list[dict[str, object]] = []
    for child in sorted(root.iterdir()):
        if not child.is_dir():
            continue
        mtime = datetime.fromtimestamp(child.stat().st_mtime, tz=UTC)
        out.append(
            {
                "run_id": child.name,
                "path": str(child),
                "last_modified": iso_z(mtime),
                "branch": branch_by_path.get(child.resolve(), None),
            }
        )
    return out


def _git_worktree_branches(repo_root: Path) -> dict[Path, str]:
    """Parse ``git worktree list --porcelain`` and return a map of
    absolute worktree path to branch name."""
    try:
        proc = run_git(repo_root, "worktree", "list", "--porcelain", timeout=15)
    except (OSError, subprocess.SubprocessError):
        return {}
    if proc.returncode != 0:
        return {}

    out: dict[Path, str] = {}
    current_path: Path | None = None
    for line in proc.stdout.splitlines():
        if line.startswith("worktree "):
            current_path = Path(line[len("worktree "):]).resolve()
        elif line.startswith("branch ") and current_path is not None:
            # The porcelain form returns refs/heads/<branch>; strip the prefix.
            ref = line[len("branch "):]
            branch = ref[len("refs/heads/"):] if ref.startswith("refs/heads/") else ref
            out[current_path] = branch
            current_path = None
    return out


# ---------------------------------------------------------------------------
# list
# ---------------------------------------------------------------------------


@worktrees_app.command("list", help="List worktrees under .worktrees/harness/.")
def list_command(
    repo_root: Path = typer.Option(
        Path("."),
        "--repo-root",
        help="Repo root containing .worktrees/harness/.",
    ),
    json_output: bool = typer.Option(
        False, "--json", help="Emit machine-readable JSON."
    ),
) -> None:
    """List worktrees discovered under ``<repo_root>/.worktrees/harness/``."""
    items = _discover_worktrees(repo_root)
    if json_output:
        typer.echo(json.dumps(items, default=str))
        return
    if not items:
        typer.echo("(no worktrees)")
        return
    for item in items:
        branch = item.get("branch") or "-"
        typer.echo(
            f"{item['run_id']}\t{item['last_modified']}\t{branch}\t{item['path']}"
        )


# ---------------------------------------------------------------------------
# cleanup
# ---------------------------------------------------------------------------


def _branch_merged_into_base(repo_root: Path, branch: str) -> bool:
    """Return True if ``branch`` is fully merged into ``dev``, ``main``, or ``master``.

    ``--merged`` is conservative: an absent branch ref counts as not-merged
    so we never remove a worktree whose ref state we can't read.
    """
    for base in ("dev", "main", "master"):
        proc = run_git(repo_root, "merge-base", "--is-ancestor", branch, base)
        if proc.returncode == 0:
            return True
    return False


@worktrees_app.command(
    "cleanup", help="Remove worktrees matching the supplied filters."
)
def cleanup_command(
    repo_root: Path = typer.Option(
        Path("."),
        "--repo-root",
        help="Repo root containing .worktrees/harness/.",
    ),
    age: str | None = typer.Option(
        None, "--age", help="Remove worktrees older than this (e.g. 30m / 12h / 7d)."
    ),
    merged: bool = typer.Option(
        False,
        "--merged",
        help=(
            "Remove worktrees whose branch is merged into dev, main, or master, "
            "and delete that merged branch (local + remote)."
        ),
    ),
) -> None:
    """Remove worktrees matching ``--age`` / ``--merged``."""
    items = _discover_worktrees(repo_root)
    if not items:
        typer.echo("(no worktrees)")
        return

    cutoff: datetime | None = None
    if age is not None:
        cutoff = datetime.now(UTC) - _parse_duration(age)

    removed: list[str] = []
    kept: list[str] = []
    failures: list[tuple[str, str]] = []

    for item in items:
        path = Path(str(item["path"]))
        last_modified = parse_iso_z(str(item["last_modified"]))
        branch = item.get("branch")
        branch_str = branch if isinstance(branch, str) else None

        should_remove = False
        # Only delete the branch when removal is driven by ``--merged`` — the
        # branch is provably integrated, so it is safe. An ``--age`` removal
        # retains the branch (an aged worktree may still hold unmerged work).
        delete_branch = False
        if cutoff is not None and last_modified < cutoff:
            should_remove = True
        if (
            merged
            and branch_str is not None
            and _branch_merged_into_base(repo_root, branch_str)
        ):
            should_remove = True
            delete_branch = True

        if not should_remove:
            kept.append(str(item["run_id"]))
            continue

        # Orphan-safe removal + optional branch deletion (local + remote). The
        # shared primitive is best-effort, so confirm by checking the directory
        # is actually gone afterwards.
        teardown_worktree(
            repo_root,
            worktree_path=path,
            branch=branch_str if delete_branch else None,
            delete_remote=delete_branch,
        )
        if path.exists():
            failures.append(
                (str(item["run_id"]), "worktree directory still present after removal")
            )
        else:
            removed.append(str(item["run_id"]))

    for run_id in removed:
        typer.echo(f"removed {run_id}")
    for run_id in kept:
        typer.echo(f"kept    {run_id}")
    for run_id, err in failures:
        typer.echo(f"failed  {run_id}: {err}", err=True)

    if failures:
        raise typer.Exit(code=1)
