"""``harness promote`` — the promotion lifecycle command group (ADR 0003).

Promotion moves completed work toward release as a **first-class, audited
harness lifecycle** — the same shape as the build verbs (``start`` → ``review``
→ ``close``), applied to branch movement over a universal ``dev -> staging ->
main`` topology (`specs/decisions/0003-promotion-lifecycle.md`). An external
orchestrator triggers it and may repair within a narrow policy; the harness owns
every state transition and records it in a promotion ledger.

CAL-1113 registered the group and its five subcommands with stable flags;
CAL-1114 added the **read-path JSON contract** over the promotion ledger
(:mod:`harness.state.promotions`); CAL-1115 wired the **worktree/merge mechanics**
for the write-path openers on top of the pure :mod:`harness.promotion` library;
CAL-1116 now runs the **gate + evidence capture** inside those openers
(:mod:`harness.promotion_gate`):

* ``start`` fetches ``origin``, validates the ``--from`` → ``--to`` pair, creates
  the promotion worktree/branch **from the target**, and attempts the merge. A
  conflict lands the classification (``agent_may_fix`` / ``needs_ticket``) and
  leaves the worktree resumable; a **clean** merge then runs the verify gate →
  ``pr_ready`` (green, recording ``gated_sha`` + bounded ``evidence``),
  ``needs_ticket`` / ``blocked`` (a failed / unrunnable gate), or ``opened`` (no
  ``verify:`` configured — ungated).
* ``continue`` resumes an ``agent_may_fix`` promotion after one bounded, in-policy
  repair: it commits the resolved merge, **re-runs the gate** on it (same mapping;
  a failed gate has now spent the bounded attempt → ``needs_ticket``), and
  increments the repair ``attempts`` count.

Still deferred: PR creation (CAL-1117) and ``escalate`` (CAL-1118) — whose body
remains a ``not_implemented`` stub. ``pr`` enforces two gates (the ``pr_ready`` +
gated-SHA PR gate, and the CAL-1116 branch-HEAD freshness check) and, once both
pass, falls through to ``not_implemented`` (the PR push is CAL-1117's).

The five subcommands are the real orchestrator **pause points**:

* ``start``    — open a promotion: create the worktree + promotion branch and
  attempt the ``--from`` → ``--to`` merge, returning a policy classification.
* ``continue`` — resume after one bounded, in-policy repair: re-run
  classification and the gate, incrementing the attempt count.
* ``status``   — read-only: report a promotion's current lifecycle state.
* ``pr``       — the success finalizer: push the promotion branch and open the PR
  (gated — refused unless the promotion is ``pr_ready`` with fresh gate evidence).
* ``escalate`` — the non-success terminal path: file/update a Linear ticket with
  the evidence and mark the promotion ``escalated``.

There is deliberately **no ``verify`` command**: gate execution lives *inside*
``start`` and ``continue`` (a promotion cannot reach ``pr_ready`` without fresh
gate evidence), so a standalone ``verify`` would name a step that is never an
independent pause/resume point.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Literal, NoReturn, cast

import typer

from harness import promotion as mechanics
from harness._time import iso_z
from harness.cli._git import teardown_worktree
from harness.cli._repo import resolve_repo_root_or_exit, resolve_verb_db_path
from harness.gate import load_gate_command
from harness.identity import generate_run_id
from harness.promotion_gate import classify_gate_failure, run_promotion_gate
from harness.state import promotions
from harness.state.promotions import Promotion, PromotionStatus

#: The ``harness promote pr`` gate-refusal reasons — the machine-readable enum an
#: orchestrator branches on when a PR is refused. ``gate_not_satisfied``: the
#: promotion is not ``pr_ready`` with a gated SHA (AC-4). ``stale_gate``: it *is*
#: gate-satisfied, but the promotion branch tip has moved past the gated SHA, so
#: the green gate no longer covers what would be pushed (CAL-1116 AC-3). Locked by
#: ``test_promotion_contract_locked.py``; adding/renaming a reason is a
#: *major*-level interface event.
PromotionRefusalReason = Literal["gate_not_satisfied", "stale_gate"]

promote_app = typer.Typer(
    help=(
        "Drive the promotion lifecycle (dev -> staging -> main; ADR 0003). "
        "v1 surface — mechanics land per CAL-1114+."
    ),
    no_args_is_help=True,
)

#: Exit code for a contract stub — an invocation the surface accepts but whose
#: mechanics are not yet wired. Reuses the stable "invocation / not satisfied"
#: code (2) rather than inventing a new one; the ``not_implemented`` marker in
#: the payload distinguishes it from a bad-flags refusal.
_STUB_EXIT = 2


def _not_implemented(subcommand: str, **extra: object) -> None:
    """Emit the structured ``not_implemented`` marker for a stubbed subcommand and
    exit with the stub code, so an orchestrator can tell "surface exists,
    mechanics pending" apart from a real error."""
    payload: dict[str, object] = {
        "error": "not_implemented",
        "command": f"promote {subcommand}",
        "detail": (
            "the promote surface is locked (CAL-1113); mechanics land per "
            "CAL-1114+ (ADR 0003)"
        ),
        **extra,
    }
    typer.echo(json.dumps(payload))
    raise typer.Exit(code=_STUB_EXIT)


