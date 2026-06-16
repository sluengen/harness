"""Run ID generation and propagation — see SPEC §4.8.

A single ULID generated at workflow start propagates to every surface (worktree
dir, branch, state row, event log, artifacts dir, log file). One ID, one grep.

The ULID format gives us:
- Fixed length (26 chars) — predictable in paths, branch names, log names.
- Crockford base32 alphabet — case-insensitive, omits I/L/O/U for readability.
- Time-ordered prefix — sorts in creation order without a separate timestamp.
"""

from __future__ import annotations

import re
from pathlib import Path

import ulid

_CROCKFORD_ULID = re.compile(r"^[0-9A-HJKMNP-TV-Z]{26}$")

# The single source of the harness worktree layout: every run gets a directory
# under ``<repo>/.worktrees/harness/`` on branch ``harness/<run_id>``. Public so
# ``harness.worktree`` and ``harness.cli.worktrees`` build their (repo-rooted)
# paths from it rather than re-spelling the literal — change the layout here once
# (CAL-590).
WORKTREES_SUBDIR = Path(".worktrees/harness")

# The branch-namespace prefix for harness runs: a run's canonical branch is
# ``harness/<run_id>``. Public so ``harness.worktree`` builds its branch names
# from the same literal rather than re-spelling it — the validated identity home
# (``worktree_branch``) and the unvalidated, configurable-prefix lifecycle home
# (``harness.worktree._branch_for``) now share this one source (CAL-719). Kept
# separate from ``WORKTREES_SUBDIR`` on purpose: a path segment and a branch
# namespace are distinct and may diverge.
BRANCH_PREFIX = "harness"
_ARTIFACTS_ROOT = Path(".harness/artifacts")
_LOG_ROOT = Path(".harness/logs")


def generate_run_id() -> str:
    """Return a new ULID as a 26-character Crockford-base32 string.

    ULIDs are time-ordered: a later call produces a string that sorts after an
    earlier one, which makes chronological listings trivial without a separate
    timestamp column.
    """
    return str(ulid.new())


def worktree_dir(run_id: str) -> Path:
    """Path of the worktree directory for a run, relative to the project root."""
    _validate(run_id)
    return WORKTREES_SUBDIR / run_id


def worktree_branch(run_id: str) -> str:
    """Branch name for a run: the validated, fixed-prefix identity home.

    Always validates the ULID and always uses the default :data:`BRANCH_PREFIX`.
    The unvalidated, configurable-prefix counterpart is
    :func:`harness.worktree._branch_for` — the two share this literal but keep
    separate contracts by design (CAL-719): identity guarantees a canonical
    ``harness/<run_id>`` branch, the lifecycle helper builds whatever branch the
    caller asks for.
    """
    _validate(run_id)
    return f"{BRANCH_PREFIX}/{run_id}"


def artifacts_dir(run_id: str) -> Path:
    """Path of the artifacts directory for a run, relative to the project root."""
    _validate(run_id)
    return _ARTIFACTS_ROOT / run_id


def log_path(run_id: str) -> Path:
    """Path of the log file for a run, relative to the project root."""
    _validate(run_id)
    return _LOG_ROOT / f"{run_id}.log"


def _validate(run_id: str) -> None:
    if not _CROCKFORD_ULID.match(run_id):
        raise ValueError(
            f"run_id {run_id!r} is not a valid 26-char Crockford-base32 ULID"
        )
