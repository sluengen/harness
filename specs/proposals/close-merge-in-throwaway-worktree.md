<!-- guidance:template-proposal@0.1.2 -->
---
proposal: close-merge-in-throwaway-worktree
status: superseded   # draft | under-decision | accepted | shipped | rejected | split
date: 2026-07-18
related: [CAL-1154, CAL-1151]
---

# Proposal: close merges in a throwaway worktree, not the main checkout

***Superseded 2026-08-15** by [ADR 0015](../decisions/0015-harness-v4-thin-verification-layer.md) — the `close` verb whose merge step this reshapes was deleted with the runtime, and nothing replaced it: integration is plain git driven by `/ship`. Kept for the audit; nothing below describes current behaviour.*

> Move `close`'s integrate-and-merge off the shared main checkout into a disposable worktree, so the merge cannot strand the checkout and two concurrent closes cannot collide — and settle the one contract this forces: what happens to the local `<base>` branch the other verbs read.

## Problem / motivation

`close` merges the run branch into the base branch **inside the main checkout**: `git checkout <base>` → `git fetch` → `git merge --ff-only FETCH_HEAD` → `git merge --no-ff <run-branch>` → `git push` (`harness/cli/close.py`, `_merge_and_push` at line 541; caller is `_run_close` step 6). The main checkout is shared, mutable state that **no gate conjunct covers** — the gate validates the *run worktree*, not the checkout the merge lands in.

CAL-1151 hardened the edges of this shape: it refuses to start the merge when the base checkout is not merge-safe (`reason=dirty_base_checkout`), always restores a merge it started, and reports any residue it could not clear. That closes the *observed* failure. It does not remove the underlying shape — a verb that mutates the main checkout to test mergeability is the root of the class.

Concurrent ticks are now real. On 2026-07-17 tick #34 landed CAL-1144 on `dev` while the CAL-1140 session was mid-run and the two collided. Two `close` runs merging in the same working tree is undefined behaviour that no amount of edge-hardening fixes: with CAL-1151 in place the second one refuses cleanly rather than corrupting, but "refuses" still means a **wedged tick** a human or a retry has to clear. A merge performed in a throwaway worktree cannot touch the main checkout at all, so the guarantee becomes **structural rather than defended**: no shared tree to strand, no precondition to check, no restore that can fail.

The reason this needs a proposal rather than a `/start` is that moving the merge off the main checkout breaks an invariant three verbs quietly depend on, and one of the three is guarded by a **locked contract**. That coupling — not the worktree mechanics — is the decision.

**The invariant that breaks.** Today `close` keeps **local `<base>` == `origin/<base>`** as a side effect of merging in the main checkout. Two readers depend on it:

- **`start`** bases the run worktree off the *local* branch name with **no fetch** (`git worktree add -b <branch> <path> dev`; `harness/cli/start.py`, `harness/worktree.py`). If local `dev` lags `origin/dev`, every new run starts from a stale tree — the builder writes, and is gate-reviewed, against out-of-date code.
- **`worktrees cleanup --merged`** checks `git merge-base --is-ancestor <branch> <local base>` (`harness/cli/worktrees.py`). A branch merged into `origin/dev` but not local `dev` reads as *not* merged, so the `--merged` net under-reclaims (conservative direction, but wrong).

Once the merge moves off the main checkout, local `<base>` is **no longer advanced by close**, and advancing it afterward is **not possible while `<base>` is checked out in the main tree** — which it always is in the harness's own routine (main sits on `dev`). Git refuses `branch -f <base>`, `fetch origin <base>:<base>`, and any ref move on a checked-out branch, because moving the ref without updating that working tree leaves the tree inconsistent with HEAD, and updating the tree is exactly the byte-for-byte mutation the change exists to forbid. This is fundamental, not an implementation gap. So the invariant cannot be preserved as-is: either the readers move to `origin/<base>`, or the advance moves to a component that owns the main checkout.

## Options

The worktree mechanics themselves are not in question — `harness/promotion.py` already merges in a `.worktrees/harness/` throwaway based on `origin/<to_branch>` (`create_promotion_worktree` → `attempt_merge` → `abort_merge` → `teardown_worktree`), and `close` should mirror that pattern. The decision is **AC-3: how the local-`<base>` readers stay correct.**

