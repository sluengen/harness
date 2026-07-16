"""``harness promote`` — the promotion lifecycle command group (ADR 0003).

Promotion moves completed work toward release as a **first-class, audited
harness lifecycle** — the same shape as the build verbs (``start`` → ``review``
→ ``close``), applied to branch movement over a universal ``dev -> staging ->
main`` topology (`specs/decisions/0003-promotion-lifecycle.md`). An external
orchestrator triggers it and may repair within a narrow policy; the harness owns
every state transition and records it in a promotion ledger.

This module is the **v1 surface contract** (CAL-1113). It registers the group
and its five subcommands with stable flags, but the bodies are **stubs**: each
reports ``not_implemented`` rather than half-performing a promotion. The
mechanics land against this fixed surface — the ledger + JSON contracts
(CAL-1114), worktree/merge mechanics (CAL-1115), gate evidence (CAL-1116), PR
creation (CAL-1117), and escalation (CAL-1118).

The five subcommands are the real orchestrator **pause points**:

* ``start``    — open a promotion: create the worktree + promotion branch and
  attempt the ``--from`` → ``--to`` merge, returning a policy classification.
* ``continue`` — resume after one bounded, in-policy repair: re-run
  classification and the gate, incrementing the attempt count.
* ``status``   — read-only: report a promotion's current lifecycle state.
* ``pr``       — the success finalizer: push the promotion branch and open the PR.
* ``escalate`` — the non-success terminal path: file/update a Linear ticket with
  the evidence and mark the promotion ``escalated``.

There is deliberately **no ``verify`` command**: gate execution lives *inside*
``start`` and ``continue`` (a promotion cannot reach ``pr_ready`` without fresh
gate evidence), so a standalone ``verify`` would name a step that is never an
independent pause/resume point.
"""

from __future__ import annotations

import json
from pathlib import Path

import typer

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
    repo: Path = typer.Option(
        Path("."), "--repo", help="Repo root of the promotion."
    ),
    json_output: bool = typer.Option(
        False, "--json", help="Emit machine-readable JSON."
    ),
) -> None:
    """Report the promotion's lifecycle state (stub — CAL-1114 adds the ledger)."""
    _not_implemented("status", repo=str(repo))


@promote_app.command("pr", help="Finalize a green promotion: push the branch and open the PR.")
def pr_command(
    repo: Path = typer.Option(
        Path("."), "--repo", help="Repo root of the promotion."
    ),
    json_output: bool = typer.Option(
        False, "--json", help="Emit machine-readable JSON."
    ),
) -> None:
    """Open the promotion PR (stub — CAL-1117 implements PR creation)."""
    _not_implemented("pr", repo=str(repo))


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
