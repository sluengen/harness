"""Tests for harness.cli — dynamic workflow subcommand generation (H-023).

See SPEC §11 (CLI Design) and §5 (Inputs and CLI generation). Each test
maps to one acceptance criterion in the H-023 brief:

* AC1 — ``harness run <workflow>`` introspects ``workflows/<workflow>.yaml``
  and registers a subcommand whose options match the YAML's ``inputs:`` block.
* AC2 — InputSpec → CLI parameter mapping (string/integer/boolean, flag form,
  default flag derived from name, position → positional argument, required,
  default, enum, pattern, the schema-level mutual-exclusion of flag+position).
* AC3 — ``harness run <workflow> --help`` prints the workflow's input
  contract — names, types, required/optional, defaults.
* AC4 — ``--base`` defaults to ``main`` and is exposed on every dynamic
  subcommand; it maps to ``Runner.run(base_branch=...)``.
* AC5 — ``harness run <workflow> [args...]`` actually invokes
  ``Runner.run(...)`` and returns the runner's exit code.
* AC6 — Unknown workflow → exit 2 with a clear error.
* AC7 — Workflow YAML invalid (``WorkflowLoadError``) → exit 2 with the
  underlying message.
* AC8 — ``--base`` default is ``main``.
* AC9 — The runner is invoked via ``asyncio.run(...)`` at the CLI boundary.
"""

from __future__ import annotations

import re
import textwrap
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from harness.cli import app
from harness.cli import run as cli_module

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_workflow(path: Path, body: str) -> Path:
    path.write_text(textwrap.dedent(body).lstrip("\n"))
    return path


def _minimal_workflow(tmp_path: Path, *, inputs_block: str = "") -> Path:
    """A loadable workflow YAML with an optional ``inputs:`` block.

    The workflow uses a single ``check`` step so the loader's contract /
    writes / worktree validations all pass without needing prompts on disk.
    """
    body = (
        "name: demo\n"
        "version: 1\n"
        "description: demo workflow for CLI tests\n"
        + (inputs_block + "\n" if inputs_block else "")
        + "steps:\n"
        "  - id: ok\n"
        "    type: check\n"
        '    expr: "True"\n'
        "    on_fail: cancel\n"
    )
    tmp_path.joinpath("demo.yaml").write_text(body)
    return tmp_path / "demo.yaml"


class _RunnerSpy:
    """Drop-in for ``Runner`` that records the call and returns a configured exit code.

    Avoids spinning up SQLite / event emitter / executor for CLI-surface
    tests. AC5 / AC8 use this to assert the CLI hands the runner the
    right ``inputs`` / ``base_branch`` and propagates its exit code.
    """

    def __init__(self, exit_code: int = 0) -> None:
        self._exit_code = exit_code
        self.calls: list[dict[str, Any]] = []

    async def run(
        self,
        workflow_path: Path,
        inputs: dict[str, Any],
        *,
        base_branch: str = "main",
    ) -> int:
        self.calls.append(
            {
                "workflow_path": workflow_path,
                "inputs": dict(inputs),
                "base_branch": base_branch,
            }
        )
        return self._exit_code


@pytest.fixture
def runner_spy(monkeypatch: pytest.MonkeyPatch) -> _RunnerSpy:
    """Install a ``_RunnerSpy`` in place of the CLI's ``Runner`` factory.

    The CLI uses ``cli_module._build_runner()`` so tests can swap a spy in.
    """
    spy = _RunnerSpy(exit_code=0)
    monkeypatch.setattr(cli_module, "_build_runner", lambda: spy)
    return spy


@pytest.fixture
def cli() -> CliRunner:
    return CliRunner()


# ---------------------------------------------------------------------------
# AC1 — workflow YAML drives the subcommand surface
# ---------------------------------------------------------------------------


def test_ac1_run_with_unknown_workflow_exits_2(
    tmp_path: Path, cli: CliRunner
) -> None:
    """No ``demo.yaml`` exists → exit 2 + error mentioning workflow name."""
    result = cli.invoke(
        app,
        ["run", "demo", "--workflows-dir", str(tmp_path)],
    )
    assert result.exit_code == 2, result.output
    assert "demo" in result.output


def test_ac1_run_workflow_with_no_inputs_block_succeeds(
    tmp_path: Path, cli: CliRunner, runner_spy: _RunnerSpy
) -> None:
    """A workflow with no ``inputs:`` block has a valid subcommand;
    invoking it calls the runner with an empty inputs dict."""
    _minimal_workflow(tmp_path)
    result = cli.invoke(
        app, ["run", "demo", "--workflows-dir", str(tmp_path)]
    )
    assert result.exit_code == 0, result.output
    assert len(runner_spy.calls) == 1
    assert runner_spy.calls[0]["inputs"] == {}


