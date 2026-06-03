"""Loop block evaluator — see SPEC §10 "Loop blocks".

A :class:`LoopStep` (workflow-schema type) carries a :class:`LoopBlock`
with ``max_iterations``, ``until``, ``fresh_context``, and a child
``steps`` list. The :class:`LoopExecutor` iterates the child steps
in declared order, evaluating ``until:`` (or ``until_bash:``) against
the run's state at the end of each iteration. The loop exits cleanly
when the satisfaction predicate is true; when ``max_iterations`` is
reached without satisfying it, the executor raises
:class:`LoopExhausted` — the runner translates that into a
``workflow_failed`` event with exit code 1 (SPEC §11).

Design choices worth flagging:

* **State propagation is automatic.** Each child step is dispatched via
  the shared :class:`harness.engine.executor.Executor`, which writes the
  step's declared ``writes:`` through :func:`harness.state.store.update_state`.
  The next iteration reads the merged state when its own executor.execute()
  call lands. No bespoke state plumbing.

* **fresh_context=True calls ``agent.reset()`` between iterations.**
  Not before iteration 1 (the agent is in its initial state already).
  Implementations that don't carry session state implement ``reset()``
  as a no-op — see :mod:`harness.dispatch.mock`.

* **Iteration numbering is 1-based.** The SPEC doesn't pin this; we
  pick 1-based because "iteration 1 of 5" reads naturally in logs and
  failure messages. The ``loop_iteration`` event's ``data.iteration``
  is the same 1-based counter.

* **``until:`` semantics differ from CheckNode.** CheckNode rejects
  non-bool results to keep authoring tight; the loop evaluator *coerces*
  with :func:`bool`. A state field that's ``None`` until written (the
  common starting state for a derived scalar) reads naturally as "not
  yet satisfied" without forcing every workflow to default-init its
  signal field. The sandbox / AST allow-list is identical — the only
  difference is the result coercion. See :mod:`harness.nodes._state_expr`.

* **``until_bash:`` runs after the iteration's child steps.** It is
  exec'd via ``asyncio.create_subprocess_exec(["bash", "-c", cmd])`` —
  list-form at the Python boundary (no ``shell=True``), but ``bash -c``
  itself still parses ``cmd``. ``$state.<field>`` / ``$inputs.<key>``
  references are substituted *as strings* into the command before exec,
  so workflow authors should not reference state fields that might
  contain untrusted shell metacharacters. The v1 threat model treats
  the workflow author as the trust boundary; per-token quoting is left
  to the author. Missing references raise (silent empty-string would
  mask authoring bugs). Exit 0 means satisfied; any non-zero exit means
  not-yet-satisfied. A :data:`_UNTIL_BASH_TIMEOUT_S` cap keeps a hung
  command from stalling the loop forever — a timeout is treated as
  "not satisfied" and the ``loop_iteration`` event carries
  ``data.until_bash_timeout=True`` so the boundary is visible.
  Combined ``until + until_bash`` is rejected with :class:`ValueError`
  because the resolution semantics are ambiguous; pick one.

* **``retry_loop:<id>`` rewinds to the named loop.** A child check
  whose ``on_fail`` field starts with ``retry_loop:`` raises
  :class:`RetryLoopRequested` from the runner's check adapter. The
  enclosing :class:`LoopExecutor` catches the exception, and:

  - if the requested ``loop_id`` matches this loop's ``step.id``, it
    breaks out of the children loop, emits a ``loop_iteration`` event
    with ``data.trigger="retry_loop_requested"``, and starts the next
    iteration (counting against the same ``max_iterations`` budget — no
    separate retry budget).
  - if it doesn't match, the exception re-raises so an outer loop
    (or the runner's generic failure handler) can resolve it. A
    ``retry_loop:<id>`` referencing a loop that is not on the active
    stack therefore surfaces as a workflow failure naming the offending
    id — sufficient for v1; nested-loop jumps are documented in
    :class:`RetryLoopRequested`.

* **Child errors propagate immediately.** The child step's retry budget
  has already been exhausted by the Executor; the LoopExecutor does not
  layer additional retries. The first raise short-circuits the loop and
  surfaces to the runner — except for :class:`RetryLoopRequested`,
  which is the engine's signalling mechanism rather than a real error.

SPEC: §5 (loop step keys), §10 (loop blocks).
"""

from __future__ import annotations

import asyncio
import contextlib
import re
from typing import Any, Final

from harness.dispatch.base import Agent, ResettableAgent
from harness.engine.executor import Context, Executor
from harness.events.emitter import EventEmitter
from harness.nodes._state_expr import parse_and_eval
from harness.state.schema import BaseState
from harness.state.store import read_state
from harness.workflow.schema import LoopStep

__all__ = ["LoopExecutor", "LoopExhausted", "RetryLoopRequested"]


# Wall-clock cap on a single ``until_bash:`` invocation. A run that
# stalls inside a network poll or a flaky external dependency shouldn't
# silently block the loop forever; we treat a timeout as "not satisfied"
# and surface it on the iteration event for visibility.
_UNTIL_BASH_TIMEOUT_S: Final[float] = 300.0

