---
proposal: scope-the-base-gate
status: accepted
date: 2026-09-14
related: [specs/decisions/0022-the-plugin-is-the-whole-deliverable.md]
---

# Proposal: scope the base gate

> `worktree-isolation` runs `commands.verify` against a base with no diff, which a change-aware gate cannot answer usefully — decide whether the plugin resolves that or documents it and leaves it to the repo.

## Problem / motivation

`worktree-isolation` → *Gating the base* runs the repo's `commands.verify` in a
detached worktree standing at the integration tip, before the branch is cut. The
skill costs this as "one gate run per worktree, weighed and accepted", and that
weighing assumed a gate whose cost does not depend on what it is asked about.

A change-aware gate breaks the assumption. It derives its scope from `git diff`
against the integration branch, and at the base that diff is empty, so the gate
is being asked a question it is not shaped to answer. What it does then is
whatever its author chose for the empty case, and nothing in the guidance says
that choice matters.

In `sluengen/calibrate` it matters. `scripts/verify.sh:1114-1115` prints
`No scoped changes detected vs ${BASE_NAME}; running backend gate (default)`
and sets `run_backend=1`, so every worktree cut in that repo pays the backend
arm — Docker Compose, Postgres, the full backend suite — whatever the ticket
will touch. For a mobile-only ticket that proves the backend is green on a
surface the ticket will not change, and says nothing about the mobile arm the
ticket will actually be gated on. The operator reports the local gate reaching
twenty-five minutes.

The information needed to do better already exists at the moment the base gate
runs. `/build` completes the grounded change spec at step 4 and creates the
worktree at step 5, so the ticket's file surface, anchored to `path:line`, is on
the ticket before `worktree-isolation` is reached. The base gate does not
consume it, because `commands.verify` takes no scope in the generic contract.

Two further facts bound the options. `worktree-isolation` is generic: `/assess`
also cuts a worktree, and supplies no change spec, so any design that requires
one needs a defined behaviour when none exists. And in calibrate the base gate
carries a second job nobody declared — `.github/workflows/verify.yml:6-9` runs
CI on pull requests and pushes to `main` only, deliberately, while most work
lands on `dev` by direct push, so the next builder's base gate is the only
routine detector of a red integration branch there.

## Options

**Option A — pass the ticket's surface to the base gate.** `/build` has the
grounded spec before step 5, so the base gate could run the arms the ticket
declares it will touch. · Targets the arm that matters, and keeps attribution
intact for exactly the surfaces a later red could appear on. · Needs a declared
way to hand a scope to a gate, which the generic contract does not have. The
spec's file list is a prediction, so a ticket that grows past it leaves the base
ungated on the arm it ends up touching. Couples a generic skill to a caller that
supplies a scope, when `/assess` supplies none.

**Option B — declare a base-gate command in `harness.yaml`.** A key beside
`commands.verify` naming what to run at a base. A repo with one gate declares
nothing and keeps today's behaviour; a repo with a change-aware gate declares
the cheap equivalent it wants. · No scope plumbing, no prediction, no new
executable; the repo decides what "green enough to start on" means for itself.
· A second gate command to keep honest, and a repo that declares one too weak
reintroduces the failure the base gate exists to prevent. Earns its place at one
observed consumer or does not.

**Option C — retire the base gate and attribute lazily.** Cut the branch
without gating; on a red in the worktree, gate the merge-base then to decide
whose it is. · Removes a full gate run from every tick. · Removes the only
routine detector of a red integration branch in a repo whose CI does not run on
integration pushes, which is calibrate's configuration today. A red `dev` would
then stand until the nightly staging promotion, costing every concurrent agent
a tick.

**Option D — document the dependency; the consumer resolves it.** State in
*Gating the base* that the run must answer "is the integration tip green over
the surfaces this ticket will touch", that a change-aware gate sees no diff at a
base, and that resolving that is the repo's own, since the repo owns its gate
script under ADR 0022 point 1. · One paragraph, no mechanism, no config, and it
unblocks calibrate immediately: the fix there is its own empty-scope fallback,
a one-line choice in a file it already owns. · Documents a sharp edge instead of
removing it. A second consumer meets the same edge and resolves it its own way.

## Recommendation

**Option D**, with B held and its reopen trigger named.

The defect is an undocumented assumption in shipped guidance, and D removes
exactly that at the cost of a paragraph. P0 refuses a mechanism added where a
number would do, and the number here is calibrate's own fallback arm — a
one-line change in a file ADR 0022 point 1 already assigns to the consumer.
Shipping B first would add a configuration key, a reader, and a way to get it
wrong, to serve one observed repo that can fix itself today without waiting for
a plugin release.