# ---------------------------------------------------------------------------
# AC2 — input-spec → CLI parameter mapping
# ---------------------------------------------------------------------------


def test_ac2_string_flag_maps_to_string_option(
    tmp_path: Path, cli: CliRunner, runner_spy: _RunnerSpy
) -> None:
    """``type: string`` + explicit ``flag:`` maps to a typed string option."""
    _minimal_workflow(
        tmp_path,
        inputs_block=textwrap.dedent(
            """
            inputs:
              linear:
                type: string
                flag: --linear
                required: true
            """
        ).strip(),
    )
    result = cli.invoke(
        app,
        [
            "run",
            "demo",
            "--workflows-dir",
            str(tmp_path),
            "--linear",
            "CAL-249",
        ],
    )
    assert result.exit_code == 0, result.output
    assert runner_spy.calls[0]["inputs"] == {"linear": "CAL-249"}


def test_ac2_integer_flag_parses_int(
    tmp_path: Path, cli: CliRunner, runner_spy: _RunnerSpy
) -> None:
    _minimal_workflow(
        tmp_path,
        inputs_block=textwrap.dedent(
            """
            inputs:
              count:
                type: integer
                default: 5
                required: false
            """
        ).strip(),
    )
    result = cli.invoke(
        app,
        [
            "run",
            "demo",
            "--workflows-dir",
            str(tmp_path),
            "--count",
            "42",
        ],
    )
    assert result.exit_code == 0, result.output
    assert runner_spy.calls[0]["inputs"] == {"count": 42}


def test_ac2_boolean_input_is_a_bool_flag(
    tmp_path: Path, cli: CliRunner, runner_spy: _RunnerSpy
) -> None:
    """``type: boolean`` → presence-flag (no value needed)."""
    _minimal_workflow(
        tmp_path,
        inputs_block=textwrap.dedent(
            """
            inputs:
              dry_run:
                type: boolean
                default: false
                required: false
            """
        ).strip(),
    )
    result = cli.invoke(
        app,
        [
            "run",
            "demo",
            "--workflows-dir",
            str(tmp_path),
            "--dry-run",
        ],
    )
    assert result.exit_code == 0, result.output
    assert runner_spy.calls[0]["inputs"] == {"dry_run": True}


def test_ac2_default_flag_name_derived_from_input_name(
    tmp_path: Path, cli: CliRunner, runner_spy: _RunnerSpy
) -> None:
    """No explicit ``flag:`` → default ``--<name>`` with underscores → dashes."""
    _minimal_workflow(
        tmp_path,
        inputs_block=textwrap.dedent(
            """
            inputs:
              free_text:
                type: string
                required: true
            """
        ).strip(),
    )
    result = cli.invoke(
        app,
        [
            "run",
            "demo",
            "--workflows-dir",
            str(tmp_path),
            "--free-text",
            "hello",
        ],
    )
    assert result.exit_code == 0, result.output
    assert runner_spy.calls[0]["inputs"] == {"free_text": "hello"}


def test_ac2_position_makes_a_positional_argument(
    tmp_path: Path, cli: CliRunner, runner_spy: _RunnerSpy
) -> None:
    """``position: 1`` → Click ``Argument``, not an option."""
    _minimal_workflow(
        tmp_path,
        inputs_block=textwrap.dedent(
            """
            inputs:
              free_text:
                type: string
                position: 1
                required: false
            """
        ).strip(),
    )
    result = cli.invoke(
        app,
        [
            "run",
            "demo",
            "--workflows-dir",
            str(tmp_path),
            "Build a dropdown menu",
        ],
    )
    assert result.exit_code == 0, result.output
    assert runner_spy.calls[0]["inputs"] == {
        "free_text": "Build a dropdown menu"
    }


def test_ac2_required_flag_errors_when_omitted(
    tmp_path: Path, cli: CliRunner, runner_spy: _RunnerSpy
) -> None:
    """``required: true`` → CLI rejects invocation without the flag."""
    _minimal_workflow(
        tmp_path,
        inputs_block=textwrap.dedent(
            """
            inputs:
              linear:
                type: string
                required: true
            """
        ).strip(),
    )
    result = cli.invoke(
        app,
        ["run", "demo", "--workflows-dir", str(tmp_path)],
    )
    assert result.exit_code != 0, result.output
    assert "linear" in result.output.lower()
    assert runner_spy.calls == []


