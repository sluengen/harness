"""``harness certify`` — the deterministic trivial fast path (#353).

Item 2 of ``specs/proposals/assurance-led-lifecycle.md``. #352 taught the
harness that a level *means* something; it could not honour ``trivial``, because
skipping the LLM review is only safe once something else can prove that the diff
being skipped is one nobody needed to read. This verb is that proof, and it has
exactly two answers:

* **certified** — every changed path is allowlisted and unrestricted, the repo's
  verify gate is green at this HEAD, and the tree is clean. A ``certify`` event
  is appended, bound to the SHA. ``close`` accepts it as the second kind of
  evidence. No engine runs, and no ``review`` event is written: a synthetic pass
  would enter ``harness stats``' verdict-by-engine table as a real one.
* **assurance_upgraded** — anything else about the *diff*. The run row moves to
  ``simple``, the issue's label follows, a comment records the reason, and the
  verb exits **0**, because a correct upgrade is the safety mechanism working
  and an unattended loop must not read it as an error.

A red or missing gate is neither: it is a **refusal** (exit
:data:`~harness.cli.review.EXIT_GATE_FAILED`, the same two tags ``review``
already emits). The upgrade trigger is an ineligible diff; "come back when the
gate is green" is the answer to a red one, and upgrading there would let a red
tree quietly buy a review the run had not earned the right to ask for.

Ordering is the contract
------------------------
Every check that can refuse runs **before** any mutation, and on the upgrade path
the stricter run state is committed **before** the tracker is touched. So a
tracker outage cannot leave a run whose row still says ``trivial`` while its
issue says ``simple``: the row is authoritative, the sync is best-effort, and a
partial sync is reported by naming the artifact rather than by rolling anything
back.

The ``UPDATE`` carries ``AND assurance = 'trivial'`` in its WHERE clause, which
is what makes the column **monotone**. Idempotent under a concurrent upgrade,
and structurally incapable of downgrading a ``simple`` or ``complex`` run — not
a convention someone has to remember, but a property of the statement.
"""

from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path
from typing import Literal

import typer
from pydantic import BaseModel

from harness import close_merge
from harness._git import GitError, diff_paths, rev_parse_head
from harness._time import elapsed_ms, iso_z
from harness.assurance import DEFAULT_ASSURANCE, DIFF_INELIGIBLE_REASON, required_stages
from harness.cli._repo import REPO_OPTION, resolve_repo_argument, resolve_verb_db_path
from harness.cli._runs import read_run_assurance, read_run_base_sha, resolve_open_run
from harness.cli._verb import VerbError, run_verb
from harness.cli.certify_tracker import UpgradeSyncError, sync_upgrade
from harness.cli.design_tracker import read_run_ticket
from harness.cli.review import EXIT_GATE_FAILED, GATE_FAILED_REASON, NO_GATE_EVIDENCE_REASON
from harness.events.emitter import EventEmitter
from harness.events.payloads import CertifyEventData
from harness.events.schema import EVENT_TYPES, EventType
from harness.gate import GATE_NOT_CONFIGURED_REASON, load_gate_command, read_gate_log_tail
from harness.state import store
from harness.tracker import Tracker, tracker_client
from harness.tracker_errors import TrackerConfigError
from harness.trivial_diff import (
    CLASSIFIER_VERSION,
    TrivialEligibility,
    classify_paths,
    ineligible,
    load_trivial_allowlist,
)

__all__ = ["certify_command", "CertifyOutput"]

#: The audit event a successful certification appends. A member of
#: ``EVENT_TYPES``; the assert guards against a rename drifting this verb away
#: from the canonical set (the :data:`harness.cli.close._CLOSE_EVENT_TYPE`
#: pattern).
_CERTIFY_EVENT_TYPE: EventType = "certify"
assert _CERTIFY_EVENT_TYPE in EVENT_TYPES

#: The refusals — exactly one is reported, and none of them mutates anything.
#: ``assurance_not_trivial`` is decided through
#: :func:`~harness.assurance.required_stages`, not by comparing the level to a
#: string, which is what finally gives ``RequiredStages.llm_review`` the consumer
#: its docstring recorded as missing.
RefusalReason = Literal[
    "no_run",
    "assurance_not_trivial",
    "dirty_worktree",
    "no_gate_evidence",
    "gate_failed",
]


