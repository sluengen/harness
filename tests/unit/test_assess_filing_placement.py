"""CAL-1168 — `/assess` step 2 files findings to a named state, not ad hoc.

`commands/assess.md` step 2 ("File the findings") never named the state an
`/assess` finding files into, so each run decided ad hoc. The operator decided
(2026-07-18, `specs/proposals/ticket-protocol-hygiene.md`): findings file to
**Todo always**, with the Build project attached (project is mandatory on this
workspace) and severity-mapped priority — accepting that the unattended loop
becomes self-feeding, guarded by the assessment severity bar and the merge-time
review gate.

**What this module asserts, after #459.** One tripwire over the step-2 body: the
three parts of the filing instruction, plus the negation that makes the placement
a decision rather than a default. It also owns :func:`_step_two`, the step slicer
that ``test_assess_architecture_scope`` imports rather than re-spelling.

Three co-occurrence tests collapsed into it (ADR 0016). Occurrence the polarity
cites (``code-quality`` Part C): the step body already says *"Filing to Todo — not
Backlog — is deliberate"*, and **no assertion in this module read the negation**.
So the guard passed unchanged on the exact regression it was written for — a step
rewritten to file into Backlog still contains the word ``Todo`` (in the sentence
explaining why it does not), still names a project, still maps severity to
priority. The CAL-1144 tick that chose Backlog by reasoning from the autoMode
clause is the occurrence; a guard blind to the negation would not have seen it
come back. The ``craft.md`` class is *A guard over prose owns structure and
negative space, never meaning* — polarity half.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
ASSESS = REPO_ROOT / "commands" / "assess.md"

#: The step whose placement rule this ticket pins.
STEP_HEADER = "### 2. File the findings"

#: The three parts of the filing instruction. Words, not sentences: how the
#: instruction is phrased is the review gate's business.
_FILING_TERMS = ("todo", "project", "severity", "priority")

#: The placement, **anchored to the state it rejects**. This is the whole content
#: of the rule — Todo is chosen *over* Backlog, deliberately, because a finding is
#: confirmed work an unattended Build tick may pick up. A window naming Todo
#: without rejecting Backlog is satisfied by a step that files into Backlog and
#: mentions Todo in passing.
_NOT_BACKLOG = re.compile(
    r"\b(?:not|never|rather than|instead of)\b(?:\W+\w+){0,3}?\W+backlog\b",
    re.IGNORECASE,
)


def _step_two() -> str:
    """The body of the ``### 2. File the findings`` step, header to next ``### ``.

    Imported by ``test_assess_architecture_scope``, which reads a different
    paragraph of the same step. One slicer, so the two guards cannot disagree
    about where the step ends.
    """
    text = ASSESS.read_text()
    m = re.search(rf"^{re.escape(STEP_HEADER)}\b.*$", text, re.MULTILINE)
    assert m, f"missing step header {STEP_HEADER!r}"
    rest = text[m.end() :]
    end = re.search(r"^#{2,3} ", rest, re.MULTILINE)
    return rest[: end.start()] if end else rest


def _filing_paragraphs() -> list[str]:
    """Step-2 paragraphs stating where a finding is filed.

    The **paragraph**, not the step, and that is load-bearing rather than tidy.
    Step 2 also carries the architecture-scope rule, which ends *"they live in
    the report, not the backlog"* — a negation beside ``backlog`` about a
    different subject entirely. Read step-wide, :data:`_NOT_BACKLOG` matches that
    sentence, so an inverted placement rule ("Filing to Backlog — not Todo — is
    deliberate") stays green. Measured while authoring this conversion's mutation
    table (#459), before the table was ever run.
    """
    return [
        " ".join(block.split())
        for block in _step_two().split("\n\n")
        if "todo" in block.lower() and block.strip()
    ]


def test_step_two_files_to_todo_and_not_to_backlog() -> None:
    """The one tripwire: the filing instruction, and the placement it rejects.

    Three parts:

    * **anchor** — exactly one paragraph of ``### 2. File the findings`` names
      the state. ``_step_two`` asserts the header exists, so a rename names
      itself rather than emptying the window; the paragraph narrowing is what
      keeps a sibling rule's negation out of the polarity check.
    * **terms** — the state, the mandatory project, and the severity-to-priority
      mapping, all read from that one paragraph.
    * **polarity** — ``not Backlog``, anchored to the state it rejects. Without
      it the terms above are satisfied word for word by the inversion, which is
      the run this rule exists to stop repeating.
    """
    paragraphs = _filing_paragraphs()
    assert len(paragraphs) == 1, (
        f"step 2 has {len(paragraphs)} paragraphs naming the filing state; it must "
        "have exactly one. The state, the project and the priority are one "
        "instruction — split apart, nothing ties the placement to the filing "
        "(CAL-1168)."
    )
    step = paragraphs[0]
    lowered = step.lower()

    missing = [term for term in _FILING_TERMS if term not in lowered]
    assert not missing, (
        f"step 2's filing instruction no longer names {missing}. A finding files "
        "into a named state, with the repo's Build project attached (a project is "
        "mandatory when filing here) and its severity mapped to a priority "
        "(CAL-1168)."
    )

    assert _NOT_BACKLOG.search(step), (
        "step 2 names Todo but no longer rejects Backlog. The placement is the "
        "rule: a finding is confirmed work, so it goes where an unattended Build "
        "tick can pick it up without a human in between — and a step that files "
        "into Backlog while mentioning Todo satisfies every other check here "
        "(CAL-1168)."
    )
