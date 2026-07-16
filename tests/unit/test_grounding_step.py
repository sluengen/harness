"""CAL-922 — WS-A: ground every change spec in current reality via a read-only
research subagent (inline self-grounding fallback).

*Source:* ``specs/proposals/ground-specs-and-context-rollover.md`` (accepted
2026-06-30), WS-A — delivery re-scoped to a research subagent (primary) with
inline self-grounding (fallback). Origin: DoorDash isolated-research-phase +
Loop-Engineering sub-agent split.

The spec-driven flow jumped straight from "open the Linear issue" to "write the
change spec" with no step that grounds the spec in *current* code — so agents
asserted stale recalled facts (a moved file, a renamed flag, a superseded
decision) that reverted the ticket to blocked mid-build. WS-A adds a grounding
step: a read-only ``researcher`` agent investigates current reality and returns a
distilled grounding brief, recorded as the change spec's ``Grounding`` section;
where no sub-agent host is available the executor self-grounds inline. The
grounding *contract* is verify-every-fact-that-names-a-file/function/flag/
version/decision against current code.

This guard pins the *presence* of that rule across the surface — it cannot (and
does not claim to) prove grounding was genuinely performed on any ticket (the
honest limit stated in the proposal's risks). Acceptance criteria (CAL-922):

* **AC-1** — a read-only ``researcher`` agent exists (no Edit/Write) and the
  ``/start`` flow dispatches it. :func:`test_researcher_agent_present`,
  :func:`test_researcher_agent_is_read_only`, :func:`test_researcher_registered`,
  :func:`test_start_flow_dispatches_researcher`.
* **AC-2** — the brief follows a defined schema (verified facts w/ ``path:line``,
  versions, decisions surfaced, open questions), recorded as the Grounding
  artifact. :func:`test_researcher_brief_schema`,
  :func:`test_change_template_has_grounding_section`.
* **AC-3** — the grounding contract lives in the skills (verify
  file/function/flag/version/decision facts vs current code; surface decisions).
  :func:`test_spec_driven_development_has_grounding_step`,
  :func:`test_spec_authoring_has_grounding_craft`.
* **AC-4 (fallback)** — with no sub-agent host, the executor self-grounds inline
  and records the same section. :func:`test_inline_grounding_fallback_documented`.
* **AC-5 (parity)** — the researcher is a registered surface unit; the general
  header/registry parity guard (``test_surface_headers_match_registry``) covers
  version equality. :func:`test_researcher_registered`.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent.parent
RESEARCHER = REPO_ROOT / "agents" / "researcher.md"
SDD = REPO_ROOT / "skills" / "spec-driven-development" / "SKILL.md"
SPEC_AUTHORING = REPO_ROOT / "skills" / "spec-authoring" / "SKILL.md"
CHANGE_TEMPLATE = REPO_ROOT / "templates" / "change.md"
START_COMMAND = REPO_ROOT / "commands" / "start.md"
REGISTRY = REPO_ROOT / "registry.yaml"


# --- AC-1: the read-only researcher agent exists and is dispatched -------------


def test_researcher_agent_present() -> None:
    """AC-1: ``agents/researcher.md`` exists with Agent frontmatter and a header."""
    assert RESEARCHER.exists(), (
        "agents/researcher.md must exist — the read-only grounding agent (CAL-922 AC-1)."
    )
    text = RESEARCHER.read_text()
    assert re.search(r"^name:\s*researcher\s*$", text, re.MULTILINE), (
        "agents/researcher.md must declare `name: researcher` in its frontmatter."
    )
    assert re.search(r"guidance:researcher@[\d.]+", text), (
        "agents/researcher.md must carry a `guidance:researcher@x.y.z` version header."
    )


def test_researcher_agent_is_read_only() -> None:
    """AC-1: the researcher is Explore-style read-only — its ``tools:`` frontmatter
    grants neither Edit nor Write, so read-only enforcement is structural, not
    just prose."""
    text = RESEARCHER.read_text()
    m = re.search(r"^tools:\s*\[([^\]]*)\]", text, re.MULTILINE)
    assert m, "agents/researcher.md must declare a `tools: [...]` frontmatter list."
    tools = {t.strip() for t in m.group(1).split(",") if t.strip()}
    assert "Edit" not in tools and "Write" not in tools, (
        f"the researcher must be read-only (no Edit/Write); got tools={sorted(tools)} "
        "(CAL-922 AC-1)."
    )
    assert "Read" in tools, "the researcher needs Read to investigate."


def test_researcher_registered() -> None:
    """AC-1/AC-5: the researcher is a registered distributed surface unit under the
    ``harness`` profile (the footprint/parity guards require every surface file to
    be registered with a matching header)."""
    entry = re.search(
        r"agents/researcher\.md:\s*\{[^}]*id:\s*researcher[^}]*\}", REGISTRY.read_text()
    )
    assert entry, (
        "registry.yaml files: must list agents/researcher.md with id: researcher "
        "(CAL-922 AC-1)."
    )
    assert "harness" in entry.group(0), (
        "the researcher entry must be in the `harness` profile."
    )


def test_start_flow_dispatches_researcher() -> None:
    """AC-1: the agent-led ``/start`` flow dispatches the researcher to ground the
    ticket — the deterministic ``start`` CLI verb is untouched."""
    text = START_COMMAND.read_text()
    assert "researcher" in text, (
        "commands/start.md must dispatch the `researcher` agent as its grounding "
        "step (CAL-922 AC-1)."
    )
    assert re.search(r"ground", text, re.IGNORECASE), (
        "commands/start.md must name the grounding step (CAL-922 AC-1)."
    )


# --- AC-2: the brief schema + the recorded Grounding section -------------------


def test_researcher_brief_schema() -> None:
    """AC-2: the researcher's output schema is defined — verified facts anchored to
    ``path:line``, current versions/flags, decisions surfaced, open questions —
    because a thin brief is the main failure mode."""
    low = RESEARCHER.read_text().lower()
    for needle in ("path:line", "decision", "open question", "version"):
        assert needle in low, (
            f"agents/researcher.md must define the brief-schema element {needle!r} "
            "(CAL-922 AC-2)."
        )


def test_change_template_has_grounding_section() -> None:
    """AC-2: ``templates/change.md`` carries a recorded ``Grounding`` section — the
    brief is recorded there (mirroring the Watchlist-trigger precedent)."""
    text = CHANGE_TEMPLATE.read_text()
    assert re.search(r"^#+\s*Grounding\b", text, re.MULTILINE), (
        "templates/change.md must have a `## Grounding` section for the recorded "
        "brief (CAL-922 AC-2)."
    )


# --- AC-3: the grounding contract lives in the skills --------------------------

#: The concrete, checkable, staleness-prone fact kinds the grounding rule is
#: scoped to (proposal D2). All five co-occurring is the signature of the rule;
#: "function"/"flag" do not pre-exist in spec-authoring, so the check is
#: non-vacuous.
_FACT_KINDS = ("file", "function", "flag", "version", "decision")


def test_spec_driven_development_has_grounding_step() -> None:
    """AC-3: the flow skill adds a grounding step before the change spec is written
    — verify recalled facts against current code."""
    text = SDD.read_text()
    assert re.search(r"ground", text, re.IGNORECASE), (
        "spec-driven-development must add a grounding step to the flow (CAL-922 AC-3)."
    )
    assert re.search(r"current (code|reality)", text, re.IGNORECASE), (
        "the grounding step must say to verify against current code/reality (AC-3)."
    )


def test_spec_authoring_has_grounding_craft() -> None:
    """AC-3: spec-authoring carries the grounding craft — verify every fact that
    names a file / function / flag / version / decision against current code, and
    the recorded brief/section."""
    low = SPEC_AUTHORING.read_text().lower()
    assert "ground" in low, "spec-authoring must document the grounding craft (AC-3)."
    missing = [k for k in _FACT_KINDS if k not in low]
    assert not missing, (
        "spec-authoring's grounding scope must name every checkable fact kind; "
        f"missing {missing} (CAL-922 AC-3 / proposal D2)."
    )


# --- AC-4: the inline self-grounding fallback ---------------------------------


def test_inline_grounding_fallback_documented() -> None:
    """AC-4: where no sub-agent host is available, the executor self-grounds inline
    and records the same section — grounding always happens."""
    corpus = (
        SDD.read_text() + SPEC_AUTHORING.read_text() + START_COMMAND.read_text()
    ).lower()
    assert "inline" in corpus and "fallback" in corpus, (
        "the inline self-grounding fallback must be documented (CAL-922 AC-4)."
    )
