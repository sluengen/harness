<!-- guidance:template-context@0.1.4 -->
# CONTEXT.md

Agent-facing current state for **harness**. Universal process lives in the entry process document; rationale and history live in the linked specs and decisions.

```yaml
profile: harness
visibility: committed
repo:
  name: harness
  project: Harness
tracker: github
github:
  repo: sluengen/harness
  project: sluengen/2
  # status_field omitted: use the built-in Status field.
layers:
  design_system: true   # design/ is the source for docs/index.html.
  feature_specs: true   # reviewer-owned as-built records live in specs/features/.
stack:
  language: Python 3.11+
  framework: Pydantic 2 / Typer / aiosqlite
commands:
  install: "uv sync --extra dev"
  lint: "uv run --extra dev ruff check ."
  typecheck: "uv run --extra dev mypy harness"
  test: "uv run --extra dev pytest"
  test_one: "uv run --extra dev pytest <path/to/test_file.py::test_name>"
  verify: "bash scripts/verify.sh"   # canonical gate: lint, typecheck, full partitioned pytest suite, smoke/drift checks, report.
  run: "harness start <ISSUE-ID> → design → review → close"
branches:
  integration: dev
  staging: staging
  release: main   # promotion topology and authority: specs/decisions/0003-promotion-lifecycle.md.
loop:
  max_review_cycles: 5           # Matches DEFAULT_MAX_REVIEW_CYCLES; policy: skills/review-discipline/SKILL.md.
  unconditional_review_cycles: 3 # Matches DEFAULT_UNCONDITIONAL_REVIEW_CYCLES; never exceed max_review_cycles.
  wall_clock_budget_minutes: 110 # Bounds unattended runs; attended mode uses attended_idle_minutes. Matches DEFAULT_WALL_CLOCK_BUDGET_MINUTES; rationale: specs/decisions/0011-attended-run-spend-scope.md and specs/features/verb-model.md.
  attended_idle_minutes: 480     # Attended reclaim threshold; matches DEFAULT_ATTENDED_IDLE_MINUTES and must not be below wall_clock_budget_minutes.
  review_model: opus             # Plain alias used by the Claude review engine; matches DEFAULT_REVIEW_MODEL. Rationale: specs/features/verb-model.md.
  untracked_file_limit: 1000     # Review pollution guard; 0 disables. Matches DEFAULT_UNTRACKED_FILE_LIMIT; evidence: specs/features/verb-model.md.
  engine_timeout_seconds: 900    # Shared design/review subprocess ceiling; matches DEFAULT_ENGINE_TIMEOUT_SECONDS. Rationale and rejected split: specs/features/verb-model.md and specs/proposals/per-engine-timeout-ceiling.md.
  probe_max_entries: 3           # Maximum proposed mutations per review; 0 disables. Matches DEFAULT_PROBE_MAX_ENTRIES; evidence: specs/features/verb-model.md.
  probe_budget_seconds: 720      # Probe ceiling, clamped to engine_timeout_seconds; matches DEFAULT_PROBE_BUDGET_SECONDS.
conventions:
  commit_format: "type(scope): description — feat / fix / chore / docs / refactor / test / spec"
paths:
  source: harness/
  tests: tests/
  proposals: specs/proposals/
  features: specs/features/
  decisions: specs/decisions/
  design_system: design/
architecture_watchlist:
  files:
    - harness/cli/review.py   # Review orchestration; seams: review_protocol.py, review_inherit.py, review_telemetry.py, review_pollution.py, review_probe.py. Carries a size: marker.
    - harness/cli/close.py    # Close gate and ledger finalization; git in close_merge.py, tracker in close_tracker.py, telemetry in close_telemetry.py, retry in close_retry.py. Carries a size: marker.
    - harness/cli/reclaim.py  # Reclaim orchestration; seams: reclaim_liveness.py, reclaim_undo.py, reclaim_closable.py, reclaim_marker.py. Tests follow the seams. Carries a size: marker.
    - harness/cli/promote.py  # Promotion lifecycle orchestration; mechanics live in promotion.py, promotion_gate.py, promotion_pr.py, and promotion_escalation.py. Carries a size: marker.
env:
  file: .env
```

## What this repo is

Deterministic, audited verbs an orchestrating agent session calls to drive a tracker ticket end-to-end. The agent implements and controls the loop; the harness owns the durable ledger, git/tracker mutations, and gate. It is self-hosted infrastructure with no product UI. `README.md` and `SPEC.md` describe the verb model.