def _read_or_not_found(
    command: str, promotion_id: str, repo: Path, db: Path | None
) -> promotions.Promotion:
    """Read a promotion by id from the ledger, or exit 2 with a ``not_found`` marker.

    The shared read prologue for the ledger-backed subcommands (``status`` /
    ``pr``): resolve ``--repo``/``--db`` the way the verbs do, read the promotion,
    and — when there is no such promotion — emit a structured ``not_found`` an
    orchestrator can tell apart from a real error, exiting with the stub/refusal
    code. Returns the promotion on success.
    """
    repo_root = resolve_repo_root_or_exit(repo)
    db_path = resolve_verb_db_path(db, repo_root)
    promotion = asyncio.run(promotions.read_promotion(promotion_id, db_path=db_path))
    if promotion is None:
        typer.echo(
            json.dumps(
                {
                    "error": "not_found",
                    "command": f"promote {command}",
                    "promotion_id": promotion_id,
                }
            )
        )
        raise typer.Exit(code=_STUB_EXIT)
    return promotion


def _refuse(reason: str, message: str, **extra: object) -> NoReturn:
    """Emit a structured mechanics refusal and exit 2.

    The write-path analogue of ``_not_found`` for the start/continue mechanics: a
    machine-readable ``reason`` (from :class:`~harness.promotion.PromotionMechanicsError`
    or a CLI-level guard) plus the human ``error`` message and any ``extra`` an
    orchestrator needs to act (e.g. the conflicted files), so a refusal is never
    a bare non-zero exit.
    """
    payload: dict[str, object] = {"error": message, "reason": reason, **extra}
    typer.echo(json.dumps(payload))
    raise typer.Exit(code=_STUB_EXIT)


def _emit_promotion(promotion: Promotion, outcome: mechanics.MergeOutcome) -> None:
    """Echo the promotion view plus the merge's live ``conflict_files`` list.

    ``start`` / ``continue`` return the full :class:`Promotion` state (so an
    orchestrator sees ``status`` / ``merged_sha`` / ``attempts`` directly) with an
    extra ``conflict_files`` key carrying the merge outcome's conflicted paths
    (empty on a clean merge) — the structured conflict data of AC-2.
    """
    payload = {
        **json.loads(promotion.model_dump_json()),
        "conflict_files": list(outcome.conflict_files),
    }
    typer.echo(json.dumps(payload))


