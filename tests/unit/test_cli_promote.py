"""``harness promote`` v1 surface contract — CAL-1113 (ADR 0003).

The promotion lifecycle (``dev -> staging -> main``, ADR 0003) is driven through a
``harness promote`` command group. This ticket locks that **surface** before any
mechanics exist: the group registers its v1 subcommands with stable flags, and
each subcommand is a contract stub that reports ``not_implemented`` rather than
half-doing a promotion. The mechanics — ledger + JSON contracts (CAL-1114),
worktree/merge (CAL-1115), gate evidence (CAL-1116), PR creation (CAL-1117),
escalation (CAL-1118) — fill the stub bodies against this fixed surface.

Command-name/subcommand-set drift is locked in ``test_cli_surface_locked.py``;
this module exercises the *stubs* — that they are invocable, expose the
documented flags, and emit a structured ``not_implemented`` marker with the
stable exit code, so an orchestrator can tell "surface exists, mechanics
pending" apart from a real error.
"""

from __future__ import annotations

import json

import pytest
from typer.testing import CliRunner

from harness.cli import app

cli_runner = CliRunner()

#: The v1 subcommands and the flags each documents / exposes. Kept in step with
#: the SPEC §11 / cli-surface.md surface blocks, which the surface-lock tests
#: assert against the live app.
_SUBCOMMANDS = ("start", "continue", "status", "pr", "escalate")


def test_promote_group_help_lists_the_v1_subcommands() -> None:
    """``harness promote --help`` names the five v1 subcommands (surface exists)."""
    result = cli_runner.invoke(app, ["promote", "--help"])
    assert result.exit_code == 0, result.output
    for sub in _SUBCOMMANDS:
        assert sub in result.output, f"promote --help omits `{sub}`: {result.output}"


@pytest.mark.parametrize("sub", _SUBCOMMANDS)
def test_promote_subcommand_help_is_invocable(sub: str) -> None:
    """Each subcommand's ``--help`` renders (the command is really registered)."""
    result = cli_runner.invoke(app, ["promote", sub, "--help"])
    assert result.exit_code == 0, result.output


@pytest.mark.parametrize("sub", _SUBCOMMANDS)
def test_promote_stub_reports_not_implemented(sub: str) -> None:
    """Each stub emits a structured ``not_implemented`` marker and exits 2.

    A contract stub must not masquerade as success (exit 0) nor as an
    infrastructure error — it reports, in machine-readable form, that the surface
    is locked but the mechanics are pending, so an orchestrator branches cleanly.
    """
    result = cli_runner.invoke(app, ["promote", sub])
    assert result.exit_code == 2, result.output
    payload = json.loads(result.output)
    assert payload["error"] == "not_implemented"
    assert payload["command"] == f"promote {sub}"


def test_promote_start_exposes_from_and_to_flags() -> None:
    """``promote start`` documents the branch endpoints ``--from`` / ``--to``.

    The design pins ``harness promote start --repo . --from dev --to staging``, so
    the endpoints are part of the v1 surface even while the body is a stub.
    """
    result = cli_runner.invoke(app, ["promote", "start", "--help"])
    assert result.exit_code == 0, result.output
    assert "--from" in result.output
    assert "--to" in result.output


def test_promote_start_defaults_are_dev_to_staging() -> None:
    """The stub echoes its resolved endpoints so the design default is observable:
    ``--from`` defaults to ``dev`` and ``--to`` to ``staging`` (ADR 0003)."""
    result = cli_runner.invoke(app, ["promote", "start"])
    payload = json.loads(result.output)
    assert payload["from"] == "dev"
    assert payload["to"] == "staging"
