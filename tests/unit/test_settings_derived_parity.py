"""The distributable settings file and the repo's derived copy must not diverge.

``.claude/settings.json`` is a *derived copy* of ``settings/harness.json``
(``BOOTSTRAP.md`` step 3; ``commands/update-guidance.md`` step 3) — the same
relationship ``AGENTS.md`` / ``CLAUDE.md`` / ``GEMINI.md`` have with the process
doc, which step 3 already guards with a byte-identical check.

Nothing mechanical enforced the settings half, so it drifted: harness ran an
``autoMode`` block, six extra force-push denies, dev-push allows, and
``WebFetch`` allows that ``settings/harness.json`` never shipped. Consumers
could not obtain that posture through any sanctioned route (CAL-1081, reported
from a nano-erp session 2026-07-15).

Two guards, because they fail for different reasons:

* **AC-1/AC-3 — the derivation holds.** The two files are byte-identical, so a
  posture added to one is added to both. :func:`test_derived_copy_is_byte_identical`.
  This is what makes the ``/update-guidance`` step-3 clobber trap harmless here:
  a clean derivation has no local content to lose. Repo-local permissions belong
  in the gitignored ``.claude/settings.local.json``, which is never derived.
* **AC-1/AC-2/AC-4 — the posture is actually present.** Byte-identity alone would
  survive deleting the posture from *both* files, so the promoted content is
  pinned directly against the distributable.

CAL-1087 extends the ``autoMode`` half. The routine's versioned guidance
instructs three tracker writes — a deferral comment plus the ``decision`` label
(``work-discovery``, ``/harness routine build`` step 2) and a Linear issue per
finding (``/assess`` step 2) — and the loop's own ``harness close`` transitions
the ticket it built. None was sanctioned, so an unattended run had them refused
with *"the scheduled task explicitly limits write actions to those the task file
requests"*. That is a **configuration** gap, not a property of unattended runs:
the same guidance writes to Linear fine wherever the posture names the action.
The fix belongs here, where the posture is versioned and distributed, rather
than in guidance degraded to match one under-configured trigger.

Each clause must carry the **bound** that makes it safe, because the clause text
is what the classifier reads. These tests pin the bound, not merely the
permission — an allowance that lost its rationale would be a wider grant wearing
the same name.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DISTRIBUTABLE = _REPO_ROOT / "settings" / "harness.json"
_DERIVED = _REPO_ROOT / ".claude" / "settings.json"

#: Force-push spellings the base globs miss — the `+refspec` bypass and the
#: `-C` reordering — plus the `main`-merge denies. Promoted from the repo's own
#: config, where they were live but unshipped.
_PROMOTED_DENIES = [
    "Bash(git -C * push * --force *)",
    "Bash(git push * +*)",
    "Bash(git push origin +*)",
    "Bash(git -C * push * +*)",
    "Bash(git merge * main)",
    "Bash(git merge * main *)",
]

#: CAL-1142: the `git -C <path>` variants of the force-with-lease push and the
#: merge-into-main denies. The base globs denied `git push --force-with-lease …`
#: and `git merge … main`, but not their `git -C <worktree> …` forms — and
#: `git -C <worktree>` is exactly how the unattended routine drives a worktree
#: without `cd`, so a worktree-targeted destructive command walked straight
#: through the guard. Promoted to match the form repo's stricter deny block.
_PROMOTED_DENIES_GIT_DASH_C = [
    "Bash(git -C * push --force-with-lease *)",
    "Bash(git -C * push * --force-with-lease *)",
    "Bash(git -C * merge * main)",
    "Bash(git -C * merge * main *)",
]

#: Pushing an already-reviewed commit to the `dev` integration branch. Profile-general:
#: every repo on this profile integrates on `dev` with the agent-led review as the
#: merge gate, so a direct push of reviewed work does not bypass review.
_PROMOTED_DEV_PUSH_ALLOWS = [
    "Bash(git push origin dev)",
    "Bash(git push origin HEAD:dev)",
    "Bash(git push origin *:dev)",
]

#: Generic enough for any repo on this profile.
_PROMOTED_WEBFETCH_ALLOWS = [
    "WebFetch(domain:github.com)",
    "WebFetch(domain:docs.anthropic.com)",
]

#: Harness's own Python-stack docs. These must stay out of a universal profile —
#: they belong in the consuming repo's gitignored settings.local.json.
_STACK_SPECIFIC_WEBFETCH = [
    "WebFetch(domain:docs.pydantic.dev)",
    "WebFetch(domain:typer.tiangolo.com)",
    "WebFetch(domain:docs.astral.sh)",
]


def _distributable() -> dict[str, Any]:
    return json.loads(_DISTRIBUTABLE.read_text())


def test_derived_copy_is_byte_identical() -> None:
    """AC-1/AC-3: `.claude/settings.json` is a pure derivation of the distributable.

    Anything harness needs but does not ship belongs in `.claude/settings.local.json`
    (gitignored, never derived), not merged into the derived copy.
    """
    distributable = _DISTRIBUTABLE.read_text()
    derived = _DERIVED.read_text()
    if distributable != derived:
        raise AssertionError(
            f"{_DERIVED.relative_to(_REPO_ROOT)} has drifted from its source "
            f"{_DISTRIBUTABLE.relative_to(_REPO_ROOT)}. It is a derived copy: promote "
            f"the difference into the source, or move repo-local content to "
            f".claude/settings.local.json."
        )


def test_distributable_carries_the_automode_dev_push_clause() -> None:
    """AC-1: the unattended-run posture ships, rather than living only here."""
    auto_mode = _distributable().get("autoMode", {})
    allow = auto_mode.get("allow", [])
    assert "$defaults" in allow, "autoMode.allow must extend the defaults"
    assert any("dev" in clause for clause in allow if clause != "$defaults"), (
        "autoMode.allow must carry the dev-push policy statement"
    )


@pytest.mark.parametrize("rule", _PROMOTED_DENIES)
def test_distributable_denies_the_force_push_forms_the_base_globs_miss(rule: str) -> None:
    """AC-1: the `+refspec` / `-C`-reordered bypasses are denied for consumers too."""
    assert rule in _distributable()["permissions"]["deny"], (
        f"{rule} is missing from the distributable's deny list"
    )


@pytest.mark.parametrize("rule", _PROMOTED_DENIES_GIT_DASH_C)
def test_distributable_denies_the_git_dash_c_worktree_variants(rule: str) -> None:
    """CAL-1142: the `git -C <worktree>` force-with-lease-push and merge-into-main
    variants are denied for consumers too — the base globs missed them, and the
    unattended routine drives worktrees via `git -C`, so this is the gap that
    matters most for an autonomous run."""
    assert rule in _distributable()["permissions"]["deny"], (
        f"{rule} is missing from the distributable's deny list"
    )


def test_gh_pr_merge_is_denied() -> None:
    """CAL-1140 discharges the deferral CAL-1142 AC-3 recorded here.

    `Bash(gh pr merge *)` is the fifth deny rule the form repo carries. CAL-1142
    adopted the other four and deferred this one, because denying it would have
    stranded the unattended idle arm: the `/assess`-report PR fallback (report ->
    feature branch -> `gh pr create` -> `gh pr merge`) was the only route by
    which a tick could land its advisory report, and the deny would have closed
    it. The deferral was therefore coupled to CAL-1140 — "adopt it only in
    concert" — and this is that concert: the advisory-report clause above
    sanctions the direct commit, so the fallback is no longer the only route and
    the coupling condition is discharged.

    What the deny buys is the dogfooding invariant: all integration goes through
    the `close` verb, whose gate refuses anything but a passing review bound to
    HEAD. A `gh pr merge` is the one route that lands work while leaving the runs
    ledger with no record of it, which is precisely what the verb loop exists to
    prevent."""
    assert "Bash(gh pr merge *)" in _distributable()["permissions"]["deny"], (
        "`Bash(gh pr merge *)` must be denied: all integration goes through the "
        "`close` verb and its HEAD-bound gate. CAL-1142 AC-3 deferred this deny "
        "only until CAL-1140's advisory-report clause removed the idle arm's "
        "dependency on the PR fallback."
    )


@pytest.mark.parametrize("rule", _PROMOTED_DEV_PUSH_ALLOWS + _PROMOTED_WEBFETCH_ALLOWS)
def test_distributable_carries_the_promoted_allows(rule: str) -> None:
    """AC-1: dev-push and generic WebFetch allows ship."""
    assert rule in _distributable()["permissions"]["allow"], (
        f"{rule} is missing from the distributable's allow list"
    )


@pytest.mark.parametrize("rule", _STACK_SPECIFIC_WEBFETCH)
def test_distributable_omits_stack_specific_webfetch_domains(rule: str) -> None:
    """AC-4: a universal profile must not ship one repo's stack docs."""
    assert rule not in _distributable()["permissions"]["allow"], (
        f"{rule} is Python-stack-specific and must not ship to every repo; "
        f"it belongs in .claude/settings.local.json"
    )


