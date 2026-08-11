"""ADR 0011 — the interactive driver declares attendance; no routine path does (#298).

``harness start --attended`` exempts a run from ``loop.wall_clock_budget_minutes``
— the only ceiling on autonomous spend the unattended loop has, standing in for a
token meter the orchestrating session cannot read. ADR 0011 accepts attendance as
a *claim* the harness cannot verify, and names the one enforcement that is
available: "the routine-path guard — a test asserting no routine passes
``--attended`` — is what keeps the erosion from happening by edit."

This module owns that guard in both directions, over ``commands/harness.md``:

* the **attended** entry point — the single ``## /harness run`` section — declares
  the flag in the ``start`` invocation it prescribes (AC-1);
* every **other** top-level section does not, in any command it prescribes (AC-2);
* and a routine that reaches ``start`` *transitively* — by handing the whole
  ticket to ``/harness run``, which is what ``/harness routine build`` step 2 does
  — states that the flag is dropped. Without that third check the guard would sit
  green while the hourly Build tick ran unbounded, because no routine section
  would contain a ``harness start`` command at all.

**What this replaces.** #295 shipped an interim form of the prohibition at the
foot of ``test_routine_commands.py`` (``test_no_routine_declares_a_run_attended``
plus its two floors). It is superseded here, not merely relocated, on two counts.
Its section set was a hardcoded two-name tuple — precisely what AC-2 forbids, and
what its own comment claimed to avoid while not doing so — so a third routine
would have arrived unguarded. And its predicate was a plain substring test over
the whole section body, which cannot separate a *command* that passes the flag
from *prose* that forbids it: it would have gone red on the very declination
sentences that close the transitive hole.

The sets here are derived from the file's own headings, fence-aware, so a routine
added later is covered the moment its heading exists.

*Source:* #298; ADR 0011; the accepted proposal
``specs/proposals/attended-runs-and-the-wall-clock.md`` (breakdown item 4 of 5).
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

# ``tests/unit/test_*.py`` → ``parents[2]`` is the repo (or worktree) root.
_REPO_ROOT = Path(__file__).resolve().parents[2]
_HARNESS_COMMAND = _REPO_ROOT / "commands" / "harness.md"
_RUN_COMMAND = _REPO_ROOT / "commands" / "harness" / "run.md"
_BUILD_ROUTINE = _REPO_ROOT / "commands" / "harness" / "routine-build.md"
_QUALITY_ROUTINE = _REPO_ROOT / "commands" / "harness" / "routine-quality.md"

_ATTENDED_FLAG = "--attended"

#: The attended entry point. Anchored at the heading start and terminated by
#: ``\b`` rather than tested by containment: a rename must fail loudly (see
#: :func:`test_exactly_one_attended_entry_point`) instead of silently emptying
#: the allowlist and disarming AC-1.
_ATTENDED_HEADING_RE = re.compile(r"^##\s+/harness run\b")

#: The parent section of the unattended loops. Every routine — the two that
#: exist and any third added later — is a ``###`` subsection of this one, which
#: is why the normative declination is single-homed in its preamble.
_ROUTINE_HEADING_RE = re.compile(r"^##\s+/harness routine\b")

#: A fence delimiter. Toggles fenced state; never itself a heading or a command.
_FENCE_RE = re.compile(r"^\s*```")

#: An inline-code span. The ``[^`\n]`` body keeps a span on one line, so prose
#: that merely contains backticks cannot swallow the rest of a paragraph.
_INLINE_CODE_RE = re.compile(r"`([^`\n]+)`")

#: A command span *is* a ``start`` invocation when its text begins here.
_START_INVOCATION = "harness start"

#: A command span that hands the ticket to the interactive driver — the
#: transitive route to ``start``.
_RUN_INVOCATION = "/harness run"

#: A sentence declining attendance: a negation, then the flag, with no sentence
#: boundary in between. Deliberately matched against *prose*, which is where the
#: transitive rule has to live — a routine that delegates issues no ``start``
#: command of its own, so there is no command span to inspect.
_DECLINATION_RE = re.compile(
    r"(?:without|omit(?:s|ted|ting)?|never|must not|does not apply|drops?)"
    r"[^.\n]{0,200}" + re.escape(_ATTENDED_FLAG),
    re.IGNORECASE,
)


def _fence_states(text: str) -> list[tuple[str, bool]]:
    """Each line paired with whether it is inside a fenced code block.

    One single pass serves both derivations. ``commands/harness.md`` embeds a
    ``markdown`` fence carrying an issue template whose ``## Context`` /
    ``## Acceptance criteria`` lines would mint phantom sections for a
    fence-blind splitter — see
    :func:`test_derivation_excludes_headings_inside_fences`.
    """
    states: list[tuple[str, bool]] = []
    in_fence = False
    for line in text.splitlines():
        if _FENCE_RE.match(line):
            in_fence = not in_fence
            # The delimiter belongs to the fence, and is neither heading nor
            # command — marking it fenced keeps it out of the heading scan.
            states.append((line, True))
            continue
        states.append((line, in_fence))
    return states


def _sections(text: str, level: int = 2) -> list[tuple[str, list[tuple[str, bool]]]]:
    """``(heading, body)`` for every heading of exactly ``level``, outside fences.

    A section's body runs to the next heading of the same-or-higher level, so a
    ``##`` slice contains its ``###`` subsections — which is what lets one check
    over the routine parent cover every routine nested beneath it.
    """
    marker = "#" * level + " "
    deeper = "#" * (level + 1)
    sections: list[tuple[str, list[tuple[str, bool]]]] = []
    current: tuple[str, list[tuple[str, bool]]] | None = None
    for line, in_fence in _fence_states(text):
        is_heading = (
            not in_fence and line.startswith(marker) and not line.startswith(deeper)
        )
        if is_heading:
            if current is not None:
                sections.append(current)
            current = (line.strip(), [])
        elif current is not None:
            current[1].append((line, in_fence))
    if current is not None:
        sections.append(current)
    return sections


def _command_spans(body: list[tuple[str, bool]], fenced_only: bool = False) -> list[str]:
    """The commands a section prescribes, as opposed to prose *about* commands.

    Two producers: every line inside a fenced block, and every inline-code span
    outside one. The distinction is load-bearing in both directions — the
    routine's one direct ``start`` call lives in prose as an inline span, while
    the declination sentences name the flag in running text — so a substring
    test over the raw body cannot tell the two apart.
    """
    spans: list[str] = []
    for line, in_fence in body:
        if in_fence:
            spans.append(line.strip())
        elif not fenced_only:
            spans.extend(m.group(1).strip() for m in _INLINE_CODE_RE.finditer(line))
    return spans


def _start_invocations(
    body: list[tuple[str, bool]], fenced_only: bool = False
) -> list[str]:
    return [
        span
        for span in _command_spans(body, fenced_only=fenced_only)
        if span.startswith(_START_INVOCATION)
    ]


def _delegates_to_run(body: list[tuple[str, bool]]) -> bool:
    return any(span.startswith(_RUN_INVOCATION) for span in _command_spans(body))


def _body_text(body: list[tuple[str, bool]]) -> str:
    return "\n".join(line for line, _ in body)


_ROUTINE_BODY = (
    "Never pass `--attended` from a routine.\n"
    "### /harness routine build\n"
    + _BUILD_ROUTINE.read_text()
    + "\n### /harness routine quality\n"
    + _QUALITY_ROUTINE.read_text()
)
_DOC = _RUN_COMMAND.read_text() + "\n" + _ROUTINE_BODY
_ATTENDED = [("## /harness run", _fence_states(_RUN_COMMAND.read_text()))]
_ROUTINE_PARENTS = [("## /harness routine", _fence_states(_ROUTINE_BODY))]
_UNATTENDED = [
    _ROUTINE_PARENTS[0],
    ("## /harness ingest", _fence_states("No start invocation.")),
]
_TOP_SECTIONS = [*_ATTENDED, *_UNATTENDED]


# --- Derivation floors -------------------------------------------------------
#
# Every check below is only as honest as the set it ranges over. An empty or
# mis-sliced derivation makes the prohibitions pass by asserting nothing, which
# is the exact failure mode #295's substring guard had.


def test_exactly_one_attended_entry_point() -> None:
    """The allowlist resolves to precisely one section.

    Zero would empty the allowlist and make AC-1 unassertable while every
    prohibition below passed; two would mean a second caller had quietly been
    granted the exemption. Either way the answer is to reconcile the heading,
    not to relax the anchor.
    """
    headings = [s[0] for s in _ATTENDED]
    assert len(headings) == 1, (
        f"expected exactly one attended entry point in {_HARNESS_COMMAND.name}, "
        f"found {len(headings)}: {headings}. `/harness run` is the one caller "
        "ADR 0011 permits to declare attendance; if it was renamed, update "
        "_ATTENDED_HEADING_RE — do not widen it."
    )


def test_derived_sections_cover_the_document() -> None:
    """The splitter returns the document's real top-level sections."""
    headings = [s[0] for s in _TOP_SECTIONS]
    assert len(headings) >= 3, (
        f"only {len(headings)} top-level sections derived from "
        f"{_HARNESS_COMMAND.name}: {headings}. The splitter is not reading the "
        "document."
    )
    assert _UNATTENDED, "no unattended sections derived — the prohibitions below assert nothing"
    assert len(_ROUTINE_PARENTS) == 1, (
        f"expected exactly one `## /harness routine` parent, found "
        f"{[s[0] for s in _ROUTINE_PARENTS]}"
    )


