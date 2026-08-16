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
  language: Python 3.11+   # tooling only — the repo has no runtime dependencies.
commands:
  install: "uv sync --extra dev"
  lint: "uv run --extra dev ruff check ."
  typecheck: "uv run --extra dev mypy scripts templates"
  test: "uv run --extra dev pytest"
  test_one: "uv run --extra dev pytest <path/to/test_file.py::test_name>"
  verify: "bash scripts/verify.sh"   # canonical gate: lint, typecheck, full pytest suite with coverage, landing-page and design-token drift checks.
branches:
  integration: dev
  staging: staging
  release: main   # promotion topology and authority: specs/decisions/0003-promotion-lifecycle.md.
loop:
  # The two keys the universal `review-discipline` skill reads. They are policy,
  # not runtime configuration — the seven that mirrored the retired runtime's
  # DEFAULT_* constants went with it (ADR 0015).
  max_review_cycles: 5           # Stop policy: skills/review-discipline/SKILL.md.
  unconditional_review_cycles: 3 # Never exceed max_review_cycles.
conventions:
  commit_format: "type(scope): description — feat / fix / chore / docs / refactor / test / spec"
paths:
  tests: tests/
  proposals: specs/proposals/
  features: specs/features/
  decisions: specs/decisions/
  design_system: design/
env:
  file: .env
```

## What this repo is

The source of a spec-driven development process, and the deterministic gates that keep it honest. It publishes a versioned guidance surface — skills, agents, commands, templates and hooks — that an installer copies into consuming repos, and it dogfoods that surface on itself. It is self-hosted infrastructure with no product UI and no runtime: ADR 0015 retired the container, the CLI verb loop and the run ledger in favour of an agent-led process bounded by a gate.

## Architecture

Three parts, and nothing else:

- **The guidance surface** — `skills/`, `agents/`, `commands/`, `templates/`, `hooks/`, `process/harness.md` and its three byte-identical mirrors (`CLAUDE.md`, `AGENTS.md`, `GEMINI.md`). `registry.yaml` is the manifest: what each file is, what version it carries, and whether the installer copies it into a consuming repo.
- **The gate** — `scripts/verify.sh`, the one command that decides whether a tree is green: ruff, mypy over `scripts`/`templates`, the pytest suite with a coverage floor over `scripts/`, and the two drift guards over `docs/index.html`.
- **The guards** — `tests/unit/`, which is almost entirely tree-readers: guidance modules asserting that the published prose says what the process requires, that versions and the registry agree, and that a retired subsystem is actually gone. `scripts/mutate.py` is the mutation instrument that proves a guard can fail.

A ticket is driven agent-led (`/build`, or `/start → /review → /ship` when attended), never by a runtime this repo hosts.

## Repo-specific principles

- TDD is mandatory: observe a failing test before implementation.
- Keep changes scoped and commits atomic; every commit leaves the gate green.
- Read the relevant spec first. The builder does not edit `specs/features/`; the reviewer records what shipped.
- Guidance is version-stamped. Edit the canonical file, bump its registry entry, and mirror `process/harness.md` byte-for-byte into `CLAUDE.md`, `AGENTS.md` and `GEMINI.md`.
- Keep `uv.lock` committed for reproducible `uv sync --frozen` builds.

## Decisions index

Use `specs/decisions/` only for cross-cutting choices that are consequential and expensive to reverse. Feature-local decisions stay in their feature spec. Amend a superseded ADR in place so links remain stable.

[0015](specs/decisions/0015-harness-v4-thin-verification-layer.md) retires the runtime, so every decision below that governed a runtime mechanism is superseded in mechanism — the reasoning stands, the machinery it chose is gone. They are kept for the audit, not as instructions.

- [0001 — local loop default; optional per-target cloud](specs/decisions/0001-cloud-runnable-harness-loop.md) — superseded in mechanism by 0015
- [0002 — in-container review engine](specs/decisions/0002-in-container-review-engine.md), amended by [0013](specs/decisions/0013-codex-engines-in-container.md) — superseded in mechanism by 0015
- [0003 — promotion lifecycle and branch topology](specs/decisions/0003-promotion-lifecycle.md) — the topology stands; the `harness promote` verb that drove it is retired by 0015
- [0004 — repo-guide drift guard](specs/decisions/0004-repo-guide-drift-guard.md)
- [0005 — retired per-ticket model tiering](specs/decisions/0005-per-ticket-model-tiering.md) — superseded in mechanism by 0015
- [0006 — hold kinds](specs/decisions/0006-hold-kinds.md)
- [0007 — design verb](specs/decisions/0007-design-verb.md) — superseded in mechanism by 0015
- [0008 — inherited ledger events](specs/decisions/0008-inherited-ledger-events.md) — superseded in mechanism by 0015
- [0009 — verb attempt telemetry](specs/decisions/0009-verb-attempt-telemetry.md) — superseded in mechanism by 0015
- [0010 — rebased-tree recertification](specs/decisions/0010-rebased-tree-recertification.md) — superseded in mechanism by 0015
- [0011 — attended-run spend scope](specs/decisions/0011-attended-run-spend-scope.md) — superseded in mechanism by 0015
- [0012 — persistent runtime host](specs/decisions/0012-persistent-runtime-host.md) — superseded in mechanism by 0015
- [0014 — changelog from commits](specs/decisions/0014-changelog-from-commits.md) — the rule stands (the commit body *is* the entry); the `CHANGELOG.md` a release assembled into is deleted by 0015, since there is nothing left to release
- [0015 — harness v4: retire the runtime, thin verification layer](specs/decisions/0015-harness-v4-thin-verification-layer.md)
- [0016 — tests own structure and negative space; the reviewer owns meaning](specs/decisions/0016-tests-own-structure-and-negative-space.md)

## Where deeper truth lives

- What the repo is now, and what it stopped being: ADR 0015
- The published guidance surface and how it is installed: `specs/features/guidance-system.md`, `registry.yaml`, `BOOTSTRAP.md`
- Build-time mutation instrument: `scripts/mutate.py`, driven by `CONTRIBUTING.md`
- Promotion policy: ADR 0003 — the topology and its nightly automation are kept, driven by `scripts/promotion-step.sh`
- User-facing feature surface: `README.md`; unconfirmed ideas: `specs/proposals/`
- Issues and in-flight work: the configured GitHub repository and Projects board

## Gotchas

- Drive work through the agent-led `/build <ISSUE-ID>`, or `/start → /review → /ship` when attended.
- `mypy` checks `scripts` and `templates`. There is no application package to type-check.
- Coverage measures `scripts/` — the only executable code the repo owns. Everything under `tests/unit/` reads the tracked tree instead of exercising a module.
- The gate runs one pytest stage. The Docker/non-Docker partition and the three-tier marker machinery went with the runtime.
- Long verification output may need capture to `/tmp/<file>.txt` and a final read.

## Python conventions

- `scripts/` is stdlib only and stays that way — a gate that needs a dependency to run is a gate that can fail for reasons unrelated to the tree.
- `from __future__ import annotations` at the top of every module; `mypy --strict` passes with no ignores.
- A guard asserts a property of the tracked tree (`git ls-files`), never of the working directory — an untracked worktree or stale bytecode must not read as source.
- Never use `eval`/`exec`/`pickle` on untrusted data, string-formatted SQL, `shell=True` with user input, or unvalidated paths outside their prefix. Secrets come from the environment and are never logged or committed.
