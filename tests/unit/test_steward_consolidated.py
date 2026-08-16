"""Guard: one ``steward`` agent; ``/assess`` selects the scope; domains are skills (CAL-704).

``/assess`` dispatched one of *two* agents — ``agents/code-steward.md`` (code domain) and
``agents/system-steward.md`` (guidance domain) — that shared one methodology
(``skills/assessment-craft/SKILL.md``) and one procedure (``agents/tasks/steward.md``). The
*process* lived in two files; only the *domain standards* differed. B1 of the pre-launch
consolidation (``specs/proposals/pre-launch-consolidation.md``) adopts the layering —
**command = the scope; agent = the process; skills = the domain standards, pulled
just-in-time** — merging the two stewards into one ``agents/steward.md`` and extracting the
guidance-domain standards into ``skills/guidance-coherence/SKILL.md``.

These guards pin the consolidated state so the split cannot regress:

* AC-1 — the two old steward agents are gone and unlisted; one ``steward`` agent replaces
  them; no dangling ``code-steward``/``system-steward`` reference survives in the live
  installed surface (history, specs/proposals, assessments, and tests keep their records);
* AC-2 — *retired.* ``skills/guidance-coherence`` and the ``system`` scope went with
  the runtime (ADR 0015 / #435); the steward now has two scopes, not three;
* AC-3 — ``/assess <scope>`` selects domains; ``code`` pulls the code-domain skills,
  ``architecture`` pulls the shape-domain standards, and ``--deep`` adds the broad lenses;
* AC-4 — the design-system lens is layer-gated;
* AC-6 — the two-surfaces / one-steward layering principle is recorded in
  ``specs/architecture-principles.md``.

*Source:* CAL-704.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent.parent
AGENTS_DIR = REPO_ROOT / "agents"
STEWARD = AGENTS_DIR / "steward.md"
CODE_STEWARD = AGENTS_DIR / "code-steward.md"
SYSTEM_STEWARD = AGENTS_DIR / "system-steward.md"
ASSESS = REPO_ROOT / "commands" / "assess.md"
REGISTRY = REPO_ROOT / "registry.yaml"
PRINCIPLES = REPO_ROOT / "specs" / "architecture-principles.md"

#: The live, installed surface — the files a consumer repo pulls. History (CHANGELOG),
#: specs/proposals + assessments (which record the change), and tests (this guard names the
#: retired agents as data) are deliberately excluded.
_SURFACE = [
    *sorted((REPO_ROOT / "commands").glob("*.md")),
    *sorted(AGENTS_DIR.glob("*.md")),
    *sorted((REPO_ROOT / "skills").glob("*/SKILL.md")),
    *sorted((REPO_ROOT / "templates").glob("*.md")),
    REPO_ROOT / "process" / "harness.md",
    REPO_ROOT / "AGENTS.md",
    REPO_ROOT / "CLAUDE.md",
    REPO_ROOT / "GEMINI.md",
    REGISTRY,
]


# --- AC-1: one steward replaces two -----------------------------------------


def test_old_steward_agents_removed() -> None:
    """Both per-domain steward agent files are gone — folded into one ``steward``."""
    for old in (CODE_STEWARD, SYSTEM_STEWARD):
        assert not old.exists(), (
            f"{old.relative_to(REPO_ROOT)} must be removed — the two stewards merge into "
            "agents/steward.md (CAL-704)"
        )


def test_single_steward_agent_exists() -> None:
    """``agents/steward.md`` exists and is a valid, versioned, named agent."""
    assert STEWARD.exists(), "agents/steward.md must exist (the single process agent, CAL-704)"
    text = STEWARD.read_text()
    assert re.search(r"<!-- guidance:steward@\d+\.\d+\.\d+ -->", text), (
        "agents/steward.md must carry a 'guidance:steward@<version>' header"
    )
    assert re.search(r"^name:\s*steward\s*$", text, re.MULTILINE), (
        "agents/steward.md frontmatter must declare 'name: steward'"
    )


def test_registry_lists_steward_not_old_stewards() -> None:
    """The registry lists the new ``steward`` and drops both old steward entries."""
    text = REGISTRY.read_text()
    assert "code-steward" not in text and "system-steward" not in text, (
        "registry.yaml must not list code-steward/system-steward — remove their entries (CAL-704)"
    )
    assert re.search(r"agents/steward\.md:\s*\{\s*id:\s*steward,", text), (
        "registry.yaml must list 'agents/steward.md: { id: steward, ... }' (CAL-704)"
    )


def test_no_dangling_steward_reference_in_surface() -> None:
    """No live installed-surface file mentions the retired per-domain steward names (AC-1)."""
    offenders = [
        str(p.relative_to(REPO_ROOT))
        for p in _SURFACE
        if p.exists() and re.search(r"code-steward|system-steward", p.read_text())
    ]
    assert not offenders, (
        "the consolidated surface must carry no 'code-steward'/'system-steward' reference; "
        f"found in: {offenders} (CAL-704 AC-1)"
    )


# --- AC-3: /assess selects the scope; scopes pull the expected skills -------


def test_assess_documents_scopes_and_deep() -> None:
    """``/assess`` documents the ``code``/``system`` scopes and the ``--deep`` modifier."""
    text = ASSESS.read_text()
    lower = text.lower()
    assert "--deep" in text, "commands/assess.md must document the '--deep' modifier (CAL-704)"
    assert "steward" in text, "commands/assess.md must dispatch the single 'steward' agent"
    assert "code" in lower and "architecture" in lower, (
        "commands/assess.md must document the 'code' and 'architecture' scopes"
    )


def test_steward_routes_each_scope_to_its_domain_skills() -> None:
    """The steward names the domain skills each scope pulls just-in-time (AC-3)."""
    text = STEWARD.read_text()
    # The code scope pulls the code-domain standards.
    code_skills = (
        "code-quality",
        "test-driven-development",
        "architecture",
        "engineering-principles",
    )
    for skill in code_skills:
        assert skill in text, f"steward.md (code scope) must pull '{skill}' as a domain standard"
    # The architecture scope pulls the shape-domain standards.
    assert "engineering-principles" in text, (
        "steward.md (architecture scope) must pull 'engineering-principles'"
    )
    # The command owns --deep's detailed lenses; the role points there.
    assess = ASSESS.read_text().lower()
    assert "--deep" in text and "commands/assess.md" in text
    assert "coverage" in assess
    assert "spec" in assess and "coherence" in assess


# --- AC-4: the design-system lens is layer-gated ----------------------------


def test_design_system_lens_is_layer_gated() -> None:
    """The design-system lens runs only when ``layers.design_system`` is on (AC-4)."""
    text = ASSESS.read_text().lower()
    assert "design-system adherence" in text and "layer-gated" in text, (
        "commands/assess.md must keep the design-system lens layer-gated"
    )


# --- AC-6: the layering principle is recorded -------------------------------


def test_layering_principle_recorded() -> None:
    """``architecture-principles.md`` records the two-surfaces / one-steward layering (AC-6)."""
    text = PRINCIPLES.read_text()
    lower = text.lower()
    assert "one steward" in lower or "single steward" in lower, (
        "architecture-principles.md must record the one-steward decision (CAL-704 AC-6)"
    )
    # The layering: command = scope, agent = process, skills = domain standards.
    assert "domain standard" in lower, (
        "architecture-principles.md must record that skills hold the domain standards"
    )
    assert "just-in-time" in lower or "just in time" in lower, (
        "architecture-principles.md must record that domain skills are pulled just-in-time"
    )
