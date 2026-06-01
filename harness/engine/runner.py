"""Top-level orchestrator: load workflow, walk steps, emit events — see SPEC §4.1.

The :class:`Runner` is invoked once per ``harness run`` call (a future CLI
entry point in H-023 will call ``asyncio.run(runner.run(...))``). It:

1. Generates a run id via :func:`harness.identity.generate_run_id`.
2. Loads the workflow YAML and derives its state schema
   (:mod:`harness.workflow.loader`, :mod:`harness.workflow.derive`).
3. Inserts the ``runs`` row and emits ``workflow_started``.
4. Walks top-level steps in declared order; for each step it dispatches
   either to :meth:`harness.engine.executor.Executor.execute` (the five
   leaf node types) or to :class:`harness.engine.loop.LoopExecutor`
   (loop blocks — SPEC §10). The
   :class:`~harness.engine.executor.Context` is built once and reused;
   per-type :data:`NodeRunner` adapters are constructed up-front from
   the five concrete Node classes (AI/Script/Check/Decision/Worktree).
5. Catches the four terminal exception classes and maps them to SPEC §11
   exit codes:

   * success → ``workflow_completed`` + status ``completed`` + exit 0.
   * :class:`KeyboardInterrupt` (SIGINT) → ``workflow_failed`` with
     ``reason='cancelled'`` + status ``cancelled`` + exit 130.
   * :class:`harness.dispatch.claude.ContractViolation` after retry budget
     → ``workflow_failed`` with the violation reason + status ``failed``
     + exit 3.
   * :class:`harness.nodes.decision.HumanDecisionRequested` → ``decision_requested``
     + ``workflow_paused`` events, status ``paused``, exit 4.
   * anything else from the executor → ``workflow_failed`` + status
     ``failed`` + exit 1.

Cleanup-on-failure: if a worktree was created (state.worktree_path is
set) and the run fails, the runner records ``cleanup_skipped: true`` on
the ``workflow_failed`` event. The worktree node's
``policy: leave_for_inspection`` covers the manual-recovery case; full
cleanup orchestration is the workflow author's responsibility (a
``worktree.cleanup`` step), not the runner's.

NodeRunner adapter shape: every concrete Node has its own ``execute``
signature (e.g. AINode takes ``inputs`` and an optional contract override,
WorktreeNode has separate ``create``/``cleanup`` methods). The runner
builds a thin closure per type that conforms to the uniform
:data:`harness.engine.executor.NodeRunner` callable shape, capturing
``inputs``, ``prompts_dir``, ``repo_root``, etc. once at construction.

Inputs storage: ``inputs`` is stored verbatim on ``runs.inputs_json``
(SPEC §11 "Per-workflow inputs"). It is **not** projected onto state —
templates access workflow inputs via ``$inputs.<name>``/``inputs``-scope,
not via state fields.
"""

from __future__ import annotations

import json
import signal
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import IO, Any

from harness.dispatch.base import Agent
from harness.dispatch.claude import ContractViolation
from harness.dispatch.mock import MockAgent
from harness.engine.executor import Context, Executor, NodeRunner
from harness.engine.loop import LoopExecutor, RetryLoopRequested
from harness.engine.retry import RetryPolicy
from harness.events.emitter import EventEmitter
from harness.identity import artifacts_dir as artifacts_dir_for
from harness.identity import generate_run_id
from harness.nodes.ai import AINode
from harness.nodes.base import NodeResult
from harness.nodes.check import CheckNode
from harness.nodes.decision import DecisionNode, HumanDecisionRequested
from harness.nodes.script import ScriptNode
from harness.nodes.worktree import WorktreeNode
from harness.state.schema import BaseState
from harness.state.store import DEFAULT_DB_PATH, connect, init_db
from harness.workflow.derive import derive_state_schema
from harness.workflow.loader import LoadedWorkflow, load_workflow
from harness.workflow.schema import (
    AIStep,
    CheckStep,
    DecisionStep,
    LoopStep,
    ScriptStep,
    Step,
    Workflow,
    WorktreeStep,
)

__all__ = ["CheckFailed", "Runner"]


class CheckFailed(RuntimeError):  # noqa: N818 — engine vocabulary
    """A check step evaluated False and its ``on_fail`` resolved to cancel.

    Raised by the runner's check adapter so the executor's standard
    ``node_failed → re-raise`` path translates a failed check into a
    workflow-level failure. The runner then catches the exception in its
    terminal handler and emits ``workflow_failed`` with exit code 1.
    """


