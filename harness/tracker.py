"""The tracker seam — the interface the verbs use, and the factory behind it.

The verbs (``start``, ``review``, ``close``, ``defer``, ``reclaim``) do not talk
to a tracker directly: they obtain a :class:`Tracker` from :func:`tracker_client`
and call the seam. ``linear.py``'s :class:`~harness.linear.LinearClient` and
``github.py``'s :class:`~harness.github.GitHubClient` are two structural
implementations; selecting between them lives in one place — this factory — so
the verbs stay backend-agnostic. That is the whole point of the seam: a backend
slots in behind the factory **without touching a single verb**.

**Which backend** is resolved from ``CONTEXT.md`` → ``tracker:`` by
:func:`harness.layers.tracker` (the single source of truth, CAL-1164). This
module does not re-parse CONTEXT.md; it reads through that resolver:

* ``linear`` → a :class:`~harness.linear.LinearClient` (needs ``LINEAR_API_KEY``;
  a missing key raises :class:`~harness.linear.LinearConfigError`, which each verb
  maps to its own exit code).
* ``github`` → a :class:`~harness.github.GitHubClient` (CAL-1105) built from the
  ``github:`` config block and ``GITHUB_TOKEN``; a missing config block or token
  raises :class:`~harness.github.GitHubConfigError`, handled by the verbs exactly
  like the Linear config error.
* ``none`` → ``None`` — the repo runs tracker-less, and the factory returns
  *without* reaching for any credential.

Both backends' boundary exceptions subclass the tracker-agnostic bases in
:mod:`harness.tracker_errors`, so the verbs catch failures without naming a
backend.

The ``Tracker`` protocol is ``@runtime_checkable`` so a conformance test can pin
both clients to it structurally — a renamed or dropped seam method breaks the
pin, catching interface drift between the verbs' dependency and either impl.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from harness import layers, repo_config
from harness.github import GitHubClient, GitHubConfigError, github_token
from harness.linear import LinearClient, linear_api_key

__all__ = ["Tracker", "tracker_client"]


@runtime_checkable
class Tracker(Protocol):
    """The tracker surface the verbs depend on — the seam.

    Exactly the methods the verbs call on a tracker client, no more. Any backend
    (Linear and GitHub today) implements these; the verbs know only this
    protocol. The signatures mirror
    :class:`~harness.linear.LinearClient` so it satisfies the seam unchanged.
    """

    async def fetch_issue(self, identifier: str) -> dict[str, Any]: ...

    async def fetch_issue_project(self, identifier: str) -> str | None: ...

    async def fetch_reclaimable_issues(
        self, *, project: str | None
    ) -> list[dict[str, str]]: ...

    async def fetch_resume_branch(self, identifier: str) -> str | None: ...

    async def fetch_handoff_branch(self, identifier: str) -> str | None: ...

    async def fetch_design_comment(self, identifier: str) -> str | None: ...

    async def transition_to_in_progress(self, identifier: str) -> None: ...

    async def transition_to_in_review(self, identifier: str) -> None: ...

    async def transition_to_done(self, identifier: str) -> None: ...

    async def transition_to_unstarted(self, identifier: str) -> None: ...

    async def apply_label(self, identifier: str, name: str) -> None: ...

    async def post_comment(self, identifier: str, body: str) -> None: ...

    async def assign_to_viewer(self, identifier: str) -> None: ...

    async def remove_label(self, identifier: str, name: str) -> None: ...

    async def unassign_viewer(self, identifier: str) -> None: ...

    async def update_issue_body(self, identifier: str, body: str) -> None: ...

    async def create_issue(
        self,
        *,
        team_key: str,
        project_name: str | None,
        title: str,
        description: str,
    ) -> dict[str, str]: ...


def tracker_client(repo_root: Path) -> Tracker | None:
    """Return the tracker client for ``repo_root``, or ``None`` if tracker-less.

    Resolves the backend from ``CONTEXT.md`` → ``tracker:`` (via
    :func:`harness.layers.tracker`) and constructs the matching implementation.
    This is the one place a backend is chosen — the verbs call it and stay
    backend-agnostic.

    Returns:
        A :class:`~harness.linear.LinearClient` for ``tracker: linear``; a
        :class:`~harness.github.GitHubClient` for ``tracker: github``; ``None``
        for ``tracker: none`` (the repo runs tracker-less, no credential fetched).

    Raises:
        harness.linear.LinearConfigError: ``tracker: linear`` but ``LINEAR_API_KEY``
            is unset — propagated so each verb maps it to its own exit code.
        harness.github.GitHubConfigError: ``tracker: github`` but the ``github:``
            config block is absent/incomplete, or ``GITHUB_TOKEN`` is unset.
    """
    backend = layers.tracker(repo_root)
    if backend == "none":
        return None
    if backend == "github":
        settings = layers.github_settings(repo_root)
        if settings is None:
            raise GitHubConfigError(
                "tracker: github requires a github: block in CONTEXT.md with "
                "repo (owner/name) and project (owner/number)"
            )
        return GitHubClient(token=github_token(), settings=settings)
    # Default / ``linear``: LinearClient is the seam's Linear implementation. The
    # ``repo.linear`` team is threaded in so an unscoped reclaim sweep (no project)
    # can filter by team rather than the whole workspace (#174); it is client config,
    # not a per-call seam argument, keeping the seam free of Linear vocabulary.
    return LinearClient(
        api_key=linear_api_key(), team=repo_config.repo_linear_team(repo_root)
    )
