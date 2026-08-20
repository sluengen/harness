#!/usr/bin/env python3
"""The gate marker — the one artifact that says *the gate ran green over these
exact bytes*.

``scripts/verify.sh`` runs this on its success path. It computes the git **tree
object** of the working tree it was run in and writes

    <git-common-dir>/harness/gate/<tree-oid>.json

Two Claude Code hooks read that file from opposite sides of one equality:
``hooks/gate-evidence-guard.js`` (Stop) asks *does a marker cover the tree this
turn is claiming is finished?*, and ``hooks/push-target-guard.js`` (PreToolUse)
asks *does a marker cover the tree this push carries?*. ``commands/build.md``
already makes those the same object — its ship step refuses to integrate unless
``git rev-parse HEAD^{tree}`` equals the tree the gate ran over — so one marker
authorises both.

**Why a tree and not a session.** ``verify.sh`` has no access to a session
identifier, and enforcement will not be built on an undocumented one. Tree
identity is the stronger claim on the axis that matters anyway: session scope
answers *did someone run the gate recently in this conversation*, which a
session that edited three files after the run still satisfies; tree identity
answers *did the gate exit 0 over these exact bytes*, which no subsequent edit
can satisfy. What it gives up, stated plainly: a marker produced by an earlier
session over an identical tree is admitted. The claim that licenses ("the gate
is green on this tree") is still true; what is not proven is that this session
watched it happen.

**Why the git directory and not the working tree.** ``.harness/`` is gitignored
*in this repo*. In a consuming repo without that rule, a marker written into the
working tree would be picked up by the very ``git add -A`` that computes the
tree, moving the OID away from the one just recorded — a marker that can never
match, i.e. a silent, permanent fail-closed wedge in exactly the repos that
skipped an install step. The git common directory cannot be tracked by
construction, is shared across every linked worktree automatically, needs no
``.gitignore`` change anywhere, and disappears with the clone.

**Why the filename carries the claim.** The decision predicate is
``exists(path)`` plus its mtime. No hook parses the body, which is diagnostics.
That removes a class of parse-failure ambiguity from two enforcement paths, and
it is honest: anyone who can write the file can write valid JSON, so parsing
buys nothing.

**What this is not.** Evidence plumbing, not an authority. Any process with
write access to the repository can create a marker by hand, and the hooks run in
the same trust domain as the agent they check. The authoritative controls remain
server-side branch protection and the gate output in CI. What this buys is that
the *default* path now requires the gate to have actually run over the exact
bytes being claimed, and that manufacturing the evidence is a discrete,
deliberate, transcript-visible act rather than a silent omission.

Subcommands::

    gate_marker.py preflight          # reject Git-visible nested worktrees
    gate_marker.py write              # the gate's success path
    gate_marker.py tree               # the tree oid of the current worktree
    gate_marker.py path --tree <oid>  # where that tree's marker would live

Stdlib only, like everything else in ``scripts/``: a gate that needs a
dependency to run is a gate that can fail for reasons unrelated to the tree.
"""

from __future__ import annotations

import argparse
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path

#: Bumped when the payload shape changes. The hooks do not read it — they do not
#: read the body at all — so this is for a human reading a marker, and for a
#: future writer that needs to tell two shapes apart.
SCHEMA = 1

#: Recorded in the payload so a marker names what produced it.
WRITER = "gate_marker.py@0.1.0"

#: The freshness bound, in seconds. Its purpose is **toolchain drift under an
#: unchanged tree** — the venv is not in the tree, ``uv.lock`` is — not session
#: scope. A day is long enough that an ordinary attended session never re-runs
#: the gate for age alone, and short enough that a marker from last week does
#: not license a claim about a toolchain that has since moved.
DEFAULT_MAX_AGE_SECONDS = 86400
MAX_AGE_ENV = "HARNESS_GATE_MARKER_MAX_AGE_SECONDS"

#: How many markers survive a prune. The directory is a cache, not a ledger:
#: ADR 0015 retired the run ledger and this change does not revive it.
KEEP = 50

#: Where the markers live, relative to the git common directory.
MARKER_SUBDIR = ("harness", "gate")


class GitError(RuntimeError):
    """A git invocation this module needs did not succeed.

    Raised rather than degraded to a default: a gate that cannot compute the
    tree it verified must say so, not quietly record the wrong one.
    """


