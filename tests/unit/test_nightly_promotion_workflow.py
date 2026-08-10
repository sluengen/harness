"""Contract guards for the deterministic nightly ``dev → staging`` promotion.

Two properties, deliberately in two tests. The first pins the workflow's shape
— schedule, concurrency, permissions, gate invocation, and the absence of any
automated repair path (#378). The second pins that the verb calls inside it can
resolve ``--repo`` at all: the workspace allowlist fails closed, so a runner
that never exports ``HARNESS_WORKSPACE_ROOTS`` gets an exit-2 refusal from every
verb (#390). It **derives** the call sites from the workflow text rather than
listing them, so a verb call added later is covered the day it lands.

That derivation reads *logical* lines, not physical ones (#391). Shell folds a
trailing backslash into the following line, and this workflow already writes one
call that way, so a ``--repo`` sitting on a continuation line is the likeliest
shape for the next call added by copying the file's own idiom — and matching per
physical line never derived it at all, so every per-call assertion below simply
never saw it. Each derived call still reports the line number of its **first**
physical line, which is the one an author can go and find.

The derivation is also indifferent to flag *order* (#393). Its verb span used to
stop at the first character outside ``[a-z -]``, so a ``--repo`` written after
any flag carrying a quote, a ``$``, a digit or an underscore escaped it — in the
wrapped and the single-line form alike, which is what showed line-basedness was
never that hole's cause.

And to how the flag is joined to its argument (#394). Typer and click accept
``--repo=<arg>`` as readily as the spaced form, and that spelling carries no
whitespace, so a pattern requiring ``--repo\\s+`` derived nothing from it at all
— the silent direction again, and the third distinct way one flag could go
unseen. Each of the three was a different property of the same pattern, which is
why the coverage claim below is executable rather than prose.

The property is a module-level function rather than a test body because the
coverage tests below feed it synthetic sources. They exist to pin *this* body's
behaviour, so they have to call it; a second copy of the rule written for them
would let the two drift, and only the copy would be under test.

Whether the exported allowlist actually admits the ``--repo`` argument is not a
text property and is not asserted here — that is
``tests/integration/test_nightly_promotion_workspace_allowlist.py``, which
executes the workflow's own export line and feeds the result to the production
resolver.
"""

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "nightly-staging-promotion.yml"

#: A ``harness <verb…> [flags…] --repo <arg>`` invocation. The verb is captured
#: only so a failure names the call site; the ``--repo`` argument is what is
#: asserted on. The span between the two is deliberately in two parts (#393):
#:
#: * the **verb** is a greedy run of whitespace-separated words that do not begin
#:   with ``-``, so the captured name stays the subcommand path. Greedy is what
#:   stops it collapsing to ``promote`` and losing the known-call-site floor.
#: * the **flags** are any further tokens, stopping at a shell command separator
#:   and at a fresh ``harness`` invocation. Both bounds keep each ``--repo``
#:   attributed to the call that actually passes it — the separator because the
#:   next command's flags are not this one's, and the lookahead because folding
#:   can put two ``harness`` calls on one logical line.
#:
#: ``#`` is deliberately absent from the separator set: ``${BASE#prefix}`` and a
#: quoted ``"issue #383"`` both carry a bare ``#``, and treating it as a boundary
#: is the mistake #383 paid for. The cost is that a commented-out invocation is
#: still derived — over-derivation, which reddens CI rather than hiding a call.
#:
#: ``--repo`` is joined to its argument by whitespace **or** a single ``=``
#: (#394), the two spellings click accepts. The alternation is deliberately
#: ``(?:\s+|=)`` rather than a character class: ``[\s=]+`` would also swallow
#: ``--repo = /tmp`` and ``--repo =/tmp``, where click reads the argument as
#: ``=`` and ``=/tmp`` respectively — so the guard would assert against a value
#: no verb receives. The ``=`` is consumed, never captured, or every correctly
#: written glued call would be refused for an argument it does not pass.
#:
#: The flag span is **greedy**, which is what makes a repeated ``--repo``
#: resolve to the *last* one written — the value click itself uses. Laziness
#: resolved it to the first, so ``--repo "$GITHUB_WORKSPACE" --repo /tmp`` went
#: green on a call that exits 2 on the runner. That was already true of the
#: all-spaced spelling before #394; admitting ``=`` would have extended it to a
#: second spelling, which is how it was found.
_REPO_RESOLVING_CALL = re.compile(
    r"harness"
    r"(?P<verb>(?:\s+[a-z][a-z-]*)+)"
    r"(?:\s+(?!harness\b)[^\s&|;]+)*"
    r"\s+--repo(?:\s+|=)(?P<arg>\S+)"
)