D also gets both of the base gate's jobs stated. *Gating the base* names only
attribution — "a red gate from here on is yours". Calibrate's configuration has
quietly given it a second job, integration-branch health, because nothing else
watches `dev` there. The operator's answer to the second decision makes that
second job explicit rather than emergent, so a repo sizing a base command knows
what it is buying.

This spends against P1: a documented dependency sits on the prose rung, and the
principle prefers enforcement on the lowest rung that can hold it. The rung is
right here because the resolution is the consumer's to make and differs per
repo, which is the same reason `commands.verify` is declared rather than
shipped.

## Not doing

- **A declared base-gate command (`commands.verify_base` or similar)** — one observed consumer, which can resolve it in its own gate script today. Reopen if a second repo with a change-aware gate meets the same edge, or if calibrate's own fix proves it cannot be expressed inside one `verify.sh`.
- **Passing the ticket's grounded surface to the gate (Option A)** — needs a scope interface the generic contract lacks, and rests on a predicted file list. Reopen if a declared base command lands and repos then ask for it to be scoped per ticket rather than per repo.
- **Retiring the base gate (Option C)** — it is the only routine detector of a red integration branch in a repo whose CI does not run on integration pushes. Reopen if a repo gains CI on every integration push, which makes the tip's status readable without a run.
- **Scoping the base gate to what the previous landing touched** — targets the likeliest breakage, but needs the gate to accept a file list and assumes one landing is the only candidate cause. Reopen if a scope interface exists for another reason.
- **Changing what the reviewer's or `/promote`'s gate runs** — those gate a real diff, so the empty-diff problem does not reach them. Out of this proposal entirely; the *two gates* contract is untouched.

## Open decisions

Both were decided by the operator on 2026-09-14, and the proposal was accepted
the same day.

| Decision | Outcome | Recorded in |
|---|---|---|
| D or B — does one observed consumer earn a configuration key, or does the consumer fix its own fallback first? | **D.** Document the dependency; the repo that owns its gate script resolves it. B stays in *Not doing* with its reopen trigger | this proposal |
| Is integration-branch health part of the base gate's job, or only attribution? | **Both jobs, declared.** The base gate serves attribution *and* integration-branch health, so a base command must be broad enough to catch a red integration branch | `skills/worktree-isolation/SKILL.md` → *Gating the base* |

**What the second decision costs, recorded because it was taken knowingly.** A
base command that must catch a red integration branch cannot be made arbitrarily
cheap, so the saving available to a repo under D is bounded by that floor rather
than by the arm its ticket touches. Calibrate's backend-arm fallback is already
doing the health job on one surface; what D buys there is the choice being made
deliberately, with both jobs named, rather than inherited from an empty-diff
default nobody weighed. The alternative — attribution only — was declined, and
is not a silent option for a later ticket to pick up: reopening it means
amending this proposal.

The assumptions register is not a recording home for this. It holds what the
harness assumes a *model* cannot do, and this is a statement about what a run
must prove, so the guidance itself is the only home.

## Breakdown

1. **State the base-gate scope dependency in `worktree-isolation`** — one paragraph in *Gating the base* naming both jobs the run must answer for (attribution, and integration-branch health), that a change-aware gate sees no diff at a base and so answers with whatever its author chose for the empty case, and that the repo owns resolving it because the repo owns its gate script. Change lane; no test, because the subject is guidance and ADR 0019 verifies prose by review or use.

   Filed 2026-09-14 as [#662](https://github.com/sluengen/harness/issues/662),
   `assurance:simple`. **Placement did not run:** the filing session could not
   reach Projects v2, so the issue carries no Status and no Todo-scoped queue
   read will return it until somebody places it. It is filed, not queued.

One item, because the thinking was the expensive part and the edit is small.
The four-dimension test fires on none of it — a paragraph migrates nothing,
fans out to no call site, decides no access pattern, and the operator has
already seen the shape in this proposal — so it is not held.

## Risks / unknowns

- **The 25-minute figure is not attributed.** The operator observed it; nobody
  has run `VERIFY_PRINT_SCOPE=1` on a real build-loop gate in calibrate to say
  which arms resolved and why. The base gate's backend fallback is one
  contributor, grounded above. A ticket whose own diff spans backend, mobile and
  design would resolve three arms correctly, and that cost is batch size rather
  than a guidance defect. **Measuring this could invalidate the whole
  proposal**, and it is cheap.
- **N=1.** Calibrate is the only consumer known to run a change-aware gate. This
  repo's own gate is unscoped and finishes in seconds, so nothing here
  dogfoods the problem.
- **Documenting a sharp edge leaves it sharp.** Each new consumer with a
  change-aware gate pays the discovery again. That is the accepted cost of D and
  the trigger that reopens B.
- **Calibrate's spine is `harness@11.1.0`** against `12.2.0` here, so a guidance
  change reaches it on its next hydrate rather than immediately.
