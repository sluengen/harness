"""The repo's verify gate, as the harness *records* it — CAL-1082.

The close gate enforced three things — a run exists, the worktree is clean, and a
``verdict='pass'`` is bound to HEAD — and **none of them was evidence that a test
ever ran**. The only instruction to run the gate lived in prose addressed to a
model (``commands/harness.md``: "Run the repo's verify gate locally as you go"),
enforced by nothing. So a ``pass`` from a reviewer that merely *read* the diff was
byte-identical in the ledger to one backed by a green test suite — against this
repo's own iron law ("no completion claim without fresh evidence") and against
``CONTEXT.md``'s claim that the harness owns "the durable record **and the
gate**".

This module is the missing half, and it is deliberately **not** an executor.

Evidence, not execution
-----------------------
The harness stays a **scaffold**: it owns the durable record and the gate, not
the toolchain. An earlier build of this ticket had ``review`` *run* the gate
in-container and proved the catch-22 that settles the design — the image cannot
carry every target repo's toolchain. ``harness:dev`` is built ``--no-dev``, so
not even this repo's own ``ruff`` is present; a Node target would need Node; an
Xcode target can never run in a Linux container at all. An executing verb would
therefore have to either bloat the image toward every ecosystem or hand a
diff-only ``pass`` to the repos it could not run — and the harness would be
unable to close its own tickets.

So the gate runs **where the toolchain already lives**: the orchestrating
session, host-side, in the worktree. It hands the result to ``review``
(``--gate-exit``/``--gate-log``), and the verb *enforces and records* it —
refusing to invoke any engine without fresh green evidence.

The evidence is **self-reported**, which grants no new trust: any process that
can write the workspace can already forge a ledger event, so this sits exactly on
the ledger's existing filesystem trust boundary rather than moving it. The
authoritative control over what actually merges is server-side branch protection
(CAL-1029), not this record. What the record buys is that a ``pass`` now *states*
whether a gate ran, so a reader — and ``close`` — can tell the two apart.

It mirrors :mod:`harness.loop_budget`, the standing precedent for this shape:
config read out of ``CONTEXT.md`` in its own module, with a documented fallback
when the key is absent, called from a verb rather than inlined into it.
``review.py`` is on the architecture watchlist — it already carries verb
orchestration, the prompt, the SUBMIT parser, the per-engine builders, the
failure detectors, and the fallback — so the gate lands here, as a seam by
construction, and ``review.py`` grows only a call site.
"""

from __future__ import annotations

import re
from pathlib import Path

__all__ = [
    "GATE_NOT_CONFIGURED_REASON",
    "GATE_OUTPUT_TAIL_LIMIT",
    "load_gate_command",
    "read_gate_log_tail",
]

#: Recorded as the ``review`` event's ``gate_reason`` when the repo configures no
#: ``verify:`` command. The harness cannot gate what a repo does not define; the
#: ledger says so plainly rather than implying a gate ran. ``close`` reads this
#: value to tell an honest "no gate configured" from missing evidence.
GATE_NOT_CONFIGURED_REASON = "not_configured"

#: How much of a gate's output is recorded, and how much rides on a refusal. The
#: tail — not the head — because the diagnostic lines (the failing assertion, the
#: summary) come last. A deliberate, bounded exception to the verb's
#: context-economy rule: this is the *reason for the refusal*, not engine
#: reasoning, and without it the agent must re-read the whole log to learn what
#: broke.
GATE_OUTPUT_TAIL_LIMIT = 2048


# ---------------------------------------------------------------------------
# Config — read the gate command from CONTEXT.md (not hardcoded)
# ---------------------------------------------------------------------------

# ``verify:`` is a distinctly-named string key in CONTEXT.md, optionally quoted
# and optionally trailed by a comment. A direct per-key match is robust here and
# avoids pulling in a YAML parser for one string — the same trade
# ``loop_budget._read_int_key`` makes for its integers. Two alternatives: the
# quoted form (group 1) takes the value verbatim, so a ``#`` inside it survives;
# the bare form (group 2) stops at a trailing comment.
_VERIFY_KEY_PATTERN = (
    r'^\s*verify:\s*"([^"]+)"\s*(?:#.*)?$'
    r'|^\s*verify:\s*([^"#\s][^#]*?)\s*(?:#.*)?$'
)


def load_gate_command(repo_root: Path) -> str | None:
    """The repo's ``verify:`` command from ``repo_root/CONTEXT.md``, else ``None``.

    Read **for the record** — to name the gate on the review event, and to know
    whether this repo defines one at all. It is never executed here.

    ``None`` means *this repo defines no gate* — both when ``CONTEXT.md`` is
    absent entirely and when it configures no ``verify:`` key. The caller records
    that absence as :data:`GATE_NOT_CONFIGURED_REASON` rather than inventing a
    default command: guessing a gate would be worse than admitting there is none.
    """
    context = repo_root / "CONTEXT.md"
    try:
        text = context.read_text()
    except OSError:
        return None
    match = re.search(_VERIFY_KEY_PATTERN, text, re.MULTILINE)
    if match is None:
        return None
    command = match.group(1) or match.group(2)
    return command.strip() or None


# ---------------------------------------------------------------------------
# Evidence intake — read what the orchestrator's gate run produced
# ---------------------------------------------------------------------------


def read_gate_log_tail(log_path: Path | None) -> str:
    """The bounded tail of the gate log at ``log_path``; ``""`` when unavailable.

    ``--gate-log`` is **optional** and best-effort: an absent, unreadable, or
    undecodable log degrades to no tail rather than failing the verb. The
    load-bearing half of the evidence is the exit code, which arrives as its own
    flag; the tail is a diagnostic convenience, and losing it must not turn a
    green gate into a refusal.
    """
    if log_path is None:
        return ""
    try:
        text = log_path.read_text(errors="replace")
    except OSError:
        return ""
    return text[-GATE_OUTPUT_TAIL_LIMIT:]
