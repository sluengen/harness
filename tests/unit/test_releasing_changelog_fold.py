"""#223 — the between-release fold procedure clears whichever ceiling tripped.

``RELEASING.md``'s "Between-release CHANGELOG fold" was written entirely against
the **byte** gate: it cited the 60,000-byte hard bound and the ~48,000-byte soft
warning, and prescribed condensing older entries' bodies. But
:mod:`tests.unit.test_changelog_rotation` enforces **two** ceilings, and the
prescribed fold is close to a no-op against the second — a condensed entry is
still heading + bullet + blank, three lines, exactly what it occupied before.

That played out on 2026-07-26: a four-entry fold took the file 47,674 → 42,825
bytes, then two new entries tripped ``test_root_changelog_is_line_bounded`` at
251 lines against 250 while bytes were still comfortable. The gate named the
right ceiling; the runbook had no procedure for it, so the fix — collapsing the
oldest entries' heading and summary onto one line, 251 → 174 — was invented
mid-run and landed as ``c907faf``.

These tests are the executable form of the acceptance criteria:

* **AC-1 — both bounds named, with values read from the test.** The ceiling
  constants are *imported* from :mod:`tests.unit.test_changelog_rotation` and
  formatted here, never retyped, so changing a bound fails this guard rather
  than silently staling the runbook. The set of ceiling tests the section must
  name is **derived** by introspecting that module for ``test_root_changelog_*``
  rather than listed (``code-quality`` Part C, "a guard derives its subjects; it
  does not list them", #220) — a fourth ceiling test added later fails here
  until the runbook documents it.
* **AC-2 — which fold relieves which ceiling.** Body condensation is stated to
  relieve bytes only; the one-line collapse is prescribed for the line ceiling,
  with ``c907faf`` cited as prior art alongside ``208118e``.
* **AC-3 — a way to tell which fold is needed.** Both ``wc`` readings are taken
  before folding.
* **AC-4 — entry length named as the upstream driver**, with a per-entry budget.
* **AC-5 — this module is the guard**, mirroring
  :mod:`tests.unit.test_release_docs_currency`, the nearest doc-currency guard.

**Every content assertion is scoped to the fold section**, never to the whole
file: "byte", "60,000" and "ceiling" all appear elsewhere in ``RELEASING.md``,
so an unscoped check would pass on the wrong prose. And every assertion is
anchored on the step *bodies* rather than their bold titles — a bullet's own
title is a sibling of its body, so a title-satisfiable assertion pins nothing
(the failure mode #221 found by mutation-checking).
"""

from __future__ import annotations

import inspect
import re
from pathlib import Path

from tests.unit import test_changelog_rotation as rotation

_REPO_ROOT = Path(__file__).resolve().parents[2]
_RELEASING = _REPO_ROOT / "RELEASING.md"

#: The fold section's H2 heading. ``test_root_changelog_soft_warning_threshold``
#: already points authors here by this exact name, so renaming it breaks that
#: pointer too — the slicer raises rather than falling back to the whole file.
_SECTION = "## Between-release CHANGELOG fold"

#: The paragraph stating the per-entry budget. Assertions about the budget are
#: scoped to it, not to the section: the section quotes byte figures in its
#: prior art and in its driver evidence, so a section-wide "<n> bytes" search
#: matches those and pins nothing.
_BUDGET_PARAGRAPH = "**The per-entry budget.**"

#: A per-entry budget, written as a digits-and-unit claim. Matched by pattern
#: rather than by literal so the budget can be re-tuned without a test edit,
#: while removing it altogether still fails.
_BUDGET = re.compile(r"\*\*[\d,]{3,} bytes[^*]*\*\*")


def _fold_section() -> str:
    """The fold section's body, to the next H2 heading."""
    text = _RELEASING.read_text(encoding="utf-8")
    start = text.find(f"\n{_SECTION}")
    assert start != -1, (
        f"RELEASING.md has no '{_SECTION}' section. It is the documented home of "
        "the between-release fold, and test_root_changelog_soft_warning_threshold "
        "names it verbatim in its failure message — rename both together or not "
        "at all."
    )
    rest = text[start + 1 :]
    nxt = re.search(r"^## ", rest[len(_SECTION) :], re.MULTILINE)
    return rest if nxt is None else rest[: len(_SECTION) + nxt.start()]


def _paragraph(lead: str) -> str:
    """The single paragraph of the fold section opening with ``lead``."""
    section = _fold_section()
    start = section.find(lead)
    assert start != -1, (
        f"RELEASING.md '{_SECTION}' has no paragraph opening with {lead!r}."
    )
    end = section.find("\n\n", start)
    return section[start:] if end == -1 else section[start:end]


def _ceiling_tests() -> list[str]:
    """Every ``test_root_changelog_*`` test — the ceilings the fold must clear.

    Derived from the rotation module rather than listed here, so a ceiling
    added later fails this guard until the runbook documents it.
    """
    return sorted(
        name
        for name, obj in vars(rotation).items()
        if name.startswith("test_root_changelog_") and inspect.isfunction(obj)
    )


# ---------------------------------------------------------------------------
# AC-1 — both bounds named, values single-sourced from the enforcing test.
# ---------------------------------------------------------------------------


def test_fold_names_both_ceilings_with_current_values() -> None:
    """The section carries every bound's current value, formatted from the test."""
    section = _fold_section()
    for label, value in (
        ("hard byte gate", f"{rotation._ROOT_BYTE_BOUND:,}-byte"),
        ("line ceiling", f"{rotation._ROOT_LINE_BOUND}-line"),
        ("soft byte warning", f"{rotation._ROOT_SOFT_WARNING_BOUND:,}-byte"),
    ):
        assert value in section, (
            f"RELEASING.md '{_SECTION}' does not name the {label} ({value}). The "
            "fold procedure must state every bound tests/unit/"
            "test_changelog_rotation.py enforces, in the unit-qualified comma "
            "form — an author whose gate just tripped needs to know which "
            "ceiling they are folding against, and a bare digit could be any "
            "figure the prose happens to quote."
        )


