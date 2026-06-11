# Code assessment — 2026-06-12

**Domain:** code (periodic code-steward pass, via `/assess`)
**Branch:** `assess/code-2026-06-12` (based on `origin/dev`)
**Verification gate (fresh):** `bash scripts/verify.sh` → **514 passed, exit 0** (ruff → mypy → pytest → CLI smoke, run this session; output at `/tmp/verify_out.txt`).
**Scope guard:** the 2026-06-11 cluster (CAL-586…603) is substantially shipped on `dev` — verified in git log (`7d5afe8` close dirty-gate, `09cf92d`/`c5d8d33` cancel redefinition, `d343953` drop `current_node`, `b051efb` worktree single-source, `59a92af` `rev_parse_head` dedup, `e1ef3ce` mypy pin, README/CONTEXT/spec banners). This pass does **not** re-file any of those, nor the parked `intake/` retirement (CAL-601) or the docs/surface retirement-completeness guard (CAL-603).

## Summary

**The verb core is healthy and the 2026-06-11 backlog has largely landed; the one new pattern worth filing is a pocket of engine-era dead code in `query.py` that the previous `current_node` cleanup (CAL-589) missed — and a unit test manufactures the data that keeps it green.** The package is clean of `shell=True`/`eval`/`pickle`, SQL is parameterized, the launcher socket allowlist is tight, the close gate now refuses a dirty worktree, and `cancel` was redefined to the verb model. Findings this cycle are small: one dead-code pocket (Medium), one structure-drift file over the hard size limit (Low), one trivial dead variable (Low), and incidental git-subprocess plumbing duplication that does **not** clear the sync-critical bar (Low). No security, dependency, or architecture-divergence findings beyond what is already filed.

**Findings:** 0 Critical · 0 High · 1 Medium · 3 Low. **Insights:** 1.

---

## Findings

### CODE-1 — dead `pr_url` / `report_path` artifact enrichment, locked green by a synthetic-state test — **[Medium]**

- **What:** `harness status --json` derives `artifact_paths` from `_ARTIFACT_KEYS = ("worktree_path", "worktree_branch", "pr_url", "report_path")`. The state schema `BaseState` (with `extra="forbid"`) declares **only** `worktree_path` / `worktree_branch` — there is no `pr_url` or `report_path` field, and no verb writes them. Validation would *reject* either key, so `state.get("pr_url")` / `state.get("report_path")` can never be populated in a real run. The two keys are engine-era residue that the CAL-589 `current_node` cleanup left behind. Worse, `test_status_json_artifact_paths_populated_from_state` seeds a **raw `state_json` blob** containing `"pr_url": "…"` straight into the DB column (`_seed_run`, bypassing `BaseState`) and asserts it surfaces — so a CI-green run vouches for a field the live system cannot produce. This is the exact anti-pattern CAL-600 (CODE-INSIGHT-3, 2026-06-11) names.
- **Where:** `harness/cli/query.py:102-107` (`_ARTIFACT_KEYS`), `:110-120` (`_extract_artifact_paths`); schema `harness/state/schema.py:79-88` (no `pr_url`/`report_path`, `extra="forbid"`); locking test `tests/unit/test_cli_query.py:693-713` (injects `pr_url` at `:701`).
- **Why:** Dead code disguised as live by a test that fabricates events/state no production path emits — false confidence, and a maintenance trap (a reader assumes `pr_url` is a live observable). Violates `code-quality` Part B (dead surface) and the CAL-600 principle that tests must assert against what live verbs write.
- **How:** Drop `pr_url` and `report_path` from `_ARTIFACT_KEYS` (leaving `worktree_path` / `worktree_branch`, which `start` genuinely writes), and rewrite the test to inject only schema-valid artifact fields. If Hermes observability genuinely needs PR/report surfacing later, add the fields to `BaseState` and have a verb write them first — then the enrichment is real.

### CODE-2 — `query.py` over the 500-line hard size limit, mixing four command concerns — **[Low]**

- **What:** `query.py` is 560 lines (hard limit 500) with no in-file justification comment. It holds four distinct read-command concerns — `status_command` + its enrichment helpers (`_fetch_enriched_status`, `_derive_failure_retryable`, `_extract_artifact_paths`), `events_command`, `logs_command` + the `--follow` poller (`_follow_logs`), and `runs_command` + its two fetchers (`_fetch_recent_runs`, `_fetch_failed_runs_grouped`). They share only `_resolve_db_path` and `_safe_json_loads`.
- **Where:** `harness/cli/query.py` (whole file, 560 lines); concern seams at `:218` (`status_command`), `:354` (`events_command`), `:392` (`logs_command`), `:513` (`runs_command`).
- **Why:** `code-quality` Part B: a file past the hard limit must be split or carry a justification comment; this one does neither, and the four concerns are independently testable (separate `test_cli_*` slices already exist). Low rather than Medium because the concerns are read-only and cohesively "query the ledger".
- **How:** Split into `query_status.py` (status + enrichment), `query_events.py` (events/logs + follow), and `query_runs.py` (runs), with the two shared helpers in a small `_query_common.py`; keep the existing command callables so `cli/__init__.py` registration is unchanged.