class CertifyOutput(BaseModel):
    """What ``certify`` decided, and what the run is under now.

    ``assurance`` is the level **in force after this call**, so a caller reads
    the plan it must now follow rather than re-deriving it from ``outcome``.
    ``reason`` is the machine-readable
    :data:`~harness.trivial_diff.IneligibilityReason` on an upgrade and ``None``
    on a certification.

    ``tracker_error`` names the *artifact* that did not synchronize (``label`` or
    ``comment``), never a stack of provider detail: the caller's next action is
    to reconcile that artifact by hand.
    """

    run_id: str
    outcome: Literal["certified", "assurance_upgraded"]
    assurance: str
    tracker_synced: bool
    certified_sha: str | None = None
    reason: str | None = None
    tracker_error: str | None = None


class _CertifyError(VerbError):
    """``certify``'s control-flow exception — a :class:`VerbError`.

    Every raise site passes a :data:`RefusalReason` by keyword, and every one of
    them fires before the verb has written anything.
    """


def certify_command(
    repo: Path | None = REPO_OPTION,
    run_id: str | None = typer.Option(
        None,
        "--run-id",
        help="Explicit run to certify. Defaults to the open run whose worktree is --repo.",
    ),
    gate_exit: int | None = typer.Option(  # noqa: B008
        None,
        "--gate-exit",
        help="Exit code of the repo's verify gate, run in the worktree. Required "
        "when the repo configures one.",
    ),
    gate_log: Path | None = typer.Option(  # noqa: B008
        None,
        "--gate-log",
        help="Path to the verify gate's captured output; its tail is recorded.",
    ),
    db: Path | None = typer.Option(  # noqa: B008
        None,
        "--db",
        help="Path to harness.db (defaults to .harness/harness.db under --repo).",
    ),
    json_output: bool = typer.Option(  # noqa: B008
        True,
        "--json/--no-json",
        help="Emit machine-readable JSON (default: on).",
    ),
) -> None:
    """Certify a trivial run's diff without an LLM review, or upgrade it to simple."""
    repo_root = resolve_repo_argument(repo)
    db_path = resolve_verb_db_path(db, repo_root)

    output = run_verb(
        lambda: asyncio.run(
            _run_certify(
                repo_root=repo_root,
                db_path=db_path,
                run_id=run_id,
                gate_exit=gate_exit,
                gate_log=gate_log,
            )
        ),
        json_output=json_output,
    )

    if json_output:
        typer.echo(output.model_dump_json())
    elif output.outcome == "certified":
        typer.echo(f"certified run {output.run_id} at {output.certified_sha}")
    else:
        typer.echo(
            f"run {output.run_id} upgraded to {output.assurance} ({output.reason}) "
            f"— an LLM review is now required"
        )