def test_fold_names_every_ceiling_test() -> None:
    """Each ``test_root_changelog_*`` test is named in the section.

    The subject set is derived, not listed, so adding a fourth ceiling test
    fails here until the runbook tells an author how to clear it.
    """
    names = _ceiling_tests()
    assert len(names) >= 2, (
        "Derived no ceiling tests from tests.unit.test_changelog_rotation — the "
        f"introspection found {names}. An empty subject set makes the loop below "
        "pass trivially; fix the derivation rather than the expectation."
    )
    section = _fold_section()
    missing = [name for name in names if name not in section]
    assert not missing, (
        f"RELEASING.md '{_SECTION}' does not name these ceiling tests: {missing}. "
        "Each bound the gate enforces must be named alongside the test that "
        "enforces it, so a failure message leads straight to its procedure."
    )


# ---------------------------------------------------------------------------
# AC-2 — which fold relieves which ceiling.
# ---------------------------------------------------------------------------


def test_fold_states_the_body_condensation_relieves_bytes_only() -> None:
    """The first pass is stated to buy bytes and no lines, in the step's body.

    The claim must survive deleting the step's bold title: "bytes" appears in
    the section's opening paragraph, so a bare substring check would pin
    nothing.
    """
    section = _fold_section()
    assert "three lines, exactly what it occupied before" in section, (
        f"RELEASING.md '{_SECTION}' must say in the first pass's body why "
        "condensing an entry buys no lines — a condensed entry is still a "
        "heading, a bullet and a blank line, three lines, exactly what it "
        "occupied before. Without the reason, an author reads the pass as a "
        "general-purpose fold and reruns it against a line failure it cannot fix."
    )


def test_fold_prescribes_the_one_line_collapse_for_the_line_ceiling() -> None:
    """The second pass — the only fold that relieves lines — has a procedure."""
    section = _fold_section()
    for fragment in ("### Earlier still — one line each", "one line per entry"):
        assert fragment in section, (
            f"RELEASING.md '{_SECTION}' is missing the second-pass collapse "
            f"({fragment!r}). Clearing the {rotation._ROOT_LINE_BOUND}-line "
            "ceiling requires collapsing an entry's heading and summary onto a "
            "single line; nothing else moves the line count."
        )


def test_fold_cites_the_second_pass_prior_art() -> None:
    """Both passes cite a landed commit, the way ``208118e`` is cited today."""
    section = _fold_section()
    for sha, pass_name in (
        ("208118e", "first-pass byte fold"),
        ("c907faf", "second-pass line collapse"),
    ):
        assert sha in section, (
            f"RELEASING.md '{_SECTION}' does not cite {sha}, the {pass_name} this "
            "procedure gives a durable home. Prior art is how an author sees the "
            "shape of the edit before making it."
        )


# ---------------------------------------------------------------------------
# AC-3 — measure first, so the fold matches the ceiling that actually tripped.
# ---------------------------------------------------------------------------


def test_fold_gives_a_measurement_step() -> None:
    """Both readings are taken before folding — the two ceilings move apart."""
    section = _fold_section()
    for command in ("wc -c CHANGELOG.md", "wc -l CHANGELOG.md"):
        assert command in section, (
            f"RELEASING.md '{_SECTION}' does not tell the author to run "
            f"`{command}` before folding. Bytes and lines move independently, so "
            "the reading decides which pass to run; without both, the author "
            "guesses."
        )


# ---------------------------------------------------------------------------
# AC-4 — entry length is the upstream driver, with a stated budget.
# ---------------------------------------------------------------------------


def test_fold_sets_a_per_entry_budget() -> None:
    """The section names entry length as the driver and states a budget."""
    paragraph = _paragraph(_BUDGET_PARAGRAPH)
    assert "length" in paragraph, (
        f"RELEASING.md '{_SECTION}' must name entry length as the upstream "
        "driver in its budget paragraph. The fold fired on nine consecutive "
        "ticks without buying durable headroom because entries kept growing; "
        "a budget that does not say what it is budgeting explains nothing."
    )
    assert _BUDGET.search(paragraph), (
        f"RELEASING.md '{_SECTION}' states no numeric per-entry budget in its "
        f"budget paragraph (an emphasised '<n> bytes …' claim matching "
        f"{_BUDGET.pattern}). An expectation an author cannot measure against "
        "is not an expectation — and the byte figures elsewhere in the section "
        "are prior art and evidence, not a budget."
    )


# ---------------------------------------------------------------------------
# The failing gate points at the procedure that clears it.
# ---------------------------------------------------------------------------


def test_line_bounded_failure_message_points_at_the_fold() -> None:
    """``test_root_changelog_is_line_bounded`` names the fold section.

    Its message used to say "rotate released entries to the archive" — the one
    action the fold section explicitly forbids between releases, since nothing
    in ``[Unreleased]`` has shipped. Its byte-side sibling
    ``test_root_changelog_soft_warning_threshold`` already points at the fold;
    the line ceiling must too, or the gate that trips sends the author the
    wrong way.
    """
    source = inspect.getsource(rotation.test_root_changelog_is_line_bounded)
    assert "Between-release CHANGELOG fold" in source, (
        "test_root_changelog_is_line_bounded's failure message must name "
        "RELEASING.md's 'Between-release CHANGELOG fold' section, the way "
        "test_root_changelog_soft_warning_threshold's already does. Rotation "
        "cannot clear this ceiling between releases — unreleased entries have "
        "not shipped."
    )