#: The allowlist assignment the promotion step must export before any verb runs.
_ALLOWLIST_EXPORT_PREFIX = "export HARNESS_WORKSPACE_ROOTS="

#: The one ``--repo`` argument the export admits: byte-identical to the root it
#: allowlists, so no ``working-directory:`` or stray ``cd`` can make the two
#: disagree.
_ALLOWED_REPO_ARG = '"$GITHUB_WORKSPACE"'

#: A call site the derivation must find. Without it, a regex that stops matching
#: yields an empty set and every assertion below passes vacuously.
_KNOWN_CALL_SITE = "promote start"


def _logical_lines(lines: list[str]) -> list[tuple[int, str]]:
    """Fold trailing-backslash continuations into the line that starts them.

    Each entry is ``(first physical line number, folded text)``. The number is
    the *first* physical line deliberately: it is where the invocation is
    written, so it is the line a failure message can send someone to.
    """
    folded: list[tuple[int, str]] = []
    buffered: str | None = None
    start = 0
    for number, line in enumerate(lines, start=1):
        text = line.rstrip()
        continues = text.endswith("\\")
        if continues:
            text = text[:-1]
        if buffered is None:
            buffered, start = text, number
        else:
            buffered = f"{buffered} {text.strip()}"
        if not continues:
            folded.append((start, buffered))
            buffered = None
    if buffered is not None:  # a trailing backslash on the last line
        folded.append((start, buffered))
    return folded


def _repo_resolving_calls(lines: list[str]) -> list[tuple[int, str, str]]:
    """Derive call sites as ``(line number, verb, --repo argument)``.

    ``finditer`` rather than ``search``: folding can bring two chained calls onto
    one logical line, and deriving only the first would be a coverage hole that
    the folding itself introduced.

    What this covers, stated as what it is rather than as "every call site" — the
    claim it carried before #393, which was false of the implementation beneath
    it. A call site is derived when it is written as ``harness`` followed by one
    or more subcommand words, then any run of tokens carrying no shell command
    separator and opening no fresh ``harness`` invocation, then ``--repo`` and
    its argument. So flag *order* does not matter, nor whether a backslash
    continuation splits the invocation across physical lines, nor whether the
    flag is joined to its argument by whitespace or by ``=`` (#394), nor whether
    the binary is named by path — ``/usr/bin/harness promote pr --repo …`` is
    derived and attributed to itself.

    A call passing ``--repo`` more than once resolves to the **last** one, in
    either spelling — the value click itself uses for a non-multiple option, so
    the guard asserts against the argument the verb will actually receive.

    What is **not** derived, each pinned by ``_UNDERIVED_SHAPES`` rather than
    stated here and trusted: a ``--repo`` supplied through a shell variable
    instead of written at the call site; a glued ``--repo=`` with an *empty*
    value, which leaves nothing for the argument span to capture; and a
    ``--repo`` belonging to a *different* command after a separator, which is a
    refusal to guess rather than a gap.

    Over-derivation, which fails closed: a commented-out invocation is derived,
    and so is a token merely ending in ``harness`` such as ``myharness``.
    """
    return [
        (number, match.group("verb").strip(), match.group("arg"))
        for number, text in _logical_lines(lines)
        for match in _REPO_RESOLVING_CALL.finditer(text)
    ]


def _allowlist_export_lines(lines: list[str]) -> list[int]:
    """Line numbers of the allowlist export, on the same numbering as the calls."""
    return [
        number
        for number, text in _logical_lines(lines)
        if text.strip().startswith(_ALLOWLIST_EXPORT_PREFIX)
    ]


