"""Linear GraphQL client for ``harness start`` — fetch and transition issues.

Uses ``urllib.request`` (stdlib) rather than an external HTTP library so the
harness remains deployable in minimal environments without ``httpx`` or
``requests``.  The blocking ``urllib`` calls are offloaded to a worker thread
via :func:`asyncio.to_thread` so the public client API is async — matching the
repository's "async by default for I/O" convention.

Only the fields the agent needs to implement against are extracted from the
Linear response (SPEC context-economy constraint):

    {id, identifier, title, description, url}

The ``transition_to_in_progress`` method first queries the issue's team states
to find the "In Progress" (``type=started``) state, then fires the
``issueUpdate`` mutation.  If no "In Progress"-named state is found it falls
back to the first ``started`` state — matching the build-codex.yaml logic.

Environment variable: ``LINEAR_API_KEY`` must be set before constructing a
:class:`LinearClient`.  :func:`linear_api_key` raises :class:`LinearConfigError`
when the variable is absent.
"""

from __future__ import annotations

import asyncio
import json
import os
import urllib.error
import urllib.request
from typing import Any

from harness.reclaim_marker import RECLAIM_LABEL, RECLAIM_MARKER, parse_preserved_branch

# size: one cohesive Linear GraphQL boundary class. The CAL-731 embed guard
# requires every Linear GraphQL operation to live in this client (never in
# command prose), so the surface grows one query-method at a time; splitting the
# client to chase the 500-line limit would scatter that boundary, not clarify it.

__all__ = [
    "LinearClient",
    "LinearConfigError",
    "LinearNotFound",
    "LinearRequestError",
    "linear_api_key",
]

_LINEAR_API_URL = "https://api.linear.app/graphql"

# Compact ticket fields — only what the implementing agent needs.
_TICKET_FIELDS = ("id", "identifier", "title", "description", "url")


class LinearConfigError(RuntimeError):
    """Raised when required Linear configuration (e.g. API key) is missing."""


class LinearNotFound(RuntimeError):  # noqa: N818 — SPEC vocab, not PEP 8 Error suffix
    """Raised when the requested issue does not exist or is inaccessible."""


class LinearRequestError(RuntimeError):
    """Raised when the Linear API returns an error or an unexpected response."""


def linear_api_key() -> str:
    """Return the ``LINEAR_API_KEY`` environment variable.

    Raises:
        LinearConfigError: when the variable is not set.
    """
    key = os.environ.get("LINEAR_API_KEY")
    if not key:
        raise LinearConfigError(
            "LINEAR_API_KEY environment variable is not set; "
            "export it before running ``harness start``"
        )
    return key


