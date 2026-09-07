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


class UnclassifiedStepError(AssertionError):
    """A ``steps:`` item this module could not classify.

    Raised, never swallowed. The whole point of the classifier below is that an
    item it cannot read is **louder** than one it can — three review cycles of
    #580 were spent on a recogniser that silently dropped what it did not match,
    so a second unpinned checkout stayed invisible while the count read one.
    """


#: A key line inside a step body. Deliberately narrow: anything a step may
#: legally contain that does not match this raises rather than being skipped.
_STEP_KEY = re.compile(r"^(?P<key>[A-Za-z_][A-Za-z0-9_.-]*):(?P<value>.*)$")

#: `run: |`, `run: >-`, and friends — a block scalar whose indented body is
#: arbitrary text, including text shaped like a step. Recognised so it can be
#: skipped wholesale; unrecognised block styles fall through to the refusal.
_BLOCK_SCALAR = re.compile(r"^[|>][0-9+-]*$")


def _unquote(value: str) -> str:
    """One matching pair of surrounding quotes removed; anything else untouched.

    `uses: "actions/checkout@v4"` is legal and is what defeated the second
    version of this guard. Only a *matching* pair is stripped, so a value with
    one stray quote stays as written and fails the comparison it is used in
    rather than being silently normalised into something that passes.
    """
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        return value[1:-1]
    return value


def _parse_steps(text: str) -> list[dict[str, object]]:
    """Every item under every ``steps:`` key in ``text``, classified or refused.

    A pure function over YAML text, so the spelling table that guards it is an
    executed regression test rather than mutation narrated in a docstring.

    **The closed set.** An item opens with a dash at the block's own indent and
    is a block mapping, spelled either way:

    .. code-block:: yaml

        - uses: actions/checkout@v4     # mapping starts on the dash line
        -                               # mapping starts on the next line
          uses: actions/checkout@v4

    Everything else — a flow item (``- {uses: …}``), a flow ``with:``, a bare
    scalar item, a line that is not ``key: value`` — raises
    :class:`UnclassifiedStepError`. That is the fail-closed property: an unreadable
    workflow makes the guard **red**, never quietly short. Returns one dict per
    step with its ``uses`` value (unquoted, or ``None``) and its ``with`` mapping.
    """
    lines = [line for line in text.splitlines() if line.strip()]
    steps: list[dict[str, object]] = []

    for index, line in enumerate(lines):
        header = re.match(r"^ *steps:(?P<rest>.*)$", line)
        if header is None:
            continue
        if header.group("rest").strip():
            raise UnclassifiedStepError(
                f"a `steps:` key carries its sequence inline ({line.strip()!r}); this module "
                "reads block sequences only — rewrite it as a block, or widen the closed set"
            )
        steps_indent = len(line) - len(line.lstrip())

        block: list[str] = []
        for following in lines[index + 1 :]:
            if len(following) - len(following.lstrip()) <= steps_indent:
                break
            block.append(following)
        if not block:
            raise UnclassifiedStepError(
                f"a `steps:` key has no block beneath it ({line.strip()!r}); a workflow this "
                "module cannot read must be red, not quietly short"
            )

        item_indent = len(block[0]) - len(block[0].lstrip())
        if not block[0].lstrip().startswith("-"):
            raise UnclassifiedStepError(
                f"a `steps:` block opens with a non-item line: {block[0]!r}"
            )

        # Split the block on dashes at the item indent; a deeper dash belongs to
        # a nested sequence inside one step and is that step's own business.
        bounds = [
            offset
            for offset, entry in enumerate(block)
            if len(entry) - len(entry.lstrip()) == item_indent and entry.lstrip().startswith("-")
        ]
        for position, opening in enumerate(bounds):
            closing = bounds[position + 1] if position + 1 < len(bounds) else len(block)
            steps.append(_classify(block[opening:closing], item_indent))

    return steps