def test_the_routine_parent_contains_every_routine() -> None:
    """The ``##`` parent slice carries both routines, so one check covers all.

    If the parent slice stopped short, the transitive check would read the wrong
    text and the ``##``-level prohibition would miss whichever routine fell
    outside it.
    """
    body = _body_text(_ROUTINE_PARENTS[0][1])
    for routine in ("### /harness routine build", "### /harness routine quality"):
        assert routine in body, (
            f"`{routine}` is not inside the `## /harness routine` slice — the "
            "section splitter is not returning the parent's real body, so every "
            "check ranging over it is reading the wrong text."
        )


def test_derivation_excludes_headings_inside_fences() -> None:
    """No phantom section is minted from the embedded issue template.

    ``/harness ingest`` embeds a ``markdown`` fence whose template carries
    ``## Context`` / ``## Goal`` / ``## Acceptance criteria`` / ``## Out of
    scope``. A fence-blind splitter would derive those as real sections — each
    with a body that is not really theirs — and the prohibitions would then range
    over text no one wrote as a section.
    """
    headings = [s[0] for s in _TOP_SECTIONS]
    for phantom in ("## Context", "## Goal", "## Acceptance criteria", "## Out of scope"):
        assert phantom not in headings, (
            f"`{phantom}` was derived as a top-level section, but it lives inside "
            "the embedded issue template's fence. The splitter is not fence-aware."
        )


