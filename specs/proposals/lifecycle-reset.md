---
proposal: lifecycle-reset
status: draft            # draft | under-decision | accepted | shipped | rejected | split | superseded
date: 2026-09-04
related: [drift-reconvergence, rebase-stable-certification, plugin-surface]
---

# Proposal: reset the lifecycle on five principles

> The repo's growing cycle time and its growing complexity are one feedback loop, not two problems. This proposes the principles that decide what does not get built, and lands the first instance — the landing posture — with measured results.

## Problem / motivation

Two symptoms, reported across consuming repos:

1. **Longer cycle times**, with the waste and rework that follow.
2. **Ballooning complexity and work creation.** Every ticket discovers small things, and the small things go on the ledger.

They drive each other. Guards and tickets accumulate, the gate lengthens, cycle time grows, the window in which concurrent work collides widens, collisions produce rework, rework discovers more small things, and those become more guards and tickets.

### The ratchet is measurable

Count the test modules the gate carries, at three revisions:

```
git ls-tree -r --name-only <rev> tests/unit | grep -c '\.py$'
```

| Revision | Date | Modules |
|---|---|---|
| `3317d1c^` — immediately before the v5 cull | 2026-08-18 | **151** |
| `3317d1c` — the cull | 2026-08-18 | **25** |
| `15908d2` — `origin/dev` today | 2026-09-01 | **45** |

The cull removed 126 modules on the day the repo decided its guards were the problem. Twenty came back within fourteen days.

The cull was correct, and it did not hold. Not one of the twenty arrived by mistake; each had a local justification, and some are legitimate code-behaviour tests admitted under ADR 0017's rule. The finding is the rate, and that nothing in the process asks about it. **A cull without a stated basis for refusal resets the counter and changes nothing else.**

The cycle-time half is already worked in [`drift-reconvergence`](drift-reconvergence.md), which measured the cost to land as exponential in gate duration multiplied by the rate other agents push. That proposal deferred its structural option pending a measurement, and the instrument it asked for was filed as #515 and closed unbuilt. The loop shows up inside the proposal written about the loop.

Doing nothing repeats the cull on a schedule, reclaiming ground the process re-takes between culls, while cycle time keeps the exponent it has.

## The principles

The basis for the reset. Each states what it rules out, because a principle that cannot refuse anything is a preference.

**1. Leverage what the frontier model harnesses bring, to the fullest.**
Rules out machinery that re-implements what the harness already does: a hand-rolled parser where a sub-agent reads, ceremony that compensates for an agent the repo no longer has.

**2. Balance quality, speed, cost, and risk mitigation.**
Rules out driving one axis to the floor. A guard that buys risk mitigation at unbounded cost to speed fails this while working exactly as designed.

**3. Simplicity scales, complexity fails. Less is more.**
Rules out the additional exception. The question to ask of a proposed guard is not whether it is correct, but whether the tree gets simpler.

**4. Get it right the first time, build quality in.**
Rules out sending a design to review that a cheap probe would have killed. Verification belongs before the write-up, not after the review cycle.

**5. Cost/benefit framing. Not all work needs to be done, not every risk needs to be covered.**
Rules out the uncomputed cost. A proposed guard, gate stage, or ticket states what it costs and what it buys, or it does not get filed.

## The first instance: the landing posture

Decided with the operator, 2026-09-04. It is included here as the worked example the principles produced, and as the evidence they yield results.

**The decision.**

- The blocking gate certifies the **composite** tree: the candidate merged with the integration branch at that moment. One gate per build.
- Landing does **not** re-gate a clean auto-merge. The push guard gains a second acceptance path: a fresh marker covering an ancestor commit's tree, that commit a parent of the pushed merge, and no authored bytes in the merge.
- A **conflicted** merge re-gates over the conflicted paths. Resolution bytes are the one thing no gate and no reviewer has seen. The marker gains a scope field so it never asserts coverage the run did not have (D4, D3).
- A red integration branch is found by the next builder's composite gate rather than by CI, which the consuming repos do not have. Sessions share findings through git refs.
- The verdict binds to the **authored** tree rather than the shipped tree. This restates spine law 3 and the tree-binding contract.

### Measured

Eight probes against `sluengen/calibrate-coffee`, private, no server-side configuration, 2026-09-04. Every probe ref was deleted afterward.

