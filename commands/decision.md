<!-- guidance:decision@0.2.0 -->
# /decision — drain the tickets held for your input

Usage: `/decision`

The unattended Build loop defers a ticket it cannot action: `harness defer`
posts a comment, applies a hold label (`input` / `operator`; ADR 0006's three
kinds, consolidated to two by ADR 0015), and assigns the ticket to the operator — the machine-readable "a human
holds this" signal `work-discovery` skips on later ticks. That outbound half
works on its own. This is the **inbound** half: an interactive sweep that pulls
every ticket held for a judgment call, presents it, captures the operator's
call, writes the resolution into the ticket, and releases it back to the
queue — so the held pile is drained by running a command, not by retyping an
ad-hoc prompt into a fresh session.

**This command is interactive.** Every other command in this guidance is
drivable unattended; `/decision` is not — it exists specifically to put a human
judgment call in the loop. Run it when you (the operator) are at the keyboard,
not from an unattended routine.

## Scope: `input` holds

`/decision` selects the **`input`** hold kind — the operator must supply
something the run cannot (ADR 0015: an answer, a judgment call, a credential,
a fact). Within the sweep, each ticket resolves one of two ways: an item
**answerable from the ticket alone** gets the operator's call captured and
released here; an item that needs the operator to **go do something first**
(supply a credential, stand up infrastructure) is skipped and stays held —
clear those by doing the thing, then answering. It never surfaces
**`operator`** holds — an interactive, hands-on session is needed (setup, a
visual check); clear those at the keyboard on the actual task, not here.

This selection is by hold label alone — never a re-triage of what a ticket
"really" needs. That classification was made once, at defer time, and
restating it here would let this sweep get it wrong silently on a ticket a
deferring run already classified correctly.

## The judgment is not restated here

Which tickets are **clearable**, what counts as a valid resolution, and what
**released** means (the change spec updated, the hold label removed, the
operator unassigned) is `work-discovery`'s "Return path" section — the single
home of that judgment, the same skill `/harness routine build` reads for the
outbound half. This command owns only the control flow around it: pull, order,
present, capture, write, release, stop.

## The loop

**Step 0 — resolve scope.** Read `CONTEXT.md`: the tracker backend
(`tracker:`) and the Build queue (`repo.project`, when set — otherwise the
whole tracker queue, same nullable-scope rule `work-discovery` uses).

**Step 1 — pull the held-for-input pile.** List open tickets in scope
carrying the `input` label **and** assigned to the operator (the viewer) —
both conditions, matching the exact state a deferral leaves a ticket in. (In
an un-migrated repo, also pull the retired `decision` label and treat it as
`input`.) This is a read, not a lifecycle mutation, so it is done directly
against the tracker rather than through a verb:

- **`tracker: github`** — `gh issue list --repo <github.repo> --label input
  --assignee @me --state open --json number,title,url,body,updatedAt` (add
  `--search 'project:<github.project>'` when `repo.project` is set and the
  queue should scope to one board).
- **`tracker: linear`** — the `linear` skill's issue-search recipe, filtered to
  `labels: { name: { eq: "input" } }`, `assignee: { isMe: { eq: true } }`,
  and (when `repo.project` is set) `project: { name: { eq: <repo.project> } }`.

Empty pile → report it and **stop**. Do not manufacture a decision to make —
an honest empty result is correct output, not a failure to route around.

**Step 2 — order the pile.** Apply the `work-discovery` ranking (dependencies
gate, priority breaks ties, ID is the fallback order) — the same ordering the
Build loop uses to pick its next ticket, so triage and build read the queue
the same way.

**Step 3 — present one at a time.** For the next ticket in order, show:

- Title, URL, and current change-spec body (context for what's being decided).
- The deferring comment — the reason text `harness defer --reason` posted —
  since that comment names exactly what the ticket needs. Read it via
  `gh issue view <n> --comments` (github) or the `linear` skill's comment-read
  recipe (linear); take the **latest** comment carrying the hold's triage
  reason if more than one exists.

Ask the operator for their call. Do not answer for them, and do not proceed
past a ticket the operator wants to skip for this session (leave it held; move
to the next).

**Step 4 — capture and release.** Once the operator gives a call:

1. Compose the resolution text from what they said.
2. Release the ticket through the verb — never a hand-rolled tracker write
   (the risk the proposal flagged: this needs write access across both
   backends, so it is a bounded, named verb mirroring `defer`, not ad-hoc
   GraphQL/`gh` mutation calls):

   ```bash
   harness release <TICKET> --resolution <text> [--resolution-file <path>]
   ```

   `release` writes the resolution into the ticket's change spec (appending or
   replacing a `## Resolution` section — so the answer is where an agent
   building the ticket cold will actually see it, not buried in a comment
   thread), removes the `input` label, and unassigns the operator — the
   full "released" definition `work-discovery` names, done as one audited
   write. The audit trail is the tracker issue itself — the resolution in the
   body, the label gone, the assignment cleared — not a ledger event (#338).
3. If `release` refuses (not on the Build queue, tracker error) — report the
   refusal and its `reason`; do not work around it by hand-rolling the write
   it exists to replace.

**Step 5 — re-pick or stop.** More tickets in the ordered pile → go to step 3.
Pile exhausted → **stop**.

## No build handoff

`/decision` never hands a released ticket to `/harness run` or `/build`. It
writes the answer and returns the ticket to Todo; the Build arm picks it up on
its own next tick. Sweeping and building are two separate jobs — conflating
them would make this command block on a full build cycle for every resolved
decision, defeating the point of running the sweep interactively and quickly.

## A released ticket that is still not actionable

If, after release, the ticket is not actually wholly actionable — the
resolution given did not fully resolve it — do not leave it half-cleared.
Re-defer it through the normal path (`harness defer <TICKET> --reason <text>
[--needs input|operator]`), same as any other not-yet-actionable
ticket the Build loop would find. `work-discovery`'s Return path section calls
this **re-deferred**: a fresh comment + label + assignment, not a `/decision`
sweep that quietly reopens the ticket without saying why.

## Report

At the end of the run (empty pile, operator stop, or pile exhausted), print:

- Tickets released this session (identifier, one-line summary of the call).
- Tickets left held (skipped this session, or re-deferred after an incomplete
  resolution).
- The remaining `input`-held pile size (0 if drained).

## Related

- `work-discovery` — the judgment this command delegates to: which holds are
  clearable, and what "released" means.
- `harness defer` / `harness release` — the audited writes on either side of a
  hold's lifetime.
- ADR 0006 — the hold kinds this command's scope rests on (three at origin;
  consolidated to two by ADR 0015).
