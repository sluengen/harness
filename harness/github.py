"""GitHub Projects v2 tracker backend — the GitHub implementation of the seam.

The second :class:`~harness.tracker.Tracker` implementation (CAL-1105), sibling to
:class:`~harness.linear.LinearClient`. The verbs never import it directly: they
obtain it from :func:`harness.tracker.tracker_client` when ``CONTEXT.md`` sets
``tracker: github``, and call the same protocol methods. This module is where the
GitHub half of that protocol lives.

**State mapping — Projects v2 single-select field (the CAL-1105 decision).**
GitHub Issues have no native workflow states, so the harness maps its states onto
a **Projects v2 single-select field** (default name ``Status``): the issue is an
item on a configured board, and a transition sets that item's field to the option
whose **name** matches the target state — ``todo`` → *Todo*, ``in_progress`` →
*In Progress*, ``in_review`` → *In Review*, ``done`` → *Done*, matched
case-insensitively. This mirrors :class:`~harness.linear.LinearClient`'s
name-then-resolve discipline (never a hard-coded option UUID): the board owns the
option ids, this client resolves them at runtime. An issue not yet on the board is
added on its first transition.

**Auth** is ``GITHUB_TOKEN`` (env-only, the same rule as ``LINEAR_API_KEY``); the
token needs the ``repo`` and ``project`` scopes (Projects v2 mutations require
``project``). Like the Linear client this uses stdlib ``urllib`` off a worker
thread so the public API is async, and it targets the single GraphQL endpoint
(``https://api.github.com/graphql``) for both Issues and Projects v2 — REST is
never needed and Projects v2 is GraphQL-only, so one transport serves both.
"""

from __future__ import annotations

import asyncio
import json
import os
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from harness.layers import GitHubSettings
from harness.reclaim_marker import (
    HANDOFF_MARKER,
    RECLAIM_LABEL,
    RECLAIM_MARKER,
    parse_handoff_branch,
    parse_preserved_branch,
)
from harness.tracker_errors import (
    TrackerConfigError,
    TrackerNotFound,
    TrackerRequestError,
)

# size: one cohesive GitHub GraphQL boundary class — the exact mirror of the
# LinearClient size waiver. Every GitHub Issues/Projects-v2 operation the verbs
# need lives behind this one client so the seam has a single GitHub surface;
# splitting it to chase the 500-line limit would scatter that boundary, not
# clarify it.

__all__ = [
    "GitHubClient",
    "GitHubConfigError",
    "GitHubNotFound",
    "GitHubRequestError",
    "github_token",
]

_GITHUB_API_URL = "https://api.github.com/graphql"

#: GitHub's API requires a User-Agent header; an absent one is rejected 403.
_USER_AGENT = "harness-tracker"

#: Compact ticket fields — the same shape the Linear client returns, so the
#: verbs read a tracker-agnostic dict (``description`` carries the issue body).
_TICKET_FIELDS = ("id", "identifier", "title", "description", "url")

#: Harness workflow state → Projects v2 single-select option **name**. Matched
#: case-insensitively against the board's option names, so the board owns the
#: option ids and this client hard-codes none (mirrors LinearClient by-name
#: state resolution).
_STATE_OPTION_NAME = {
    "todo": "Todo",
    "in_progress": "In Progress",
    "in_review": "In Review",
    "done": "Done",
}

#: The transient states the ``reclaim --stale`` sweep enumerates — the exact two
#: the Linear client scopes to (In Progress *and* In Review, CAL-1103).
_RECLAIMABLE_STATUS_NAMES = ("in progress", "in review")

#: Default colour for a label the client has to create (GitHub ``createLabel``
#: requires a 6-hex colour); the harness never depends on label colour.
_DEFAULT_LABEL_COLOR = "ededed"


class GitHubConfigError(TrackerConfigError):
    """Raised when required GitHub configuration (token or ``github:`` block) is missing."""


class GitHubNotFound(TrackerNotFound):  # noqa: N818 — SPEC vocab, not PEP 8 Error suffix
    """Raised when the requested issue, board, or owner does not exist or is inaccessible."""


class GitHubRequestError(TrackerRequestError):
    """Raised when the GitHub API returns an error or an unexpected response."""


def github_token() -> str:
    """Return the ``GITHUB_TOKEN`` environment variable.

    Raises:
        GitHubConfigError: when the variable is not set.
    """
    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        raise GitHubConfigError(
            "GITHUB_TOKEN environment variable is not set; export a token with "
            "the 'repo' and 'project' scopes before running the GitHub tracker"
        )
    return token


@dataclass(frozen=True)
class _ProjectMeta:
    """Resolved, memoized metadata for the configured Projects v2 board."""

    owner_kind: str  # "user" or "organization"
    project_id: str
    title: str | None
    field_id: str
    options: dict[str, str]  # option name (lower) -> option id


