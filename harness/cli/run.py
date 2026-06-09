"""``harness run <workflow>`` — dynamic subcommand generation (SPEC §11).

Per-workflow subcommand generation: at invocation, the CLI loads
``workflows/<workflow>.yaml``, reads its ``inputs:`` block, and dynamically
generates the appropriate Click parameters on the fly. Adding a new workflow
means writing YAML, not editing CLI code.

The outer ``run`` Typer command is a thin wrapper that locates the workflow
file, hands off to a Click command built from the workflow's inputs, and
propagates the runner's exit code per SPEC §11.
"""

from __future__ import annotations

import asyncio
import re
from pathlib import Path
from typing import Any

import click
import typer

from harness.cli._workflows import _resolve_workflows_dir
from harness.engine.runner import Runner
from harness.workflow.loader import WorkflowLoadError, load_workflow
from harness.workflow.schema import InputSpec

__all__ = ["run_command"]

# Re-exported so existing importers (e.g. tests) can still reach the function
# via ``harness.cli.run._resolve_workflows_dir``.
__all__ += ["_resolve_workflows_dir"]


# Internal kwarg name for the reserved ``--base`` flag. Namespaced so a
# workflow input also called ``base`` (or wired to the ``--base`` flag)
# cannot clobber the runner's ``base_branch`` argument. Click derives the
# kwarg name from the second non-dashed entry in a parameter's decl list,
# so this string lands as the dict key for ``--base``.
_BASE_BRANCH_KW = "_base_branch__"
_REPO_ROOT_KW = "_repo_root__"


def _build_runner(*, quiet: bool = False, repo_root: Path | None = None) -> Runner:
    """Construct the default :class:`Runner`.

    Lives at module scope so tests can monkeypatch it with a spy that
    captures the runner's arguments without spinning up SQLite + the
    executor + agent dispatch.

    Args:
        quiet: When ``True``, suppress progress output to stderr.
        repo_root: When provided, passed to Runner as the filesystem root
            for git worktree operations.
    """
    from harness.dispatch.claude import ClaudeAgent

    kwargs: dict[str, Any] = {"agent": ClaudeAgent(), "progress": not quiet}
    if repo_root is not None:
        kwargs["repo_root"] = repo_root
    return Runner(**kwargs)


def run_command(
    ctx: typer.Context,
    workflow: str = typer.Argument(
        ..., help="Workflow name (e.g. ``feature``) — resolves to ``workflows/<name>.yaml``."
    ),
    workflows_dir: Path | None = typer.Option(  # noqa: B008 — Typer pattern.
        None,
        "--workflows-dir",
        help=(
            "Directory containing workflow YAML files. "
            "Falls back to $HARNESS_WORKFLOWS_DIR, then ./workflows, "
            "then bundled package data."
        ),
    ),
    quiet: bool = typer.Option(  # noqa: B008 — Typer pattern.
        False,
        "--quiet",
        help="Suppress per-node progress output to stderr.",
    ),
) -> None:
    """Execute a workflow. Per-workflow flags are loaded from its YAML.

    Run ``harness run <workflow> --help`` to see the workflow's specific
    inputs.
    """
    resolved_dir = _resolve_workflows_dir(workflows_dir)
    workflow_path = resolved_dir / f"{workflow}.yaml"
    if not workflow_path.is_file():
        typer.echo(
            f"error: workflow {workflow!r} not found at {workflow_path}",
            err=True,
        )
        raise typer.Exit(code=2)

    try:
        loaded = load_workflow(workflow_path)
    except WorkflowLoadError as exc:
        typer.echo(f"error: workflow {workflow!r} failed to load: {exc}", err=True)
        raise typer.Exit(code=2) from None

    dynamic_command = _build_dynamic_command(
        workflow_name=workflow,
        workflow_path=workflow_path,
        inputs_spec=dict(loaded.workflow.inputs),
        description=loaded.workflow.description or None,
        quiet=quiet,
    )

    try:
        result = dynamic_command.main(
            args=list(ctx.args),
            prog_name=f"harness run {workflow}",
            standalone_mode=False,
        )
    except click.exceptions.UsageError as exc:
        exc.show()
        raise typer.Exit(code=2) from None
    except click.exceptions.ClickException as exc:
        exc.show()
        raise typer.Exit(code=2) from None

    exit_code = int(result) if isinstance(result, int) else 0
    raise typer.Exit(code=exit_code)


# ---------------------------------------------------------------------------
# Internals — building the per-workflow click.Command
# ---------------------------------------------------------------------------


_PYTHON_TYPE_FOR: dict[str, type] = {
    "string": str,
    "integer": int,
    "boolean": bool,
}


