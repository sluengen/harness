"""``harness promote`` v1 surface contract — CAL-1113 (ADR 0003).

The promotion lifecycle (``dev -> staging -> main``, ADR 0003) is driven through a
``harness promote`` command group. CAL-1113 locked that **surface** before any
mechanics existed: the group registers its v1 subcommands with stable flags. The
mechanics then fill the stub bodies against that fixed surface — the ledger +
read-path JSON contract (CAL-1114), worktree/merge (CAL-1115), gate evidence
(CAL-1116), PR creation (CAL-1117), escalation (CAL-1118).

Command-name/subcommand-set drift is locked in ``test_cli_surface_locked.py``;
this module exercises the surface: every subcommand is invocable and exposes its
documented flags, and the three still-stubbed write-path bodies
(``start`` / ``continue`` / ``escalate``) emit a structured ``not_implemented``
marker with the stable exit code, so an orchestrator can tell "surface exists,
mechanics pending" apart from a real error. The two ledger-backed read-path
bodies wired in CAL-1114 (``status`` / ``pr``) have their JSON contract locked in
``test_promotion_contract_locked.py``.
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

#: The write-path subcommands whose bodies are still contract stubs. ``status`` /
#: ``pr`` were wired to the ledger in CAL-1114, and ``start`` / ``continue`` to the
#: worktree/merge mechanics in CAL-1115 (they do real git work and are covered in
#: ``test_cli_promote_start.py``), so only ``escalate`` (CAL-1118) still emits
#: ``not_implemented`` on a bare invocation.
_STUB_SUBCOMMANDS = ("escalate",)


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


@pytest.mark.parametrize("sub", _STUB_SUBCOMMANDS)
def test_promote_stub_reports_not_implemented(sub: str) -> None:
    """Each still-stubbed write-path body emits ``not_implemented`` and exits 2.

    A contract stub must not masquerade as success (exit 0) nor as an
    infrastructure error — it reports, in machine-readable form, that the surface
    is locked but the mechanics are pending, so an orchestrator branches cleanly.
    (``status`` / ``pr`` are wired in CAL-1114 — see the contract-lock module.)
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
    """The design default ``dev`` → ``staging`` is documented on the endpoints
    (ADR 0003). Asserted via ``--help`` rather than a bare run — ``start`` now does
    real git work, so its full behaviour is covered in ``test_cli_promote_start.py``."""
    result = cli_runner.invoke(app, ["promote", "start", "--help"])
    assert result.exit_code == 0, result.output
    assert "dev" in result.output
    assert "staging" in result.output
