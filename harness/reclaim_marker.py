"""The reclaim-comment contract — single-sourced for its two parties (CAL-739).

``harness reclaim`` (CAL-735) reverts a stranded ticket to Todo and posts a
comment naming the preserved (checkpoint-pushed) branch; ``harness start
--resume`` (CAL-739) reads that comment back to continue the dead run from its
branch. The comment format therefore has a **writer** and a **reader**, and a
format the reader guesses at would silently drift from the writer — so it lives
in exactly one place here, beside :func:`parse_preserved_branch` that recovers
the branch from it. ``test_reclaim_marker.py`` pins the round-trip.

This module is intentionally dependency-free (stdlib ``re`` only) and lives at
the package root rather than under ``harness.cli`` so both :mod:`harness.linear`
(the reader's GraphQL client) and :mod:`harness.cli.reclaim` (the writer) import
it without a circular dependency through ``harness.cli.__init__``.
"""

from __future__ import annotations

import re

__all__ = [
    "NO_BRANCH_SENTINEL",
    "RECLAIM_LABEL",
    "RECLAIM_MARKER",
    "format_reclaim_comment",
    "parse_preserved_branch",
]

#: The label reclaim applies to a reverted ticket so a re-picked ticket is
#: visibly marked, and the reader's structured gate that a ticket is a
#: reclamation re-pick (proposal ``stale-run-reclamation`` D1).
RECLAIM_LABEL = "reclaimed"

#: The opening phrase every reclaim comment carries — the reader keys on it to
#: identify a reclaim comment among a ticket's other comments.
RECLAIM_MARKER = "Reclaimed by `harness reclaim`"

#: The preserved-branch value used when a reclaim found no durable WIP — parses
#: back to ``None`` (no resumable branch → a clean restart on the next pick).
NO_BRANCH_SENTINEL = "(none — clean restart on next pick)"

#: The preserved-branch clause: a backtick-quoted ref the writer emits and the
#: reader extracts. One regex, one format string — they cannot drift.
_PRESERVED_RE = re.compile(r"Preserved branch: `([^`]+)`")


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


def parse_preserved_branch(comment_body: str) -> str | None:
    """The preserved branch ref named in a reclaim comment, or ``None``.

    Returns ``None`` for every non-branch case — a comment that is not a reclaim
    comment, one that names the no-WIP sentinel, or one whose preserved-branch
    clause is absent/unparseable. The reader thus never resumes from a wrong ref:
    any ambiguity degrades to a clean restart, which ``close``'s HEAD-bound gate
    keeps safe.
    """
    if RECLAIM_MARKER not in comment_body:
        return None
    match = _PRESERVED_RE.search(comment_body)
    if match is None:
        return None
    ref = match.group(1)
    return None if ref == NO_BRANCH_SENTINEL else ref
