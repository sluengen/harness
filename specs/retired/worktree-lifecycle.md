# Worktree lifecycle — isolated branch per run

> **Superseded 2026-08-15** — describes the isolated worktree a run built in, the merge `close` performed, and the reclaim sweep that tidied up after it. [ADR 0015](../decisions/0015-harness-v4-thin-verification-layer.md) deletes the verbs that managed all three. Worktree isolation itself survives: it is now plain `git worktree`, driven by the universal `worktree-isolation` skill. Kept for historical reference only.

> Every run builds in its own git worktree on its own branch, so file mutations never escape to the main working tree; `close` advances the base by merging that branch, then reclaims the worktree and branch it no longer needs.

## Behaviour

`harness start` creates an isolated worktree off the base branch; the agent does all its work there; `harness close` merges the branch back into the base and then tears the worktree and branch down. Worktree creation is a verb helper (`harness/worktree.py`, `WorktreeNode.create`), re-homed from the retired engine — the engine-era node wrapper and load-time graph validation are gone (CAL-574). Removal is single-sourced in `harness._git.teardown_worktree`, the best-effort reclaim primitive shared by `start` rollback, `close`, and the `harness worktrees cleanup` sweep — so a run no longer leaks its worktree directory or branch (CAL-767).

### Create — off the base branch

`harness start` calls `WorktreeNode.create(run_id, repo_root, base)`.

The `base` is **resolved from the repo's branch model** rather than hardcoded (CAL-1106): an explicit `--base` wins, else `branches.integration` from the repo's CONTEXT.md, else the repo's origin default branch (`git symbolic-ref refs/remotes/origin/HEAD`), else `dev` as the back-compat fallback (`harness._git.resolve_base_branch`). A repo configured `integration: dev` — like the harness itself — is unchanged; a `main`/`trunk` repo no longer has to pass `--base` on every call.

The worktree is **started from `origin/<base>`**, not the local `<base>` branch (CAL-1154, Option 1). Since `close` merges in a throwaway worktree and pushes `origin/<base>` without advancing the local branch (see *Merge back* below), the local branch lags the merged work; basing a new run off it would start every run on a stale tree. `start` resolves the clean-start commit-ish with `harness._git.preferred_base_ref`: `origin/<base>` when it resolves, else the local `<base>` (offline / no-origin repos, or `origin` present but that branch never pushed) — so no-origin repos and much of the test suite behave exactly as before. The **recorded** `base_branch` (the merge target) is always the local name, unaffected.

#### Scenario: `harness start` creates the worktree

- GIVEN `harness start <ticket>` whose base branch `<base>` is resolved as above (default `dev`)
- WHEN the helper's `create` runs
- THEN it computes the canonical path `<repo_root>/.worktrees/harness/<run_id>/` and branch `harness/<run_id>`, creates the parent directory chain if needed, and runs `git -c worktree.useRelativePaths=true worktree add -b harness/<run_id> <path> <start_point>`, where `<start_point>` is `origin/<base>` when it resolves else the local `<base>`
- AND if the path already exists it raises rather than silently reuse; on a `git` failure it best-effort cleans up any half-baked directory before raising

#### Relative pointers — the worktree is usable from both the host and the container, with no flip

`create` writes the worktree's two pointer files — the worktree `.git` and the admin `<repo>/.git/worktrees/<run_id>/gitdir` — in **relative** form (`worktree.useRelativePaths=true`, git ≥ 2.48). This is load-bearing for the Docker wrapper: `harness start` runs *inside* the container, where the repo is mounted at `/workspace`, but the same worktree is also operated on from the host, where it lives at `/Users/...`. An **absolute** pointer baked at create time is valid in only one of those namespaces, so the operator previously had to hand-flip both files between container-form and host-form around every git operation — a fragile dance whose broken-worktree window let a concurrent `git worktree prune` delete the admin dir and its uncommitted work (CAL-866). A relative pointer resolves from the file's own location, so it is correct in *both* namespaces at once: no flip is ever needed, and `git worktree list` never marks the worktree spuriously `prunable` (CAL-935).

