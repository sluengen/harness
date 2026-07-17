"""CAL-1134 — the OpenCode + MLX local orchestrator stack is documented as a spike.

The promotion lifecycle (ADR 0003) is agent-agnostic: ``RUNBOOK.md`` documents the
*routine* any outer agent follows (CAL-1119). This ticket documents one concrete,
cheap **local** instantiation of that outer-agent slot — OpenCode in
non-interactive mode driving the harness promotion verbs, with an MLX LM server on
localhost supplying bounded prose/repair work — and records *why the stack stays
outside harness core*: proposal D3 resolved local inference as out of scope for
harness promotion (the model powers the outer agent, never the harness surface).

The record lives at ``specs/local-orchestrator-stack.md`` rather than in
``RUNBOOK.md`` because the stack is a **hypothesis, not yet validated**: no part of
it is installed or exercised here, and the operational runbook documents how the
harness *does* operate. Keeping the two apart stops an unproven stack from reading
as current practice, and leaves ``RUNBOOK.md``'s promotion section as the
agent-agnostic contract it already is.

These tests are the executable form of the acceptance criteria, and — as in
:mod:`tests.unit.test_promotion_routine_docs` — the **drift guard** that keeps the
prose tied to the real surface: the documented subcommands derive from the live
``promote`` Typer app and the documented stop conditions from
:data:`~harness.state.promotions.PROMOTION_STATUSES`, so a renamed subcommand or
lifecycle state fails this gate until the runbook is updated too.

* **AC-1** — the stack is documented, and why it stays outside harness core.
* **AC-2** — the minimal prompt, the harness command sequence, and the stop
  conditions for ``pr_ready`` / ``agent_may_fix`` / ``needs_ticket`` / ``blocked``.
* **AC-3** — ``launchd``/cron is the v1 scheduler; the OpenCode cron plugin is an
  optional later convenience.
* **AC-4** — the MLX LM server binds to localhost only, and local inference powers
  the outer agent, not the harness.
* **AC-5** — a rehydration checklist for a future session.
* **AC-6** — the precondition: the promotion verbs exist. Asserted against the live
  surface rather than claimed in prose.
"""

from __future__ import annotations

import re
from pathlib import Path

from harness.cli.promote import promote_app
from harness.state.promotions import PROMOTION_STATUSES

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DOC = _REPO_ROOT / "specs" / "local-orchestrator-stack.md"
_SPEC_INDEX = _REPO_ROOT / "SPEC.md"
_RUNBOOK = _REPO_ROOT / "RUNBOOK.md"

#: The four states AC-2 names as the orchestrator's stop conditions. Each is
#: cross-checked against the live ``PROMOTION_STATUSES`` below, so this list
#: cannot drift into naming a state the surface no longer has.
_STOP_CONDITIONS = ("pr_ready", "agent_may_fix", "needs_ticket", "blocked")


def _doc() -> str:
    assert _DOC.exists(), (
        f"CAL-1134: the local orchestrator runbook is missing at "
        f"{_DOC.relative_to(_REPO_ROOT)}"
    )
    return _DOC.read_text(encoding="utf-8")


def _normalized() -> str:
    """The doc, lowercased with whitespace runs collapsed — so a phrase check is
    insensitive to markdown's non-semantic soft line-wraps."""
    return re.sub(r"\s+", " ", _doc().lower())


def test_doc_exists_and_is_not_a_stub() -> None:
    """The spike has a home, and it is a real record rather than a placeholder."""
    assert len(_doc().splitlines()) > 40, (
        "the local orchestrator runbook is a stub — it must document the full stack"
    )


def test_ac1_documents_the_stack() -> None:
    """AC-1 — every layer of the stack hypothesis is named."""
    lower = _normalized()
    for component in ("opencode", "mlx", "qwen"):
        assert component in lower, f"AC-1: the runbook does not name '{component}'"


def test_ac1_states_why_the_stack_is_outside_harness_core() -> None:
    """AC-1 — the boundary is stated: the stack is outer-agent, not harness core.

    Proposal D3 resolved local inference as out of scope for harness promotion.
    The runbook must say so, not merely describe the stack.
    """
    lower = _normalized()
    assert "outside" in lower, (
        "AC-1: the runbook does not state the stack stays outside harness core"
    )
    assert "outer agent" in lower, (
        "AC-1: the runbook does not frame the stack as occupying the outer-agent slot"
    )
    assert "d3" in lower, (
        "AC-1: the runbook does not cite proposal D3, the decision that put local "
        "inference out of scope for harness promotion"
    )


def test_ac2_includes_the_minimal_prompt() -> None:
    """AC-2 — a concrete, minimal prompt is given, in a fenced block."""
    text = _doc()
    fenced = re.findall(r"```[a-z]*\n(.*?)```", text, re.DOTALL)
    assert fenced, "AC-2: the runbook contains no fenced blocks — no prompt is given"
    prompt_blocks = [b for b in fenced if "harness promote" in b and "promotion" in b.lower()]
    assert prompt_blocks, (
        "AC-2: no fenced block reads as the orchestrator prompt (one naming the "
        "promotion task and constraining the agent to harness promote commands)"
    )


