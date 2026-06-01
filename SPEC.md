# Calibrate Harness — Spec Index

Design specs live in `specs/`. Each file describes a specific area of the implementation as it actually exists. Read the file for the area you are working on.

---

## Spec files

| File | What it covers |
|---|---|
| [`specs/engine-loop.md`](specs/engine-loop.md) | Loop block evaluator: `LoopExecutor`, `LoopExhausted`, `RetryLoopRequested`, `until:` / `until_bash:` satisfaction predicates, `retry_loop:<id>` rewind signal |
| [`specs/engine-executor.md`](specs/engine-executor.md) | Per-node execution: `Executor`, `Context`, dependency checking, contract validation, state writes, per-step retry policy, per-completion snapshots |
| [`specs/state-store.md`](specs/state-store.md) | SQLite schema (runs, events, run_snapshots), `BaseState`, type-driven merge rules, notes bounding, snapshot read/write |
| [`specs/worktree-isolation.md`](specs/worktree-isolation.md) | `WorktreeNode`, create/cleanup actions, three cleanup policies (`merge_to_base`, `leave_for_inspection`, `delete_unconditionally`), branch naming, load-time ancestry validation |
| [`specs/ai-node.md`](specs/ai-node.md) | `AINode`, `Agent` protocol, `ClaudeAgent` / `CodexAgent` / `OpencodeAgent` dispatch adapters, structured output via submit tool, `ContractViolation` / `AgentStalled`, failure-mode catalogue |
| [`specs/script-node.md`](specs/script-node.md) | `ScriptNode`, variable substitution in `args`, command/script dispatch, contract override path, output capture and truncation |
| [`specs/workflow-schema.md`](specs/workflow-schema.md) | YAML structure, all step types, `InputSpec`, `WriteSpec`, inline and shared contracts, per-node retry config, load-time validation rules |
| [`specs/cli.md`](specs/cli.md) | Full command surface, dynamic per-workflow subcommand generation, exit codes, `--json` output shapes, worktrees CLI |
| [`specs/build-workflow.md`](specs/build-workflow.md) | The `workflows/build.yaml` workflow: all steps, prompts, contracts, state fields, constraints |

---

## How to use these specs

- When implementing a feature, read the spec file for that area first.
- When writing a new workflow, read [`specs/workflow-schema.md`](specs/workflow-schema.md) and [`specs/build-workflow.md`](specs/build-workflow.md) as examples.
- When debugging a run, read [`specs/state-store.md`](specs/state-store.md) (event log, state shape) and [`specs/engine-executor.md`](specs/engine-executor.md) (lifecycle events).
- The spec files describe the implementation as it exists. If you find a divergence between a spec file and the code, the code is the authority — update the spec.