def test_ac2_default_value_is_honoured(
    tmp_path: Path, cli: CliRunner, runner_spy: _RunnerSpy
) -> None:
    _minimal_workflow(
        tmp_path,
        inputs_block=textwrap.dedent(
            """
            inputs:
              base:
                type: string
                default: staging
                required: false
                flag: --target
            """
        ).strip(),
    )
    result = cli.invoke(
        app,
        ["run", "demo", "--workflows-dir", str(tmp_path)],
    )
    assert result.exit_code == 0, result.output
    assert runner_spy.calls[0]["inputs"] == {"base": "staging"}


def test_ac2_enum_rejects_disallowed_value(
    tmp_path: Path, cli: CliRunner, runner_spy: _RunnerSpy
) -> None:
    _minimal_workflow(
        tmp_path,
        inputs_block=textwrap.dedent(
            """
            inputs:
              domain:
                type: string
                enum: [architecture, harness]
                required: true
            """
        ).strip(),
    )
    bad = cli.invoke(
        app,
        [
            "run",
            "demo",
            "--workflows-dir",
            str(tmp_path),
            "--domain",
            "nonsense",
        ],
    )
    assert bad.exit_code != 0
    good = cli.invoke(
        app,
        [
            "run",
            "demo",
            "--workflows-dir",
            str(tmp_path),
            "--domain",
            "architecture",
        ],
    )
    assert good.exit_code == 0, good.output
    assert runner_spy.calls[0]["inputs"] == {"domain": "architecture"}


def test_ac2_pattern_mismatch_exits_2(
    tmp_path: Path, cli: CliRunner, runner_spy: _RunnerSpy
) -> None:
    """``pattern:`` is enforced after click parsing via ``re.fullmatch``.

    A mismatch must exit with code 2 (invocation error per SPEC §11),
    not the runner's 0 / 1 / 3 / 130 codes.
    """
    _minimal_workflow(
        tmp_path,
        inputs_block=textwrap.dedent(
            """
            inputs:
              linear:
                type: string
                pattern: "^[A-Z]+-[0-9]+$"
                required: true
            """
        ).strip(),
    )
    result = cli.invoke(
        app,
        [
            "run",
            "demo",
            "--workflows-dir",
            str(tmp_path),
            "--linear",
            "not-a-ticket",
        ],
    )
    assert result.exit_code == 2, result.output
    assert "pattern" in result.output.lower()
    assert runner_spy.calls == []


def test_ac2_pattern_match_allows_invocation(
    tmp_path: Path, cli: CliRunner, runner_spy: _RunnerSpy
) -> None:
    _minimal_workflow(
        tmp_path,
        inputs_block=textwrap.dedent(
            """
            inputs:
              linear:
                type: string
                pattern: "^[A-Z]+-[0-9]+$"
                required: true
            """
        ).strip(),
    )
    result = cli.invoke(
        app,
        [
            "run",
            "demo",
            "--workflows-dir",
            str(tmp_path),
            "--linear",
            "CAL-249",
        ],
    )
    assert result.exit_code == 0, result.output
    assert runner_spy.calls[0]["inputs"] == {"linear": "CAL-249"}


# ---------------------------------------------------------------------------
# AC3 — --help prints the workflow's input contract
# ---------------------------------------------------------------------------


def test_ac3_help_lists_inputs_with_types_and_defaults(
    tmp_path: Path, cli: CliRunner
) -> None:
    _minimal_workflow(
        tmp_path,
        inputs_block=textwrap.dedent(
            """
            inputs:
              linear:
                type: string
                required: true
                flag: --linear
              count:
                type: integer
                default: 5
                required: false
              free_text:
                type: string
                position: 1
                required: false
            """
        ).strip(),
    )
    result = cli.invoke(
        app,
        [
            "run",
            "demo",
            "--workflows-dir",
            str(tmp_path),
            "--help",
        ],
    )
    assert result.exit_code == 0, result.output
    # Names appear
    assert "--linear" in result.output
    assert "--count" in result.output
    # Positional appears, free_text uppercased per click convention
    assert re.search(r"\bFREE_TEXT\b|free_text", result.output)
    # Default is surfaced for --count
    assert "5" in result.output


# ---------------------------------------------------------------------------
# AC4 / AC8 — --base option with default 'main'
# ---------------------------------------------------------------------------


def test_ac4_base_flag_defaults_to_main(
    tmp_path: Path, cli: CliRunner, runner_spy: _RunnerSpy
) -> None:
    _minimal_workflow(tmp_path)
    result = cli.invoke(
        app, ["run", "demo", "--workflows-dir", str(tmp_path)]
    )
    assert result.exit_code == 0, result.output
    assert runner_spy.calls[0]["base_branch"] == "main"


