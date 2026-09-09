---
name: promote
description: "/promote — land a reviewed branch, or move completed work toward release. Two altitudes: `/promote <TICKET>` takes the branch `/build` left at PASS and rebases, gates, pushes, closes and cleans up; `/promote <src> to <dst>` runs a release hop along the repo's role branches. Use when the operator says `/promote`, \"land it\", \"ship the reviewed branch\", or \"promote dev to main\". Reachable by the model: `/routine` invokes the landing altitude to finish its tick, so `disable-model-invocation` is deliberately not set here — it would leave the unattended loop building work it can never ship (#623)."
model: inherit
effort: medium
---

The portable plugin root is two directories above this SKILL.md. Resolve embedded paths beginning `skills/`, `agents/`, `templates/`, `hooks/`, or `.codex/` from that root; resolve repository artifacts from the workspace root.

# /promote — land a reviewed branch, or move completed work toward release

One skill, two altitudes, because both are the same act at different scales: take
work that has already earned its verdict and move it onto the branch that comes
next, gating over the bytes that will actually land.

| Invocation | What it does |
|---|---|
| `/promote <TICKET>` | Lands the reviewed branch `/build` left at PASS: rebase, gate, push, close, reflect, clean up. |
| `/promote <src> to <dst>` | The release hop along the repo's role branches. |

**There is no no-arg form.** Neither altitude is inferred: the landing altitude
needs its ticket, and a release hop needs both `<src>` and `<dst>`.

The mechanism at both altitudes is plain git plus the repo's own verify gate.
ADR 0015 retired the audited `harness promote` verb loop; ADR 0022 retired the
tree binding and the landing machinery built on it. There is no promotion id, no
ledger row, and no marker: the gate a run reads itself is the assurance, and the
audit trail is ordinary git history, the ticket, and the PR.

# Altitude 1 — landing a reviewed ticket

Usage: `/promote <TICKET-ID>`

`/build` ends at PASS with the ticket In Review and its own branch pushed. This
half takes it from there. It is also the **re-entry point for a run that already
earned its verdict**: one whose context ran out after PASS resumes here rather
than rebuilding. A run that ended any other way does not — a FAIL, a DEFER, or a
spent budget resumes at `/build`, because what it is missing is the verdict this
altitude requires on record before it does anything.

Stage order is normative. The `authority` field names the system allowed to act
at that stage; never insert a tracker action into a Git-only interval.

<!-- harness:promote-lifecycle:begin -->
- stage: rebase
  authority: git
- stage: full_gate
  authority: gate
- stage: pass
  authority: gate
- stage: tree_compare
  authority: git
- stage: push
  authority: git
- stage: tracker_done
  authority: tracker
<!-- harness:promote-lifecycle:end -->

## Before the first stage: read the ticket as it is now

**Re-read the ticket's live state, and stop rather than shipping against one that
moved.** Splitting the lifecycle widened the interval between reading a spec and
pushing a tree, so a ticket closed, held, or materially amended in between is
likelier than it was — and none of those is visible in the branch. Confirm three
things from the tracker, not from memory or from `run.json`:

- It is **In Review**, and not Done, Canceled, or back in Todo. A ticket already
  Done means somebody landed this work; verify before adding a second copy.
- It carries **no hold**. A hold applied after the verdict is a human asking for
  something, and landing past it answers them by ignoring them.
- Its change spec still describes what the branch does. A materially amended
  spec means the verdict covered a different question; return it to review.

Any of the three is a stop, reported to the operator with what moved — not a
hold, because the ticket is already carrying whatever state moved it.

Then confirm a **PASS is on record for this ticket** and the branch it names is
the branch in hand. There is no machine half to this: the ticket's state and the
review report are the record, and a branch that reached here without a verdict is
a run that skipped the review, which this command does not launder.

## The stages

1. *Rebase.* Fetch, and bring the integration branch into the candidate.
   [`skills/build/references/reconcile.md`](../build/references/reconcile.md)
   owns every rule — base movement as normal concurrency, the two-attempt bound,
   the monotonic-field trap, functional conflict as the only escalation — and
   this is the second of the two places that load it. **The stage is named
   `rebase` and the operation is a merge**, exactly as that reference describes:
   never `git rebase` on a branch anything else may have fetched.
2. *Gate.* Run the repo's `harness.yaml` `commands.verify` gate over the merged
   tree — read the command fresh from `harness.yaml` every run and never
   hardcode one here. Capture the output and read all of it.