# --- CAL-1087: the writes the routine's own guidance instructs are sanctioned --


def _automode_allow() -> list[str]:
    return [c for c in _distributable()["autoMode"]["allow"] if c != "$defaults"]


def _clause_containing(*terms: str) -> str | None:
    """The single autoMode clause mentioning every one of *terms*, if any."""
    for clause in _automode_allow():
        if all(term in clause for term in terms):
            return clause
    return None


def test_automode_sanctions_the_routine_deferral_write() -> None:
    """CAL-1087/CAL-1167: `work-discovery` tells the routine to comment on a
    ticket it judged not-yet-actionable, label it `decision`/`operator`, and
    assign it to the operator. The posture must permit the write the guidance
    instructs, bounded to the queue the routine pulls from — otherwise the
    deferral is refused and the ticket wedges the queue with the reason recorded
    nowhere a human looks."""
    clause = _clause_containing("`decision`")
    assert clause, (
        "autoMode.allow must sanction the deferral write `work-discovery` "
        "instructs — a comment plus the `decision`/`operator` label (CAL-1087)."
    )
    assert "comment" in clause.lower(), (
        "the deferral clause must name the comment, not only the label — the "
        "comment is what tells the human why the ticket was deferred."
    )
    assert "queue" in clause.lower(), (
        "the deferral clause must state its bound: the queue the routine pulls "
        "from. An unbounded 'may write to Linear' is a wider grant (CAL-1087)."
    )
    assert "assign" in clause.lower(), (
        "CAL-1167: the deferral now assigns the ticket to the operator — the "
        "machine-readable hold signal. The clause must name the assignment, the "
        "new write class it sanctions."
    )
    assert "operator" in clause.lower(), (
        "the deferral clause must state the assignment's bound: the only "
        "assignee it ever sets is the operator, never a re-scope or reassignment "
        "of others' work (CAL-1167)."
    )


