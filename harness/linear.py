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

from harness.design_marker import is_design_comment
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
    TrackerTransitionUnconfirmed,
)
from harness.tracker_queue import QueueMembership

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


class LinearConfigError(TrackerConfigError):
    """Raised when required Linear configuration (e.g. API key) is missing."""


class LinearNotFound(TrackerNotFound):  # noqa: N818 — SPEC vocab, not PEP 8 Error suffix
    """Raised when the requested issue does not exist or is inaccessible."""


class LinearRequestError(TrackerRequestError):
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

    def __init__(self, api_key: str, *, team: str | None = None) -> None:
        self._api_key = api_key
        # The ``repo.linear`` team key, threaded in by :func:`harness.tracker.tracker_client`.
        # Used only to scope an unscoped reclaim sweep (``fetch_reclaimable_issues``
        # with no project) to this team rather than the whole workspace (#174).
        self._team = team

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    async def fetch_issue(self, identifier: str) -> dict[str, Any]:
        """Fetch issue ``identifier`` and return a compact ticket dict.

        Returns a dict with keys: ``id``, ``identifier``, ``title``,
        ``description``, ``url``, and ``labels`` (the issue's label names,
        e.g. for #177's model-tier resolution).

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
    labels { nodes { name } }
  }
}
"""
        data = await self._request(query, {"id": identifier})
        raw = (data.get("data") or {}).get("issue")
        if raw is None:
            raise LinearNotFound(f"Linear issue {identifier!r} not found")
        result: dict[str, Any] = {k: raw.get(k) for k in _TICKET_FIELDS}
        result["labels"] = [
            n.get("name") for n in (raw.get("labels") or {}).get("nodes", []) if n.get("name")
        ]
        return result

    async def fetch_queue_membership(
        self, identifier: str, *, project: str | None
    ) -> QueueMembership:
        """Whether issue ``identifier`` is on this repo's Build queue (CAL-1143, #248).

        The membership check ``harness defer`` / ``harness release`` bind to. The
        *scope* is nullable, mirroring :meth:`fetch_reclaimable_issues` (#174):

        * ``project`` set → the queue is that project; membership is
          ``issue's project name == project``.
        * ``project`` ``None`` (the whole-queue mode) → the queue is the client's
          ``repo.linear`` team, so an issue in that team is on the queue whatever
          project it does or does not sit in. With no team configured either, the
          repo has declared no scope at all and the only membership fact left is
          that the issue exists, so the answer is ``True``.

        The last case deliberately differs from :meth:`fetch_reclaimable_issues`,
        which *refuses* the same configuration: that call **enumerates** and would
        sweep every team the token can see, whereas this one resolves a single
        ticket the operator named explicitly. Refusing here for symmetry would
        re-wedge triage for exactly the class of repo #248 is about, just under a
        different reason.

        The returned ``project`` is always the issue's *own* project name (or
        ``None``), never the configured scope echoed back — it feeds the ledger
        event and ``--json`` when no scope is configured.

        The team is read in the **same** request as the project, so a nullable
        scope costs no extra round trip. Deriving it from the ``TEAM-123``
        identifier prefix instead was rejected: the API answers authoritatively
        here, and string-parsing an identifier is the kind of inference this
        method exists to remove.

        Raises:
            LinearNotFound: the issue does not exist.
            LinearRequestError: the API returned an error.
        """
        query = """
query IssueQueueMembership($id: String!) {
  issue(id: $id) {
    id
    project {
      name
    }
    team {
      key
    }
  }
}
"""
        data = await self._request(query, {"id": identifier})
        issue = (data.get("data") or {}).get("issue")
        if issue is None:
            raise LinearNotFound(f"Linear issue {identifier!r} not found")
        name = (issue.get("project") or {}).get("name")
        issue_project = str(name) if name else None

        if project is not None:
            return QueueMembership(on_queue=issue_project == project, project=issue_project)

        if self._team is None:
            return QueueMembership(on_queue=True, project=issue_project)

        team_key = (issue.get("team") or {}).get("key")
        return QueueMembership(on_queue=team_key == self._team, project=issue_project)

    async def fetch_reclaimable_issues(
        self, *, project: str | None
    ) -> list[dict[str, str]]:
        """List the reclaimable issues as ``[{identifier, updated_at}]``.

        The enumeration the ``harness reclaim --stale`` sweep (CAL-736) filters by
        age.  Scoped to **both** transient ``started`` states — **In Progress**
        *and* **In Review** — by name.  Before CAL-1103 In Review was only ever a
        human handoff, so the sweep deliberately skipped it; now ``review`` parks a
        reviewed ticket In Review as a normal step of the autonomous verb loop, so a
        dead orchestrator between ``review`` and ``close`` can strand a ticket there
        — exactly the wedged-queue failure the sweep exists to unblock.  Staleness
        (the ``updatedAt`` threshold, proposal D2) remains the only abandonment
        signal: a live review→close never idles that long, so a stale ticket in
        either state is a dead run.  ``updated_at`` carries Linear's ``updatedAt``
        (ISO-8601 UTC): the staleness signal the sweep compares against its
        threshold.  Requests up to 100 issues unpaged.

        The *scope* is nullable (#174).  ``project`` set → the named project.
        ``project`` ``None`` (the whole-queue mode) → the client's ``repo.linear``
        team, so a Linear team running several projects is swept whole.  It filters
        by **team**, never the bare workspace: an unscoped ``issues`` query would
        otherwise sweep every team the token can see (the proposal's stated risk), so
        with no project *and* no team there is nothing safe to scope to and the call
        is refused rather than run unbounded.

        Raises:
            LinearRequestError: the API returned an error or an unexpected response,
                or ``project`` is ``None`` and no ``repo.linear`` team scopes the sweep.
        """
        if project is not None:
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
            variables: dict[str, str] = {"project": project}
        elif self._team is not None:
            query = """
query ReclaimableIssues($team: String!) {
  issues(
    first: 100
    filter: {
      team: { key: { eq: $team } }
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
            variables = {"team": self._team}
        else:
            raise LinearRequestError(
                "an unscoped reclaim sweep needs a repo.linear team to scope to; "
                "none is configured, and sweeping the whole workspace is refused"
            )
        data = await self._request(query, variables)
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

    async def fetch_design_comment(self, identifier: str) -> str | None:
        """The body of the ticket's latest design comment, or ``None`` (#258).

        The read side of the design-comment contract, feeding ADR 0008's adopt
        path: a resumed run recovers its predecessor's design from the ticket
        rather than paying for a fresh Opus call. The **body** is returned
        verbatim rather than a parsed design, because the caller authenticates it
        by recomputing the content hash over exactly these bytes — parsing (and
        judging) is the caller's, and the seam stays free of design vocabulary.

        Selection is :func:`~harness.design_marker.is_design_comment`, the
        contract's own predicate, so this cannot drift from what the parser will
        accept. Unlike the two resume readers there is **no label gate**: a
        design comment is posted on every run, and no label marks it.

        Raises:
            LinearNotFound: the issue does not exist.
            LinearRequestError: the API returned an error.
        """
        return await self._latest_comment_body(identifier, matches=is_design_comment)

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

        Both resume markers are single formatter-written lines with no embedded
        free text, so a **substring** test identifies them safely — which is why
        the design reader, whose comments embed arbitrary markdown, does not
        share this predicate (#257).

        Raises:
            LinearNotFound: the issue does not exist.
            LinearRequestError: the API returned an error.
        """
        body = await self._latest_comment_body(
            identifier,
            matches=lambda candidate: marker in candidate,
            require_label=require_label,
        )
        return None if body is None else parser(body)

    async def _latest_comment_body(
        self,
        identifier: str,
        *,
        matches: Callable[[str], bool],
        require_label: str | None = None,
    ) -> str | None:
        """The body of the latest comment satisfying ``matches``, or ``None``.

        The one Linear read behind every marker-keyed reader — the two resume
        sources and the design reader — so the query, the windowing, the
        latest-wins rule and the label gate exist once. Callers differ only in
        the predicate that recognises their comment, and in what they do with the
        body they get back.

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
        marked = [c for c in comment_nodes if matches(c.get("body") or "")]
        if not marked:
            return None
        latest = max(marked, key=lambda c: c.get("createdAt") or "")
        return str(latest.get("body") or "")

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

    async def assign_to_viewer(self, identifier: str) -> None:
        """Assign issue ``identifier`` to the authenticated user — the operator.

        Agents authenticate with the operator's own API key and have no Linear
        identity of their own, so the API's ``viewer`` **is** the operator; an
        assignee at all is the machine-readable "a human holds this" signal the
        ``work-discovery`` held-tickets skip rule reads. Resolves the viewer id
        and the issue's UUID in one query, then fires ``issueUpdate(assigneeId)``.

        Raises:
            LinearNotFound: the issue does not exist.
            LinearRequestError: the API returned an error, the key resolved no
                viewer, or ``issueUpdate`` did not report ``success: true``.
        """
        resolve_query = """
