"""The Build-queue membership answer — a leaf type shared by the tracker seam.

``defer`` and ``release`` both ask one question before any write: *is this ticket
on the repo's Build queue?* Until #248 that question was answered by
:meth:`Tracker.fetch_issue_project`, whose ``str | None`` return overloaded two
incompatible meanings — ``None`` meant "not on the configured board" for GitHub
(refuse) and "on no project" for Linear (legitimate when scope is unset). One
value cannot carry both, so the caller had to infer which backend it held. This
type separates the two facts, letting each backend answer for its own queue
while the verbs stay backend-agnostic.

It lives in its own module — imported by :mod:`harness.linear`,
:mod:`harness.github` and :mod:`harness.tracker` alike — for the same reason
:mod:`harness.tracker_errors` does: both clients need it, and the seam imports
both clients, so a shared leaf is the only placement that forms no cycle.
"""

from __future__ import annotations

from dataclasses import dataclass

__all__ = ["QueueMembership", "scope_phrase"]


def scope_phrase(project: str | None) -> str:
    """How a message names the Build queue in force.

    Nullable scope needs prose for both modes. This is the phrasing ``reclaim``
    already uses for the same distinction, single-sourced here so ``defer`` and
    ``release`` cannot drift from each other.
    """
    if project is not None:
        return f"the Build queue {project!r}"
    return "the whole tracker queue"


@dataclass(frozen=True)
class QueueMembership:
    """Whether an issue is on the repo's Build queue, and the container it sits in.

    ``on_queue`` is the gate: ``False`` means the verb performs no tracker write
    and no ledger write. ``project`` is the issue's own container name *as that
    backend knows it* — never the configured scope echoed back — and is
    advisory: it feeds the ledger event and the ``--json`` ``project`` field when
    no scope is configured.

    The two are independent. ``on_queue=True`` with ``project=None`` is a real
    combination (a Linear issue inside the repo's team but attached to no
    project) and is precisely what the old ``str | None`` return could not
    express.
    """

    on_queue: bool
    project: str | None
