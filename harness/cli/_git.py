"""Shared git helpers for the verbs (CAL-606).

The HEAD-SHA read is a domain rule, not incidental plumbing: ``review`` binds a
verdict to ``git rev-parse HEAD`` and ``close`` refuses to merge unless that
same SHA is still HEAD. That logic previously lived as byte-for-byte copies in
``review.py`` and ``close.py``, differing only in which verb-private exception
they raised. Extracting it here gives the rule one home — a change to the git
invocation (``--verify``, NUL-terminated output, …) lands once — and each caller
re-raises :class:`GitError` as its own verb-specific error.
"""

from __future__ import annotations

import subprocess
from pathlib import Path


class GitError(RuntimeError):
    """A git subprocess invocation failed.

    A plain :class:`RuntimeError` subclass so each verb can catch it and
    re-raise as its own control-flow exception (with the verb's exit code)
    without this module depending on either verb.
    """


def rev_parse_head(worktree_path: Path) -> str:
    """Return the current HEAD SHA of ``worktree_path`` (sync — run in a thread).

    Raises :class:`GitError` if ``git rev-parse HEAD`` exits non-zero.
    """
    result = subprocess.run(  # noqa: S603, S607
        ["git", "-C", str(worktree_path), "rev-parse", "HEAD"],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise GitError(
            f"git rev-parse HEAD failed for {worktree_path}: {result.stderr.strip()}"
        )
    return result.stdout.strip()