def git(args: Sequence[str], cwd: Path, *, env: Mapping[str, str] | None = None) -> str:
    """Run ``git <args>`` in ``cwd`` and return its trimmed stdout.

    Raises :class:`GitError` on a non-zero exit, carrying git's own stderr —
    the caller has no better diagnosis to offer than the one git already wrote.
    """
    completed = subprocess.run(  # noqa: S603 - list form, shell=False, argv[0] is literal
        ["git", *args],  # noqa: S607 - `git` from PATH, as every other caller here
        cwd=cwd,
        capture_output=True,
        text=True,
        env={**os.environ, **(env or {})},
    )
    if completed.returncode != 0:
        raise GitError(
            f"git {' '.join(args)} failed in {cwd} "
            f"(exit {completed.returncode}): {completed.stderr.strip()}"
        )
    return completed.stdout.strip()


def git_common_dir(cwd: Path) -> Path:
    """The git directory shared by every worktree of this repository.

    ``--path-format=absolute`` is the spelling ``skills/worktree-isolation``
    already uses; without it a linked worktree answers with a relative path
    whose meaning depends on the caller's cwd.
    """
    return Path(git(["rev-parse", "--path-format=absolute", "--git-common-dir"], cwd)).resolve()


def marker_dir(cwd: Path) -> Path:
    """The directory holding this repository's gate markers."""
    return git_common_dir(cwd).joinpath(*MARKER_SUBDIR)


def marker_path(tree: str, cwd: Path) -> Path:
    """Where the marker for ``tree`` lives. The filename is the whole claim."""
    return marker_dir(cwd) / f"{tree}.json"


def current_tree(cwd: Path) -> str:
    """The git tree object of ``cwd``'s working tree, including uncommitted work.

    Computed against a **temporary index**, so the gate stages nothing as a side
    effect. ``git add -A`` honours ``.gitignore``, so ``gate.log``, ``.evidence/``,
    ``.harness/`` and the venv are excluded exactly as they are excluded from any
    commit — which is what keeps a marker from going stale the moment the gate
    writes its own log.

    The temporary index lives in the marker directory rather than ``TMPDIR``:
    the git directory is guaranteed to exist wherever this can run at all, and
    the location cannot affect the resulting oid.

    Side effect worth naming: this writes blobs and trees into the object
    database (loose, gc-able). ``commands/build.md`` already does the same thing
    in the *real* index when it computes ``certified_tree``.
    """
    scratch = marker_dir(cwd)
    scratch.mkdir(parents=True, exist_ok=True)
    handle, index = tempfile.mkstemp(prefix=".index-", dir=scratch)
    os.close(handle)
    # mkstemp creates the file; git wants to create it itself, and an empty
    # file is not a valid index.
    os.unlink(index)
    env = {"GIT_INDEX_FILE": index}
    try:
        try:
            git(["read-tree", "HEAD"], cwd, env=env)
        except GitError:
            # No commits yet: start from an empty index rather than failing the
            # gate on a repository that simply has no history.
            git(["read-tree", "--empty"], cwd, env=env)
        git(["add", "-A"], cwd, env=env)
        return git(["write-tree"], cwd, env=env)
    finally:
        Path(index).unlink(missing_ok=True)


