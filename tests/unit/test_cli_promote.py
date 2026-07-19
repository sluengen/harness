"""``harness promote`` v1 surface contract — CAL-1113 (ADR 0003).

The promotion lifecycle (``dev -> staging -> main``, ADR 0003) is driven through a
``harness promote`` command group. CAL-1113 locked that **surface** before any
mechanics existed: the group registers its v1 subcommands with stable flags. The
mechanics then fill the stub bodies against that fixed surface — the ledger +
read-path JSON contract (CAL-1114), worktree/merge (CAL-1115), gate evidence
(CAL-1116), PR creation (CAL-1117), escalation (CAL-1118).

Command-name/subcommand-set drift is locked in ``test_cli_surface_locked.py``;
this module exercises the surface: every subcommand is invocable and exposes its
documented flags. As of CAL-1118 the whole surface is wired — no subcommand
remains a ``not_implemented`` stub. The mechanics each have their own module: the
ledger + read-path JSON contract (``status`` / ``pr``) in
``test_promotion_contract_locked.py``, the worktree/merge openers (``start`` /
``continue``) in ``test_cli_promote_start.py``, and escalation
(``escalate``) in ``test_cli_promote_escalate.py``.
"""

from __future__ import annotations

import re

import pytest
from typer.testing import CliRunner

from harness.cli import app

cli_runner = CliRunner()


def _help_text(*argv: str) -> str:
    """Return ``--help`` output with ANSI colour codes and rich box borders
    stripped and whitespace collapsed, so a flag can be matched regardless of how
    the renderer wrapped *or coloured* it across lines.

    CI renders help with colour at 80 cols (``FORCE_COLOR``); the ANSI SGR codes
    then interleave the help text, so a contiguous-substring check passes locally
    (no colour) but fails on CI unless they are stripped first (CAL-751)."""
    out = cli_runner.invoke(app, [*argv, "--help"]).output
    out = re.sub(r"\x1b\[[0-9;]*m", "", out)  # strip ANSI SGR colour codes
    return re.sub(r"\s+", " ", re.sub(r"[│|]", " ", out))

#: The v1 subcommands and the flags each documents / exposes. Kept in step with
#: the SPEC §11 / cli-surface.md surface blocks, which the surface-lock tests
#: assert against the live app.
_SUBCOMMANDS = ("start", "continue", "status", "pr", "escalate")


def test_promote_group_help_lists_the_v1_subcommands() -> None:
    """``harness promote --help`` names the five v1 subcommands (surface exists)."""
    result = cli_runner.invoke(app, ["promote", "--help"])
    assert result.exit_code == 0, result.output
    help_text = _help_text("promote")
    for sub in _SUBCOMMANDS:
        assert sub in help_text, f"promote --help omits `{sub}`: {help_text}"


@pytest.mark.parametrize("sub", _SUBCOMMANDS)
def test_promote_subcommand_help_is_invocable(sub: str) -> None:
    """Each subcommand's ``--help`` renders (the command is really registered)."""
    result = cli_runner.invoke(app, ["promote", sub, "--help"])
    assert result.exit_code == 0, result.output


def test_promote_start_exposes_from_and_to_flags() -> None:
    """``promote start`` documents the branch endpoints ``--from`` / ``--to``.

    The design pins ``harness promote start --repo . --from dev --to staging``, so
    the endpoints are part of the v1 surface even while the body is a stub.
    """
    result = cli_runner.invoke(app, ["promote", "start", "--help"])
    assert result.exit_code == 0, result.output
    help_text = _help_text("promote", "start")
    assert "--from" in help_text
    assert "--to" in help_text


def test_promote_start_defaults_are_dev_to_staging() -> None:
    """The design default ``dev`` → ``staging`` is documented on the endpoints
    (ADR 0003). Asserted via ``--help`` rather than a bare run — ``start`` now does
    real git work, so its full behaviour is covered in ``test_cli_promote_start.py``."""
    result = cli_runner.invoke(app, ["promote", "start", "--help"])
    assert result.exit_code == 0, result.output
    help_text = _help_text("promote", "start")
    assert "dev" in help_text
    assert "staging" in help_text