**Option 1 — readers move to `origin/<base>`.** `close` pushes to `origin/<base>` from the throwaway worktree; that push updates the local `refs/remotes/origin/<base>` tracking ref on the same machine **with no new fetch**, so `origin/<base>` is current for the next reader immediately. `start` bases off `origin/<base>` when it resolves, falling back to local `<base>` (mirroring the existing `resolve_base_branch` chain, so offline/no-origin repos and much of the test suite still work); `worktrees cleanup` checks ancestry against `origin/<base>` likewise. · *Trade-offs:* changes `start`'s base-resolution contract (local → origin) and carries **wide existing-test impact** — many `start` tests assume a local base, and the `origin`-present-but-stale-tracking-ref path needs the fallback exercised. But it is the only option that fixes *both* the routine and interactive use, and the network worry evaporates because close's own push keeps `origin/<base>` current.

**Option 2 — move the local-base advance into the routine pre-flight.** `close` stays purely in the throwaway worktree; `/harness routine build`'s pre-flight fast-forwards local `<base>` to `origin/<base>` in the main tree (`git -C <main> merge --ff-only origin/<base>` — safe because the routine owns main and expects it clean on `<base>`). `start` and `cleanup` are untouched. · *Trade-offs:* smaller blast radius, but it fixes only the routine. An **interactive** `/harness run` close (no routine pre-flight) leaves local `<base>` lagging, so an interactive builder's next `start` is stale — the bug simply relocates to the attended path.

**Option 3 — document the lag.** Keep the readers on local `<base>` and accept it lagging `origin/<base>`, recording the consequence. · *Trade-offs:* the lag **grows** every close, so builders start from an increasingly stale tree — a compounding correctness regression, not an acceptable "recorded consequence." Rejected.

## Recommendation

**Option 1 — ratified (Scott, 2026-07-18).** It is the only option that makes the guarantee hold for *both* the unattended routine and interactive use, and its apparent weakness — needing the network — is illusory: close's push updates the local tracking ref, so `origin/<base>` is authoritative on the same machine without a fetch. It costs a `start`-contract change and a test migration, but that migration is doing real work — it removes the last place a reader silently trusts a branch the merge no longer advances. Option 2 leaves a live staleness bug on the interactive path, which is exactly the "fixed the routine, not the shape" trap this proposal exists to avoid; Option 3 compounds. This aligns with `engineering-principles`: the structural guarantee (no shared tree to mutate) beats the defended one (a precondition + restore that can still fail), and a single source of truth for "the base" beats two refs that can disagree.

**The deciding argument is consistency with the promotion verb.** `harness/promotion.py` — the other verb that merges into a base branch — already landed exactly this pattern: `fetch_origin` first; `validate_branch_pair` checks **`origin/<from>` and `origin/<to>`**, never a local branch; `create_promotion_worktree` bases the throwaway worktree off **`origin/<to_branch>`**; `attempt_merge` merges **`origin/<from_branch>`**; and it never reads or advances any local base ref, reusing `.worktrees/harness/` so `worktrees cleanup` reclaims it. Option 1 makes `close` **structurally identical** to promotion — same throwaway area, same origin-ref source of truth, same reclamation. Option 2 would leave `close` alone in relying on a local base ref advanced out-of-band, deliberately diverging from the pattern already chosen for its sibling verb. The one intended difference — promotion opens a PR while `close` pushes `origin/<base>` directly — works *with* the grain: close's push is what keeps `origin/<base>` current for the next reader, no fetch.

## Open decisions

| Decision | Who decides | Recorded in |
|---|---|---|
| ~~AC-3: readers move to `origin/<base>` (Option 1) vs advance-in-routine (Option 2)~~ **RESOLVED → Option 1** (Scott, 2026-07-18) | Scott | this proposal + `specs/worktree-lifecycle.md` (the base-resolution contract, at build) |
| Whether `dirty_base_checkout` and its restore helpers are removed outright, or kept as a narrowed safety net | architect / reviewer at build | `tests/unit/test_verb_contract_locked.py` (a locked, *major*-level change) + `specs/verb-model.md` |
| Whether to fix the failed-push divergence (local `<base>` ahead of `origin/<base>` after a push that fails post-merge) here or split it | architect at build | the change spec / as-built record |

