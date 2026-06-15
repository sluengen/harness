"""CAL-710 — ``engineering-principles`` carries the simplicity decision ladder.

Spawned from ``specs/proposals/borrow-from-ponytail.md`` (accepted 2026-06-15,
Option C). The proposal folds ponytail's "stop at the first rung that holds"
decision ladder into ``engineering-principles`` — the ordered *procedure* that
operationalises the simplicity *values* the skill already states (no premature
abstraction, smallest change, minimal dependencies), so "could this be simpler?"
is a reflex at the keystroke rather than a per-case judgement.

The load-bearing constraint — the reason the plugin itself was *not* installed —
is the scope guard: the ladder governs *what to build*, never *whether to test*
or *what the spec requires*. The added text says so and cross-references
``test-driven-development`` (test-first is untouched) and ``review-discipline``
Stage 1 (acceptance criteria are not self-descoped). This guard binds both into
the skill so a future re-edit cannot silently drop them.

A text-parse content guard in the style of ``test_review_discipline_port_orphan``
(CAL-665) and ``test_distributed_skill_cites`` (CAL-654): it reads the as-built
guidance and asserts the rule is present.

Acceptance criteria (this ticket):

* **AC-1** — ``engineering-principles`` contains the ordered ladder (all six
  rungs) and the reflex clause. Proven by
  :func:`test_ladder_has_six_rungs_and_reflex_clause`.
* **AC-2** — the text carries an explicit scope guard that the ladder never
  overrides test-first or spec compliance, cross-referencing
  ``test-driven-development`` and ``review-discipline``. Proven by
  :func:`test_ladder_scope_guard_cross_references_iron_laws`.
"""

from __future__ import annotations

from pathlib import Path

# ``tests/unit/test_*.py`` → ``parents[2]`` is the repo (or worktree) root.
_REPO_ROOT = Path(__file__).resolve().parents[2]
_SKILL = _REPO_ROOT / "skills" / "engineering-principles" / "SKILL.md"
_LADDER_HEADING = "## Before you write it"


def _skill_text() -> str:
    return _SKILL.read_text(encoding="utf-8")


def _ladder_section() -> str:
    """The decision-ladder subsection, isolated from the rest of the skill."""
    text = _skill_text()
    start = text.find(_LADDER_HEADING)
    assert start != -1, (
        "engineering-principles must carry a decision-ladder subsection "
        f"('{_LADDER_HEADING}') (CAL-710 AC-1)"
    )
    rest = text[start + len(_LADDER_HEADING) :]
    end = rest.find("\n## ")  # bounded by the next top-level section
    return rest if end == -1 else rest[:end]


def test_ladder_has_six_rungs_and_reflex_clause() -> None:
    """The ladder names all six ordered rungs and the reflex clause (AC-1)."""
    section = _ladder_section()
    lower = section.lower()
    # An ordered list of six rungs, numbered 1..6.
    for n in range(1, 7):
        assert f"{n}." in section, f"the ladder is missing ordered rung {n}"
    # The rungs, in order: exist-at-all (YAGNI) → stdlib → native platform →
    # already-installed dependency → one line → minimum code that works.
    rungs = [
        ("need", "rung 1 — does it need to exist at all (YAGNI)"),
        ("standard library", "rung 2 — the standard library"),
        ("native", "rung 3 — a native platform feature"),
        ("dependency", "rung 4 — an already-installed dependency"),
        ("one line", "rung 5 — can it be one line"),
        ("minimum", "rung 6 — the minimum code that works"),
    ]
    for needle, why in rungs:
        assert needle in lower, f"ladder missing {why}"
    # "stop at the first rung that holds" is the ladder's governing instruction.
    assert "first" in lower and "holds" in lower, (
        "the ladder must instruct stopping at the first rung that holds"
    )
    # The reflex clause: take the higher rung and move on; not a research project.
    assert "reflex" in lower and "research project" in lower, (
        "the ladder must carry the reflex clause (a reflex, not a research "
        "project) (CAL-710 AC-1)"
    )


def test_ladder_scope_guard_cross_references_iron_laws() -> None:
    """The scope guard names test-first + spec compliance as untouched (AC-2)."""
    section = _ladder_section()
    lower = section.lower()
    assert "scope guard" in lower, (
        "the ladder must carry an explicit scope guard (CAL-710 AC-2)"
    )
    # It cross-references both iron-law skills by name...
    assert "test-driven-development" in lower, (
        "the scope guard must cross-reference test-driven-development "
        "(test-first is unaffected)"
    )
    assert "review-discipline" in lower, (
        "the scope guard must cross-reference review-discipline Stage 1 "
        "(acceptance criteria are not self-descoped)"
    )
    # ...and states the ladder governs what to build, not testing or the spec.
    assert "build" in lower and ("test" in lower or "spec" in lower), (
        "the scope guard must state the ladder governs what to build, never "
        "whether to test or what the spec requires"
    )
