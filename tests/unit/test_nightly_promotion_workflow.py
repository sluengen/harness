"""Contract guards for the deterministic nightly ``dev → main`` promotion.

Admission (ADR 0017 D5): class (a) — the contract of a workflow file, asserted
on its text because no execution reaches it.

v5 chunk 3 (ADR 0003 as amended, ADR 0017 D6): this repo retires its ``staging``
role, so the nightly promotes ``dev → main`` directly — an unattended advance of
``main`` on green, recorded as this repo's topology in
``specs/infrastructure.md``. **#485 changed how that advance lands.** ``main`` is
protected and requires a pull request, so the job opens or reuses one from
``dev`` and merges it through the API; fast-forward-only publishing is retired
in favour of tree identity (ADR 0003 as amended 2026-08-19). The discipline is
otherwise unchanged: gate on the exact candidate, never force, never repair,
never resolve a conflict.

The step's logic lives in ``scripts/promotion-step.sh``, and what that logic
*does* is proven by executing it against a stubbed ``git`` in
``tests/unit/test_promotion_step_script.py`` — the instrument swap of
the `promotion-guard-instrument` proposal (settled, and removed from the tree
by #547; git history keeps it), whose rule is recorded in
``specs/architecture-principles.md`` (*CI logic lives in a script, not in a
`run:` block*). Four tickets of regex (#390, #391, #393, #394) derived call sites
out of shell text here; none of that survives, because a text guard could only
ever show the workflow *said* something.

What is left is the text no execution reaches: the workflow's schedule,
concurrency and permissions; the pin that its promotion step invokes the script
and carries nothing else; and the ban on the workflow mutating a ref or licensing
a repair from any *other* step, which is the one thing the deleted derivation
covered that a step-scoped pin does not.

**#435 narrowed the ban rather than dropping it, and #485 widened it again.** ADR
0015 retires the ``harness promote`` verb and keeps the promotion, so ``git
push`` moved from *forbidden everywhere* to *the script's job, and only the
script's*. That is a weaker ban than the one it replaces, so it is stated as a
location rather than an absence: the workflow may not mutate, because a mutation
added to a ``run:`` block is one no executed guard can see, while the script's
own calls are asserted on recorded argv by the module above. Since the promotion
became a pull-request merge, the mutations the workflow may not make include the
API ones — ``gh pr create``, ``gh pr merge``, ``gh api`` — not only the git ones.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from tests.unit._prose import REPO_ROOT

WORKFLOW = REPO_ROOT / ".github" / "workflows" / "nightly-promotion.yml"
CI_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "ci.yml"
SCRIPT = REPO_ROOT / "scripts" / "promotion-step.sh"

#: Exactly the grants the promotion needs (#485): the merge writes onto `main`,
#: the job opens and merges its own pull request, and it reads the required
#: check's conclusion. Asserted as a **set**, not as substrings — a presence
#: check cannot see a widening, which is the whole risk a permissions block
#: carries.
_PERMISSIONS = {
    "contents": "write",
    "pull-requests": "write",
    "checks": "read",
}

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
    "gh api",             # the script reaches the API at all
    # ...and one of those calls is the merge. `gh api` alone cannot witness it:
    # the check-run poll spells `gh api` too, so deleting only the merge leaves
    # a `gh api` presence check green. `--method PUT` is the merge's alone.
    "--method PUT",
    "main",               # onto this branch
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


def _permissions_block() -> dict[str, str]:
    """The workflow's top-level ``permissions:`` mapping, parsed whole.

    Parsed rather than substring-matched so the comparison can be an equality:
    what a permissions block must not do is *grow*, and no presence check can
    see that.
    """
    lines = WORKFLOW.read_text(encoding="utf-8").splitlines()
    starts = [i for i, line in enumerate(lines) if line.rstrip() == "permissions:"]
    assert len(starts) == 1, (
        f"the workflow must declare exactly one top-level `permissions:` block; "
        f"found {len(starts)}"
    )
    granted: dict[str, str] = {}
    for line in lines[starts[0] + 1 :]:
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if not line.startswith(" "):
            break
        match = re.match(r"^\s+([a-z-]+):\s*([a-z-]+)\s*(?:#.*)?$", line)
        assert match is not None, f"unreadable line in the permissions block: {line!r}"
        granted[match.group(1)] = match.group(2)
    return granted


def _ci_trigger_branches(event: str) -> list[str]:
    """The branch filter ``ci.yml`` declares for ``event``.

    Derived from the file rather than restated here, so the guard measures what
    the workflow says and not what this module remembers it said.
    """
    match = re.search(
        rf"^ {{2}}{re.escape(event)}:\s*\n\s+branches:\s*\[([^\]]*)\]",
        CI_WORKFLOW.read_text(encoding="utf-8"),
        re.MULTILINE,
    )
    assert match is not None, f"ci.yml declares no `{event}:` trigger with a branch filter"
    return [branch.strip() for branch in match.group(1).split(",") if branch.strip()]


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
    assert WORKFLOW.is_file(), "the nightly dev-to-main promotion workflow must exist (#378)"
    workflow = WORKFLOW.read_text(encoding="utf-8")

    assert 'cron: "0 14 * * *"' in workflow, "14:00 UTC is midnight in Australia/Brisbane"
    assert "workflow_dispatch:" in workflow
    assert "nightly-dev-to-main" in workflow
    assert "cancel-in-progress: false" in workflow
    assert "ref: dev" in workflow, "the job must gate and promote `dev`, not the default branch"
    assert "fetch-depth: 0" in workflow
    # No commit author is pinned. Nothing in this job creates a commit: the
    # merge commit is written server-side by the API, and `fetch`/`ls-remote`
    # need no author. Pinning one would defend configuration the job no longer
    # reads (#485). Read over `_uncommented`, as the repair ban below already
    # is: over the raw text a comment *explaining* that no author is configured
    # — the natural next edit to a step this change deleted — turns the gate red
    # (mutation-proved). A ban belongs over what the job runs, not over what it
    # says about itself.
    assert "git config user." not in _uncommented(workflow), (
        "the promotion writes no local commit, so a configured author is dead "
        "configuration the suite must not defend"
    )


def test_the_workflow_grants_exactly_the_promotion_permissions() -> None:
    """The permissions block is pinned as a **set**, not by presence (#485).

    ``assert "contents: write" in workflow`` is satisfied by any block that also
    grants ``id-token: write`` or ``packages: write``: a substring check can see
    an absence but never a widening, and widening is the only direction a
    permissions block fails in. The mapping is parsed and compared whole, so a
    fourth grant fails here rather than shipping unobserved.
    """
    granted = _permissions_block()

    assert granted == _PERMISSIONS, (
        f"the nightly grants {granted}, not exactly {_PERMISSIONS}; the job merges "
        "its own promotion pull request and reads one check, and needs nothing else"
    )


def test_the_promotion_step_is_given_the_token_and_the_checkout_is_not() -> None:
    """The credential reaches ``gh`` through the step's env, and only there (#485).

    ``GH_TOKEN`` is the Actions-issued, job-scoped ``GITHUB_TOKEN`` — not a
    stored secret and not a PAT — forwarded to the one step that talks to the
    API. ``persist-credentials: false`` is the other half: the script never
    pushes, so the git layer loses the ability to. Together they are a real
    narrowing, and both are invisible to any test that executes the script,
    because both are properties of the workflow that invokes it.
    """
    workflow = WORKFLOW.read_text(encoding="utf-8")
    step = _promotion_step_lines(workflow.splitlines())

    assert any(line.strip() == "env:" for line in step), (
        f"the promotion step declares no `env:`, so `gh` has no token: {step}"
    )
    assert any(line.strip() == "GH_TOKEN: ${{ secrets.GITHUB_TOKEN }}" for line in step), (
        f"the promotion step must forward the job-scoped GITHUB_TOKEN as GH_TOKEN: {step}"
    )
    assert "persist-credentials: false" in workflow, (
        "the checkout keeps its push credential; the promotion goes through the "
        "API and the git layer needs no write authority"
    )


def test_ci_runs_pull_request_checks_only_for_the_integration_branch() -> None:
    """``ci.yml``'s ``pull_request`` trigger is narrowed to base ``dev`` (#485).

    A pull request opened by a workflow using ``GITHUB_TOKEN`` produces runs in
    an approval-required state, which nothing unattended can approve. The
    promotion PR's base is ``main``, so a ``pull_request: [main, ...]`` trigger
    raises a second, permanently unapproved run of the required check's name on
    the gated commit. Whether such a run blocks a required status check is
    unevidenced — this narrowing removes the question rather than answering it,
    and a later widening silently restores the deadlock risk.
    """
    assert _ci_trigger_branches("pull_request") == ["dev"], (
        f"ci.yml raises pull-request runs for "
        f"{_ci_trigger_branches('pull_request')}; only `dev` may raise them, or a "
        "bot-opened promotion PR gets an approval-gated duplicate of the check "
        "`main` requires"
    )
    assert "main" in _ci_trigger_branches("push"), (
        "ci.yml no longer runs the gate on pushes to main, so the narrowing above "
        "removed coverage rather than a duplicate"
    )


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
    for forbidden in ("git push", "git merge", "git tag", "gh pr create", "gh pr merge", "gh api"):
        assert forbidden not in shell, (
            f"the workflow runs `{forbidden}` directly; every mutation of a ref or a "
            f"pull request belongs in {SCRIPT.relative_to(REPO_ROOT)}, where the "
            "executed guard covers what it does"
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

    # `-f ` used to stand in for `--force`'s short spelling. It is also `gh
    # api`'s short flag for a field, so once the promotion went through the API
    # (#485) the ban would have fired on a call that forces nothing. Both halves
    # were fixed rather than either alone: the ban now names what it means, and
    # the script writes `--raw-field`, so neither a false red nor an over-broad
    # guard is left behind.
    for forbidden in ("--force", "--force-with-lease", "push -f", "agent_may_fix"):
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
        "the gate and, only on green, advance main"
    )
