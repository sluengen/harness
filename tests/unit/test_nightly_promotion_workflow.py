"""Contract guards for the deterministic nightly ``dev → staging`` promotion.

The step's logic now lives in ``scripts/promotion-step.sh``, and what that logic
*does* is proven by executing it against stubbed binaries in
``tests/integration/test_promotion_step_script.py`` — the instrument swap of
``specs/proposals/promotion-guard-instrument.md``, whose rule is recorded in
``specs/architecture-principles.md`` (*CI logic lives in a script, not in a
`run:` block*). Four tickets of regex (#390, #391, #393, #394) derived call sites
out of shell text here; none of that survives, because a text guard could only
ever show the workflow *said* something.

What is left is the text no execution reaches: the workflow's schedule,
concurrency and permissions; the pin that its promotion step invokes the wrapper
and carries nothing else, plus the ban on a verb invoked from any *other* step,
which is the one thing the deleted derivation covered that a step-scoped pin does
not; and the ban on an automated repair path, applied to **both** promotion
sources — extraction would otherwise leave a ``git push`` added to the script
uncovered, since the ban used to read one file and the logic now lives in the
other.
"""

from __future__ import annotations

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "nightly-staging-promotion.yml"
SCRIPT = REPO_ROOT / "scripts" / "promotion-step.sh"

#: The step that runs the promotion. Located by name so a rename is a named
#: failure rather than a guard that quietly stops checking anything.
_STEP = "- name: Promote the gated candidate"

#: The interpreter the step is allowed to name, and the only token permitted
#: before the script path.
_INTERPRETER = "bash"

#: Both files the promotion's shell can live in. The ban below is parametrized
#: over this pair rather than over the workflow alone: the logic moved, so a
#: repair path added to the script is now the likelier regression, and the tie
#: between "the script the ban covers" and "the script the workflow actually
#: invokes" is asserted in
#: :func:`test_the_promotion_step_carries_no_logic_of_its_own`, which derives the
#: referenced path from the ``run:`` value and requires it to be :data:`SCRIPT`.
_PROMOTION_SOURCES = (WORKFLOW, SCRIPT)

#: The three lifecycle calls the promotion drives, in order.
_LIFECYCLE_CALLS = ("promote start", "promote continue", "promote pr")


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
    assert "fetch-depth: 0" in workflow
    assert "git config user.name" in workflow and "git config user.email" in workflow


def test_the_promotion_step_carries_no_logic_of_its_own() -> None:
    """The step invokes the wrapper and nothing else.

    Three assertions whose conjunction pins the ``run:`` value exactly, without
    any one of them restating another: the value is ``bash`` plus one token, that
    token names a file that exists, and that file is :data:`SCRIPT` — the module
    ``tests/integration/test_promotion_step_script.py`` actually executes. A
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


def test_no_verb_is_invoked_outside_the_extracted_script() -> None:
    """No step invokes a verb; every verb call lives in the script.

    The pin above is exact but *step*-scoped — it says what one step's ``run:``
    value is, and a second step added anywhere else in the file is outside its
    reach. The text derivation this module deleted read the whole workflow, so it
    caught a verb invoked from any step; keeping that reach after narrowing the
    executed guard onto one script takes a workflow-scoped ban. The class is not
    hypothetical: this workflow holds ``contents: write``, a scheduled run is
    read from the default branch so CI can never exercise it, and the four
    tickets behind #396 were all about a ``--repo`` argument that left the
    allowlist.

    Comment lines are dropped first, because the ``permissions:`` block names
    ``harness promote pr`` in prose. Whole lines only: in YAML a ``#`` inside a
    quoted scalar is not a comment, so stripping from a mid-line ``#`` would let
    a real call hide behind one. The cost of erring this way is a trailing
    comment that mentions the wrapper, which can move to its own line.
    """
    lines = WORKFLOW.read_text(encoding="utf-8").splitlines()
    shell = "\n".join(line for line in lines if not line.lstrip().startswith("#"))

    assert _step_run_value(_promotion_step_lines(lines)) in shell, (
        "the comment strip removed the promotion step's own `run:` line, so the "
        "ban below would be reading text that cannot run anything"
    )
    assert "harness" not in shell, (
        "the workflow invokes a verb directly; every verb call belongs in "
        f"{SCRIPT.relative_to(REPO_ROOT)}, where the executed guard covers what "
        "it passes"
    )


@pytest.mark.parametrize("source", _PROMOTION_SOURCES, ids=lambda path: path.name)
def test_no_promotion_source_carries_a_repair_or_push_path(source: Path) -> None:
    """Neither promotion source may push directly or license an automated repair.

    Two files, because the extraction moved the shell out of the one the ban used
    to read. The floor is the file itself: a ban over a missing or empty file
    passes for the wrong reason.
    """
    assert source.is_file(), f"{source} is not a file, so the ban below checks nothing"
    text = source.read_text(encoding="utf-8")
    assert text.strip(), f"{source} is empty, so the ban below checks nothing"

    assert "git push" not in text, (
        f"{source.name} pushes directly; only `harness promote pr` may advance staging"
    )
    assert "agent_may_fix" not in text, (
        f"{source.name} licenses an automated repair; the nightly stops instead (#378)"
    )


@pytest.mark.parametrize("call", _LIFECYCLE_CALLS)
def test_the_script_drives_the_three_lifecycle_calls(call: str) -> None:
    """A presence check, and deliberately no more.

    What each call *passes* is proven by executing the script
    (``tests/integration/test_promotion_step_script.py``); this only pins that the
    file the workflow runs is still the promotion, so a script emptied to ``true``
    fails here rather than leaving the executed guard asserting over an empty
    invocation list.
    """
    assert SCRIPT.is_file(), f"{SCRIPT} must exist — the workflow invokes it"
    assert call in SCRIPT.read_text(encoding="utf-8"), (
        f"scripts/promotion-step.sh no longer drives `harness {call}`"
    )
