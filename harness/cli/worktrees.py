"""``harness worktrees`` subcommands — list + cleanup.

Scope is deliberately narrow: walk ``<repo_root>/.worktrees/harness/`` on
disk, then for ``cleanup`` reclaim each candidate via the shared
:func:`harness._git.teardown_worktree` primitive (orphan-safe — it falls
back to ``rmtree`` for a directory whose worktree registration is already
pruned, the cruft a plain ``git worktree remove`` cannot touch). The ``start``
verb has its own :class:`harness.worktree.WorktreeNode` helper for run-time
worktree lifecycle; this CLI surface is the operator/routine housekeeping path.

Filters for ``cleanup``:

* ``--age <duration>`` — remove worktrees whose directory mtime is older
  than the supplied duration (``30m``, ``12h``, ``7d``). Reclaims orphaned
  directories regardless of branch; **retains** the branch (an aged worktree may
  hold unmerged work).
* ``--merged`` — remove worktrees whose branch is fully merged into the repo's
  configured integration base (``branches.integration`` in CONTEXT.md, else the
  origin default, else ``dev`` — CAL-1106), **and delete that merged branch**
  (local, and on ``origin`` if it was pushed) — it is provably integrated, so the
  branch is dead weight (CAL-767).

Without filters, ``cleanup`` is a no-op (it prints "kept" lines so the
operator sees what would have been candidate). The conservative default
matches the harness rule "never assume uncommitted work is stale".

**#235 — a "merged" branch is not always safe to delete.** ``git merge-base
--is-ancestor`` is true both for a branch that genuinely landed *and* for a
fresh run branch that has made zero commits yet — its tip trivially equals the
base. A run whose WIP is ``git stash``'d rather than committed looks exactly
like the second case, so ``--merged`` could delete a live run's worktree and
branch out from under it. Before honouring an ancestry-true match, ``--merged``
now runs three vetoes and takes the first hit:

1. **Ledger** — the run's ``runs`` row (matched by ``worktree_path`` first,
   then by ``run_id``) has a non-terminal status
   (:data:`harness.state.schema.IN_FLIGHT_STATUSES`).
2. **Stash** — ``git stash list`` in the worktree has an entry for this branch.
3. **Dirty tree** — the worktree has uncommitted changes
   (:func:`harness.close_merge.worktree_porcelain`).

A vetoed worktree is kept (the reason is printed) unless ``--force`` is given,
which removes it anyway and names what it overrode. ``--age`` is untouched by
any of this — it exists specifically to reclaim the directories of runs that
never closed (whose ledger rows can stay non-terminal forever), so vetoing
there would re-open the cruft leak CAL-767 closed; it also never touches the
branch or ``refs/stash``.
"""

from __future__ import annotations

import asyncio
import json
import re
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import typer

from harness._git import (
    preferred_base_ref,
    resolve_base_branch,
    run_git,
    teardown_worktree,
    worktree_toplevel_matches,
)
from harness._time import iso_z, parse_iso_z
from harness.cli._duration import _parse_duration
from harness.cli._repo import (
    REPO_OPTION_HELP,
    repo_arg_or_cwd,
    resolve_verb_db_path,
)
from harness.close_merge import CloseMergeError, worktree_porcelain
from harness.identity import WORKTREES_SUBDIR
from harness.state import store
from harness.state.schema import IN_FLIGHT_STATUSES

worktrees_app = typer.Typer(
    help="Inspect or clean up worktrees under .worktrees/harness/",
    no_args_is_help=True,
)


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
    repo: Path | None = typer.Option(
        None,
        "--repo",
        "--repo-root",
        help=REPO_OPTION_HELP,
    ),
    json_output: bool = typer.Option(
        False, "--json", help="Emit machine-readable JSON."
    ),
) -> None:
    """List worktrees discovered under ``<repo_root>/.worktrees/harness/``."""
    repo_root = repo_arg_or_cwd(repo)
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
    """Return True if ``branch`` is fully merged into the repo's integration base.

    The base is resolved from the repo's branch model (CAL-1106) —
    ``branches.integration`` in CONTEXT.md, else the origin default branch, else
    ``dev`` — rather than a hardcoded ``dev``/``main``/``master`` set that never
    reclaimed a ``trunk``/``develop`` repo's worktrees. Ancestry is checked against
    ``origin/<base>`` when it resolves (CAL-1154, Option 1): since ``close`` merges
    in a throwaway worktree and pushes ``origin/<base>`` without advancing the local
    branch, a just-closed run is merged into ``origin/<base>`` but *not* local
    ``<base>`` — checking the local branch would leave it forever unreclaimed.
    Falls back to the local base for offline / no-origin repos
    (:func:`~harness._git.preferred_base_ref`).

    ``--merged`` is conservative: an absent branch ref (or an unreadable base)
    counts as not-merged so we never remove a worktree whose ref state we can't
    read.
    """
    base = preferred_base_ref(repo_root, resolve_base_branch(repo_root))
    proc = run_git(repo_root, "merge-base", "--is-ancestor", branch, base)
    return proc.returncode == 0