| # | Probe | Result | Consequence |
|---|---|---|---|
| 1 | Push a commit-pointing ref to `refs/harness/gate/<oid>` | new reference | Custom namespaces work on a private repo. No plan gating. |
| 2 | Push a **blob**-pointing ref, no commit wrapper | new reference | A record is one blob. |
| 3 | Fresh clone, then `+refs/harness/*:refs/harness/*` | needs an explicit refspec | Records never bloat an ordinary fetch. Discovery must name them. |
| 4 | Two unrelated commits race one claim ref | second rejected, non-fast-forward | First-writer-wins works. The coordination primitive is free. |
| 5 | `--force-with-lease` through the hooks | **denied by `git-push-guard.js`** | Killed the lease-steal design. Replaced by bucket rotation. |
| 6 | `<tree>/<bucket>` beneath an existing `<tree>` ref | rejected, cannot lock ref | D/F conflict. Every key stays flat. |
| 7 | `git ls-remote origin 'refs/harness/gate/*'` | ~1.0s, zero objects | Put the outcome in the ref name. The discriminator costs one second. |
| 8 | `refs/notes/` fallback | new reference | Available, and unnecessary. |

### Modelled

Carried from `drift-reconvergence` with its inputs unchanged, and still assumptions rather than measurements: exposure window 15 min falls to about 5 s, collision probability at λ≈8/hr falls from 87% to 1.1%, and expected attempts to land fall from 7.4 to about 1.01.

### What each principle decided

| Principle | The call it made |
|---|---|
| 1 | Conflict resolution goes to a sub-agent instead of a lock server. The red/green discriminator is one `ls-remote` instead of a reviewer round trip. |
| 2 | Accepts a rare red integration branch, detected by the next builder, to remove an exponential. Quality is balanced against three other axes and the trade is stated rather than assumed. |
| 3 | Four git refs. No CI job, no merge queue, no lock server, no new service. When probe 5 killed the lease, its replacement was **simpler** than what it replaced, which is the sign the principle did work rather than got cited. |
| 4 | The probes ran before the write-up. Probe 5 killed a design in two minutes that would otherwise have consumed a review cycle, a build, and a reversal. |
| 5 | The clean merge is not gated and the conflicted one is. Stale counts in an as-built record get the existing rule against bare counts enforced, not a reviewer round trip. Both are refusals that name what they declined to buy. |

## Options

These concern how the principles bind. The landing posture above is decided.

**Option A — principles as guidance only.** State them in the spine, add no mechanism. · *Trade-offs:* free, and it cannot become its own ceremony. It is also what the v5 cull did, and the table above measures the result.

**Option B — principles plus an obligation where work is created.** A filed ticket, a proposed guard, and a new gate stage each carry one line of cost and benefit. A proposal or ticket without one does not get filed. No guard enforces it, because principle 3 forbids buying enforcement for a prose rule and #511 measured what that costs. · *Trade-offs:* cheap, and it asks the question when the work is created rather than at an audit months later. Convention-only, so it decays unless the operator holds it.

**Option C — principles plus a periodic ratio check.** `/assess process` derives the module count and the guard-to-deliverable ratio at each pass, using the derivation above. · *Trade-offs:* one command makes regrowth visible with no standing machinery. It detects rather than prevents, and it is the shape that already failed when nobody computed the ratio for four cycles.

**Option D — cull now, decide the basis later.** · *Trade-offs:* the experiment already run, with 20 of 126 modules back inside a fortnight.

## Recommendation

**B and C together.** A is the status quo under a new name, and D repeats a measured failure.

B puts the cost question at the moment of creation, which is the only point where refusing is cheap. C makes the regrowth visible without standing machinery, and its derivation is three `git ls-tree` invocations rather than an instrument to build. Neither adds a guard; both are convention, and principle 3 is why.

This proposal stays narrow on purpose. It fixes the basis and lands one instance. The review loop, the assurance levels, the ticket lifecycle, and the guidance skills are for the agents that follow, and each should show the same shape: a measured before, a decision traceable to a numbered principle, and a measured after.

## Open decisions

| Decision | Who decides | Recorded in |
|---|---|---|
| Do the principles enter the spine as a numbered list that later work cites by number? **Held** 2026-09-04: the operator judged this part of the wider redesign rather than a question this proposal should settle alone | user | `CLAUDE.md` spine |

## Decisions — 2026-09-04

Taken by the operator on this proposal. Each is carried into the breakdown item that implements it.

