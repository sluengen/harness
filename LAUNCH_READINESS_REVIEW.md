# Launch Readiness Review

Date: 2026-06-03

Scope: repository review of the deterministic agentic pipeline harness before using it to build production app features. This report covers code architecture, launch-blocking bugs, verification gaps, and uplift actions.

## Executive Summary

The harness has a strong deterministic core: workflows are declared in YAML, parsed into Pydantic models, executed by a top-level runner, and persisted through a SQLite event/state store. The separation between orchestration, execution, node behavior, and dispatch adapters is mostly clean.

The repo is not yet launch-clean. The biggest risks are unsupported agent adapters that appear implemented, a documented loop feature that fails at runtime, stale agent-facing repo instructions, non-clean type checks, and verification commands that did not complete during review. These should be remediated before relying on the harness as the production feature-building pipeline.

Recommended launch stance:

- Use only the Claude adapter as a supported AI backend until Codex/OpenCode submit-tool injection is real.
- Treat `until_bash` input substitution as unsupported until fixed.
- Require clean `ruff`, `mypy harness intake`, CLI smoke tests, and pytest in CI before launch.
- Update agent-facing docs immediately so future agents do not follow stale "pre-implementation" instructions.

## Architecture Assessment

### Strengths

- `Runner` owns workflow lifecycle, terminal status, signal handling, and exit-code mapping.
- `Executor` owns per-step dependency checks, retry wrapping, contract validation, state projection, snapshots, and lifecycle events.
- Node implementations are side-effect focused and mostly kept behind `NodeRunner` adapters.
- Workflow loading validates contracts and writer consistency before execution.
- State writes go through one store module, with SQLite WAL and `BEGIN IMMEDIATE` for serialized updates.
- Prompt rendering uses Jinja `StrictUndefined`, which is the right default for workflow authoring safety.
- Worktree isolation is first-class rather than left to prompt convention.

### Main Architectural Risks

- Several future surfaces are present in code and tests: Codex/OpenCode dispatch, human decision resume, Linear webhook intake. Some are explicitly planned for later versions in `README.md`, but they are still importable and may look usable.
- Agent-facing instructions in `CLAUDE.md` contradict `README.md`, creating a real risk for agent-led development.
- The verification story is not currently crisp enough for a launch gate. `ruff` passes, but mypy and test execution need cleanup.

## Launch-Blocking Findings

### 1. Codex and OpenCode Adapters Do Not Have Real Submit-Tool Injection

Severity: P1

Files:

- `harness/dispatch/codex.py`
- `harness/dispatch/opencode.py`

Problem:

Both adapters accept `submit_tool_schema`, but command construction leaves tool injection as a TODO. The runtime then waits for a tool call named `submit_<node_id>`. Without actual tool registration, real runs are likely to end in `ContractViolation("not_called")`.

Why it matters:

The harness depends on structured submit calls for deterministic contract validation. An adapter that cannot reliably present the submit tool is not production-capable.

Remediation actions:

- Mark Codex/OpenCode as unsupported at runtime until submit injection is implemented.
- Add a clear guard in adapter constructors or CLI dispatch selection: fail fast with "Codex/OpenCode dispatch is not supported in this release."
- Keep existing parser tests, but add an integration-style test proving that a real adapter can expose the submit tool before enabling it.
- Update docs to state exactly which adapters are supported in v1 launch.

Uplift actions:

- Add an `AgentCapability` check or adapter metadata with fields like `supports_submit_tool`, `supports_cwd`, `supports_max_turns`, and `supports_tool_allowlist`.
- Add a backend compatibility matrix to `AUTHORING.md`.

### 2. `until_bash` Documents `$inputs.*` Support But Always Rejects It

Severity: P1

File:

- `harness/engine/loop.py`

Problem:

`LoopExecutor._evaluate_satisfaction()` calls `_substitute_template()` with `inputs={}` for `until_bash`. Any command containing `$inputs.foo` raises "unknown inputs key" even though the module docstring says `$inputs.<key>` is supported.

Why it matters:

Workflow authors will reasonably use workflow inputs in loop predicates, especially for polling IDs, branch names, Linear IDs, or environment targets. A valid-looking workflow can fail only at runtime.

Remediation actions:

- Add `inputs: dict[str, Any]` to `Context`, or add a loop-specific execution context that carries inputs.
- Pass run inputs from `Runner._run_inner()` and `Runner._resume_inner()` into the `Context`.
- Add tests for `until_bash` with `$inputs.foo` substitution.
- Update docs if inputs should remain unsupported.

Uplift actions:

- Stop using ad hoc substitution for bash command strings. Prefer rendering with a shared, tested templating helper that supports `state` and `inputs` consistently across AI prompts, script args, and loop predicates.
- Add a workflow static validation pass that flags `$inputs.*` usage in surfaces that do not support it.

### 3. Verification Is Not Launch-Clean

Severity: P1

Files:

- `pyproject.toml`
- `intake/linear_webhook.py`
- multiple tests

Observed during review:

- `ruff check .` passed.
- `mypy harness intake` failed with one error: unused `type: ignore` in `intake/linear_webhook.py`.
- `mypy harness intake tests` failed with 90 errors across 23 files.
- `.venv/bin/python -m pytest` did not complete or emit output during the review window.
- `.venv/bin/python -m harness.cli --help` did not complete or emit output during the review window.