async def _run_certify(
    *,
    repo_root: Path,
    db_path: Path,
    run_id: str | None,
    gate_exit: int | None,
    gate_log: Path | None,
) -> CertifyOutput:
    """Drive the certification flow; raise :class:`_CertifyError` on any refusal."""
    invoked_at = iso_z()

    # 1. Resolve the run — the shared rule ``review`` and ``close`` use.
    resolved = await resolve_open_run(db_path, repo_root, run_id)
    if resolved is None:
        where = f"run-id {run_id}" if run_id else f"worktree {repo_root}"
        raise _CertifyError(f"no open run found for {where}", 2, reason="no_run")
    resolved_run_id, worktree_path, _base_branch, _worktree_branch = resolved
    worktree = Path(worktree_path)

    # 2. Guard the level, through the policy table rather than a string compare.
    #    A run whose level requires an LLM review is not this verb's business,
    #    and saying so before any git or tracker work keeps the refusal cheap.
    assurance = await read_run_assurance(db_path, resolved_run_id)
    if required_stages(assurance).llm_review:
        raise _CertifyError(
            f"run {resolved_run_id} is assurance:{assurance}, which requires an "
            f"LLM review — there is nothing for `harness certify` to do. Run "
            f"`harness review` instead.",
            2,
            reason="assurance_not_trivial",
        )

    # 3. Verify-gate evidence, before any mutation and before any classification.
    #    The same contract ``review`` enforces, reused rather than restated so an
    #    orchestrator branches on the two tags it already knows. A repo that
    #    configures no gate is *not* refused here — it is classified ineligible
    #    at step 6, because the trivial path's entire safety argument is the
    #    gate and there is nothing to argue from.
    gate_command = await asyncio.to_thread(load_gate_command, worktree)
    gate_ran = False
    gate_reason: str | None = GATE_NOT_CONFIGURED_REASON
    gate_exit_code: int | None = None
    gate_output_tail: str | None = None
    if gate_command is not None:
        if gate_exit is None:
            raise _CertifyError(
                f"no verify-gate evidence supplied. This repo configures a gate "
                f"({gate_command!r}); run it in the worktree and pass the result "
                f"(--gate-exit <code> [--gate-log <path>]). Nothing was recorded "
                f"and the run's assurance is unchanged — the harness does not "
                f"certify what it cannot show was verified.",
                EXIT_GATE_FAILED,
                reason=NO_GATE_EVIDENCE_REASON,
            )
        gate_output_tail = await asyncio.to_thread(read_gate_log_tail, gate_log)
        if gate_exit != 0:
            raise _CertifyError(
                f"verify gate failed (exit {gate_exit}): {gate_command!r}. Nothing "
                f"was recorded and the run's assurance is unchanged — a red gate "
                f"is not an ineligible diff, so it does not upgrade the run. Fix "
                f"the failure in gate_output_tail and certify again.",
                EXIT_GATE_FAILED,
                reason=GATE_FAILED_REASON,
                extra={"gate_output_tail": gate_output_tail},
            )
        gate_ran = True
        gate_reason = None
        gate_exit_code = gate_exit

    # 4. Refuse a dirty worktree — ``close``'s own predicate, called, not copied.
    #    Certifying a tree whose working copy differs from HEAD would record a
    #    claim about content nobody classified.
    try:
        dirty = await asyncio.to_thread(close_merge.worktree_porcelain, worktree)
    except close_merge.CloseMergeError as exc:
        raise _CertifyError(
            f"failed to read git status for worktree {worktree_path}: {exc}", 1
        ) from exc
    if dirty:
        raise _CertifyError(
            f"worktree {worktree_path} has uncommitted changes; commit them so "
            f"the certification covers the tree that will merge",
            2,
            reason="dirty_worktree",
        )

    # 5. The two SHAs the classification spans.
    try:
        head_sha = await asyncio.to_thread(rev_parse_head, worktree)
    except (GitError, OSError, subprocess.SubprocessError) as exc:
        raise _CertifyError(
            f"failed to read HEAD for worktree {worktree_path}: {exc}", 1
        ) from exc
    base_sha = await read_run_base_sha(db_path, resolved_run_id)

    # 6. Classify.
    eligibility = await _classify(worktree, base_sha, gate_command)

    if eligibility.eligible:
        await _record_certification(
            db_path,
            run_id=resolved_run_id,
            head_sha=head_sha,
            # ``base_sha`` is non-None here: a run without one answers
            # ``no_base_sha`` at step 6 and never reaches this branch.
            base_sha=base_sha or "",
            assurance=assurance,
            eligibility=eligibility,
            gate_command=gate_command,
            gate_ran=gate_ran,
            gate_reason=gate_reason,
            gate_exit_code=gate_exit_code,
            gate_output_tail=gate_output_tail,
            invoked_at=invoked_at,
        )
        return CertifyOutput(
            run_id=resolved_run_id,
            outcome="certified",
            assurance=assurance,
            certified_sha=head_sha,
            tracker_synced=True,
        )

    return await _upgrade(
        repo_root,
        db_path,
        run_id=resolved_run_id,
        eligibility=eligibility,
    )


async def _classify(
    worktree: Path, base_sha: str | None, gate_command: str | None
) -> TrivialEligibility:
    """The eligibility answer for this run, in the order that names the root cause.

    The policy is read from the **run's own worktree**, not from wherever the
    verb was invoked. That is what makes the answer a property of the tree being
    certified rather than of the caller's working directory — and the tree is
    where ``CONTEXT.md`` is a *restricted* path, so a run that edits its own
    allowlist is ineligible on that ground alone, and the whole-run
    ``base_sha...HEAD`` range keeps it ineligible on a later commit too.
    """
    if gate_command is None:
        # ``has_gate_evidence`` accepts an unconfigured gate for a *review* — an
        # engine still read the diff. For a trivial certification it would mean
        # merging with no verification of any kind, so the narrowing lives here,
        # at the write site, and the shared predicate keeps one opinion about
        # what green means.
        return ineligible("gate_not_configured")
    if base_sha is None:
        return ineligible("no_base_sha")
    paths = await asyncio.to_thread(diff_paths, worktree, base_sha)
    if paths is None:
        return ineligible("diff_unreadable")
    return classify_paths(paths, await asyncio.to_thread(load_trivial_allowlist, worktree))