class LinearClient:
    """Minimal async Linear GraphQL client.

    The blocking ``urllib`` HTTP call is offloaded to a worker thread so the
    public API is async.

    Args:
        api_key: Linear personal API token.  Use :func:`linear_api_key` to
            read it from the environment.
    """

    def __init__(self, api_key: str) -> None:
        self._api_key = api_key

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    async def fetch_issue(self, identifier: str) -> dict[str, Any]:
        """Fetch issue ``identifier`` and return a compact ticket dict.

        Returns a dict with keys: ``id``, ``identifier``, ``title``,
        ``description``, ``url``.

        Raises:
            LinearNotFound: the issue does not exist.
            LinearRequestError: the API returned an error.
        """
        query = """
query FetchIssue($id: String!) {
  issue(id: $id) {
    id
    identifier
    title
    description
    url
  }
}
"""
        data = await self._request(query, {"id": identifier})
        raw = (data.get("data") or {}).get("issue")
        if raw is None:
            raise LinearNotFound(f"Linear issue {identifier!r} not found")
        return {k: raw.get(k) for k in _TICKET_FIELDS}

    async def fetch_in_progress_issues(
        self, *, project: str
    ) -> list[dict[str, str]]:
        """List the In-Progress issues in ``project`` as ``[{identifier, updated_at}]``.

        The enumeration the ``harness reclaim --stale`` sweep (CAL-736) filters by
        age.  Scoped to the named project and the **In Progress** state by name, so
        the other ``started`` state — In Review, a legitimate handoff — is never
        swept up.  ``updated_at`` carries Linear's ``updatedAt`` (ISO-8601 UTC):
        the staleness signal the sweep compares against its threshold (proposal
        D2).  Requests up to 100 issues unpaged — a single project never holds more
        simultaneously-In-Progress tickets than that.

        Raises:
            LinearRequestError: the API returned an error or an unexpected response.
        """
        query = """
query InProgressIssues($project: String!) {
  issues(
    first: 100
    filter: {
      project: { name: { eq: $project } }
      state: { name: { eq: "In Progress" } }
    }
  ) {
    nodes {
      identifier
      updatedAt
    }
  }
}
"""
        data = await self._request(query, {"project": project})
        nodes = ((data.get("data") or {}).get("issues") or {}).get("nodes") or []
        return [
            {"identifier": n["identifier"], "updated_at": n["updatedAt"]}
            for n in nodes
        ]

    async def fetch_resume_branch(self, identifier: str) -> str | None:
        """The preserved WIP branch a reclaimed ticket can resume from, or ``None``.

        Resume (proposal ``stale-run-reclamation`` D4 / CAL-739): when a run's
        orchestrator died, ``harness reclaim`` reverted the ticket to Todo and
        posted a comment naming the checkpoint-pushed branch the next run
        continues from. This reads it back — the durable record survives to a
        fresh container because it lives on **Linear**, not the dead checkout.

        Returns the branch only when the ticket still carries the ``reclaimed``
        label **and** its latest reclaim comment names a real branch. The label
        is the structured gate (the ticket is a reclamation re-pick); the comment
        carries the ref. Every other case — not reclaimed, a reclaim that
        preserved no durable WIP (the sentinel), or no parseable reclaim comment —
        returns ``None`` so the caller restarts clean rather than resume a wrong
        ref. The **latest** reclaim comment wins, so a ticket reclaimed more than
        once resumes from its freshest branch.

        Raises:
            LinearNotFound: the issue does not exist.
            LinearRequestError: the API returned an error.
        """
        query = """
query ResumeBranch($id: String!) {
  issue(id: $id) {
    labels { nodes { name } }
    comments(first: 20) { nodes { body createdAt } }
  }
}
"""
        data = await self._request(query, {"id": identifier})
        issue = (data.get("data") or {}).get("issue")
        if issue is None:
            raise LinearNotFound(f"Linear issue {identifier!r} not found")

        label_names = {
            (n.get("name") or "").lower()
            for n in (issue.get("labels") or {}).get("nodes", [])
        }
        if RECLAIM_LABEL not in label_names:
            return None

        comment_nodes: list[dict[str, Any]] = (
            (issue.get("comments") or {}).get("nodes", [])
        )
        reclaim_comments = [
            c for c in comment_nodes if RECLAIM_MARKER in (c.get("body") or "")
        ]
        if not reclaim_comments:
            return None
        latest = max(reclaim_comments, key=lambda c: c.get("createdAt") or "")
        return parse_preserved_branch(latest.get("body") or "")

    async def transition_to_in_progress(self, identifier: str) -> None:
        """Transition issue ``identifier`` to the first In Progress state.

        Queries the team's workflow states to locate the In Progress state id,
        then fires an ``issueUpdate`` mutation.

        Raises:
            LinearNotFound: the issue does not exist.
            LinearRequestError: the API returned an error, no ``started``
                workflow state is configured on the issue's team, or the
                ``issueUpdate`` mutation did not report ``success: true``.
        """
        await self._transition(
            identifier, state_type="started", preferred_name="in progress"
        )

    async def transition_to_done(self, identifier: str) -> None:
        """Transition issue ``identifier`` to its completed (Done) state.

        Queries the team's workflow states to locate the completed state id,
        then fires an ``issueUpdate`` mutation.  Mirrors
        :meth:`transition_to_in_progress` but targets ``type=='completed'``:
        prefers a state literally named "Done", else the first completed-type
        state.

        Raises:
            LinearNotFound: the issue does not exist.
            LinearRequestError: the API returned an error, no ``completed``
                workflow state is configured on the issue's team, or the
                ``issueUpdate`` mutation did not report ``success: true``.
        """
        await self._transition(
            identifier, state_type="completed", preferred_name="done"
        )

    async def transition_to_unstarted(self, identifier: str) -> None:
        """Transition issue ``identifier`` back to its Todo (unstarted) state.

        The revert a reclamation sweep applies to a ticket stranded In Progress
        by a dead run (proposal ``stale-run-reclamation``).  Mirrors
        :meth:`transition_to_in_progress` but targets ``type=='unstarted'``:
        prefers a state literally named "Todo", else the first unstarted-type
        state.

        Raises:
            LinearNotFound: the issue does not exist.
            LinearRequestError: the API returned an error, no ``unstarted``
                workflow state is configured on the issue's team, or the
                ``issueUpdate`` mutation did not report ``success: true``.
        """
        await self._transition(
            identifier, state_type="unstarted", preferred_name="todo"
        )

    async def apply_label(self, identifier: str, name: str) -> None:
        """Resolve (creating if absent) the label ``name`` and add it to ``identifier``.

        Resolves the label id at runtime from the issue's team labels — never a
        hard-coded UUID — matching it case-insensitively; if no such label
        exists it is created on the issue's team.  Adds it with ``issueAddLabel``
        so any labels already on the issue are preserved.

        The caller supplies the label name (e.g. reclamation passes
        ``"reclaimed"``), keeping this client a generic primitive.

        Raises:
            LinearNotFound: the issue does not exist.
            LinearRequestError: the API returned an error, label creation
                returned no label, or ``issueAddLabel`` did not report
                ``success: true``.
        """
        labels_query = """
query IssueTeamLabels($id: String!) {
  issue(id: $id) {
    id
    team {
      id
      labels {
        nodes {
          id
          name
        }
      }
    }
  }
}
"""
        data = await self._request(labels_query, {"id": identifier})
        issue = (data.get("data") or {}).get("issue")
        if issue is None:
            raise LinearNotFound(f"Linear issue {identifier!r} not found")
        issue_id: str = issue["id"]
        team = issue.get("team") or {}
        team_id: str = team["id"]
        label_nodes: list[dict[str, Any]] = (team.get("labels") or {}).get("nodes", [])

        target = next(
            (n for n in label_nodes if (n.get("name") or "").lower() == name.lower()),
            None,
        )
        if target is not None:
            label_id: str = target["id"]
        else:
            label_id = await self._create_label(name, team_id)

        add_mutation = """
mutation AddLabel($id: String!, $labelId: String!) {
  issueAddLabel(id: $id, labelId: $labelId) {
    success
  }
}
"""
        result = await self._request(
            add_mutation, {"id": issue_id, "labelId": label_id}
        )
        success = (result.get("data") or {}).get("issueAddLabel", {}).get("success")
        if not success:
            raise LinearRequestError(
                f"Linear issueAddLabel did not report success for {identifier!r}; "
                f"response: {result!r}"
            )

    async def _create_label(self, name: str, team_id: str) -> str:
        """Create label ``name`` on team ``team_id`` and return its id."""
        create_mutation = """
mutation CreateLabel($name: String!, $teamId: String!) {
  issueLabelCreate(input: {name: $name, teamId: $teamId}) {
    success
    issueLabel {
      id
    }
  }
}
"""
        created = await self._request(
            create_mutation, {"name": name, "teamId": team_id}
        )
        payload = (created.get("data") or {}).get("issueLabelCreate") or {}
        label_id = (payload.get("issueLabel") or {}).get("id")
        if not payload.get("success") or not label_id:
            raise LinearRequestError(
                f"Linear issueLabelCreate did not return a label for {name!r}; "
                f"response: {created!r}"
            )
        return str(label_id)

    async def post_comment(self, identifier: str, body: str) -> None:
        """Post a comment with ``body`` to issue ``identifier`` (``commentCreate``).

        Resolves the issue's UUID first (``commentCreate`` keys on the id, not
        the identifier), then fires the mutation.

        Raises:
            LinearNotFound: the issue does not exist.
            LinearRequestError: the API returned an error or ``commentCreate``
                did not report ``success: true``.
        """
        id_query = """
query IssueId($id: String!) {
  issue(id: $id) {
    id
  }
}
"""
        data = await self._request(id_query, {"id": identifier})
        issue = (data.get("data") or {}).get("issue")
        if issue is None:
            raise LinearNotFound(f"Linear issue {identifier!r} not found")
        issue_id: str = issue["id"]

        mutation = """
mutation AddComment($issueId: String!, $body: String!) {
  commentCreate(input: {issueId: $issueId, body: $body}) {
    success
  }
}
"""
        result = await self._request(
            mutation, {"issueId": issue_id, "body": body}
        )
        success = (result.get("data") or {}).get("commentCreate", {}).get("success")
        if not success:
            raise LinearRequestError(
                f"Linear commentCreate did not report success for {identifier!r}; "
                f"response: {result!r}"
            )

    async def _transition(
        self, identifier: str, *, state_type: str, preferred_name: str
    ) -> None:
        """Move issue ``identifier`` to a workflow state of ``state_type``.

        Shared implementation behind :meth:`transition_to_in_progress`,
        :meth:`transition_to_done`, and :meth:`transition_to_unstarted`.  Queries
        the team's workflow states, selects
        a state literally named ``preferred_name`` (case-insensitive) if present
        else the first state of ``state_type``, then fires an ``issueUpdate``
        mutation.  Mirrors ``build-codex.yaml``.

        Raises:
            LinearNotFound: the issue does not exist.
            LinearRequestError: the API returned an error, no ``state_type``
                workflow state is configured on the issue's team, or the
                ``issueUpdate`` mutation did not report ``success: true``.
        """
        states_query = """
query IssueStates($id: String!) {
  issue(id: $id) {
    id
    team {
      states {
        nodes {
          id
          name
          type
        }
      }
    }
  }
}
"""
        data = await self._request(states_query, {"id": identifier})
        issue = (data.get("data") or {}).get("issue")
        if issue is None:
            raise LinearNotFound(f"Linear issue {identifier!r} not found")

        issue_id: str = issue["id"]
        nodes: list[dict[str, Any]] = (
            (issue.get("team") or {})
            .get("states", {})
            .get("nodes", [])
        )

        candidates = [n for n in nodes if n.get("type") == state_type]
        if not candidates:
            raise LinearRequestError(
                f"Linear issue {identifier!r} has no {state_type!r} workflow state configured; "
                f"cannot transition to {preferred_name.title()}"
            )

        named = [
            n for n in candidates if (n.get("name") or "").lower() == preferred_name
        ]
        target = named[0] if named else candidates[0]
        state_id: str = target["id"]

        mutation = """
mutation TransitionIssue($id: String!, $stateId: String!) {
  issueUpdate(id: $id, input: {stateId: $stateId}) {
    success
  }
}
"""
        result = await self._request(mutation, {"id": issue_id, "stateId": state_id})
        success = (result.get("data") or {}).get("issueUpdate", {}).get("success")
        if not success:
            raise LinearRequestError(
                f"Linear issueUpdate mutation did not report success for {identifier!r}; "
                f"response: {result!r}"
            )

    # ------------------------------------------------------------------
    # Internal HTTP helper
    # ------------------------------------------------------------------

    async def _request(self, query: str, variables: dict[str, Any]) -> dict[str, Any]:
        """POST a GraphQL request and return the parsed JSON body.

        The blocking ``urllib`` call runs in a worker thread.

        Raises:
            LinearRequestError: on any transport error (HTTP, connection,
                timeout) or malformed response.
        """
        return await asyncio.to_thread(self._request_sync, query, variables)

    def _request_sync(self, query: str, variables: dict[str, Any]) -> dict[str, Any]:
        """Blocking implementation of :meth:`_request` — runs off the event loop.

        Every transport-layer failure is converted to :class:`LinearRequestError`
        so callers only ever see the Linear boundary exception types.
        """
        body = json.dumps({"query": query, "variables": variables}).encode()
        req = urllib.request.Request(  # noqa: S310
            _LINEAR_API_URL,
            data=body,
            headers={
                "Authorization": self._api_key,
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:  # noqa: S310
                raw = resp.read().decode()
        except urllib.error.HTTPError as exc:
            raise LinearRequestError(
                f"Linear API HTTP {exc.code}: {exc.reason}"
            ) from exc
        except urllib.error.URLError as exc:
            raise LinearRequestError(
                f"Linear API unreachable: {exc.reason}"
            ) from exc
        except OSError as exc:
            # Covers socket.timeout / TimeoutError and any other transport
            # failure not wrapped by urllib (e.g. a timeout during read).
            raise LinearRequestError(
                f"Linear API request failed: {exc}"
            ) from exc

        try:
            payload: dict[str, Any] = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise LinearRequestError(
                f"Linear API returned non-JSON: {raw[:200]!r}"
            ) from exc

        errors = payload.get("errors")
        if errors:
            msg = "; ".join(e.get("message", str(e)) for e in errors)
            raise LinearRequestError(f"Linear GraphQL error: {msg}")

        return payload
