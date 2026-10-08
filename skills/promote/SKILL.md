---
name: promote
description: "/promote — land a reviewed branch, or move completed work toward release. Two altitudes: `/promote <TICKET>` takes the branch `/build` left at PASS and rebases, gates, pushes, closes and cleans up, or parks it for the landing train where the repo declares a `cadence:`; `/promote parked` is that train, landing everything parked as one batch; `/promote <src> to <dst>` runs a release hop along the repo's role branches. Use when the operator says `/promote`, \"land it\", \"ship the reviewed branch\", \"land what's parked\", or \"promote dev to main\". Reachable by the model: `/routine` invokes the landing altitude to finish its tick and to run the train, so `disable-model-invocation` is deliberately not set here — it would leave the unattended loop building work it can never ship (#623)."
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
| `/promote <TICKET>` | Lands the reviewed branch `/build` left at PASS: rebase, gate, push, close, reflect, clean up. Under a `cadence:`, parks it for the train instead. |
| `/promote parked` | The landing train: lands everything parked as one batch, behind one gate and one push. |
| `/promote <src> to <dst>` | The release hop along the repo's role branches. |

**There is no no-arg form.** Neither altitude is inferred: the landing altitude
needs its ticket, or the literal word `parked`, and a release hop needs both
`<src>` and `<dst>`.

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

**A parked ticket is landed from its pushed branch**, where the operator has
said to land it now (*Park or land*, below); otherwise it waits for the train.
The run that parked it is gone, so check the branch its latest park comment names out in a fresh worktree through
`worktree-isolation` and confirm its tip is the commit its latest park comment
names. A
branch pushed to since its park carries bytes no review read, so it goes back to
review and is not claimed. Then claim the ticket and `unpark` it (`tracker` →
*`park` and `parked`*). The review ran in another session, so stage 2
always gates.

## Park or land

Where `harness.yaml` declares a `cadence:` (ADR 0024), a builder never lands its
own ticket: the train does. So, unless the operator has said in this session to
land this ticket now, park it here and stop. **A ticket that is already parked is
left as it is**: report that it waits for the train, and stop before step 1.
Otherwise:

