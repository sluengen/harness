"""#267 — ``RELEASING.md`` documents the fragment mechanism it actually has.

Before #267 this module guarded a "Between-release CHANGELOG fold" section: a
two-pass procedure (condense bodies for bytes, collapse to one line for lines)
against a root file that every ticket appended to. #267 removed the
accumulation, so both passes describe a mechanism that no longer exists —
there is nothing to fold between releases because ``CHANGELOG.md`` no longer
grows between releases.

The guard moves with the doc rather than being deleted, because what made it
load-bearing is unchanged: a runbook that drifts from the gate sends an author
whose build just failed in the wrong direction, which is exactly what happened
on 2026-07-26 when the line ceiling tripped and the runbook had no procedure
for it.

Two mechanisms are kept verbatim from the retired version, and they are the
reason this guard cannot go stale:

* **The bound values are imported from the enforcing registry and formatted
  here**, never retyped — so re-baselining a ratchet fails this guard until the
  runbook is updated with it.
* **The bound set is derived** from ``scripts/cadence.py``'s ``BOUNDS`` rather
  than listed (``code-quality`` Part C, "a guard derives its subjects; it does
  not list them", #220) — so a bound added or renamed later fails here until the
  runbook names it. Since #350 that registry, not
  :mod:`tests.unit.test_changelog_rotation`, is where the cadence bounds live;
  what stays in the rotation module is the per-change window guard, whose
  failure message this file still pins.

These tests are the executable form of AC-6:

* **The section documents the write** — the fragment path, the heading grammar,
  and the closed category set.
* **The section documents the exemption** — the ``### None`` form, which is the
  only way past the presence gate for a change that warrants no entry.
* **The section documents the fold** — the invocation, at release rather than
  between releases.
* **The section documents the ratchet**, with both bounds and both tests named.
* **The release step owns the re-baseline** — the one place allowed to move a
  ratchet constant says so.

**Every content assertion is scoped to the section**, never to the whole file:
``changelog.d`` and ``CHANGELOG.md`` both appear elsewhere in ``RELEASING.md``
now, so an unscoped check would pass on the wrong prose.
"""

from __future__ import annotations

import inspect
import re
import sys
from pathlib import Path

from tests.unit import test_changelog_rotation as rotation

_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT / "scripts"))

import cadence  # noqa: E402

_RELEASING = _REPO_ROOT / "RELEASING.md"

#: The fragment section's H2 heading. Both ratchet tests name it verbatim in
#: their failure messages, so renaming it breaks those pointers too — the
#: slicer raises rather than falling back to the whole file.
_SECTION = "## Changelog fragments"

#: The release step that owns the deliberate re-baseline of the ratchet.
_RELEASE_SECTION = "## Release notes + the `staging → main` promotion"

#: The per-entry budget paragraph. Budget assertions are scoped to it, not to
#: the section: the section quotes byte figures in its ratchet table and its
#: prior art, so a section-wide "<n> bytes" search matches those and pins
#: nothing.
_BUDGET_PARAGRAPH = "**The per-entry budget.**"

#: A per-entry budget, written as a digits-and-unit claim. Matched by pattern so
#: the budget can be re-tuned without a test edit, while removing it altogether
#: still fails.
_BUDGET = re.compile(r"\*\*[\d,]{3,} bytes[^*]*\*\*")


def _section(heading: str) -> str:
    """A section's body, to the next H2 heading."""
    text = _RELEASING.read_text(encoding="utf-8")
    start = text.find(f"\n{heading}")
    assert start != -1, (
        f"RELEASING.md has no '{heading}' section. It is the documented home of "
        "the changelog fragment mechanism, and tests/unit/"
        "test_changelog_rotation.py names it verbatim in the failure messages of "
        "both ratchet tests — rename them together or not at all."
    )
    rest = text[start + 1 :]
    nxt = re.search(r"^## ", rest[len(heading) :], re.MULTILINE)
    return rest if nxt is None else rest[: len(heading) + nxt.start()]


def _fold_section() -> str:
    return _section(_SECTION)


