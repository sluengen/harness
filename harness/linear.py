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

        # Mirror build-codex.yaml: prefer a state named "in progress";
        # fall back to first started-type state.
        started = [n for n in nodes if n.get("type") == "started"]
        if not started:
            raise LinearRequestError(
                f"Linear issue {identifier!r} has no 'started' workflow state configured; "
                "cannot transition to In Progress"
            )

        ip_named = [
            n for n in started if (n.get("name") or "").lower() == "in progress"
        ]
        target = ip_named[0] if ip_named else started[0]
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

        # Prefer a state named "done"; fall back to first completed-type state.
        completed = [n for n in nodes if n.get("type") == "completed"]
        if not completed:
            raise LinearRequestError(
                f"Linear issue {identifier!r} has no 'completed' workflow state configured; "
                "cannot transition to Done"
            )

        done_named = [n for n in completed if (n.get("name") or "").lower() == "done"]
        target = done_named[0] if done_named else completed[0]
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
