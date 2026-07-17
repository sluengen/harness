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
back to the first ``started`` state — a deterministic name-then-type fallback.

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
from collections.abc import Callable
from typing import Any

from harness.reclaim_marker import (
    HANDOFF_MARKER,
    RECLAIM_LABEL,
    RECLAIM_MARKER,
    parse_handoff_branch,
    parse_preserved_branch,
)

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

    async def fetch_issue_project(self, identifier: str) -> str | None:
        """Return the name of the project issue ``identifier`` belongs to, or ``None``.

        The Build-queue membership check ``harness defer`` binds to (CAL-1143):
        the verb only defers a ticket on this repo's ``repo.project``, so it reads
        the ticket's project name and compares. ``None`` means the issue is on no
        project — the caller treats that as "not on the Build queue".

        Raises:
            LinearNotFound: the issue does not exist.
            LinearRequestError: the API returned an error.
        """
        query = """
query IssueProject($id: String!) {
  issue(id: $id) {
    id
    project {
      name
    }
  }
}
"""
        data = await self._request(query, {"id": identifier})
        issue = (data.get("data") or {}).get("issue")
        if issue is None:
            raise LinearNotFound(f"Linear issue {identifier!r} not found")
        project = issue.get("project") or {}
        name = project.get("name")
        return str(name) if name else None

    async def fetch_reclaimable_issues(
        self, *, project: str
    ) -> list[dict[str, str]]:
        """List the reclaimable issues in ``project`` as ``[{identifier, updated_at}]``.

        The enumeration the ``harness reclaim --stale`` sweep (CAL-736) filters by
        age.  Scoped to the named project and **both** transient ``started`` states
        — **In Progress** *and* **In Review** — by name.  Before CAL-1103 In Review
        was only ever a human handoff, so the sweep deliberately skipped it; now
        ``review`` parks a reviewed ticket In Review as a normal step of the
        autonomous verb loop, so a dead orchestrator between ``review`` and
        ``close`` can strand a ticket there — exactly the wedged-queue failure the
        sweep exists to unblock.  Staleness (the ``updatedAt`` threshold, proposal
        D2) remains the only abandonment signal: a live review→close never idles
        that long, so a stale ticket in either state is a dead run.  ``updated_at``
        carries Linear's ``updatedAt`` (ISO-8601 UTC): the staleness signal the
        sweep compares against its threshold.  Requests up to 100 issues unpaged —
        a single project never holds more simultaneously-active tickets than that.

        Raises:
            LinearRequestError: the API returned an error or an unexpected response.
        """
        query = """
query ReclaimableIssues($project: String!) {
  issues(
    first: 100
    filter: {
      project: { name: { eq: $project } }
      state: { name: { in: ["In Progress", "In Review"] } }
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
        return await self._latest_marked_branch(
            identifier,
            marker=RECLAIM_MARKER,
            parser=parse_preserved_branch,
            require_label=RECLAIM_LABEL,
        )

    async def _latest_marked_branch(
        self,
        identifier: str,
        *,
        marker: str,
        parser: Callable[[str], str | None],
        require_label: str | None = None,
    ) -> str | None:
        """The branch named by the latest comment carrying ``marker``, or ``None``.

        The shared read path behind :meth:`fetch_resume_branch` (death-keyed
        reclaim) and :meth:`fetch_handoff_branch` (proactive context-rollover),
        which differ only in three parameters: the comment ``marker`` they scan
        for, the ``parser`` that pulls the ref out of a matching body, and — for
        reclaim only — a ``require_label`` gate. The **latest** matching comment
        wins (a ticket marked more than once resumes from its freshest branch),
        and every non-match (no ``require_label``, no marked comment, a marker
        that preserved no branch) returns ``None`` so the caller restarts clean.

        ``last: 20`` — Linear's default connection order is oldest-first, so
        ``first`` would return the *oldest* comments and drop the freshest marker
        (posted just before the re-pick) off the page on a ticket with >20
        comments. Window newest-first so the latest marker is always present
        (CAL-1005). Labels are queried only when a ``require_label`` gate applies.

        Raises:
            LinearNotFound: the issue does not exist.
            LinearRequestError: the API returned an error.
        """
        labels_block = "labels { nodes { name } }\n    " if require_label else ""
        query = f"""