# Regex for ``$state.<field>`` / ``$inputs.<key>`` substitution inside
# the ``until_bash:`` command string. Mirrors the script-node token
# vocabulary (``harness/nodes/script.py``); the difference is that
# script-node args are whole tokens while ``until_bash`` is one command
# line and must accept embedded references.
_TEMPLATE_REF_RE: Final[re.Pattern[str]] = re.compile(
    r"\$(state|inputs)\.([A-Za-z_][A-Za-z0-9_]*)"
)


class LoopExhausted(Exception):  # noqa: N818 — engine vocabulary (cf. CheckFailed)
    """A loop block ran ``max_iterations`` without ``until:`` becoming true.

    The runner's generic terminal-failure handler maps this to exit
    code 1 and a ``workflow_failed`` event whose ``reason`` is the
    class name. The class name (``"LoopExhausted"``) is the
    identifiable marker downstream consumers grep for; the message
    additionally carries the loop step id and the iteration count.
    """


class RetryLoopRequested(Exception):  # noqa: N818 — engine signalling vocabulary
    """A check step requested another iteration of a named loop.

    Raised by the runner's check adapter when a check evaluates False
    and its ``on_fail`` is ``retry_loop:<loop-id>``. The closest enclosing
    :class:`LoopExecutor` catches the exception:

    * If ``loop_id`` matches the loop's ``step.id``, the executor breaks
      out of the children-of-this-iteration loop and starts the next
      iteration (counting against the same ``max_iterations`` budget).
    * Otherwise it re-raises, letting an outer loop catch it. If no
      enclosing loop matches, the runner's generic failure handler
      surfaces the exception as a workflow failure naming the offending
      id.

    The class is not a programming error; it is the engine's signalling
    mechanism. Callers should treat it like ``StopIteration``: produced
    by check_adapter, consumed by LoopExecutor.
    """

    def __init__(self, loop_id: str, *, requested_by: str) -> None:
        super().__init__(
            f"retry_loop:{loop_id} requested by check {requested_by!r}"
        )
        self.loop_id = loop_id
        self.requested_by = requested_by