def _git_status(args: Sequence[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    """Run a Git predicate whose non-zero status can be an ordinary answer."""
    return subprocess.run(  # noqa: S603 - shell-free argument vector
        ["git", *args],  # noqa: S607 - same PATH contract as :func:`git`
        cwd=cwd,
        capture_output=True,
        text=True,
        env=os.environ,
    )


def preflight(cwd: Path) -> None:
    """Refuse registered nested worktrees that Git can sweep into the root.

    The check is deliberately before :func:`current_tree`: materializing the
    tree is the operation whose ``git add -A`` would absorb a visible nested
    worktree. Only other registered worktrees strictly beneath this checkout
    are relevant; siblings and parents cannot be descendants of its index.
    """
    root = Path(git(["rev-parse", "--show-toplevel"], cwd)).resolve()
    listing = git(["worktree", "list", "--porcelain", "-z"], cwd)
    for field in listing.split("\0"):
        if not field.startswith("worktree "):
            continue
        candidate = Path(field.removeprefix("worktree ")).resolve()
        try:
            candidate.relative_to(root)
        except ValueError:
            continue
        if candidate == root:
            continue
        if not candidate.exists():
            continue
        ignored = _git_status(["check-ignore", "--quiet", "--", str(candidate)], root)
        if ignored.returncode == 0:
            continue
        if ignored.returncode != 1:
            raise GitError(
                f"git check-ignore failed for registered nested worktree {candidate} "
                f"(exit {ignored.returncode}): {ignored.stderr.strip()}"
            )
        raise GitError(
            f"registered nested worktree is visible to git: {candidate}; ignore its "
            "parent (normally .worktrees/ or .claude/worktrees/) before running the gate"
        )


def max_age_seconds(env: Mapping[str, str]) -> int:
    """The freshness bound ``env`` asks for, or the default.

    Both hooks re-implement this parse, so the degenerate cases need one agreed
    answer. An unusable value reads as *unset*: reading it as "never fresh"
    would wedge every session behind a gate run that can never satisfy it, and
    reading it as "always fresh" would disarm the bound silently. Neither
    failure is worth inheriting from a typo in an environment variable.
    """
    raw = env.get(MAX_AGE_ENV, "")
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return DEFAULT_MAX_AGE_SECONDS
    return value if value > 0 else DEFAULT_MAX_AGE_SECONDS


def prune(directory: Path, *, max_age: int, keep: int, now: float | None = None) -> None:
    """Drop markers past ``max_age``, then all but the ``keep`` newest.

    Best-effort by design: a marker that vanished under us (a concurrent prune
    from another worktree) is not an error, and a prune failure must never fail
    a gate run that already passed.
    """
    moment = time.time() if now is None else now
    markers = sorted(directory.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    for index, marker in enumerate(markers):
        expired = moment - marker.stat().st_mtime > max_age
        if expired or index >= keep:
            marker.unlink(missing_ok=True)


def write_marker(cwd: Path, *, exit_code: int = 0) -> Path:
    """Record that the gate exited ``exit_code`` over ``cwd``'s current tree.

    Called only on green. The body is diagnostics for a human; the *filename* is
    the claim the hooks read.
    """
    tree = current_tree(cwd)
    path = marker_path(tree, cwd)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema": SCHEMA,
        "tree": tree,
        "head": _head(cwd),
        "branch": _branch(cwd),
        "worktree": str(Path(git(["rev-parse", "--show-toplevel"], cwd)).resolve()),
        "gate": "bash scripts/verify.sh",
        "exit": exit_code,
        "finished_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "epoch": int(time.time()),
        "host": socket.gethostname(),
        "writer": WRITER,
    }
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    prune(path.parent, max_age=max_age_seconds(os.environ), keep=KEEP)
    return path


def _head(cwd: Path) -> str:
    """``HEAD``'s commit, or the empty string in a repository with no commits."""
    try:
        return git(["rev-parse", "HEAD"], cwd)
    except GitError:
        return ""


def _branch(cwd: Path) -> str:
    """The checked-out branch, or ``HEAD`` when detached."""
    try:
        return git(["rev-parse", "--abbrev-ref", "HEAD"], cwd)
    except GitError:
        return ""


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__ and __doc__.splitlines()[0])
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("preflight", help="reject Git-visible registered nested worktrees")
    subparsers.add_parser("write", help="record a green gate run over the current tree")
    subparsers.add_parser("tree", help="print the tree oid of the current worktree")
    path_parser = subparsers.add_parser("path", help="print where a tree's marker lives")
    path_parser.add_argument("--tree", required=True, help="the tree oid")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    cwd = Path.cwd()
    try:
        if args.command == "preflight":
            preflight(cwd)
        elif args.command == "write":
            path = write_marker(cwd)
            # The filename is the claim, so the announcement reads it back off
            # the path rather than recomputing the tree — two computations here
            # could disagree, and the one that matters is the one on disk.
            print(f"gate marker: {path.stem} -> {path}")
        elif args.command == "tree":
            print(current_tree(cwd))
        else:
            print(marker_path(args.tree, cwd))
    except GitError as err:
        print(f"gate_marker: {err}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