def _gate_clean_merge(
    worktree: Path, merged_sha: str | None
) -> tuple[PromotionStatus, str | None, str | None]:
    """Run the verify gate on a cleanly-merged promotion worktree; map it to state.

    Returns ``(status, gated_sha, evidence)`` for a clean merge whose HEAD is
    ``merged_sha`` (CAL-1116). The gate command is read from the *worktree's*
    ``CONTEXT.md`` (the merged tree gates itself). The mapping:

    * no ``verify:`` configured → ``opened`` (ungated; cannot advance to
      ``pr_ready`` without evidence — the review/close ``not_configured`` posture);
    * green → ``pr_ready`` with ``gated_sha = merged_sha`` and bounded evidence;
    * red / unrunnable → :func:`~harness.promotion_gate.classify_gate_failure`
      (``needs_ticket`` / ``blocked``) with bounded evidence and no gated SHA.
    """
    command = load_gate_command(worktree)
    if command is None:
        return "opened", None, None
    evidence = run_promotion_gate(worktree, command=command)
    if evidence.passed:
        return "pr_ready", merged_sha, evidence.evidence
    return classify_gate_failure(evidence), None, evidence.evidence  # type: ignore[return-value]


@promote_app.command("start", help="Open a promotion: merge --from into --to and classify.")
def start_command(
    repo: Path = typer.Option(
        Path("."), "--repo", help="Repo root to promote within."
    ),
    from_branch: str = typer.Option(
        "dev", "--from", help="Source branch to promote from (default: dev)."
    ),
    to_branch: str = typer.Option(
        "staging", "--to", help="Target branch to promote into (default: staging)."
    ),
    db: Path | None = typer.Option(
        None, "--db", help="Path to harness.db (defaults to .harness/harness.db under --repo)."
    ),
    json_output: bool = typer.Option(
        True, "--json", help="Emit machine-readable JSON (always on)."
    ),
) -> None:
    """Open a promotion: create the worktree/branch, attempt the merge, classify (CAL-1115)."""
    repo_root = resolve_repo_root_or_exit(repo)
    db_path = resolve_verb_db_path(db, repo_root)

    # 1. Refresh the remote refs and validate the pair BEFORE any state — an
    #    invalid pair or an unreachable remote leaves no worktree and no row.
    try:
        mechanics.fetch_origin(repo_root)
        mechanics.validate_branch_pair(repo_root, from_branch, to_branch)
    except mechanics.PromotionMechanicsError as exc:
        _refuse(
            exc.reason,
            str(exc),
            command="promote start",
            **{"from": from_branch, "to": to_branch},
        )

    # 2. Mint the promotion id and create the worktree/branch from the target.
    promotion_id = generate_run_id()
    branch_name = mechanics.promotion_branch_name(from_branch, to_branch)
    try:
        worktree = mechanics.create_promotion_worktree(
            repo_root, promotion_id, to_branch=to_branch, branch_name=branch_name
        )
    except mechanics.PromotionMechanicsError as exc:
        _refuse(exc.reason, str(exc), command="promote start")

    # 3. Attempt the merge and classify. A genuine git error (no conflicted
    #    paths) tears the fresh worktree down — there is nothing to resume.
    try:
        outcome = mechanics.attempt_merge(worktree, from_branch=from_branch)
    except mechanics.PromotionMechanicsError as exc:
        teardown_worktree(repo_root, worktree_path=worktree, branch=branch_name)
        _refuse(exc.reason, str(exc), command="promote start")

    # 4. Record the promotion. A clean merge runs the gate (CAL-1116) → `pr_ready`
    #    (green, with a gated SHA), `needs_ticket`/`blocked` (failed), or `opened`
    #    (no gate configured); a conflict carries its merge classification.
    now = iso_z()
    status: PromotionStatus
    if outcome.clean:
        status, gated_sha, evidence = _gate_clean_merge(worktree, outcome.merged_sha)
    else:
        # A conflict's classification is always a PromotionStatus (agent_may_fix /
        # needs_ticket); typed str|None on MergeOutcome, narrowed here.
        status = cast(PromotionStatus, outcome.classification)
        gated_sha, evidence = None, None
    promotion = Promotion(
        promotion_id=promotion_id,
        repo=str(repo_root),
        from_branch=from_branch,
        to_branch=to_branch,
        status=status,
        created_at=now,
        updated_at=now,
        worktree_path=str(worktree),
        promotion_branch=branch_name,
        merged_sha=outcome.merged_sha,
        gated_sha=gated_sha,
        evidence=evidence,
        attempts=0,
    )
    asyncio.run(promotions.insert_promotion(promotion, db_path=db_path))
    _emit_promotion(promotion, outcome)


