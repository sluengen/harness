"""Guard: the ``agents/tasks/`` layer is eliminated; the steward is self-sufficient (CAL-716).

``agents/steward.md:24`` pointed at ``agents/tasks/steward.md`` — a file *not* in
``registry.yaml``, so the reference dangled in every consumer. The task file was also
stale (the retired 5-domain model; reports written to ``steward-<domain>-<date>.md`` at the
repo root, contradicting the live 2-scope model and the ``assessments/`` convention), and
``agents/tasks/release.md`` overlapped ``RELEASING.md``. SYSTEM-3 / SYSTEM-INSIGHT-3 of
``assessments/2026-06-15-system-and-code.md`` decided to eliminate the layer: a "task" is
always one of the four durable artifacts in disguise — a **command** (the trigger + scope),
an **agent role** (who runs it + which skills), a **skill** (the how), and a **template**
(the output format); the specific instance lives in **Linear**, not in a ``tasks/`` file.

These guards pin the eliminated state so the layer cannot regress:

* AC-1 — ``agents/tasks/`` is gone (and the registry lists no entry under it);
* AC-2 — ``agents/steward.md`` carries no dangling ``agents/tasks`` reference and is a
  valid, versioned, self-sufficient agent;
* AC-3 — ``templates/assessment.md`` exists, is a versioned surface unit, and is referenced
  for the report format; the registry lists it;
* AC-4 — the conceptual model (task = command + role + skill + template; the instance lives
  in Linear; no ``tasks/`` artifact) is recorded in ``architecture-principles.md``;
* the useful half of ``release.md`` (release notes from Linear + a ``dev → main`` PR) is
  folded into ``RELEASING.md``.

*Source:* CAL-716.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent.parent
AGENTS_DIR = REPO_ROOT / "agents"
TASKS_DIR = AGENTS_DIR / "tasks"
STEWARD = AGENTS_DIR / "steward.md"
ASSESS_TEMPLATE = REPO_ROOT / "templates" / "assessment.md"
ASSESSMENT_CRAFT = REPO_ROOT / "skills" / "assessment-craft" / "SKILL.md"
REGISTRY = REPO_ROOT / "registry.yaml"
PRINCIPLES = REPO_ROOT / "specs" / "architecture-principles.md"
RELEASING = REPO_ROOT / "RELEASING.md"


# --- AC-1: the tasks layer is gone ------------------------------------------


def test_agents_tasks_directory_removed() -> None:
    """``agents/tasks/`` no longer exists — the redundant layer is eliminated."""
    assert not TASKS_DIR.exists(), (
        "agents/tasks/ must be removed — a task is always a command/role/skill/template "
        "in disguise, never a fifth artifact (CAL-716 AC-1)"
    )
    assert not list(AGENTS_DIR.glob("tasks/*.md")), (
        "no agents/tasks/*.md file may survive the elimination (CAL-716 AC-1)"
    )


def test_registry_lists_no_tasks_entry() -> None:
    """The registry copy-list carries no ``agents/tasks/`` entry (it never installed)."""
    assert "agents/tasks" not in REGISTRY.read_text(), (
        "registry.yaml must list no agents/tasks/ path (CAL-716 AC-1)"
    )


# --- AC-2: the steward is self-sufficient -----------------------------------


def test_steward_has_no_dangling_tasks_reference() -> None:
    """``agents/steward.md`` no longer points at the removed ``agents/tasks/`` file (AC-2)."""
    text = STEWARD.read_text()
    assert "agents/tasks" not in text, (
        "agents/steward.md must not reference agents/tasks/ — fold the procedure in or point "
        "only to installed files (CAL-716 AC-2)"
    )


def test_steward_is_versioned_and_self_sufficient() -> None:
    """The steward is a valid, versioned, named agent that carries its own procedure (AC-2)."""
    text = STEWARD.read_text()
    assert re.search(r"<!-- guidance:steward@\d+\.\d+\.\d+ -->", text), (
        "agents/steward.md must carry a 'guidance:steward@<version>' header"
    )
    assert re.search(r"^name:\s*steward\s*$", text, re.MULTILINE), (
        "agents/steward.md frontmatter must declare 'name: steward'"
    )
    lower = text.lower()
    # The folded procedure: read the scope, summarise, assess, write a dated report.
    assert "summar" in lower and "assess" in lower and "report" in lower, (
        "agents/steward.md must carry the folded procedure (read/summarise/assess/report) "
        "now that the tasks/ pointer is gone (CAL-716 AC-2)"
    )


# --- AC-3: the report format lives in a template, and is referenced ----------


def test_assessment_template_exists_and_is_versioned() -> None:
    """``templates/assessment.md`` exists and is a versioned surface unit (AC-3)."""
    assert ASSESS_TEMPLATE.exists(), (
        "templates/assessment.md must exist — the report-format artifact the steward writes "
        "into (CAL-716 AC-3)"
    )
    text = ASSESS_TEMPLATE.read_text()
    assert re.search(r"<!-- guidance:template-assessment@\d+\.\d+\.\d+ -->", text), (
        "templates/assessment.md must carry a 'guidance:template-assessment@<version>' header"
    )
    lower = text.lower()
    # The format must carry the load-bearing parts of an assessment report.
    for part in ("finding", "severity", "insight"):
        assert part in lower, (
            f"templates/assessment.md must document the '{part}' part of the report format"
        )


def test_registry_lists_assessment_template() -> None:
    """The registry lists ``templates/assessment.md`` as ``template-assessment`` (AC-3)."""
    assert re.search(
        r"templates/assessment\.md:\s*\{\s*id:\s*template-assessment,",
        REGISTRY.read_text(),
    ), (
        "registry.yaml must list 'templates/assessment.md: { id: template-assessment, ... }' "
        "(CAL-716 AC-3)"
    )


def test_assessment_template_is_referenced_for_the_format() -> None:
    """The template is referenced where the report format is defined (AC-3).

    A template nobody points at is dead surface; the steward (the writer) and
    ``assessment-craft`` (the methodology's Output section) must name it.
    """
    referers = [
        p
        for p in (STEWARD, ASSESSMENT_CRAFT)
        if p.exists() and "templates/assessment.md" in p.read_text()
    ]
    assert referers, (
        "templates/assessment.md must be referenced for the report format by the steward "
        "and/or assessment-craft (CAL-716 AC-3)"
    )


# --- AC-4: the conceptual model is recorded ---------------------------------


def test_task_conceptual_model_recorded() -> None:
    """``architecture-principles.md`` records the task = command + role + skill + template model.

    The instance lives in Linear; there is no ``tasks/`` artifact (AC-4).
    """
    text = PRINCIPLES.read_text()
    lower = text.lower()
    for term in ("command", "role", "skill", "template"):
        assert term in lower, (
            f"architecture-principles.md must name '{term}' as one of the four task artifacts "
            "(CAL-716 AC-4)"
        )
    assert "linear" in lower or "tracker" in lower, (
        "architecture-principles.md must record that the task instance lives in Linear/the "
        "tracker (CAL-716 AC-4)"
    )
    assert "tasks/" in text, (
        "architecture-principles.md must record that there is no tasks/ artifact (CAL-716 AC-4)"
    )


# --- release.md fold --------------------------------------------------------


def test_releasing_doc_absorbs_release_notes_procedure() -> None:
    """The useful half of the removed ``release.md`` is folded into ``RELEASING.md``.

    ``release.md`` summarised completed tracker tickets into release notes and
    raised the release PR; that procedure must survive its deletion (CAL-716).
    (The tracker cutover to GitHub, tick #69, means "tracker tickets" reads as
    GitHub issues here, not Linear tickets — see #196.)
    """
    lower = RELEASING.read_text().lower()
    assert "release notes" in lower, (
        "RELEASING.md must document generating release notes (folded from "
        "agents/tasks/release.md, CAL-716)"
    )
    assert "completed issues" in lower, (
        "RELEASING.md must document summarising completed tracker issues into the notes (CAL-716)"
    )