def _classify(item: list[str], item_indent: int) -> dict[str, object]:
    """One ``steps:`` item, as ``{"uses": str | None, "with": {...}}``."""
    opener = re.match(r"^ *-(?P<rest>.*)$", item[0])
    assert opener is not None, f"not a step item: {item[0]!r}"
    rest = opener.group("rest")

    body: list[tuple[int, str]] = []
    if rest.strip():
        if rest.lstrip()[0] in "{[":
            raise UnclassifiedStepError(
                f"a `steps:` item is written in flow style ({item[0].strip()!r}); this module "
                "reads block mappings only — rewrite it as a block, or widen the closed set"
            )
        # The first key sits wherever its first non-space character actually is,
        # which is not always `dash + 2`: `-   uses:` is legal and indents by more.
        body_indent = item_indent + 1 + (len(rest) - len(rest.lstrip()))
        body.append((body_indent, rest.strip()))
        remainder = item[1:]
    else:
        if not item[1:]:
            raise UnclassifiedStepError(f"a `steps:` item has no body: {item[0]!r}")
        body_indent = len(item[1]) - len(item[1].lstrip())
        if body_indent <= item_indent:
            raise UnclassifiedStepError(f"a `steps:` item has no body: {item[0]!r}")
        remainder = item[1:]

    for entry in remainder:
        body.append((len(entry) - len(entry.lstrip()), entry.strip()))

    uses: str | None = None
    options: dict[str, str] = {}
    position = 0
    while position < len(body):
        indent, content = body[position]
        position += 1
        if indent != body_indent:
            continue  # a sub-value; its owning key consumed it below

        matched = _STEP_KEY.match(content)
        if matched is None:
            raise UnclassifiedStepError(
                f"a `steps:` item carries a line this module cannot read as `key: value`: "
                f"{content!r}"
            )
        key, value = matched.group("key"), matched.group("value").strip()

        if _BLOCK_SCALAR.match(value):
            while position < len(body) and body[position][0] > body_indent:
                position += 1
            continue

        if key == "uses":
            uses = _unquote(value)
        elif key == "with":
            if value:
                raise UnclassifiedStepError(
                    f"a step writes `with:` in flow style ({content!r}); this module reads block "
                    "mappings only — rewrite it as a block, or widen the closed set"
                )
            while position < len(body) and body[position][0] > body_indent:
                _, option = body[position]
                position += 1
                pair = _STEP_KEY.match(option)
                if pair is None:
                    raise UnclassifiedStepError(
                        f"unreadable line in a step `with:` block: {option!r}"
                    )
                options[pair.group("key")] = _unquote(pair.group("value").strip())

    return {"uses": uses, "with": options}


#: What a checkout step's `uses:` starts with. One spelling, used by the parse
#: and by the floor below, so the two can never drift apart and disagree about
#: what they are counting.
_CHECKOUT = "actions/checkout@"


def _checkout_steps_in(text: str) -> list[dict[str, object]]:
    """Every classified checkout step in ``text``, under a floor on the count.

    **The floor is the half that does not depend on this module reading YAML
    correctly.** Four review cycles of #580 each found a spelling the recogniser
    silently dropped — a two-line ``uses:``, a quoted value, a flow item, a bare
    dash, and finally a whole second job whose ``steps:`` was written inline. In
    every case it failed *open*: the extra step vanished and the count still read
    one. Each fix taught the parser one more shape, which is a bet that the next
    spelling has been imagined.

    This is not that bet. The number of steps classified as checkouts is compared
    against the number of times ``actions/checkout@`` simply *appears* in the
    text, and a shortfall raises. A spelling nobody has thought of cannot escape,
    because escaping means being mentioned and not counted, which is exactly what
    is measured. The parser may still fail to *read* a workflow; it can no longer
    fail to *notice* one.

    The cost is over-refusal — ``actions/checkout@`` inside a ``run:`` body, or in
    a string that is not a step, trips it. That is the fail-closed direction: a
    loud, diagnosable red on a legal edit, rather than a silent green on a
    dangerous one.
    """
    steps = _parse_steps(text)
    checkouts = [
        step
        for step in steps
        if isinstance(step["uses"], str) and step["uses"].startswith(_CHECKOUT)
    ]

    mentioned = text.count(_CHECKOUT)
    if len(checkouts) < mentioned:
        raise UnclassifiedStepError(
            f"{mentioned} occurrence(s) of `{_CHECKOUT}` appear in this workflow but only "
            f"{len(checkouts)} were classified as steps, so {mentioned - len(checkouts)} "
            "escaped the parse entirely — which is how an unpinned second checkout hides "
            "from the count (#580). Either a step is written in a shape this module does "
            "not read, or the name appears somewhere that is not a step."
        )
    return checkouts


def _ci_checkout_steps() -> list[dict[str, object]]:
    """Every ``actions/checkout`` step in ``ci.yml``, classified and floored.

    Read over ``_uncommented`` so a ``#`` line naming a key cannot satisfy the
    assertions, and derived from the file rather than restated here.
    """
    return _checkout_steps_in(_uncommented(CI_WORKFLOW.read_text(encoding="utf-8")))


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


#: A workflow holding exactly one pinned checkout, used as the control the
#: spellings below are grafted into. Its answer must differ from theirs, or the
#: table proves only that the parser runs.
_ONE_PINNED_CHECKOUT = """\
jobs:
  lint-and-test:
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0
      - name: Install uv
        uses: astral-sh/setup-uv@v3
"""