@promote_app.command("continue", help="Resume a promotion after one bounded repair.")
def continue_command(
    promotion_id: str = typer.Option(
        ..., "--promotion-id", help="Id of the promotion to resume."
    ),
    repo: Path = typer.Option(
        Path("."), "--repo", help="Repo root of the open promotion."
    ),
    db: Path | None = typer.Option(
        None, "--db", help="Path to harness.db (defaults to .harness/harness.db under --repo)."
    ),
    json_output: bool = typer.Option(
        True, "--json", help="Emit machine-readable JSON (always on)."
    ),
) -> None:
    """Resume an ``agent_may_fix`` promotion after a bounded repair (CAL-1115)."""
    repo_root = resolve_repo_root_or_exit(repo)
    db_path = resolve_verb_db_path(db, repo_root)
    promotion = asyncio.run(promotions.read_promotion(promotion_id, db_path=db_path))
    if promotion is None:
        typer.echo(
            json.dumps(
                {
                    "error": "not_found",
                    "command": "promote continue",
                    "promotion_id": promotion_id,
                }
            )
        )
        raise typer.Exit(code=_STUB_EXIT)

    # Only a conflict awaiting repair (`agent_may_fix`) is resumable: a clean
    # `opened` merge has nothing to continue, and `needs_ticket` must escalate.
    if promotion.status != "agent_may_fix":
        _refuse(
            "not_resumable",
            f"promotion {promotion_id} is {promotion.status!r}, not 'agent_may_fix' — "
            "only a conflict awaiting repair can be continued",
            command="promote continue",
            promotion_id=promotion_id,
            status=promotion.status,
        )

    if promotion.worktree_path is None or not Path(promotion.worktree_path).exists():
        _refuse(
            "worktree_missing",
            f"promotion {promotion_id} has no resumable worktree at "
            f"{promotion.worktree_path!r}",
            command="promote continue",
            promotion_id=promotion_id,
        )

    worktree = Path(promotion.worktree_path)

    # Complete the repaired merge — refuses `dirty_worktree` (with the still-
    # unresolved files) if the orchestrator's repair left any conflict unstaged.
    try:
        outcome = mechanics.complete_merge(worktree)
    except mechanics.PromotionMechanicsError as exc:
        _refuse(
            exc.reason,
            str(exc),
            command="promote continue",
            promotion_id=promotion_id,
            conflict_files=list(mechanics.conflicted_files(worktree)),
        )

    # Repair accepted: count the attempt (ADR 0003 "one bounded attempt") and run
    # the gate on the resolved merge (CAL-1116). Green → `pr_ready` with a gated
    # SHA; a failed gate has now spent the bounded repair → `needs_ticket` /
    # `blocked`; no gate configured → `opened` (ungated).
    status, gated_sha, evidence = _gate_clean_merge(worktree, outcome.merged_sha)
    updated = promotion.model_copy(
        update={
            "status": status,
            "merged_sha": outcome.merged_sha,
            "gated_sha": gated_sha,
            "evidence": evidence,
            "attempts": promotion.attempts + 1,
            "updated_at": iso_z(),
        }
    )
    asyncio.run(promotions.update_promotion(updated, db_path=db_path))
    _emit_promotion(updated, outcome)


