"""Workspace allowlist enforcement — the ``HARNESS_WORKSPACE_ROOTS`` primitive
(CAL-584).

Every verb resolves ``--repo`` through this allowlist (via ``harness/cli/_repo.py``)
to enforce a single safety property: *the harness is never pointed at a host path
outside an allowed root*. It was introduced for the host launcher (CAL-579, whose
scaffolding was retired in CAL-712); the allowlist itself is load-bearing on every
verb and stays.

Design (see ``specs/retired/hermes-orchestration.md`` §"Target repo allowlist"):

* ``HARNESS_WORKSPACE_ROOTS`` is a colon-separated list of absolute host
  directories. Unset or empty ⇒ *no* allowed roots ⇒ everything is rejected
  (**fail closed**).
* Both the candidate path and each root are ``realpath``-normalized (symlinks
  and ``..`` resolved) before comparison, so ``../`` traversal and symlink
  tricks that resolve outside the roots are defeated.
* A candidate is accepted iff, after normalization, it equals a root or is a
  *path-segment* descendant of one. A string-prefix match is not sufficient:
  ``/work/repo-evil`` must not pass for root ``/work/repo``.

:func:`resolve_repo_root` layers a second, independent check on top of the
allowlist (#214): the accepted path must also be an actual **git top-level**.
The allowlist answers *may the harness touch this path*; it never answered *is
this path a repo root*, so a verb invoked one directory too deep resolved
happily and planted its worktree, branch, and ledger rows under the wrong root.
See that function for why the order between the two checks is load-bearing.

The module is framework-agnostic — it raises :class:`WorkspaceNotAllowed` or
:class:`NotAGitTopLevel` on rejection. The CLI adapter
(``harness/cli/_repo.py``) translates both into an exit-code-2 refusal.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path

__all__ = [
    "WORKSPACE_ROOTS_ENV",
    "NotAGitTopLevel",
    "WorkspaceNotAllowed",
    "allowed_roots",
    "is_git_top_level",
    "resolve_repo_root",
    "resolve_within_allowlist",
]

#: Environment variable holding the colon-separated allowlist of host roots.
WORKSPACE_ROOTS_ENV = "HARNESS_WORKSPACE_ROOTS"

#: Appended to the refusal message when no roots are configured at all — the
#: Docker wrapper (``~/bin/harness``) pins this allowlist itself, so an empty
#: one usually means the native CLI ran by mistake (#246).
_EMPTY_ROOTS_HINT = (
    " The Docker wrapper ~/bin/harness pins that allowlist itself, so an "
    "empty one usually means the native CLI ran instead: in a venv-activated "
    "shell, bare `harness` resolves to the console script on PATH, not the "
    "wrapper. Invoke ~/bin/harness by absolute path, or export "
    f"{WORKSPACE_ROOTS_ENV} to run natively on purpose."
)


class WorkspaceNotAllowed(Exception):  # noqa: N818 — mirrors SPEC vocabulary
    """A repo path resolves outside every configured workspace root.

    Carries the normalized ``path`` and the configured ``roots`` so the CLI can
    name both in its refusal message.
    """

    def __init__(self, path: Path, roots: list[Path]) -> None:
        self.path = path
        self.roots = roots
        if roots:
            roots_desc = ", ".join(str(r) for r in roots)
            hint = ""
        else:
            roots_desc = f"none — {WORKSPACE_ROOTS_ENV} is unset or empty"
            hint = _EMPTY_ROOTS_HINT
        super().__init__(
            f"repo path {path} is outside the allowed workspace roots "
            f"({roots_desc}){hint}"
        )


class NotAGitTopLevel(Exception):  # noqa: N818 — mirrors WorkspaceNotAllowed
    """A repo path is inside the allowlist but is not a git repository root.

    Distinct from :class:`WorkspaceNotAllowed` on purpose: that one means *this
    path is outside the security boundary*, this one means *inside it, but not
    a repo root*. Folding them together would have a verb tell an operator
    standing one directory too deep that their path is "outside the allowed
    workspace roots", which it is not.

    Carries the normalized ``path`` so the CLI can name it in its refusal.
    """

    def __init__(self, path: Path) -> None:
        self.path = path
        super().__init__(
            f"repo path {path} is not a git repository root — no .git entry "
            f"there. Run the verb from the repository's top level (the harness "
            f"writes worktrees, branches, and ledger rows relative to it)."
        )


def allowed_roots(env: Mapping[str, str] | None = None) -> list[Path]:
    """Parse :data:`WORKSPACE_ROOTS_ENV` into realpath-normalized roots.

    Splits on ``:``, drops empty/whitespace-only segments, and ``realpath``-
    normalizes each survivor. An unset or empty variable yields an empty list —
    the deny-all (fail-closed) state.

    ``env`` defaults to :data:`os.environ`; tests pass an explicit mapping.
    """
    source = os.environ if env is None else env
    raw = source.get(WORKSPACE_ROOTS_ENV, "")
    roots: list[Path] = []
    for segment in raw.split(":"):
        stripped = segment.strip()
        if not stripped:
            continue
        roots.append(Path(stripped).resolve())
    return roots


def resolve_within_allowlist(path: Path | str, roots: list[Path]) -> Path:
    """Return the realpath-normalized ``path`` iff it lies within some root.

    Accepts when the normalized candidate equals a root or is a path-segment
    descendant of one (``root in candidate.parents``). Raises
    :class:`WorkspaceNotAllowed` otherwise — including when ``roots`` is empty.

    ``roots`` are expected to already be normalized (as :func:`allowed_roots`
    returns them); the candidate is normalized here.
    """
    candidate = Path(path).resolve()
    for root in roots:
        if candidate == root or root in candidate.parents:
            return candidate
    raise WorkspaceNotAllowed(candidate, roots)


def is_git_top_level(path: Path) -> bool:
    """Whether ``path`` is the root of a git working tree (#214).

    True iff a ``.git`` entry exists *directly* inside ``path``. Deliberately
    ``exists()``, not ``is_dir()``: a linked worktree (``git worktree add``)
    carries ``.git`` as a **file** holding a ``gitdir:`` pointer, and the verbs
    are routinely invoked with ``--repo`` pointing at a run's worktree (#179),
    so an ``is_dir()`` check would refuse every in-flight run.

    A filesystem check rather than ``git rev-parse --show-toplevel`` keeps this
    module framework-agnostic (no subprocess, no dependency on the CLI layer's
    git helpers) and costs a stat instead of a process on every verb
    invocation. The two agree on the cases that matter: a subdirectory of a
    repo and a bare repo are both rejected either way.
    """
    return (path / ".git").exists()


def resolve_repo_root(repo: Path | str, env: Mapping[str, str] | None = None) -> Path:
    """Resolve ``--repo`` to an absolute path, enforced against the allowlist.

    The single path-acceptance point shared by the verbs. It normalizes the
    candidate, enforces :data:`WORKSPACE_ROOTS_ENV`, and then requires the
    survivor to be an actual git top-level. Raises:

    * :class:`WorkspaceNotAllowed` when the candidate is outside every
      configured root (or when none are configured), and
    * :class:`NotAGitTopLevel` when it is inside the allowlist but carries no
      ``.git`` entry.

    **Order is load-bearing.** The allowlist is the security boundary and is
    checked first, so a path outside the roots keeps reporting the allowlist
    refusal it always reported, whether or not it happens to be a repo; the git
    check only ever narrows what the allowlist already admitted.

    The git check exists because the allowlist alone accepted *any* resolvable
    path (#214). A verb invoked one directory too deep — trivially easy here,
    where the source package ``harness/`` shares the repo's name — silently
    wrote its worktree, branch, and ledger rows under the wrong root, landing
    them at ``<repo>/harness/.worktrees/harness/<id>`` where the harness's own
    ``worktrees cleanup`` could never see them again. Failing loudly at the one
    acceptance point is what makes that unrepeatable.
    """
    candidate = resolve_within_allowlist(repo, allowed_roots(env))
    if not is_git_top_level(candidate):
        raise NotAGitTopLevel(candidate)
    return candidate