- GIVEN a worktree created in-container (repo mounted at `/workspace`)
- THEN both pointer files are relative, so host git (repo at `/Users/...`) and container git (repo at `/workspace`) each run `status` / `commit` / `worktree list` in the worktree with no restore step, and neither sees it as prunable
- AND because relative worktree pointers and the `extensions.relativeWorktrees` marker they stamp require git ≥ 2.48 — which the base image's Debian trixie does not ship (2.47.3) — the harness image compiles git 2.50.x from source (`docker/Dockerfile` `git-build` stage); a host using this worktree layout likewise needs git ≥ 2.48

### Resume — start the worktree from a preserved branch

`WorktreeNode.create` accepts an optional `start_point` that decouples the commit the new branch starts at from the recorded `base` (the merge target). `harness start --resume` uses it to **continue a reclaimed run from its checkpoint-pushed WIP branch** (CAL-739, proposal [`stale-run-reclamation`](../proposals/stale-run-reclamation.md) D4) instead of restarting cold.

#### Scenario: `harness start --resume` continues a reclaimed run

- GIVEN a `reclaimed` ticket whose dead run left a checkpoint-pushed branch `<wip>` on `origin` (the reclaim comment names it; [`reclaim`](run-ledger.md) preserved it)
- WHEN `harness start <ticket> --resume` runs
- THEN it reads `<wip>` from Linear (`LinearClient.fetch_resume_branch`), `git fetch origin <wip>`, and calls `create(..., base=<base>, start_point=<fetched SHA>)` — so the worktree's `harness/<run_id>` branch continues from the recovered WIP tip while `base_branch` stays `<base>`
- AND `close` therefore merges into `<base>` and its HEAD-bound gate keeps the resumed run safe from double-merge
- AND when no durable WIP exists — the reclaim preserved no branch, or `<wip>` no longer fetches — the resume `start_point` is `None` and it falls back to the ordinary clean start (off `origin/<base>`, else local `<base>`, per *Create* above) — best-effort; resume never blocks the queue

**What `--resume` fetches after a rebase.** `--resume` fetches whatever tip the dead run last *checkpointed to `origin`* — so the freshness of the resume point is exactly the freshness of the last successful checkpoint. Because [`checkpoint`](run-ledger.md) force-with-lease-pushes (CAL-1162), a rebase-before-close that rewrote `<wip>` **re-checkpoints cleanly**, and `--resume` fetches the rebased tip — not the stale pre-rebase one. The tip can be stale only when the final checkpoint after that rebase did **not** land: either it was never attempted (the run died between the rebase and the next checkpoint), or the force-with-lease lease *refused* it because `origin` carried a commit the run had not seen (`reason='stale_remote'`) — and that refusal is a **named outcome the run sees**, not a silent lapse. In that lapsed case `--resume` fetches the pre-rebase tip and the resumed run re-encounters the conflict the rebase had resolved; the durability guarantee is best-effort, and a stale resume degrades to redoing the rebase, never a wrong merge (the HEAD-bound `close` gate still holds).

### Teardown — scoped to the worktree it was asked to reclaim

