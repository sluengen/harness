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
CAL-1116 added the gate + evidence step, and **CAL-1159 moved the gate host-side**:
the verb no longer executes the gate (the ``harness:dev`` image is built
``--no-dev`` and cannot run a target repo's toolchain — the ``review`` boundary,
CAL-1082), so the caller runs it in the worktree and reports the result via
``--gate-exit`` / ``--gate-log``, and the verb *classifies* it
(:mod:`harness.promotion_gate`):

* ``start`` fetches ``origin``, validates the ``--from`` → ``--to`` pair, creates
  the promotion worktree/branch **from the target**, and attempts the merge. A
  conflict lands the classification (``agent_may_fix`` / ``needs_ticket``) and
  leaves the worktree resumable; a **clean** merge is classified against the
  caller's reported gate → ``pr_ready`` (green ``--gate-exit 0``, recording
  ``gated_sha`` + bounded ``evidence``), ``needs_ticket`` (a red gate),
  ``gate_pending`` (a gate is defined but no evidence supplied — merged, awaiting a
  host-side gate), or ``opened`` (no ``verify:`` configured — ungated).
* ``continue`` resumes an ``agent_may_fix`` conflict after one bounded, in-policy
  repair (commit the resolved merge, spend the attempt) **or** a ``gate_pending``
  merge (nothing to repair), then classifies the caller's reported gate the same
  way — a red gate that has spent the bounded repair lands ``needs_ticket``.

CAL-1117 wired ``pr`` — the success finalizer. It enforces two gates (the
``pr_ready`` + gated-SHA PR gate, and the CAL-1116 branch-HEAD freshness check) and,
once both pass, **publishes** (the publication mechanics live in the sibling
:mod:`harness.promotion_pr`). CAL-1158 then split publication by **hop**, because
the two hops finish differently — *staging is derived, main is decided*:

* the **staging hop** (``--to staging``) advances the target itself to the gated
  SHA and opens **no** PR, reaching the terminal ``promoted`` state — nothing is
  judged there, so the green gate is the whole decision and the nightly promotion
  completes without a human;
* the **release hop** (``--to main``) is unchanged: push only the promotion branch,
  open a PR into the target from deterministic facts, record ``pr_opened``. Merging
  it stays a deliberate human act — the single decision point.

The command keeps the name ``pr`` (the locked v1 surface; there is deliberately no
``promote land``) — it is *the success finalizer*, and the hop selects the
mechanism.

CAL-1118 now wires ``escalate`` — the non-success terminal path. It files (or, when
the promotion is already linked, comments on) a tracker ticket carrying the promotion
evidence — id, endpoints, branch/worktree, conflict files, gate summary, next action
(the content is rendered by the sibling :mod:`harness.promotion_escalation`; the
tracker I/O goes through the :class:`~harness.tracker.Tracker` seam) — then records
the escalation ticket id and the terminal ``escalated`` state. Tracker configuration
that prevents escalation returns a structured ``blocked`` result rather than a raw
failure, and a tracker-less repo returns ``no_tracker`` carrying the evidence it
cannot file. The whole ``promote`` surface is now wired; no subcommand remains a stub.

Since #328 the backend is resolved **only** through
:func:`~harness.tracker.tracker_client`, like every other writing verb: this module
constructs no backend client and catches no backend-specific error, so escalation
works on whichever backend ``CONTEXT.md`` → ``tracker:`` selects instead of on
Linear alone. That contract is guarded by ``test_promote_no_direct_tracker_client``.

The five subcommands are the real orchestrator **pause points**:

* ``start``    — open a promotion: create the worktree + promotion branch and
  attempt the ``--from`` → ``--to`` merge, returning a policy classification.
* ``continue`` — resume after one bounded, in-policy repair: re-run
  classification and the gate, incrementing the attempt count.