3. *Pass.* Green over the tree in hand is what licenses the push. **A red gate
   here is this builder's to fix, whatever caused it.** That is the resolved
   posture and it is deliberate: stop the line, not stop the tick. The bytes
   that arrived in step 1 are other tickets' reviewed work, so the ordinary
   repair is a merge repair rather than a design change — and where it is a
   design change, the red is the signal to return the ticket to review rather
   than to push through it. **Name the residual rather than discovering it:** a
   fix made here is made after the review that no longer covers it. That is the
   trade the split accepts, and a fix large enough to want a reviewer is a fix
   large enough to go back to one.
4. *Tree compare.* `git rev-parse HEAD^{tree}` must equal the tree the gate just
   ran over. Nothing may be edited between the gate and the push — the check is
   cheap and it is the whole of what the retired binding still buys.
5. *Push.* Integrate exactly as `harness.yaml`'s `branches:` block declares:
   a direct push where the model allows one, a PR where it requires one, and
   where a human must merge that PR, that is a hold rather than a failure. Never
   force. Never a release branch from this altitude — that is altitude 2's hop,
   and it has its own rules. **Never push from a shape you cannot describe:** a
   dirty worktree, a detached HEAD, or a branch the repository declares no role
   for is a state to report, not a landing. One uninterrupted sequence from stage
   4 to here, with no tracker write inside it.
6. *Close.* Post the merge link and transition the ticket to Done.

## After the push

- **Reflect.** At most three lines, or `none` — the wastes this run met by P2's
  categories and what should change, each line appended to an improvement ledger,
  this repo's or the guidance source's, resolved as `review-discipline` →
  `references/improvement-ledger.md` says and never hardcoded.
- **Close the ticket and clean up.** Run `worktree-isolation`'s cleanup
  procedure, reporting any resource it could not release rather than substituting
  a broad host cleanup.
- `tracker: none` skips the tracker steps and reports them skipped.

# Altitude 2 — the release hop

Usage: `/promote <src> to <dst>`

## Argument resolution

Each word resolves against this repo's `harness.yaml` `branches:` roles first,
falling back to a literal branch ref:

1. If the word is one of the three canonical role keys — `integration`,
   `staging`, `release` — and `harness.yaml` defines that role, resolve to the
   branch name it names.
2. Otherwise, use the word itself as a literal branch ref.

This is why the same invocation shape works everywhere, whatever a repo calls
its branches. Take this repo's own two-role topology (`integration: dev`,
`release: main` — ADR 0003 as amended retired its `staging` role):

- `/promote dev to main` — the release hop. `dev` matches no role key, so it is
  used literally; `main` matches no role key and is used literally too.
- `/promote integration to release` resolves identically — the canonical role
  names always work.

