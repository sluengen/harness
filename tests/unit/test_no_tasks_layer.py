"""Guard: the ``agents/tasks/`` layer is eliminated; the steward is self-sufficient (CAL-716).

``agents/steward.md:24`` pointed at ``agents/tasks/steward.md`` — a file *not* in
``registry.yaml``, so the reference dangled in every consumer. The task file was also
stale (the retired 5-domain model; reports written to ``steward-<domain>-<date>.md`` at the
repo root, contradicting the live 2-scope model and the ``assessments/`` convention), and
``agents/tasks/release.md`` overlapped the then-current ``RELEASING.md``. SYSTEM-3 /
SYSTEM-INSIGHT-3 of ``assessments/2026-06-15-system-and-code.md`` decided to eliminate the
layer: a "task" is always one of the four durable artifacts in disguise — a **command**
(the trigger + scope), an **agent role** (who runs it + which skills), a **skill**
(the how), and a **template** (the output format); the specific instance lives in
**Linear**, not in a ``tasks/`` file.

These guards pin the eliminated state so the layer cannot regress:

* AC-1 — ``agents/tasks/`` is gone (and the registry lists no entry under it);
* AC-2 — ``agents/steward.md`` carries no dangling ``agents/tasks`` reference and is a
  valid, versioned, self-sufficient agent;
* AC-3 — ``templates/assessment.md`` exists, is a versioned surface unit, and is referenced
  for the report format; the registry lists it;
* AC-4 — the conceptual model (task = command + role + skill + template; the instance lives
  in the tracker; no ``tasks/`` artifact) is recorded in ``architecture-principles.md``;
* the useful half of ``release.md`` (release notes + a ``dev → main`` PR) was
  folded into ``RELEASING.md``, which #435 deleted with the release path it described.

*Source:* CAL-716.

**What changed at #459.** Under ADR 0016 (*tests own structure and negative
space; the reviewer owns meaning*) the **absence** assertions and the **registry
identity** assertions stay byte-for-byte — they are exactly the two classes the
decision exempts. Two prose co-occurrences went:

* ``agents/steward.md`` was searched file-wide for ``summar``/``assess``/
  ``report``. Three common words in an agent file about assessment passes:
  satisfied by any steward, including one that points at a ``tasks/`` file again.
  What that test still owns — the versioned header and the ``name:`` frontmatter
  — is identity, and stays.
* AC-4 was four common words (``command``, ``role``, ``skill``, ``template``)
  searched over the whole of ``architecture-principles.md``, a document that
  necessarily uses all four throughout. It is now **anchored to the task-model
  section** and carries the claim's polarity: *there is no ``tasks/`` artifact*.
  Occurrence it cites (``code-quality`` Part C, *A new guard cites the occurrence
  it prevents*): the whole-file form passed before the section was ever written,
  and would keep passing over a document that reinstated the fifth artifact.
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


#: The elimination, **anchored to the artifact it denies**. A document carrying a
#: negation somewhere and the token ``tasks/`` somewhere states nothing — the
#: section discusses the retired directory at length. The claim is that no such
#: artifact exists. Four words is the gap the legitimate spellings keep ("there is
#: no standalone `tasks/` artifact", "no `tasks/` artifact").
_NO_TASKS_ARTIFACT = re.compile(r"\bno\b(?:\W+\w+){0,4}?\W+`?tasks/", re.IGNORECASE)


def _task_model_section() -> str:
    """The **body** of the task-model section of ``architecture-principles.md``.

    Anchored on a heading naming the ``tasks/`` artifact, derived from the
    document's own headings rather than pinned to one title. Two narrowings:

    **By section**, because ``command``, ``role``, ``skill`` and ``template``
    are the document's working vocabulary from end to end — a file-wide search
    for them reports the model present before it was written and after it is
    removed.

    **Body only**, because the heading itself states the denial. A window that
    included its own title would answer a question about what the document
    *records* with the document's own table of contents, and the polarity
    assertion below would be satisfied by the heading no matter what the section
    went on to say.
    """
    text = PRINCIPLES.read_text()
    headings = list(re.finditer(r"^##+ .*$", text, re.MULTILINE))
    hits = [i for i, m in enumerate(headings) if "tasks/" in m.group(0).lower()]
    assert hits, (
        "architecture-principles.md must carry a section heading recording that "
        "there is no `tasks/` artifact — the layer's elimination is a decision, "
        "and a decision with no heading is not findable (CAL-716 AC-4)"
    )
    assert len(hits) == 1, (
        f"architecture-principles.md carries {len(hits)} `tasks/` headings; the "
        "task model has one home"
    )
    start = headings[hits[0]].end()
    end = headings[hits[0] + 1].start() if hits[0] + 1 < len(headings) else len(text)
    body = text[start:end]
    assert body.strip(), "the task-model section has a heading and no body"
    return body


def test_task_conceptual_model_recorded() -> None:
    """One tripwire for AC-4: the section, its four artifacts, and the denial (#459)."""
    section = _task_model_section()
    lower = section.lower()

    for term in ("command", "role", "skill", "template"):
        assert term in lower, (
            f"the task-model section must name '{term}' as one of the four task "
            "artifacts a unit of repeatable work decomposes into (CAL-716 AC-4)"
        )
    assert "tracker" in lower or "linear" in lower, (
        "the task-model section must record that the task *instance* lives in the "
        "tracker rather than in a file — without it the four artifacts read as a "
        "taxonomy and the instance has nowhere to go (CAL-716 AC-4)"
    )
    assert _NO_TASKS_ARTIFACT.search(lower), (
        "the task-model section must state that there is *no* `tasks/` artifact, "
        "with the negation anchored to it. A section that names the four "
        "artifacts and discusses `tasks/` without denying it reinstates the fifth "
        "thing this decision eliminated (CAL-716 AC-4)"
    )


# --- release.md fold --------------------------------------------------------