#: Every spelling of a *second*, unpinned `actions/checkout` step that has ever
#: escaped this guard, plus the ones that never did. Each must end red — either
#: counted (so the count assertion fails) or refused (so the parser raises).
#: Three of these five were live defects found in review, one per cycle.
_SECOND_CHECKOUT_SPELLINGS = {
    "one-line uses": "      - uses: actions/checkout@v4\n",
    "name then uses": "      - name: Again\n        uses: actions/checkout@v4\n",
    "double-quoted uses": '      - uses: "actions/checkout@v4"\n',
    "single-quoted uses": "      - uses: 'actions/checkout@v4'\n",
    "flow mapping item": "      - { uses: actions/checkout@v4 }\n",
    "bare dash, mapping below": "      -\n        uses: actions/checkout@v4\n",
    "extra spaces after dash": "      -   uses: actions/checkout@v4\n",
    "full sha pin": "      - uses: actions/checkout@8f4b7f84864484a7bf31766abe9204da3cbe65b3\n",
}


def test_the_ci_checkout_supplies_the_ref_the_cycle_start_guard_reads() -> None:
    """``ci.yml``'s checkout must fetch a ref naming the release role (#580).

    ``tests/unit/test_release_version_cycle.py`` reads three things off that ref
    — ``rev-parse --verify``, the manifest blob, and ``diff --cached`` against
    its tree — and where no such ref exists it returns ``NO_RELEASE_REF``, which
    is in ``SKIPPING``. A bare ``actions/checkout@v4`` fetches only the ref being
    built, so on every ``push: dev`` run the start-of-cycle guard **skipped**,
    and the only control left on a missing version bump was the builder's local
    gate — client-side, on whichever machine happened to push, while the spine's
    posture puts the controls of record in CI.

    That is not hypothetical: nightly promotion run 34046398127 (2026-09-06)
    failed ``Kind.EQUAL`` on ``dev`` roughly a day after the offending landing,
    having been green on every push in between, because the nightly is the one
    workflow that fetches full history.

    The fix is the checkout action's own key, not a hand-written fetch step: a
    narrow ``--depth=1`` fetch of the release branch would serve the three reads
    (none needs history), but it re-implements ref fetching and adds a
    ``harness.yaml`` read inside CI, which P2 refuses while a native option
    exists. Measured 2026-09-07: 1781 commits, 10 remote heads, 22 MB ``.git``.
    """
    checkouts = _ci_checkout_steps()

    assert len(checkouts) == 1, (
        f"ci.yml declares {len(checkouts)} `actions/checkout` steps; this guard pins the "
        "fetch depth of exactly one, so a second checkout would be unpinned and could "
        "reintroduce the shallow clone this ticket removed"
    )
    options = checkouts[0]["with"]
    assert isinstance(options, dict)
    assert options.get("fetch-depth") == "0", (
        f"ci.yml's checkout declares fetch-depth={options.get('fetch-depth')!r}, so no ref "
        "naming the release role is fetched and the start-of-cycle version guard reports "
        "NO_RELEASE_REF and skips on every push — a false green, not a pass (#580)"
    )


def test_the_control_workflow_reads_as_one_pinned_checkout() -> None:
    """The table below is worthless if its baseline already fails.

    Two identically-failed runs compare equal (#466): without this, every row
    of ``test_no_spelling_of_a_second_checkout_escapes_the_count`` could be red
    because the *fixture* is malformed rather than because the spelling was
    caught, and the table would score a perfect kill rate while measuring
    nothing.
    """
    steps = _parse_steps(_ONE_PINNED_CHECKOUT)
    checkouts = [
        step
        for step in steps
        if isinstance(step["uses"], str) and step["uses"].startswith("actions/checkout@")
    ]

    assert len(steps) == 2, f"the control should classify two steps, got {len(steps)}"
    assert len(checkouts) == 1
    assert checkouts[0]["with"] == {"fetch-depth": "0"}


@pytest.mark.parametrize("spelling", sorted(_SECOND_CHECKOUT_SPELLINGS))
def test_no_spelling_of_a_second_checkout_escapes_the_count(spelling: str) -> None:
    """A second unpinned checkout must be counted or refused — never dropped.

    This is the regression table for #580's central defect. The guard's
    recogniser was found vacuous in **three consecutive review cycles**, each
    time by a spelling its author had not thought to try: the two-line
    ``- name:``/``uses:`` form, a quoted ``uses:`` value, and both a flow-mapping
    item and a bare dash with the mapping below. Every one of them failed
    *open* — the extra step vanished from the parse and the count still read
    one — which is the only direction that matters.

    The classifier replaces enumeration of spellings with a closed set plus a
    refusal, so the property asserted here is not "each known spelling is
    matched" but "**no** spelling escapes": either the step is classified, and
    the count rises to two, or it cannot be read, and
    :class:`UnclassifiedStepError` is raised. Both are red. A future spelling nobody
    has imagined lands in the second bucket by construction.
    """
    injected = _ONE_PINNED_CHECKOUT.replace(
        "      - name: Install uv\n",
        _SECOND_CHECKOUT_SPELLINGS[spelling] + "      - name: Install uv\n",
    )
    assert injected != _ONE_PINNED_CHECKOUT, "the spelling was never grafted into the control"

    try:
        checkouts = _checkout_steps_in(injected)
    except UnclassifiedStepError:
        return  # refused, which is red for the guard — the fail-closed arm
    assert len(checkouts) == 2, (
        f"a second checkout spelled {spelling!r} was neither counted nor refused: the parse "
        f"found {len(checkouts)} checkout step(s), so this spelling can hide an unpinned "
        "checkout from the count assertion (#580)"
    )


