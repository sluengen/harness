"""Contract guards for the deterministic nightly ``dev → staging`` promotion.

Two properties, deliberately in two tests. The first pins the workflow's shape
— schedule, concurrency, permissions, gate invocation, and the absence of any
automated repair path (#378). The second pins that the verb calls inside it can
resolve ``--repo`` at all: the workspace allowlist fails closed, so a runner
that never exports ``HARNESS_WORKSPACE_ROOTS`` gets an exit-2 refusal from every
verb (#390). It **derives** the call sites from the workflow text rather than
listing them, so a verb call added later is covered the day it lands.

Whether the exported allowlist actually admits the ``--repo`` argument is not a
text property and is not asserted here — that is
``tests/integration/test_nightly_promotion_workspace_allowlist.py``, which
executes the workflow's own export line and feeds the result to the production
resolver.
"""

import re
from pathlib import Path

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
    lines = WORKFLOW.read_text(encoding="utf-8").splitlines()

    calls = [
        (number, match.group("verb").strip(), match.group("arg"))
        for number, line in enumerate(lines, start=1)
        if (match := _REPO_RESOLVING_CALL.search(line)) is not None
    ]
    # Floor: a derivation that silently stops matching must be red, not green.
    assert calls, "no `harness … --repo` call site was derived from the workflow"
    assert _KNOWN_CALL_SITE in {verb for _, verb, _ in calls}, (
        f"the derivation lost its known call site `harness {_KNOWN_CALL_SITE}`; "
        f"it found {sorted({verb for _, verb, _ in calls})}"
    )

    exports = [
        number
        for number, line in enumerate(lines, start=1)
        if line.strip().startswith(_ALLOWLIST_EXPORT_PREFIX)
    ]
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