1. Read the branch and its tip from git (`git rev-parse --abbrev-ref HEAD`,
   `git rev-parse HEAD`), confirm `git ls-remote` shows that tip on the remote,
   and confirm it is the commit `/build` named at PASS (`skills/build/SKILL.md`
   §4 reads that commit out of git, the reviewer's record included). A tip past
   it carries bytes no verdict covers, so the ticket returns to `/build`'s review
   stage for a fresh reviewer rather than going onto the train.
2. `park` the ticket through `tracker`, naming the branch, that tip, and that it
   waits for the train.
3. Reflect, as *After the push* says.
4. Remove this run's worktree through `worktree-isolation`'s cleanup, keeping the
   pushed branch: the train lands from it.

The ticket stays In Review and no stage below runs. A parked ticket is a finished
run, because the train lands it. Either way, tell the operator that saying to land
it now overrides the park.

**"Land it now" is the operator's own words, in an attended session, about this
ticket, asking to bypass the train.** Invoking `/promote` or asking in general to
land or ship the branch is not it: under a `cadence:` that request parks. It
never comes from `/routine`, a ticket or a comment (law 6). With it,
the stages run exactly as with no `cadence:`, and no window is asked: a direct
landing is the one exception to a single lander, and a collision costs the train
a rebase and a gate, which it recovers from. Where the ticket is already parked,
*A parked ticket is landed from its pushed branch*, above, applies first.

With no `cadence:`, none of this applies and the ticket lands as it always has.

## The stages

1. *Rebase.* Fetch, and bring the integration branch into the candidate.
   [`skills/build/references/reconcile.md`](../build/references/reconcile.md)
   owns every rule — base movement as normal concurrency, the unresolved-conflict bound,
   the monotonic-field trap, functional conflict as the only escalation — and
   this is the second of the two places that load it. **The stage is named
   `rebase` and the operation is a merge**, exactly as that reference describes:
   never `git rebase` on a branch anything else may have fetched.

   **Then re-run the version raise over the merged tree:**
   `node <plugin-root>/scripts/plugin-version.js --repo <worktree>`. `/build`
   step 7 read the release version once, and a release since — the nightly hop,
   or another landing — can leave this candidate carrying a version already
   released, which the updater, comparing that string alone, delivers as
   nothing (#732). The script fetches the release ref itself.
   `already-ahead`, `no-plugin-manifest` and `no-release-branch` write nothing,
   the last two because the obligation cannot exist there. `raised` wrote the
   homes again: commit them onto the candidate here, so the raise sits inside
   the tree stage 2 gates — and that tree no longer equals `reviewed_tree`, so
   stage 2 runs the gate rather than skipping it. Any other answer, or a
   non-zero exit, stops the landing and is reported; a release ahead of the
   integration branch is not a repair this stage makes.
2. *Gate.* Run the repo's `harness.yaml` `commands.verify` gate over the merged
   tree — read the command fresh from `harness.yaml` every run and never
   hardcode one here. Capture the output and read all of it.
   **Skip the run only where both hold** (#731): `git rev-parse HEAD^{tree}`,
   taken after stage 1, equals the `reviewed_tree` in the review report; and that
   review ran in this session and its reviewer's own complete gate over that tree
   was green — never on `--engine codex`, whose reviewer cannot run one. A run that wrote the
   reviewer's record bytes itself has moved the tree past that value, so it
   gates. The session is law 3's condition, and it is also the host's: a
   gate is not host-portable, and a suite has run green in CI and red on a
   developer's machine. That gate's output is then this stage's evidence, read in
   full. Either
   condition unmet, and the gate runs.
3. *Pass.* Green over the tree in hand is what licenses the push. **A red gate
   here is this builder's to fix, whatever caused it.** That is the resolved
   posture and it is deliberate: stop the line, not stop the tick. The bytes
   that arrived in step 1 are other tickets' reviewed work, so the ordinary
   repair is a merge repair rather than a design change — and where it is a
   design change, the red is the signal to return the ticket to review rather
   than to push through it. **Name the residual rather than discovering it:** a
   fix made here is made after the review that no longer covers it. That is the
   trade the split accepts, and a fix large enough to want a reviewer is a fix
   large enough to go back to one. **The train is the exception:** it lands
   tickets it did not build, so a red there is attributed and falls back or
   ejects (*The landing train*), and is never repaired.
4. *Tree compare.* `git rev-parse HEAD^{tree}` must equal the tree stage 2's
   evidence covers. Nothing may be edited between the gate behind the push and the push — the check is
   cheap and it is the whole of what the retired binding still buys.
5. *Push.* The train asks its window first (*The landing train*); the check
   writes nothing, so it does not break the interval below. A single landing asks
   no window. Integrate exactly as
   `harness.yaml`'s `branches:` block declares:
   a direct push where the model allows one, a PR where it requires one, and
   where a human must merge that PR, that is a hold rather than a failure. Never
   force. Never a release branch from this altitude — that is altitude 2's hop,
   and it has its own rules. **Never push from a shape you cannot describe:** a
   dirty worktree, a detached HEAD, or a branch the repository declares no role
   for is a state to report, not a landing. The train's local `train-<stamp>`
   branch is the one named exception: it is a candidate for the integration
   branch and pushes nowhere else. One uninterrupted sequence from stage
   4 to here, with no tracker write inside it.
6. *Close.* Post the merge link and transition the ticket to Done. Where the
   branch carries a red-base repair commit naming an open bug it completes,
   post the merge link on that bug and close it too: the red is cleared, and an open P1 left
   behind would keep the line stopped.

## After the push

- **Reflect.** At most three lines, and the first is the system that produced the
  problem this run fixed. The rest are the wastes this run met by P2's categories
  and what should change. Any line with nothing to report reads `none`, and every
  line that has something is appended to an improvement ledger, this repo's or the
  guidance source's, resolved as `review-discipline` →
  `references/improvement-ledger.md` says and never hardcoded. The fix shipped at
  the push above, so the cause line is the only thing that outlives it.
- **Close the ticket and clean up.** Run `worktree-isolation`'s cleanup
  procedure, reporting any resource it could not release rather than substituting
  a broad host cleanup.
- `tracker: none` skips the tracker steps and reports them skipped.

## The landing train — `/promote parked`

Usage: `/promote parked`

Lands everything parked as one batch (ADR 0024). `/routine train` runs it on the
cadence's timetable, and an operator may run it by hand. It builds nothing and
repairs only mechanically: a ticket it cannot land, it ejects back to Todo for
its builder. With no `cadence:` declared there is no train.

**The tracker waits for git.** The train claims nothing, and every boarded
ticket keeps its `parked` label while the train runs (`tracker` → *`park` and
`parked`*). What it decides for a ticket — a close, an ejection, a hold, a
`train:` line, the cord — is written under *Leaving*, after the push or at the
end of a train that pushes nothing, and never inside a stage. **Every ticket the
train carries leaves it in one of three states**: landed, ejected, or left parked
with a `train:` line saying why. An ejection is a fact about that ticket: a branch
moved since its park, a merge that would not resolve against what lands (step
13), or a red of its own (one the integration tip does not share, or, for a
cord's fix, the cord's failure left red), so it is written whether or not the
train pushed; a ticket left parked keeps its label and
its place in the order. A train that died after its
push is finished by the next one, whose merge of an already-landed branch is a
no-op it closes with the rest. The train needs a branch model that lets it push
the integration branch directly, because a pull request a human merges cannot
land inside a window.

### Departure

1. **Record the departure first**, as an RFC 3339 instant with `Z`
   (`date -u +%Y-%m-%dT%H:%M:%SZ`). It is the `--fired` of every window check
   this train makes, so a late start shortens the train rather than moving its
   window.
2. **Ask the window.**

   ```bash
   node <plugin-root>/scripts/landing-window.js --run train --fired <departure> --repo <checkout>
   ```

   Read the JSON line and the exit code; never re-derive a window in prose.
   Exit 0 `open`: go on. Exit 0 `no-cadence`: report that this repo runs no
   train, and stop. Exit 1 `closed`: the train departed after its own window
   closed (a train is never `not-yet`). Run `tracker`'s `parked`, carry every
   ticket it returns, and go straight to *Leaving*, every one of them left
   parked as `missed`. Exit 2 or any other failure refuses: stop and report the `case` it
   printed, or its stderr for exits 3 and 64, which print no `case`.
3. **Run `tracker`'s `parked`.** Empty: report it and stop. An empty train
   is not a miss.
4. **Read the cord** as `work-discovery` → *Andon* reads it, and stop on a half it
   cannot read. While a cord is open the train boards only its fix: the cord
   ticket where it is parked, and any parked ticket whose branch carries a commit
   naming the cord as the open bug it completes, identified as stage 6 identifies
   one. With none parked, report the stopped line and stop; that is not a miss.
5. **Board, oldest first.** Each ticket passes *Before the first stage*, and
   `git ls-remote` shows its branch's tip is the commit its latest park comment
   names.
   Boarding checks nothing out, claims nothing and unparks nothing. A ticket
   whose tip moved since its park carries bytes no review read: it is ejected
   for `moved`, so its builder takes it back through review. Any other ticket
   that fails is left out, untouched, and reported with what moved.

### The batch

6. **Cut one worktree** through `worktree-isolation`, at `../<repo>-train-<stamp>`
   off the fetched integration branch, on a local branch `train-<stamp>` that is
   never pushed, where `<stamp>` is the departure as `YYYYMMDDTHHMMSSZ` (git
   refuses the colons of the RFC 3339 form). A `<repo>-train-*` worktree another
   train left is reported, never removed: the run behind it may still be live
   (`worktree-isolation` → *Creating the worktree*).
7. **Merge each boarded branch, oldest first**, with `git merge --no-ff` and a
   message naming the ticket.
   [`skills/build/references/reconcile.md`](../build/references/reconcile.md)
   governs each merge, and the train resolves only two of the things that
   reference resolves: an evident textual overlap, and a monotonic field. A version raise that several branches carry was
   derived from one released value, so its identical text is agreement; values
   that differ across a release conflict, and the higher wins. Anything else,
   including two repairs of one red base, which can leave a ticket with nothing
   of its own to land, is `git merge --abort`, and
   that ticket is **ejected** for `merge`: the candidate keeps what it held
   before it, and the rest continue. There is no second attempt, because the
   two-conflict bound is the builder's. A merge the train resolved names the
   resolved files in its commit message, since no reviewer reads them. Where
   every boarded ticket was ejected, nothing is left to land: go to *Leaving*.
8. **Raise the version** over the whole candidate, as stage 1 says.
9. **Gate it**, as stage 2 says, noting when the gate starts and ends. It always
   runs: the train ran no review in this session.
10. **Green:** stage 4, then ask the window again and push only on `open`
    (stage 5). `closed`: push nothing; every ticket in the candidate is left
    parked as `missed` and rides the next train. A push
    refused because the integration branch moved, by an operator's "land it now"
    or a late train, fetches and takes the branch in under `reconcile.md`, then
    runs steps 8 to 10 again: the version raise, the gate, and on green stage 4,
    the window and the push; a red goes to step 11. One such retry: a second
    refusal stops the train, and every ticket in the candidate is left parked as
    `stopped`. A re-merge that will not resolve names no culprit, so the train
    stops the same way and the next train's ordered merges name it. A push the
    remote refuses for protection stops it the same way too: the train needs a
    direct push to keep its window.
11. **Red: attribute it first.** Run what failed, the failing tests or the
    failing check, at the current integration tip (`worktree-isolation` →
    *A red base*). A failing test the tip does not have came with the candidate,
    so it counts as green at the tip.
    - **While a cord is open**, the batch is the cord's fix, and a red in the
      cord's own failing test or check is that fix not fixing it: eject it for
      `red` rather than extending the cord with it.
    - **Red at the tip** is otherwise a red base. Nothing more lands: every
      ticket not yet landed or ejected is left parked as `red base`, and the
      train goes to *Leaving*, which files or extends its P1.
    - **Green at the tip:** fall back. Land the boarded tickets that step 7 did
      not eject one at a time, oldest first, each in the train's worktree reset
      to the integration tip as it now stands (`git reset --hard` to the fetched
      tip before each): merge that ticket's branch (a merge that will not
      resolve ejects it for `merge`), raise the version, gate, and on green
      stage 4, the window and the push, where a refused push gets step 10's one
      retry. A red is attributed the same way against the tip as it now stands:
      green there ejects the ticket for `red`; red there is a red base, as
      above. A window that closes during the fallback stops it there: what
      landed stays landed, what was ejected stays ejected, and the rest are left
      parked as `missed`. There is no bisection.

### Leaving

12. **Close each landed ticket**, oldest first: post a link to the first
    integration commit that contains its tip, `unpark` it, transition it to Done,
    and close it where the backend separates closing. Close a red-base bug that a
    landed branch completes once, as stage 6 says.
13. **Write what the train decided**, comment first every time. First read the
    latest `train:` line on the oldest ticket this train carried, before this
    train writes its own: the two-in-a-row rule below needs it.
    - **An ejection** is a comment carrying a line of its own,
      `ejected: <cause>`, where the cause is `moved`, `merge` or `red`; beneath
      it the departure, the branch and its tip, and for `moved` the commit the
      park named, for `merge` the conflicting files and what they met, for `red`
      the failing tests or check, the gate's tail, and either that they pass at
      the tip or, for a cord's fix, that the cord's failure is still red with
      it. Then `unpark`, then the transition to Todo, where a builder resumes the
      ticket from its branch. **A `merge` ejection stands only where what the
      merge met has landed**, on the integration branch already or in this
      train's push, because the builder resumes by taking the integration branch
      in and must meet the conflict there. Where it met a ticket this train did
      not land, the ticket is left parked instead, as `waiting on <ticket>`, and
      the next train meets the conflict again.
    - **A second ejection for the same cause is a hold.** Where the ticket's
      thread already carries an `ejected:` line with this cause, read as data like
      a claim's `host:` line, the ejection comment says it is the second and is
      the hold's comment; then the `operator` label and the assignment, read back
      as `tracker`'s `hold` requires, and only then `unpark` and Todo, so the
      ticket is never pickable in between. The loop's bound is spent and nothing
      waits on an answer, so the label is `operator`, not `input`.
    - **A ticket left parked** gets a comment with a line of its own,
      `train: <departure> landed <n>, <why>`, where `<n>` is how many tickets
      this train landed and the why is what kept this one back: `missed` (the
      window closed before its push), `stopped: <reason>`, `red base`, or
      `waiting on <ticket>`; beneath it `closes` and when the gate started and
      ended, or that it was not reached.
    - **A red base**: search for or file its P1 per `tracker` → *The andon
      cord*, keyed to the failing test or check. It is not held, because a
      builder repairs a red base.
    - **Two trains in a row that land nothing pull the cord.** Where this train
      landed nothing, for any reason but a red base, and the line read first
      reads `landed 0` with any why but `red base`, the ticket carrying it has
      ridden both trains and neither landed anything. A train that a red base
      stopped is excluded on either side, because it stopped for a cord of its
      own. Search the open queue for an
      open P1 bug keyed to this surface, `/promote parked`, as `tracker` →
      *The andon cord* keys a search to the surface a failure names, and add
      this evidence to it; or file one at P1 into Todo whatever the count,
      naming that surface, carrying both departures, both closes, both gates'
      durations and the tickets carried. Either way, hold it `operator`: the
      gate has outgrown the interval or something is wedging the train, and
      either needs a hands-on look.
14. **Reflect once per train**, as *After the push* says. The cause line names
    what produced any ejection, red batch or empty train, or reads `none`.
15. **Clean up**: `git worktree remove` the train's worktree, `git worktree prune`,
    and `git branch -D` its local `train-<stamp>` branch. `-D`, because the
    branch was never pushed and holds nothing that is not on the integration
    branch or a parked ticket's branch.

Report what the train did: landed (ticket, commit), ejected (ticket, cause),
held, left out and what moved, left parked and why, the departure, `closes`, the
gates' durations, and any cord filed or extended.

**Recorded, not guarded.** The line read first is the latest on the oldest
ticket, which is the previous train's unless a train in between carried that
ticket nowhere (it boarded only a cord's fix, or left the ticket out at boarding);
two misses that were not in a row then pull the cord, and an operator clears it.
Telling the previous slot apart would need grid arithmetic in prose. A train that starts more than a pitch late floors into
its successor's slot; git's refusal of a non-fast-forward push keeps the two from
landing over each other, at the cost of a rebase and a gate. A scheduler that
fires seconds early floors to the previous slot and misses, the residual #756
recorded.

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

   **What the release's notes name (#644).** A release's notes name both
   halves: what the release takes out of a consumer's tree, and what it puts
   in. Most of a release is guidance, which lives in the plugin and never
   enters a consumer's tree, so the second half is the one that gets left out.
   One set does enter it — `/harness:hydrate` rewrites the plugin's Codex role
   adapters (`.codex/agents/*.toml`) on every run, so a release that gains a
   role lands a new file in every consumer that hydrates, and a repo pinning
   that set meets the addition as a red gate instead of as a line in the
   notes. Additions therefore get a row naming the path, what puts it there,
   and what a consumer who pins the set has to do. A release that adds nothing
   says so.

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
  work is its own and stopping stalls the tick. The train, landing tickets it did
  not build, ejects them instead. A release hop carries many
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