def test_ac2_names_every_promote_subcommand() -> None:
    """AC-2 — the expected harness command sequence names every live subcommand.

    Derived from the live Typer app, so a renamed/added subcommand fails this gate
    until the runbook documents it.
    """
    text = _doc()
    names = sorted(c.name for c in promote_app.registered_commands if c.name)
    assert names, "the promote app registered no subcommands — introspection is broken"
    missing = [name for name in names if f"promote {name}" not in text]
    assert not missing, (
        f"AC-2: the runbook's command sequence omits these promote subcommands: "
        f"{missing} (live surface: {names})"
    )


def test_ac2_stop_conditions_are_real_lifecycle_states() -> None:
    """AC-2 (drift guard) — the four stop conditions still exist on the surface."""
    unknown = [s for s in _STOP_CONDITIONS if s not in PROMOTION_STATUSES]
    assert not unknown, (
        f"AC-2: these documented stop conditions are no longer real promotion "
        f"states: {unknown} (live: {sorted(PROMOTION_STATUSES)})"
    )


def test_ac2_documents_each_stop_condition() -> None:
    """AC-2 — the runbook says what the orchestrator does for each stop condition."""
    text = _doc()
    missing = [s for s in _STOP_CONDITIONS if f"`{s}`" not in text]
    assert not missing, (
        f"AC-2: the runbook does not document these stop conditions (as `state` "
        f"tokens): {missing}"
    )


def test_ac3_recommends_launchd_or_cron_for_v1() -> None:
    """AC-3 — ``launchd``/cron is the v1 scheduler."""
    lower = _normalized()
    assert "launchd" in lower, "AC-3: the runbook does not recommend launchd for v1"
    assert "cron" in lower, "AC-3: the runbook does not mention cron scheduling"


def test_ac3_treats_the_opencode_cron_plugin_as_optional_later() -> None:
    """AC-3 — the OpenCode cron plugin is an optional later convenience, not v1."""
    lower = _normalized()
    assert "cron plugin" in lower, (
        "AC-3: the runbook does not mention the OpenCode cron plugin"
    )
    assert "optional" in lower, (
        "AC-3: the runbook does not treat the OpenCode cron plugin as optional"
    )


def test_ac4_mlx_server_binds_localhost_only() -> None:
    """AC-4 — the MLX LM server must bind to localhost only."""
    lower = _normalized()
    assert "localhost" in lower, (
        "AC-4: the runbook does not state the MLX LM server binds to localhost"
    )
    assert re.search(r"localhost only|only to localhost|bind[s]? .{0,30}localhost", lower), (
        "AC-4: the runbook does not state the localhost bind as a requirement"
    )


def test_ac4_local_inference_powers_the_outer_agent_not_the_harness() -> None:
    """AC-4 — local inference powers the outer agent; the harness stays model-free."""
    lower = _normalized()
    assert "not the harness" in lower or "never the harness" in lower, (
        "AC-4: the runbook does not state that local inference powers the outer "
        "agent rather than the harness"
    )


def test_ac5_has_a_rehydration_checklist() -> None:
    """AC-5 — a rehydration checklist for a future session, covering all five steps."""
    lower = _normalized()
    assert "rehydration" in lower, "AC-5: the runbook has no rehydration checklist"
    required = {
        "the accepted proposal": r"proposal",
        "the promotion command contracts": r"contract",
        "the MLX/OpenCode config": r"config",
        "a dry-run promotion": r"dry[- ]run",
        "escalation behaviour": r"escalat",
    }
    missing = [label for label, pat in required.items() if not re.search(pat, lower)]
    assert not missing, (
        f"AC-5: the rehydration checklist does not cover: {missing}"
    )


def test_ac6_promotion_surface_exists() -> None:
    """AC-6 — the precondition holds: the promotion verbs exist.

    The ticket gates this work on the promotion CLI/ledger/merge/gate/PR/escalation
    verbs existing (CAL-1113–1118). That is a checkable property of the live
    surface, so it is asserted here rather than claimed in prose.
    """
    names = {c.name for c in promote_app.registered_commands if c.name}
    for verb in ("start", "continue", "status", "pr", "escalate"):
        assert verb in names, (
            f"AC-6: the promotion surface is missing '{verb}' — this ticket's "
            f"precondition does not hold"
        )


def test_doc_is_registered_in_the_spec_index() -> None:
    """Repo convention — a spec under ``specs/`` is reachable from the SPEC.md index."""
    assert "specs/local-orchestrator-stack.md" in _SPEC_INDEX.read_text(encoding="utf-8"), (
        "the local orchestrator runbook is not registered in SPEC.md's spec index"
    )


def test_runbook_points_at_the_stack_record() -> None:
    """The operational runbook points at the concrete stack from its promotion section.

    The agent-agnostic contract stays in ``RUNBOOK.md``; the concrete stack lives in
    its own record. The pointer is what keeps the second discoverable from the first.
    """
    assert "specs/local-orchestrator-stack.md" in _RUNBOOK.read_text(encoding="utf-8"), (
        "RUNBOOK.md does not point at specs/local-orchestrator-stack.md"
    )