class _InFlightRuns:
    """The ledger's non-terminal runs, indexed for the two ways a worktree
    directory maps back to a ``runs`` row: an exact ``worktree_path`` match
    (the authoritative one — ``start`` writes it), falling back to the
    directory name as ``run_id`` (the ``harness/<ULID>`` convention, which
    also covers a row with no ``worktree_path`` recorded)."""

    def __init__(self, rows: list[tuple[str, str | None, str]]) -> None:
        self._by_run_id = {run_id: status for run_id, _path, status in rows}
        self._by_path = {
            Path(path).resolve(): (run_id, status)
            for run_id, path, status in rows
            if path is not None
        }

    def veto(self, run_id: str, worktree_path: Path) -> str | None:
        hit = self._by_path.get(worktree_path.resolve())
        if hit is not None:
            matched_run_id, matched_status = hit
            return f"run {matched_run_id} in flight (status={matched_status})"
        by_id_status = self._by_run_id.get(run_id)
        if by_id_status is not None:
            return f"run {run_id} in flight (status={by_id_status})"
        return None


async def _in_flight_runs_async(db_path: Path) -> _InFlightRuns:
    # The placeholder count comes from the fixed local IN_FLIGHT_STATUSES
    # frozenset, never from request/tracker input — bound parameters carry
    # the actual values, so this is not a string-built query.
    placeholders = ",".join("?" for _ in IN_FLIGHT_STATUSES)
    query = f"SELECT run_id, worktree_path, status FROM runs WHERE status IN ({placeholders})"  # noqa: S608
    async with store.connect(db_path) as conn:
        cursor = await conn.execute(query, tuple(IN_FLIGHT_STATUSES))
        rows = await cursor.fetchall()
    return _InFlightRuns([(str(r[0]), r[1], str(r[2])) for r in rows])


def _in_flight_runs(db_path: Path) -> _InFlightRuns:
    """The ledger's non-terminal runs — a no-op lookup when the DB is absent.

    #235: a worktree's branch can be a trivial merge-base ancestor of the
    integration branch simply because the run hasn't committed anything yet
    (WIP stashed, not committed) — ``git`` ancestry alone can't tell that
    apart from a genuinely-landed, safe-to-delete branch. The ledger's run
    status is the authoritative "is this run still in flight" signal (the
    same one ``close`` and ``reclaim`` use). An absent DB (the fresh-container
    regime, or a repo never driven by the harness) has no opinion — it is not
    itself a veto, since the other two probes (stash / dirty tree) still
    guard that case, and vetoing on absence alone would turn every sweep into
    a no-op there.
    """
    if not db_path.exists():
        return _InFlightRuns([])
    return asyncio.run(_in_flight_runs_async(db_path))


_STASH_SUBJECT_RE = re.compile(r"^(?:WIP on|On) (?P<branch>.+):")


def _stash_veto(worktree_path: Path, branch: str) -> str | None:
    """A ``git stash`` entry for ``branch`` in ``worktree_path`` is a veto —
    it is uncommitted WIP a ``--merged`` delete would destroy with no
    recovery path beyond dangling-object forensics (the exact #235 repro)."""
    if not worktree_toplevel_matches(worktree_path):
        return None
    proc = run_git(worktree_path, "stash", "list", "--format=%gd%x09%gs")
    if proc.returncode != 0:
        return f"could not verify worktree state: {proc.stderr.strip()}"
    for line in proc.stdout.splitlines():
        selector, _, subject = line.partition("\t")
        match = _STASH_SUBJECT_RE.match(subject)
        if match is not None and match.group("branch") == branch:
            return f"stashed WIP on {branch} ({selector})"
    return None


