"""The design-comment contract — single-sourced for its writer and readers.

ADR 0007 makes the ``design`` stage's artifact the change spec's Design section,
posted to the ticket as a **marked comment** — deliberately not a new artifact
class, and not a file under ``specs/``. The marker is what lets a later reader
(a human scanning the ticket, or tooling) pick the design out of a comment stream
that already carries reclamation and handoff comments.

This module owns that contract, the way :mod:`harness.reclaim_marker` owns the
reclaim/handoff ones: the phrase and the body format live in exactly one place,
so the ``design`` verb cannot inline a second copy that drifts.

**Non-collision with the resume protocols.** ``start --resume`` walks a ticket's
comments looking for a preserved WIP branch, gated on
:data:`~harness.reclaim_marker.RECLAIM_MARKER` /
:data:`~harness.reclaim_marker.HANDOFF_MARKER`. :data:`DESIGN_MARKER` is a
distinct phrase and a design comment carries no ``Preserved branch:`` clause, so
neither reader can ever mistake a design for a resumable ref — and, since #257,
a reclaim or handoff comment does not parse as a *design* either. All three
directions are pinned in ``test_design_marker.py``, the same guard the two
resume markers hold each other to.

**The reader arrived (#257).** This module shipped with no parser on the stated
grounds that "a parser with no reader would be speculative surface" — the
enforcement #212 performs keys on the ledger ``design`` event, not on the ticket.
That condition no longer holds. ADR 0008 has a resumed run *adopt* its
predecessor's design rather than re-pay for an Opus call, and the design text
lives nowhere but this comment: the ledger event carries only a ``design_hash``
and a ``grounded_sha``, deliberately (ADR 0007). So #258 is the reader that
:func:`parse_design_comment` exists for, and the deferral is resolved by the
reader turning up rather than by overriding the reasoning that deferred it.

The parser reports what the comment *claims*; it never authenticates. Its caller
recomputes the hash over the recovered text and refuses a mismatch — ADR 0008's
rule that the verb writing an inherited event verifies the claim at write time.
Keeping report and judgment apart is what lets a caller tell "no hash stated"
from "hash does not match".

Like ``reclaim_marker``, this module is dependency-free (stdlib ``re`` only) and
lives at the package root so any layer can import it without a cycle through
``harness.cli``.
"""

from __future__ import annotations

import re
from typing import NamedTuple

__all__ = [
    "DESIGN_MARKER",
    "ParsedDesign",
    "format_design_comment",
    "parse_design_comment",
]

#: The opening phrase every design comment carries — the key a reader identifies
#: a design comment by, and the phrase whose distinctness from the reclaim and
#: handoff markers keeps the three protocols from cross-matching.
DESIGN_MARKER = "Design by `harness design`"

#: The fence between the comment's provenance header and the design itself. One
#: constant, referenced by both the writer's body and the reader's split, on the
#: :data:`~harness.reclaim_marker._PRESERVED_RE` precedent: the single token the
#: two must agree on cannot drift, because there is only one of it.
_DESIGN_SEPARATOR = "\n\n---\n\n"

#: The provenance clauses, one compiled regex each. Applied to the **header
#: slice only** — never the whole comment. A design body legitimately contains
#: backticked ``design_hash`` prose (this module's own design did), and a comment
#: that could supply its own provenance from its body would be self-signing.
_RUN_ID_RE = re.compile(r"for run `([^`]+)`")
_GROUNDED_SHA_RE = re.compile(r"grounded at `([^`]+)`")
_DESIGN_HASH_RE = re.compile(r"design_hash `([^`]+)`")


class ParsedDesign(NamedTuple):
    """A design recovered from a ticket comment — the text, plus what it claims.

    ``design_markdown`` is the artifact, recovered **verbatim**: byte-identical
    to what :func:`format_design_comment` embedded, because the caller's hash
    comparison is over exactly those bytes. It is never empty — a comment with
    nothing after the separator parses to ``None``, so "recovered nothing" and
    "recovered an empty design" are not the same value at a call site.

    The other three fields are **claims, not facts** — what the comment states,
    reported as written and never shape-checked. Authentication is the caller's
    (ADR 0008); each field is independently optional, so header drift costs the
    provenance rather than the design.
    """

    design_markdown: str
    design_hash: str | None
    grounded_sha: str | None
    run_id: str | None


def _clause(pattern: re.Pattern[str], header: str) -> str | None:
    """The first capture of ``pattern`` in ``header``, or ``None`` if absent."""
    match = pattern.search(header)
    return None if match is None else match.group(1)


def format_design_comment(
    run_id: str,
    design_markdown: str,
    *,
    design_hash: str,
    grounded_sha: str,
    when: str,
) -> str:
    """The design comment body: the marker, the provenance, then the design.

    The design is embedded **verbatim** — it is the artifact, so it is never
    summarised or truncated here. Above it sits the provenance that ties the
    comment to its ledger ``design`` event: the run it belongs to, the
    ``design_hash`` of this exact text, and the ``grounded_sha`` the engine
    studied. A reader can therefore tell whether the design on the ticket is the
    one the ledger recorded, and which tree it was grounded in.

    ``when`` is the (already-formatted) timestamp, passed in rather than read
    here so the body is deterministic for the tests.
    """
    return (
        f"{DESIGN_MARKER} at {when} for run `{run_id}`, grounded at "
        f"`{grounded_sha}` (design_hash `{design_hash}`). This is the change "
        f"spec's Design section; the build session implements against it."
        f"{_DESIGN_SEPARATOR}"
        f"{design_markdown}"
    )


def parse_design_comment(comment_body: str) -> ParsedDesign | None:
    """The design recovered from a design comment, or ``None`` (#257).

    The counterpart to :func:`format_design_comment`, and pure: no ledger, no
    tracker, no I/O. It **never raises** — every ambiguity degrades to ``None``,
    on the :func:`~harness.reclaim_marker.parse_preserved_branch` posture, so a
    caller that cannot recover a design falls back to running the engine.

    The gate is the marker as a **prefix**, where the two reclaim readers use a
    substring. Those comments are single formatter-written lines with no embedded
    free text; a design comment embeds arbitrary engine-written markdown, and a
    design *about this contract* quotes the marker in its prose. A substring gate
    would let a comment that merely quotes a design pass as one. The prefix is
    the invariant the formatter already holds, and ``post_design_comment`` posts
    its body verbatim, so nothing prepends to it.

    Recovery is :meth:`str.partition` on the **first** :data:`_DESIGN_SEPARATOR`,
    taking the entire remainder — so a design carrying its own ``---`` fences
    keeps every one of them. The text is returned unstripped; ``.strip()`` is
    used only as a blank-remainder predicate, because byte-identity is what the
    caller's hash comparison needs.
    """
    if not comment_body.startswith(DESIGN_MARKER):
        return None
    header, separator, design_markdown = comment_body.partition(_DESIGN_SEPARATOR)
    if not separator or not design_markdown.strip():
        return None
    return ParsedDesign(
        design_markdown=design_markdown,
        design_hash=_clause(_DESIGN_HASH_RE, header),
        grounded_sha=_clause(_GROUNDED_SHA_RE, header),
        run_id=_clause(_RUN_ID_RE, header),
    )