def _paragraph(lead: str) -> str:
    """The single paragraph of the fragment section opening with ``lead``."""
    section = _fold_section()
    start = section.find(lead)
    assert start != -1, (
        f"RELEASING.md '{_SECTION}' has no paragraph opening with {lead!r}."
    )
    end = section.find("\n\n", start)
    return section[start:] if end == -1 else section[start:end]


def _cadence_bounds() -> tuple[cadence.CadenceBound, ...]:
    """Every registered cadence bound — the subjects the runbook must name.

    Derived from the registry rather than listed here, so a bound added later
    fails this guard until the runbook documents how to clear it (#350 moved the
    bounds out of ``tests.unit.test_changelog_rotation`` into that registry).
    """
    return cadence.BOUNDS


# ---------------------------------------------------------------------------
# The section documents the fragment write.
# ---------------------------------------------------------------------------


def test_section_documents_the_fragment_path() -> None:
    """The path an author must create, in its placeholder form."""
    section = _fold_section()
    assert "`changelog.d/<ticket>.md`" in section, (
        f"RELEASING.md '{_SECTION}' must name the fragment path as "
        "`changelog.d/<ticket>.md`. It is the one thing an author needs from "
        "this section, and the presence gate's failure message names the same "
        "shape."
    )


def test_section_documents_the_heading_grammar_and_categories() -> None:
    """The closed category set, derived from the script that enforces it."""
    import sys

    sys.path.insert(0, str(_REPO_ROOT / "scripts"))
    import changelog_fragments as cf

    section = _fold_section()
    missing = [c for c in cf.CATEGORIES if f"`{c}`" not in section]
    assert not missing, (
        f"RELEASING.md '{_SECTION}' does not name these categories: {missing}. "
        "The set is closed — `check` rejects anything outside it — so an author "
        "who cannot see the whole set from the runbook will guess and fail the "
        "gate."
    )


def test_section_states_the_filename_is_the_key() -> None:
    """Why a resumed run cannot duplicate an entry."""
    section = _fold_section()
    assert "primary key" in section and "overwrites" in section, (
        f"RELEASING.md '{_SECTION}' must say the filename is the primary key and "
        "that a resumed run overwrites rather than duplicating. Without it, an "
        "author resuming a build looks for a de-duplication step that does not "
        "exist."
    )


# ---------------------------------------------------------------------------
# The section documents the exemption — the only way past the presence gate.
# ---------------------------------------------------------------------------


def test_section_documents_the_exemption_form() -> None:
    section = _fold_section()
    assert "### None — " in section, (
        f"RELEASING.md '{_SECTION}' must give the exemption form verbatim "
        "('### None — <why> (#<ticket>)'). A change that genuinely warrants no "
        "entry has no other way past the presence gate, and an author who cannot "
        "find it will fake an entry instead."
    )
    assert "reviewer" in section, (
        f"RELEASING.md '{_SECTION}' must say why the exemption is a file in the "
        "diff rather than a flag: so a reviewer sees the claim and can disagree "
        "with it. Without the reason it reads as a formality to satisfy."
    )


def test_section_documents_the_no_ticket_exemption_form() -> None:
    """#287 — the ticket-less class needs a documented filename, not a workaround.

    The prefix is read from the module rather than typed here, so renaming it
    fails this test instead of leaving the runbook quietly describing a form
    the guard no longer accepts.
    """
    import sys

    sys.path.insert(0, str(_REPO_ROOT / "scripts"))
    import changelog_fragments as cf

    section = _fold_section()
    assert f"{cf.NO_TICKET_PREFIX}<slug>" in section, (
        f"RELEASING.md '{_SECTION}' must give the ticket-less form verbatim "
        f"('{cf.NO_TICKET_PREFIX}<slug>.md'). It is the only honest way past the "
        "gate for an /assess report or a /propose output, and an author who "
        "cannot find it will borrow someone else's ticket number instead."
    )
    assert "may carry **only**" in section and f"### {cf.NONE_CATEGORY}" in section, (
        f"RELEASING.md '{_SECTION}' must state the None-only rule — it is what "
        "keeps the class out of released history, so an author who writes a "
        "releasable entry on a no-ticket stem learns why it is refused."
    )


