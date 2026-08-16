"""The process doc's rosters must index every registered agent and skill (#453).

``process/harness.md`` is the index every agent reads at startup: a unit it does
not list is one nobody knows to reach for. Two were missing when this guard was
written — ``researcher``, registered at ``agents/researcher.md`` and dispatched
by name from ``commands/start.md``, and ``work-discovery``, registered at
``skills/work-discovery/SKILL.md`` and invoked by ``/routine``. Both were live,
both were absent from their table, and nothing measured the omission.

Both rosters are derived from ``registry.yaml`` rather than hand-listed, so the
guard closes the *next* omission and not merely those two.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PROCESS_DOC = ROOT / "process" / "harness.md"
REGISTRY = ROOT / "registry.yaml"

#: A registry entry is one line: two spaces, the path, then an inline mapping
#: whose first key is the unit's id. ``skills/*/references/*.md`` entries are not
#: ``SKILL.md`` and are deliberately outside the skill roster — a reference is
#: reached through the skill that links it, never chosen on its own.
AGENT_ENTRY = re.compile(r"^ {2}agents/[\w.-]+\.md:\s*\{\s*id:\s*([\w-]+)\s*,", re.MULTILINE)
SKILL_ENTRY = re.compile(r"^ {2}skills/[\w-]+/SKILL\.md:\s*\{\s*id:\s*([\w-]+)\s*,", re.MULTILINE)

#: Registered skills deliberately absent from the Skills table, each carrying the
#: reason it is untabled. An exemption whose reason is not written down decays
#: into a silent hole in the index — the thing this guard exists to prevent.
UNTABLED_SKILLS = {
    # `linear` and `github-issues` are provider recipes, not independently chosen
    # skills: `tracker` is the front door and selects between them, and the
    # tracker row already names both. A row of their own would misdescribe how
    # they are reached.
    "linear",
    "github-issues",
}


def _section(heading: str) -> str:
    """The process doc's ``## <heading>`` section, up to the next ``##`` heading."""
    text = PROCESS_DOC.read_text(encoding="utf-8")
    match = re.search(
        rf"^## {re.escape(heading)}\b.*?(?=^## |\Z)",
        text,
        re.MULTILINE | re.DOTALL,
    )
    assert match, f"process/harness.md has no '## {heading}' section to read"
    return match.group(0)


def _tabled_ids(heading: str) -> set[str]:
    """The backticked ids in the first column of that section's table."""
    return set(re.findall(r"^\|\s*`([^`]+)`\s*\|", _section(heading), re.MULTILINE))


def _registered_agents() -> set[str]:
    return set(AGENT_ENTRY.findall(REGISTRY.read_text(encoding="utf-8")))


def _registered_skills() -> set[str]:
    return set(SKILL_ENTRY.findall(REGISTRY.read_text(encoding="utf-8")))


def test_the_registry_rosters_this_guard_reads_are_live() -> None:
    """Non-vacuity floor: both derived rosters are populated and anchored.

    An empty roster makes every set difference below empty, so the guard would
    report green over nothing at all. Membership is pinned, never cardinality —
    a count is the drift this guard exists to remove.
    """
    agents = _registered_agents()
    skills = _registered_skills()
    assert {"dev", "reviewer"} <= agents, (
        f"the agent roster derived from registry.yaml lost its anchors; got {sorted(agents)}"
    )
    assert {"code-quality", "tracker"} <= skills, (
        f"the skill roster derived from registry.yaml lost its anchors; got {sorted(skills)}"
    )


def test_every_registered_agent_is_a_row_in_the_agents_table() -> None:
    missing = sorted(_registered_agents() - _tabled_ids("Agents"))
    assert not missing, (
        f"registered agents absent from the process doc's Agents table: {missing}. "
        "The doc is the index every agent reads — an agent it omits is one nobody "
        "knows to dispatch. Add a row per missing id."
    )


def test_every_registered_skill_is_a_row_in_the_skills_table_or_allowlisted() -> None:
    missing = sorted(_registered_skills() - _tabled_ids("Skills") - UNTABLED_SKILLS)
    assert not missing, (
        f"registered skills absent from the process doc's Skills table: {missing}. "
        "Add a row per missing id, or add it to UNTABLED_SKILLS with the reason "
        "it is reached some other way."
    )


def test_each_roster_reads_its_own_section_of_the_doc() -> None:
    """The Agents and Skills tables are read as two sections, not one open span.

    Placement is the point: #453 was filed because ``researcher`` was missing
    from the *Agents table*, not from the document. #453's own mutation table
    measured the gap — dropping the ``(?=^## |\\Z)`` bound from :func:`_section`
    lets each heading run to end-of-file, so every later table's rows count as
    this section's, and both membership assertions above survive the edit
    (``section-scope-runs-past-its-heading``: SURVIVED (LIVE), the observable
    digest moved, so the mutation changed what the guard reads). Disjointness is
    what dies when the sections stop being sections.
    """
    overlap = sorted(_tabled_ids("Agents") & _tabled_ids("Skills"))
    assert not overlap, (
        f"the Agents and Skills tables share rows: {overlap}. Each section must "
        "stop at the next '## ' heading — a roster that reads past it accepts an "
        "id listed in some other table as though it were its own."
    )


def test_no_untabled_skill_exemption_outlives_its_reason() -> None:
    """An allowlist entry for a skill that now has a row is a stale exemption."""
    stale = sorted(UNTABLED_SKILLS & _tabled_ids("Skills"))
    assert not stale, (
        f"UNTABLED_SKILLS still exempts skills the Skills table now lists: {stale}. "
        "Drop them from the allowlist — an exemption nothing needs reads as a rule."
    )
