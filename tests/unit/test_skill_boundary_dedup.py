"""CAL-718 — skill-boundary dedup + engine-era ``lessons/`` retirement.

*Source:* ``assessments/2026-06-15-system-and-code.md`` SYSTEM-4 + SYSTEM-5.

Two shared rules were each restated near-verbatim in two skills with no single
owner, and a ``lessons/`` tree of 19 engine-era files lingered, referenced by
nothing live. Duplicated knowledge drifts; this guard pins the post-dedup state
so it cannot silently grow back:

* **AC-1a (decision mechanics)** — ``spec-authoring`` owns the "a decision lives
  in the spec it governs / no ``decisions/`` folder / supersede in place" rule;
  ``architecture`` keeps only "when is a choice decision-worthy" and *points* to
  ``spec-authoring`` rather than restating the mechanics as its own sections.
* **AC-1b (smallest change + rule of three)** — ``engineering-principles`` owns
  both principles; ``code-quality`` *references* it from both the "smallest
  working solution" and "extract on the third strike" subsections rather than
  restating them uncross-referenced.
* **AC-2** — ``lessons/`` is retired: no tracked file remains under it.

AC-3 (registry/version parity) is already enforced globally by
``test_guidance_source.test_surface_headers_match_registry`` — the bumps this
ticket makes are checked there, so a second per-skill parity guard here would be
redundant (the over-engineering lens ``review-discipline`` Stage 2 names).
"""

from __future__ import annotations

import re
from pathlib import Path

from tests._gitutil import tracked_files_under

REPO_ROOT = Path(__file__).resolve().parents[2]
SKILLS = REPO_ROOT / "skills"


def _read(rel: str) -> str:
    return (SKILLS / rel).read_text()


def _section(text: str, heading: str) -> str:
    """The body of a Markdown section.

    From the line whose stripped heading text equals ``heading`` (at any ``#``
    level) up to the next heading of the same-or-higher level, a horizontal
    rule, or EOF. Used to scope an assertion to one subsection so a cross-ref in
    a *different* part of the file cannot satisfy it.
    """
    lines = text.splitlines()
    start: int | None = None
    level = 0
    for i, line in enumerate(lines):
        m = re.match(r"(#+)\s+(.*)$", line)
        if m and m.group(2).strip() == heading:
            start, level = i + 1, len(m.group(1))
            break
    assert start is not None, f"section heading not found: {heading!r}"
    body: list[str] = []
    for line in lines[start:]:
        m = re.match(r"(#+)\s+", line)
        if (m and len(m.group(1)) <= level) or line.strip() == "---":
            break
        body.append(line)
    return "\n".join(body)


def test_decision_mechanics_single_home() -> None:
    """AC-1a — spec-authoring owns the decision-recording rule; architecture points."""
    sa = _read("spec-authoring/SKILL.md")
    arch = _read("architecture/SKILL.md")

    # OWNER — spec-authoring states the rule and the supersede mechanic.
    assert "Decisions live in the spec they govern" in sa
    assert "`decisions/` folder" in sa
    assert re.search(r"supersed", sa, re.I)

    # architecture KEEPS its unique part: when a choice is decision-worthy.
    assert "decision-worthy" in arch

    # architecture POINTS to spec-authoring instead of restating the mechanics.
    assert "spec-authoring" in arch
    assert "## Where the decision lives" not in arch, (
        "architecture must not own a standalone decision-home section — that "
        "rule lives in spec-authoring now (CAL-718 / SYSTEM-4)."
    )
    assert "## Superseding a decision" not in arch, (
        "architecture must not own a standalone supersede section — point to "
        "spec-authoring (CAL-718 / SYSTEM-4)."
    )
    assert "update it in place" not in arch, (
        "architecture must not restate the supersede-in-place mechanic verbatim "
        "— spec-authoring owns it (CAL-718 / SYSTEM-4)."
    )


def test_smallest_change_and_rule_of_three_reference_owner() -> None:
    """AC-1b — engineering-principles owns the principles; code-quality references them."""
    ep = _read("engineering-principles/SKILL.md")
    cq = _read("code-quality/SKILL.md")

    # OWNER — engineering-principles states both principles.
    assert "Smallest change that satisfies the spec" in ep
    assert "No premature abstraction" in ep

    # code-quality references the owner from BOTH operational subsections, so
    # the principle has one home and a pointer from the application.
    smallest = _section(cq, "Smallest working solution")
    assert "engineering-principles" in smallest, (
        "code-quality's 'Smallest working solution' must point to "
        "engineering-principles (the owner of the smallest-change principle), "
        "not restate it uncross-referenced (CAL-718 / SYSTEM-4)."
    )
    third = _section(cq, "Extract on the third strike")
    assert "engineering-principles" in third, (
        "code-quality's 'Extract on the third strike' must point to "
        "engineering-principles (the owner of the rule of three) (CAL-718 / SYSTEM-4)."
    )


def test_lessons_tree_retired() -> None:
    """AC-2 — the engine-era lessons/ tree carries no tracked file."""
    assert tracked_files_under("lessons") == set(), (
        "engine-era lessons/ is retired (CAL-718 / SYSTEM-5): workflow YAML and "
        "captured run output from the retired engine, referenced by nothing "
        "live. No tracked file may remain under lessons/."
    )