# --- AC-1: the attended entry point declares attendance ----------------------


def test_run_command_declares_attended() -> None:
    """AC-1: ``/harness run``'s prescribed ``start`` invocation carries the flag.

    Scoped to *fenced* invocations — the prescriptive ones. The same section's
    prose deliberately quotes flagless ``harness start`` forms, most pointedly
    the breaker-recovery block's negative example ("the recovery is **not**
    ``harness start <TICKET> --resume`` on its own"), so a blanket rule over
    every span would demand the flag on a form the document is telling the
    reader not to use.
    """
    body = _ATTENDED[0][1]
    fenced = _start_invocations(body, fenced_only=True)
    assert fenced, (
        "`/harness run` prescribes no fenced `harness start` invocation, so AC-1 "
        "has nothing to assert against. The Step 1 command block is the thing "
        "being guarded — restore it."
    )
    missing = [span for span in fenced if _ATTENDED_FLAG not in span]
    assert not missing, (
        f"`/harness run` prescribes `harness start` without `{_ATTENDED_FLAG}`: "
        f"{missing}. It is the interactive driver — the one caller ADR 0011 "
        "permits to declare attendance — and an undeclared run is measured "
        "against the wall clock while the operator is thinking."
    )


# --- AC-2: no unattended entry point declares attendance ---------------------


