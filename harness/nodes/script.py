"""Script node — subprocess wrapper for bash/python — see SPEC §4.3, §5.

This node runs a shell or python subprocess on behalf of a workflow step,
captures stdout / stderr / exit_code, and returns them inside a typed
:class:`ScriptOutput` contract. Non-zero exit codes raise
:class:`ScriptNodeError`; the node fails fast rather than producing a
NodeResult that downstream steps would have to interpret.

Variable substitution: ``args`` entries that match ``$state.<field>`` or
``$inputs.<key>`` are replaced literally with the referenced value
coerced to ``str``. Missing references raise — silent empty-string
substitution would mask workflow-authoring bugs.

Out of scope (deferred):

* Configurable ``on_fail`` (mirror CheckNode) — the v1 contract is
  "non-zero exit means the node failed".
* Streaming stdout/stderr to the event log — v1 captures only.
* Contract enforcement against the YAML ``contract:`` block — that is
  the executor's (H-007) job. ScriptNode produces a fixed
  ``ScriptOutput`` shape; the executor validates whatever subset of it
  the workflow declared.

SPEC: §4.3 (Node protocol), §5 ("script" rows / "Variable substitution").
"""

from __future__ import annotations

import asyncio
import contextlib
import shutil
import sys
from pathlib import Path
from typing import Any, Final, Literal

from pydantic import BaseModel, ConfigDict

from harness.nodes.base import Attestation, NodeResult
from harness.state.schema import BaseState
from harness.workflow.schema import ScriptStep

__all__ = [
    "ScriptNode",
    "ScriptNodeError",
    "ScriptOutput",
]


# Default cap on captured stdout/stderr per stream. A subprocess that emits
# gigabytes shouldn't blow up the harness; we keep the head and append a
# truncation marker so the boundary is human-visible.
DEFAULT_MAX_OUTPUT_BYTES: Final[int] = 1024 * 1024  # 1 MiB

# Default wall-clock timeout in seconds. Mirrors AINode's ``timeout_s`` default
# magnitude (600s); kept smaller here because shell scripts are typically
# shorter-lived than agent calls.
DEFAULT_TIMEOUT_S: Final[float] = 300.0

_TRUNCATION_MARKER: Final[str] = "\n…[truncated]"


class ScriptNodeError(RuntimeError):  # noqa: N818 — spec vocabulary, not PEP-8 N818
    """Raised when a script subprocess fails, times out, or is misconfigured."""


class ScriptOutput(BaseModel):
    """Contract for a script step.

    The three fields are the universal subprocess outcome shape; downstream
    nodes can reference any of them via ``writes:``. The executor (H-007)
    is responsible for validating whatever subset of these the workflow's
    declared ``contract:`` actually exposes — ScriptNode always populates
    all three.
    """

    model_config = ConfigDict(extra="forbid")

    stdout: str
    stderr: str
    exit_code: int