def _split(value: str, key: str, shape: str) -> tuple[str, str]:
    """Split ``owner/tail`` config into its two parts, or raise a config error."""
    parts = value.split("/")
    if len(parts) != 2 or not parts[0] or not parts[1]:
        raise GitHubConfigError(
            f"github.{key} must be '{shape}', got {value!r}"
        )
    return parts[0], parts[1]


def _issue_number(identifier: str) -> int:
    """Normalise a GitHub issue identifier (``42`` or ``#42``) to an int."""
    text = identifier.strip().lstrip("#")
    try:
        return int(text)
    except ValueError as exc:
        raise GitHubNotFound(
            f"{identifier!r} is not a GitHub issue number"
        ) from exc


class GitHubClient:
    """Async GitHub GraphQL client — the GitHub implementation of the tracker seam.

    Args:
        token: a GitHub token with ``repo`` and ``project`` scopes. Use
            :func:`github_token` to read it from the environment.
        settings: the ``github:`` config block (:class:`~harness.layers.GitHubSettings`)
            — the issues repo, the Projects v2 board, and the status field name.
    """

    def __init__(self, *, token: str, settings: GitHubSettings) -> None:
        self._token = token
        self._owner, self._name = _split(settings.repo, "repo", "owner/name")
        self._project_login, number = _split(
            settings.project, "project", "owner/number"
        )
        try:
            self._project_number = int(number)
        except ValueError as exc:
            raise GitHubConfigError(
                f"github.project number must be an integer, got {number!r}"
            ) from exc
        self._status_field = settings.status_field
        self._meta: _ProjectMeta | None = None

    # ------------------------------------------------------------------
    # Public interface (the Tracker protocol)
    # ------------------------------------------------------------------

    async def fetch_issue(self, identifier: str) -> dict[str, Any]:
        """Fetch issue ``identifier`` and return a compact ticket dict.

        Returns a dict with keys ``id``, ``identifier``, ``title``,
        ``description`` (the issue body), ``url``, and ``labels`` (the issue's
        label names, e.g. for #177's model-tier resolution) — the same shape
        the Linear client returns, so the verbs stay tracker-agnostic.

        Raises:
            GitHubNotFound: the issue does not exist.
            GitHubRequestError: the API returned an error.
        """
        number = _issue_number(identifier)
        query = """
query FetchIssue($owner: String!, $name: String!, $number: Int!) {
  repository(owner: $owner, name: $name) {
    issue(number: $number) { id number title body url labels(first: 50) { nodes { name } } }
  }
}
"""
        issue = await self._issue_node(query, number, ("issue",))
        return {
            "id": issue.get("id"),
            "identifier": str(issue.get("number")),
            "title": issue.get("title"),
            "description": issue.get("body"),
            "url": issue.get("url"),
            "labels": [
                n.get("name")
                for n in (issue.get("labels") or {}).get("nodes", [])
                if n.get("name")
            ],
        }

    async def fetch_issue_project(self, identifier: str) -> str | None:
        """Return the configured board's title if the issue is on it, else ``None``.

        The Build-queue membership check ``harness defer`` binds to (CAL-1143). On
        GitHub the "project" is the configured Projects v2 board, so this reports
        the board title when the issue is an item on it and ``None`` otherwise
        (the caller treats ``None`` as "not on the Build queue").

        Raises:
            GitHubNotFound: the issue does not exist.
            GitHubRequestError: the API returned an error.
        """
        number = _issue_number(identifier)
        query = """
query IssueProjects($owner: String!, $name: String!, $number: Int!) {
  repository(owner: $owner, name: $name) {
    issue(number: $number) {
      id
      projectItems(first: 20) { nodes { project { id title } } }
    }
  }
}
"""
        issue = await self._issue_node(query, number, ("issue",))
        meta = await self._project_metadata()
        for item in (issue.get("projectItems") or {}).get("nodes", []):
            project = item.get("project") or {}
            if project.get("id") == meta.project_id:
                title = project.get("title")
                return str(title) if title else None
        return None

    async def fetch_reclaimable_issues(
        self, *, project: str | None
    ) -> list[dict[str, str]]:
        """List reclaimable issues on the board as ``[{identifier, updated_at}]``.

        The enumeration the ``harness reclaim --stale`` sweep filters by age.
        Scoped to the configured board and to **both** transient states — *In
        Progress* and *In Review*, matched by the Status option name — mirroring
        the Linear client (CAL-1103). ``updated_at`` carries the issue's
        ``updatedAt`` (ISO-8601 UTC), the staleness signal the sweep compares
        against its threshold. The ``project`` argument is accepted for protocol
        symmetry — nullable since #174 — but the board itself *is* the queue, so it
        is not re-resolved: ``None`` (the whole-queue mode) and any project value
        sweep the same board, the unset path being this backend's current behaviour.

        Raises:
            GitHubRequestError: the API returned an error or an unexpected response.
        """
        meta = await self._project_metadata()
        query = f"""
query Reclaimable($login: String!, $number: Int!, $field: String!) {{
  {meta.owner_kind}(login: $login) {{
    projectV2(number: $number) {{
      items(first: 100) {{
        nodes {{
          content {{ ... on Issue {{ number updatedAt }} }}
          fieldValueByName(name: $field) {{
            ... on ProjectV2ItemFieldSingleSelectValue {{ name }}
          }}
        }}
      }}
    }}
  }}
}}
"""
        data = await self._request(
            query,
            {
                "login": self._project_login,
                "number": self._project_number,
                "field": self._status_field,
            },
        )
        owner = (data.get("data") or {}).get(meta.owner_kind) or {}
        nodes = ((owner.get("projectV2") or {}).get("items") or {}).get("nodes", [])
        reclaimable: list[dict[str, str]] = []
        for node in nodes:
            content = node.get("content") or {}
            status = (node.get("fieldValueByName") or {}).get("name")
            if content.get("number") is None or status is None:
                continue
            if status.lower() in _RECLAIMABLE_STATUS_NAMES:
                reclaimable.append(
                    {
                        "identifier": str(content["number"]),
                        "updated_at": content["updatedAt"],
                    }
                )
        return reclaimable

    async def fetch_resume_branch(self, identifier: str) -> str | None:
        """The preserved WIP branch a reclaimed ticket can resume from, or ``None``.

        The GitHub counterpart of :meth:`~harness.linear.LinearClient.fetch_resume_branch`
        (proposal ``stale-run-reclamation`` D4): reads back the branch named by
        the latest reclaim comment, gated on the ``reclaimed`` label — the same
        marker and gate as Linear, over GitHub issue comments and labels.

        Raises:
            GitHubNotFound: the issue does not exist.
            GitHubRequestError: the API returned an error.
        """
        return await self._latest_marked_branch(
            identifier,
            marker=RECLAIM_MARKER,
            parser=parse_preserved_branch,
            require_label=RECLAIM_LABEL,
        )

    async def fetch_handoff_branch(self, identifier: str) -> str | None:
        """The preserved WIP branch a proactively handed-off ticket continues from.

        The GitHub counterpart of :meth:`~harness.linear.LinearClient.fetch_handoff_branch`
        (proposal ``ground-specs-and-context-rollover`` WS-B): keys **only** on
        the handoff marker in a comment (no label gate), so it never picks up a
        death-keyed reclaim comment and vice versa.

        Raises:
            GitHubNotFound: the issue does not exist.
            GitHubRequestError: the API returned an error.
        """
        return await self._latest_marked_branch(
            identifier,
            marker=HANDOFF_MARKER,
            parser=parse_handoff_branch,
        )

    async def transition_to_in_progress(self, identifier: str) -> None:
        """Set the issue's board Status to *In Progress* (adding it to the board if absent)."""
        await self._set_status(identifier, "in_progress")

    async def transition_to_in_review(self, identifier: str) -> None:
        """Set the issue's board Status to *In Review*."""
        await self._set_status(identifier, "in_review")

    async def transition_to_done(self, identifier: str) -> None:
        """Set the issue's board Status to *Done*."""
        await self._set_status(identifier, "done")

    async def issue_is_done(self, identifier: str) -> bool:
        """Whether the issue's board Status option is *Done*.

        A read-only counterpart to :meth:`transition_to_done` (#233): observes
        the item's current Status rather than trusting a mutation's
        acknowledgement. Deliberately does **not** reuse :meth:`_resolve_item`
        — a verification read must mutate nothing, and that helper adds the
        issue to the board when it is absent. An issue on no item of the
        configured board is reported ``False``, not an error.

        Raises:
            GitHubNotFound: the issue does not exist.
            GitHubRequestError: the API returned an error.
        """
        number = _issue_number(identifier)
        meta = await self._project_metadata()
        query = """
query IssueStatus($owner: String!, $name: String!, $number: Int!, $field: String!) {
  repository(owner: $owner, name: $name) {
    issue(number: $number) {
      id
      projectItems(first: 20) {
        nodes {
          project { id }
          fieldValueByName(name: $field) {
            ... on ProjectV2ItemFieldSingleSelectValue { name }
          }
        }
      }
    }
  }
}
"""
        issue = await self._issue_node(
            query, number, ("issue",), extra_variables={"field": self._status_field}
        )
        for item in (issue.get("projectItems") or {}).get("nodes", []):
            if (item.get("project") or {}).get("id") != meta.project_id:
                continue
            status = (item.get("fieldValueByName") or {}).get("name")
            return (status or "").lower() == _STATE_OPTION_NAME["done"].lower()
        return False

    async def transition_to_unstarted(self, identifier: str) -> None:
        """Set the issue's board Status back to *Todo* (the reclamation revert)."""
        await self._set_status(identifier, "todo")

    async def apply_label(self, identifier: str, name: str) -> None:
        """Resolve (creating if absent) the label ``name`` and add it to the issue.

        Resolves the label id from the repo's labels by name, creating it on the
        repo if none exists, then adds it with ``addLabelsToLabelable`` so labels
        already on the issue are preserved — the GitHub mirror of the Linear
        client's resolve-or-create primitive.

        Raises:
            GitHubNotFound: the issue does not exist.
            GitHubRequestError: the API returned an error or a mutation returned
                no result.
        """
        number = _issue_number(identifier)
        query = """
query IssueAndLabel($owner: String!, $name: String!, $number: Int!, $label: String!) {
  repository(owner: $owner, name: $name) {
    id
    issue(number: $number) { id }
    label(name: $label) { id }
  }
}
"""
        data = await self._request(
            query,
            {
                "owner": self._owner,
                "name": self._name,
                "number": number,
                "label": name,
            },
        )
        repo = (data.get("data") or {}).get("repository")
        if repo is None:
            raise GitHubNotFound(
                f"GitHub repository {self._owner}/{self._name} not found"
            )
        issue = repo.get("issue")
        if issue is None:
            raise GitHubNotFound(f"GitHub issue {identifier!r} not found")
        existing = repo.get("label")
        label_id = (
            existing["id"]
            if existing
            else await self._create_label(repo["id"], name)
        )

        mutation = """
mutation AddLabel($labelableId: ID!, $labelIds: [ID!]!) {
  addLabelsToLabelable(input: {labelableId: $labelableId, labelIds: $labelIds}) {
    labelable { ... on Issue { id } }
  }
}
"""
        result = await self._request(
            mutation, {"labelableId": issue["id"], "labelIds": [label_id]}
        )
        labelable = (
            (result.get("data") or {})
            .get("addLabelsToLabelable", {})
            .get("labelable")
        )
        if not labelable:
            raise GitHubRequestError(
                f"GitHub addLabelsToLabelable returned no result for {identifier!r}; "
                f"response: {result!r}"
            )

    async def post_comment(self, identifier: str, body: str) -> None:
        """Post a comment with ``body`` to the issue (``addComment``).

        Raises:
            GitHubNotFound: the issue does not exist.
            GitHubRequestError: the API returned an error or the mutation returned
                no comment.
        """
        node_id = await self._issue_node_id(identifier)
        mutation = """
mutation AddComment($subjectId: ID!, $body: String!) {
  addComment(input: {subjectId: $subjectId, body: $body}) {
    commentEdge { node { id } }
  }
}
"""
        result = await self._request(mutation, {"subjectId": node_id, "body": body})
        comment = (
            ((result.get("data") or {}).get("addComment") or {}).get("commentEdge")
            or {}
        ).get("node")
        if not comment:
            raise GitHubRequestError(
                f"GitHub addComment returned no comment for {identifier!r}; "
                f"response: {result!r}"
            )

    async def assign_to_viewer(self, identifier: str) -> None:
        """Assign the issue to the authenticated user — the operator.

        The machine-readable "a human holds this" signal ``work-discovery`` reads
        (CAL-1143), the GitHub mirror of the Linear client's ``assign_to_viewer``:
        resolves the token's ``viewer`` id and the issue node id in one query,
        then ``addAssigneesToAssignable``.

        Raises:
            GitHubNotFound: the issue does not exist.
            GitHubRequestError: the API returned an error, no viewer resolved, or
                the mutation returned no result.
        """
        number = _issue_number(identifier)
        query = """
query ViewerAndIssue($owner: String!, $name: String!, $number: Int!) {
  viewer { id }
  repository(owner: $owner, name: $name) { issue(number: $number) { id } }
}
"""
        data = await self._request(
            query, {"owner": self._owner, "name": self._name, "number": number}
        )
        payload = data.get("data") or {}
        issue = (payload.get("repository") or {}).get("issue")
        if issue is None:
            raise GitHubNotFound(f"GitHub issue {identifier!r} not found")
        viewer_id = (payload.get("viewer") or {}).get("id")
        if not viewer_id:
            raise GitHubRequestError(
                "GitHub resolved no viewer for the token; cannot assign "
                f"{identifier!r} to the operator"
            )

        mutation = """
mutation AssignIssue($assignableId: ID!, $assigneeIds: [ID!]!) {
  addAssigneesToAssignable(
    input: {assignableId: $assignableId, assigneeIds: $assigneeIds}
  ) {
    assignable { ... on Issue { id } }
  }
}
"""
        result = await self._request(
            mutation, {"assignableId": issue["id"], "assigneeIds": [viewer_id]}
        )
        assignable = (
            (result.get("data") or {})
            .get("addAssigneesToAssignable", {})
            .get("assignable")
        )
        if not assignable:
            raise GitHubRequestError(
                f"GitHub addAssigneesToAssignable returned no result for {identifier!r}; "
                f"response: {result!r}"
            )

    async def remove_label(self, identifier: str, name: str) -> None:
        """Remove the label ``name`` from the issue if present (``removeLabelsFromLabelable``).

        The release-side mirror of :meth:`apply_label` (#193, the ``defer``
        shape in reverse): resolves the label id from the issue's **own**
        labels, matched case-insensitively. A ticket that no longer carries the
        label is a clean no-op, so a release can run twice without erroring.

        Raises:
            GitHubNotFound: the issue does not exist.
            GitHubRequestError: the API returned an error or the mutation
                returned no result.
        """
        number = _issue_number(identifier)
        query = """
query IssueLabels($owner: String!, $name: String!, $number: Int!) {
  repository(owner: $owner, name: $name) {
    issue(number: $number) { id labels(first: 50) { nodes { id name } } }
  }
}
"""
        data = await self._request(
            query, {"owner": self._owner, "name": self._name, "number": number}
        )
        repo = (data.get("data") or {}).get("repository")
        if repo is None:
            raise GitHubNotFound(
                f"GitHub repository {self._owner}/{self._name} not found"
            )
        issue = repo.get("issue")
        if issue is None:
            raise GitHubNotFound(f"GitHub issue {identifier!r} not found")
        label_nodes: list[dict[str, Any]] = (issue.get("labels") or {}).get("nodes", [])
        target = next(
            (n for n in label_nodes if (n.get("name") or "").lower() == name.lower()),
            None,
        )
        if target is None:
            return  # already absent — idempotent release

        mutation = """
mutation RemoveLabel($labelableId: ID!, $labelIds: [ID!]!) {
  removeLabelsFromLabelable(input: {labelableId: $labelableId, labelIds: $labelIds}) {
    labelable { ... on Issue { id } }
  }
}
"""
        result = await self._request(
            mutation, {"labelableId": issue["id"], "labelIds": [target["id"]]}
        )
        labelable = (
            (result.get("data") or {})
            .get("removeLabelsFromLabelable", {})
            .get("labelable")
        )
        if not labelable:
            raise GitHubRequestError(
                f"GitHub removeLabelsFromLabelable returned no result for "
                f"{identifier!r}; response: {result!r}"
            )

    async def unassign_viewer(self, identifier: str) -> None:
        """Clear the assignee on the issue (``removeAssigneesFromAssignable``).

        The release-side mirror of :meth:`assign_to_viewer` (#193): resolves the
        token's ``viewer`` id and the issue node id, then removes that assignee
        unconditionally — ``defer`` only ever assigns the operator, so whoever
        holds the ticket *is* the assignee this clears. This is the load-bearing
        release step: assignment is the authoritative "a human holds this"
        signal ``work-discovery`` reads, so clearing it is what actually returns
        the ticket to the queue.

        Raises:
            GitHubNotFound: the issue does not exist.
            GitHubRequestError: the API returned an error, no viewer resolved,
                or the mutation returned no result.
        """
        number = _issue_number(identifier)
        query = """
query ViewerAndIssue($owner: String!, $name: String!, $number: Int!) {
  viewer { id }
  repository(owner: $owner, name: $name) { issue(number: $number) { id } }
}
"""
        data = await self._request(
            query, {"owner": self._owner, "name": self._name, "number": number}
        )
        payload = data.get("data") or {}
        issue = (payload.get("repository") or {}).get("issue")
        if issue is None:
            raise GitHubNotFound(f"GitHub issue {identifier!r} not found")
        viewer_id = (payload.get("viewer") or {}).get("id")
        if not viewer_id:
            raise GitHubRequestError(
                "GitHub resolved no viewer for the token; cannot unassign "
                f"{identifier!r} from the operator"
            )

        mutation = """
mutation UnassignIssue($assignableId: ID!, $assigneeIds: [ID!]!) {
  removeAssigneesFromAssignable(
    input: {assignableId: $assignableId, assigneeIds: $assigneeIds}
  ) {
    assignable { ... on Issue { id } }
  }
}
"""
        result = await self._request(
            mutation, {"assignableId": issue["id"], "assigneeIds": [viewer_id]}
        )
        assignable = (
            (result.get("data") or {})
            .get("removeAssigneesFromAssignable", {})
            .get("assignable")
        )
        if not assignable:
            raise GitHubRequestError(
                f"GitHub removeAssigneesFromAssignable returned no result for "
                f"{identifier!r}; response: {result!r}"
            )

    async def update_issue_body(self, identifier: str, body: str) -> None:
        """Overwrite the issue's body with ``body`` (``updateIssue``).

        The release step that writes a decision's resolution into the ticket's
        change spec (#193) — into the body an agent reads cold, not only a
        comment thread. The caller composes the full new body (existing spec +
        appended resolution section); this primitive just sets it.

        Raises:
            GitHubNotFound: the issue does not exist.
            GitHubRequestError: the API returned an error or the mutation
                returned no result.
        """
        node_id = await self._issue_node_id(identifier)
        mutation = """
mutation UpdateIssueBody($id: ID!, $body: String!) {
  updateIssue(input: {id: $id, body: $body}) {
    issue { id }
  }
}
"""
        result = await self._request(mutation, {"id": node_id, "body": body})
        issue = ((result.get("data") or {}).get("updateIssue") or {}).get("issue")
        if not issue:
            raise GitHubRequestError(
                f"GitHub updateIssue returned no issue for {identifier!r}; "
                f"response: {result!r}"
            )

    async def create_issue(
        self,
        *,
        team_key: str,
        project_name: str | None,
        title: str,
        description: str,
    ) -> dict[str, str]:
        """Create an issue in the repo, add it to the board; return ``{identifier, url}``.

        The GitHub mirror of the Linear client's ``create_issue`` (the primitive
        behind ``harness ingest`` / escalation). ``team_key`` and ``project_name``
        are Linear addressing and are ignored — GitHub's repo and board come from
        config; the new issue is added to the configured board so it lands on the
        queue. ``identifier`` is the new issue number.

        Raises:
            GitHubNotFound: the configured repository does not exist.
            GitHubRequestError: the API errored or ``createIssue`` returned no issue.
        """
        repo_query = """
query RepoId($owner: String!, $name: String!) {
  repository(owner: $owner, name: $name) { id }
}
"""
        repo_data = await self._request(
            repo_query, {"owner": self._owner, "name": self._name}
        )
        repo = (repo_data.get("data") or {}).get("repository")
        if repo is None:
            raise GitHubNotFound(
                f"GitHub repository {self._owner}/{self._name} not found"
            )

        mutation = """
mutation CreateIssue($repoId: ID!, $title: String!, $body: String!) {
  createIssue(input: {repositoryId: $repoId, title: $title, body: $body}) {
    issue { id number url }
  }
}
"""
        result = await self._request(
            mutation, {"repoId": repo["id"], "title": title, "body": description}
        )
        issue = ((result.get("data") or {}).get("createIssue") or {}).get("issue")
        if not issue:
            raise GitHubRequestError(
                f"GitHub createIssue returned no issue for {self._owner}/{self._name}; "
                f"response: {result!r}"
            )
        await self._add_to_board(issue["id"])
        return {"identifier": str(issue["number"]), "url": str(issue["url"])}

    # ------------------------------------------------------------------
    # Internal — Projects v2 status mechanics
    # ------------------------------------------------------------------

    async def _set_status(self, identifier: str, state: str) -> None:
        """Set the issue's board Status field to the option for ``state``.

        Resolves the board's field + option ids (memoized), the option whose name
        matches the state, and the issue's project item (adding the issue to the
        board if it is not on it yet), then fires ``updateProjectV2ItemFieldValue``.

        Raises:
            GitHubNotFound: the issue does not exist.
            GitHubRequestError: the API errored, the board has no matching status
                option, or the mutation returned no result.
        """
        meta = await self._project_metadata()
        option_name = _STATE_OPTION_NAME[state]
        option_id = meta.options.get(option_name.lower())
        if option_id is None:
            raise GitHubRequestError(
                f"Projects v2 board {self._project_login}/{self._project_number} "
                f"has no {self._status_field!r} option named {option_name!r}; "
                f"available: {sorted(meta.options)}"
            )
        item_id = await self._resolve_item(identifier, meta)
        mutation = """
mutation SetStatus($projectId: ID!, $itemId: ID!, $fieldId: ID!, $optionId: String!) {
  updateProjectV2ItemFieldValue(
    input: {
      projectId: $projectId
      itemId: $itemId
      fieldId: $fieldId
      value: {singleSelectOptionId: $optionId}
    }
  ) {
    projectV2Item { id }
  }
}
"""
        result = await self._request(
            mutation,
            {
                "projectId": meta.project_id,
                "itemId": item_id,
                "fieldId": meta.field_id,
                "optionId": option_id,
            },
        )
        updated = (
            (result.get("data") or {})
            .get("updateProjectV2ItemFieldValue", {})
            .get("projectV2Item")
        )
        if not updated:
            raise GitHubRequestError(
                f"GitHub updateProjectV2ItemFieldValue returned no item for "
                f"{identifier!r}; response: {result!r}"
            )

    async def _resolve_item(self, identifier: str, meta: _ProjectMeta) -> str:
        """The issue's project-item id on the configured board, adding it if absent."""
        number = _issue_number(identifier)
        query = """
query IssueItems($owner: String!, $name: String!, $number: Int!) {
  repository(owner: $owner, name: $name) {
    issue(number: $number) {
      id
      projectItems(first: 50) { nodes { id project { id } } }
    }
  }
}
"""
        issue = await self._issue_node(query, number, ("issue",))
        for item in (issue.get("projectItems") or {}).get("nodes", []):
            if (item.get("project") or {}).get("id") == meta.project_id:
                return str(item["id"])
        return await self._add_to_board(issue["id"])

    async def _add_to_board(self, content_id: str) -> str:
        """Add a content node (an issue) to the configured board; return the item id."""
        meta = await self._project_metadata()
        mutation = """
mutation AddItem($projectId: ID!, $contentId: ID!) {
  addProjectV2ItemById(input: {projectId: $projectId, contentId: $contentId}) {
    item { id }
  }
}
"""
        result = await self._request(
            mutation, {"projectId": meta.project_id, "contentId": content_id}
        )
        item = (
            (result.get("data") or {})
            .get("addProjectV2ItemById", {})
            .get("item")
        )
        if not item:
            raise GitHubRequestError(
                f"GitHub addProjectV2ItemById returned no item for board "
                f"{self._project_login}/{self._project_number}; response: {result!r}"
            )
        return str(item["id"])

    async def _project_metadata(self) -> _ProjectMeta:
        """Resolve and memoize the board id, status field id, and option-id map.

        Learns the owner kind (user vs organization) from ``repositoryOwner``,
        then reads the single-select status field named ``status_field`` and its
        options. Cached for the client's lifetime — the board's shape does not
        change within a run.
        """
        if self._meta is not None:
            return self._meta
        owner_kind = await self._owner_kind()
        query = f"""
query ProjectMeta($login: String!, $number: Int!, $field: String!) {{
  {owner_kind}(login: $login) {{
    projectV2(number: $number) {{
      id
      title
      field(name: $field) {{
        ... on ProjectV2SingleSelectField {{ id name options {{ id name }} }}
      }}
    }}
  }}
}}
"""
        data = await self._request(
            query,
            {
                "login": self._project_login,
                "number": self._project_number,
                "field": self._status_field,
            },
        )
        owner = (data.get("data") or {}).get(owner_kind)
        project = (owner or {}).get("projectV2") if owner else None
        if not project:
            raise GitHubNotFound(
                f"Projects v2 board {self._project_login}/{self._project_number} "
                "not found (check the project number and token 'project' scope)"
            )
        field = project.get("field")
        if not field or "options" not in field:
            raise GitHubRequestError(
                f"Projects v2 board {self._project_login}/{self._project_number} has "
                f"no single-select field named {self._status_field!r}"
            )
        options = {
            (o.get("name") or "").lower(): o["id"] for o in field["options"]
        }
        self._meta = _ProjectMeta(
            owner_kind=owner_kind,
            project_id=project["id"],
            title=project.get("title"),
            field_id=field["id"],
            options=options,
        )
        return self._meta

    async def _owner_kind(self) -> str:
        """Whether the board owner is a ``user`` or an ``organization``.

        Projects v2 hang off either a User or an Organization, and the GraphQL
        root field differs; resolving the owner's ``__typename`` first picks the
        right one without a null-vs-error guess.
        """
        query = """
query OwnerKind($login: String!) { repositoryOwner(login: $login) { __typename } }
"""
        data = await self._request(query, {"login": self._project_login})
        owner = (data.get("data") or {}).get("repositoryOwner")
        if owner is None:
            raise GitHubNotFound(
                f"GitHub owner {self._project_login!r} not found"
            )
        return "organization" if owner.get("__typename") == "Organization" else "user"

    # ------------------------------------------------------------------
    # Internal — issue-node helpers and the shared marked-branch read
    # ------------------------------------------------------------------

    async def _issue_node(
        self,
        query: str,
        number: int,
        path: tuple[str, ...],
        *,
        extra_variables: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Run ``query`` for an issue by number and return the issue node.

        ``path`` is the key sequence below ``repository`` down to the issue node
        (``("issue",)`` for a direct ``repository.issue`` query). ``extra_variables``
        merges into the standard ``owner``/``name``/``number`` set, for a query
        that needs one more (e.g. :meth:`issue_is_done`'s ``$field``). Raises
        :class:`GitHubNotFound` when the repository or issue is absent.
        """
        data = await self._request(
            query,
            {
                "owner": self._owner,
                "name": self._name,
                "number": number,
                **(extra_variables or {}),
            },
        )
        node: Any = (data.get("data") or {}).get("repository")
        if node is None:
            raise GitHubNotFound(
                f"GitHub repository {self._owner}/{self._name} not found"
            )
        for key in path:
            node = (node or {}).get(key)
        if node is None:
            raise GitHubNotFound(f"GitHub issue #{number} not found")
        return dict(node)

    async def _issue_node_id(self, identifier: str) -> str:
        """The GraphQL node id of an issue by identifier (for node-keyed mutations)."""
        number = _issue_number(identifier)
        query = """
query IssueNode($owner: String!, $name: String!, $number: Int!) {
  repository(owner: $owner, name: $name) { issue(number: $number) { id } }
}
"""
        issue = await self._issue_node(query, number, ("issue",))
        return str(issue["id"])

    async def _create_label(self, repo_id: str, name: str) -> str:
        """Create label ``name`` on the repo and return its id."""
        mutation = """
mutation CreateLabel($repoId: ID!, $name: String!, $color: String!) {
  createLabel(input: {repositoryId: $repoId, name: $name, color: $color}) {
    label { id }
  }
}
"""
        result = await self._request(
            mutation,
            {"repoId": repo_id, "name": name, "color": _DEFAULT_LABEL_COLOR},
        )
        label = ((result.get("data") or {}).get("createLabel") or {}).get("label")
        if not label:
            raise GitHubRequestError(
                f"GitHub createLabel returned no label for {name!r}; "
                f"response: {result!r}"
            )
        return str(label["id"])

    async def _latest_marked_branch(
        self,
        identifier: str,
        *,
        marker: str,
        parser: Callable[[str], str | None],
        require_label: str | None = None,
    ) -> str | None:
        """The branch named by the latest issue comment carrying ``marker``, or ``None``.

        The GitHub mirror of :meth:`~harness.linear.LinearClient._latest_marked_branch`
        behind both resume (death-keyed, label-gated) and handoff (proactive, no
        gate). The **latest** matching comment wins; every non-match returns
        ``None`` so the caller restarts clean. ``comments(last: 100)`` windows the
        newest comments so the freshest marker is always on the page.

        Raises:
            GitHubNotFound: the issue does not exist.
            GitHubRequestError: the API returned an error.
        """
        number = _issue_number(identifier)
        query = """
query MarkedBranch($owner: String!, $name: String!, $number: Int!) {
  repository(owner: $owner, name: $name) {
    issue(number: $number) {
      labels(first: 50) { nodes { name } }
      comments(last: 100) { nodes { body createdAt } }
    }
  }
}
"""
        issue = await self._issue_node(query, number, ("issue",))
        if require_label is not None:
            label_names = {
                (n.get("name") or "").lower()
                for n in (issue.get("labels") or {}).get("nodes", [])
            }
            if require_label.lower() not in label_names:
                return None
        comment_nodes: list[dict[str, Any]] = (
            (issue.get("comments") or {}).get("nodes", [])
        )
        marked = [c for c in comment_nodes if marker in (c.get("body") or "")]
        if not marked:
            return None
        latest = max(marked, key=lambda c: c.get("createdAt") or "")
        return parser(latest.get("body") or "")

    # ------------------------------------------------------------------
    # Internal HTTP helper
    # ------------------------------------------------------------------

    async def _request(self, query: str, variables: dict[str, Any]) -> dict[str, Any]:
        """POST a GraphQL request and return the parsed JSON body.

        The blocking ``urllib`` call runs in a worker thread, mirroring the Linear
        client so the public API is async.

        Raises:
            GitHubRequestError: on any transport error or a GraphQL ``errors`` block.
        """
        return await asyncio.to_thread(self._request_sync, query, variables)

    def _request_sync(self, query: str, variables: dict[str, Any]) -> dict[str, Any]:
        """Blocking implementation of :meth:`_request` — runs off the event loop."""
        body = json.dumps({"query": query, "variables": variables}).encode()
        req = urllib.request.Request(  # noqa: S310
            _GITHUB_API_URL,
            data=body,
            headers={
                "Authorization": f"Bearer {self._token}",
                "Content-Type": "application/json",
                "User-Agent": _USER_AGENT,
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:  # noqa: S310
                raw = resp.read().decode()
        except urllib.error.HTTPError as exc:
            raise GitHubRequestError(
                f"GitHub API HTTP {exc.code}: {exc.reason}"
            ) from exc
        except urllib.error.URLError as exc:
            raise GitHubRequestError(
                f"GitHub API unreachable: {exc.reason}"
            ) from exc
        except OSError as exc:
            raise GitHubRequestError(f"GitHub API request failed: {exc}") from exc

        try:
            payload: dict[str, Any] = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise GitHubRequestError(
                f"GitHub API returned non-JSON: {raw[:200]!r}"
            ) from exc

        errors = payload.get("errors")
        if errors:
            msg = "; ".join(e.get("message", str(e)) for e in errors)
            raise GitHubRequestError(f"GitHub GraphQL error: {msg}")

        return payload