@promote_app.command("status", help="Report a promotion's lifecycle state (read-only).")
def status_command(
    promotion_id: str = typer.Option(
        ..., "--promotion-id", help="Id of the promotion to read."
    ),
    repo: Path = typer.Option(
        Path("."), "--repo", help="Repo root of the promotion."
    ),
    db: Path | None = typer.Option(
        None, "--db", help="Path to harness.db (defaults to .harness/harness.db under --repo)."
    ),
    json_output: bool = typer.Option(
        True, "--json", help="Emit machine-readable JSON (always on)."
    ),
) -> None:
    """Report a promotion's lifecycle state by id — the typed ledger view (CAL-1114)."""
    promotion = _read_or_not_found("status", promotion_id, repo, db)
    typer.echo(promotion.model_dump_json())


@promote_app.command("pr", help="Finalize a green promotion: push the branch and open the PR.")
def pr_command(
    promotion_id: str = typer.Option(
        ..., "--promotion-id", help="Id of the promotion to open a PR for."
    ),
    repo: Path = typer.Option(
        Path("."), "--repo", help="Repo root of the promotion."
    ),
    db: Path | None = typer.Option(
        None, "--db", help="Path to harness.db (defaults to .harness/harness.db under --repo)."
    ),
    json_output: bool = typer.Option(
        True, "--json", help="Emit machine-readable JSON (always on)."
    ),
) -> None:
    """Open the promotion PR — gated (CAL-1114); the push itself lands in CAL-1117."""
    promotion = _read_or_not_found("pr", promotion_id, repo, db)

    # AC-4: PR creation is refused unless the promotion is pr_ready with a gated
    # SHA. The refusal is CAL-1114's; only the push past it is CAL-1117's.
    if not promotions.pr_gate_satisfied(promotion):
        reason: PromotionRefusalReason = "gate_not_satisfied"
        typer.echo(
            json.dumps(
                {
                    "error": "promotion gate not satisfied",
                    "reason": reason,
                    "command": "promote pr",
                    "promotion_id": promotion_id,
                    "status": promotion.status,
                    "gated_sha": promotion.gated_sha,
                }
            )
        )
        raise typer.Exit(code=_STUB_EXIT)

    # AC-3 (CAL-1116): the recorded green gate must still cover what would be
    # pushed. If the promotion branch tip has moved past the gated SHA, the
    # evidence is stale — refuse rather than push an ungated commit. An
    # unresolvable branch (already cleaned up) is not treated as stale here; the
    # push itself (CAL-1117) will handle a missing branch.
    repo_root = resolve_repo_root_or_exit(repo)
    live_head = (
        mechanics.branch_head(repo_root, promotion.promotion_branch)
        if promotion.promotion_branch
        else None
    )
    if live_head is not None and live_head != promotion.gated_sha:
        stale_reason: PromotionRefusalReason = "stale_gate"
        _refuse(
            stale_reason,
            "promotion gate evidence is stale — the branch HEAD moved past the "
            "gated SHA; re-run the gate before opening the PR",
            command="promote pr",
            promotion_id=promotion_id,
            status=promotion.status,
            gated_sha=promotion.gated_sha,
            branch_head=live_head,
        )

    # Gate satisfied and fresh — the actual push + PR creation is CAL-1117.
    _not_implemented("pr", promotion_id=promotion_id, status=promotion.status)


@promote_app.command("escalate", help="File a Linear ticket and mark the promotion escalated.")
def escalate_command(
    repo: Path = typer.Option(
        Path("."), "--repo", help="Repo root of the promotion."
    ),
    json_output: bool = typer.Option(
        False, "--json", help="Emit machine-readable JSON."
    ),
) -> None:
    """Escalate a blocked promotion (stub — CAL-1118 implements escalation)."""
    _not_implemented("escalate", repo=str(repo))
