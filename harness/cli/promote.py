"""``harness promote`` — the promotion lifecycle command group (ADR 0003).

Promotion moves completed work toward release as a **first-class, audited
harness lifecycle** — the same shape as the build verbs (``start`` → ``review``
→ ``close``), applied to branch movement over a universal ``dev -> staging ->
main`` topology (`specs/decisions/0003-promotion-lifecycle.md`). An external
orchestrator triggers it and may repair within a narrow policy; the harness owns
every state transition and records it in a promotion ledger.

CAL-1113 registered the group and its five subcommands with stable flags. This
module now also carries CAL-1114 — the **read-path JSON contract** over the
promotion ledger (:mod:`harness.state.promotions`): ``status`` reads a promotion
by id and emits the typed :class:`~harness.state.promotions.Promotion` view, and
``pr`` enforces the PR gate (it refuses unless the promotion is ``pr_ready`` with
a gated SHA). The three write-path bodies — ``start`` / ``continue`` /
``escalate`` — are still **stubs** reporting ``not_implemented``; their mechanics
land against this fixed surface (worktree/merge CAL-1115, gate evidence CAL-1116,
PR creation CAL-1117, escalation CAL-1118). ``pr`` on a gate-*satisfied*
promotion also reports ``not_implemented`` — the refusal is CAL-1114's, the PR
push itself is CAL-1117's.

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
from typing import Literal

import typer

from harness.cli._repo import resolve_repo_root_or_exit, resolve_verb_db_path
from harness.state import promotions

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
    json_output: bool = typer.Option(
        False, "--json", help="Emit machine-readable JSON."
    ),
) -> None:
    """Open a promotion (stub — CAL-1115+ implements the worktree/merge)."""
    _not_implemented("start", repo=str(repo), **{"from": from_branch, "to": to_branch})


@promote_app.command("continue", help="Resume a promotion after one bounded repair.")
def continue_command(
    repo: Path = typer.Option(
        Path("."), "--repo", help="Repo root of the open promotion."
    ),
    json_output: bool = typer.Option(
        False, "--json", help="Emit machine-readable JSON."
    ),
) -> None:
    """Resume after a bounded repair (stub — CAL-1115/1116 implement the retry)."""
    _not_implemented("continue", repo=str(repo))


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
