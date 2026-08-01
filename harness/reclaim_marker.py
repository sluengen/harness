"""The reclaim- and handoff-comment contracts — single-sourced for their parties.

Two sibling protocols recover a run's checkpoint-pushed WIP branch through a
Linear comment; both live here so their writer and reader can never drift, and
so the **distinction** between them is stated in one place (CAL-739 / CAL-923):

* **Death-keyed reclamation (CAL-739).** ``harness reclaim`` (CAL-735) reverts a
  stranded ticket to **Todo**, applies the ``reclaimed`` **label**, and posts a
  comment carrying :data:`RECLAIM_MARKER`; ``harness start --resume`` reads it
  back via :func:`parse_preserved_branch`. The orchestrator is **presumed dead**.
* **Proactive context-rollover handoff (CAL-923).** A session that is *alive but
  near its context limit* checkpoints, keeps the ticket **In Progress** (no
  label), and posts a comment carrying :data:`HANDOFF_MARKER`; a fresh session
  resumes the **same** ticket via ``harness start --resume``, which reads it back
  via :func:`parse_handoff_branch`.

The two **never collide**: they use *distinct* marker strings, so a reader keyed
on one never matches a comment written for the other (pinned in
``test_reclaim_marker.py``), and they occupy *distinct* Linear states (Todo +
``reclaimed`` vs In Progress). Only the ``Preserved branch:`` clause is shared —
both recover the ref through :data:`_PRESERVED_RE`.

This module is intentionally dependency-free (stdlib ``re`` only) and lives at
the package root rather than under ``harness.cli`` so both :mod:`harness.linear`
(the reader's GraphQL client) and :mod:`harness.cli.reclaim` (the writer) import
it without a circular dependency through ``harness.cli.__init__``.
"""

from __future__ import annotations

import re

__all__ = [
    "HANDOFF_MARKER",
    "NO_BRANCH_SENTINEL",
    "RECLAIM_LABEL",
    "RECLAIM_MARKER",
    "UNRECLAIM_MARKER",
    "format_handoff_comment",
    "format_reclaim_comment",
    "format_unreclaim_comment",
    "parse_handoff_branch",
    "parse_preserved_branch",
]

#: The label reclaim applies to a reverted ticket so a re-picked ticket is
#: visibly marked, and the reader's structured gate that a ticket is a
#: reclamation re-pick (proposal ``stale-run-reclamation`` D1).
RECLAIM_LABEL = "reclaimed"

#: The opening phrase every reclaim comment carries — the reader keys on it to
#: identify a reclaim comment among a ticket's other comments.
RECLAIM_MARKER = "Reclaimed by `harness reclaim`"

#: The opening phrase every proactive context-rollover **handoff** comment
#: carries (CAL-923). Distinct from :data:`RECLAIM_MARKER` so the two readers
#: never cross-match — the structural basis for non-collision.
HANDOFF_MARKER = "Context-rollover handoff by `harness checkpoint`"

#: The opening phrase every **reversal** comment carries (#254) — the correcting
#: comment ``harness reclaim --undo`` posts when a reclaim is confirmed to have
#: been a false positive. Deliberately worded so it does not *contain* either
#: sibling marker: its subject is a reclamation, so quoting
#: :data:`RECLAIM_MARKER` verbatim would make every undo comment cross-match the
#: resume reader (pinned by the pairwise-containment test).
UNRECLAIM_MARKER = "Reclaim reversed by `harness reclaim --undo`"

#: The preserved-branch value used when a reclaim/handoff found no durable WIP —
#: parses back to ``None`` (no resumable branch → a clean restart on resume).
NO_BRANCH_SENTINEL = "(none — clean restart on next pick)"

#: The preserved-branch clause: a backtick-quoted ref the writer emits and the
#: reader extracts. One regex, one format string — they cannot drift. Shared by
#: both the reclaim and handoff contracts.
_PRESERVED_RE = re.compile(r"Preserved branch: `([^`]+)`")


def _parse_preserved_ref(comment_body: str) -> str | None:
    """Extract the ``Preserved branch:`` ref, or ``None`` for the sentinel/absent.

    The shared clause parser both contracts call *after* their own marker gate —
    it does not itself check any marker, so it must never be called on a raw
    comment (that would ignore the reclaim-vs-handoff distinction). Returns
    ``None`` when the clause is missing or names the no-WIP sentinel.
    """
    match = _PRESERVED_RE.search(comment_body)
    if match is None:
        return None
    ref = match.group(1)
    return None if ref == NO_BRANCH_SENTINEL else ref