def _dirty_veto(worktree_path: Path) -> str | None:
    """Uncommitted changes in ``worktree_path`` are a veto — ``teardown_worktree``
    uses ``git worktree remove --force``, which would discard them silently."""
    if not worktree_toplevel_matches(worktree_path):
        return None
    try:
        porcelain = worktree_porcelain(worktree_path)
    except CloseMergeError as exc:
        return f"could not verify worktree state: {exc}"
    if porcelain:
        return "uncommitted changes in the worktree"
    return None


def _merge_veto(
    in_flight: _InFlightRuns, run_id: str, worktree_path: Path, branch: str
) -> str | None:
    """The first of the three #235 probes (ledger, stash, dirty tree) to
    object to reclaiming this merged worktree, or ``None`` if none does."""
    return (
        in_flight.veto(run_id, worktree_path)
        or _stash_veto(worktree_path, branch)
        or _dirty_veto(worktree_path)
    )


@worktrees_app.command(
    "cleanup", help="Remove worktrees matching the supplied filters."
)
def cleanup_command(
    repo: Path | None = typer.Option(
        None,
        "--repo",
        "--repo-root",
        help=REPO_OPTION_HELP,
    ),
    age: str | None = typer.Option(
        None, "--age", help="Remove worktrees older than this (e.g. 30m / 12h / 7d)."
    ),
    merged: bool = typer.Option(
        False,
        "--merged",
        help=(
            "Remove worktrees whose branch is merged into the repo's configured "
            "integration base (CONTEXT.md branches.integration, else the origin "
            "default, else dev), and delete that merged branch (local + remote). "
            "Skips a worktree whose run is still in flight, has a stash, or has "
            "uncommitted changes (#235) unless --force is given."
        ),
    ),
    force: bool = typer.Option(
        False,
        "--force",
        help="Remove a --merged candidate despite an in-flight/stash/dirty veto (#235).",
    ),
    db: Path | None = typer.Option(
        None, "--db", help="Path to harness.db (defaults to .harness/harness.db)."
    ),
) -> None:
    """Remove worktrees matching ``--age`` / ``--merged``."""
    repo_root = repo_arg_or_cwd(repo)
    items = _discover_worktrees(repo_root)
    if not items:
        typer.echo("(no worktrees)")
        return

    cutoff: datetime | None = None
    if age is not None:
        cutoff = datetime.now(UTC) - _parse_duration(age)

    in_flight = (
        _in_flight_runs(resolve_verb_db_path(db, repo_root)) if merged else _InFlightRuns([])
    )

    removed: list[tuple[str, str | None]] = []
    kept: list[tuple[str, str | None]] = []
    failures: list[tuple[str, str]] = []

    for item in items:
        run_id = str(item["run_id"])
        path = Path(str(item["path"]))
        last_modified = parse_iso_z(str(item["last_modified"]))
        branch = item.get("branch")
        branch_str = branch if isinstance(branch, str) else None

        should_remove = False
        # Only delete the branch when removal is driven by ``--merged`` — the
        # branch is provably integrated, so it is safe. An ``--age`` removal
        # retains the branch (an aged worktree may still hold unmerged work).
        delete_branch = False
        veto: str | None = None
        forced_over: str | None = None
        if cutoff is not None and last_modified < cutoff:
            should_remove = True
        if merged and branch_str is not None and _branch_merged_into_base(repo_root, branch_str):
            veto = _merge_veto(in_flight, run_id, path, branch_str)
            if veto is None:
                should_remove = True
                delete_branch = True
            elif force:
                should_remove = True
                delete_branch = True
                forced_over = veto

        if not should_remove:
            note = f"merged, but {veto}" if veto is not None else None
            kept.append((run_id, note))
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
                (run_id, "worktree directory still present after removal")
            )
        else:
            note = f"forced over: {forced_over}" if forced_over is not None else None
            removed.append((run_id, note))

    for run_id, note in removed:
        suffix = f" ({note})" if note is not None else ""
        typer.echo(f"removed {run_id}{suffix}")
    for run_id, note in kept:
        suffix = f" ({note})" if note is not None else ""
        typer.echo(f"kept    {run_id}{suffix}")
    for run_id, err in failures:
        typer.echo(f"failed  {run_id}: {err}", err=True)

    if failures:
        raise typer.Exit(code=1)
