"""Workspace allowlist enforcement — the ``HARNESS_WORKSPACE_ROOTS`` primitive
(CAL-584).

The host launcher (CAL-579) and the Hermes flow rely on a single safety
property: *the caller never specifies the mount; the launcher picks it from an
allowlist*. This module is what that property enforces against — a check that
constrains which host paths a harness run may be pointed at via ``--repo``.

Design (see ``specs/hermes-orchestration.md`` §"Target repo allowlist"):

* ``HARNESS_WORKSPACE_ROOTS`` is a colon-separated list of absolute host
  directories. Unset or empty ⇒ *no* allowed roots ⇒ everything is rejected
  (**fail closed**).
* Both the candidate path and each root are ``realpath``-normalized (symlinks
  and ``..`` resolved) before comparison, so ``../`` traversal and symlink
  tricks that resolve outside the roots are defeated.
* A candidate is accepted iff, after normalization, it equals a root or is a
  *path-segment* descendant of one. A string-prefix match is not sufficient:
  ``/work/repo-evil`` must not pass for root ``/work/repo``.

The module is framework-agnostic — it raises :class:`WorkspaceNotAllowed` on
rejection. The CLI adapter (``harness/cli/_repo.py``) translates that into an
exit-code-2 refusal.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path

__all__ = [
    "WORKSPACE_ROOTS_ENV",
    "WorkspaceNotAllowed",
    "allowed_roots",
    "resolve_repo_root",
    "resolve_within_allowlist",
]

#: Environment variable holding the colon-separated allowlist of host roots.
WORKSPACE_ROOTS_ENV = "HARNESS_WORKSPACE_ROOTS"


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
        else:
            roots_desc = f"none — {WORKSPACE_ROOTS_ENV} is unset or empty"
        super().__init__(
            f"repo path {path} is outside the allowed workspace roots "
            f"({roots_desc})"
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


def resolve_repo_root(repo: Path | str, env: Mapping[str, str] | None = None) -> Path:
    """Resolve ``--repo`` to an absolute path, enforced against the allowlist.

    The single path-acceptance point shared by the verbs: it both normalizes the
    candidate and enforces :data:`WORKSPACE_ROOTS_ENV`. Raises
    :class:`WorkspaceNotAllowed` when the candidate is outside every configured
    root (or when none are configured).
    """
    return resolve_within_allowlist(repo, allowed_roots(env))