def _assert_every_call_runs_under_an_exported_allowlist(lines: list[str]) -> None:
    """Assert the allowlist property over ``lines``. Raises ``AssertionError``."""
    calls = _repo_resolving_calls(lines)
    # Floor: a derivation that silently stops matching must be red, not green.
    assert calls, "no `harness … --repo` call site was derived from the workflow"
    assert _KNOWN_CALL_SITE in {verb for _, verb, _ in calls}, (
        f"the derivation lost its known call site `harness {_KNOWN_CALL_SITE}`; "
        f"it found {sorted({verb for _, verb, _ in calls})}"
    )

    exports = _allowlist_export_lines(lines)
    assert exports, (
        f"the workflow never exports the workspace allowlist; without "
        f"{_ALLOWLIST_EXPORT_PREFIX} every verb refuses with exit 2 — a runner has "
        f"no ~/bin/harness wrapper to pin it"
    )

    for number, verb, arg in calls:
        assert min(exports) < number, (
            f"`harness {verb}` at line {number} runs before the allowlist export at "
            f"line {min(exports)}; the export has to precede the first verb call"
        )
        assert arg == _ALLOWED_REPO_ARG, (
            f"`harness {verb}` at line {number} passes --repo {arg}, which is not the "
            f"allowlisted root {_ALLOWED_REPO_ARG}"
        )


def test_nightly_promotion_workflow_is_a_bounded_deterministic_staging_hop() -> None:
    """The scheduler gates a candidate and never contains an automated repair path."""
    assert WORKFLOW.is_file(), "the nightly dev-to-staging promotion workflow must exist (#378)"
    workflow = WORKFLOW.read_text(encoding="utf-8")

    assert 'cron: "0 14 * * *"' in workflow, "14:00 UTC is midnight in Australia/Brisbane"
    assert "workflow_dispatch:" in workflow
    assert "nightly-dev-to-staging" in workflow
    assert "cancel-in-progress: false" in workflow
    assert "contents: write" in workflow
    assert "fetch-depth: 0" in workflow
    assert 'harness promote start --repo "$GITHUB_WORKSPACE" --from dev --to staging' in workflow
    assert "git config user.name" in workflow and "git config user.email" in workflow
    assert 'if [ "$status" != "gate_pending" ]' in workflow
    assert 'cd "$worktree"' in workflow and "bash scripts/verify.sh" in workflow
    assert 'harness promote continue --repo "$GITHUB_WORKSPACE"' in workflow
    assert 'if [ "$status" != "pr_ready" ]' in workflow
    assert 'harness promote pr --repo "$GITHUB_WORKSPACE"' in workflow
    assert "git push" not in workflow
    assert "agent_may_fix" not in workflow


def test_every_verb_call_runs_under_an_already_exported_workspace_allowlist() -> None:
    """Each derived ``--repo`` call site is preceded by the allowlist export (#390)."""
    _assert_every_call_runs_under_an_exported_allowlist(
        WORKFLOW.read_text(encoding="utf-8").splitlines()
    )


# --- Coverage of the derivation itself, on synthetic sources (#391) -----------
#
# The workflow is the one real input, and it is correct — so it can only ever
# show the property holding. These sources show what the property *refuses*,
# through the same function the test above calls.

#: A well-formed single-line call, carrying the known call site the floor wants.
_GOOD_CALL = 'uv run harness promote start --repo "$GITHUB_WORKSPACE" --from dev --to staging'

#: The allowlist export, written exactly as the workflow writes it.
_EXPORT = f'{_ALLOWLIST_EXPORT_PREFIX}"$GITHUB_WORKSPACE"'

#: The first physical line of a call wrapped in the workflow's own idiom — the
#: shape that escaped the derivation entirely before #391.
_WRAPPED_HEAD = "uv run harness promote status \\"

#: Flags written between the verb and ``--repo``, one per character class the
#: pre-#393 verb span could not cross: a quote and a ``$``, a digit, and an
#: underscore. The hole was never about one spelling, so neither is its guard.
_INTERVENING_FLAGS = ['--promotion-id "$id"', "--gate-exit 0", "--gate_log run.log"]

