"""CAL-1112 — record the promotion branch policy and lifecycle design.

The accepted proposal ``specs/proposals/local-promotion-steward.md`` (Option C)
needs a durable design record before the ``harness promote`` mechanics are built:
the universal ``dev -> staging -> main`` topology with ``staging`` first-class, the
promotion lifecycle states, the bounded repair authority, the PR authority, and
the escalation path. This ticket records that design — no CLI, no mechanics.

This guards the recorded decision (ADR 0003) plus the ``CONTEXT.md`` branch-policy
change (``staging`` first-class) and the decisions index — the same shape as
``test_review_engine_decision.py`` guards ADR 0002 and
``test_loop_substrate_decision.py`` guards ADR 0001.
"""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
ADR = REPO_ROOT / "specs" / "decisions" / "0003-promotion-lifecycle.md"
CONTEXT = REPO_ROOT / "CONTEXT.md"
PROPOSAL = "specs/proposals/local-promotion-steward.md"


def _read(path: Path) -> str:
    assert path.exists(), f"expected file to exist: {path.relative_to(REPO_ROOT)}"
    return path.read_text(encoding="utf-8")


# --- AC-1: CONTEXT.md records staging as first-class between dev and main -----


def _branches_block(context: str) -> list[str]:
    """The lines of the ``branches:`` YAML block (until the next top-level key)."""
    lines = context.splitlines()
    start = next(i for i, ln in enumerate(lines) if ln.startswith("branches:"))
    block: list[str] = []
    for ln in lines[start + 1 :]:
        if ln and not ln[0].isspace():  # next top-level key ends the block
            break
        block.append(ln)
    return block


def test_context_branches_records_staging_first_class() -> None:
    """``branches:`` names staging as its own key — not buried in a comment."""
    block = _branches_block(_read(CONTEXT))
    keys = [ln.strip().split(":", 1)[0] for ln in block if ":" in ln and ln.strip()]
    assert "staging" in keys, (
        "CONTEXT.md branches: must record `staging` as a first-class key "
        "(AC-1), alongside integration and release"
    )


def test_context_staging_sits_between_dev_and_main() -> None:
    """Ordering encodes the ``dev -> staging -> main`` topology."""
    block = _branches_block(_read(CONTEXT))
    idx = {
        key: i
        for i, ln in enumerate(block)
        if ln.strip()
        for key in [ln.strip().split(":", 1)[0]]
    }
    assert idx.get("integration", -1) < idx.get("staging", -1) < idx.get(
        "release", 1 << 30
    ), (
        "staging must sit between integration (dev) and release (main) so the "
        "block reads as the dev -> staging -> main promotion topology"
    )


# --- AC-2: ADR records lifecycle states, branch policy, repair + PR authority -


def test_adr_present() -> None:
    """The promotion design is recorded as an ADR."""
    assert ADR.exists(), (
        "the promotion branch policy and lifecycle design must be recorded in "
        "specs/decisions/0003-promotion-lifecycle.md"
    )


def test_adr_records_the_universal_topology() -> None:
    """ADR records ``dev -> staging -> main`` as the universal promotion topology."""
    low = _read(ADR).lower()
    for branch in ("dev", "staging", "main"):
        assert branch in low, f"ADR must name the `{branch}` branch in the topology"
    assert "staging" in low and (
        "candidate" in low or "stabiliz" in low or "stabilis" in low
    ), "ADR must describe staging as the stabilized release candidate"


def test_adr_records_the_lifecycle_states() -> None:
    """ADR records the promotion lifecycle / policy-classification states."""
    low = _read(ADR).lower()
    for state in ("pr_ready", "agent_may_fix", "needs_ticket", "blocked"):
        assert state in low, f"ADR must record the `{state}` promotion state"
    for terminal in ("pr_opened", "escalated"):
        assert terminal in low, f"ADR must record the `{terminal}` terminal state"


def test_adr_records_repair_authority() -> None:
    """ADR records the bounded, one-attempt repair authority."""
    low = _read(ADR).lower()
    assert "repair" in low, "ADR must record the repair authority"
    assert "bounded" in low or "one" in low or "single" in low, (
        "ADR must record that repair is bounded to a single attempt"
    )
    assert "escalat" in low, "ADR must record the escalation path"


