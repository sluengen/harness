"""CAL-1119 / #189 — the outer-agent promotion routine is documented, and tied
to source.

The promotion lifecycle (ADR 0003) is an audited harness surface that an
external orchestrator — Hermes, OpenClaw, Claude, Codex, or a human — drives on a
schedule. The surface (``harness promote start / continue / status / pr /
escalate``) and its structured states shipped in CAL-1113–1118; CAL-1119
documented the *routine* around them directly in ``RUNBOOK.md`` (how any outer
agent moves work ``dev → staging → main``, what states it branches on, what it
must never do, how bounded repair and escalation behave) because no versioned
command yet existed to carry it.

**#189 moved that content into `commands/promote.md`** — the versioned,
universal command every repo on this guidance installs, with role-based
argument resolution (`/promote <src> to <dst>` against `CONTEXT.md`
`branches:`) so the same invocation shape works whether a repo's roles are
named `dev`/`staging`/`main` or `develop`/`staging`/`production`. The
orchestration logic lives in exactly one place.

These tests are the executable form of the acceptance criteria and — more
importantly — the **drift guard** that keeps the prose tied to the real
surface: the documented subcommands are derived from the live ``promote``
Typer app and the documented states from
:data:`~harness.state.promotions.PROMOTION_STATUSES`, so a renamed subcommand or
a new lifecycle state fails this gate until the command doc is updated too.

* **AC-1 — the command exists, is version-stamped, and is listed** in the
  `CLAUDE.md` command table.
* **AC-2 — role resolution is specified**: a repo whose `branches:` are
  `develop` / `staging` / `production` drives `/promote develop to staging`
  unchanged.
* **AC-3/AC-5 — retired (#435).** ADR 0015 retires the ``harness promote`` verb
  loop: the five subcommands, the ten lifecycle states, and the one-bounded-repair
  policy were all properties of that loop. Nothing remains to derive them from.
* **AC-4 — the forbidden actions** survive, reduced. Three of the four
  prohibitions were about staying inside the harness lifecycle and went with it;
  what stands on its own is that the release branch is never direct-pushed, the
  release PR is never auto-merged, and neither a conflict nor a red gate is
  repaired.
* **AC-6 — retired (#435).** ADR 0015 deletes `RUNBOOK.md` with the operator
  loops it documented, so "the runbook is a pointer, not a second copy" no
  longer has a subject. The one-place-only property it protected now holds by
  construction: `commands/promote.md` is the only surviving home.

**#435 also collapsed the two paths into one.** ``commands/promote.md`` used to
carry a verb-backed loop *and* a reduced no-harness fallback, and the fallback
checks below were scoped to that section precisely because the verb-backed path
above them used the same vocabulary. The verb-backed path is gone, so the
reduced path is the whole command and the checks read the whole document. Their
subject did not change — only its scope did.
"""

from __future__ import annotations

import re
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_COMMAND = _REPO_ROOT / "commands" / "promote.md"
_CLAUDE_MD = _REPO_ROOT / "CLAUDE.md"


def _command_doc() -> str:
    return _COMMAND.read_text(encoding="utf-8")


def test_command_exists_and_versioned() -> None:
    """AC-1: ``commands/promote.md`` exists and carries a guidance version stamp."""
    assert _COMMAND.exists(), "commands/promote.md does not exist"
    first_line = _command_doc().splitlines()[0]
    assert re.match(r"<!--\s*guidance:promote@\d+\.\d+\.\d+\s*-->", first_line), (
        f"commands/promote.md's first line is not a guidance version stamp: {first_line!r}"
    )


def test_command_listed_in_claude_md_table() -> None:
    """AC-1: `/promote` is listed in the `CLAUDE.md` command table."""
    claude_md = _CLAUDE_MD.read_text(encoding="utf-8")
    assert "/promote" in claude_md, (
        "CLAUDE.md does not list /promote in its command table"
    )


def test_ac2_role_resolution_example_documented() -> None:
    """AC-2: a repo whose `branches:` are `develop`/`staging`/`production` drives
    `/promote develop to staging` unchanged — same invocation shape as this
    repo's own `dev`/`staging`/`main` roles."""
    doc = _command_doc()
    assert re.search(r"develop\s*(?:->|→|\bto\b)\s*staging", doc, re.IGNORECASE), (
        "AC-2: the generic 'develop to staging' role-resolution example is not shown"
    )
    assert "production" in doc.lower(), (
        "AC-2: the generic repo's 'production' release-role branch is not named"
    )


def test_ac2_shows_this_repos_own_flows() -> None:
    """The command also demonstrates the concrete `dev`/`staging`/`main` hop this
    repo actually drives — the nightly-stabilization and release examples."""
    doc = _command_doc()
    dev_to_staging = re.search(r"dev\s*(?:->|→|\bto\b)\s*staging", doc)
    staging_to_main = re.search(r"staging\s*(?:->|→|\bto\b)\s*main", doc)
    assert dev_to_staging, "the 'dev to staging' example is not shown"
    assert staging_to_main, "the 'staging to main' example is not shown"


def _normalized_prose() -> str:
    """The command doc, lowercased with runs of whitespace collapsed to one
    space — so a phrase check is insensitive to markdown's non-semantic soft
    line-wraps (``must\\nnot`` reads as ``must not``)."""
    return re.sub(r"\s+", " ", _command_doc().lower())