#: Shapes ``_repo_resolving_calls``' docstring names as **not** derived, and the
#: near-neighbours it names as derived. Parametrized so the residual list
#: measures itself rather than being read: #393 first shipped a residual clause
#: that was simply false of the code beneath it, and reading is what missed it.
_UNDERIVED_SHAPES = [
    "uv run harness promote pr $REPO_FLAG",
    "uv run harness promote start && some_tool --repo /tmp",
    # The nearest neighbour of the shape #394 closed, measured rather than
    # assumed: an *empty* glued value has nothing for ``\S+`` to capture, so it
    # escapes exactly as the whole glued spelling used to. Unchanged by #394
    # rather than left by it — the pre-change pattern missed it too — and it is
    # the fail-open direction, so it is stated here instead of being discovered.
    "uv run harness promote pr --repo= /tmp",
]

#: The anti-vacuity companion. Without it every case above would also pass
#: against a ``_step`` that produced nothing derivable at all.
_DERIVED_SHAPES = [
    "uv run harness promote pr --repo /tmp",
    "/usr/bin/harness promote pr --repo /tmp",
    "uv run harness promote start && harness promote pr --repo /tmp",
    'uv run harness promote pr --note "issue #383" --repo /tmp',
    # Moved up from ``_UNDERIVED_SHAPES`` by #394: the ``=`` spelling Typer and
    # click accept as readily as the spaced one. This entry *is* that ticket's
    # red-first evidence, so it stays here rather than being folded into the
    # tests below.
    'uv run harness promote pr --repo="$GITHUB_WORKSPACE"',
]


def _step(*body: str) -> list[str]:
    """A promotion ``run:`` block carrying ``body``, indented as the workflow is."""
    return [
        "      - name: Promote the gated candidate",
        "        shell: bash",
        "        run: |",
        "          set -euo pipefail",
        *(f"          {line}" for line in body),
    ]


def _line_of(lines: list[str], body_line: str) -> int:
    """The 1-based physical line number ``_step`` gave ``body_line``."""
    found = [number for number, line in enumerate(lines, start=1) if line.strip() == body_line]
    assert len(found) == 1, f"expected exactly one {body_line!r} in the source, found {found}"
    return found[0]


def test_a_repo_argument_on_a_continuation_line_is_derived_and_refused() -> None:
    """AC-1: the workflow's own wrapping idiom is no longer an escape route."""
    lines = _step(_EXPORT, _GOOD_CALL, _WRAPPED_HEAD, '  --repo /tmp --promotion-id "$id"')

    with pytest.raises(AssertionError) as refused:
        _assert_every_call_runs_under_an_exported_allowlist(lines)

    assert "--repo /tmp" in str(refused.value)


def test_a_wrapped_call_is_reported_at_its_first_physical_line() -> None:
    """AC-2: the number points at the invocation, not at its continuation."""
    lines = _step(_EXPORT, _GOOD_CALL, _WRAPPED_HEAD, '  --repo /tmp --promotion-id "$id"')

    with pytest.raises(AssertionError) as refused:
        _assert_every_call_runs_under_an_exported_allowlist(lines)

    assert f"line {_line_of(lines, _WRAPPED_HEAD)}" in str(refused.value)


@pytest.mark.parametrize("flag", _INTERVENING_FLAGS)
def test_a_repo_argument_written_after_another_flag_is_derived_and_refused(flag: str) -> None:
    """AC-1: flag *order* is not an escape route either, on one physical line.

    #391 closed the line-based hole; this is the reach-based one it left. The
    verb span stopped at the first character outside ``[a-z -]``, so any flag
    carrying a quote, a ``$``, a digit or an underscore ended the match before
    ``--repo`` was ever reached.
    """
    lines = _step(_EXPORT, _GOOD_CALL, f"uv run harness promote status {flag} --repo /tmp")

    with pytest.raises(AssertionError) as refused:
        _assert_every_call_runs_under_an_exported_allowlist(lines)

    assert "--repo /tmp" in str(refused.value)


@pytest.mark.parametrize("flag", _INTERVENING_FLAGS)
def test_a_repo_argument_after_another_flag_on_a_continuation_line_is_refused(flag: str) -> None:
    """AC-1, in the workflow's own wrapping idiom: the two holes compose.

    Measured identical in both forms during #391's review, which is what showed
    line-basedness was never this one's cause.
    """
    lines = _step(_EXPORT, _GOOD_CALL, f"uv run harness promote status {flag} \\", "  --repo /tmp")

    with pytest.raises(AssertionError) as refused:
        _assert_every_call_runs_under_an_exported_allowlist(lines)

    assert "--repo /tmp" in str(refused.value)