def _build_dynamic_command(
    *,
    workflow_name: str,
    workflow_path: Path,
    inputs_spec: dict[str, InputSpec],
    description: str | None,
    quiet: bool = False,
) -> click.Command:
    """Compile the workflow's ``inputs:`` block into a ``click.Command``.

    The command's callback validates ``pattern:`` constraints, builds the
    inputs dict, then drives :meth:`Runner.run` via :func:`asyncio.run`.
    Returns a Click command whose ``main()`` is invoked by the outer
    Typer ``run`` command.
    """
    params: list[click.Parameter] = []
    pattern_checks: dict[str, str] = {}

    positional_inputs = sorted(
        ((name, spec) for name, spec in inputs_spec.items() if spec.position is not None),
        key=lambda kv: kv[1].position or 0,
    )
    flag_inputs = [
        (name, spec) for name, spec in inputs_spec.items() if spec.position is None
    ]

    for name, spec in flag_inputs:
        params.append(_input_to_option(name, spec))
        if spec.pattern is not None:
            pattern_checks[name] = spec.pattern

    for name, spec in positional_inputs:
        params.append(_input_to_argument(name, spec))
        if spec.pattern is not None:
            pattern_checks[name] = spec.pattern

    # Reserved --base flag, exposed on every dynamic subcommand. Maps to
    # Runner.run(base_branch=...). The kwarg name is namespaced so a
    # workflow input bound to ``--base`` cannot clobber it.
    params.append(
        click.Option(
            ["--base", _BASE_BRANCH_KW],
            type=str,
            default="dev",
            show_default=True,
            help="Base branch the run is started against (passed to Runner.run).",
        )
    )

    # Reserved --repo flag. When provided, sets repo_root on the Runner so
    # worktree operations target the given directory instead of CWD.
    params.append(
        click.Option(
            ["--repo", _REPO_ROOT_KW],
            type=click.Path(path_type=Path),
            default=None,
            help="Filesystem root for git worktree operations. Defaults to the current directory.",
        )
    )

    def callback(**kw: Any) -> int:
        base_branch: str = kw.pop(_BASE_BRANCH_KW)
        repo_root: Path | None = kw.pop(_REPO_ROOT_KW)
        for input_name, pattern in pattern_checks.items():
            value = kw.get(input_name)
            if value is None:
                continue
            if not re.fullmatch(pattern, str(value)):
                click.echo(
                    f"error: input {input_name!r} value {value!r} does not "
                    f"match pattern {pattern!r}",
                    err=True,
                )
                return 2

        inputs: dict[str, Any] = {k: v for k, v in kw.items() if v is not None}

        runner = _build_runner(quiet=quiet, repo_root=repo_root)
        exit_code = asyncio.run(
            runner.run(workflow_path, inputs, base_branch=base_branch)
        )
        return int(exit_code)

    help_text = description or f"Execute the {workflow_name!r} workflow."
    return click.Command(
        name=workflow_name,
        params=params,
        callback=callback,
        help=help_text,
    )


def _input_to_option(name: str, spec: InputSpec) -> click.Option:
    """Convert a flag-style :class:`InputSpec` to a ``click.Option``.

    The Click option name (the kwarg the callback receives) is derived
    from the primary flag — passing ``[flag]`` alone lets Click compute
    the kwarg name; for a flag like ``--free-text`` Click derives
    ``free_text``, which matches the input name. For inputs whose
    ``flag:`` is something exotic (e.g. ``--linear`` for ``linear_id``),
    we list the kwarg-name as a *secondary* identifier so Click writes
    the option's value into the callback under the input name.

    Avoids passing ``default=None`` explicitly: Click's required-check
    treats an explicit ``None`` default as "the user has a fallback" and
    silently skips the missing-required validation. Omitting the kwarg
    lets the field default to ``UNSET`` so missing-required raises.
    """
    flag = spec.flag if spec.flag is not None else f"--{name.replace('_', '-')}"

    derived = flag.lstrip("-").replace("-", "_")
    decls: list[str] = [flag] if derived == name else [flag, name]

    required = spec.required and spec.default is None
    has_default = spec.default is not None

    if spec.type == "boolean":
        kwargs: dict[str, Any] = {
            "is_flag": True,
            "default": bool(spec.default) if has_default else False,
            "help": _help_for(spec),
        }
        if required:
            kwargs["required"] = True
        return click.Option(decls, **kwargs)

    click_type: Any = _PYTHON_TYPE_FOR[spec.type]
    if spec.enum is not None:
        click_type = click.Choice([str(v) for v in spec.enum])

    kwargs = {
        "type": click_type,
        "help": _help_for(spec),
    }
    if has_default:
        kwargs["default"] = spec.default
        kwargs["show_default"] = True
    if required:
        kwargs["required"] = True
    return click.Option(decls, **kwargs)


def _input_to_argument(name: str, spec: InputSpec) -> click.Argument:
    """Convert a positional :class:`InputSpec` to a ``click.Argument``.

    Same ``default=None``-vs-UNSET subtlety as :func:`_input_to_option`:
    only pass ``default`` when there's a real value, so Click's
    required-check actually fires on missing-required arguments.
    """
    if spec.type == "boolean":
        raise WorkflowLoadError(
            f"input {name!r}: boolean type cannot be a positional argument"
        )

    click_type: Any = _PYTHON_TYPE_FOR[spec.type]
    if spec.enum is not None:
        click_type = click.Choice([str(v) for v in spec.enum])

    kwargs: dict[str, Any] = {"type": click_type}
    if spec.default is not None:
        kwargs["default"] = spec.default
    if spec.required and spec.default is None:
        kwargs["required"] = True
    else:
        kwargs["required"] = False
    return click.Argument([name], **kwargs)


def _help_for(spec: InputSpec) -> str:
    """Build a one-line help string surfacing type + required/optional."""
    bits = [f"type: {spec.type}"]
    if spec.required and spec.default is None:
        bits.append("required")
    else:
        bits.append("optional")
    if spec.enum is not None:
        bits.append(f"choices: {spec.enum}")
    if spec.pattern is not None:
        bits.append(f"pattern: {spec.pattern}")
    return " | ".join(bits)
