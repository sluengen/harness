"""v2-reserved CLI surface — see SPEC §11 (Decisions).

The four verbs below are part of the v2 human-in-the-loop decision flow:

* ``slate-harness decisions list``               — enumerate paused runs
* ``slate-harness decision show <run-id>``       — display the question + state
* ``slate-harness decision approve <run-id>``    — resume from the decision node
* ``slate-harness decision reject <run-id>``     — apply the on_reject path

Per SPEC, the *names* are reserved in v1 so callers can plan for them
without churn at the v1→v2 boundary. The bodies error gracefully with the
message ``"deferred to v2"`` and exit code **2** (invocation error per
SPEC §11 exit table). With ``--json``, the message is emitted as
``{"error": "deferred to v2"}`` on stdout; without ``--json``, it goes to
stderr so stdout stays empty for pipes.

The v1 contract pinned by tests:

* exit code is **2** for every verb
* stdout is empty in the human form; the JSON form emits exactly the
  ``{"error": "deferred to v2"}`` object
* ``--help`` text on each command begins with ``"v2-reserved — not yet
  implemented"`` so users discover the surface but understand it's inert

When v2 lands, the bodies are replaced with real implementations and the
exit codes shift (``decision approve`` becomes 0/4 etc.) — but the verb
names, flag names, and ``--json`` key shape stay stable.
"""

from __future__ import annotations

import json

import typer

__all__ = ["decisions_app", "decision_app"]


# ---------------------------------------------------------------------------
# Shared "deferred to v2" responder.
#
# Centralised so all four commands route through the same exit-code + payload
# logic. Tests against any one verb effectively cover the others, but we keep
# per-verb tests to lock the wiring.
# ---------------------------------------------------------------------------


_DEFERRED_MESSAGE = "deferred to v2"
_RESERVED_HELP = "v2-reserved — not yet implemented (see SPEC §11)."


def _reserved_v2(json_output: bool) -> None:
    """Emit the canonical ``deferred to v2`` response and raise ``typer.Exit``.

    Always raises :class:`typer.Exit` with code 2; never returns normally.
    Callers don't need to ``raise`` themselves — the typed return is ``None``
    to keep call-sites tidy at the Typer command boundary.
    """
    if json_output:
        typer.echo(json.dumps({"error": _DEFERRED_MESSAGE}))
    else:
        typer.echo(_DEFERRED_MESSAGE, err=True)
    raise typer.Exit(code=2)


# ---------------------------------------------------------------------------
# ``slate-harness decisions`` (plural) — only one verb today (``list``), but kept as
# a sub-app for symmetry with ``decision`` and to leave room for v2 verbs like
# ``decisions count`` without restructuring.
# ---------------------------------------------------------------------------


decisions_app = typer.Typer(
    help="v2-reserved — enumerate paused runs awaiting human decision.",
    no_args_is_help=True,
)


@decisions_app.command("list", help=_RESERVED_HELP)
def decisions_list_command(
    json_output: bool = typer.Option(
        False, "--json", help="Emit machine-readable JSON."
    ),
) -> None:
    """List paused runs — v2-reserved, not yet implemented."""
    _reserved_v2(json_output)


# ---------------------------------------------------------------------------
# ``harness decision`` (singular) — show / approve / reject. Three verbs, so
# a sub-app is the idiomatic Typer pattern.
# ---------------------------------------------------------------------------


decision_app = typer.Typer(
    help="v2-reserved — inspect or resolve a paused decision node.",
    no_args_is_help=True,
)


@decision_app.command("show", help=_RESERVED_HELP)
def decision_show_command(
    run_id: str = typer.Argument(..., help="Run identifier (ULID)."),
    json_output: bool = typer.Option(
        False, "--json", help="Emit machine-readable JSON."
    ),
) -> None:
    """Show a paused decision — v2-reserved, not yet implemented."""
    _reserved_v2(json_output)


@decision_app.command("approve", help=_RESERVED_HELP)
def decision_approve_command(
    run_id: str = typer.Argument(..., help="Run identifier (ULID)."),
    comment: str | None = typer.Option(
        None, "--comment", help="Optional decision comment (captured to event log)."
    ),
    json_output: bool = typer.Option(
        False, "--json", help="Emit machine-readable JSON."
    ),
) -> None:
    """Approve a paused decision — v2-reserved, not yet implemented."""
    _reserved_v2(json_output)


@decision_app.command("reject", help=_RESERVED_HELP)
def decision_reject_command(
    run_id: str = typer.Argument(..., help="Run identifier (ULID)."),
    comment: str | None = typer.Option(
        None, "--comment", help="Optional decision comment (captured to event log)."
    ),
    json_output: bool = typer.Option(
        False, "--json", help="Emit machine-readable JSON."
    ),
) -> None:
    """Reject a paused decision — v2-reserved, not yet implemented."""
    _reserved_v2(json_output)