class Runner:
    """Top-level workflow orchestrator (SPEC §4.1).

    Construction is cheap — the heavy work happens in :meth:`run`. The
    instance is reusable across multiple ``run()`` invocations as long as
    callers want the same agent / policy / repo_root configuration.

    Args:
        agent: The :class:`Agent` to use for AI / decision dispatch.
            Defaults to :class:`MockAgent` so unit tests don't need a
            live Claude session.
        policy: Retry policy. Defaults to :meth:`RetryPolicy.v1_default`.
        db_path: SQLite path. Defaults to ``.harness/harness.db`` (SPEC
            §12 single-db-per-project model).
        prompts_dir: Filesystem root for Jinja prompt templates. AI /
            decision nodes resolve ``step.prompt`` relative to this.
            Defaults to ``prompts`` next to the workflow file at
            ``run`` time when ``None``.
        repo_root: Filesystem root used by the worktree adapter. Defaults
            to ``Path(".")``.
    """

    def __init__(
        self,
        *,
        agent: Agent | None = None,
        policy: RetryPolicy | None = None,
        db_path: Path | None = None,
        prompts_dir: Path | None = None,
        repo_root: Path | None = None,
        progress: bool = True,
        _progress_file: IO[str] | None = None,
    ) -> None:
        self._agent: Agent = agent if agent is not None else MockAgent()
        self._policy = policy if policy is not None else RetryPolicy.v1_default()
        self._db_path = db_path if db_path is not None else DEFAULT_DB_PATH
        self._prompts_dir = prompts_dir
        self._repo_root = repo_root if repo_root is not None else Path(".")
        self._progress = progress
        self._progress_file = _progress_file
        self._executor = Executor(policy=self._policy)

    async def run(
        self,
        workflow_path: Path,
        inputs: dict[str, Any],
        *,
        base_branch: str = "main",
        _node_overrides: dict[str, NodeRunner] | None = None,
    ) -> int:
        """Execute the workflow end-to-end and return the SPEC §11 exit code.

        Args:
            workflow_path: Path to the workflow YAML.
            inputs: Workflow inputs. Stored verbatim on
                ``runs.inputs_json``; available to templates via the
                ``inputs`` scope key.
            base_branch: Branch the run was started against. Lands on
                :attr:`BaseState.base_branch` and the ``runs.base_branch``
                column. Defaults to ``"main"``.
            _node_overrides: Test seam — override one or more entries of
                the node-runner registry by ``step.type``. Production
                callers do not pass this; it is documented only for
                regression tests covering the SIGINT / cancellation path.

        Returns:
            ``0`` on success, ``1`` on caught executor failure, ``3`` on
            :class:`ContractViolation` after retry exhaustion, ``4`` on
            :class:`HumanDecisionRequested` (workflow paused awaiting
            decision), ``130`` on SIGINT / ``KeyboardInterrupt``.

        Raises:
            Any exception from :func:`load_workflow` or
                :func:`derive_state_schema` — invocation errors (SPEC §11
                exit 2) are the CLI layer's concern, not the runner's.
        """
        loaded = load_workflow(workflow_path)

        state_schema = derive_state_schema(loaded)
        run_id = generate_run_id()

        # Install a SIGINT handler that maps the signal to a
        # ``KeyboardInterrupt`` raised at the next interpreter check
        # point. The default Python handler already does this for the
        # main thread, but we re-install defensively so a calling shell
        # that masked SIGINT doesn't leave the runner unable to honour
        # SPEC §10's cancellation contract.
        previous_handler = self._install_sigint_handler()

        try:
            return await self._run_inner(
                loaded=loaded,
                run_id=run_id,
                state_schema=state_schema,
                inputs=inputs,
                base_branch=base_branch,
                node_overrides=_node_overrides,
            )
        finally:
            # Always restore the previous handler — even if _run_inner
            # raised an unexpected exception class out past our terminal
            # handling.
            self._restore_sigint_handler(previous_handler)

    # ---- internals ------------------------------------------------------- #

    async def _run_inner(
        self,
        *,
        loaded: LoadedWorkflow,
        run_id: str,
        state_schema: type[BaseState],
        inputs: dict[str, Any],
        base_branch: str,
        node_overrides: dict[str, NodeRunner] | None,
    ) -> int:
        """Core orchestration after load / derive / SIGINT install."""
        started_wall = datetime.now(UTC)
        started_monotonic = time.monotonic()
        artifacts_dir = artifacts_dir_for(run_id)

        # Build initial state. Per SPEC §6: BaseState fields are populated
        # by the engine at run start; per-workflow fields default to None
        # / [] / {} via the derived class.
        initial_state = state_schema.model_validate(
            {
                "run_id": run_id,
                "workflow_name": loaded.workflow.name,
                "base_branch": base_branch,
                "artifacts_dir": str(artifacts_dir),
                "started_at": started_wall,
                "notes": [],
            }
        )

        await init_db(self._db_path)
        await self._insert_run_row(
            run_id=run_id,
            workflow=loaded.workflow,
            initial_state=initial_state,
            inputs=inputs,
            base_branch=base_branch,
            started_at=started_wall,
        )

        from harness.engine.progress import ProgressReporter

        progress_sink = (
            ProgressReporter(loaded.workflow.name, file=self._progress_file)
            if self._progress
            else None
        )

        emitter = EventEmitter(self._db_path, on_emit=progress_sink)
        await emitter.emit(
            run_id=run_id,
            event_type="workflow_started",
            data={
                "workflow_name": loaded.workflow.name,
                "workflow_version": loaded.workflow.version,
            },
        )

        # Build the per-run Context. Node adapters are reusable across
        # the workflow's lifespan — construct once, reference everywhere.
        registry = self._build_node_registry(
            inputs=inputs,
            workflow_path=loaded.path,
            run_id=run_id,
        )
        if node_overrides:
            registry = {**registry, **node_overrides}

        ctx = Context(
            run_id=run_id,
            db_path=self._db_path,
            contracts=loaded.contracts,
            state_schema=state_schema,
            nodes=registry,
            workflow_name=loaded.workflow.name,
            progress_sink=progress_sink,
        )

        # Build the loop evaluator once per run; it reuses the same
        # executor + agent + emitter so loop children share the wider
        # run's retry policy, contract registry, and event log.
        loop_executor = LoopExecutor(
            executor=self._executor,
            agent=self._agent,
            emitter=emitter,
        )

        # Walk steps. Each terminal exception class maps to a distinct
        # exit code (SPEC §11). KeyboardInterrupt MUST be caught before
        # the catch-all ``BaseException`` arm so the cancelled path wins.
        last_step_id: str | None = None
        try:
            for step in loaded.workflow.steps:
                last_step_id = step.id
                if isinstance(step, LoopStep):
                    await loop_executor.execute(step, ctx)
                else:
                    await self._executor.execute(step, ctx)
        except KeyboardInterrupt:
            await self._finalise_failure(
                emitter=emitter,
                run_id=run_id,
                last_step_id=last_step_id,
                started_monotonic=started_monotonic,
                status="cancelled",
                exit_code=130,
                reason="cancelled",
            )
            return 130
        except ContractViolation as exc:
            await self._finalise_failure(
                emitter=emitter,
                run_id=run_id,
                last_step_id=last_step_id,
                started_monotonic=started_monotonic,
                status="failed",
                exit_code=3,
                reason=f"ContractViolation: {exc.reason}",
            )
            return 3
        except HumanDecisionRequested as exc:
            await self._finalise_pause(
                emitter=emitter,
                run_id=run_id,
                started_monotonic=started_monotonic,
                step_id=exc.step_id,
                message=exc.message,
            )
            return 4
        except BaseException as exc:
            # Catch-all for anything else the executor surfaces post-retry.
            # The executor already emitted ``node_failed``; we layer the
            # workflow-level terminal event on top.
            await self._finalise_failure(
                emitter=emitter,
                run_id=run_id,
                last_step_id=last_step_id,
                started_monotonic=started_monotonic,
                status="failed",
                exit_code=1,
                reason=type(exc).__name__,
                message=str(exc),
            )
            return 1

        # Success path.
        duration_ms = int((time.monotonic() - started_monotonic) * 1000)
        await self._update_run_completion(
            run_id=run_id,
            status="completed",
            exit_code=0,
            duration_ms=duration_ms,
        )
        await emitter.emit(
            run_id=run_id,
            event_type="workflow_completed",
            duration_ms=duration_ms,
        )
        return 0

    async def _finalise_failure(
        self,
        *,
        emitter: EventEmitter,
        run_id: str,
        last_step_id: str | None,
        started_monotonic: float,
        status: str,
        exit_code: int,
        reason: str,
        message: str | None = None,
    ) -> None:
        """Persist the failure on the ``runs`` row + emit ``workflow_failed``.

        Includes a ``cleanup_skipped`` flag when the run created a
        worktree but no ``worktree.cleanup`` step could run (full
        recovery is the worktree node's ``leave_for_inspection``
        policy's job — see SPEC §9).
        """
        duration_ms = int((time.monotonic() - started_monotonic) * 1000)
        await self._update_run_completion(
            run_id=run_id,
            status=status,
            exit_code=exit_code,
            duration_ms=duration_ms,
        )

        data: dict[str, Any] = {"reason": reason}
        if last_step_id is not None:
            data["node_id"] = last_step_id
        if message is not None:
            data["message"] = message
        # Best-effort: if the run created a worktree, surface that
        # cleanup_skipped flag so an operator scanning events knows the
        # worktree dir is still around for manual inspection.
        cleanup_skipped = await self._worktree_was_created(run_id)
        if cleanup_skipped:
            data["cleanup_skipped"] = True

        await emitter.emit(
            run_id=run_id,
            event_type="workflow_failed",
            duration_ms=duration_ms,
            data=data,
        )

    async def _finalise_pause(
        self,
        *,
        emitter: EventEmitter,
        run_id: str,
        started_monotonic: float,
        step_id: str,
        message: str,
    ) -> None:
        """Persist the paused state + emit lifecycle events + print instructions.

        Called when a human-decision node is reached (SPEC §4.5, H-2-002).
        Updates the run row to status='paused' with exit_code=4, emits
        ``decision_requested`` and ``workflow_paused`` events, then prints the
        decision message and resume instructions to stdout.
        """
        duration_ms = int((time.monotonic() - started_monotonic) * 1000)
        await self._update_run_completion(
            run_id=run_id,
            status="paused",
            exit_code=4,
            duration_ms=duration_ms,
        )
        await emitter.emit(
            run_id=run_id,
            event_type="decision_requested",
            node_id=step_id,
            data={"step_id": step_id, "message": message},
        )
        await emitter.emit(
            run_id=run_id,
            event_type="workflow_paused",
            duration_ms=duration_ms,
            data={"step_id": step_id},
        )
        print(
            f"\n[harness] Workflow paused — human decision required\n"
            f"  Run ID:  {run_id}\n"
            f"  Message: {message}\n"
            f"\n"
            f"  To continue:\n"
            f"    harness decision approve {run_id}\n"
            f"    harness decision reject  {run_id}\n",
            file=sys.stdout,
        )

    async def _worktree_was_created(self, run_id: str) -> bool:
        """True iff the run row's state shows a worktree was provisioned."""
        try:
            async with (
                connect(self._db_path) as conn,
                conn.execute(
                    "SELECT state_json FROM runs WHERE run_id = ?", (run_id,)
                ) as cur,
            ):
                row = await cur.fetchone()
        except Exception:  # pragma: no cover — defensive only
            return False
        if row is None:
            return False
        try:
            state = json.loads(str(row[0]))
        except Exception:  # pragma: no cover — defensive only
            return False
        return bool(state.get("worktree_path"))

    async def _insert_run_row(
        self,
        *,
        run_id: str,
        workflow: Workflow,
        initial_state: BaseState,
        inputs: dict[str, Any],
        base_branch: str,
        started_at: datetime,
    ) -> None:
        """INSERT the ``runs`` row with status='running' before any step.

        The schema requires non-null ``state_json`` / ``inputs_json`` /
        ``started_at``; everything else is left null until the run
        terminates (the completion update fills ``completed_at``,
        ``exit_code``, ``duration_ms`` in one go).
        """
        async with connect(self._db_path) as conn:
            await conn.execute(
                "INSERT INTO runs ("
                "run_id, workflow_name, workflow_version, status, "
                "state_json, inputs_json, base_branch, started_at"
                ") VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    run_id,
                    workflow.name,
                    workflow.version,
                    "running",
                    initial_state.model_dump_json(),
                    json.dumps(inputs),
                    base_branch,
                    started_at.isoformat(),
                ),
            )
            await conn.commit()

    async def _update_run_completion(
        self,
        *,
        run_id: str,
        status: str,
        exit_code: int,
        duration_ms: int,
    ) -> None:
        """Mark the run row as terminal and stamp completion metadata."""
        completed_at = datetime.now(UTC).isoformat()
        async with connect(self._db_path) as conn:
            await conn.execute(
                "UPDATE runs SET status = ?, exit_code = ?, "
                "completed_at = ?, duration_ms = ? WHERE run_id = ?",
                (status, exit_code, completed_at, duration_ms, run_id),
            )
            await conn.commit()

    # ---- node adapter wiring -------------------------------------------- #

    def _build_node_registry(
        self,
        *,
        inputs: dict[str, Any] | None = None,
        workflow_path: Path | None = None,
        run_id: str | None = None,
    ) -> dict[str, NodeRunner]:
        """Build the 5-type adapter registry the executor consumes.

        Each concrete Node has its own ``execute()`` signature; the
        adapters close over the per-run plumbing (inputs, prompts_dir,
        repo_root, run_id) and present a uniform
        ``async def(step, state, ctx) -> NodeResult`` shape.

        Called both from :meth:`run` (with the live args) and from tests
        (with bare defaults) — the registry shape is identical in both
        cases; the closures simply substitute empty inputs / Path(".")
        when called outside a run.
        """
        inputs = inputs if inputs is not None else {}
        prompts_dir = self._resolve_prompts_dir(workflow_path)
        repo_root = self._repo_root
        # ``run_id`` is only used by the worktree adapter; fall through
        # to a placeholder when called from tests just probing the
        # registry shape.
        rid = run_id if run_id is not None else ""

        ai_node = AINode(agent=self._agent, prompts_dir=prompts_dir)
        script_node = ScriptNode()
        check_node = CheckNode()
        decision_node = DecisionNode(
            agent=self._agent,
            prompts_dir=prompts_dir,
        )
        worktree_node = WorktreeNode()

        async def ai_adapter(
            step: Step, state: BaseState, ctx: Context
        ) -> NodeResult[Any]:
            assert isinstance(step, AIStep), (
                f"ai adapter received non-AIStep: {type(step).__name__}"
            )
            # Pass the loader-compiled contract via ``contract_override``
            # so the AINode's isinstance guard binds to the same Pydantic
            # class the executor checks against. Without this, AINode
            # recompiles the inline dict into a fresh class and the
            # executor's downstream isinstance check fails on identity.
            override = ctx.contracts.get(step.id)
            return await ai_node.execute(
                step=step,
                state=state,
                inputs=inputs,
                contract_override=override,
            )

        async def script_adapter(
            step: Step, state: BaseState, ctx: Context
        ) -> NodeResult[Any]:
            assert isinstance(step, ScriptStep), (
                f"script adapter received non-ScriptStep: {type(step).__name__}"
            )
            # Same rationale as ai_adapter: when the step declares an
            # inline contract:, the loader compiled it and exposed it via
            # ctx.contracts. Pass it through so ScriptNode parses stdout
            # as JSON and binds it to the same Pydantic class the
            # executor's downstream isinstance check uses. Without this,
            # the steward workflow's write-report step (writes:
            # [report_path]) would fail at the executor's
            # _validate_writes_against_contract — ScriptOutput has no
            # ``report_path`` field. See SPEC §14.
            override = ctx.contracts.get(step.id)
            return await script_node.execute(
                step=step,
                state=state,
                inputs=inputs,
                contract_override=override,
            )

        async def check_adapter(
            step: Step, state: BaseState, _ctx: Context
        ) -> NodeResult[Any]:
            assert isinstance(step, CheckStep), (
                f"check adapter received non-CheckStep: {type(step).__name__}"
            )
            result = await check_node.execute(step=step, state=state)
            # SPEC §5: ``on_fail: cancel`` means a false check halts the
            # run. The CheckNode reports passed=False without raising;
            # the runner translates the routing here so the executor's
            # standard ``node_failed → re-raise`` path covers cancel.
            # ``continue`` lets the workflow proceed regardless;
            # ``retry_loop:<id>`` raises :class:`RetryLoopRequested` so
            # the enclosing :class:`LoopExecutor` can rewind to the
            # named loop. With no enclosing loop the runner's generic
            # handler surfaces it as a workflow failure naming the id.
            if not result.contract.passed:
                on_fail = result.contract.on_fail
                if on_fail == "cancel":
                    raise CheckFailed(
                        f"check {step.id!r} failed and on_fail=cancel: "
                        f"expr={step.expr!r}"
                    )
                if on_fail.startswith("retry_loop:"):
                    loop_id = on_fail[len("retry_loop:") :]
                    raise RetryLoopRequested(loop_id, requested_by=step.id)
                # on_fail == "continue" — fall through, result returned.
            return result

        async def decision_adapter(
            step: Step, state: BaseState, ctx: Context
        ) -> NodeResult[Any]:
            assert isinstance(step, DecisionStep), (
                f"decision adapter received non-DecisionStep: {type(step).__name__}"
            )
            # Same rationale as ai_adapter: pass the loader-compiled
            # contract so executor + decision isinstance checks agree on
            # one class.
            override = ctx.contracts.get(step.id)
            return await decision_node.execute(
                step=step,
                state=state,
                inputs=inputs,
                contract_override=override,
            )

        async def worktree_adapter(
            step: Step, state: BaseState, _ctx: Context
        ) -> NodeResult[Any]:
            assert isinstance(step, WorktreeStep), (
                f"worktree adapter received non-WorktreeStep: "
                f"{type(step).__name__}"
            )
            if step.action == "create":
                assert step.base is not None  # WorktreeStep validator
                base = step.base
                if base.startswith("$inputs."):
                    key = base[len("$inputs."):]
                    base = str(inputs.get(key, base))
                elif base.startswith("$state."):
                    field = base[len("$state."):]
                    base = str(getattr(state, field, base))
                return await worktree_node.create(
                    run_id=rid,
                    repo_root=repo_root,
                    base=base,
                )
            # cleanup
            assert step.policy is not None  # WorktreeStep validator
            if state.worktree_path is None or state.worktree_branch is None:
                raise RuntimeError(
                    f"worktree.cleanup step {step.id!r}: no worktree "
                    f"recorded on state (worktree_path / worktree_branch "
                    f"are None) — was worktree.create run?"
                )
            return await worktree_node.cleanup(
                run_id=rid,
                repo_root=repo_root,
                worktree_path=state.worktree_path,
                worktree_branch=state.worktree_branch,
                base=state.base_branch,
                policy=step.policy,
            )

        return {
            "ai": ai_adapter,
            "script": script_adapter,
            "check": check_adapter,
            "decision": decision_adapter,
            "worktree": worktree_adapter,
        }

    def _resolve_prompts_dir(self, workflow_path: Path | None) -> Path:
        """Pick the prompts dir: constructor override > repo root > ``.``.

        Prompts live at ``prompts/`` next to ``workflows/`` at the repo root,
        so the Jinja loader must be anchored there — not at ``workflow_path.parent``
        (which is ``workflows/``). ``self._repo_root`` defaults to ``Path(".")``
        which is the cwd at invocation time (the repo root for normal usage).
        """
        if self._prompts_dir is not None:
            return self._prompts_dir
        return self._repo_root

    # ---- signal handling ------------------------------------------------- #

    @staticmethod
    def _install_sigint_handler() -> Any:
        """Install the default SIGINT → KeyboardInterrupt handler.

        Python's default already maps SIGINT to KeyboardInterrupt on the
        main thread; we re-install ``signal.default_int_handler``
        defensively so a parent process that suppressed SIGINT doesn't
        leave the runner unable to honour SPEC §10's cancellation
        contract. Off the main thread (some test harnesses), the call
        raises :class:`ValueError`; we treat that as "nothing to do".
        """
        try:
            return signal.signal(signal.SIGINT, signal.default_int_handler)
        except (ValueError, OSError):  # pragma: no cover - non-main-thread
            return None

    @staticmethod
    def _restore_sigint_handler(previous: Any) -> None:
        """Best-effort restore the previous handler installed by Python."""
        if previous is None:
            return
        try:
            signal.signal(signal.SIGINT, previous)
        except (ValueError, OSError):  # pragma: no cover - non-main-thread
            return
