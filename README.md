# Calibrate Harness

A deterministic workflow execution harness in Python. Decouples *what* gets run (orchestration, external) from *how* it runs (this harness).

> Build a deterministic execution engine, not an agent framework.

## Status

**Pre-implementation.** `SPEC.md` is the source of truth and current deliverable. Proposed repo structure, core modules, YAML schema, CLI surface, and migration plan are documented there for review before any code lands.

## Tech stack (planned)

Python 3.11+ · Pydantic 2 · Typer · Jinja2 · PyYAML · `anthropic` SDK · `openai` SDK (Ollama-compatible) · aiosqlite · pytest · ruff · uv · Docker

## Related

- **Primary consumer:** `calibrate-coffee` — pipelines for that project will be defined as YAML workflows here.
- **Design ancestry:** Inspired by [Archon](https://github.com/coleam00/Archon) (workflow concepts, worktree-per-run, event log) but is a stack-aligned greenfield rewrite, not a fork.