def test_a_repo_argument_glued_by_an_equals_sign_is_derived_and_refused() -> None:
    """AC-1: ``--repo=<arg>`` is the same flag, and the guard has to see it (#394).

    Typer and click accept the glued spelling as readily as the spaced one, and
    it carries no whitespace at all — so a pattern keyed on ``--repo\\s+`` derived
    nothing from it and every per-call assertion below simply never ran. Silent,
    and in the direction this module exists to close: the argument reaches the
    runner, where an unallowlisted root is an exit-2 refusal from the verb.
    """
    lines = _step(_EXPORT, _GOOD_CALL, "uv run harness promote status --repo=/tmp")

    with pytest.raises(AssertionError) as refused:
        _assert_every_call_runs_under_an_exported_allowlist(lines)

    assert "--repo /tmp" in str(refused.value)


def test_a_glued_repo_argument_on_a_continuation_line_is_refused() -> None:
    """AC-1, in the workflow's own wrapping idiom: the two spellings compose.

    The folding of #391 and the gluing of #394 are independent, so the wrapped
    form needs its own case rather than being argued from the single-line one —
    the same reasoning that gave flag order two tests in #393.
    """
    lines = _step(_EXPORT, _GOOD_CALL, "uv run harness promote status \\", "  --repo=/tmp")

    with pytest.raises(AssertionError) as refused:
        _assert_every_call_runs_under_an_exported_allowlist(lines)

    assert "--repo /tmp" in str(refused.value)


def test_a_glued_call_naming_the_allowlisted_root_is_accepted() -> None:
    """AC-3: the ``=`` is *consumed*, not captured — so a correct call still passes.

    The discriminator between widening the pattern and merely making it refuse
    everything glued. A form that kept the separator inside the group would
    derive ``=$GITHUB_WORKSPACE``, which matches no allowlisted root, and the
    guard would redden the workflow over a call written exactly as intended.
    Refusing the bad shape proves nothing about that; only accepting the good
    one does.
    """
    _assert_every_call_runs_under_an_exported_allowlist(
        _step(_EXPORT, _GOOD_CALL, f"uv run harness promote pr --repo={_ALLOWED_REPO_ARG}")
    )


#: A repeated ``--repo`` whose **last** occurrence is not the allowlisted root,
#: in both spellings. click resolves a non-multiple option to the last value, so
#: every one of these exits 2 on the runner and the guard has to refuse it.
_REPEATED_ENDING_UNALLOWLISTED = [
    f"uv run harness promote pr --repo={_ALLOWED_REPO_ARG} --repo /tmp",
    f"uv run harness promote pr --repo {_ALLOWED_REPO_ARG} --repo /tmp",
]

#: The same shapes with the orderings swapped: the last occurrence *is* the
#: allowlisted root, so click passes it and the guard must accept.
_REPEATED_ENDING_ALLOWLISTED = [
    f"uv run harness promote pr --repo=/tmp --repo {_ALLOWED_REPO_ARG}",
    f"uv run harness promote pr --repo /tmp --repo {_ALLOWED_REPO_ARG}",
]


@pytest.mark.parametrize("repeated", _REPEATED_ENDING_UNALLOWLISTED)
def test_a_repeated_repo_flag_resolves_to_the_last_one_written(repeated: str) -> None:
    """The flag span is greedy, so attribution matches click's last-wins (#394).

    A lazy span resolved a repeated ``--repo`` to the **first** occurrence, which
    is the wrong end: click passes the last. So a call ending in an
    unallowlisted root went green here and exited 2 on the runner — the silent
    direction this module exists to close.

    The all-spaced case in this list was already wrong before #394; admitting
    ``=`` would have extended the same hole to a second spelling, which is how it
    was found. Both are pinned, so neither end of the class can reopen.
    """
    lines = _step(_EXPORT, _GOOD_CALL, repeated)

    with pytest.raises(AssertionError) as refused:
        _assert_every_call_runs_under_an_exported_allowlist(lines)

    assert "--repo /tmp" in str(refused.value)


