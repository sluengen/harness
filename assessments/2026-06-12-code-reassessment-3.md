# Code Steward assessment — harness — 2026-06-12 (reassessment 3)

**Filed:** CAL-625 (CODE-1, Todo) · CAL-626 (CODE-2, In Progress — actioned in this same change). Both labelled `review-finding` / `source:review-finding`, priority Medium.

**Summary:** Codebase is healthy — ruff clean, mypy clean (32 source files, 0 errors), no TODO/FIXME in `harness/`, files within size limits (largest 446 lines), git helpers properly centralized. Two small, self-contained as-built-doc divergences found; both are documentation-vs-code drift in the as-built contract surface, the most fertile area for this repo.

---

## Findings

### CODE-1 — `harness worktrees cleanup --merged` doc says "main", code checks dev/main/master — Medium

- **What:** The `--merged` filter's user-facing help and the module docstring claim the branch is checked against `main`, but the implementation checks `dev`, `main`, **and** `master`. The function is even named `_branch_merged_into_main` while its own body iterates `("dev", "main", "master")`.
- **Where:**
  - `harness/cli/worktrees.py:13` — module docstring: "`--merged` — remove worktrees whose branch is fully merged into ``main``."
  - `harness/cli/worktrees.py:199` — Typer help: `help="Remove worktrees whose branch is merged into main."`
  - `harness/cli/worktrees.py:165-175` — `def _branch_merged_into_main(...)` with body `for base in ("dev", "main", "master")`.
- **Why:** As-built divergence (assessment area 9) — the documented behaviour understates the real check. For this repo `dev` is the integration branch (CONTEXT.md `branches.integration: dev`), so the broader check is correct and intentional; the docs/name are the stale part. A user reading `--help` would believe a branch merged only into `dev` (the common case here) is **not** a cleanup candidate, when in fact it is.
- **How:** Update the line 13 docstring and the line 199 help string to read "merged into `dev`, `main`, or `master`" (or "the integration/release base"). Optionally rename `_branch_merged_into_main` → `_branch_merged_into_base` so the name matches the body. Pure doc/identifier change, no behavioural edit; the existing `--merged` tests still pass.

### CODE-2 — `commands/harness.md` gate-refusal list omits `dirty_worktree` — Medium

- **What:** The agent-facing contract `commands/harness.md` documents the `close` gate-refusal `reason` values an orchestrating agent must handle, but lists only three of the four the code actually emits. `dirty_worktree` is missing.
- **Where:**
  - `commands/harness.md:85-89` — "The `reason` is one of:" then `no_run` / `no_passing_review` / `stale_review` only.
  - `harness/cli/close.py:74` — `RefusalReason = Literal["no_run", "dirty_worktree", "no_passing_review", "stale_review"]` (code emits four).
  - `harness/cli/close.py:36-37, 44, 207` — `dirty_worktree` documented in the verb docstring and raised in the gate.
  - `SPEC.md:234` (§4.4) — as-built spec correctly lists all four including `dirty_worktree`.
- **Why:** As-built divergence (area 9). `/harness run` instructs the agent to act on the refusal `reason` and "do not work around it". If `close` refuses with `dirty_worktree` (uncommitted edits in the worktree — a real, reachable refusal, locked by `test_cli_close.py::test_dirty_worktree_refused_when_uncommitted_edits`), the orchestrating agent reading only `commands/harness.md` has no documented handling path and may misclassify it as an "unexpected error". SPEC §4.4 and the code agree on four reasons; this contract doc is the lone outlier.
- **How:** Add a fourth bullet to `commands/harness.md:85-89`, e.g. "**`dirty_worktree`** — the worktree has uncommitted changes; what would merge was never reviewed. Commit (or discard) the edits, re-run `harness review` to bind a fresh pass to the new HEAD, then close again." Insert it before `no_passing_review` to match the code's enumeration order.
- **Actioned (CAL-626):** fixed in `commands/harness.md`, `SPEC.md:94`, and — folded in during review after the reviewer flagged the identical omission — `README.md:43` and `README.md:154`, so every as-built doc surface listing the refusal-reason set now matches the four-reason `RefusalReason` literal. `specs/cli.md` is left alone (banner-marked superseded).

---

## Not flagged (checked, deliberately excluded)

- **`identity.artifacts_dir()` / `identity.log_path()`** — unused by production code (vestigial from the retired engine's per-run identity layout, SPEC §8), but they have explicit unit coverage (`tests/unit/test_identity.py`) and `artifacts_dir` remains a `BaseState` field (`harness/state/schema.py:86`). Tested, documented public surface tied to the SPEC §8 contract — does not meet the "exports nothing imports" dead-code bar.
- **`_status_porcelain` (close.py:364)** — single local helper, not duplicated; `run_git`/`rev_parse_head` are already centralized in `harness/cli/_git.py` (CAL-610). No cross-file duplication remaining.
- **Superseded specs** (`specs/cli.md`, `hermes-orchestration.md`, engine-*.md) — explicitly banner-marked superseded in `SPEC.md` §index; their drift from current code is by design and out of scope for as-built cross-check.

---

## Systemic insights

None. Both findings are isolated one-line doc edits, not a recurring pattern across the codebase, and no guidance file is implicated. Zero insights is a legitimate outcome here — the as-built/code coherence machinery (codex reviewing SPEC prose against verb code) is already catching divergence well; these two are the residue in surfaces a per-change reviewer would not have had the diff to catch.
