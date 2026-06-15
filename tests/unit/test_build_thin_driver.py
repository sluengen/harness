"""CAL-715 — thin ``/build`` to a delegating driver (no embedded Linear GraphQL).

Source: ``assessments/2026-06-15-system-and-code.md`` SYSTEM-2 (Medium) — the
sibling of the ``linear`` skill consolidation (CAL-714).

``commands/build.md`` re-encoded the start→review→ship loop the stepped trio
(``/start`` / ``/review`` / ``/ship``) already encodes, and embedded raw
``api.linear.app`` GraphQL/``jq`` blocks duplicating the ``linear`` skill. Two
parallel encodings of one loop — one re-hardcoding Linear's API — guaranteed to
drift. CAL-715 makes ``/build`` a *thin* driver: Linear ops delegate to the
``linear`` skill, worktree to ``worktree-isolation``, implementation to
``test-driven-development``, the review *criteria* to ``review-discipline``. Only
the autonomous-loop control (fix loop, convergence check, implement sub-agent
spawn, the machine ``SUBMIT:`` envelope + engine, abandon path) stays inline.

These guards pin the thin contract:

* **AC-1** — ``build.md`` embeds no raw Linear GraphQL. The absolute invariant is
  owned by ``test_linear_skill.py`` (``test_no_command_embeds_linear_graphql`` +
  ``test_embed_allowlist_shrinks``, with ``build.md`` removed from the
  ``EMBED_ALLOWLIST``); this file pins the positive half — ``build.md`` names the
  ``linear`` skill as the home for those operations.
* **AC-2** — the loop substance references the phase skills rather than
  re-encoding them: ``linear``, ``worktree-isolation``, ``test-driven-development``,
  ``review-discipline``.
* **AC-4** — ``/build`` appears in the process-doc command table.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
BUILD = REPO_ROOT / "commands" / "build.md"
PROCESS_DOC = REPO_ROOT / "process" / "harness.md"


# --- AC-1: no embedded Linear GraphQL; the linear skill is the home -----------


def test_build_embeds_no_linear_graphql() -> None:
    """``build.md`` embeds no raw Linear GraphQL endpoint (AC-1).

    The absolute no-embed invariant (and the shrinking allowlist) lives in
    ``test_linear_skill.py``; this is the local restatement for CAL-715.
    """
    assert "api.linear.app" not in BUILD.read_text(), (
        "commands/build.md still embeds a raw Linear GraphQL endpoint "
        "(api.linear.app) — delegate Linear operations to the `linear` skill "
        "(CAL-715 AC-1)."
    )


def test_build_references_linear_skill() -> None:
    """``build.md`` names the ``linear`` skill as the home for Linear ops (AC-1/AC-2)."""
    assert "`linear`" in BUILD.read_text(), (
        "commands/build.md must reference the `linear` skill for Linear operations "
        "(mark in progress, fetch ticket, set in review, create defer ticket, "
        "comment, close) instead of re-encoding the API (CAL-715 AC-1/AC-2)."
    )


# --- AC-2: the loop substance references the phase skills ----------------------

#: The phase skills the thin driver delegates to, each referenced by name.
PHASE_SKILLS = (
    "worktree-isolation",
    "test-driven-development",
    "review-discipline",
)


def test_build_references_phase_skills() -> None:
    """The loop substance references the phase skills rather than re-encoding them (AC-2)."""
    text = BUILD.read_text()
    missing = [s for s in PHASE_SKILLS if s not in text]
    assert not missing, (
        f"commands/build.md must reference the phase skills {missing} rather than "
        "re-encoding the worktree / test-first / review method inline (CAL-715 AC-2)."
    )


# --- AC-4: /build is in the process command table -----------------------------


def test_build_in_process_command_table() -> None:
    """``/build`` has a row in the process-doc command table (AC-4).

    The table previously listed only the stepped trio + /propose / /assess /
    /update-guidance; the autonomous agent-led driver was absent (SYSTEM-2).
    """
    rows = [
        ln
        for ln in PROCESS_DOC.read_text().splitlines()
        if re.match(r"\|\s*`/build", ln)
    ]
    assert rows, (
        "process/harness.md command table has no `/build` row — the autonomous "
        "agent-led driver must appear in the command table (CAL-715 AC-4)."
    )
