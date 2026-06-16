# Code assessment (reassessment) — 2026-06-16

**Steward:** steward (`code` scope) · **Base:** `dev` @ `30e191c` · **Gate:** PASS — 968 tests, ruff clean, mypy clean, CLI smoke clean.

## Why this pass

The earlier 2026-06-16 assessment (`2026-06-16-code.md`) was taken at `dev` @ `19404cd` and covered the CAL-712..719 refactor batch. Since then the **stale-run-reclamation** workstream (CAL-734..739) landed — 34 files, +3537/−133: the new `harness/cli/reclaim.py` (440), `harness/cli/checkpoint.py` (200), the shared `harness/cli/_abandon.py` (142), `harness/reclaim_marker.py` (80), +254 in `harness/linear.py` (the CAL-734 primitives), the `start --resume` path, and the `cancel.py` → `_abandon.py` refactor. This pass concentrated on residue that batch could leave — duplicated ledger/Linear logic, dead references, weak tests, and architecture drift in the new verbs.

## Verdict

The reclamation workstream is **clean** and, notably, *consolidating* rather than duplicating:

- `cancel.py` shed 91 lines by extracting the ledger-abandon transaction into the shared `harness/cli/_abandon.py`, which both `cancel` and `reclaim` now use — one home for the status-flip + `workflow_failed` event invariant.
- `_transition` in `harness/linear.py` backs all three state transitions (`in_progress` / `done` / `unstarted`); the new revert reuses it rather than re-implementing.
- The `--stale` sweep reuses the single-target `--ticket` reclaim path per ticket (no second reclaim implementation).
- `harness/reclaim_marker.py` single-sources the reclaim-comment contract so its writer (`reclaim`) and reader (`start --resume` / `fetch_resume_branch`) cannot drift, with `test_reclaim_marker.py` pinning the round-trip.

Test coverage is strong (968 tests; new `test_cli_reclaim.py`, `test_cli_checkpoint.py`, `test_linear_reclaim_primitives.py`, `test_reclaim_marker.py`, `test_cli_start.py` resume cases). The new verbs route every git/Linear mutation through a verb (no raw state-transitions in the loop), preserving the audit-trail invariant.

## Findings

**One finding, actioned in the same change** (so it is recorded here and in its PR rather than left open for a later run).

### CODE-1 — Live source cites the retired `build-codex.yaml` (Low)

- **What.** Two docstrings in `harness/linear.py` cross-referred a reader to `build-codex.yaml`: line 17 (*"matching the build-codex.yaml logic"*) and line 415 (*"Mirrors `build-codex.yaml`"*).
- **Evidence.** `build-codex.yaml` was deleted with the deterministic engine (CAL-574); `find . -name build-codex.yaml` returns nothing, and `test_engine_retired.py::test_build_yaml_removed` already asserts the file is gone. The two cites predate the reclamation work (`git blame` → the original `harness start` commit and CAL-641); they survived because the engine-retirement guard checked the file's *existence* but not textual *citation* of it. This is exactly the dangling-cite-to-a-retired-artifact class that `test_retired_spec_cites.py` (CAL-633) eliminated for retired SPEC sections — *"a cite into retired prose is worse than no cite at all."*
- **Why it matters.** A reader following the docstring to verify the state-transition logic against its named source finds a file that no longer exists. Low severity (doc-only, no behavioural impact), but a real coherence gap in a guarded class.
- **Fix (shipped in this change).** Both docstrings made self-contained (the fallback logic is fully described without the dead anchor), and `test_engine_retired.py` AC-2 extended with `test_no_live_harness_source_cites_a_retired_build_yaml` — a tracked-tree sweep that fails if any live `harness/**/*.py` names `build.yaml` / `build-codex.yaml`. This closes the gap the file-existence guard left, so the class cannot reappear.

## Systemic insights

No new insight this cycle. The fix *applies* an existing insight rather than proposing a new one: the codebase already recognises "live source must not cite a retired artifact" as a structural-guard class (`test_retired_spec_cites.py`, CAL-633). The only gap was that the engine-retirement guard checked file existence but not citation; extending AC-2 brings `build*.yaml` into parity with the retired-SPEC-section guard. No further guard is warranted.

## Dimensions examined (clean)

- **Size/structure drift** — new modules are well within limits (`reclaim.py` 440, `checkpoint.py` 200, `_abandon.py` 142); `linear.py` grew to host the CAL-734 primitives and carries a `size:` justification (the CAL-731 embed-allowlist requires every Linear GraphQL op to live in this one client).
- **Cross-file duplication** — the opposite: `cancel.py` → `_abandon.py` extraction, `_transition` shared across three transitions, `reclaim_marker` single-sourcing the comment contract, the sweep reusing the `--ticket` path. No load-bearing pattern duplicated 2+ places.
- **Dead code** — no imports to retired modules; `_RECLAIM_REASON` / `_CANCEL_REASON` / `CANCELLABLE_STATUSES` are all live. `ruff` reports zero unused imports.
- **Stale TODOs** — none in the changed surface.
- **Test health** — 968 pass; the new verbs' ACs each have tests (idempotent no-op, terminal-status refusal, revert-only-when-no-local-run, resume-fallback-on-unfetchable-branch, checkpoint emits no review/close event). No weak assertions in the changed areas.
- **Cross-cutting security** — the `--repo` workspace allowlist is still enforced on every verb via `cli/_repo.py`; `checkpoint`/`reclaim` use list-form git (no `shell=True`); no string-built SQL (the `_abandon` UPDATE is parameterised and guards on the observed status for optimistic concurrency); secrets stay in env.
- **Architecture drift** — `start --resume` correctly decouples the worktree's git start-point from the recorded `base_branch` (merge target), so `close`'s HEAD-bound gate stays safe from double-merge (CAL-739 design). Every git/Linear mutation routes through a verb. No layer boundary crossed.
- **Dependency health** — unchanged from the morning pass; all production and dev dependencies at current releases.