@pytest.mark.parametrize(
    "heading,body",
    _UNATTENDED,
    ids=[s[0].lstrip("# ").split(" \\<")[0] for s in _UNATTENDED],
)
def test_no_unattended_entry_point_declares_attended(
    heading: str, body: list[tuple[str, bool]]
) -> None:
    """AC-2: every section outside the allowlist keeps its runs bounded.

    Derived, not listed: a routine added later is a ``###`` subsection of the
    ``## /harness routine`` parent and is therefore already inside this slice,
    with nobody having to remember to extend a tuple.
    """
    offenders = [
        span for span in _start_invocations(body) if _ATTENDED_FLAG in span
    ]
    assert not offenders, (
        f"`{heading}` prescribes `{_ATTENDED_FLAG}`: {offenders}. That exempts "
        "the run from the wall-clock budget (ADR 0011) with no operator present, "
        "and the wall clock is the only ceiling on autonomous spend there is. "
        "Remove the flag, or amend ADR 0011 first if the decision has genuinely "
        "changed."
    )


# --- The transitive half: a routine that delegates must decline --------------


def test_routine_preamble_declines_attendance() -> None:
    """The normative rule is stated once, where it covers every routine.

    This is the check that makes AC-2 mean something. A routine issues no
    ``harness start`` command of its own when it delegates — ``/harness routine
    build`` step 2 hands the whole ticket to ``/harness run``, whose Step 1 now
    declares the flag — so the prohibition above would be *vacuously* green while
    every hourly tick ran unbounded. The declination is what closes that.
    """
    preamble = _body_text(_ROUTINE_PARENTS[0][1]).split("### ")[0]
    assert _DECLINATION_RE.search(preamble), (
        "the `## /harness routine` preamble does not state that a routine never "
        f"passes `{_ATTENDED_FLAG}`. Without it a routine inherits the attendance "
        "declaration through its delegation to `/harness run`, and the unattended "
        "loop loses the only ceiling it has on autonomous spend (ADR 0011)."
    )


_DELEGATING_ROUTINES = [
    (heading, body)
    for heading, body in _sections(_body_text(_ROUTINE_PARENTS[0][1]), level=3)
    if _delegates_to_run(body)
]


def test_a_routine_actually_delegates_to_the_run_command() -> None:
    """Non-vacuity floor for the check below.

    ``/harness routine build`` reaches ``start`` through ``/harness run``; that
    delegation is the whole reason the transitive check exists. If the derived
    set were empty, the parametrized check would pass by ranging over nothing.
    """
    assert _DELEGATING_ROUTINES, (
        "no routine was derived as delegating to `/harness run`, so the "
        "transitive check below asserts nothing. Either the section splitter is "
        "wrong or the Build routine's delegation was rewritten — reconcile it, "
        "do not delete the check."
    )


