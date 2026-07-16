"""``harness promote`` — the promotion lifecycle command group (ADR 0003).

Promotion moves completed work toward release as a **first-class, audited
harness lifecycle** — the same shape as the build verbs (``start`` → ``review``
→ ``close``), applied to branch movement over a universal ``dev -> staging ->
main`` topology (`specs/decisions/0003-promotion-lifecycle.md`). An external
orchestrator triggers it and may repair within a narrow policy; the harness owns
every state transition and records it in a promotion ledger.

CAL-1113 registered the group and its five subcommands with stable flags;
CAL-1114 added the **read-path JSON contract** over the promotion ledger
(:mod:`harness.state.promotions`): ``status`` reads a promotion by id and emits
the typed :class:`~harness.state.promotions.Promotion` view, and ``pr`` enforces
the PR gate. CAL-1115 now wires the **worktree/merge mechanics** for the two
write-path openers, ``start`` and ``continue``, on top of the pure
:mod:`harness.promotion` library:

* ``start`` fetches ``origin``, validates the ``--from`` → ``--to`` pair, creates
  the promotion worktree/branch **from the target**, attempts the merge, and
  records the promotion. A clean merge lands ``status='opened'`` with the
  ``merged_sha``; a conflict lands the classification (``agent_may_fix`` /
  ``needs_ticket``) and leaves the worktree resumable, returning the conflicted
  files.
* ``continue`` resumes an ``agent_may_fix`` promotion after one bounded, in-policy
  repair: it commits the resolved merge, records the ``merged_sha``, and
  increments the repair ``attempts`` count.

Still deferred: gate evidence (a merge only reaches ``pr_ready`` in CAL-1116), PR
creation (CAL-1117), and ``escalate`` (CAL-1118) — whose body remains a
``not_implemented`` stub. ``pr`` on a gate-*satisfied* promotion also reports
``not_implemented`` (the refusal is CAL-1114's, the PR push CAL-1117's).

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
from typing import Literal, NoReturn

import typer

from harness import promotion as mechanics
from harness._time import iso_z
from harness.cli._git import teardown_worktree
from harness.cli._repo import resolve_repo_root_or_exit, resolve_verb_db_path
from harness.identity import generate_run_id
from harness.state import promotions
from harness.state.promotions import Promotion

#: The ``harness promote pr`` gate-refusal reasons — the machine-readable enum an
#: orchestrator branches on when a PR is refused (AC-4). One member in v1: the
#: promotion is not ``pr_ready`` with a gated SHA. Locked by
#: ``test_promotion_contract_locked.py``; adding/renaming a reason is a
#: *major*-level interface event.
PromotionRefusalReason = Literal["gate_not_satisfied"]

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

    # 4. Record the promotion. A clean merge is `opened` (awaiting the gate,
    #    CAL-1116) with its merged HEAD; a conflict carries its classification.
    now = iso_z()
    status = "opened" if outcome.clean else outcome.classification
    promotion = Promotion(
        promotion_id=promotion_id,
        repo=str(repo_root),
        from_branch=from_branch,
        to_branch=to_branch,
        status=status,  # type: ignore[arg-type]  # classify_conflicts returns a PromotionStatus
        created_at=now,
        updated_at=now,
        worktree_path=str(worktree),
        promotion_branch=branch_name,
        merged_sha=outcome.merged_sha,
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

    # Repair accepted: record the merged HEAD, count the attempt (ADR 0003 "one
    # bounded attempt"), and move to `opened` (awaiting the gate, CAL-1116).
    updated = promotion.model_copy(
        update={
            "status": "opened",
            "merged_sha": outcome.merged_sha,
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

    # Gate satisfied — the actual push + PR creation is CAL-1117.
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