**D2 — the verdict binds to the authored tree, and a clean auto-merge may carry it.** The claim narrows to *every authored byte that ships was gated and reviewed, and the merge carrying them added no authored bytes*. The guard proves that from git alone: one merge base, parents exactly the passed commit and the incoming tip, a clean index and worktree, no staged resolution. Disjoint changed-path sets were considered and **not** required, so two builds touching one file still take the fast path when git resolves it. The residual risk is a silent semantic merge inside a shared file, and the next builder's composite gate is what catches it.

**D4 — a conflicted merge re-gates over the conflicted paths, not the whole tree.** Resolution bytes are the only uncertified path left under D2, so they are gated; a slow gate is why the run is scoped rather than full. This is the one place the proposal adds machinery, and D3 is how that machinery was kept to a single line.

**D3 — one optional command, no strategy key.** A repo names its scoped test command in the existing `commands:` block. Declared, the conflict path runs scoped; undeclared, it runs the full gate. No `landing:` block, no strategy branch in `/build`, and one acceptance shape in the push guard. This mirrors `assurance.trivial_certify`, which already degrades when a repo has not opted in, so an unconfigured repo is safe by construction rather than by remembering to set a key.

**D5 — pruning rides on a write that already happens.** When a builder publishes a gate record it also deletes records whose dev tree has left the integration branch's recent history. No scheduler, no standing job, and nothing to run in the CI budget the design does not have. The cost is that one session routinely deletes refs another session wrote, which is safe only because records are content-keyed and re-derivable by re-running a gate.

## Breakdown

Items 1 and 2 gate the rest. Every criterion measures something that runs.

1. **Push guard second acceptance path.** `push-target-guard.js` accepts a push whose tree carries no marker when a fresh marker covers an ancestor commit's tree and the merge introduced no authored bytes. *Criterion:* the guard allows a clean two-parent merge over a certified ancestor, and denies the same shape once one byte is authored into it.
2. **Spine law restatement.** Law 3 and the tree-binding contract in authored-tree terms; the Stop hook and gate-evidence guard follow. No new guard.
3. **Gate record protocol.** `refs/harness/gate/<dev-tree>-red|-green` as blobs, flat keys, `ls-remote` discovery, and the prune from D5 riding on each publish. *Criterion:* a record published from one clone is read by another in one `ls-remote` with no object transfer; publishing a record for a current dev tree deletes a record whose tree has left the recent history and leaves current ones alone.
4. **Claim protocol.** `refs/harness/claim/<dev-tree>-<epoch-bucket>`, create-wins, no force anywhere. *Criterion:* two concurrent creates on one bucket yield exactly one winner, and a rotated bucket admits a new one.
5. **Scoped re-gate on the conflict path.** `commands.test_scoped` in the spine, and a marker that records what the run covered. *Criterion:* a marker written by a scoped run names its scope, and a push whose authored bytes fall outside that scope is denied; a repo declaring no scoped command runs the full gate on this path instead.
6. **`/build` stages.** Composite gate before the verdict, land loop after it, triage before diagnosis, park when the claim is lost.
7. **Green pointer.** `refs/harness/green/<integration>` advances on uncontended landings; new worktrees branch from it.
8. **Cost/benefit at creation.** `spec-authoring` and `/capture` require the line. Convention, no guard.

## Risks / unknowns

- **λ has never been measured.** The 8/hr push rate is carried from `drift-reconvergence` and remains an assumption. A much lower λ leaves the landing posture correct and its benefit smaller than claimed.
- **Detection latency for a red integration branch becomes "until the next build"** rather than one gate duration. A repo with few builds per day is materially worse off than with CI, and should re-decide the trade.
- **Ref growth over months is unmeasured**, and no prune policy exists.
- **Principle 5 is the one most likely to be cited without being applied.** A cost/benefit line is easy to write and hard to falsify. It is convention by design, and if it decays this proposal has bought a preamble.
- **The scoped re-gate is where this proposal spends against its own principle 3.** It is the only new machinery here: a spine command, a marker scope field, and a scope-derivation step. If the derivation is wrong the marker asserts coverage the run did not have, which is the vacuity shape `craft.md` already catalogues. Item 5's criterion exists to make that failure visible, and a repo that declares no scoped command never buys any of it.
- **This proposal can become what it describes.** If the reset spawns a governance layer, an enforcement guard, or a standing audit obligation, principle 3 has been broken by the document that states it.

**What would invalidate the recommendation:** a measured λ near zero across consuming repos, which collapses the landing posture's benefit; or a second derivation showing the post-cull regrowth is entirely legitimate code-behaviour tests, which weakens the ratchet thesis and leaves cycle time as the only problem.