@pytest.mark.parametrize(
    "heading,body",
    _DELEGATING_ROUTINES,
    ids=[h.lstrip("# ") for h, _ in _DELEGATING_ROUTINES],
)
def test_delegating_routines_decline_attendance(
    heading: str, body: list[tuple[str, bool]]
) -> None:
    """A routine that delegates says so at the point of delegation.

    The parent preamble carries the rule, but an agent reading the Build
    routine's step 2 must not have to have read the preamble to get this right.
    """
    assert _DECLINATION_RE.search(_body_text(body)), (
        f"`{heading}` hands the ticket to `/harness run` — whose Step 1 declares "
        f"`{_ATTENDED_FLAG}` — without stating that this path drops the flag. An "
        "agent following the delegation literally would start an unbounded run "
        "on an unattended tick (ADR 0011)."
    )


# --- Positive controls: the predicates can actually fail ----------------------
#
# ``test_no_unattended_entry_point_declares_attended`` is green before any edit —
# nothing passes the flag today — so it earns its teeth here rather than from the
# live tree. Planted fixtures, no disk.


def test_predicate_flags_a_planted_attended_routine() -> None:
    """A routine that passes the flag is detected, fenced or inline."""
    fenced = "## /harness routine x\n\n```bash\nharness start <T> --attended\n```\n"
    inline = "## /harness routine x\n\nRun `harness start <T> --attended` first.\n"
    for planted in (fenced, inline):
        body = _sections(planted)[0][1]
        assert [s for s in _start_invocations(body) if _ATTENDED_FLAG in s], (
            f"the predicate missed a planted attended invocation in:\n{planted}"
        )


def test_predicate_ignores_a_prose_mention_of_the_flag() -> None:
    """Naming the flag in order to forbid it is not passing it.

    This is the half #295's substring guard got wrong, and it is not academic:
    the declination sentences this ticket adds name ``--attended`` inside routine
    sections, so a substring predicate would report the fix as the violation.
    """
    planted = (
        "## /harness routine x\n\n"
        "This tick is unattended: start **without** `--attended`, and never pass "
        "`--attended` to `harness start` on a routine path.\n"
    )
    body = _sections(planted)[0][1]
    assert not [s for s in _start_invocations(body) if _ATTENDED_FLAG in s], (
        "a prose mention of the flag was read as a command that passes it — the "
        "predicate is matching text rather than command spans."
    )
    assert _DECLINATION_RE.search(_body_text(body)), (
        "the declination predicate did not recognise an explicit refusal"
    )


def test_declination_predicate_rejects_a_section_with_no_refusal() -> None:
    """A delegating section that says nothing about the flag is not compliant."""
    planted = (
        "## /harness routine x\n\n"
        "Implement it: `/harness run <TICKET>` (primary).\n"
    )
    body = _sections(planted)[0][1]
    assert _delegates_to_run(body), "the delegation predicate missed a planted delegation"
    assert not _DECLINATION_RE.search(_body_text(body)), (
        "the declination predicate accepted a section that never declines the "
        "flag, so it would pass the transitive hole this guard exists to close"
    )


def test_attended_obligation_fails_on_a_flagless_run_section() -> None:
    """Positive control for AC-1: an undeclared driver section is detected."""
    planted = "## /harness run <T>\n\n```bash\nharness start <ISSUE-ID>\n```\n"
    section = _sections(planted)[0]
    assert _ATTENDED_HEADING_RE.match(section[0]), "the anchor missed a real run heading"
    fenced = _start_invocations(section[1], fenced_only=True)
    assert fenced and all(_ATTENDED_FLAG not in span for span in fenced), (
        "the AC-1 predicate would not notice a `/harness run` section that "
        "stopped declaring attendance"
    )


def test_attended_anchor_does_not_match_the_routine_heading() -> None:
    """``/harness routine`` must never be read as ``/harness run``.

    The two share a prefix only up to ``ru``, so containment happens to be safe
    here — but the anchor is what guarantees it, and a guard that relies on an
    accident is one rename away from granting every routine the exemption.
    """
    assert not _ATTENDED_HEADING_RE.match("## /harness routine \\<loop\\>")
    assert _ATTENDED_HEADING_RE.match("## /harness run \\<ISSUE-ID\\>")