def _fallback_section() -> str:
    """The reduced path — which, since #435, is the whole command document.

    It was a ``## …fallback…`` slice while a verb-backed loop shared the file,
    because that loop used the same "opens no PR" / "pushes only the promotion
    branch" vocabulary and an unscoped search would have passed on *its* prose
    even if the fallback said nothing. With the verb-backed path retired there is
    no competing prose left to be confused by, so the scope widens to the file.
    """
    return _command_doc()


def _normalized_fallback() -> str:
    return re.sub(r"\s+", " ", _fallback_section().lower())


def test_ac4_states_the_forbidden_actions() -> None:
    """AC-4: the prohibitions that survive the verb loop are stated as such.

    Three of the original four were "do not do this outside the harness
    lifecycle", and went with the lifecycle. These three stand on their own: they
    are about what a promotion may push and what it may repair, which is true
    whether or not anything audits it — and they matter *more* on the reduced
    path, because nothing refuses them now except the prose.
    """
    doc = _normalized_prose()
    assert "never" in doc or "must not" in doc, (
        "AC-4: commands/promote.md states no prohibition on the driving agent"
    )
    assert re.search(r"never direct-pushed|never push(?:es)? the (?:target|release)", doc), (
        "AC-4: direct release-branch push is not forbidden"
    )
    assert re.search(r"(?:auto-?merge|merging it)", doc), (
        "AC-4: auto-merging the release PR is not forbidden"
    )
    assert re.search(r"repair", doc), (
        "AC-4: repairing a conflict or a red gate is not forbidden"
    )


# --- #190: the agent-orchestrated fallback for repos without the harness app ---
#
# ADR 0003's 2026-07-23 amendment names this path explicitly reduced: no
# bounded repair, no five-state machine, no ledger. These tests are the
# fallback's acceptance criteria, and — like the AC-1..6 tests above — the
# drift guard against it drifting into a second, unaudited implementation of
# the promotion lifecycle.


def test_fallback_stops_on_conflict_no_repair() -> None:
    """AC: the fallback stops and reports on a merge conflict — no repair
    attempt of any kind, bounded or otherwise (unlike the verb-backed path)."""
    doc = _normalized_fallback()
    assert re.search(r"conflict.{0,200}stop and report", doc, re.DOTALL) or re.search(
        r"stop and report.{0,200}conflict", doc, re.DOTALL
    ), "the fallback does not state it stops and reports on a merge conflict"
    assert "no repair" in doc or "no repair attempt" in doc, (
        "the fallback does not state it makes no repair attempt on conflict"
    )


def test_fallback_stops_on_red_gate_no_repair() -> None:
    """AC: the fallback stops and reports on a red gate, capturing the gate
    output — it never attempts a repair or a retry."""
    doc = _normalized_fallback()
    assert re.search(r"red.{0,120}stop and report", doc, re.DOTALL), (
        "the fallback does not state it stops and reports on a red gate"
    )


def test_fallback_reads_gate_from_context_verify_never_hardcoded() -> None:
    """AC: the fallback reads the gate command from CONTEXT.md `commands.verify`
    — it must never hardcode a gate command of its own."""
    section = _fallback_section()
    assert "commands.verify" in section, (
        "the fallback does not read the gate command from CONTEXT.md commands.verify"
    )
    assert "never hardcod" in section.lower() or "not hardcod" in section.lower(), (
        "the fallback does not state the gate command is never hardcoded"
    )


def test_fallback_preserves_hop_asymmetry() -> None:
    """AC: the hop asymmetry from the verb-backed path holds on the fallback
    too — an intermediate branch is advanced directly (no PR); the release
    branch only ever gets a pushed promotion branch + an opened PR."""
    doc = _normalized_fallback()
    assert "no pr" in doc, (
        "the fallback does not state the intermediate hop opens no PR"
    )
    assert re.search(r"push(?:es)? only the promotion branch", doc), (
        "the fallback does not state the release hop pushes only the promotion "
        "branch (never the target directly)"
    )


def test_fallback_states_what_is_lost_without_the_ledger() -> None:
    """AC: a stated 'what you lose without the ledger' paragraph — no promotion
    id, no audit trail, no resumable state."""
    doc = _normalized_fallback()
    assert "without the ledger" in doc or "no ledger" in doc, (
        "the fallback does not name what is lost by having no ledger"
    )
    assert "audit trail" in doc, (
        "the fallback does not state there is no audit trail without the ledger"
    )
    assert "resumable" in doc, (
        "the fallback does not state there is no resumable state without the ledger"
    )


def test_fallback_is_explicitly_reduced_by_decision() -> None:
    """AC: the section states plainly that it is reduced by decision (citing
    ADR 0003's 2026-07-23 amendment), so a later reader does not 'complete' it
    into a mirror of the verb-backed path."""
    doc = _normalized_fallback()
    assert "2026-07-23" in doc, (
        "the fallback does not cite ADR 0003's 2026-07-23 amendment date"
    )
    assert "reduced" in doc, (
        "the fallback does not state plainly that it is reduced by decision"
    )
    assert "mirror" in doc or "drift" in doc, (
        "the fallback does not warn against completing it into a mirror of the "
        "verb-backed path"
    )