`teardown_worktree` acts on **one named path**, and its blast radius is part of the contract rather than an implementation detail (#371). `git worktree remove --force <path>` removes that worktree's directory *and* its admin entry under `<git-common-dir>/worktrees/<name>/`, and provably leaves every other registration alone. It runs whether or not the directory is still present: git clears a registration whose directory is already gone, so a stale entry cannot accumulate and block a later `git worktree add` at the same path — which is how `probe_tree.create` reclaims a leftover from a previous review.

**When that call fails, the registry decides what happens next — never the filesystem (#372).** `teardown_worktree` reads `git worktree list --porcelain` and looks for the path's own stanza (`harness._git._registration_state`). Only a path git no longer lists at all reaches the `shutil.rmtree` fallback — the orphan, the cruft a plain `git worktree remove` cannot touch. A path git *still* lists is left alone, and so is a path whose registry read did not answer.

The guard this replaced asked the wrong question. It read "non-zero exit **and** the directory still exists" as proof of an orphan, and that is proof of nothing: `git worktree remove --force` exits **128** both for a path git no longer tracks *and* for a locked worktree, and the directory survives in both. So the fallback destroyed a locked worktree's contents and left its registration standing — a registration with no directory under it, which then refuses the next `git worktree add` at that path, the exact half-state this section's area guard exists to prevent. The predicate that discriminates is not "is it locked?" but "is this path still a registered worktree?" — what the old comment asserted and never measured.

Two details of the read are load-bearing. It compares **realpaths** (`Path.resolve()` on both sides), because porcelain emits realpaths: a checkout reached through a symlinked parent — macOS's `/tmp`, or any operator whose repo sits behind one — is listed at a path that does not string-match the one teardown was handed, and a string comparison would find no stanza, conclude "orphan", and delete a live worktree. And it is **structural, never textual**: nothing parses `stderr`, whose wording drifts between git versions. Locking is read off the stanza's `locked` line, which git prints bare or as `locked <reason>` (a reason containing newlines is quoted, so it cannot split the stanza).

The read **fails closed**. A non-zero exit, a raised `OSError`/`subprocess.SubprocessError` (`TimeoutExpired` included — the read is bounded), or output carrying no `worktree` stanza at all all mean *no opinion*, not "unregistered": git always lists at least the main checkout, so an empty parse is a failed read, and the one answer that authorises a delete must never be reachable by failing to read.

Teardown **reports** what it did rather than raising — it stays best-effort (CAL-767), and a caller that needs to explain a refusal cannot re-derive one from the filesystem, which cannot tell a survivor from a refusal. The return is a `TeardownOutcome`:

| Outcome | Meaning | Directory | Registration |
|---|---|---|---|
| `RECLAIMED` | `git worktree remove --force` succeeded | gone | gone |
| `ORPHAN_REMOVED` | nothing registered at that path, so what was on disk was cruft | `rmtree`d | never existed |
| `LOCKED` | the worktree is locked | kept | kept |
| `UNKNOWN` | removal failed while still registered, or the registry did not answer | kept | kept |
| `SKIPPED_AREA` | outside `.worktrees/harness/` — neither half was ever eligible | untouched | untouched |

`ORPHAN_REMOVED` is returned for any unregistered path in the area, including one whose directory never existed (the `rmtree` is then a no-op); no caller distinguishes the two, and every live caller either iterates directories that exist or ignores the outcome entirely.

**A lock is honoured, never overridden (#372).** `git worktree lock` is the operator's "hands off", and teardown answers it by leaving the subject **entirely** alone — directory *and* registration — and returning `LOCKED`. It never escalates to `git worktree remove -f -f` and never unlocks. `git worktree unlock` is the release, and it is the operator's alone: the next teardown after an unlock reclaims both halves normally, so `LOCKED` is a refusal, not a sticky state.

Three things make honouring the right answer rather than the polite one. A lock *inside* `.worktrees/harness/` can only have been set by a human — nothing in `harness/` issues `git worktree lock`, so a lock there is a deliberate instruction, not machine residue. `--force` is not consent to `-f -f`: git's two rungs answer two different objections (uncommitted content, and an explicit hold), and this repo already refuses to read the first as the second — `worktrees cleanup`'s dirty/stash/in-flight vetoes exist for exactly that reason. And the reversibility is asymmetric: honouring leaves cruft that one `git worktree unlock` clears, while overriding destroys uncommitted contents irrecoverably, from an unattended hourly sweep.

The **two-half invariant** is what both halves of the rule serve: teardown never leaves a directory without its registration or a registration without its directory. Every outcome above satisfies it.

The branch steps are unaffected by any of this. `git branch -D` and the optional `git push origin --delete` run on **every** step-1 outcome, `LOCKED` included: a lock is a statement about a directory and says nothing about a branch.

**Consequence for the throwaway worktrees.** `probe_tree.create_probe_tree` and `close_merge._create_merge_worktree` both reclaim a leftover at their path before reusing it. A *locked* leftover is now kept, so the following `git worktree add` fails — and each converts that into its own named error (`ProbeTreeError`, `CloseMergeError` with `reason='worktree_create_failed'`) rather than wedging. The stage degrades and the operator sees a path to fix; the locked contents survive.

The `.worktrees/harness/` area guard gates **both** steps. A `worktree_path` that is the main checkout, or anything outside the run-worktree area, has neither its directory removed nor its registration cleared: deregistering a directory teardown may not delete would leave a live worktree with no registration, which is the broken half-state below. It is also what stands between the registry probe and an out-of-area delete: an ordinary directory outside the area is, correctly, *not a registered worktree*, so the probe would answer "unregistered" for the home directory as readily as for a leftover run tree. The guard runs first, and the probe is never reached for a path outside the area.

Until #371 the removal was followed by a bare, repo-wide `git worktree prune`. That command takes no path, and every verb runs **in the container**, where the repo is mounted at `/workspace` and nothing else on the host filesystem exists — so the prune read every worktree registered outside the mount as missing and deleted its admin entry. The directory survived on the host, so the damage stayed invisible until something read that tree and git answered `fatal: not a git repository: <repo>/.git/worktrees/<name>` with exit 128, arriving as a wall of red in tracked-tree guards the change never touched. A *host-side* prune does not do this, which is why the failure was twice recorded as a race between concurrent sessions before the mechanism was found. The harness's own worktrees were immune only by accident of location.

The two `git worktree add` rollback paths (`harness/worktree.py`, `harness/promotion.py`) carried the same unscoped prune and are scoped the same way. `tests/unit/test_no_unscoped_worktree_prune.py` bans the call across `harness/` outright — there is no scoped form of `git worktree prune`, so the token pair is the defect rather than an argument to check — and `tests/integration/test_docker_worktree_prune.py` proves it in a real container.

#### Scenario: a worktree outside the container mount survives an unrelated teardown

- GIVEN a run worktree at `<repo>/.worktrees/harness/<run_id>` and an unrelated worktree registered at a host path outside the mount (a verify-gate worktree, say)
- WHEN a verb runs `teardown_worktree` for that run inside the container
- THEN the run's directory and admin entry are both gone
- AND the outside worktree stays registered — `git ls-files` there still exits 0 on the host

#### Scenario: a locked worktree is left entirely alone

- GIVEN a registered worktree under `.worktrees/harness/` that an operator has locked (`git worktree lock`, with or without `--reason`), holding uncommitted work
- WHEN any caller runs `teardown_worktree` on it
- THEN `git worktree remove --force` refuses (exit 128), the registry read finds the path's stanza carrying a `locked` line, and teardown returns `LOCKED`
- AND the directory, its uncommitted contents, and the admin entry all survive — neither half touched, and no `remove -f -f` is ever issued
- AND the same holds when the locked worktree's *directory* has already been deleted by something else: the lock, not the directory, is what teardown answers to, so the registration is still not cleared
- AND the same holds when the repo is reached through a symlinked parent, because the stanza is matched on realpaths

#### Scenario: the operator releases the lock and the next teardown reclaims

- GIVEN a worktree teardown has just reported `LOCKED`
- WHEN the operator runs `git worktree unlock <path>` and teardown runs again
- THEN it returns `RECLAIMED`, the directory and the admin entry are both gone, and `git worktree add` at that same path is accepted again — the consequence the half-reclaim used to destroy

#### Scenario: an orphaned directory is still reclaimed

- GIVEN a directory under `.worktrees/harness/` that git does not list as a worktree (its registration is already gone)
- WHEN `teardown_worktree` runs on it
- THEN `git worktree remove --force` fails, the registry read finds no stanza for the path, and the `rmtree` fallback removes it, returning `ORPHAN_REMOVED` — the cruft case is unchanged by #372

#### Scenario: a still-registered worktree that cannot be removed is not destroyed

- GIVEN a registered, unlocked worktree under `.worktrees/harness/` whose `git worktree remove --force` fails for some other reason — or a repo whose `git worktree list` cannot be read at all (a non-zero exit, a wedged git that times out, or output naming no worktree)
- WHEN `teardown_worktree` runs on it
- THEN nothing is deleted and the outcome is `UNKNOWN`: a teardown that cannot tell which case it is in must not act, and an unreadable registry must never be the route to a delete
- AND teardown still does not raise — the probe's failures, `subprocess.TimeoutExpired` included, are outcomes rather than exceptions (CAL-767)

### Rollback — `start` removes its own worktree on a later failure

`start` creates the worktree as a **local** side effect before it touches the ledger or Linear, so any later failure rolls it back.

#### Scenario: a duplicate-run or DB failure after create

- GIVEN `start` has created the worktree but a later step fails (the partial unique index rejects a duplicate open run, or the ledger insert fails)
- THEN `start` removes the worktree directly via `_cleanup_worktree_sync`, which delegates to `teardown_worktree` (`git worktree remove --force`, `git branch -D harness/<run_id>`; no remote delete — the branch was never pushed) — best-effort, so a failed rollback never masks the original error

### Merge back — `close` merges in a throwaway worktree, then reclaims the run worktree

`harness close` merges the run branch into `origin/<base>` **in a throwaway worktree, never the main checkout** (`harness/close_merge.py`, mirroring `harness/promotion.py` — CAL-1154). It fetches `origin/<base>` (so a base that advanced during the run is integrated — CAL-777), creates a **detached** worktree at `.worktrees/harness/<run_id>-close` based on that current tip, runs `git merge --no-ff <worktree_branch>` in it, pushes the merge commit with `git push origin HEAD:<base>`, and tears the throwaway worktree down wholesale. The main checkout's working tree is not mutated on any path (success, conflict, or a rejected push), so the merge cannot strand it and two concurrent closes cannot collide in a shared tree — each has its own throwaway worktree, and a loser's non-fast-forward push is rejected and retries. The push advances the local `refs/remotes/origin/<base>` tracking ref on the same machine with no fetch, which is what the `start` / `worktrees cleanup` readers base off (the local `<base>` branch is **not** advanced by a close).

Once the merge has landed — and the ticket is Done and the ledger row closed — `close` calls `teardown_worktree(..., delete_remote=True)` to remove the **run** worktree directory and delete the branch both locally and on `origin` (a checkpoint may have pushed it). This teardown is **best-effort and runs last**: the close has already succeeded, so a teardown failure never fails it or undoes the merge — the housekeeping sweep reclaims anything left behind.

#### Scenario: a successful `close` reclaims its worktree and branch

- GIVEN an open run whose worktree HEAD has a passing review and a clean tree
- WHEN `harness close` merges, transitions the ticket Done, and closes the ledger row
- THEN it removes `<repo_root>/.worktrees/harness/<run_id>/`, deletes the local branch `harness/<run_id>`, and (best-effort) deletes it from `origin`
- AND if the teardown raises, the close still returns success (merged, ticket Done, status closed) — teardown is best-effort housekeeping after an already-successful close
- AND a gate refusal (`stale_review` / `dirty_worktree` / `no_run`) exits before any teardown, so the worktree survives for the agent to fix and re-review

### Housekeeping — `harness worktrees`

`harness worktrees list` discovers the worktrees under `<repo_root>/.worktrees/harness/`. `harness worktrees cleanup [--age <duration>] [--merged] [--force] [--db <p>]` is the safety-net sweep for worktrees `close` did not reclaim — a run whose container died before close's teardown step, or cruft from before self-cleaning close landed. It removes the worktree *directories* matching the filters via `teardown_worktree` (orphan-safe: an `rmtree` fallback reclaims a directory whose worktree registration is already pruned, which `git worktree remove` cannot touch). `--merged` additionally **deletes the merged branch** (local + on `origin`) — it is provably integrated, so dead weight; `--age` removes the directory but **retains the branch** (an aged worktree may still hold unmerged work).

The sweep is the one caller that **reads the `TeardownOutcome`** (#372), because it is the one that has to explain itself to an operator. A `LOCKED` worktree is reported as a failure line naming the lock *and the way out* — `worktree is locked — release it with: git worktree unlock <path>` — rather than the generic "still present after removal", which reads as a malfunction and names no remedy for a sweep that would otherwise keep refusing the same worktree every hour forever. `UNKNOWN` is reported as `removal failed and the worktree is still registered`. Both are failure lines, so the sweep still exits 1 with the worktree intact; the directory-still-present check remains as the backstop for everything else. Every other caller ignores the outcome — teardown's contract is unchanged for them.

**`--merged` is a merge-ancestry test, not a liveness test (#235).** `git merge-base --is-ancestor <branch> <base>` is true both for a branch that genuinely landed *and* for a fresh run branch that has made zero commits yet — its tip trivially equals the base. A run whose WIP is `git stash`'d rather than committed looks exactly like the second case, so ancestry alone is not sufficient to call a worktree safe to delete. Before honouring an ancestry-true match, `--merged` runs three vetoes and takes the first hit: (1) **ledger** — the run's `runs` row (matched by `worktree_path`, falling back to `run_id`) has a non-terminal status (`harness.state.schema.IN_FLIGHT_STATUSES`); (2) **stash** — `git stash list`, anchored in the worktree, has an entry naming this branch; (3) **dirty tree** — the worktree has uncommitted changes (`worktree_porcelain`). A vetoed worktree is kept (with the reason printed) unless `--force` is given, which removes it anyway and names what it overrode. The veto applies only to the `--merged` arm — an `--age`-driven removal of the same (old, vetoed) worktree still proceeds, retaining the branch, exactly as before. The Build routine (`/harness routine build`) runs `harness worktrees cleanup --merged --age 7d` in its pre-flight so the reclaim is automatic, not operator-only.

#### Scenario: `--merged` deletes the worktree and its branch

- GIVEN a worktree whose branch is merged into the repo's configured integration base (`branches.integration`, else the origin default, else `dev` — the same `resolve_base_branch` resolution `start` uses, CAL-1106), its branch pushed to `origin`, its run terminal (or unrecorded) in the ledger, no stash naming the branch, and a clean tree
- WHEN `harness worktrees cleanup --merged` runs
- THEN it checks ancestry against `origin/<base>` when it resolves — else the local base (`preferred_base_ref`, CAL-1154) — so a run merged into `origin/<base>` by a throwaway-worktree close (which never advances the local branch) is still recognised as merged; it removes the directory and deletes the branch locally and on `origin`
- AND an orphaned directory (no live worktree registration) older than `--age` is still removed via the `rmtree` fallback

#### Scenario: `--merged` skips an in-flight run whose WIP is only stashed (#235)

- GIVEN a worktree whose branch is a trivial ancestor of the base (no commits yet) because its run's WIP is `git stash`'d rather than committed, and its ledger row is still non-terminal (or, with no ledger DB, the stash alone stands as evidence)
- WHEN `harness worktrees cleanup --merged` runs
- THEN the worktree and its branch survive, and the kept line names the vetoing reason (the in-flight run, or the stash)
- AND `harness worktrees cleanup --merged --force` removes it anyway and names what it overrode

## Data model

The worktree feature has no persistent state of its own; `worktree_path` and `worktree_branch` are recorded on the [run ledger](run-ledger.md) `runs` row by `harness start`.

| Item | Pattern |
|---|---|
| Worktree path | `<repo_root>/.worktrees/harness/<run_id>/` |
| Branch name | `harness/<run_id>` |

Every run gets a unique branch derived from its ULID `run_id`, so concurrent runs never collide. The `.worktrees/harness` path root has a single source, `harness.identity.WORKTREES_SUBDIR`; both `harness.worktree.worktree_path(repo_root, run_id)` and the `harness worktrees` CLI derive their repo-rooted paths from it, so a layout change is one edit (CAL-590).

## Known limitations

- `close`'s teardown is best-effort: if it cannot reach `origin` to delete the remote branch (or its container dies first), the worktree or branch can survive that close. The `harness worktrees cleanup --merged --age 7d` sweep in the Build routine's pre-flight is the safety net that reclaims the remainder; it bounds the leak rather than eliminating every transient one.
- `WorktreeNode.create` does not validate the `run_id` it is handed; `harness.identity.worktree_dir` is the validating entry point.

> The engine-era `CleanupPolicy` machinery (`WorktreeNode.cleanup` — `merge_to_base` / `leave_for_inspection` / `delete_unconditionally`) was **retired in CAL-693**: it had no live caller (the live paths use direct git — `start` rollback, `close` merge, `worktrees cleanup`) and was exercised only by its own tests. Only `WorktreeNode.create` survives.

## Decisions

### Teardown honours `git worktree lock` rather than overriding it (#372)

**Context.** Teardown could not tell a locked worktree from an orphaned directory, because `git worktree remove --force` reports both with exit 128 and the directory survives both. Once the discriminator existed (is the path still registered?), the locked case needed an answer: honour the lock and report the refusal, or escalate to `git worktree remove -f -f` and always succeed.

**Decision.** Honour it. A locked worktree is left entirely alone, both halves, and the refusal comes back as `TeardownOutcome.LOCKED`. Teardown never issues `-f -f` and never unlocks; `git worktree unlock` is the operator's release.

**Alternative rejected — escalate to `-f -f`.** It makes teardown total, which is superficially attractive for an unattended sweep that would otherwise report the same worktree every hour. Its cost is that the sweep becomes the one thing in the system that can silently destroy work a human deliberately protected: a lock under `.worktrees/harness/` can only have been set by a human, since nothing in `harness/` locks. The reversibility is asymmetric — honouring leaves cruft one command clears, overriding destroys uncommitted contents with no recovery — and `--force` is not consent to `-f -f`, a distinction this repo already draws in `worktrees cleanup`'s dirty/stash/in-flight vetoes. The recurring-report cost is paid instead by making the report name its own remedy.

**Consequences.** A locked leftover at a path `probe_tree.create_probe_tree` or `close_merge._create_merge_worktree` wants is now kept, so their `git worktree add` fails; both already convert that into a named error, so the stage degrades rather than wedging. The sweep gains a second failure classification and keeps exiting 1. Feature-local, per `CONTEXT.md`: `specs/decisions/` is reserved for cross-cutting choices that are consequential and expensive to reverse, and this one is scoped to a single primitive and reversible by editing it.

## Cross-references

- [`specs/retired/worktree-isolation.md`](../retired/worktree-isolation.md) — the engine-era `WorktreeNode` reference (historical; the `cleanup` machinery it documents is retired)
- [verb-model.md](verb-model.md) — `start` creates the worktree, `close` merges the branch
- [run-ledger.md](run-ledger.md) — where `worktree_path` / `worktree_branch` are recorded
- [cli-surface.md](cli-surface.md) — the `worktrees` housekeeping commands
