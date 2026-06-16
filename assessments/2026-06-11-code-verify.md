# Code assessment — 2026-06-11 (verification + new-drift pass)

**Domain:** code (post-fix verification + new-drift hunt)
**Branch:** `claude/kind-kepler-363159` (carries the merged `dev` tree post 2026-06-11 fixes)
**Preceded by:** `assessments/2026-06-11-code.md` (comprehensive adversarial pass, filed CAL-586–603)
**Verification gate (fresh, this session):** first run: 1 failed (intermittent socket flake), exit 1. Second run: 464 passed, exit 0. Third run: 464 passed, exit 0. See "Gate result" below.

## One-line summary

All nine shipped fixes hold — the gate is genuinely clean — and two new low-severity findings were identified (a load-dependent socket test flake, and duplicated `_rev_parse_head` across two verb modules), neither of which compromises correctness or security.

---

## Verification gate result

```
bash scripts/verify.sh     (run 1): 1 failed, 463 passed — exit 1
bash scripts/verify.sh     (run 2): 464 passed — exit 0
bash scripts/verify.sh     (run 3): 464 passed — exit 0
uv run pytest              (×10 isolated socket-test runs): 0 failures
```

The single failure (`tests/integration/test_launcher_socket.py::test_full_verb_cycle_over_the_socket`) is a pre-existing load-sensitive race (see CODE-7 below). It did not recur on any subsequent run. The gate is functionally passing.

---

## Half-1 — Verification status

| Item | Shipped? | Tested? | Notes |
|------|----------|---------|-------|
| **CAL-586 (CODE-1)** — `close` dirty-worktree bypass | Yes | Yes | Refusal at `close.py:204–210`, precedes `_merge_and_push` (step 6); tests at `:300` (untracked file) and `:330` (modified tracked file). Gate ordering confirmed: dirty check is step 3, merge is step 6. No auto-commit path remains anywhere in `_merge_and_push`. |
| **CAL-590 (CODE-5)** — worktree layout single-sourced | Yes | Yes | `WORKTREES_SUBDIR` defined in `harness/identity.py:26`; `worktree.py` imports it and exposes `worktree_path()` helper; `cli/worktrees.py` imports from `identity` at line 30; `cli/start.py` uses `WorktreeNode` which internally calls `worktree_path()`. `tests/unit/test_worktree_convention.py` pins all three derivations converge. |
| **CAL-591 (DOC-1)** — README.md rewritten to verb model | Yes | N/A (doc) | No engine references remain; verb model described end-to-end. |
| **CAL-592 (DOC-2)** — CONTEXT.md body rewritten | Yes | N/A (doc) | Body matches verb model; `run:` quick-ref now reads `harness start <ISSUE-ID> → review → close`. No broken command. |
| **CAL-593 (DOC-3)** — supersede banners on six engine specs + cli.md | Yes | N/A (doc) | All seven files carry a dated `> **Superseded 2026-06-11**` banner at line 3. Verified: `engine-executor.md`, `engine-loop.md`, `ai-node.md`, `script-node.md`, `workflow-schema.md`, `build-workflow.md`, `specs/cli.md`. |
| **CAL-594 (DOC-4)** — `/harness build-workflow` + AUTHORING.md retired | Yes | N/A (doc) | `commands/harness.md` has no `build-workflow` section. `AUTHORING.md` gone. `skills/workflow-authoring.md` gone. `workflows/` and `contracts/` directories gone. |
| **CAL-595 (DOC-5)** — stale doc refs fixed | Yes | N/A (doc) | (a) `CONTEXT.md` gate step: already correct on `dev` per commit message. (b) `RELEASING.md`: `harness validate workflows/build.yaml` removed; gate checklist aligns to real `verify.sh`. (c) `SPEC.md §11`: `harness close` added to verb surface; "future" framing on `close` removed. |
| **CAL-596 (ADH-1)** — D5 routing wording scoped to run-lifecycle | Yes | N/A (spec) | `specs/architecture-principles.md:33` now reads "Every *run-lifecycle* git and ticket mutation goes through a verb." Scope qualifier present; agent-led backup flow explicitly carved out in the Consequences note at line 52. |
| **CAL-599 (CODE-INSIGHT-2)** — self-enforcing-guardrails principle added | Yes | N/A (spec) | `specs/architecture-principles.md:27–29` has "### Self-enforcing guardrails" section; `pyproject.toml` front-matter confirms `last_updated: 2026-06-11  # CAL-599`. |
| **CAL-602 (CODE-6)** — duplicate mypy pin collapsed | Yes | N/A (config) | `pyproject.toml` has exactly one `mypy` entry: `mypy>=2.0.0` in `[project.optional-dependencies].dev` at line 24. The `[dependency-groups]` section is gone. Confirmed with grep — no second occurrence. |