class LoopExecutor:
    """Iterates a :class:`LoopStep`'s child steps until satisfaction or exhaustion.

    Constructed once per workflow run; the runner reuses the shared
    :class:`Executor`, :class:`Agent`, and :class:`EventEmitter` so the
    loop's children get the same retry policy, dispatch wiring, and
    event log as top-level steps.
    """

    def __init__(
        self,
        *,
        executor: Executor,
        agent: Agent,
        emitter: EventEmitter,
    ) -> None:
        self._executor = executor
        self._agent = agent
        self._emitter = emitter

    async def execute(self, step: LoopStep, ctx: Context) -> None:
        """Run the loop until its satisfaction predicate or ``max_iterations``.

        Args:
            step: The :class:`LoopStep` carrying the :class:`LoopBlock`.
            ctx: The same :class:`Context` the runner builds for top-level
                steps — shared registry, contracts, db, schema.

        Raises:
            LoopExhausted: ``max_iterations`` elapsed without the
                satisfaction predicate becoming true.
            ValueError: the loop declares both ``until:`` and
                ``until_bash:`` — the resolution semantics are
                ambiguous; pick one.
            Any exception a child step raises after retry exhaustion.
        """
        loop = step.loop
        self._reject_combined_until_fields(step)

        for iteration in range(1, loop.max_iterations + 1):
            # SPEC §10 fresh_context: reset *between* iterations, not
            # before iteration 1 (the agent is already in its initial
            # state at that point). We probe with isinstance() against
            # the optional :class:`ResettableAgent` protocol so adapters
            # that don't carry session state (the in-process MockAgent
            # for tests) need no special handling.
            if (
                loop.fresh_context
                and iteration > 1
                and isinstance(self._agent, ResettableAgent)
            ):
                self._agent.reset()

            # Run each child step end-to-end via the shared Executor.
            # The executor handles node_started/completed, retries,
            # contract validation, state writes — we don't re-implement
            # any of that here.
            try:
                for child in loop.steps:
                    await self._executor.execute(child, ctx)
            except RetryLoopRequested as exc:
                if exc.loop_id != step.id:
                    # Cross-loop request — let an outer loop catch it,
                    # or let the runner's generic handler surface it.
                    raise
                # Matching loop: skip the until-evaluation, log the
                # retry trigger, and start the next iteration. Counts
                # against ``max_iterations``.
                await self._emitter.emit(
                    run_id=ctx.run_id,
                    event_type="loop_iteration",
                    node_id=step.id,
                    data={
                        "iteration": iteration,
                        "max_iterations": loop.max_iterations,
                        "until_satisfied": False,
                        "trigger": "retry_loop_requested",
                        "requested_by": exc.requested_by,
                    },
                )
                continue

            # Evaluate the satisfaction predicate against the now-current
            # state. The state read picks up any writes the child steps
            # just made.
            state = await read_state(
                ctx.run_id, ctx.state_schema, db_path=ctx.db_path
            )
            satisfied, event_extras = await self._evaluate_satisfaction(
                step, state, ctx
            )

            event_data: dict[str, Any] = {
                "iteration": iteration,
                "max_iterations": loop.max_iterations,
                "until_satisfied": satisfied,
                "trigger": "until_evaluated",
            }
            event_data.update(event_extras)
            await self._emitter.emit(
                run_id=ctx.run_id,
                event_type="loop_iteration",
                node_id=step.id,
                data=event_data,
            )

            if satisfied:
                return

        predicate = (
            f"until_bash={loop.until_bash!r}"
            if loop.until_bash
            else f"until={loop.until!r}"
        )
        if loop.on_exhaust == "continue":
            return
        raise LoopExhausted(
            f"loop_exhausted: step {step.id!r} ran {loop.max_iterations} "
            f"iterations without satisfying {predicate}"
        )

    # ---- internals ------------------------------------------------------- #

    async def _evaluate_satisfaction(
        self, step: LoopStep, state: BaseState, ctx: Context
    ) -> tuple[bool, dict[str, Any]]:
        """Decide whether the loop is satisfied this iteration.

        Returns ``(satisfied, event_extras)``. The extras dict carries
        per-mode diagnostic fields (e.g. ``until_bash_timeout``) that
        the caller merges into the ``loop_iteration`` event data.
        """
        loop = step.loop
        # ``until_bash:`` takes precedence when set alone — the combined
        # case has already been rejected up front. ``until: ""`` is
        # treated as "absent" so legacy workflows pairing it with
        # ``until_bash:`` keep working.
        if loop.until_bash:
            command = self._substitute_template(
                loop.until_bash,
                state=state,
                inputs=dict(ctx.inputs),
                step_id=step.id,
            )
            exit_code, timed_out = await self._run_until_bash(command)
            extras: dict[str, Any] = {"until_bash_exit_code": exit_code}
            if timed_out:
                extras["until_bash_timeout"] = True
            return exit_code == 0, extras

        # Default path: Python expression over state. ``until`` is
        # guaranteed non-empty here by the schema validator + the
        # combined-fields check.
        assert loop.until is not None
        return bool(parse_and_eval(loop.until, state=state)), {}

    @staticmethod
    async def _run_until_bash(command: str) -> tuple[int, bool]:
        """Execute the bash command and return ``(exit_code, timed_out)``.

        list-form ``["bash", "-c", command]`` — no ``shell=True``, no
        argv interpolation. The single positional after ``-c`` becomes
        ``$0``; we pass ``harness-until-bash`` so any positional refs
        in the command see the expected ``$0`` rather than a path that
        could leak the workflow author's filesystem layout.
        """
        proc = await asyncio.create_subprocess_exec(
            "bash",
            "-c",
            command,
            "harness-until-bash",
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        try:
            await asyncio.wait_for(proc.wait(), timeout=_UNTIL_BASH_TIMEOUT_S)
        except TimeoutError:
            with contextlib.suppress(ProcessLookupError):
                proc.kill()
            await proc.wait()
            return (proc.returncode if proc.returncode is not None else -1, True)
        return (proc.returncode if proc.returncode is not None else -1, False)

    @staticmethod
    def _substitute_template(
        command: str,
        *,
        state: BaseState,
        inputs: dict[str, Any],
        step_id: str,
    ) -> str:
        """Replace ``$state.<field>`` / ``$inputs.<key>`` with ``str(value)``.

        Missing references raise :class:`ValueError` — silent empty-string
        substitution would mask workflow-authoring bugs (cf. SPEC §5 and
        :meth:`harness.nodes.script.ScriptNode._substitute`).
        """

        def _repl(m: re.Match[str]) -> str:
            scope, name = m.group(1), m.group(2)
            if scope == "state":
                if not hasattr(state, name):
                    raise ValueError(
                        f"loop step {step_id!r} until_bash: unknown state field "
                        f"$state.{name} — state has no attribute {name!r}"
                    )
                return str(getattr(state, name))
            # scope == "inputs"
            if name not in inputs:
                raise ValueError(
                    f"loop step {step_id!r} until_bash: unknown inputs key "
                    f"$inputs.{name} — inputs has no key {name!r}"
                )
            return str(inputs[name])

        return _TEMPLATE_REF_RE.sub(_repl, command)

    @staticmethod
    def _reject_combined_until_fields(step: LoopStep) -> None:
        """Refuse loop blocks that declare both ``until:`` and ``until_bash:``.

        The schema validator already requires at least one. Both at once
        is ambiguous — the resolution order (Python expression vs. bash
        subprocess) is intentionally not picked; the workflow author
        must commit to one shape.
        """
        loop = step.loop
        has_until = loop.until is not None and loop.until != ""
        has_until_bash = loop.until_bash is not None and loop.until_bash != ""
        if has_until and has_until_bash:
            raise ValueError(
                f"loop step {step.id!r}: both until={loop.until!r} and "
                f"until_bash={loop.until_bash!r} are set — pick one. "
                f"The resolution semantics are intentionally ambiguous."
            )