async def _record_certification(
    db_path: Path,
    *,
    run_id: str,
    head_sha: str,
    base_sha: str,
    assurance: str,
    eligibility: TrivialEligibility,
    gate_command: str | None,
    gate_ran: bool,
    gate_reason: str | None,
    gate_exit_code: int | None,
    gate_output_tail: str | None,
    invoked_at: str,
) -> None:
    """Append the ``certify`` event.

    Through :class:`~harness.events.emitter.EventEmitter`, **not**
    ``emit_observation``: this write is load-bearing evidence, not observation, so
    a lost row must fail the verb rather than be swallowed. A certification
    nobody recorded is a run that will be refused at ``close`` — which is the
    safe direction, but it must be *visible* rather than silent.
    """
    created_at = iso_z()
    data = CertifyEventData(
        run_id=run_id,
        certified_sha=head_sha,
        base_sha=base_sha,
        assurance=assurance,
        classifier_version=CLASSIFIER_VERSION,
        eligible_paths=list(eligibility.eligible_paths),
        allowlist=list(eligibility.allowlist),
        gate_ran=gate_ran,
        created_at=created_at,
        gate_command=gate_command,
        gate_exit_code=gate_exit_code,
        gate_reason=gate_reason,
        gate_output_tail=gate_output_tail,
        invoked_at=invoked_at,
        duration_ms=elapsed_ms(invoked_at, created_at),
    )
    await EventEmitter(db_path).emit(
        run_id,
        _CERTIFY_EVENT_TYPE,
        data=data.model_dump(exclude_none=True),
    )


async def _upgrade(
    repo_root: Path,
    db_path: Path,
    *,
    run_id: str,
    eligibility: TrivialEligibility,
) -> CertifyOutput:
    """Persist the stricter state, then synchronize the issue. In that order.

    The ordering is the acceptance criterion, and it is enforced by sequence
    rather than by a transaction spanning the network: the ``UPDATE`` is
    committed before ``tracker_client`` is even resolved, so there is no window
    in which a tracker failure could leave the row behind.

    No event is written on this path. The AC is literal — *"the run and issue
    upgrade to simple and no certification event is written"* — and the outcome
    is already durable in two places (the run row and the tracker comment). The
    consequence, named rather than left implicit: ``certify`` has no ledger
    denominator, so ADR 0009's "every verb records its attempt" does not yet hold
    for it. That is a deferral with a follow-up, not an oversight.
    """
    reason = eligibility.reason or "unlisted_path"
    await _persist_upgrade(db_path, run_id)

    client: Tracker | None
    try:
        client = await asyncio.to_thread(tracker_client, repo_root)
    except TrackerConfigError:
        # The row is already authoritative; an unresolvable tracker is a partial
        # sync, not a failed upgrade, and it is never a reason to roll back.
        return _upgraded(run_id, reason, synced=False, error="client")
    if client is None:
        # Tracker-less: there is nothing to synchronize, so the sync is complete.
        return _upgraded(run_id, reason, synced=True, error=None)

    ticket = await read_run_ticket(db_path, run_id)
    if ticket is None:
        return _upgraded(run_id, reason, synced=False, error="ticket")

    try:
        await sync_upgrade(
            client,
            ticket,
            run_id=run_id,
            reason=reason,
            offending_paths=eligibility.offending_paths,
            classifier_version=CLASSIFIER_VERSION,
        )
    except UpgradeSyncError as exc:
        return _upgraded(run_id, reason, synced=False, error=exc.artifact)
    return _upgraded(run_id, reason, synced=True, error=None)


def _upgraded(
    run_id: str, reason: str, *, synced: bool, error: str | None
) -> CertifyOutput:
    return CertifyOutput(
        run_id=run_id,
        outcome="assurance_upgraded",
        assurance=DEFAULT_ASSURANCE,
        reason=reason,
        tracker_synced=synced,
        tracker_error=error,
    )


async def _persist_upgrade(db_path: Path, run_id: str) -> None:
    """The one statement that mutates ``runs.assurance`` outside ``start``.

    ``AND assurance = 'trivial'`` is the monotonicity mechanism: the statement is
    idempotent under a concurrent upgrade and cannot express a downgrade of a
    ``simple`` or ``complex`` run. Committed before anything reaches the network.
    """
    async with store.connect(db_path) as conn:
        await conn.execute(
            "UPDATE runs SET assurance = ?, assurance_reason = ? "
            "WHERE run_id = ? AND assurance = 'trivial'",
            (DEFAULT_ASSURANCE, DIFF_INELIGIBLE_REASON, run_id),
        )
        await conn.commit()