query IssueAndViewer($id: String!) {
  viewer {
    id
  }
  issue(id: $id) {
    id
  }
}
"""
        data = await self._request(resolve_query, {"id": identifier})
        payload = data.get("data") or {}
        issue = payload.get("issue")
        if issue is None:
            raise LinearNotFound(f"Linear issue {identifier!r} not found")
        viewer_id = (payload.get("viewer") or {}).get("id")
        if not viewer_id:
            raise LinearRequestError(
                "Linear resolved no viewer for the API key; cannot assign "
                f"{identifier!r} to the operator"
            )
        issue_id: str = issue["id"]

        mutation = """
mutation AssignIssue($id: String!, $assigneeId: String!) {
  issueUpdate(id: $id, input: {assigneeId: $assigneeId}) {
    success
  }
}
"""
        result = await self._request(
            mutation, {"id": issue_id, "assigneeId": viewer_id}
        )
        success = (result.get("data") or {}).get("issueUpdate", {}).get("success")
        if not success:
            raise LinearRequestError(
                f"Linear issueUpdate did not report success assigning {identifier!r}; "
                f"response: {result!r}"
            )

    async def remove_label(self, identifier: str, name: str) -> None:
        """Remove the label ``name`` from ``identifier`` if present (``issueRemoveLabel``).

        The release-side mirror of :meth:`apply_label` (#193, the ``defer``
        shape in reverse): resolves the label id from the issue's **own**
        labels (not the team's full set — nothing to resolve-or-create), matched
        case-insensitively. A ticket that no longer carries the label is a clean
        no-op, so a release can run twice without erroring.

        Raises:
            LinearNotFound: the issue does not exist.
            LinearRequestError: the API returned an error, or ``issueRemoveLabel``
                did not report ``success: true``.
        """
        labels_query = """
query IssueLabels($id: String!) {
  issue(id: $id) {
    id
    labels {
      nodes {
        id
        name
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
        label_nodes: list[dict[str, Any]] = (issue.get("labels") or {}).get("nodes", [])
        target = next(
            (n for n in label_nodes if (n.get("name") or "").lower() == name.lower()),
            None,
        )
        if target is None:
            return  # already absent — idempotent release

        mutation = """
mutation RemoveLabel($id: String!, $labelId: String!) {
  issueRemoveLabel(id: $id, labelId: $labelId) {
    success
  }
}
"""
        result = await self._request(
            mutation, {"id": issue_id, "labelId": target["id"]}
        )
        success = (result.get("data") or {}).get("issueRemoveLabel", {}).get("success")
        if not success:
            raise LinearRequestError(
                f"Linear issueRemoveLabel did not report success for {identifier!r}; "
                f"response: {result!r}"
            )

    async def unassign_viewer(self, identifier: str) -> None:
        """Clear the assignee on ``identifier`` (``issueUpdate(assigneeId: null)``).

        The release-side mirror of :meth:`assign_to_viewer` (#193): unconditional
        — ``defer`` only ever assigns the operator, so whoever holds the ticket
        *is* the assignee this clears. This is the load-bearing release step:
        assignment is the authoritative "a human holds this" signal
        ``work-discovery`` reads, so clearing it is what actually returns the
        ticket to the queue.

        Raises:
            LinearNotFound: the issue does not exist.
            LinearRequestError: the API returned an error, or ``issueUpdate``
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
mutation UnassignIssue($id: String!) {
  issueUpdate(id: $id, input: {assigneeId: null}) {
    success
  }
}
"""
        result = await self._request(mutation, {"id": issue_id})
        success = (result.get("data") or {}).get("issueUpdate", {}).get("success")
        if not success:
            raise LinearRequestError(
                f"Linear issueUpdate did not report success unassigning {identifier!r}; "
                f"response: {result!r}"
            )

    async def update_issue_body(self, identifier: str, body: str) -> None:
        """Overwrite the issue's description with ``body`` (``issueUpdate``).

        The release step that writes a decision's resolution into the ticket's
        change spec (#193) — into the body an agent reads cold, not only a
        comment thread. The caller composes the full new body (existing spec +
        appended resolution section); this primitive just sets it.

        Raises:
            LinearNotFound: the issue does not exist.
            LinearRequestError: the API returned an error, or ``issueUpdate``
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
mutation UpdateDescription($id: String!, $description: String!) {
  issueUpdate(id: $id, input: {description: $description}) {
    success
  }
}
"""
        result = await self._request(
            mutation, {"id": issue_id, "description": body}
        )
        success = (result.get("data") or {}).get("issueUpdate", {}).get("success")
        if not success:
            raise LinearRequestError(
                f"Linear issueUpdate did not report success updating the body of "
                f"{identifier!r}; response: {result!r}"
            )

    async def create_issue(
        self,
        *,
        title: str,
        description: str,
        project: str | None,
    ) -> dict[str, str]:
        """Create a Todo issue on the configured team; return ``{identifier, url}``.

        The primitive behind ``harness promote escalate`` (CAL-1118): file a fresh
        escalation ticket carrying the promotion evidence. Resolves the team id
        from its key, the Todo (``unstarted``) workflow state, and — when
        ``project`` is given — the project id by name, all at runtime (never a
        hard-coded UUID, the same discipline as :meth:`apply_label`), then fires
        ``issueCreate`` into that team/project/state.

        The team is **client config** (``repo.linear``, threaded in by
        :func:`harness.tracker.tracker_client`), not a seam parameter: a team is a
        Linear concept GitHub can never honour, so a caller that had to supply one
        would be a caller that knows which backend it holds (#328). A client built
        without one therefore raises here rather than letting a neutral verb
        pre-check a Linear-only fact.

        Raises:
            LinearConfigError: the client carries no team (``repo.linear`` unset) —
                raised before any request, so nothing is mutated.
            LinearNotFound: no team with the configured key exists.
            LinearRequestError: the API errored, ``project`` names no project
                on the team, the team has no ``unstarted`` (Todo) state, or
                ``issueCreate`` did not return an issue.
        """
        if self._team is None:
            raise LinearConfigError(
                "no Linear team configured — set repo.linear in CONTEXT.md to file "
                "an issue"
            )
        team_key = self._team
        project_name = project
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
        mutation and confirms it landed by reading the post-write state back
        off that same mutation's response (#233) — no extra round trip, and so
        no write-then-read replica-lag window.

        Raises:
            LinearNotFound: the issue does not exist.
            LinearRequestError: the API returned an error, or no ``state_type``
                workflow state is configured on the issue's team.
            TrackerTransitionUnconfirmed: the mutation reported ``success: true``
                but the returned post-write state is not the state that was
                requested (or the response omits it) — a self-reported
                ``success`` is not proof the state actually changed.
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
    issue {
      id
      state {
        id
        name
      }
    }
  }
}
"""
        result = await self._request(mutation, {"id": issue_id, "stateId": state_id})
        payload = (result.get("data") or {}).get("issueUpdate") or {}
        if not payload.get("success"):
            raise LinearRequestError(
                f"Linear issueUpdate mutation did not report success for {identifier!r}; "
                f"response: {result!r}"
            )
        # Confirm the write actually took: compare the returned state id against
        # the id this call selected, not against the literal name
        # ``preferred_name`` — a team whose completed state is named "Shipped"
        # must still confirm. A missing ``issue``/``state`` is refused, not
        # trusted (the same fail-safe reading close's verify-gate backstop
        # already applies to absent evidence, CAL-1082).
        post_state = ((payload.get("issue") or {}).get("state") or {}).get("id")
        if post_state != state_id:
            raise TrackerTransitionUnconfirmed(
                f"Linear issueUpdate for {identifier!r} reported success, but the "
                f"post-write state is {post_state!r}, not the requested "
                f"{target.get('name')!r} ({state_id!r}); response: {result!r}"
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