@pytest.mark.parametrize("repeated", _REPEATED_ENDING_ALLOWLISTED)
def test_a_repeated_repo_flag_ending_in_the_allowlisted_root_is_accepted(repeated: str) -> None:
    """The companion direction: last-wins, not merely "refuse anything repeated".

    Without this, a derivation that flagged every repeated ``--repo`` regardless
    of value would satisfy the test above while refusing calls click runs
    correctly — the same reason the glued spelling needs an accept-direction
    case as well as a refuse-direction one.
    """
    _assert_every_call_runs_under_an_exported_allowlist(_step(_EXPORT, _GOOD_CALL, repeated))


def test_a_refused_call_names_only_its_subcommand_path() -> None:
    """AC-2: widening the span must not fold the intervening flags into the verb.

    Asserted on a *synthetic* source rather than the workflow, deliberately. All
    three real call sites write ``--repo`` directly after the verb, so they
    derive identically under the two-part span and under the cheaper degradation
    that simply lets the verb run to ``--repo`` — a check over the real file
    could not tell the two apart and would be decoration. The difference is only
    ever visible where a flag intervenes, and it is visible in the one place the
    verb is *for*: the message that sends an author to the call site.
    """
    lines = _step(_EXPORT, _GOOD_CALL, 'uv run harness promote status --id "$x" --repo /tmp')

    with pytest.raises(AssertionError) as refused:
        _assert_every_call_runs_under_an_exported_allowlist(lines)

    assert "`harness promote status` at line" in str(refused.value)


def test_a_repo_argument_is_attributed_to_its_own_harness_invocation() -> None:
    """AC-2: the widened span may not reach across a *later* ``harness``.

    Two chained invocations where only the second carries ``--repo``. A span
    that crossed the second ``harness`` would still refuse the argument — but
    blame the first call for it, which is precisely the per-call attribution
    ``finditer`` was added for in #391.
    """
    lines = _step(
        _EXPORT,
        _GOOD_CALL,
        "uv run harness promote status && uv run harness promote pr --repo /tmp",
    )

    with pytest.raises(AssertionError) as refused:
        _assert_every_call_runs_under_an_exported_allowlist(lines)

    assert "`harness promote pr`" in str(refused.value)


def test_a_call_on_the_final_continuation_line_is_derived() -> None:
    """AC-3: the trailing-buffer flush in ``_logical_lines`` is load-bearing.

    A source whose last physical line still ends in a backslash leaves the fold
    buffered. Without the flush the whole invocation is dropped and the guard
    goes green on a call it never saw — the silent direction, which is the one
    this module exists to close.
    """
    lines = _step(_EXPORT, _GOOD_CALL, "uv run harness promote pr \\", "  --repo /tmp \\")

    with pytest.raises(AssertionError) as refused:
        _assert_every_call_runs_under_an_exported_allowlist(lines)

    assert "--repo /tmp" in str(refused.value)


@pytest.mark.parametrize("shape", _UNDERIVED_SHAPES)
def test_a_shape_the_docstring_calls_underived_really_is(shape: str) -> None:
    """AC-4: every clause of the stated coverage is measured, not asserted in prose.

    A docstring is the one part of a guard nothing runs. #393 exists partly
    because the previous one overclaimed; its own first draft then *under*
    claimed, naming a by-path invocation as underived when it is derived. Both
    directions are the same defect — a coverage statement no test can falsify.
    """
    assert _repo_resolving_calls(_step(shape)) == []


@pytest.mark.parametrize("shape", _DERIVED_SHAPES)
def test_a_shape_the_docstring_calls_derived_really_is(shape: str) -> None:
    """The companion floor: the cases above must fail to derive for their own reason.

    Every ``== []`` above is satisfied by a derivation that has stopped working
    altogether, so each underived shape is paired with the nearest shape that
    must still be found — including the by-path invocation the first draft got
    backwards, and a genuine second ``harness`` call after a separator.
    """
    assert _repo_resolving_calls(_step(shape))


def test_a_second_harness_call_behind_no_separator_is_attributed_to_itself() -> None:
    """The ``(?!harness\\b)`` lookahead, on the one shape the separator bound misses.

    Found by a *survivor*: once the flag span stopped at ``&``, ``;`` and ``|``,
    dropping the lookahead killed nothing, because every chained shape then under
    test was separator-chained. It is not redundant — it is what a trailing
    comment needs, and ``#`` is deliberately not a separator (see the pattern).
    Without it the argument is blamed on ``promote pr``, the call that does not
    pass it; with it the commented-out ``promote status`` answers for its own.
    """
    commented_out = "uv run harness promote pr # harness promote status --repo /tmp"
    lines = _step(_EXPORT, _GOOD_CALL, commented_out)

    with pytest.raises(AssertionError) as refused:
        _assert_every_call_runs_under_an_exported_allowlist(lines)

    assert "`harness promote status` at line" in str(refused.value)