Now take a repo whose roles are `integration: develop`, `staging: staging`,
`release: production` — a repo that deploys to a staging environment and so
runs all three roles. **The identical invocation drives it unchanged:**
`/promote develop to staging` — `develop` matches no role key so it is used
literally (and happens to be that repo's actual integration branch); `staging`
resolves via the role to `staging`. No per-repo command variant is needed; the
resolver is what changes, not the command.

## The loop

1. *Fetch and branch.* `git fetch origin`, then create a promotion worktree
   off the *target* branch (`<dst>`, resolved above) at its remote tip. Work
   in the worktree, never in the main checkout.
2. *Merge the source in.* Merge `<src>` into it. **On conflict: stop and
   report** — the conflicting files and a diff summary. No repair attempt,
   bounded or otherwise; this path has no repair authority at all.
3. *Gate it.* Run the repo's `harness.yaml` `commands.verify` gate in that
   worktree — read the command fresh from `harness.yaml` every run and
   never hardcode a gate command here, since this path keeps no state to
   remember one in. Capture the output. **On red: stop and report** the
   captured output. No retry.
4. *On green, publish.* The hop selects the mechanism:
   - `<dst>` is an *intermediate* branch (e.g. `staging`): push the merged
     tree directly to the target ref. No PR — the gate already made the call.
   - `<dst>` is the *release* branch (e.g. `main`): a protected release
     branch's required check commonly comes from a `push`-triggered run on a
     named branch or a `pull_request`-triggered run scoped to particular base
     branches — not from an arbitrary PR head. Check whether the merge is
     *content-trivial*: `<dst>`, relative to its merge base with `<src>`,
     contributes no content, so the merge's tree equals `<src>`'s own tip tree.
     - *Content-trivial:* open the PR with **head `<src>` itself** and push
       nothing new. `<src>` is already pushed, so its tip already carries
       whatever check its own `push` trigger raised, and the PR inherits that
       check by head-SHA association. A synthetic promotion branch's head
       commit was never pushed anywhere on its own; if the target repo's CI
       does not *also* run `pull_request` checks based on `<dst>`, that head
       gets no check run at all, and a branch that requires the check blocks
       the PR permanently, not just slowly.
     - *Not content-trivial* (`<dst>` carries commits `<src>` does not):
       `<src>`'s own tip no longer stands in for what will land. Push the
       merge to a promotion branch and open the PR from it, but first confirm
       the target repo's CI actually raises the required check for a PR
       shaped that way (a `pull_request` trigger whose base matches `<dst>`,
       or a `push` trigger matching the promotion branch's name). If it does
       not, treat it as the same stop condition as an unrunnable gate: do not
       open a PR nothing can ever check — stop and report instead.

     Either way, the PR body carries the commit range and the gate evidence,
     and a human merges it — this command never merges its own PR.

   A protected target that can only advance through a pull request cannot be
   fast-forwarded: a merged PR always writes a commit the source does not
   carry. Assert the property fast-forwarding was protecting instead — **the
   tree that lands equals the tree the gate certified** — on the merge the API
   returns, and record in the repo's infrastructure spec that you did.

5. *Back-merge after the release hop.* When the release branch gains commits
   the integration branch does not have — the merge commit, a hotfix — merge
   release back into integration promptly. Skipping it makes every later
   promotion carry a phantom divergence that surfaces as a conflict on
   somebody else's ticket. The back-merge is part of the release, not
   housekeeping to remember afterwards.

   **A version bump is not one of those commits.** A release identifier is
   raised at the *start* of a cycle, on the integration branch, by the first
   change to land after the previous release. Raising it here is too late by
   construction: the release ships content the old identifier does not
   distinguish, so a consumer updating between the hop and the bump is told
   it is already current over bytes that changed.

## What the release hop must never do

- **Push the release branch directly.** This command never direct-pushes the
  `release` role's branch. The release hop opens a PR into it — from `<src>`
  itself when the merge is content-trivial, otherwise from a promotion branch
  — and never pushes `<dst>`; that is this command's whole mechanism. The one
  path that may advance release **unattended** is a repo's own promotion
  automation where its recorded topology decision says so (this repo's
  nightly `dev → main`, ADR 0003 as amended — see its infrastructure asset);
  how that automation lands the hop, PR or otherwise, is its script's business
  and never this command's.
- **Auto-merge the release PR.** Opening it is this command's job; merging it
  is a human/CI act.
- **Repair a conflict or a red gate.** Both are stop conditions **at this
  altitude, and only at this one.** Altitude 1's posture is the opposite by
  decision: a builder landing its own ticket fixes the red it meets, because the
  work is its own and stopping stalls the tick. A release hop carries many
  tickets and owns none of them, so a red candidate is a finding against the
  source branch — fix it there and re-promote. A promotion that needs a code
  decision is a ticket, not a retry.
- **Push anything on a gate it did not read.** A hop that could not run the
  gate is a stop, not a pass — never treat an unrunnable gate as green. This one
  binds both altitudes: it is ADR 0022 point 2 restated, and nothing else stands
  behind a push.

## Escalating a stop

A stopped hop is a normal outcome, not an error. Report it: the source and
target branches, the conflicting files or the gate output tail, and the branch
and worktree left in place to inspect. A red gate on a candidate is a finding
against the **source** branch — fix it there and re-promote; never patch the
candidate. An **infrastructure** failure (a missing toolchain, absent
credentials, an unclean base) is a different outcome from a red tree: the gate
reserves an exit code for it, and it stops the run without filing blame against
the code. Where the repo has a tracker, file that
report as a ticket through `tracker` so it is not lost when the
session ends, carrying exactly one assurance level chosen per `authoring`
→ *Choosing assurance*. Where it does not, the report to the operator is the
record.

## Reduced by decision, not by omission

ADR 0003's 2026-07-23 amendment named this path explicitly reduced — no bounded
repair, no state machine, no ledger — and ADR 0015 made it the only path. Do not
"complete" it back into a mirror of the audited lifecycle it replaced: a
promotion needing conflict classification or a repair budget is a promotion a
human should be looking at, and growing one here is how a command drifts into a
second, unaudited implementation of a thing that was deliberately retired.
