"""Linear GraphQL API client.

Thin wrapper around Linear's GraphQL API for operations used by the harness:
get/update issues, add comments, list workflow statuses.

Auth: reads LINEAR_API_KEY from environment. Load .env before importing if
running outside a shell that has already sourced it.
"""

from __future__ import annotations

import os

import httpx

API_URL = "https://api.linear.app/graphql"
DEFAULT_TIMEOUT = 30.0


class LinearAPIError(Exception):
    """Raised when Linear returns a GraphQL error or unexpected HTTP status."""


class LinearRateLimitError(LinearAPIError):
    """Raised when Linear returns a RATELIMITED error code."""

    def __init__(self, message: str, retry_after: int | None = None):
        super().__init__(message)
        self.retry_after = retry_after


class LinearClient:
    """Synchronous Linear GraphQL client."""

    def __init__(self, api_key: str | None = None):
        self.api_key = api_key or os.environ.get("LINEAR_API_KEY", "")
        if not self.api_key:
            raise ValueError(
                "LINEAR_API_KEY is required. Set it in .env or the environment."
            )

    def _request(self, query: str, variables: dict | None = None) -> dict:
        headers = {
            "Authorization": self.api_key,
            "Content-Type": "application/json",
        }
        payload: dict = {"query": query}
        if variables:
            payload["variables"] = variables

        resp = httpx.post(API_URL, json=payload, headers=headers, timeout=DEFAULT_TIMEOUT)

        try:
            body = resp.json()
        except Exception:
            raise LinearAPIError(f"HTTP {resp.status_code}: {resp.text}")

        if "errors" in body and body["errors"]:
            error = body["errors"][0]
            message = error.get("message", "Unknown GraphQL error")
            extensions = error.get("extensions", {})
            if extensions.get("code") == "RATELIMITED":
                retry_after = None
                raw = resp.headers.get("retry-after")
                if raw is not None:
                    try:
                        retry_after = int(raw)
                    except ValueError:
                        pass
                raise LinearRateLimitError(message, retry_after=retry_after)
            raise LinearAPIError(message)

        if resp.status_code >= 400:
            raise LinearAPIError(f"HTTP {resp.status_code}: {resp.text}")

        return body.get("data", {})

    def get_issue(self, identifier: str) -> dict:
        """Return full details for a single issue by identifier (e.g. CAL-497)."""
        query = """
        query GetIssue($identifier: String!) {
            issue(id: $identifier) {
                id
                identifier
                title
                priority
                description
                state { id name }
                labels { nodes { id name } }
                url
            }
        }
        """
        data = self._request(query, {"identifier": identifier})
        issue = data.get("issue")
        if issue is None:
            raise LinearAPIError(f"Issue {identifier} not found")
        issue["labels"] = [lb["name"] for lb in issue.get("labels", {}).get("nodes", [])]
        return issue

    def list_statuses(self, team_id: str) -> dict[str, str]:
        """Return a mapping of workflow state name → ID for a team."""
        query = """
        query WorkflowStates($teamId: ID!) {
            workflowStates(filter: { team: { id: { eq: $teamId } } }) {
                nodes { id name type }
            }
        }
        """
        data = self._request(query, {"teamId": team_id})
        nodes = data.get("workflowStates", {}).get("nodes", [])
        return {node["name"]: node["id"] for node in nodes}

    def update_issue_state(self, issue_id: str, state_id: str) -> dict:
        """Move an issue to a different workflow state."""
        query = """
        mutation UpdateIssue($issueId: String!, $stateId: String!) {
            issueUpdate(id: $issueId, input: { stateId: $stateId }) {
                success
                issue { id identifier state { id name } }
            }
        }
        """
        data = self._request(query, {"issueId": issue_id, "stateId": state_id})
        return data.get("issueUpdate", {})

    def add_comment(self, issue_id: str, body: str) -> dict:
        """Add a comment to an issue (issue_id is the UUID, not the identifier)."""
        query = """
        mutation AddComment($issueId: String!, $body: String!) {
            commentCreate(input: { issueId: $issueId, body: $body }) {
                success
                comment { id body }
            }
        }
        """
        data = self._request(query, {"issueId": issue_id, "body": body})
        return data.get("commentCreate", {})