#: Where a second checkout can hide that is **not** inside the tracked job.
#: Cycle 4 shipped a table whose every row injected a step into the one job the
#: control declares, so a whole second job was outside everything it measured —
#: the blind spot that let `steps:` written inline escape. Each value is appended
#: to the control, so the escape is structural rather than a different spelling
#: of the same step.
_SECOND_CHECKOUT_ELSEWHERE = {
    "second job, block steps": """\
  other-job:
    steps:
      - uses: actions/checkout@v4
""",
    "second job, inline steps": """\
  other-job:
    steps: [{uses: actions/checkout@v4}, {name: x, run: echo hi}]
""",
    "second job, steps with no block": """\
  other-job:
    steps:
""",
    "name buried in a run body": """\
  other-job:
    steps:
      - name: Print
        run: |
          echo actions/checkout@v4
""",
}


@pytest.mark.parametrize("location", sorted(_SECOND_CHECKOUT_ELSEWHERE))
def test_no_checkout_outside_the_tracked_job_escapes_the_count(location: str) -> None:
    """A checkout the parser cannot reach must still be noticed.

    The rows above are not spellings of a step; they are *places a step can be*
    that the previous table could not see, because every one of its rows edited
    the single job its control declares. A second job whose ``steps:`` is written
    inline is what failed cycle 4, and it failed **open**.

    Each row must end red: counted, or refused. The last row is deliberately not
    a step at all — ``actions/checkout@v4`` inside a ``run:`` body — and is here
    to pin the floor's cost honestly. It refuses, which is over-refusal on a
    legal workflow, and that is the direction this guard is willing to be wrong
    in. A row that silently passed would mean the floor had been quietly widened
    into uselessness.
    """
    injected = _ONE_PINNED_CHECKOUT + _SECOND_CHECKOUT_ELSEWHERE[location]
    assert injected != _ONE_PINNED_CHECKOUT, "the location was never appended to the control"

    try:
        checkouts = _checkout_steps_in(injected)
    except UnclassifiedStepError:
        return  # refused — the fail-closed arm

    assert len(checkouts) == 2, (
        f"a checkout at {location!r} was neither counted nor refused: the parse found "
        f"{len(checkouts)} checkout step(s), so it can hide from the count assertion (#580)"
    )


def test_the_floor_notices_what_the_parser_cannot_read() -> None:
    """The floor must be doing work the classifier is not.

    Without this, the floor could be dead code: every row above might be red
    because the *parser* refused it, leaving the count comparison never decisive.
    Here the parser reads the workflow cleanly and returns one checkout, while the
    text mentions two — so only the floor can object, and the message must name
    the shortfall rather than blame a shape.
    """
    hidden = _ONE_PINNED_CHECKOUT + """\
  other-job:
    steps:
      - name: Print
        run: echo actions/checkout@v4
"""
    assert len(_parse_steps(hidden)) == 3, "the parser should read this workflow without refusing"

    with pytest.raises(UnclassifiedStepError, match="escaped the parse"):
        _checkout_steps_in(hidden)


def test_an_inline_steps_sequence_is_refused_by_name_not_only_by_the_floor() -> None:
    """The parser and the floor must be distinguishable, not merely both red.

    Reverting the ``steps:`` header refusal on its own left the whole suite
    green: the floor caught the escape, so nothing pinned the parser's own
    refusal and that line could have been deleted without a single test
    objecting. Two defences that only ever fire together are one defence and
    one unpinned line.

    So this asserts *which* arm answers. An inline ``steps:`` sequence must be
    refused by the parser, naming the shape — the floor's shortfall message is
    the wrong answer here even though it is also red, because it means the
    parser silently skipped a block it should have refused. The match is on the
    word that discriminates the two messages, which is the instrument; without
    it the mechanisms are indistinguishable (#580, cycle 4).
    """
    inline = _ONE_PINNED_CHECKOUT + "  other-job:\n    steps: [{uses: actions/checkout@v4}]\n"

    with pytest.raises(UnclassifiedStepError, match="inline"):
        _checkout_steps_in(inline)


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