def format_reclaim_comment(run_id: str | None, branch: str | None, *, when: str) -> str:
    """The reclamation comment body naming when it happened and the preserved branch.

    ``branch`` is the *resumable* ref — the run's checkpoint-pushed branch — or
    ``None`` when no durable WIP exists, in which case the sentinel is named so
    the reader degrades to a clean restart. ``when`` is the (already-formatted)
    timestamp the reclaim happened, passed in rather than read here so the body
    is deterministic for the round-trip guard.
    """
    run_clause = f"run `{run_id}`" if run_id else "no local run row found"
    ref = branch if branch else NO_BRANCH_SENTINEL
    return (
        f"{RECLAIM_MARKER} at {when}. The orchestrating session is presumed dead "
        f"({run_clause}); the ticket is reverted to **Todo** and labelled "
        f"`{RECLAIM_LABEL}` so it can be re-picked. Preserved branch: `{ref}`."
    )


def format_handoff_comment(run_id: str | None, branch: str | None, *, when: str) -> str:
    """The proactive context-rollover **handoff** comment body (CAL-923).

    The alive-but-near-limit counterpart to :func:`format_reclaim_comment`. The
    body states — for the human reader and for the non-collision guard — that the
    session is *alive* and the ticket **stays In Progress** (it is deliberately
    NOT reverted to Todo and carries no ``reclaimed`` label), so a fresh session
    continues the **same** ticket via ``harness start --resume``. ``branch`` is
    the checkpoint-pushed WIP ref, or ``None`` → the sentinel (clean restart).
    """
    run_clause = f"run `{run_id}`" if run_id else "no local run row found"
    ref = branch if branch else NO_BRANCH_SENTINEL
    return (
        f"{HANDOFF_MARKER} at {when}. The orchestrating session is alive "
        f"({run_clause}) but near its context budget; the ticket stays "
        f"**In Progress** (no revert, no label) and a fresh session continues the "
        f"same ticket via `harness start --resume`. Preserved branch: `{ref}`."
    )


def format_unreclaim_comment(run_id: str | None, *, when: str) -> str:
    """The correcting comment ``reclaim --undo`` posts on a false-positive revert (#254).

    Deliberately carries **no** ``Preserved branch:`` clause. The undo comment sits
    on the same ticket as the reclaim comment it reverses, so a ref named here
    could be picked up by a later ``start --resume`` scan; the run is being
    re-opened in place, so there is no ref to hand over in the first place.

    ``when`` is passed in rather than read here, like its two siblings, so the body
    is deterministic for the round-trip guards. There is no free-text field: the
    body is published to an externally-visible tracker, and keeping it generated
    is what makes it testable.
    """
    run_clause = f"run `{run_id}`" if run_id else "no local run row found"
    return (
        f"{UNRECLAIM_MARKER} at {when}. The earlier reclamation was a false "
        f"positive — the orchestrating session was alive ({run_clause}). The "
        f"ticket is restored to **In Progress**, the `{RECLAIM_LABEL}` label is "
        "removed, and the run is re-opened in its existing worktree."
    )


def parse_preserved_branch(comment_body: str) -> str | None:
    """The preserved branch ref named in a **reclaim** comment, or ``None``.

    Returns ``None`` for every non-branch case — a comment that is not a reclaim
    comment (including a *handoff* comment, which carries a different marker), one
    that names the no-WIP sentinel, or one whose preserved-branch clause is
    absent/unparseable. The reader thus never resumes from a wrong ref: any
    ambiguity degrades to a clean restart, which ``close``'s HEAD-bound gate keeps
    safe.
    """
    if RECLAIM_MARKER not in comment_body:
        return None
    return _parse_preserved_ref(comment_body)


def parse_handoff_branch(comment_body: str) -> str | None:
    """The preserved branch ref named in a **handoff** comment, or ``None`` (CAL-923).

    The proactive counterpart to :func:`parse_preserved_branch`, gated on
    :data:`HANDOFF_MARKER`. A reclaim comment (different marker) parses to
    ``None`` here, and a handoff comment parses to ``None`` in
    :func:`parse_preserved_branch` — the non-collision the two protocols rely on.
    Every other non-branch case (sentinel, missing clause) also degrades to
    ``None`` → a clean restart.
    """
    if HANDOFF_MARKER not in comment_body:
        return None
    return _parse_preserved_ref(comment_body)
