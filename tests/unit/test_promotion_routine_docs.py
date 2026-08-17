"""CAL-1119 / #189 — `/promote` carries the promotion routine an outer agent drives.

The promotion lifecycle (ADR 0003) is a surface an external orchestrator — or a
human — drives on a schedule. CAL-1119 documented the routine in ``RUNBOOK.md``
because no versioned command existed to carry it; **#189 moved it into
`commands/promote.md`**, the versioned, universal command every repo on this
guidance installs, with role-based argument resolution (`/promote <src> to
<dst>` against `CONTEXT.md` `branches:`). The orchestration logic lives in
exactly one place.

**#435 collapsed the two paths into one.** ADR 0015 retired the audited ``harness
promote`` verb loop, so the subcommand and lifecycle-state derivations this module
once ran against the live Typer app have no source left to derive from, the
reduced fallback is the whole command, and ``RUNBOOK.md`` is gone. AC-3, AC-5 and
AC-6 went with them.

**What this module asserts, after #459.** Four things:

* the command exists and is version-stamped, and the process doc's command table
  lists it — identity and structural correspondence, untouched;
* **one tripwire over ``## The loop``** — the hop reads its gate from
  ``CONTEXT.md``, stops rather than repairing, and publishes asymmetrically, with
  each negation anchored to what it governs;
* **one tripwire over ``## What this command must never do``** — the four
  prohibitions are present under a heading that is itself the negation.

Nine sentence-pins collapsed into those two under #459 (ADR 0016). Among them
was ``assert "2026-07-23" in doc`` — a literal date, pinning an amendment's
identity to prose that a reader may legitimately reword or re-cite, and measuring
nothing about whether the path stayed reduced.

Occurrence the polarity anchors cite (``code-quality`` Part C): the pre-#459 form
asserted ``"no repair" in doc``, ``"no pr" in doc`` and ``"never hardcod" in
doc`` over the whole document, each unanchored. Every one of them is satisfied by
prose stating the opposite rule in one section and the pinned token in another —
and after #435 widened the scope from the fallback section to the file, that gap
is the whole document wide. The ``craft.md`` class is *A guard over prose owns
structure and negative space, never meaning*.
"""

from __future__ import annotations

import re

from tests.unit._prose import REPO_ROOT

_COMMAND = REPO_ROOT / "commands" / "promote.md"
_CLAUDE_MD = REPO_ROOT / "CLAUDE.md"

#: The two rule-homes inside the command, each read as its own window.
_LOOP_HEADING = "## The loop"
_PROHIBITIONS_HEADING = "## What this command must never do"


def _command_doc() -> str:
    return _COMMAND.read_text(encoding="utf-8")


def _section(heading: str) -> str:
    """The body under a ``## `` heading, up to the next ``## ``.

    Returns ``""`` when the heading is absent, so a rename fails the tripwire
    that reads it rather than leaving its containment checks scanning nothing.
    """
    text = _command_doc()
    start = re.search(rf"^{re.escape(heading)}\s*$", text, re.MULTILINE)
    if start is None:
        return ""
    rest = text[start.end() :]
    following = re.search(r"^## ", rest, re.MULTILINE)
    return (rest[: following.start()] if following is not None else rest).strip()


def _normalize(text: str) -> str:
    """Lowercased, whitespace collapsed — markdown soft-wraps are not semantic."""
    return re.sub(r"\s+", " ", text.lower())


def test_command_exists_and_versioned() -> None:
    """AC-1: ``commands/promote.md`` exists and carries a guidance version stamp."""
    assert _COMMAND.exists(), "commands/promote.md does not exist"
    first_line = _command_doc().splitlines()[0]
    assert re.match(r"<!--\s*guidance:promote@\d+\.\d+\.\d+\s*-->", first_line), (
        f"commands/promote.md's first line is not a guidance version stamp: {first_line!r}"
    )


def test_command_listed_in_claude_md_table() -> None:
    """AC-1: `/promote` is listed in the `CLAUDE.md` command table."""
    claude_md = _CLAUDE_MD.read_text(encoding="utf-8")
    assert "/promote" in claude_md, (
        "CLAUDE.md does not list /promote in its command table"
    )


#: The gate command is **read**, never remembered. Anchored to ``hardcode``
#: because that is the noun the refusal governs: this path keeps no state, so a
#: gate command written into the command doc is the state it cannot hold.
_NEVER_HARDCODE = re.compile(
    r"\b(?:never|not|no|do not)\b(?:\W+\w+){0,4}?\W+hardcod\w*\b", re.IGNORECASE
)