Why it matters:

This harness is intended to become the deterministic production pipeline. Its own verification gate must be reliable, fast enough, and unambiguous.

Remediation actions:

- Remove or correct the unused ignore in `intake/linear_webhook.py`.
- Decide whether tests are in mypy scope. If yes, fix the 90 test typing errors. If no, change the documented/CI command to `mypy harness intake` and keep tests out of strict mypy.
- Investigate why pytest hangs. Run targeted subsets and identify the hanging test.
- Add a CI timeout for pytest so hangs fail loudly.
- Add a minimal CLI smoke test in CI:
  - `harness version`
  - `harness --help`
  - `harness validate workflows/release-notes.yaml`

Uplift actions:

- Add a `make verify` or `scripts/verify.sh` command that runs the canonical checks in the same order locally and in CI.
- Add test duration reporting with `pytest --durations=20`.
- Split slow or external integration tests behind markers.

### 4. Agent-Facing Docs Are Stale and Contradict Runtime Reality

Severity: P2

Files:

- `CLAUDE.md`
- `README.md`

Problem:

`CLAUDE.md` says the repo is "Pre-implementation" and that the deliverable is the spec. `README.md` says v1.0 is shipped and the repo contains a working engine, CLI, Docker image, and authoring guide.

Why it matters:

This repo is explicitly designed for agentic development. Stale agent bootstrap docs can cause future agents to avoid code changes, misread priorities, or follow obsolete process instructions.

Remediation actions:

- Update `CLAUDE.md` to match current project state.
- Replace "planned" language with supported launch surfaces and current verification commands.
- Point agents to `README.md`, `AUTHORING.md`, and relevant `specs/` files.
- Add a short "launch readiness" section that states which adapters and features are supported.

Uplift actions:

- Add a docs consistency test that checks for stale phrases like "Pre-implementation" or "planned" in bootstrap docs.
- Make `CLAUDE.md` a concise operational guide and keep deep design in `SPEC.md`.

### 5. `worktree.merge_to_base` Can Mutate a Dirty Main Working Tree

Severity: P2

File:

- `harness/nodes/worktree.py`

Problem:

The cleanup policy advances the base ref with `git update-ref`, then runs `git read-tree --reset -u HEAD` in the repo root. The code comment assumes all work happened in the isolated worktree and therefore local modifications are not at risk.

Why it matters:

Production users may run the harness from a dirty checkout. Updating the main working tree after moving the ref can disturb local files or create confusing status output.

Remediation actions:

- Before `merge_to_base`, check that the base repo working tree and index are clean.
- If dirty, fail with a clear `WorktreeNodeError` telling the user to commit/stash or run in CI/container.
- Add tests for dirty working tree and dirty index cases.
- Document that `merge_to_base` is intended for clean CI or clean local checkouts.

Uplift actions:

- Prefer using a bare repo or dedicated integration worktree for merge operations.
- Consider making `leave_for_inspection` the default production cleanup policy, with merge handled by an explicit review/PR path.

## Additional Remediation Backlog

### Tighten Supported Feature Surface

Actions:

- Add a `SUPPORTED.md` or README section listing v1 supported features.
- Explicitly label v1.5/v2 code paths as experimental or disabled.
- Add tests that unsupported adapters fail fast with a helpful message.

### Improve Workflow Authoring Safety

Actions:

- Add static validation for unsupported variable references in `script.args`, `until_bash`, prompts, and checks.
- Add examples for safe bash quoting when workflow authors use state or input values in shell commands.
- Consider replacing raw `until_bash` strings with argv-style commands or a script node reference.

### Strengthen Observability

Actions:

- Ensure every failed workflow event includes enough context to diagnose the failing node, exception type, message, and cleanup status.
- Add a `harness doctor` command that checks auth, git cleanliness, DB accessibility, supported adapters, and CLI wiring.
- Add a query command to list recent failed runs grouped by failure reason.

### Harden Release Process

Actions:

- Define a launch gate:
  - `ruff check .`
  - `mypy harness intake`
  - `pytest`
  - CLI smoke tests
  - one mock workflow run
  - one real Claude dry run in a throwaway repo/worktree
- Add CI timeouts and test markers.
- Publish a release checklist and require it before tagging.

### Clarify Version Roadmap

Actions:

- Align `README.md`, `CLAUDE.md`, `AUTHORING.md`, and changelog around what is v1, v1.1, v1.5, and v2.
- Move future-facing implementation notes out of production docstrings where they can be mistaken for current behavior.
- Add migration notes for each version boundary.

## Recommended Remediation Order

1. Fix verification so the team can trust the gate:
   - investigate pytest/CLI hangs
   - fix `mypy harness intake`
   - decide test mypy scope

2. Disable or clearly guard unsupported adapters:
   - Codex
   - OpenCode

3. Fix `until_bash` input substitution or document it as unsupported.

4. Update `CLAUDE.md` and add supported-surface documentation.

5. Add worktree dirty-state guard before `merge_to_base`.

6. Add launch CI and release checklist.

## Launch Decision

Recommended decision: do not use this harness for production feature-building until the P1 items are closed and verification is green.

Acceptable limited launch: use the harness only with the Claude adapter, clean worktrees, and workflows that do not rely on `$inputs.*` in `until_bash`, after pytest and CLI smoke tests complete successfully in CI.

