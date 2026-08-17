"""Contract guards for the deterministic nightly ``dev → staging`` promotion.

The step's logic lives in ``scripts/promotion-step.sh``, and what that logic
*does* is proven by executing it against a stubbed ``git`` in
``tests/unit/test_promotion_step_script.py`` — the instrument swap of
``specs/proposals/promotion-guard-instrument.md``, whose rule is recorded in
``specs/architecture-principles.md`` (*CI logic lives in a script, not in a
`run:` block*). Four tickets of regex (#390, #391, #393, #394) derived call sites
out of shell text here; none of that survives, because a text guard could only
ever show the workflow *said* something.

What is left is the text no execution reaches: the workflow's schedule,
concurrency and permissions; the pin that its promotion step invokes the script
and carries nothing else; and the ban on the workflow mutating a ref or licensing
a repair from any *other* step, which is the one thing the deleted derivation
covered that a step-scoped pin does not.

**#435 narrowed the ban rather than dropping it.** ADR 0015 retires the ``harness
promote`` verb and keeps the promotion, so ``git push`` moved from *forbidden
everywhere* to *the script's job, and only the script's*. That is a weaker ban
than the one it replaces, so it is stated as a location rather than an absence:
the workflow may not push, because a push added to a ``run:`` block is a mutation
no executed guard can see, while the script's push is asserted on recorded argv
by the module above.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.unit._prose import REPO_ROOT

WORKFLOW = REPO_ROOT / ".github" / "workflows" / "nightly-staging-promotion.yml"
SCRIPT = REPO_ROOT / "scripts" / "promotion-step.sh"

#: The step that runs the promotion. Located by name so a rename is a named
#: failure rather than a guard that quietly stops checking anything.
_STEP = "- name: Promote the gated candidate"

#: The interpreter the step is allowed to name, and the only token permitted
#: before the script path.
_INTERPRETER = "bash"

#: Both files the promotion's shell can live in. The repair ban below is
#: parametrized over this pair rather than over the workflow alone: the logic
#: moved, so a repair path added to the script is now the likelier regression,
#: and the tie between "the script the ban covers" and "the script the workflow
#: actually invokes" is asserted in
#: :func:`test_the_promotion_step_carries_no_logic_of_its_own`, which derives the
#: referenced path from the ``run:`` value and requires it to be :data:`SCRIPT`.
_PROMOTION_SOURCES = (WORKFLOW, SCRIPT)

#: What the script must still be seen to do. A presence check, and deliberately
#: no more — the *behaviour* is measured by executing it. This is the floor that
#: stops a script emptied to ``true`` from leaving the executed guard asserting
#: over an empty invocation list.
_SCRIPT_MUST_DRIVE = (
    "scripts/verify.sh",  # the gate decides
    "git push",           # and only a green gate advances the ref
    "staging",            # to this branch
)


def _promotion_step_lines(lines: list[str]) -> list[str]:
    """The promotion step's own lines, from its ``- name:`` to the next sibling.

    Asserts rather than indexing bare: a renamed or removed step must name what
    was looked for, so whoever renamed it does not have to reconstruct it (#391).
    """
    starts = [i for i, line in enumerate(lines) if line.strip() == _STEP]
    assert len(starts) == 1, (
        f"the workflow must have exactly one step named {_STEP!r}; found {len(starts)} "
        f"— renamed, removed, or duplicated?"
    )
    start = starts[0]
    indent = len(lines[start]) - len(lines[start].lstrip())
    step = [lines[start]]
    for line in lines[start + 1 :]:
        if line.strip() and (len(line) - len(line.lstrip())) <= indent:
            break
        step.append(line)
    return step


def _step_run_value(step: list[str]) -> str:
    """The single ``run:`` value in ``step``, stripped.

    Exactly one: a step that grew a second ``run:`` line has grown logic again,
    which is the thing this module now exists to forbid.
    """
    runs = [line.strip() for line in step if line.strip().startswith("run:")]
    assert len(runs) == 1, (
        f"the promotion step must carry exactly one `run:`; found {len(runs)}: {runs}"
    )
    return runs[0][len("run:") :].strip()


def _uncommented(text: str) -> str:
    """``text`` without whole comment lines.

    Whole lines only: in YAML a ``#`` inside a quoted scalar is not a comment, so
    stripping from a mid-line ``#`` would let a real command hide behind one. The
    cost of erring this way is a trailing comment that mentions a banned token,
    which can move to its own line.
    """
    return "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("#"))


def test_the_workflow_is_a_bounded_deterministic_nightly() -> None:
    """The scheduler's own shape: when it fires, that it cannot race itself, and
    what it may write (#378). None of this is reachable by executing anything."""
    assert WORKFLOW.is_file(), "the nightly dev-to-staging promotion workflow must exist (#378)"
    workflow = WORKFLOW.read_text(encoding="utf-8")

    assert 'cron: "0 14 * * *"' in workflow, "14:00 UTC is midnight in Australia/Brisbane"
    assert "workflow_dispatch:" in workflow
    assert "nightly-dev-to-staging" in workflow
    assert "cancel-in-progress: false" in workflow
    assert "contents: write" in workflow
    assert "ref: dev" in workflow, "the job must gate and promote `dev`, not the default branch"
    assert "fetch-depth: 0" in workflow
    assert "git config user.name" in workflow and "git config user.email" in workflow


def test_the_promotion_step_carries_no_logic_of_its_own() -> None:
    """The step invokes the script and nothing else.

    Three assertions whose conjunction pins the ``run:`` value exactly, without
    any one of them restating another: the value is ``bash`` plus one token, that
    token names a file that exists, and that file is :data:`SCRIPT` — the module
    ``tests/unit/test_promotion_step_script.py`` actually executes. A
    workflow pointing at some *other* script would be green on the first two and
    is caught by the third; a workflow that grew ``| tee run.log`` is caught by
    the first, and that matters beyond tidiness, because ``::error::``
    annotations are interpreted only on the step's own stdout.
    """
    step = _promotion_step_lines(WORKFLOW.read_text(encoding="utf-8").splitlines())
    value = _step_run_value(step)

    tokens = value.split()
    assert tokens[:1] == [_INTERPRETER] and len(tokens) == 2, (
        f"the promotion step's `run:` must be `{_INTERPRETER} <script>` and nothing "
        f"more (specs/architecture-principles.md → CI logic lives in a script); it is "
        f"{value!r}"
    )
    referenced = REPO_ROOT / tokens[1]
    assert referenced.is_file(), (
        f"the promotion step invokes {tokens[1]}, which is not a file in this tree"
    )
    assert referenced == SCRIPT, (
        f"the promotion step invokes {tokens[1]}, but the executed guard drives "
        f"{SCRIPT.relative_to(REPO_ROOT)} — the workflow would be running shell no "
        f"test covers"
    )


def test_no_workflow_step_mutates_a_ref_outside_the_extracted_script() -> None:
    """The push lives in the script, where executing it can measure what it pushes.

    The pin above is exact but *step*-scoped — it says what one step's ``run:``
    value is, and a second step added anywhere else in the file is outside its
    reach. The text derivation this module deleted read the whole workflow, so it
    caught a mutation invoked from any step; keeping that reach after narrowing
    the executed guard onto one script takes a workflow-scoped ban.

    The class is not hypothetical: this workflow holds ``contents: write`` and a
    scheduled run is read from the default branch, so CI can never exercise it.
    """
    shell = _uncommented(WORKFLOW.read_text(encoding="utf-8"))

    assert _step_run_value(_promotion_step_lines(shell.splitlines())) in shell, (
        "the comment strip removed the promotion step's own `run:` line, so the "
        "ban below would be reading text that cannot run anything"
    )
    for forbidden in ("git push", "git merge", "git tag"):
        assert forbidden not in shell, (
            f"the workflow runs `{forbidden}` directly; every ref mutation belongs in "
            f"{SCRIPT.relative_to(REPO_ROOT)}, where the executed guard covers what "
            "it does"
        )


@pytest.mark.parametrize("source", _PROMOTION_SOURCES, ids=lambda path: path.name)
def test_no_promotion_source_licenses_an_automated_repair(source: Path) -> None:
    """Neither promotion source may repair a red gate or force a ref.

    The nightly stops and reports (#378); ADR 0015 keeps that posture through the
    rewrite, since plain git makes a force-push exactly as available as the
    retired verb's bounded repair was. The floor is the file itself: a ban over a
    missing or empty file passes for the wrong reason.
    """
    assert source.is_file(), f"{source} is not a file, so the ban below checks nothing"
    text = _uncommented(source.read_text(encoding="utf-8"))
    assert text.strip(), f"{source} is empty, so the ban below checks nothing"

    for forbidden in ("--force", "-f ", "agent_may_fix"):
        assert forbidden not in text, (
            f"{source.name} licenses an automated repair or a forced ref update "
            f"({forbidden!r}); the nightly stops and reports instead (#378)"
        )


@pytest.mark.parametrize("token", _SCRIPT_MUST_DRIVE)
def test_the_script_still_drives_the_promotion(token: str) -> None:
    """A presence check, and deliberately no more.

    What the script *does* with each of these is proven by executing it
    (``tests/unit/test_promotion_step_script.py``); this only pins that
    the file the workflow runs is still the promotion, so a script emptied to
    ``true`` fails here rather than leaving the executed guard asserting over an
    empty invocation list.
    """
    assert SCRIPT.is_file(), f"{SCRIPT} must exist — the workflow invokes it"
    assert token in SCRIPT.read_text(encoding="utf-8"), (
        f"scripts/promotion-step.sh no longer names {token!r} — it must still run "
        "the gate and, only on green, advance staging"
    )