#: The two stop conditions refuse repair. Anchored to ``repair``: the loop names
#: repair only to forbid it, so a window carrying the word without a negation has
#: been inverted into the bounded-repair lifecycle #435 retired.
_NO_REPAIR = re.compile(
    r"\b(?:never|not|no)\b(?:\W+\w+){0,4}?\W+repair\w*\b", re.IGNORECASE
)

#: The release hop's asymmetry, anchored to the target it must not touch.
_NEVER_THE_TARGET = re.compile(
    r"\b(?:never|not|no)\b(?:\W+\w+){0,4}?\W+target\b", re.IGNORECASE
)


def test_the_loop_sources_its_gate_and_stops_rather_than_repairing() -> None:
    """``## The loop`` states the mechanism it is safe to drive unattended.

    One tripwire over one rule-home (#459), replacing six whole-file phrase pins.
    Its parts:

    * **anchor** — ``## The loop`` resolves to prose. Every assertion reads that
      slice only; before #459 they read the whole document, which after #435 put
      the argument-resolution examples and the escalation section inside the same
      search space.
    * **terms** — ``commands.verify`` (the gate is sourced, not invented),
      ``stop and report`` (the outcome of both stop conditions), ``promotion
      branch`` (what the release hop pushes instead of the target).
    * **polarity** — three negations, each anchored to the noun it governs: the
      gate command is never hardcoded, neither stop condition is repaired, and the
      release hop never pushes the target directly. A window carrying the terms
      without them describes a loop that repairs conflicts and pushes ``main``,
      and the pre-#459 checks read that as the rule.
    """
    section = _section(_LOOP_HEADING)
    assert section, f"commands/promote.md has no {_LOOP_HEADING!r} section"
    normalized = _normalize(section)

    missing = [
        term
        for term in ("commands.verify", "stop and report", "promotion branch")
        if term not in normalized
    ]
    assert not missing, (
        f"{_LOOP_HEADING!r} no longer states {missing}. The hop reads its gate from "
        "CONTEXT.md, stops and reports on conflict or red, and publishes the "
        "release hop through a promotion branch — drop any of those and the loop "
        "is no longer safe to drive unattended."
    )

    assert _NEVER_HARDCODE.search(normalized), (
        f"{_LOOP_HEADING!r} does not refuse a hardcoded gate command. This path "
        "keeps no state, so it must read `CONTEXT.md` `commands.verify` fresh "
        "every run; a remembered command is a gate that silently stops matching "
        "the repo."
    )
    assert _NO_REPAIR.search(normalized), (
        f"{_LOOP_HEADING!r} no longer refuses repair on a conflict or a red gate. "
        "Naming the stop conditions without refusing repair is the bounded-repair "
        "lifecycle ADR 0015 retired, wearing the reduced path's vocabulary."
    )
    assert _NEVER_THE_TARGET.search(normalized), (
        f"{_LOOP_HEADING!r} no longer states the release hop leaves the target "
        "branch alone. 'Push the promotion branch' without 'never the target' is "
        "satisfied by a hop that pushes both."
    )


def test_the_prohibitions_are_stated_as_prohibitions() -> None:
    """``## What this command must never do`` carries its four subjects.

    One tripwire over the second rule-home. **The polarity lives in the heading,
    not in each bullet, and that is stated rather than faked:** two of the four
    bullets ("Auto-merge the release PR", "Push the release branch directly")
    carry no negation of their own because the heading scopes the whole list. So
    the heading match *is* the polarity assertion — a heading reworded into
    "What this command does" turns four prohibitions into four instructions
    without changing a word of the list, and nothing else in this module would
    see it.
    """
    text = _command_doc()
    assert re.search(rf"^{re.escape(_PROHIBITIONS_HEADING)}\s*$", text, re.MULTILINE), (
        f"commands/promote.md has no {_PROHIBITIONS_HEADING!r} heading. The list "
        "below it carries no negation of its own — the heading is what makes it a "
        "list of prohibitions rather than a list of steps."
    )

    section = _normalize(_section(_PROHIBITIONS_HEADING))
    missing = [
        subject
        for subject in ("direct-pushed", "auto-merge", "repair", "gate")
        if subject not in section
    ]
    assert not missing, (
        f"the prohibitions section no longer names {missing}. These four are what "
        "a driving agent may not do: direct-push the release branch, merge its own "
        "PR, repair a stop condition, or push on a gate it could not read."
    )