def test_adr_records_pr_authority() -> None:
    """ADR records that the harness owns PR creation and never auto-merges."""
    low = _read(ADR).lower()
    assert "pr" in low and "promotion branch" in low, (
        "ADR must record that the harness pushes only the promotion branch and "
        "creates the PR"
    )
    assert "auto-merge" in low or "auto merge" in low or "direct" in low, (
        "ADR must record that direct target-branch pushes / auto-merge are out "
        "of scope for the release hop"
    )


# --- CAL-1158 AC-6: the amendment is recorded, with its rationale -------------


def test_adr_records_the_staging_hop_amendment_and_its_rationale() -> None:
    """AC-6 — the ADR records the 2026-07-17 decision *and why*.

    The rationale is the load-bearing half: without "staging is derived, main is
    decided" the amendment reads as a safety rule being weakened, and the next
    reader re-litigates it. The ticket and date make it traceable.
    """
    text = _read(ADR)
    low = text.lower()
    assert "CAL-1158" in text, "ADR must cite the amending ticket (AC-6)"
    assert "2026-07-17" in text, "ADR must date the amendment (AC-6)"
    assert "derived" in low and "decided" in low, (
        "ADR must record the amendment's rationale — staging is *derived* (the "
        "gate is the decision) while main is *decided* (the human decision point)"
    )
    assert "promoted" in low, (
        "ADR must record the `promoted` terminal state the staging hop reaches"
    )


def test_adr_scopes_the_no_direct_push_rule_to_the_release_hop() -> None:
    """AC-6 — the rule is scoped, not deleted: main stays PR-only.

    A reader must be able to tell which hop each rule governs. The failure this
    guards is the original wording's: one rule stated for "target branches" that
    silently bound a hop its rationale never reached.
    """
    low = _read(ADR).lower()
    assert "release hop" in low, (
        "ADR must name the *release hop* as what the no-direct-push / no-auto-merge "
        "rule is scoped to"
    )
    assert "staging hop" in low, (
        "ADR must name the *staging hop* as the direct-push path"
    )
    assert "auto-merge remains out of scope" in low or "auto-merge" in low, (
        "ADR must keep auto-merge out of scope"
    )


def test_adr_mechanism_wording_does_not_contradict_the_pr_rule() -> None:
    """AC-6 — the topology section no longer reads as a direct merge *onto* staging.

    The original line 22 ("Promotion merges `dev → staging`, runs the gate there")
    described the topology in mechanism terms that contradicted the PR-authority
    section, and misled the person configuring branch protection. The merge happens
    on the *candidate*; only a green candidate advances the target.
    """
    low = _read(ADR).lower()
    assert "candidate" in low, (
        "the topology section must describe the merge as landing on the promotion "
        "*candidate*, not on staging itself"
    )
    assert "promotion merges `dev → staging`, runs the gate there" not in low, (
        "the contradicting mechanism wording must be gone: it reads as a direct "
        "merge onto staging while the PR-authority section governs the real path"
    )


# --- AC-3: the harness is agent-agnostic -------------------------------------


def test_adr_states_harness_is_agent_agnostic() -> None:
    """ADR states the harness is agent-agnostic; the orchestrator is external."""
    text = _read(ADR)
    low = text.lower()
    assert "agent-agnostic" in low or "agent agnostic" in low, (
        "ADR must state the harness promotion surface is agent-agnostic (AC-3)"
    )
    named = sum(
        name in low for name in ("hermes", "openclaw", "claude", "codex", "human")
    )
    assert named >= 3, (
        "ADR must name the interchangeable outer orchestrators "
        "(Hermes/OpenClaw/Claude/Codex/humans)"
    )


def test_adr_cites_the_ticket_and_proposal() -> None:
    """The ADR traces to the deciding ticket and the accepted proposal."""
    text = _read(ADR)
    assert "CAL-1112" in text, "ADR must cite CAL-1112"
    assert "local-promotion-steward" in text, (
        f"ADR must cite the accepted proposal ({PROPOSAL})"
    )


# --- CONTEXT decisions index names the ADR (mirrors the 0002 guard) ----------


def test_context_index_names_adr_0003() -> None:
    """The CONTEXT.md decisions index lists ADR 0003 alongside 0001 and 0002."""
    text = _read(CONTEXT)
    assert "0003" in text and "specs/decisions/0003" in text, (
        "CONTEXT.md decisions index must name ADR 0003"
    )
