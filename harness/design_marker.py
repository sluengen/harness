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
neither reader can ever mistake a design for a resumable ref — pinned in
``test_design_marker.py``, the same guard the two resume markers hold each other
to.

There is deliberately **no parser here.** Nothing reads the design back out of
the comment: the enforcement item 3 (#212) performs keys on the ledger ``design``
event, not on the ticket. A parser with no reader would be speculative surface;
the marker and the formatter are what the contract actually needs.

Like ``reclaim_marker``, this module is dependency-free and lives at the package
root so any layer can import it without a cycle through ``harness.cli``.
"""

from __future__ import annotations

__all__ = ["DESIGN_MARKER", "format_design_comment"]

#: The opening phrase every design comment carries — the key a reader identifies
#: a design comment by, and the phrase whose distinctness from the reclaim and
#: handoff markers keeps the three protocols from cross-matching.
DESIGN_MARKER = "Design by `harness design`"


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
        f"spec's Design section; the build session implements against it.\n\n"
        f"---\n\n"
        f"{design_markdown}"
    )
