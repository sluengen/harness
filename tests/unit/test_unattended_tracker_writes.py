"""CAL-1087 — versioned guidance never instructs a tracker write the unattended
runner cannot make.

*Source:* CAL-1087 (Bug, ``review-insight``). Found by the unattended Build
routine on 2026-07-15, which hit the wall itself.

``work-discovery@0.1.0`` told the routine, on a not-yet-actionable ticket, to
"leave a comment on the ticket naming what it needs, label it ``decision``";
``/harness routine build`` step 2 repeated it; ``/assess`` step 2 said "create a
Linear issue" for every finding. **An unattended run can do none of this** — the
host's auto-mode classifier refuses every Linear write, because an autonomous
agent writing to an external system with no human naming the write is exactly
what it should stop. The block is correct; the guidance's assumption about it
was wrong, and it said nothing about what to do instead.

The failure was silent and self-perpetuating: on 2026-07-15 the routine judged
CAL-1082 not-actionable, could not apply the ``decision`` label, and so could
not remove it from the queue — with the deferral recorded nowhere a human would
look.

**The contract chosen (CAL-1087 design decision).** The condition is not "does
this repo have a tracker" but **"is the tracker available to *this run*"**, which
has two causes — the repo has none (``layers.linear: false``, static) or the run
is unattended (dynamic). Both collapse to the **one fallback ``/assess`` already
models**: surface it in the run's report; the report is the durable record. No
new mechanism, no state outside the tracker.

Re-picking a deferred ticket is **accepted, not engineered away** (AC-1's
explicit escape hatch): the judgment is cheap and re-derived from current data
each tick, the tick continues to the next candidate or the quality arm rather
than being burned, and — unlike a committed deferral note — no stale local state
can park a ticket a human has since fixed. The ``decision`` label survives as
something an *attended* actor applies; *reading* it needs no write, so the skip
rule is untouched.

Acceptance criteria (CAL-1087):

* **AC-1** — ``work-discovery`` states what an unattended runner does when it
  cannot write to the tracker, and explains why re-picking is acceptable. Proven
  by :func:`test_work_discovery_names_the_unattended_fallback`,
  :func:`test_work_discovery_explains_why_repicking_is_acceptable`, and
  :func:`test_work_discovery_deferral_instructs_no_tracker_write`.
* **AC-2** — ``/assess``'s filing step states the unattended fallback,
  consistent with its existing "no tracker" branch. Proven by
  :func:`test_assess_filing_names_the_unattended_fallback`.
* **AC-3** — ``/harness routine build`` step 2 no longer instructs a write the
  runner cannot make. Proven by
  :func:`test_build_routine_defers_without_a_tracker_write`.
* **AC-4** — a guard pins the contract so the gap cannot silently reopen. This
  module, with its detector boundary pinned by
  :func:`test_detector_flags_a_write_imperative` /
  :func:`test_detector_ignores_prose_about_the_label`.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent.parent
SKILL = REPO_ROOT / "skills" / "work-discovery" / "SKILL.md"
HARNESS_COMMAND = REPO_ROOT / "commands" / "harness.md"
ASSESS_COMMAND = REPO_ROOT / "commands" / "assess.md"


def _section(text: str, heading_substr: str) -> str:
    """The body of the heading line containing ``heading_substr`` up to the next
    heading of the same-or-higher level (mirrors ``test_work_discovery_skill``)."""
    lines = text.splitlines()
    start = None
    level = 0
    for i, line in enumerate(lines):
        if line.startswith("#") and heading_substr in line:
            start = i
            level = len(line) - len(line.lstrip("#"))
            break
    if start is None:
        return ""
    body = [lines[start]]
    for line in lines[start + 1 :]:
        if line.startswith("#") and len(line) - len(line.lstrip("#")) <= level:
            break
        body.append(line)
    return "\n".join(body)


#: Imperatives that direct the *reader of the step* to mutate the tracker. These
#: are the phrasings an unattended runner cannot execute. The set is deliberately
#: narrow — it matches an instruction ("leave a comment", "label it"), not prose
#: *about* the tracker ("a human applies the `decision` label"), so the guard
#: pins the contract without banning the vocabulary.
_WRITE_IMPERATIVES = (
    r"leave a comment",
    r"add a comment",
    r"post a comment",
    r"label it\b",
    r"create a linear issue",
)


def _write_imperatives(text: str) -> list[str]:
    """Every tracker-write imperative *text* directs at its reader."""
    low = text.lower()
    return [p for p in _WRITE_IMPERATIVES if re.search(p, low)]


# --- detector boundary (keeps the guard honest / non-vacuous) ------------------


def test_detector_flags_a_write_imperative() -> None:
    """The detector fires on the exact instruction CAL-1087 removes — the
    ``work-discovery@0.1.0`` deferral step the unattended runner could not run."""
    assert _write_imperatives(
        "Leave a comment on the ticket naming what it needs, label it `decision`, "
        "and move on to the next candidate."
    ) == ["leave a comment", "label it\\b"]
    assert _write_imperatives("For every finding, create a Linear issue (`linear`)")


def test_detector_ignores_prose_about_the_label() -> None:
    """The detector does not fire on prose that *describes* the tracker without
    instructing the runner to write to it — the `decision` label survives as a
    thing an attended actor applies and the runner reads."""
    assert not _write_imperatives(
        "A ticket carrying the `decision` label was judged not-yet-actionable on "
        "an earlier pass and is waiting on a human. Skip it."
    )
    assert not _write_imperatives(
        "Surface the deferral in the run's report, naming the ticket and what it "
        "needs, and move on to the next candidate."
    )
    assert not _write_imperatives(
        "An attended run can apply the `decision` label; an unattended one cannot."
    )


# --- AC-1: work-discovery states the unattended path --------------------------


def test_work_discovery_deferral_instructs_no_tracker_write() -> None:
    """AC-1/AC-4 (core): the skill's actionability step does not instruct a
    tracker write. The skill's whole audience is the unattended runner (its own
    frontmatter: "when an unattended routine must pick its own next ticket"), so
    an instruction it cannot execute is not a branch — it is simply wrong."""
    body = _section(SKILL.read_text(), "Actionability")
    found = _write_imperatives(body)
    assert not found, (
        "work-discovery's actionability step instructs a tracker write "
        f"({found}) that the unattended runner it serves cannot make — the "
        "host's classifier refuses every autonomous Linear write. State the "
        "surface-and-report path instead (CAL-1087 AC-1)."
    )


def test_work_discovery_names_the_unattended_fallback() -> None:
    """AC-1: the skill says what the runner does *instead* — it cannot write to
    the tracker, so it surfaces the deferral in the run's report and moves on."""
    body = _section(SKILL.read_text(), "Actionability")
    low = body.lower()
    assert "unattended" in low, (
        "work-discovery's actionability step must name the unattended run — the "
        "condition under which the tracker is unavailable to the runner "
        "(CAL-1087 AC-1)."
    )
    assert re.search(r"report|surface", low), (
        "work-discovery must state the fallback: surface the deferral in the "
        "run's report, which is the durable record (CAL-1087 AC-1)."
    )


