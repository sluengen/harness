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
* **AC-3 — the exact commands and structured states** the orchestrator branches
  on are named — every ``promote`` subcommand and every ``PromotionStatus``.
* **AC-4 — the forbidden outer-agent actions** are stated: no direct
  target-branch push, no PR creation outside the harness, no Linear promotion
  mutation outside the harness.
* **AC-5 — the bounded repair policy and escalation** behaviour are documented.
* **AC-6 — retired (#435).** ADR 0015 deletes `RUNBOOK.md` with the operator
  loops it documented, so "the runbook is a pointer, not a second copy" no
  longer has a subject. The one-place-only property it protected now holds by
  construction: `commands/promote.md` is the only surviving home.
* **The contract stays agent-agnostic** (Design): Hermes is named as the likely
  local cron driver, but the surface is deterministic and model-free — local
  inference powers only the outer agent.
"""

from __future__ import annotations

import re
from pathlib import Path

from harness.cli.promote import promote_app
from harness.state.promotions import PROMOTION_STATUSES
from tests._cliutil import registered_command_surface

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


def test_ac3_names_every_promote_subcommand() -> None:
    """AC-3: every live ``promote`` subcommand is named (derived from the Typer app)."""
    doc = _command_doc()
    names = sorted(registered_command_surface(promote_app))
    assert names, "the promote app registered no subcommands — introspection is broken"
    missing = [name for name in names if f"promote {name}" not in doc]
    assert not missing, (
        f"AC-3: commands/promote.md does not name these promote subcommands: "
        f"{missing} (found in the live surface: {names})"
    )


def test_ac3_names_every_lifecycle_state() -> None:
    """AC-3: every ``PromotionStatus`` the orchestrator can branch on is documented.

    Derived from :data:`PROMOTION_STATUSES`, so a new or renamed state fails this
    gate until the command doc names it. Each state is matched as a backtick-quoted
    token (``\\`pr_opened\\```) so ``opened`` is not spuriously satisfied by
    ``pr_opened``.
    """
    doc = _command_doc()
    missing = sorted(s for s in PROMOTION_STATUSES if f"`{s}`" not in doc)
    assert not missing, (
        f"AC-3: commands/promote.md does not document these lifecycle states "
        f"(as `state` tokens): {missing}"
    )


def _normalized_prose() -> str:
    """The command doc, lowercased with runs of whitespace collapsed to one
    space — so a phrase check is insensitive to markdown's non-semantic soft
    line-wraps (``must\\nnot`` reads as ``must not``)."""
    return re.sub(r"\s+", " ", _command_doc().lower())


def _fallback_section() -> str:
    """The ``commands/promote.md`` section documenting the no-harness,
    agent-orchestrated fallback (#190) — located by the first ``## `` heading
    whose text mentions "fallback" (case-insensitive), sliced up to the next
    ``## `` heading or end of file.

    Scoping to this section (rather than the whole doc) matters: the
    harness-backed path above already uses phrases like "opens no PR" and
    "pushes only the promotion branch" for its own staging/release hops, so an
    unscoped search would pass even if the fallback said nothing at all.
    """
    text = _command_doc()
    headings = list(re.finditer(r"^## .*$", text, re.MULTILINE))
    for i, h in enumerate(headings):
        if "fallback" in h.group(0).lower():
            start = h.start()
            end = headings[i + 1].start() if i + 1 < len(headings) else len(text)
            return text[start:end]
    raise AssertionError(
        "commands/promote.md has no '## …fallback…' section for the no-harness path"
    )


def _normalized_fallback() -> str:
    return re.sub(r"\s+", " ", _fallback_section().lower())


def test_ac4_states_forbidden_outer_agent_actions() -> None:
    """AC-4: the three forbidden outer-agent actions are stated as prohibitions."""
    doc = _normalized_prose()
    assert "must not" in doc, (
        "AC-4: commands/promote.md states no prohibition ('must not') on the outer agent"
    )
    # The three forbidden actions: direct target-branch push, PR creation outside
    # the harness, and tracker promotion mutation outside the harness.
    assert "push" in doc, "AC-4: direct target-branch push is not forbidden"
    assert "tracker" in doc, "AC-4: out-of-band tracker mutation is not forbidden"
    assert re.search(r"\bpr\b|pull request", doc), (
        "AC-4: out-of-band PR creation is not forbidden"
    )
    assert "outside" in doc, (
        "AC-4: the prohibition does not frame PR/tracker actions as 'outside the harness'"
    )


def test_ac5_documents_bounded_repair_and_escalation() -> None:
    """AC-5: one bounded repair attempt and the escalation path are documented."""
    doc = _normalized_prose()
    assert "bounded" in doc, "AC-5: the bounded repair policy is not documented"
    assert re.search(r"\bonce\b|one .*attempt|single .*attempt", doc), (
        "AC-5: the doc does not state repair is a single bounded attempt"
    )
    assert "escalat" in doc, "AC-5: escalation behaviour is not documented"


def test_design_contract_is_agent_agnostic() -> None:
    """Design — Hermes is the likely driver, but the surface is agent-agnostic.

    The harness surface is deterministic and model-free; local inference powers
    only the outer agent. The doc must name Hermes as the likely local cron driver
    yet keep the contract open to any orchestrator.
    """
    lower = _normalized_prose()
    assert "hermes" in lower, (
        "Design: commands/promote.md does not name Hermes as the likely local cron driver"
    )
    assert "agent-agnostic" in lower, (
        "Design: commands/promote.md does not state the surface is agent-agnostic"
    )
    assert "deterministic" in lower, (
        "Design: commands/promote.md does not state the harness surface is "
        "deterministic/model-free"
    )


# --- #190: the agent-orchestrated fallback for repos without the harness app ---
#
# ADR 0003's 2026-07-23 amendment names this path explicitly reduced: no
# bounded repair, no five-state machine, no ledger. These tests are the
# fallback's acceptance criteria, and — like the AC-1..6 tests above — the
# drift guard against it drifting into a second, unaudited implementation of
# the promotion lifecycle.


def test_fallback_section_specifies_harness_detection() -> None:
    """AC: the fallback section exists, and detection of harness presence/absence
    is specified rather than assumed — the reader must be told exactly how to
    tell the two paths apart, not left to guess."""
    doc = _normalized_fallback()
    assert "$path" in doc or "on path" in doc, (
        "the fallback does not specify how to detect the harness app's "
        "presence/absence (expected a $PATH check, mirroring /harness run's own)"
    )


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