query MarkedBranch($id: String!) {{
  issue(id: $id) {{
    {labels_block}comments(last: 20) {{ nodes {{ body createdAt }} }}
  }}
}}
"""
        data = await self._request(query, {"id": identifier})
        issue = (data.get("data") or {}).get("issue")
        if issue is None:
            raise LinearNotFound(f"Linear issue {identifier!r} not found")

        if require_label is not None:
            label_names = {
                (n.get("name") or "").lower()
                for n in (issue.get("labels") or {}).get("nodes", [])
            }
            if require_label not in label_names:
                return None

        comment_nodes: list[dict[str, Any]] = (
            (issue.get("comments") or {}).get("nodes", [])
        )
        marked = [c for c in comment_nodes if marker in (c.get("body") or "")]
        if not marked:
            return None
        latest = max(marked, key=lambda c: c.get("createdAt") or "")
        return parser(latest.get("body") or "")

    async def fetch_handoff_branch(self, identifier: str) -> str | None:
        """The preserved WIP branch a **proactively handed-off** ticket continues from.

        Proactive context-rollover handoff (proposal
        ``ground-specs-and-context-rollover`` WS-B / CAL-923): a session that is
        *alive but near its context limit* checkpoints its WIP and posts a
        :data:`~harness.reclaim_marker.HANDOFF_MARKER` comment naming the pushed
        branch, so a fresh session continues the **same** ticket. This reads that
        branch back.

        The counterpart to :meth:`fetch_resume_branch`, and deliberately
        different in one way: a proactive handoff keeps the ticket **In Progress**
        and applies **no** ``reclaimed`` label (it is not a reclamation), so this
        keys **only** on the handoff marker in a comment — there is no label gate.
        The handoff marker is distinct from the reclaim marker, so this never
        picks up a death-keyed reclaim comment (and ``fetch_resume_branch`` never
        picks up a handoff comment). The **latest** handoff comment wins. Every
        other case — no handoff comment, a handoff that preserved no durable WIP
        (the sentinel) — returns ``None`` so the caller restarts clean.

        Raises:
            LinearNotFound: the issue does not exist.
            LinearRequestError: the API returned an error.
        """
        return await self._latest_marked_branch(
            identifier,
            marker=HANDOFF_MARKER,
            parser=parse_handoff_branch,
        )

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

    async def transition_to_in_review(self, identifier: str) -> None:
        """Transition issue ``identifier`` to its In Review state.

        The transition ``review`` owns (CAL-1103): a ticket parked here is being
        reviewed, distinct from In Progress (being built).  In Review shares the
        ``started`` type with In Progress, so this disambiguates by **name** —
        :meth:`_transition` prefers a state literally named "In Review", falling
        back to the first ``started`` state only if none is named that.

        Raises:
            LinearNotFound: the issue does not exist.
            LinearRequestError: the API returned an error, no ``started``
                workflow state is configured on the issue's team, or the
                ``issueUpdate`` mutation did not report ``success: true``.
        """
        await self._transition(
            identifier, state_type="started", preferred_name="in review"
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

    async def create_issue(
        self,
        *,
        team_key: str,
        project_name: str | None,
        title: str,
        description: str,
    ) -> dict[str, str]:
        """Create a Todo issue on team ``team_key`` and return ``{identifier, url}``.

        The primitive behind ``harness promote escalate`` (CAL-1118): file a fresh
        escalation ticket carrying the promotion evidence. Resolves the team id
        from its key, the Todo (``unstarted``) workflow state, and — when
        ``project_name`` is given — the project id by name, all at runtime (never a
        hard-coded UUID, the same discipline as :meth:`apply_label`), then fires
        ``issueCreate`` into that team/project/state.

        Raises:
            LinearNotFound: no team with ``team_key`` exists.
            LinearRequestError: the API errored, ``project_name`` names no project
                on the team, the team has no ``unstarted`` (Todo) state, or
                ``issueCreate`` did not return an issue.
        """
        team_query = """