# ---------------------------------------------------------------------------
# The section documents the fold, and the release step owns the re-baseline.
# ---------------------------------------------------------------------------


def test_section_states_the_fold_is_a_release_step() -> None:
    """There is no between-release fold any more — the doc must say so."""
    section = _fold_section()
    assert "at release, not between releases" in section, (
        f"RELEASING.md '{_SECTION}' must state that the fold happens at release "
        "rather than between releases. The retired two-pass procedure ran on "
        "nine consecutive Build ticks; an author who still believes in it will "
        "go looking for a fold to run when the ratchet trips, and the fix is to "
        "write a fragment instead."
    )


def test_release_step_names_the_fold_invocation() -> None:
    """The release checklist carries the command, not a description of it."""
    release = _section(_RELEASE_SECTION)
    assert "scripts/changelog_fragments.py fold" in release, (
        f"RELEASING.md '{_RELEASE_SECTION}' must name the fold invocation. The "
        "fold is the step that turns fragments into released history; a "
        "checklist that only describes it leaves the operator to reconstruct "
        "the command."
    )


def test_release_step_owns_the_ratchet_rebaseline() -> None:
    """Exactly one place may move a cadence constant, and it says so."""
    release = _section(_RELEASE_SECTION)
    assert "scripts/cadence.py" in release, (
        f"RELEASING.md '{_RELEASE_SECTION}' must name scripts/cadence.py, which "
        "holds the ratchet constants since #350. The fold is the one step "
        "allowed to move them, so the instruction to re-baseline belongs with "
        "it — otherwise the next release trips a check with no documented way "
        "through."
    )


def test_release_step_verifies_cadence_before_promoting() -> None:
    """The fold's own work is verified before the promotion is driven.

    The cadence bounds no longer fail the gate (#350), so the release step is
    where an unfolded window must be caught. Without this, a release could be
    driven with the window still over the bound and nothing would object.
    """
    release = _section(_RELEASE_SECTION)
    assert "scripts/cadence.py check" in release, (
        f"RELEASING.md '{_RELEASE_SECTION}' must run `scripts/cadence.py check` "
        "after the fold and before driving the promotion. `report` never fails, "
        "so naming it here would verify nothing."
    )


# ---------------------------------------------------------------------------
# The cadence bounds — values imported from the registry, subjects derived.
# ---------------------------------------------------------------------------


def test_section_names_every_cadence_bound_with_its_current_value() -> None:
    """The section carries every bound's current value, formatted from the registry.

    The subject set is derived, not listed, so a bound added to ``cadence.BOUNDS``
    later fails this guard until the runbook tells an author how to clear it.
    """
    bounds = _cadence_bounds()
    assert len(bounds) >= 3, (
        "Derived fewer than 3 cadence bounds from scripts/cadence.py — the "
        f"registry read {[b.name for b in bounds]}. A short or empty subject set "
        "makes the loop below pass trivially; fix the derivation rather than the "
        "expectation."
    )
    section = _fold_section()
    for entry in bounds:
        value = f"{entry.bound:,} {entry.unit}"
        assert value in section, (
            f"RELEASING.md '{_SECTION}' does not name the {entry.name} bound "
            f"({value}). The section must state every bound scripts/cadence.py "
            "enforces, in the unit-qualified comma form — an author whose "
            "release check just failed needs to know which ceiling they are "
            "against, and a bare digit could be any figure the prose quotes."
        )


def test_section_names_the_enforcing_script_not_the_gate() -> None:
    """The runbook points at the release-path check, not at the gate.

    The regression: prose that still tells an author their *gate* enforces these
    bounds sends them to fix the wrong thing, and invites the next person to put
    the bound back in the gate.
    """
    section = _fold_section()
    assert "scripts/cadence.py" in section, (
        f"RELEASING.md '{_SECTION}' must name scripts/cadence.py as the home of "
        "the cadence bounds (#350)."
    )
    missing = [entry.name for entry in _cadence_bounds() if entry.name not in section]
    assert not missing, (
        f"RELEASING.md '{_SECTION}' does not name these cadence bounds: {missing}. "
        "Each bound must be named alongside the check that enforces it, so a "
        "failure message leads straight to its procedure."
    )