def test_another_commands_repo_flag_is_not_attributed_to_the_harness_call() -> None:
    """The flag span may not cross a shell command separator.

    The widening's own new failure class: the pre-#393 verb span could not cross
    ``&``, ``;`` or ``|`` either, so letting the flag run past one would hand a
    *different* command's ``--repo`` to the harness call and redden the workflow
    over an argument no verb ever sees. ``#`` is deliberately **not** a stop
    character — ``${BASE#prefix}`` and a quoted ``"issue #383"`` both carry a
    bare one, and #383 is the tick that paid for treating ``#`` as a boundary.
    """
    lines = _step(_EXPORT, _GOOD_CALL, "uv run harness promote start && some_tool --repo /tmp")

    _assert_every_call_runs_under_an_exported_allowlist(lines)


def test_a_wrapped_call_naming_the_allowlisted_root_is_accepted() -> None:
    """Folding has to *derive* the wrapped call, not blanket-refuse the shape."""
    _assert_every_call_runs_under_an_exported_allowlist(
        _step(
            _EXPORT,
            _GOOD_CALL,
            _WRAPPED_HEAD,
            f'  --repo {_ALLOWED_REPO_ARG} --promotion-id "$id"',
        )
    )


def test_a_second_call_on_the_same_folded_line_is_derived() -> None:
    """Folding merges physical lines, so one logical line can carry two calls.

    Deriving only the first would be a hole the folding itself opened: before
    #391 these were two physical lines and each was matched on its own.
    """
    lines = _step(
        _EXPORT,
        _GOOD_CALL,
        'uv run harness promote pr --repo "$GITHUB_WORKSPACE" && \\',
        "  uv run harness promote status --repo /tmp",
    )

    with pytest.raises(AssertionError) as refused:
        _assert_every_call_runs_under_an_exported_allowlist(lines)

    assert "--repo /tmp" in str(refused.value)


def test_a_single_line_call_naming_another_root_is_still_refused() -> None:
    """AC-3, #390's `--repo .` kill: folding did not cost the single-line coverage."""
    lines = _step(_EXPORT, _GOOD_CALL, 'uv run harness promote pr --repo . --id "$id"')

    with pytest.raises(AssertionError) as refused:
        _assert_every_call_runs_under_an_exported_allowlist(lines)

    assert "--repo ." in str(refused.value)


def test_a_step_that_never_exports_the_allowlist_is_refused() -> None:
    """AC-3, #390's drop-the-export kill."""
    with pytest.raises(AssertionError) as refused:
        _assert_every_call_runs_under_an_exported_allowlist(_step(_GOOD_CALL))

    assert _ALLOWLIST_EXPORT_PREFIX in str(refused.value)


def test_an_export_below_the_first_call_is_refused() -> None:
    """AC-3, #390's move-the-export kill: ordering, not mere presence."""
    with pytest.raises(AssertionError) as refused:
        _assert_every_call_runs_under_an_exported_allowlist(_step(_GOOD_CALL, _EXPORT))

    assert "before the allowlist export" in str(refused.value)


def test_a_source_with_no_derivable_call_is_refused() -> None:
    """AC-3, #390's empty-derived-set floor: a dead derivation is red, not green."""
    with pytest.raises(AssertionError) as refused:
        _assert_every_call_runs_under_an_exported_allowlist(_step(_EXPORT))

    assert "no `harness … --repo` call site" in str(refused.value)


def test_a_source_that_lost_the_known_call_site_is_refused() -> None:
    """The second floor: deriving *some* call is not deriving `promote start`."""
    lines = _step(_EXPORT, 'uv run harness promote pr --repo "$GITHUB_WORKSPACE"')

    with pytest.raises(AssertionError) as refused:
        _assert_every_call_runs_under_an_exported_allowlist(lines)

    assert _KNOWN_CALL_SITE in str(refused.value)