### CODE-3 — dead `node_info` variable in `runs --failed` output — **[Low]**

- **What:** `runs_command` builds each failed-run line with a `node_info = ""` local that is always the empty string and is concatenated into the f-string for no effect — a leftover from the engine-era per-node grouping (the `node` concept was retired with the engine).
- **Where:** `harness/cli/query.py:536` (`node_info = ""`), interpolated at `:539`.
- **Why:** Dead code; reads as if a node label might appear, but it never can. Minor `code-quality` Part B cleanup.
- **How:** Delete the `node_info` assignment and the `{node_info}` interpolation.

### CODE-4 — git-subprocess invocation duplicated across five sync sites — **[Low]**

- **What:** The `subprocess.run(["git", "-C", str(cwd), *args], check=False, capture_output=True, text=True)` shape with a returncode-check-then-raise epilogue is hand-written in five sync helpers (plus an async twin `_git` in `worktree.py`). Seven `# noqa: S603, S607` git-subprocess sites total.
- **Where:** `harness/cli/_git.py:32` (`rev_parse_head`), `harness/cli/close.py:372` (`_status_porcelain`) and `:405` (`_merge_and_push._run`), `harness/cli/start.py:390-405` (`_cleanup_worktree_sync`, three calls), `harness/cli/worktrees.py:107,176,191`; async variant `harness/worktree.py` `_git`.
- **Why:** `code-quality` Part B "third strike" duplication. **It does *not* clear the sync-critical bar** (assessment-craft §2): the one load-bearing git call — the HEAD read the gate binds to — was already centralized into `_git.py:rev_parse_head` (CAL-606), and the remaining copies differ deliberately (raise `GitError` vs `_CloseError` vs best-effort silent cleanup; sync vs async). So this is incidental plumbing, hence **Low**, and arguably acceptable as-is.
- **How:** Optional: hoist a single sync `run_git(cwd, *args, *, on_error) -> str` into `cli/_git.py` that the raising callers share (cleanup stays best-effort and opts out). Only worth doing on the next touch of two of these files; not urgent.

---

## Systemic insights

### CODE-INSIGHT-1 — the CAL-600 "no synthetic data" principle needs an enforcement seam, not just a skill line — *(evidence: CODE-1)*

- **Edit:** CAL-600 already records (2026-06-11) the principle "tests must not synthesize data no live path produces" as a `code-quality` / `test-driven-development` addition. CODE-1 shows the principle did not prevent recurrence on its own: `test_status_json_artifact_paths_populated_from_state` was written *after* that insight's evidence (CAL-589's `current_node` cleanup) yet still seeds `pr_url`. The concrete, testable seam: extend `tests/unit/test_engine_retired.py` (the existing retirement-property guard) with an assertion that every key in `harness/cli/query.py:_ARTIFACT_KEYS` is a declared field of `BaseState` — i.e. the enrichment surface cannot list a field the schema forbids. That converts "reviewer must remember the principle" into a failing test.
- **Why / evidence:** CODE-1 — a `_ARTIFACT_KEYS` entry (`pr_url`/`report_path`) with no schema field and no writer, kept green only because a test fabricates it. One property test would catch this class (dead enrichment keys) at the source. Caps at one insight this cycle; the finding count is low and a second insight would be padding.

---

## What is genuinely strong

- **The 2026-06-11 backlog landed cleanly.** The close gate now refuses a dirty worktree before any side effect (`close.py:189-211`, `_status_porcelain`); `cancel` was redefined to the verb model with an explicit in-flight allowlist and an atomic status-flip + `workflow_failed` event (`cancel.py`); the worktree layout convention is single-sourced through `harness.identity.WORKTREES_SUBDIR`; `rev_parse_head` is shared in `cli/_git.py`; the duplicate mypy pin is gone (`[dependency-groups]` removed).
- **`workflow_failed` enrichment is now live, not dead.** The `failure_reason` / `failure_retryable` branches in `query.py` that CAL-589 examined are reachable: `cancel` is the live emitter of `workflow_failed` (`query.py:19-22` documents this honestly). Only the `pr_url`/`report_path` *artifact* keys remain dead (CODE-1).
- **Security posture holds.** No `shell=True` / `os.system` / `eval` / `exec` / `pickle`; all SQL parameterized; the launcher control socket exposes a fixed op set with a per-op param allowlist and resolves the repo against a realpath allowlist before any `docker run` (`launcher.py:32-48,62-67`).
- **Test suite is real.** 514 passing, `--strict-markers`, no `xfail`; the gate-enforcement and context-economy properties are asserted by tests that would fail if the feature broke.

---

## Out of scope (already owned — not re-filed)

| Observation | Owner |
|---|---|
| `intake/linear_webhook.py` shells out to the deleted `harness run`; `test_linear_webhook.py:384` asserts the broken `["harness","run","build",…]` argv | **CAL-601** (intake retirement, parked) |
| Docs/CLI-surface retirement-completeness grep guard | **CAL-603** |
| SEC-1 live `LINEAR_API_KEY` in working-tree `.env` | **CAL-597** (surface-to-human) |