def test_work_discovery_explains_why_repicking_is_acceptable() -> None:
    """AC-1: the skill discharges the AC's explicit escape hatch — the deferral
    path does not remove the ticket from the next tick's candidate set, so the
    skill must say *why* re-picking is acceptable rather than leave the
    self-perpetuating loop unexplained."""
    body = _section(SKILL.read_text(), "Actionability")
    low = body.lower()
    assert re.search(r"re-pick|repick|next tick|each tick", low), (
        "work-discovery must address what happens on the next tick — an "
        "unattended deferral leaves the ticket in the candidate set (CAL-1087 "
        "AC-1)."
    )
    assert re.search(r"cheap|seconds|not burned|next candidate|stale", low), (
        "work-discovery must explain why re-picking is acceptable: the judgment "
        "is cheap and re-derived from current data, the tick continues to the "
        "next candidate, and no stale local state can park a fixed ticket "
        "(CAL-1087 AC-1)."
    )


# --- AC-3: the routine command no longer instructs the write ------------------


def test_build_routine_defers_without_a_tracker_write() -> None:
    """AC-3/AC-4: ``/harness routine build`` step 2 does not instruct a comment
    or a label mutation. The command owns control flow; the deferral *judgment*
    (and its fallback) is single-homed in the skill it invokes."""
    body = _section(HARNESS_COMMAND.read_text(), "/harness routine build")
    found = _write_imperatives(body)
    assert not found, (
        f"the Build routine instructs a tracker write ({found}) the unattended "
        "runner cannot make. Delegate the deferral to the `work-discovery` "
        "skill's path instead of re-stating an impossible step (CAL-1087 AC-3)."
    )
    assert "work-discovery" in body, (
        "the Build routine must still invoke the `work-discovery` skill, which "
        "owns the deferral judgment (CAL-1087 AC-3)."
    )


# --- AC-2: /assess names the unattended fallback ------------------------------


def test_assess_filing_names_the_unattended_fallback() -> None:
    """AC-2: ``/assess``'s filing step states the unattended fallback, consistent
    with the ``layers.linear: false`` branch it already carries. Both causes —
    no tracker, and no human in the turn — reach the same place: keep the report,
    surface the findings. The report is already committed durably (step 3), so
    the fallback needs no new machinery."""
    body = _section(ASSESS_COMMAND.read_text(), "File the findings")
    low = body.lower()
    assert "unattended" in low, (
        "/assess's filing step must name the unattended run — it is told to file "
        "every finding as a Linear issue, which an unattended run cannot do "
        "(CAL-1087 AC-2)."
    )
    assert "layers.linear: false" in low or "no tracker" in low, (
        "/assess's filing step must keep its existing no-tracker branch — the "
        "unattended fallback is stated consistently with it, not as a rival "
        "mechanism (CAL-1087 AC-2)."
    )
    assert re.search(r"report", low), (
        "/assess's unattended fallback must name the report as the deliverable "
        "that survives a run nobody watched (CAL-1087 AC-2)."
    )
