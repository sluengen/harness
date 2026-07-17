"""CAL-1119 — the outer-agent promotion routine is documented, and tied to source.

The promotion lifecycle (ADR 0003) is an audited harness surface that an
external orchestrator — Hermes, OpenClaw, Claude, Codex, or a human — drives on a
schedule. The surface (``harness promote start / continue / status / pr /
escalate``) and its structured states shipped in CAL-1113–1118; this ticket
documents the *routine* around them: how any outer agent moves work
``dev → staging → main`` on a schedule, what states it branches on, what it must
never do, and how bounded repair and escalation behave.

The routine guidance lives in the operational runbook (``RUNBOOK.md``, the home
of the harness's own loops). These tests are the executable form of the
acceptance criteria and — more importantly — the **drift guard** that keeps the
prose tied to the real surface: the documented subcommands are derived from the
live ``promote`` Typer app and the documented states from
:data:`~harness.state.promotions.PROMOTION_STATUSES`, so a renamed subcommand or
a new lifecycle state fails this gate until the routine doc is updated too.

* **AC-1 — the promotion flow is shown** for both the nightly ``dev → staging``
  candidate and the deliberate ``staging → main`` release.
* **AC-2 — the exact commands and structured states** the orchestrator branches
  on are named — every ``promote`` subcommand and every ``PromotionStatus``.
* **AC-3 — the forbidden outer-agent actions** are stated: no direct
  target-branch push, no PR creation outside the harness, no Linear promotion
  mutation outside the harness.
* **AC-4 — the bounded repair policy and escalation** behaviour are documented.
* **The contract stays agent-agnostic** (Design): Hermes is named as the likely
  local cron driver, but the surface is deterministic and model-free — local
  inference powers only the outer agent.
"""

from __future__ import annotations

import re
from pathlib import Path

from harness.cli.promote import promote_app
from harness.state.promotions import PROMOTION_STATUSES

_REPO_ROOT = Path(__file__).resolve().parents[2]
_RUNBOOK = _REPO_ROOT / "RUNBOOK.md"


def _runbook() -> str:
    return _RUNBOOK.read_text(encoding="utf-8")


def _promotion_section() -> str:
    """The ``RUNBOOK.md`` section documenting the promotion routine.

    Located by the first ``## `` heading whose text mentions "promotion"
    (case-insensitive, so the exact wording can be tuned without breaking the
    guard), sliced up to the next ``## `` heading or end of file.
    """
    text = _runbook()
    headings = list(re.finditer(r"^## .*$", text, re.MULTILINE))
    for i, h in enumerate(headings):
        if "promotion" in h.group(0).lower():
            start = h.start()
            end = headings[i + 1].start() if i + 1 < len(headings) else len(text)
            return text[start:end]
    raise AssertionError(
        "RUNBOOK.md has no '## …promotion…' section documenting the promotion routine"
    )


def test_promotion_section_exists() -> None:
    """The routine has a home: a top-level promotion section in the runbook."""
    section = _promotion_section()
    assert len(section.splitlines()) > 10, (
        "the promotion section is a stub — it must document the full routine"
    )


def test_ac1_shows_both_promotion_flows() -> None:
    """AC-1 — nightly ``dev → staging`` and deliberate ``staging → main`` are shown."""
    section = _promotion_section()
    # Tolerate either arrow style (``->`` or ``→``) and surrounding whitespace.
    dev_to_staging = re.search(r"dev\s*(?:->|→)\s*staging", section)
    staging_to_main = re.search(r"staging\s*(?:->|→)\s*main", section)
    assert dev_to_staging, "AC-1: the nightly 'dev → staging' flow is not shown"
    assert staging_to_main, "AC-1: the deliberate 'staging → main' flow is not shown"
    assert "nightly" in section.lower(), (
        "AC-1: the section does not describe the nightly schedule for dev → staging"
    )


def test_ac2_names_every_promote_subcommand() -> None:
    """AC-2 — every live ``promote`` subcommand is named (derived from the Typer app)."""
    section = _promotion_section()
    names = sorted(c.name for c in promote_app.registered_commands if c.name)
    assert names, "the promote app registered no subcommands — introspection is broken"
    missing = [name for name in names if f"promote {name}" not in section]
    assert not missing, (
        f"AC-2: the promotion routine does not name these promote subcommands: "
        f"{missing} (found in the live surface: {names})"
    )


def test_ac2_names_every_lifecycle_state() -> None:
    """AC-2 — every ``PromotionStatus`` the orchestrator can branch on is documented.

    Derived from :data:`PROMOTION_STATUSES`, so a new or renamed state fails this
    gate until the routine doc names it. Each state is matched as a backtick-quoted
    token (``\\`pr_opened\\```) so ``opened`` is not spuriously satisfied by
    ``pr_opened``.
    """
    section = _promotion_section()
    missing = sorted(s for s in PROMOTION_STATUSES if f"`{s}`" not in section)
    assert not missing, (
        f"AC-2: the promotion routine does not document these lifecycle states "
        f"(as `state` tokens): {missing}"
    )


def _normalized_prose() -> str:
    """The promotion section, lowercased with runs of whitespace collapsed to one
    space — so a phrase check is insensitive to markdown's non-semantic soft
    line-wraps (``must\\nnot`` reads as ``must not``)."""
    return re.sub(r"\s+", " ", _promotion_section().lower())


def test_ac3_states_forbidden_outer_agent_actions() -> None:
    """AC-3 — the three forbidden outer-agent actions are stated as prohibitions."""
    section = _normalized_prose()
    assert "must not" in section, (
        "AC-3: the section states no prohibition ('must not') on the outer agent"
    )
    # The three forbidden actions: direct target-branch push, PR creation outside
    # the harness, and Linear promotion mutation outside the harness.
    assert "push" in section, "AC-3: direct target-branch push is not forbidden"
    assert "linear" in section, "AC-3: out-of-band Linear mutation is not forbidden"
    assert re.search(r"\bpr\b|pull request", section), (
        "AC-3: out-of-band PR creation is not forbidden"
    )
    assert "outside" in section, (
        "AC-3: the prohibition does not frame the PR/Linear actions as 'outside the harness'"
    )


def test_ac4_documents_bounded_repair_and_escalation() -> None:
    """AC-4 — one bounded repair attempt and the escalation path are documented."""
    section = _normalized_prose()
    assert "bounded" in section, "AC-4: the bounded repair policy is not documented"
    assert re.search(r"\bonce\b|one .*attempt|single .*attempt", section), (
        "AC-4: the doc does not state repair is a single bounded attempt"
    )
    assert "escalat" in section, "AC-4: escalation behaviour is not documented"


def test_design_contract_is_agent_agnostic() -> None:
    """Design — Hermes is the likely driver, but the surface is agent-agnostic.

    The harness surface is deterministic and model-free; local inference powers
    only the outer agent. The doc must name Hermes as the likely local cron driver
    yet keep the contract open to any orchestrator.
    """
    lower = _normalized_prose()
    assert "hermes" in lower, (
        "Design: the doc does not name Hermes as the likely local cron driver"
    )
    assert "agent-agnostic" in lower, (
        "Design: the doc does not state the surface is agent-agnostic"
    )
    assert "deterministic" in lower, (
        "Design: the doc does not state the harness surface is deterministic/model-free"
    )
