"""Shared git helpers for the verbs (CAL-606, CAL-610).

Two layers live here. :func:`run_git` is the generic *invocation* primitive —
the ``git -C <cwd> …`` argv prefix with ``check=False`` and
``capture_output=True`` — that every sync verb site shells out with. It returns
the :class:`subprocess.CompletedProcess` untouched so each caller keeps its own
error policy: raise a verb-specific exception, ignore the result for best-effort
cleanup, or inspect ``returncode`` directly. Centralising it means a change to
*how* the verbs call git (a flag, the binary path, NUL-terminated output) lands
once.

:func:`rev_parse_head` is a domain rule layered on top: ``review`` binds a
verdict to ``git rev-parse HEAD`` and ``close`` refuses to merge unless that
same SHA is still HEAD. That logic previously lived as byte-for-byte copies in
``review.py`` and ``close.py``, differing only in which verb-private exception
they raised. Giving the rule one home lets each caller re-raise :class:`GitError`
as its own verb-specific error.
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


def run_git(
    cwd: Path,
    *args: str,
    timeout: float | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run ``git -C <cwd> <args>`` capturing text output; never raise on non-zero.

    The shared invocation shape — the ``git -C`` prefix, ``check=False``,
    ``capture_output=True``, ``text=True`` — lives here so a change to how the
    verbs shell out to git lands once. Error handling stays with the caller: the
    :class:`subprocess.CompletedProcess` is returned untouched, so callers
    inspect ``returncode`` and raise their own verb-specific exception, ignore it
    (best-effort cleanup), or read the parsed output.

    ``timeout`` is forwarded as-is — a fired timeout raises
    :class:`subprocess.TimeoutExpired`, which the caller's guard handles; this
    helper does not swallow it.
    """
    return subprocess.run(  # noqa: S603, S607
        ["git", "-C", str(cwd), *args],
        check=False,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def rev_parse_head(worktree_path: Path) -> str:
    """Return the current HEAD SHA of ``worktree_path`` (sync — run in a thread).

    Raises :class:`GitError` if ``git rev-parse HEAD`` exits non-zero.
    """
    result = run_git(worktree_path, "rev-parse", "HEAD")
    if result.returncode != 0:
        raise GitError(
            f"git rev-parse HEAD failed for {worktree_path}: {result.stderr.strip()}"
        )
    return result.stdout.strip()