* ``status``   — read-only: report a promotion's current lifecycle state.
* ``pr``       — the success finalizer: push the promotion branch and open the PR
  from deterministic facts (gated — refused unless the promotion is ``pr_ready``
  with fresh gate evidence), then record ``pr_opened``.
* ``escalate`` — the non-success terminal path: file/update a tracker ticket with
  the evidence and mark the promotion ``escalated``.

There is deliberately **no ``verify`` command**: the gate is not a harness verb at
all (CAL-1159) — the caller runs it host-side and reports the result to ``start`` /
``continue`` via ``--gate-exit`` / ``--gate-log``, exactly as the build ``review``
gate works. A standalone ``verify`` would name a step the harness does not perform.
"""

# size: one cohesive command group — the five promotion-lifecycle subcommands
# (start / continue / status / pr / escalate) and their shared refuse/emit
# prologue. The heavy mechanics already live in sibling modules (harness/promotion.py
# merge, promotion_gate.py gate, promotion_pr.py publish); splitting the CLI itself
# would scatter one orchestrator surface across files for no cohesion gain.

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Literal, NoReturn, cast

import typer

from harness import promotion as mechanics
from harness import repo_config
from harness._git import teardown_worktree
from harness._time import iso_z
from harness.cli._repo import (
    REPO_OPTION_HELP,
    resolve_repo_argument,
    resolve_verb_db_path,
)
from harness.gate import load_gate_command
from harness.identity import generate_run_id
from harness.promotion_escalation import build_escalation_body, build_escalation_title
from harness.promotion_gate import classify_gate_failure, evidence_from_report
from harness.promotion_pr import (
    DIRECT_PUSH_TARGET,
    build_pr_body,
    build_pr_title,
    collect_promotion_facts,
    create_pull_request,
    push_promotion_branch,
    push_target_branch,
)
from harness.state import promotions
from harness.state.promotions import Promotion, PromotionStatus
from harness.tracker import tracker_client
from harness.tracker_errors import (
    TrackerConfigError,
    TrackerNotFound,
    TrackerRequestError,
)

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

#: Exit code for a structured, machine-readable refusal — a ``not_found`` id, a
#: mechanics refusal, or a gate that is not satisfied. The stable "invocation /
#: not satisfied" code (2); the payload's ``error`` / ``reason`` marker
#: distinguishes each case from a real (non-zero, unstructured) error.
_STUB_EXIT = 2


def _read_or_not_found(
    command: str, promotion_id: str, repo: Path | None, db: Path | None
) -> promotions.Promotion:
    """Read a promotion by id from the ledger, or exit 2 with a ``not_found`` marker.

    The shared read prologue for the ledger-backed subcommands (``status`` /
    ``pr``): resolve ``--repo``/``--db`` the way the verbs do, read the promotion,
    and — when there is no such promotion — emit a structured ``not_found`` an
    orchestrator can tell apart from a real error, exiting with the stub/refusal
    code. Returns the promotion on success.
    """
    repo_root = resolve_repo_argument(repo)
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


def _emit_promotion(
    promotion: Promotion, outcome: mechanics.MergeOutcome, **extra: object
) -> None:
    """Echo the promotion view plus the merge's live ``conflict_files`` list.

    ``start`` / ``continue`` return the full :class:`Promotion` state (so an
    orchestrator sees ``status`` / ``merged_sha`` / ``attempts`` directly) with an
    extra ``conflict_files`` key carrying the merge outcome's conflicted paths
    (empty on a clean merge) — the structured conflict data of AC-2. ``extra``
    carries any additional write-path markers (e.g. ``reason=no_gate_evidence`` on
    a ``gate_pending`` result) an orchestrator branches on.
    """
    payload = {
        **json.loads(promotion.model_dump_json()),
        "conflict_files": list(outcome.conflict_files),
        **extra,
    }
    typer.echo(json.dumps(payload))


#: The ``reason`` an otherwise-``gate_pending`` classification carries, so an
#: orchestrator can tell "nothing supplied yet" from "supplied, but untrustworthy"
#: apart — both leave the promotion resumable via ``continue --gate-exit``, but
#: only the second means a gate genuinely ran and its evidence was lost (#188).
_NO_GATE_EVIDENCE_REASON = "no_gate_evidence"
_GATE_LOG_UNREADABLE_REASON = "gate_log_unreadable"


def _classify_gate(
    worktree: Path,
    *,
    merged_sha: str | None,
    gate_exit: int | None,
    gate_log: Path | None,
) -> tuple[PromotionStatus, str | None, str | None, str | None]:
    """Map a cleanly-merged promotion's *reported* gate result to lifecycle state.

    The gate runs **host-side, in the caller's session** — the verb never executes
    it (CAL-1159, the ``review`` boundary). This reads whether the merged tree
    *defines* a gate (from the worktree's ``CONTEXT.md``) and classifies the
    evidence the caller supplied via ``--gate-exit``/``--gate-log``. Returns
    ``(status, gated_sha, evidence, reason)`` for a clean merge whose HEAD is
    ``merged_sha``:

    * no ``verify:`` configured → ``opened`` (ungated; cannot advance to
      ``pr_ready`` without evidence — the review/close ``not_configured`` posture);
    * a gate is defined but no evidence supplied (``gate_exit is None``) →
      ``gate_pending`` / :data:`_NO_GATE_EVIDENCE_REASON`: the merge is done and
      the worktree waits to be gated host-side (AC-1). Silence is not a pass;
    * green (``--gate-exit 0``) but the supplied ``--gate-log`` could not be read
      → ``gate_pending`` / :data:`_GATE_LOG_UNREADABLE_REASON` (#188): the
      evidence tail is the whole point of the promotion audit trail — recording a
      green exit code with no trustworthy tail would fail *open*, so this fails
      *closed* instead, resumable exactly like ``no_gate_evidence``;
    * green with a readable log → ``pr_ready`` with ``gated_sha = merged_sha`` and
      bounded evidence drawn from the supplied log (AC-2);
    * red (non-zero ``--gate-exit``) →
      :func:`~harness.promotion_gate.classify_gate_failure` (``needs_ticket``)
      with bounded evidence and no gated SHA (AC-3). An unreadable log alongside a
      red exit changes nothing here — the promotion is already halted for a human,
      not advancing on unearned trust.
    """
    command = load_gate_command(worktree)
    if command is None:
        return "opened", None, None, None
    if gate_exit is None:
        return "gate_pending", None, None, _NO_GATE_EVIDENCE_REASON
    evidence = evidence_from_report(command, gate_exit=gate_exit, gate_log=gate_log)
    if evidence.passed and evidence.log_unreadable:
        return "gate_pending", None, None, _GATE_LOG_UNREADABLE_REASON
    if evidence.passed:
        return "pr_ready", merged_sha, evidence.evidence, None
    status = classify_gate_failure(evidence)
    return cast(PromotionStatus, status), None, evidence.evidence, None


@promote_app.command("start", help="Open a promotion: merge --from into --to and classify.")
def start_command(
    repo: Path | None = typer.Option(
        None, "--repo", help=REPO_OPTION_HELP
    ),
    from_branch: str = typer.Option(
        "dev", "--from", help="Source branch to promote from (default: dev)."
    ),
    to_branch: str = typer.Option(
        "staging", "--to", help="Target branch to promote into (default: staging)."
    ),
    gate_exit: int | None = typer.Option(
        None,
        "--gate-exit",
        help="Exit code of the caller's host-side verify gate on the merged tree "
        "(CAL-1159). Omit to leave a gated repo at 'gate_pending' for the caller to "
        "gate and resume via 'continue'.",
    ),
    gate_log: Path | None = typer.Option(
        None,
        "--gate-log",
        help="Path to the gate's captured output; a bounded tail is recorded as evidence.",
    ),
    db: Path | None = typer.Option(
        None, "--db", help="Path to harness.db (defaults to .harness/harness.db under --repo)."
    ),
    json_output: bool = typer.Option(
        True, "--json", help="Emit machine-readable JSON (always on)."
    ),
) -> None:
    """Open a promotion: create the worktree/branch, attempt the merge, classify (CAL-1115)."""
    repo_root = resolve_repo_argument(repo)
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

    # 4. Record the promotion. A clean merge is classified against the caller's
    #    reported gate (CAL-1159) → `pr_ready` (green, with a gated SHA),
    #    `needs_ticket` (red), `gate_pending` (a gate is defined but no evidence was
    #    supplied — merged, awaiting a host-side gate), or `opened` (no gate
    #    configured); a conflict carries its merge classification.
    now = iso_z()
    status: PromotionStatus
    reason: str | None
    if outcome.clean:
        status, gated_sha, evidence, reason = _classify_gate(
            worktree, merged_sha=outcome.merged_sha, gate_exit=gate_exit, gate_log=gate_log
        )
    else:
        # A conflict's classification is always a PromotionStatus (agent_may_fix /
        # needs_ticket); typed str|None on MergeOutcome, narrowed here.
        status = cast(PromotionStatus, outcome.classification)
        gated_sha, evidence, reason = None, None, None
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
    _emit_promotion(promotion, outcome, **({"reason": reason} if reason else {}))


#: The promotion states ``continue`` can resume. ``agent_may_fix`` — a merge
#: conflict awaiting one bounded repair; ``gate_pending`` — a clean merge awaiting
#: the caller's host-side gate evidence (CAL-1159). A clean ``opened`` merge has
#: nothing to continue and ``needs_ticket`` must escalate.
_RESUMABLE_STATUSES: frozenset[str] = frozenset({"agent_may_fix", "gate_pending"})


@promote_app.command("continue", help="Resume a promotion after one bounded repair.")
def continue_command(
    promotion_id: str = typer.Option(
        ..., "--promotion-id", help="Id of the promotion to resume."
    ),
    repo: Path | None = typer.Option(
        None, "--repo", help=REPO_OPTION_HELP
    ),
    gate_exit: int | None = typer.Option(
        None,
        "--gate-exit",
        help="Exit code of the caller's host-side verify gate on the resolved/merged "
        "tree (CAL-1159). Omit to leave a gated repo at 'gate_pending'.",
    ),
    gate_log: Path | None = typer.Option(
        None,
        "--gate-log",
        help="Path to the gate's captured output; a bounded tail is recorded as evidence.",
    ),
    db: Path | None = typer.Option(
        None, "--db", help="Path to harness.db (defaults to .harness/harness.db under --repo)."
    ),
    json_output: bool = typer.Option(
        True, "--json", help="Emit machine-readable JSON (always on)."
    ),
) -> None:
    """Resume a promotion: complete a bounded repair, or classify a supplied gate.

    Two states resume here (CAL-1115, CAL-1159). An ``agent_may_fix`` conflict is
    completed (the one bounded repair, attempt counted) and then classified against
    the caller's gate evidence — the staged resolution *is* the merged tree, so a
    gate the caller ran on it is valid. A ``gate_pending`` merge is already
    committed; ``continue`` only classifies the gate the caller has since run.
    Either way the gate runs host-side and is reported via ``--gate-exit`` /
    ``--gate-log`` (the ``review`` boundary), never executed by the verb.
    """
    repo_root = resolve_repo_argument(repo)
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

    if promotion.status not in _RESUMABLE_STATUSES:
        _refuse(
            "not_resumable",
            f"promotion {promotion_id} is {promotion.status!r}, not one of "
            f"{sorted(_RESUMABLE_STATUSES)} — nothing to continue",
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

    if promotion.status == "agent_may_fix":
        # Complete the repaired merge — refuses `dirty_worktree` (with the still-
        # unresolved files) if the orchestrator's repair left any conflict unstaged.
        # The bounded attempt (ADR 0003) is spent here, whatever the gate then says.
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
        merged_sha = outcome.merged_sha
        attempts = promotion.attempts + 1
    else:
        # `gate_pending`: the merge is already committed (start, or a prior
        # continue). There is nothing to repair — only the caller's gate to
        # classify — so no attempt is spent.
        outcome = mechanics.MergeOutcome(clean=True, merged_sha=promotion.merged_sha)
        merged_sha = promotion.merged_sha
        attempts = promotion.attempts

    # Classify against the gate the caller ran host-side. Green → `pr_ready` (gated
    # SHA == merged HEAD); red → `needs_ticket`; no evidence yet, or an unreadable
    # `--gate-log` (#188), → `gate_pending`; no gate configured → `opened` (ungated).
    status, gated_sha, evidence, reason = _classify_gate(
        worktree, merged_sha=merged_sha, gate_exit=gate_exit, gate_log=gate_log
    )
    updated = promotion.model_copy(
        update={
            "status": status,
            "merged_sha": merged_sha,
            "gated_sha": gated_sha,
            "evidence": evidence,
            "attempts": attempts,
            "updated_at": iso_z(),
        }
    )
    asyncio.run(promotions.update_promotion(updated, db_path=db_path))
    _emit_promotion(updated, outcome, **({"reason": reason} if reason else {}))


@promote_app.command("status", help="Report a promotion's lifecycle state (read-only).")
def status_command(
    promotion_id: str = typer.Option(
        ..., "--promotion-id", help="Id of the promotion to read."
    ),
    repo: Path | None = typer.Option(
        None, "--repo", help=REPO_OPTION_HELP
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
    repo: Path | None = typer.Option(
        None, "--repo", help=REPO_OPTION_HELP
    ),
    db: Path | None = typer.Option(
        None, "--db", help="Path to harness.db (defaults to .harness/harness.db under --repo)."
    ),
    json_output: bool = typer.Option(
        True, "--json", help="Emit machine-readable JSON (always on)."
    ),
) -> None:
    """Open the promotion PR — gated (CAL-1114), then push + create the PR (CAL-1117)."""
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
    repo_root = resolve_repo_argument(repo)
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

    # Both gates pass — publish. HOW depends on the hop (CAL-1158): the staging hop
    # lands the gated candidate on the target itself and is done; the release hop
    # pushes the promotion branch and opens a PR for a human to merge. A push / gh
    # failure surfaces as a structured refusal, never a bare traceback.
    branch = promotion.promotion_branch
    gated_sha = promotion.gated_sha
    if branch is None or gated_sha is None:
        # pr_gate_satisfied guarantees a gated SHA, and a real pr_ready promotion
        # always carries its branch. A row missing either is malformed — refuse
        # rather than push a None ref. (Also narrows the Optionals for the push.)
        integrity_reason: PromotionRefusalReason = "gate_not_satisfied"
        _refuse(
            integrity_reason,
            "promotion is missing its branch or gated SHA — cannot open a PR",
            command="promote pr",
            promotion_id=promotion_id,
            status=promotion.status,
        )

    db_path = resolve_verb_db_path(db, repo_root)
    if promotion.to_branch == DIRECT_PUSH_TARGET:
        updated = _land_on_target(
            promotion, repo_root=repo_root, gated_sha=gated_sha, promotion_id=promotion_id
        )
    else:
        updated = _open_release_pr(
            promotion,
            repo_root=repo_root,
            branch=branch,
            gated_sha=gated_sha,
            promotion_id=promotion_id,
        )
    asyncio.run(promotions.update_promotion(updated, db_path=db_path))
    typer.echo(updated.model_dump_json())


def _land_on_target(
    promotion: Promotion, *, repo_root: Path, gated_sha: str, promotion_id: str
) -> Promotion:
    """Publish the **staging hop**: advance the target to the gated SHA; no PR.

    Staging is *derived* — the green gate is the whole decision, so there is no PR
    to open and nothing for a human to judge (ADR 0003 as amended 2026-07-17). Only
    the target ref moves: the promotion branch is deliberately **not** pushed, since
    no PR will reference it. Terminal state is ``promoted``, not ``pr_opened`` —
    the ledger must not claim a PR that does not exist.
    """
    try:
        push_target_branch(repo_root, target=promotion.to_branch, gated_sha=gated_sha)
    except mechanics.PromotionMechanicsError as exc:
        _refuse(
            exc.reason,
            str(exc),
            command="promote pr",
            promotion_id=promotion_id,
            status=promotion.status,
        )
    return promotion.model_copy(update={"status": "promoted", "updated_at": iso_z()})


def _open_release_pr(
    promotion: Promotion,
    *,
    repo_root: Path,
    branch: str,
    gated_sha: str,
    promotion_id: str,
) -> Promotion:
    """Publish the **release hop**: push the promotion branch and open the PR.

    ``main`` is *decided* — merging the release PR stays a deliberate human/CI act,
    so the harness pushes only the promotion branch (never the target), drafts the
    prose from deterministic facts, and records the PR URL + the terminal
    ``pr_opened`` state (CAL-1117, ADR 0003 "PR authority").
    """
    try:
        push_promotion_branch(repo_root, branch)
        facts = collect_promotion_facts(
            repo_root,
            from_branch=promotion.from_branch,
            to_branch=promotion.to_branch,
            gated_sha=gated_sha,
        )
        outcome = create_pull_request(
            repo_root,
            base=promotion.to_branch,
            head=branch,
            title=build_pr_title(facts),
            body=build_pr_body(facts, evidence=promotion.evidence),
        )
    except mechanics.PromotionMechanicsError as exc:
        _refuse(
            exc.reason,
            str(exc),
            command="promote pr",
            promotion_id=promotion_id,
            status=promotion.status,
        )
    return promotion.model_copy(
        update={
            "status": "pr_opened",
            "pr_url": outcome.url,
            "updated_at": iso_z(),
        }
    )


def _promotion_conflict_files(promotion: Promotion) -> tuple[str, ...]:
    """The promotion worktree's conflicted paths — best-effort, never raises.

    Read live from the worktree (the conflicts are not stored on the row). An
    absent or already-clean worktree yields none, so escalation stays robust even
    when the worktree was torn down or never conflicted. A git-exec failure
    (``OSError``) also degrades to empty rather than crashing the safety path.
    """
    if promotion.worktree_path is None:
        return ()
    worktree = Path(promotion.worktree_path)
    if not worktree.exists():
        return ()
    try:
        return mechanics.conflicted_files(worktree)
    except OSError:
        return ()


def _reescalation_comment(body: str) -> str:
    """Prefix the escalation body as a re-escalation update comment (AC-2)."""
    return (
        "**Re-escalation update** — the promotion re-entered the escalate path "
        "with the current evidence below.\n\n" + body
    )


@promote_app.command(
    "escalate", help="File/update a tracker ticket and mark the promotion escalated."
)
def escalate_command(
    promotion_id: str = typer.Option(
        ..., "--promotion-id", help="Id of the promotion to escalate."
    ),
    repo: Path | None = typer.Option(
        None, "--repo", help=REPO_OPTION_HELP
    ),
    project: str | None = typer.Option(
        None,
        "--project",
        help="Tracker project scope (default: CONTEXT.md repo.project; may be unset).",
    ),
    db: Path | None = typer.Option(
        None, "--db", help="Path to harness.db (defaults to .harness/harness.db under --repo)."
    ),
    json_output: bool = typer.Option(
        True, "--json", help="Emit machine-readable JSON (always on)."
    ),
) -> None:
    """Escalate a blocked promotion: file or update a tracker ticket, mark it
    ``escalated`` (CAL-1118). Idempotent — a promotion already linked to an
    escalation ticket is commented on, not duplicated (AC-2).

    The tracker is resolved through :func:`~harness.tracker.tracker_client`, the
    same seam every other writing verb uses, so the terminal works on whichever
    backend ``CONTEXT.md`` → ``tracker:`` names (#328). This verb never constructs
    a backend client and never catches a backend-specific error.
    """
    promotion = _read_or_not_found("escalate", promotion_id, repo, db)
    repo_root = resolve_repo_argument(repo)
    db_path = resolve_verb_db_path(db, repo_root)

    # The scope is nullable (#174/#248): the flag overrides CONTEXT.md's
    # repo.project, and unset means the backend's natural queue rather than an
    # error. There is no team to resolve here — that is a Linear-only fact, and it
    # now lives inside the Linear client as config (#328).
    project_name = project or repo_config.repo_project(repo_root)

    # The body is rendered before the client is resolved, so the `no_tracker`
    # refusal below can carry the evidence it cannot file anywhere.
    title = build_escalation_title(promotion)
    body = build_escalation_body(
        promotion, conflict_files=_promotion_conflict_files(promotion)
    )

    # AC-4: tracker configuration that prevents escalation → a structured
    # `blocked` result (never a raw traceback), on either backend: a missing
    # credential, an absent `github:` block, or a Linear client with no team. The
    # promotion row is left untouched — escalation did not happen, so its state
    # must not advance to `escalated`.
    try:
        client = tracker_client(repo_root)
    except TrackerConfigError as exc:
        _refuse(
            "blocked",
            str(exc),
            command="promote escalate",
            promotion_id=promotion_id,
            status=promotion.status,
        )

    if client is None:
        # `tracker: none` — there is nowhere to file. The refusal carries the
        # rendered evidence because nothing else will: the promotion row does not
        # store it, and with no tracker the operator *is* the escalation target.
        # Recording the terminal `escalated` with a null ticket is the wrong
        # alternative — `escalated` means a ticket is waiting for a human.
        _refuse(
            "no_tracker",
            "this repo runs tracker-less (CONTEXT.md tracker: none) — there is no "
            "tracker to escalate into; the evidence is in this payload",
            command="promote escalate",
            promotion_id=promotion_id,
            status=promotion.status,
            escalation_title=title,
            escalation_body=body,
        )

    try:
        if promotion.escalation_ticket is None:
            # AC-1: first escalation — file a Todo issue carrying the evidence.
            created = asyncio.run(
                client.create_issue(
                    title=title,
                    description=body,
                    project=project_name,
                )
            )
            ticket_id = created["identifier"]
            escalation_url: str | None = created["url"]
            action = "created"
        else:
            # AC-2: already linked — comment on the existing ticket, no duplicate.
            ticket_id = promotion.escalation_ticket
            asyncio.run(client.post_comment(ticket_id, _reescalation_comment(body)))
            escalation_url = None
            action = "updated"
    except TrackerConfigError as exc:
        # A config gap can surface here as well as at the factory: a backend owns
        # facts a neutral verb must not pre-check, so it raises when it first needs
        # one — `LinearClient.create_issue` does exactly this for a client with no
        # team. Both points are the same `blocked` terminal; catching only the
        # factory left this one exiting 1 with a raw traceback.
        _refuse(
            "blocked",
            str(exc),
            command="promote escalate",
            promotion_id=promotion_id,
            status=promotion.status,
        )
    except (TrackerNotFound, TrackerRequestError) as exc:
        _refuse(
            "escalation_failed",
            str(exc),
            command="promote escalate",
            promotion_id=promotion_id,
        )

    # AC-3: record the escalation ticket + the terminal `escalated` state.
    updated = promotion.model_copy(
        update={
            "status": "escalated",
            "escalation_ticket": ticket_id,
            "updated_at": iso_z(),
        }
    )
    asyncio.run(promotions.update_promotion(updated, db_path=db_path))
    payload = {
        **json.loads(updated.model_dump_json()),
        "action": action,
        "escalation_url": escalation_url,
    }
    typer.echo(json.dumps(payload))
