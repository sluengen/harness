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

from tests.unit._prose import REPO_ROOT

PROCESS_DOC = REPO_ROOT / "process" / "harness.md"
REGISTRY = REPO_ROOT / "registry.yaml"

#: A registry entry is one line: two spaces, the path, then an inline mapping
#: whose first key is the unit's id. ``skills/*/references/*.md`` entries are not
#: ``SKILL.md`` and are deliberately outside the skill roster — a reference is
#: reached through the skill that links it, never chosen on its own.
AGENT_ENTRY = re.compile(r"^ {2}agents/[\w.-]+\.md:\s*\{\s*id:\s*([\w-]+)\s*,", re.MULTILINE)
SKILL_ENTRY = re.compile(r"^ {2}skills/[\w-]+/SKILL\.md:\s*\{\s*id:\s*([\w-]+)\s*,", re.MULTILINE)

#: Registered skills deliberately absent from the Skills table, each carrying the
#: reason it is untabled. An exemption whose reason is not written down decays
#: into a silent hole in the index — the thing this guard exists to prevent.
#: Two assertions bound this set in opposite directions, because a comment is not
#: a predicate: an entry the table *does* list is stale
#: (:func:`test_no_untabled_skill_exemption_outlives_its_reason`), and an entry the
#: Skills section never names at all has not earned its exemption
#: (:func:`test_an_untabled_skill_is_still_named_by_the_table_that_skips_it`).
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
    from the *Agents table*, not from the document. Mutation measured the gap in
    both directions, and they are not the same edit.

    *Widening* — narrowing :func:`_section`'s bound from ``(?=^## |\\Z)`` to
    ``(?=\\Z)`` — runs every heading to end-of-file, so each later table's rows
    count as this section's. Both membership assertions above survive it by
    construction: they only ever *admit* ids, and a wider span cannot remove one.
    Disjointness is the exclusive killer, and it is what dies when the sections
    stop being sections.

    *Deleting* the bound outright does the opposite, because ``.*?`` is lazy and
    nothing is left to force it open: each section collapses to its own heading
    line, both tabled sets derive to empty, and there the two membership
    assertions are the exclusive killers while this one passes over ``set() &
    set()``. Neither assertion covers the other's direction, which is why both
    exist.
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


def test_an_untabled_skill_is_still_named_by_the_table_that_skips_it() -> None:
    """An exemption has to be earned from the doc, not asserted by this file.

    Staleness is only half the discipline. Nothing above reads what goes *into*
    :data:`UNTABLED_SKILLS`, so the allowlist is otherwise a silent opt-out from
    the guard: adding a registered skill's id to it and deleting that skill's row
    leaves every assertion in this module green over exactly the omission #453
    was filed for. Review measured that — a mutation adding an arbitrary id to
    the set survived the whole suite (``allowlist-admits-an-arbitrary-id``:
    SURVIVED (LIVE), observable digest ``0867b7de…`` → ``8289cde5…``, so the
    mutation was live and nothing noticed).

    The exemption's stated reason is the predicate that closes it, and it happens
    to be structural rather than semantic: ``linear`` and ``github-issues`` are
    untabled *because the tracker row already names them*. So an exempted skill
    must still be named somewhere in the Skills section — just not as a row of
    its own. A skill the section never mentions is not "reached some other way";
    it is missing, and the exemption is a way of not saying so.
    """
    section = _section("Skills")
    unearned = sorted(skill for skill in UNTABLED_SKILLS if f"`{skill}`" not in section)
    assert not unearned, (
        f"UNTABLED_SKILLS exempts skills the Skills table never names: {unearned}. "
        "An exemption is only true of a skill the table reaches some other way, and "
        "the table has to show that route. Give it a row, or name it in the row of "
        "the skill that dispatches it — an allowlist entry no reader can corroborate "
        "is an opt-out from this guard, not a documented exception."
    )
