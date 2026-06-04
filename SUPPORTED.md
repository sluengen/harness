# Supported Features — v1

This file is the authoritative record of what harness v1 supports. Anything not listed here is either v1.5/v2 scope or explicitly unsupported.

## v1 — Fully supported

| Feature | Notes |
|---------|-------|
| `ClaudeAgent` dispatch | via `claude_agent_sdk` |
| Script nodes (`bash` + `python`) | `command:` or `script:` with args substitution |
| Check nodes | Python expression evaluation over state |
| Decision nodes (`actor: llm`) | LLM-gated gate; human actor is v2 |
| Worktree lifecycle (create + cleanup) | Isolated git worktree per run |
| Loop blocks (`until:` + `until_bash:`) | With `max_iterations` + `on_exhaust` |
| `$state.<field>` substitution | In `args:` and `until_bash:` |
| `$inputs.<key>` substitution | In `args:` and `until_bash:` — see AUTHORING.md §inputs |
| Per-write merge override (`merge: replace`) | Long-form `writes:` |
| Per-node retry configuration | `retry.transient.attempts` override |
| Linear webhook intake | `intake/` package; POST /webhook |
| State snapshots (per-completion) | Written after every successful node |
| Workflow-level cancellation | SIGINT + SIGTERM → graceful exit 130 |

## v1.5 — Adapters (experimental, not production-ready)

These adapters exist in the codebase but raise `RuntimeError` if used without a test `proc_fn`. They are disabled by default.

| Feature | Status |
|---------|--------|
| `CodexAgent` dispatch | Subprocess adapter exists; `proc_fn=None` raises `RuntimeError` |
| `OpencodeAgent` dispatch | Subprocess adapter exists; `proc_fn=None` raises `RuntimeError` |

Do not reference these adapters in production workflows. Use `ClaudeAgent`.

## v2 — Reserved / not implemented

| Feature | Notes |
|---------|-------|
| Human decision nodes (`actor: human`) | Schema parses; runtime raises on encounter |
| Decision pause/resume via CLI | `harness decision approve/reject` is stubbed |
| `harness init <dir>` scaffold | Not implemented |
| PyPI publish | Not implemented |
