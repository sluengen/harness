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

#: A ``harness <verb…> --repo <arg>`` invocation. The verb is captured only so a
#: failure names the call site; the ``--repo`` argument is what is asserted on.
_REPO_RESOLVING_CALL = re.compile(r"harness\s+(?P<verb>[a-z][a-z \-]*?)\s+--repo\s+(?P<arg>\S+)")

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
    """Derive every call site as ``(line number, verb, --repo argument)``.

    ``finditer`` rather than ``search``: folding can bring two chained calls onto
    one logical line, and deriving only the first would be a coverage hole that
    the folding itself introduced.
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