def test_automode_sanctions_assess_finding_filing() -> None:
    """CAL-1087: `/assess` step 2 files every finding and insight as an issue —
    the assessment's entire output. A finding it cannot file is lost."""
    clause = _clause_containing("/assess", "Creating Linear issues")
    assert clause, (
        "autoMode.allow must sanction filing an `/assess` pass's findings as "
        "issues — the step its own guidance instructs (CAL-1087)."
    )
    assert "queue" in clause.lower(), (
        "the filing clause must state its bound: findings land on the repo's "
        "Build queue for triage (CAL-1087)."
    )


def test_automode_sanctions_the_worktree_cleanup_preflight() -> None:
    """CAL-1108: `/harness routine build` step 0 instructs the merged-worktree
    cleanup as its housekeeping pre-flight, and it was refused on every tick —
    the same guidance-instructs-what-the-runner-cannot-do shape CAL-1087 fixed
    everywhere else.

    The bound is what makes it safe, and it is the whole question for a delete:
    the command removes only branches already merged into an integration branch,
    plus orphaned directories past the age threshold. It never touches an
    unmerged or in-flight worktree — including a reclaimed ticket's preserved WIP
    branch, which lives on `origin` and is fetched by `--resume`."""
    clause = _clause_containing("worktrees cleanup")
    assert clause, (
        "autoMode.allow must sanction the `harness worktrees cleanup --merged` "
        "pre-flight that `/harness routine build` step 0 instructs (CAL-1108)."
    )
    assert "merged" in clause, (
        "the cleanup clause must name the merged-only bound — the property that "
        "makes a delete safe is that the branch already landed (CAL-1108)."
    )
    assert "unmerged" in clause, (
        "the cleanup clause must state what it will NOT touch. An allowance to "
        "delete is only as safe as the boundary it names (CAL-1108)."
    )