The first is the ratification this proposal sought and has (Option 1). The remaining two are build-time calls carried by CAL-1154's acceptance criteria and out-of-scope notes. The second is a locked-contract change — dropping or renaming a `RefusalReason` member is a *major*-level event under `test_verb_contract_locked.py`, so if Option 1 makes `dirty_base_checkout` unreachable it must be removed **deliberately**, with the locked contract updated in the same change, not left emittable-but-dead.

## Breakdown

**CAL-1154 is the change spec that carries this work** — its acceptance criteria AC-1…AC-6 already enumerate the items below, so the proposal ratifies its AC-3 rather than spawning duplicate tickets. The items are the build plan *within* CAL-1154 (each shippable on its own where the seam allows; the first two are coupled and land together). The builder may split item 3 (the AC-6 seam cut) into a follow-up ticket if the behaviour change lands large — moving the `# size:` justification to that follow-up when they do.

1. **Throwaway-merge git module + `close` rewrite** — a new module mirroring `promotion.py`'s `create_promotion_worktree` / `attempt_merge` / `abort_merge` / `teardown_worktree` (reusing `_git.teardown_worktree`, which already refuses to remove anything outside `.worktrees/harness/`); rewrite `close._merge_and_push` to call it, with the conflict path tearing down the whole worktree (AC-2, no `merge --abort` on a shared tree). Includes removing the now-unreachable `dirty_base_checkout` precondition + `_restore_base_checkout` / `_base_checkout_residue` / `_merge_in_progress` and updating the **locked** refusal-reason contract and `RefusalReason` enum in lockstep.
2. **AC-3 reader migration (Option 1)** — `start` bases off `origin/<base>` with local fallback; `worktrees cleanup --merged` checks ancestry vs `origin/<base>`; migrate the affected `start`/`cleanup` tests. Lands with item 1 so the invariant is never half-moved.
3. **AC-6 seam cut** — separate the **git** concern (`_merge_and_push` and friends) out of `close.py` (currently 685 lines, over the 500 limit with a `# size:` justification pointing at this ticket) from the close **gate** and **ledger** concerns; the size justification retires when the seam lands.
4. **Specs** — update `specs/worktree-lifecycle.md` (base resolution now `origin/<base>`), `specs/verb-model.md` (close no longer mutates the main checkout; refusal-reason set change), and `cli-surface.md` if the surface shifts.
5. **Tests (AC-4, AC-5)** — drive a real merge and a real conflict through the new path, asserting the main checkout is byte-identical before and after both, and that two concurrent closes cannot corrupt a shared tree (the loser fails cleanly and retryably).

## Risks / unknowns

- **Test-migration breadth (Option 1).** The `start` base-resolution change touches many existing tests that assume a local base. This is the bulk of the work and the reason to build attended — it is mechanical but wide, and a missed fallback (origin present, `origin/<base>` tracking ref stale or absent) would strand offline/fresh-clone repos and much of the suite.
- **Locked-contract change.** Removing `dirty_base_checkout` is a *major* event. If any path can still legitimately hit a dirty base (e.g. an interactive close with an unexpectedly dirty main tree), removing the reason is wrong — verify unreachability before deleting, and update `test_verb_contract_locked.py` in the same commit so the contract never lies.
- **Failed-push divergence (pre-existing).** A push that fails after a successful local merge leaves local `<base>` ahead of `origin/<base>`, so the next close's `merge --ff-only` fails with a diverge error (surfaced by CAL-1151's audit, left unfixed there). A throwaway-worktree design likely removes it for free because close never advances local `<base>`; if it does not, the change spec must say so rather than leave it latent.
- **Concurrency proof.** AC-5 asks tests to prove two concurrent closes cannot corrupt a shared tree. With distinct throwaway worktrees per run this should hold structurally, but the `origin/<base>` push is still a race (two closes pushing to the same base) — the loser must fail cleanly and retryably (non-ff push rejected), which the test must actually drive, not assume.