## Architecture

The Python package exposes a Typer CLI backed by SQLite, git worktrees, tracker adapters, and review/design engine dispatch.

The driven lifecycle is `start → design → implement → review → (fix → review)* → close`.

Four verbs, one ledger, one gate:

- **`start`** validates the ticket, moves it to In Progress, creates a worktree from `branches.integration`, and opens a run.
- **`design`** records a grounded design attempt for complex work; simpler assurance levels record a skip.
- **`review`** records a pass/fail/defer verdict bound to the reviewed git SHA. Engine selection and fallback are in `specs/features/verb-model.md`.
- **`close`** requires a passing verdict for current HEAD, then integrates, pushes, moves the ticket to Done, and finalizes the run.

Read-only/ops commands inspect or maintain the same ledger. Every lifecycle git and tracker mutation goes through a verb; hand-written mutations break the audit trail. Read the governing feature spec before changing a verb, ledger schema, or gate.

## Repo-specific principles

- TDD is mandatory: observe a failing test before implementation.
- Keep changes scoped and commits atomic; every commit leaves the gate green.
- Read the relevant spec first. The builder does not edit `specs/features/`; the reviewer records what shipped.
- Keep `uv.lock` committed for reproducible `uv sync --frozen` builds.

## Decisions index

Use `specs/decisions/` only for cross-cutting choices that are consequential and expensive to reverse. Feature-local decisions stay in their feature spec. Amend a superseded ADR in place so links remain stable.

- [0001 — local loop default; optional per-target cloud](specs/decisions/0001-cloud-runnable-harness-loop.md)
- [0002 — in-container review engine](specs/decisions/0002-in-container-review-engine.md), amended by [0013](specs/decisions/0013-codex-engines-in-container.md)
- [0003 — promotion lifecycle and branch topology](specs/decisions/0003-promotion-lifecycle.md)
- [0005 — retired per-ticket model tiering](specs/decisions/0005-per-ticket-model-tiering.md)
- [0006 — hold kinds](specs/decisions/0006-hold-kinds.md)
- [0007 — design verb](specs/decisions/0007-design-verb.md)
- [0009 — verb attempt telemetry](specs/decisions/0009-verb-attempt-telemetry.md)
- [0010 — rebased-tree recertification](specs/decisions/0010-rebased-tree-recertification.md)
- [0011 — attended-run spend scope](specs/decisions/0011-attended-run-spend-scope.md)

## Where deeper truth lives

- System design and verb behavior: `SPEC.md`, `specs/features/verb-model.md`, `specs/features/cli-surface.md`, `specs/features/run-ledger.md`, `specs/features/worktree-lifecycle.md`
- Build-time mutation instrument: `scripts/mutate.py`, driven by `CONTRIBUTING.md`
- Harness workflows: `commands/harness.md` and its directly linked workflow references
- Loop operations: `RUNBOOK.md`; loop substrate: ADR 0001
- Promotion policy: ADR 0003; attended timing: ADR 0011
- User-facing feature surface: `README.md`; unconfirmed ideas: `specs/proposals/`
- Issues and in-flight work: the configured GitHub repository and Projects board

## Gotchas

- Use `~/bin/harness` from a target repo for the Docker-wrapped verbs. Use `bin/harness` only while developing this checkout; native installs use `uv tool install .`.
- Drive attended work through `/harness run <ISSUE-ID>` or the agent-led `/build`; workflow and refusal handling live behind `commands/harness.md`.
- Cross-repo verbs use CWD; direct/native calls may also accept `--repo` and `--base`.
- `mypy` checks `harness`, not tests.
- Tests are automatically tiered by `tests/_tiers.py`. The verify gate partitions Docker and non-Docker tests but covers their union with one coverage floor.
- Long verification output may need capture to `/tmp/<file>.txt` and a final read.

## Python conventions

- Use `@asynccontextmanager` for resource handles; `harness/state/store.py` is the pattern.
- Exception names mirror SPEC vocabulary; apply a scoped `# noqa: N818` where required.
- Validate Pydantic boundaries, trust validated interior data, and use async I/O.
- Never use `eval`/`exec`/`pickle` on untrusted data, string-formatted SQL, `shell=True` with user input, or unvalidated paths outside their prefix. Secrets come from the environment and are never logged or committed.