---

## Half-2 — New findings

### CODE-7 — Load-sensitive socket test race in `test_launcher_socket.py` — **[Low]** · `CAL-605`

**What:** `_request()` (the test's socket helper) calls `client.shutdown(socket.SHUT_WR)` after `sendall`, then reads the response. Under load the server's `_ControlRequestHandler.handle()` can complete (and the OS can reclaim the fd) before the client reaches `shutdown()`, yielding `OSError: [Errno 57] Socket is not connected`. The race is real — it triggered once in the first full-suite run and produced a gate failure (exit 1).

**Where:** `tests/integration/test_launcher_socket.py:63` — `client.shutdown(socket.SHUT_WR)` in `_request()`. The race is triggered in `test_full_verb_cycle_over_the_socket` on the `"docker"` op (the last request in the cycle), which the server resolves instantly as `unknown_operation` and closes.

**Why it matters:** The gate is supposed to be deterministic. A sporadic exit 1 on a green tree wastes review time, erodes trust in the gate, and is particularly sharp here because the harness's own rule is "no completion claim without fresh gate evidence." A flaky gate undermines that principle from the inside.

**How to fix:** Remove the `shutdown(SHUT_WR)` call; it is not necessary for reading a response (the server writes and closes). Replace with just `recv` in a loop until EOF — the server closes the connection after writing, which already signals EOF to the reader. Alternatively wrap the `shutdown()` call in `try/except OSError: pass`.

---

### CODE-8 — `_rev_parse_head` duplicated across `review.py` and `close.py` — **[Low]** · `CAL-606`

**What:** Identical git-HEAD-reading logic appears as a private function in two verb modules. The implementations differ only in which module-private exception class they raise (`_ReviewError` vs `_CloseError`).

**Where:**
- `harness/cli/review.py:398–412` — `def _rev_parse_head(worktree_path: Path) -> str`
- `harness/cli/close.py:366–380` — `def _rev_parse_head(worktree_path: Path) -> str`

Quoted evidence — both are byte-for-byte identical except the exception class:
```python
# review.py:398
raise _ReviewError(f"git rev-parse HEAD failed for {worktree_path}: ...", 1)
# close.py:366
raise _CloseError(f"git rev-parse HEAD failed for {worktree_path}: ...", 1)
```

**Why it matters:** This is a domain-rule helper (the gate binds to HEAD SHA) duplicated across 2 load-bearing modules — at the 2+ threshold for domain rules. A change to the git invocation (e.g. `-z` for NUL-terminated output, or adding `--verify`) needs to land in both files. The `CAL-586` fix that introduced `_status_porcelain` into `close.py` also created a third git-helper in that file, increasing the surface that diverges from `review.py` over time. The natural home is `harness/cli/_git.py` (or a thin `_git_helpers.py`) re-exported by both verbs.

**How to fix:** Extract to `harness/cli/_git.py` with a `rev_parse_head(worktree_path: Path) -> str` that raises a plain `RuntimeError` or a new module-level `GitError`; callers re-raise as their own verb-specific error. This is a refactor, not a behaviour change — the existing tests cover both callers and remain valid.

---

## Systemic insights

No new systemic insights warranted. CODE-8 is consistent with the pattern already captured in CODE-INSIGHT-2 (a verb helper self-enforces; extracting shared helpers is the enabling mechanism). The existing guidance is sufficient.

---

## Still open / tracked (parked — not re-filed)

- **CAL-587** (cancel vestigial) — decision-parked
- **CAL-589** (`query.py` dead engine-era branches) — decision-parked
- **CAL-597** (SEC-1 live key in `.env`) — surface-to-human, no self-action
- **CAL-600** (test-synthesis principle) — guidance-locked, awaits `/update-guidance`
- **CAL-601** (intake shells to deleted `harness run`) — decision-parked
- **CAL-603** (retirement-testable docs assertion) — coupled to CAL-601, parked
