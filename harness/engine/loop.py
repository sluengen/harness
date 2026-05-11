"""Loop block evaluator — see SPEC §10 "Loop blocks".

A :class:`LoopStep` (workflow-schema type) carries a :class:`LoopBlock`
with ``max_iterations``, ``until``, ``fresh_context``, and a child
``steps`` list. The :class:`LoopExecutor` iterates the child steps
in declared order, evaluating ``until:`` against the run's state at
the end of each iteration. The loop exits cleanly when ``until:`` is
true; when ``max_iterations`` is reached without satisfying ``until:``,
it raises :class:`LoopExhausted` — the runner translates that into a
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

* **``until_bash:`` is deferred.** The schema accepts it; the executor
  refuses. ``until_bash`` alone raises :class:`NotImplementedError`;
  both ``until`` and ``until_bash`` together raises :class:`ValueError`
  (ambiguous). Either fires before the first iteration so a misconfigured
  workflow doesn't leave residue.

* **Child errors propagate immediately.** The child step's retry budget
  has already been exhausted by the Executor; the LoopExecutor does not
  layer additional retries. The first raise short-circuits the loop and
  surfaces to the runner.

SPEC: §5 (loop step keys), §10 (loop blocks).
"""

from __future__ import annotations

from harness.dispatch.base import Agent, ResettableAgent
from harness.engine.executor import Context, Executor
from harness.events.emitter import EventEmitter
from harness.nodes._state_expr import parse_and_eval
from harness.state.store import read_state
from harness.workflow.schema import LoopStep

__all__ = ["LoopExecutor", "LoopExhausted"]


class LoopExhausted(Exception):  # noqa: N818 — engine vocabulary (cf. CheckFailed)
    """A loop block ran ``max_iterations`` without ``until:`` becoming true.

    The runner's generic terminal-failure handler maps this to exit
    code 1 and a ``workflow_failed`` event whose ``reason`` is the
    class name. The class name (``"LoopExhausted"``) is the
    identifiable marker downstream consumers grep for; the message
    additionally carries the loop step id and the iteration count.
    """


class LoopExecutor:
    """Iterates a :class:`LoopStep`'s child steps until ``until:`` or exhaustion.

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
        """Run the loop until ``until:`` is true or ``max_iterations``.

        Args:
            step: The :class:`LoopStep` carrying the :class:`LoopBlock`.
            ctx: The same :class:`Context` the runner builds for top-level
                steps — shared registry, contracts, db, schema.

        Raises:
            LoopExhausted: ``max_iterations`` elapsed without ``until:``
                becoming true.
            NotImplementedError: the loop declares ``until_bash:`` with
                no ``until:`` — bash-evaluated exit conditions are
                deferred to a follow-up ticket.
            ValueError: the loop declares both ``until:`` and
                ``until_bash:`` — the resolution semantics are
                ambiguous; pick one.
            Any exception a child step raises after retry exhaustion.
        """
        loop = step.loop
        self._reject_until_bash_combinations(step)

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
            for child in loop.steps:
                await self._executor.execute(child, ctx)

            # Evaluate ``until:`` against the now-current state. The
            # state read picks up any writes the child steps just made.
            state = await read_state(
                ctx.run_id, ctx.state_schema, db_path=ctx.db_path
            )
            satisfied = bool(parse_and_eval(loop.until, state=state))

            await self._emitter.emit(
                run_id=ctx.run_id,
                event_type="loop_iteration",
                node_id=step.id,
                data={
                    "iteration": iteration,
                    "max_iterations": loop.max_iterations,
                    "until_satisfied": satisfied,
                },
            )

            if satisfied:
                return

        raise LoopExhausted(
            f"loop_exhausted: step {step.id!r} ran {loop.max_iterations} "
            f"iterations without satisfying until={loop.until!r}"
        )

    # ---- internals ------------------------------------------------------- #

    @staticmethod
    def _reject_until_bash_combinations(step: LoopStep) -> None:
        """Refuse loop blocks that declare ``until_bash:`` in any form.

        Two distinct cases, two distinct exception classes — the runner
        surfaces both as exit code 1, but the messages name the
        misconfiguration so the workflow author can fix it.
        """
        loop = step.loop
        if loop.until_bash is not None and loop.until:
            raise ValueError(
                f"loop step {step.id!r}: both until={loop.until!r} and "
                f"until_bash={loop.until_bash!r} are set — pick one. "
                f"until_bash execution is deferred to a follow-up ticket."
            )
        if loop.until_bash is not None:
            raise NotImplementedError(
                f"loop step {step.id!r}: until_bash={loop.until_bash!r} "
                f"is not yet supported (deferred to a follow-up ticket); "
                f"use until: with a state expression for now."
            )
