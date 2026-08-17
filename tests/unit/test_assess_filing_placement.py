"""CAL-1168 — `/assess` step 2 files findings to a named state, not ad hoc.

`commands/assess.md` step 2 ("File the findings") never named the state an
`/assess` finding files into, so each run decided ad hoc. The operator decided
(2026-07-18, `specs/proposals/ticket-protocol-hygiene.md`): findings file to
**Todo always**, with the Build project attached (project is mandatory on this
workspace) — accepting that the unattended loop becomes self-feeding, guarded by
the assessment's filing-time bar and the merge-time review gate.

**What this module asserts, after #459.** One tripwire over the step-2 body: the
three parts of the filing instruction, plus the negation that makes the placement
a decision rather than a default. The step slicer this module and
``test_assess_architecture_scope`` both read, :func:`tests.unit._prose.assess_step_two`,
lives in the shared home since #467 rather than in either of them.

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

from tests.unit._prose import assess_step_two

#: The two surviving parts of the filing instruction. Words, not sentences: how
#: the instruction is phrased is the review gate's business.
_FILING_TERMS = ("todo", "project")

#: The parts #448 retired, kept here **as the inverse of the same assertion**
#: rather than deleted. The severity→priority mapping was the third and fourth
#: term above until the Critical/High/Medium/Low scale went (ADR 0015, #455), and
#: a retired requirement whose test is simply removed leaves the step free to
#: grow it back with nothing red — the `craft.md` remedy for a retired predicate
#: is to turn it around, not to drop it. So the same paragraph that must name the
#: state and the project must now *not* name these.
_RETIRED_FILING_TERMS = ("severity", "priority")

#: The placement, **anchored to the state it rejects**. This is the whole content
#: of the rule — Todo is chosen *over* Backlog, deliberately, because a finding is
#: confirmed work an unattended Build tick may pick up. A window naming Todo
#: without rejecting Backlog is satisfied by a step that files into Backlog and
#: mentions Todo in passing.
_NOT_BACKLOG = re.compile(
    r"\b(?:not|never|rather than|instead of)\b(?:\W+\w+){0,3}?\W+backlog\b",
    re.IGNORECASE,
)


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
        for block in assess_step_two().split("\n\n")
        if "todo" in block.lower() and block.strip()
    ]


def test_step_two_files_to_todo_and_not_to_backlog() -> None:
    """The one tripwire: the filing instruction, and the placement it rejects.

    Three parts:

    * **anchor** — exactly one paragraph of ``### 2. File the findings`` names
      the state. ``assess_step_two`` asserts the header exists, so a rename names
      itself rather than emptying the window; the paragraph narrowing is what
      keeps a sibling rule's negation out of the polarity check.
    * **terms** — the state and the mandatory project, read from that one
      paragraph, and — the same assertion inverted — the retired
      severity-to-priority mapping absent from it.
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
        "mandatory when filing here) (CAL-1168)."
    )

    returned = [term for term in _RETIRED_FILING_TERMS if term in lowered]
    assert not returned, (
        f"step 2's filing instruction names {returned} again. The severity scale "
        "is retired for the blocking×size 2×2, so a finding no longer carries a "
        "grade to map onto a priority — placing one there would send the filer "
        "back to a vocabulary `review-discipline` no longer defines (#455)."
    )

    assert _NOT_BACKLOG.search(step), (
        "step 2 names Todo but no longer rejects Backlog. The placement is the "
        "rule: a finding is confirmed work, so it goes where an unattended Build "
        "tick can pick it up without a human in between — and a step that files "
        "into Backlog while mentioning Todo satisfies every other check here "
        "(CAL-1168)."
    )