class ScriptNode:
    """v1 script node: substitute → dispatch subprocess → capture → return.

    Conforms structurally to :class:`harness.nodes.base.Node`. The class is
    stateless apart from its two configured caps (``max_output_bytes``,
    ``timeout_s``); the executor (H-007) constructs one ScriptNode per
    workflow run and reuses it across every script step.
    """

    type: Literal["script"] = "script"

    def __init__(
        self,
        *,
        max_output_bytes: int = DEFAULT_MAX_OUTPUT_BYTES,
        timeout_s: float = DEFAULT_TIMEOUT_S,
    ) -> None:
        if max_output_bytes <= 0:
            raise ValueError("max_output_bytes must be positive")
        if timeout_s <= 0:
            raise ValueError("timeout_s must be positive")
        self._max_output_bytes = max_output_bytes
        self._timeout_s = timeout_s

    async def execute(
        self,
        *,
        step: ScriptStep,
        state: BaseState,
        inputs: dict[str, Any] | None = None,
    ) -> NodeResult[ScriptOutput]:
        """Run the script step and return its captured output.

        Raises:
            ScriptNodeError: on non-zero exit, timeout, or missing
                ``$state.X`` / ``$inputs.X`` reference in ``args``.
        """
        inputs = inputs or {}
        resolved_args = [
            self._substitute(arg, state=state, inputs=inputs) for arg in step.args
        ]
        argv = self._build_argv(step, resolved_args)
        cwd = self._resolve_cwd(step, state)

        stdout, stderr, exit_code = await self._run(argv, cwd=cwd)

        if exit_code != 0:
            raise ScriptNodeError(
                f"script step {step.id!r}: exit code {exit_code}; "
                f"stderr: {stderr.strip()[:500]}"
            )

        return NodeResult(
            contract=ScriptOutput(
                stdout=stdout,
                stderr=stderr,
                exit_code=exit_code,
            ),
            attestation=Attestation(
                status="complete",
                reasoning=f"script step {step.id!r} exited 0",
            ),
        )

    # ---- internals ------------------------------------------------------- #

    @staticmethod
    def _substitute(arg: str, *, state: BaseState, inputs: dict[str, Any]) -> str:
        """Replace ``$state.<field>`` / ``$inputs.<key>`` with str(value).

        Top-level dotted access only — no nested attribute walking. Missing
        references raise so workflow-authoring bugs surface immediately
        rather than silently substituting empty string (SPEC §5).
        """
        if arg.startswith("$state."):
            field = arg[len("$state.") :]
            if not field:
                raise ScriptNodeError(f"empty $state. reference in args: {arg!r}")
            try:
                value = getattr(state, field)
            except AttributeError as e:
                raise ScriptNodeError(
                    f"unknown state field in args: {arg!r} — "
                    f"state has no attribute {field!r}"
                ) from e
            return str(value)
        if arg.startswith("$inputs."):
            key = arg[len("$inputs.") :]
            if not key:
                raise ScriptNodeError(f"empty $inputs. reference in args: {arg!r}")
            if key not in inputs:
                raise ScriptNodeError(
                    f"unknown inputs key in args: {arg!r} — "
                    f"inputs has no key {key!r}"
                )
            return str(inputs[key])
        return arg

    def _build_argv(self, step: ScriptStep, args: list[str]) -> list[str]:
        """Construct the ``argv`` list to pass to ``create_subprocess_exec``.

        The schema validator already enforces ``command XOR script``, so we
        just branch on which is set.
        """
        if step.runtime == "bash":
            if step.command is not None:
                # ``bash -c <cmd> <name> $1 $2 ...`` — the first positional
                # after ``-c`` is ``$0``; we pass "harness-script" so the
                # author's positionals start at ``$1`` as they expect.
                return ["bash", "-c", step.command, "harness-script", *args]
            assert step.script is not None  # ScriptStep validator guarantees this
            return ["bash", step.script, *args]

        # runtime == "python"
        py = self._python_executable()
        if step.command is not None:
            return [py, "-c", step.command, *args]
        assert step.script is not None
        return [py, step.script, *args]

    @staticmethod
    def _python_executable() -> str:
        """Prefer the project's .venv python, else sys.executable, else PATH."""
        venv_python = Path(".venv") / "bin" / "python"
        if venv_python.is_file():
            return str(venv_python)
        # Prefer the current interpreter to avoid surprising version drift
        # between the test harness and the subprocess.
        return sys.executable or shutil.which("python") or "python"

    @staticmethod
    def _resolve_cwd(step: ScriptStep, state: BaseState) -> Path | None:
        """``step.cwd`` (treated as Path) wins; else state.worktree_path; else None."""
        if step.cwd is not None:
            return Path(step.cwd)
        if state.worktree_path is not None:
            return state.worktree_path
        return None

    async def _run(
        self,
        argv: list[str],
        *,
        cwd: Path | None,
    ) -> tuple[str, str, int]:
        """Spawn the subprocess and return ``(stdout, stderr, exit_code)``.

        Wraps :func:`asyncio.subprocess.Process.communicate` in
        :func:`asyncio.wait_for` for the timeout. On timeout we kill the
        child before raising so a runaway sleep doesn't outlive the run.
        """
        proc = await asyncio.create_subprocess_exec(
            *argv,
            cwd=str(cwd) if cwd is not None else None,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                proc.communicate(), timeout=self._timeout_s
            )
        except TimeoutError as e:
            # Best-effort kill. ProcessLookupError on a race — already dead.
            with contextlib.suppress(ProcessLookupError):
                proc.kill()
            await proc.wait()
            raise ScriptNodeError(
                f"script timed out after {self._timeout_s}s: argv={argv!r}"
            ) from e

        return (
            self._truncate(stdout_bytes.decode(errors="replace")),
            self._truncate(stderr_bytes.decode(errors="replace")),
            proc.returncode if proc.returncode is not None else -1,
        )

    def _truncate(self, text: str) -> str:
        """Cap the captured stream at ``max_output_bytes`` of UTF-8.

        Measuring on the encoded form so the cap matches the on-the-wire
        size; truncating on character count gives the wrong answer for
        non-ASCII output. The marker is appended verbatim so the boundary
        is human-visible.
        """
        encoded = text.encode("utf-8", errors="replace")
        if len(encoded) <= self._max_output_bytes:
            return text
        head = encoded[: self._max_output_bytes].decode("utf-8", errors="replace")
        return head + _TRUNCATION_MARKER
