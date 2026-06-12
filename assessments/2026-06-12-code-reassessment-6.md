# Code Steward assessment — harness — 2026-06-12 (reassessment 6)

> Filed as report #6 (not #5): an unmerged sibling PR (CAL-629, PR #78) already holds
> `2026-06-12-code-reassessment-5.md`. Renamed to avoid a merge collision on `dev`.

**Domain:** `code` · **Branch assessed:** `assess/code-2026-06-12e` off `origin/dev` @ `ef1f76f` · **Trigger:** scheduled assessment fallback (fifth code-steward pass of the day, after CAL-586–629 shipped).

**Summary:** This is the fifth code-steward pass on `dev` today and the codebase remains genuinely healthy — ruff clean, mypy clean (32 source files, 0 errors), fast suite 527 passed / 47 deselected, exit 0. All eight dimensions swept fresh against the four prior reports. One new, wholly-contained finding survives the high saturation bar: a Low-severity duplicated open-run resolution query shared by `review` and `close`. Everything else is either already filed/shipped, deliberately-excluded tested surface, or a justified split. **One Low finding. No insights.**

## Gate (run fresh this session)

| Check | Command | Result |
|---|---|---|
| Lint | `uv run ruff check .` | **All checks passed** (exit 0) |
| Types | `uv run mypy harness` | **Success: no issues found in 32 source files** (exit 0) |
| Fast suite | `uv run pytest -m 'not slow and not integration' -q` | **527 passed, 47 deselected** (exit 0) |

Note: the first gate run showed 56 failures + a `mypy` spawn error purely because the worktree's `.venv` had been created without the `dev` extra (no `pytest-asyncio`, no `mypy`). `uv sync --extra dev` then a clean re-run produced the numbers above. This is the same environment-cruft class the prior reports flagged for local gates (CODE-3 / CAL-619) — not a real failure, but worth noting that a fresh worktree needs `uv sync --extra dev` before the gate is meaningful.

---

## Findings

### CODE-1 — open-run resolution query duplicated across `review` and `close` — **Low**

- **What:** `close._resolve_open_run` and `review._resolve_open_run` are the same domain rule written twice: "locate the active run — with an explicit `run_id` match `WHERE run_id = ? AND status = 'open'`, otherwise match `WHERE worktree_path = ? AND status = 'open'`." Both implement the identical `db_path.exists()` guard, the identical `run_id`-vs-`worktree_path` branch, the identical `status = 'open'` filter, and the identical `store.connect(...) → fetchone()` shape. They differ only in the projected columns (`close` selects four — `run_id, worktree_path, base_branch, worktree_branch`; `review` selects two — `run_id, worktree_path`) and the return arity. Each docstring explicitly acknowledges the parallel: "mirroring `harness review`'s `_resolve_open_run` query style" / "mirroring `harness start`'s `_find_open_run` query style."
- **Where:**
  - `harness/cli/close.py:314-345` (`_resolve_open_run`; the two `status = 'open'` query branches at `:331` and `:337`).
  - `harness/cli/review.py:367-393` (`_resolve_open_run`; the two branches at `:382` and `:385`).
  - (`harness/cli/start.py:290-309` `_find_open_run` is the *ticket*-keyed sibling — a different query, single param, no run_id/worktree_path dispatch — so it is the cousin the docstrings name, not a third copy of this exact rule.)
- **Why:** Cross-file duplication of a load-bearing domain rule (code-quality area 2). "Which run is the active one for this verb" is the dispatch contract the gate depends on — the `status = 'open'` filter in particular must stay identical across verbs, or a verb could act on a closed/abandoned run. Two structurally-identical copies that can drift independently are a latent (if currently-dormant) inconsistency. It is **Low, not Medium**, because: both copies are unit-tested, the `status = 'open'` literal is consistent across all five `runs`-query sites checked (`grep` confirmed — `close.py`, `review.py`, `start.py`, `store.py` partial-index DDL all agree), and the projected-columns difference means a naive merge would have to be parameterised rather than a literal de-dup. It is a clean structural improvement, not a bug.
- **How:** Extract one resolver into `harness/cli/_git.py`'s sibling (or a small `harness/cli/_runs.py`) that takes the column list, e.g. `async def resolve_open_run(db_path, repo_root, run_id, columns) -> tuple | None` owning the `db_path.exists()` guard + the run_id/worktree_path branch + the `status = 'open'` filter, and have both verbs call it with their column tuple and adapt the returned row. This puts the "open run is the one with `status='open'`, found by run_id or worktree_path" rule in exactly one place. Existing `test_cli_review.py` / `test_cli_close.py` resolution tests lock the behaviour through the refactor (test-first: assert both verbs still resolve the same open run).

---

## Not flagged (checked this pass, deliberately excluded)

- **`worktree.py::_git` (async, `:80`) vs `cli/_git.py::run_git` (sync, `:35`)** — two git-invocation primitives, but a *justified* split, not duplication: `worktree.py` drives the async worktree lifecycle (`asyncio.create_subprocess_exec`, `cwd=`, returns `(rc, out, err)` tuple) while `run_git` is the synchronous verb-site primitive (`git -C` prefix, returns `CompletedProcess`). Different concurrency models and return contracts; merging them would force one caller onto the wrong shape. The sync centralization (CAL-606/610) deliberately covered the sync sites only.
- **`identity.artifacts_dir()` / `log_path()` (`identity.py:53,59`)** — no production caller, but tested (`test_identity.py`) and `artifacts_dir` is a live `BaseState` field (`schema.py:86`) tied to the SPEC §8 contract. Same exclusion reassessment-3 recorded; still correct.
- **`harness/trigger.py` (`HermesTrigger`, `agent_run_command`)** — referenced only within itself plus `test_trigger.py` and `test_hermes_demo.py`, and not wired into any verb/launcher. This is the deliberate CAL-585 Hermes-launch stand-in, documented in SPEC §4.9 (CAL-618) — a not-yet-wired demonstration entrypoint, not dead code.
- **`mypy>=2.0.0` pin (`pyproject.toml`)** — the intended single pin (CAL-602); runtime deps (pydantic 2, typer, aiosqlite, ulid-py) are minimal and current. Dependency health: clean.
- **Size / structure** — every source file is within the 500-line hard limit (largest `launcher.py` at 446); no file mixes drifted concerns. No TODO/FIXME/HACK in `harness/`.
- **CAL-629 (PR #78, `_time.py` SPEC §12 doc-cite)** — in-flight, not re-flagged per instruction.

---

## Systemic insights

None this cycle. CODE-1 is a single isolated structural de-dup, not evidence of a recurring class, and no guidance file is implicated — the existing review machinery (codex cross-checking as-built SPEC against verb code) plus the CAL-619 git-aware guard already cover the patterns that produced the earlier insights. Zero insights is the honest outcome on a fifth same-day pass of a codebase the prior four already hardened.