def test_ac4_base_flag_overridable(
    tmp_path: Path, cli: CliRunner, runner_spy: _RunnerSpy
) -> None:
    _minimal_workflow(tmp_path)
    result = cli.invoke(
        app,
        [
            "run",
            "demo",
            "--workflows-dir",
            str(tmp_path),
            "--base",
            "staging",
        ],
    )
    assert result.exit_code == 0, result.output
    assert runner_spy.calls[0]["base_branch"] == "staging"


def test_ac4_base_flag_does_not_collide_with_workflow_inputs(
    tmp_path: Path, cli: CliRunner, runner_spy: _RunnerSpy
) -> None:
    """A workflow that declares its own input named ``other`` still
    gets the stable ``--base`` flag separately."""
    _minimal_workflow(
        tmp_path,
        inputs_block=textwrap.dedent(
            """
            inputs:
              other:
                type: string
                default: ""
                required: false
            """
        ).strip(),
    )
    result = cli.invoke(
        app,
        [
            "run",
            "demo",
            "--workflows-dir",
            str(tmp_path),
            "--other",
            "hi",
            "--base",
            "staging",
        ],
    )
    assert result.exit_code == 0, result.output
    assert runner_spy.calls[0]["base_branch"] == "staging"
    assert runner_spy.calls[0]["inputs"] == {"other": "hi"}


# ---------------------------------------------------------------------------
# AC5 / AC9 — invokes Runner.run via asyncio.run; propagates exit code
# ---------------------------------------------------------------------------


def test_ac5_propagates_runner_exit_code(
    tmp_path: Path,
    cli: CliRunner,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The CLI returns whatever ``Runner.run`` returned (here: 3)."""
    _minimal_workflow(tmp_path)
    spy = _RunnerSpy(exit_code=3)
    monkeypatch.setattr(cli_module, "_build_runner", lambda: spy)

    result = cli.invoke(
        app, ["run", "demo", "--workflows-dir", str(tmp_path)]
    )
    assert result.exit_code == 3, result.output
    assert len(spy.calls) == 1


def test_ac9_runner_invoked_via_asyncio_run(
    tmp_path: Path,
    cli: CliRunner,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """asyncio.run is the boundary — verify the CLI uses it (not raw await
    in a sync context, which would be a bug). We assert by monkeypatching
    asyncio.run and confirming it was called with our runner's coroutine.
    """
    _minimal_workflow(tmp_path)
    spy = _RunnerSpy(exit_code=0)
    monkeypatch.setattr(cli_module, "_build_runner", lambda: spy)

    calls: list[Any] = []
    import asyncio as _asyncio

    real_run = _asyncio.run

    def tracking_run(coro: Any, *args: Any, **kw: Any) -> Any:
        calls.append(coro)
        return real_run(coro, *args, **kw)

    monkeypatch.setattr(cli_module.asyncio, "run", tracking_run)

    result = cli.invoke(
        app, ["run", "demo", "--workflows-dir", str(tmp_path)]
    )
    assert result.exit_code == 0, result.output
    assert len(calls) == 1


# ---------------------------------------------------------------------------
# AC6 — unknown workflow → exit 2
# ---------------------------------------------------------------------------


def test_ac6_unknown_workflow_clear_error(
    tmp_path: Path, cli: CliRunner
) -> None:
    """File doesn't exist → exit 2 + message names the missing workflow."""
    result = cli.invoke(
        app, ["run", "missing", "--workflows-dir", str(tmp_path)]
    )
    assert result.exit_code == 2
    assert "missing" in result.output


# ---------------------------------------------------------------------------
# AC7 — invalid workflow YAML → exit 2
# ---------------------------------------------------------------------------


def test_ac7_invalid_workflow_yaml_exits_2(
    tmp_path: Path, cli: CliRunner
) -> None:
    """Workflow file exists but fails validation → exit 2 + underlying msg.
    Here we omit ``steps:`` so the loader's schema check fails."""
    _write_workflow(
        tmp_path / "bad.yaml",
        """
        name: bad
        version: 1
        # No steps — Workflow requires min_length=1
        """,
    )
    result = cli.invoke(
        app, ["run", "bad", "--workflows-dir", str(tmp_path)]
    )
    assert result.exit_code == 2, result.output
    # The output should carry some hint of the underlying validation
    # failure — the loader surfaces a WorkflowLoadError with the cause.
    assert "bad" in result.output.lower() or "steps" in result.output.lower()


# ---------------------------------------------------------------------------
# Existing CLI surface — preserved
# ---------------------------------------------------------------------------


def test_existing_version_command_still_runs(cli: CliRunner) -> None:
    """Regression: the ``version`` command still works."""
    result = cli.invoke(app, ["version"])
    assert result.exit_code == 0
    assert "calibrate-harness" in result.output
