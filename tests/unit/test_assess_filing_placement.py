"""CAL-1168 — `/assess` step 2 files findings to a named state, not ad hoc.

`commands/assess.md` step 2 ("File the findings") never named the state an
`/assess` finding files into, so each run decided ad hoc. The operator decided
(2026-07-18, `specs/proposals/ticket-protocol-hygiene.md`): findings and
insights file to **Todo always**, with the Build project attached (project is
mandatory on this workspace) and severity-mapped priority — accepting that the
unattended loop becomes self-feeding, guarded by the assessment severity bar and
the merge-time review gate.

These are text-parse content guards in the style of
``test_assess_architecture_scope``: they pin the placement rule into the step-2
prose so a later re-edit cannot silently drop it.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
ASSESS = REPO_ROOT / "commands" / "assess.md"

#: The step whose placement rule this ticket pins.
STEP_HEADER = "### 2. File the findings"


def _step_two() -> str:
    """The body of the ``### 2. File the findings`` step, header to next ``### ``."""
    text = ASSESS.read_text()
    m = re.search(rf"^{re.escape(STEP_HEADER)}\b.*$", text, re.MULTILINE)
    assert m, f"missing step header {STEP_HEADER!r}"
    rest = text[m.end() :]
    end = re.search(r"^#{2,3} ", rest, re.MULTILINE)
    return rest[: end.start()] if end else rest


def test_step_two_names_todo_as_the_filing_state() -> None:
    """AC-1: step 2 names Todo as the state findings file into.

    Before this, the step named a label and a priority but no state, so an
    unattended run chose one by reasoning from the autoMode clause (the CAL-1144
    tick chose Backlog) — the gap this closes."""
    step = _step_two()
    assert "Todo" in step, (
        "step 2 must name Todo as the state findings file into — the operator "
        "decided findings file to Todo always (CAL-1168)."
    )


def test_step_two_names_the_mandatory_project() -> None:
    """AC-1: step 2 names the Build project attached (project is mandatory)."""
    step = _step_two()
    assert "project" in step.lower(), (
        "step 2 must name the Build project attached — a project is mandatory "
        "on this workspace when filing (CAL-1168)."
    )


def test_step_two_names_severity_mapped_priority() -> None:
    """AC-1: step 2 keeps severity-mapped priority alongside the new placement."""
    step = _step_two()
    assert "severity" in step.lower() and "priority" in step.lower(), (
        "step 2 must map severity to priority when filing (CAL-1168)."
    )