def test_automode_sanctions_the_gated_close_verb() -> None:
    """CAL-1087: `harness close` is what lands a finished run — the Linear
    transition plus the merge. Unsanctioned, the loop can build and review its
    own work but never ship it.

    The clause must carry the bound that makes it safe: the verb refuses unless
    a passing review is bound to the current HEAD, so it cannot land unreviewed
    work. That is the same reviewed-work-only condition the dev-push clause
    rests on — the permission rides on the gate, not on trust."""
    clause = _clause_containing("harness close")
    assert clause, (
        "autoMode.allow must sanction `harness close` — without it the loop "
        "cannot land the work it built and reviewed (CAL-1087)."
    )
    for term in ("reviewed SHA", "HEAD"):
        assert term in clause, (
            f"the close clause must name its gate ({term!r}): the permission is "
            "safe only because the verb refuses a review that does not cover "
            "what would merge (CAL-1087)."
        )
    assert "stale_review" in clause, (
        "the close clause must name the refusal reasons that enforce the gate, "
        "so the bound is auditable rather than asserted (CAL-1087)."
    )


def test_automode_sanctions_the_advisory_assess_report_commit() -> None:
    """CAL-1140: `/assess` steps 3-4 instruct the routine to commit its dated
    report — plus the retention compaction of the rolling log — directly to the
    integration branch, because the report carries nothing reviewable and a PR
    per run would pile up trivial approvals under a scheduled cadence.

    The only dev-push clause was scoped to *already-reviewed* work, and an
    assessment report is committed unreviewed, so whether the write was
    sanctioned at all was ambiguous. The ambiguity resolved permissive in
    practice — an unattended tick pushed a report with no denial — which is the
    argument for stating the clause rather than against it: a posture that works
    only because the classifier read an ambiguous clause charitably is one
    re-reading away from an idle arm that silently loses its report every tick.

    The bound is advisory-only, and it is what separates this from the
    reviewed-work clause it must not widen: the commit may touch `assessments/`
    and nothing else.
    """
    clause = _clause_containing("advisory", "assessments/LOG.md")
    assert clause, (
        "autoMode.allow must sanction the advisory `/assess` report commit that "
        "`/assess` steps 3-4 instruct — including the `assessments/LOG.md` "
        "retention compaction they put in the same commit (CAL-1140)."
    )
    assert "only `assessments/`" in clause, (
        "the advisory-report clause must name its bound: the commit touches "
        "`assessments/` and nothing else. An unbounded 'may commit to dev' is "
        "the reviewed-work clause widened to code, which CAL-1140 puts out of "
        "scope."
    )
    assert "never code" in clause, (
        "the advisory-report clause must state what it will NOT touch. An "
        "allowance to push to an integration branch is only as safe as the "
        "boundary it names (CAL-1140)."
    )
    assert "open finding" in clause, (
        "the retention half deletes superseded report files, so the clause must "
        "carry the rule that makes that delete safe: never fold away a report "
        "with an open finding (`/assess` step 4)."
    )
    assert "force-push" in clause.lower(), (
        "the advisory-report clause must restate that force-pushes to `dev` stay "
        "blocked — it grants a push, and the deny block is what bounds it."
    )