query TeamForIssue($key: String!) {
  teams(filter: { key: { eq: $key } }, first: 1) {
    nodes {
      id
      states { nodes { id name type } }
      projects { nodes { id name } }
    }
  }
}
"""
        data = await self._request(team_query, {"key": team_key})
        team_nodes = ((data.get("data") or {}).get("teams") or {}).get("nodes") or []
        if not team_nodes:
            raise LinearNotFound(f"Linear team {team_key!r} not found")
        team = team_nodes[0]
        team_id: str = team["id"]

        state_id = self._select_todo_state(team, team_key)
        project_id = self._resolve_project_id(team, project_name, team_key)

        mutation = """
mutation CreateIssue(
  $teamId: String!
  $title: String!
  $description: String!
  $stateId: String
  $projectId: String
) {
  issueCreate(
    input: {
      teamId: $teamId
      title: $title
      description: $description
      stateId: $stateId
      projectId: $projectId
    }
  ) {
    success
    issue {
      identifier
      url
    }
  }
}
"""
        result = await self._request(
            mutation,
            {
                "teamId": team_id,
                "title": title,
                "description": description,
                "stateId": state_id,
                "projectId": project_id,
            },
        )
        payload = (result.get("data") or {}).get("issueCreate") or {}
        issue = payload.get("issue")
        if not payload.get("success") or not issue:
            raise LinearRequestError(
                f"Linear issueCreate did not return an issue for team {team_key!r}; "
                f"response: {result!r}"
            )
        return {"identifier": str(issue["identifier"]), "url": str(issue["url"])}

    @staticmethod
    def _select_todo_state(team: dict[str, Any], team_key: str) -> str:
        """The team's Todo state id — a state named "Todo", else the first
        ``unstarted`` state (the same name-then-type resolution as
        :meth:`transition_to_unstarted`)."""
        nodes: list[dict[str, Any]] = (team.get("states") or {}).get("nodes", [])
        candidates = [n for n in nodes if n.get("type") == "unstarted"]
        if not candidates:
            raise LinearRequestError(
                f"Linear team {team_key!r} has no 'unstarted' (Todo) workflow state"
            )
        named = [n for n in candidates if (n.get("name") or "").lower() == "todo"]
        return str((named[0] if named else candidates[0])["id"])

    @staticmethod
    def _resolve_project_id(
        team: dict[str, Any], project_name: str | None, team_key: str
    ) -> str | None:
        """The id of the team's project named ``project_name``, or ``None`` when no
        project was requested. Raises when a named project is not found."""
        if project_name is None:
            return None
        nodes: list[dict[str, Any]] = (team.get("projects") or {}).get("nodes", [])
        project = next(
            (p for p in nodes if (p.get("name") or "") == project_name), None
        )
        if project is None:
            raise LinearRequestError(
                f"Linear team {team_key!r} has no project named {project_name!r}"
            )
        return str(project["id"])

    async def _transition(
        self, identifier: str, *, state_type: str, preferred_name: str
    ) -> None:
        """Move issue ``identifier`` to a workflow state of ``state_type``.

        Shared implementation behind :meth:`transition_to_in_progress`,
        :meth:`transition_to_done`, and :meth:`transition_to_unstarted`.  Queries
        the team's workflow states, selects
        a state literally named ``preferred_name`` (case-insensitive) if present
        else the first state of ``state_type``, then fires an ``issueUpdate``
        mutation.

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