def test_section_explains_why_there_are_two_guards() -> None:
    """The pair is deliberate — neither guard subsumes the other."""
    section = _fold_section()
    assert "abstain" in section, (
        f"RELEASING.md '{_SECTION}' must say that the presence check abstains "
        "where the base cannot resolve. A reader who does not know that will "
        "read a passing gate as proof the fragment was checked."
    )
    assert "Neither subsumes the other" in section, (
        f"RELEASING.md '{_SECTION}' must state why both the presence check and "
        "the ratchet exist: one is direct but base-dependent, the other "
        "base-independent but indirect. Without the reason, the next author to "
        "find them redundant deletes the one their environment does not exercise."
    )


def test_section_gives_the_measurement_commands() -> None:
    """Both readings, so an author can see where the file sits."""
    section = _fold_section()
    for command in ("wc -c CHANGELOG.md", "wc -l CHANGELOG.md"):
        assert command in section, (
            f"RELEASING.md '{_SECTION}' does not tell the author how to take the "
            f"`{command}` reading. Bytes and lines ratchet independently, so a "
            "single reading cannot tell them which one tripped."
        )


# ---------------------------------------------------------------------------
# The per-entry budget survives the move — it was always the upstream driver.
# ---------------------------------------------------------------------------


def test_section_sets_a_per_entry_budget() -> None:
    """The section names entry length as the driver and states a budget."""
    paragraph = _paragraph(_BUDGET_PARAGRAPH)
    assert "length" in paragraph, (
        f"RELEASING.md '{_SECTION}' must name entry length as the upstream "
        "driver in its budget paragraph. The retired fold fired on nine "
        "consecutive ticks without buying durable headroom because entries kept "
        "growing; a budget that does not say what it is budgeting explains "
        "nothing, and fragments inherit the problem unchanged."
    )
    assert _BUDGET.search(paragraph), (
        f"RELEASING.md '{_SECTION}' states no numeric per-entry budget in its "
        f"budget paragraph (an emphasised '<n> bytes …' claim matching "
        f"{_BUDGET.pattern}). An expectation an author cannot measure against is "
        "not an expectation — and the byte figures elsewhere in the section are "
        "the ratchet table and prior art, not a budget."
    )


# ---------------------------------------------------------------------------
# The failing gate points at the procedure that clears it.
# ---------------------------------------------------------------------------


def test_gate_guard_failure_message_points_at_the_fragment_section() -> None:
    """The per-change guard names the section that tells an author what to do.

    Its predecessors' messages prescribed the two-pass fold — the procedure #267
    retired. A gate that trips must send the author to the mechanism that
    actually exists, or it sends them to rewrite a file they should not touch.
    """
    source = inspect.getsource(rotation.test_unreleased_window_carries_no_new_entries)
    assert "Changelog fragments" in source, (
        "test_unreleased_window_carries_no_new_entries' failure message must "
        "name RELEASING.md's 'Changelog fragments' section. Folding cannot clear "
        "this bound — since #267 the way past it is to write a fragment instead "
        "of editing CHANGELOG.md."
    )
    assert "changelog.d" in source or "_FRAGMENT_DIRNAME" in source, (
        "its failure message must name the fragment directory, so the fix is a "
        "path away rather than a doc search. Either the literal or the "
        "interpolated _FRAGMENT_DIRNAME constant satisfies this — the constant "
        "is the better form, since it single-sources the directory name with "
        "the enumeration that reads it."
    )


def test_every_cadence_remedy_points_at_the_release_procedure() -> None:
    """A cadence breach names the procedure that clears it, not just the number.

    The bounds moved off the gate (#350), so their message is now the *only*
    thing an author sees — a bare "41/40" with no remedy would leave them to
    guess, or worse, to raise the bound.
    """
    remedyless = [
        entry.name for entry in _cadence_bounds() if "RELEASING.md" not in entry.remedy
    ]
    assert not remedyless, (
        f"these cadence bounds' remedies do not name RELEASING.md: {remedyless}. "
        "A breach must lead straight to the procedure that clears it."
    )
