# Code reassessment (e) — 2026-06-13

**Steward:** code-steward · **Base:** `origin/dev` @ `c460ac5` · **Gate:** PASS (598 passed, `scripts/verify.sh` clean)

## Summary

Zero new findings. This is the fifth+ code assessment in two days; the actionable backlog of dead code, duplication, and as-built drift has been shipped (CAL-610/629/632/635/637/638/640/641/644) or is decision-parked (CAL-633/636 §-cite cluster). A full pass across all eight dimensions surfaced no genuinely-new, wholly-contained code finding. The structural patterns a reviewer would flag once (rollback handlers, gate logic, security checks) are already centralized and well-documented. Calling zero is the correct, expected outcome here — not a gap in the pass.

## Gate result

`bash scripts/verify.sh` → **PASS**. ruff clean, `mypy harness` clean, **598 passed in 56.33s**, CLI smoke (`harness 0.1.0`) ok. No async false-failures: `verify.sh` runs under the dev extra with `pytest-asyncio` present, so the host-`uv run pytest` caveat in CONTEXT.md did not apply this run. Output captured at `/tmp/verify-e.txt`.

## Findings

None.

The dimensions examined, with the evidence that each is clean:

1. **Size / structure drift.** Largest module is `harness/launcher.py` (446 lines) — under the 500 hard limit, single concern (the narrow control-socket protocol; all symbols `build_verb_argv` / `_verb_command` / `ControlServer` / socket handlers serve launch). `worktree.py` (410) is one concern (git-worktree lifecycle) with one internal `_git` helper. No file past the hard limit; no too-long file mixing concerns.
2. **Cross-file duplication.** The git-invocation primitive was hoisted to `harness/cli/_git.py:run_git` / `rev_parse_head` (CAL-606/610). `worktree.py`'s `_git` is async (`create_subprocess_exec`) where `_git.py` is sync (`subprocess.run`) — a justified split, not duplication. The query commands share `_query_common.py`. No load-bearing pattern repeated three+ times without a home.
3. **Dead code.** `harness/trigger.py` (the Hermes-trigger stand-in, CAL-585) is imported only by tests, but it is a documented reference implementation with its own unit + integration suite (`test_trigger.py`, `test_hermes_demo.py`) and a spec home (`hermes-orchestration.md`) — deliberate surface, not dead. Orphaned `.pyc` files from the retired engine (`validate`/`decisions`/`run`/`_workflows`, `test_engine_retry`) exist only in local gitignored `__pycache__` dirs (0 tracked `.pyc`), so they are not part of the repo surface.
4. **Stale TODOs.** None. `grep TODO/FIXME/XXX/HACK` over `harness/` returns nothing.
5. **Test health.** No `assert True` / pass-only tests. Unit tests do not reach a real network/Linear (the lone `urllib` hit is a stale `.pyc`, not source). The CLI surface is locked by `test_cli_surface_locked.py`; the gate logic and worktree ACs have measuring tests. `mypy tests` reports 9 errors — but tests are deliberately outside the gate's `mypy harness` scope (`scripts/verify.sh:10`) and the test-mypy backlog is a documented, excluded gotcha. Not actionable as a CODE finding.
6. **Cross-cutting security gaps.** The workspace allowlist check is centralized through one adapter (`harness/cli/_repo.py:resolve_repo_root_or_exit`), used identically by `start` / `review` / `close`. The close gate (start-exists + HEAD-bound `verdict=pass`) lives only in `close.py`. No repeated *missing* check; the launcher's param-allowlist design makes mount/image/privilege injection inexpressible at the protocol boundary. No new gap.
7. **Architecture drift.** The `except Exception` handlers in `start.py` / `close.py` / `review.py` are documented rollback / best-effort blocks (each comments the priority of the original error) — not swallowed errors. Layer boundaries hold: transport (`cli/`) → domain (`worktree.py`/`linear.py`/`launcher.py`) → data (`state/store.py`). The CLI surface and SPEC §4/§11 still match (locked by test). The known retired-§-cite divergence is the parked CAL-633/636 cluster — evidence-only, not re-filed.
8. **Dependency health.** Four runtime deps (`pydantic>=2.5`, `typer>=0.9`, `aiosqlite>=0.19`, `ulid-py>=1.1`) — minimal, each earns its keep. No outdated/security flag of note.

## Systemic insights

No insights this cycle.

One routing observation (not a CODE finding — CONTEXT.md coherence is `system-steward`'s remit per code-steward.md boundary): **CONTEXT.md:91 states "The 89 test-file mypy errors are a known backlog" but the current `mypy tests` count is 9.** The stale magnitude could mislead a future agent into thinking the test-type backlog is an order of magnitude larger than it is. If a steward touches that gotcha line, refresh the number or drop the specific count. Surfaced for routing to system-steward; deliberately not filed as CODE.
