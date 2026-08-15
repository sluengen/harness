<!-- guidance:promote@0.4.0 -->
# /promote — move completed work toward release

Usage: `/promote <src> to <dst>`

Promotion moves completed work toward release — `dev → staging → main` on the
universal three-tier topology (ADR 0003). This command is the versioned caller:
it transcribes the loop once, so an agent runs `/promote` instead of re-deriving
it from prose each time.

There is **no no-arg form** — a release hop is deliberate, not inferred. Both
`<src>` and `<dst>` are required.

The mechanism is plain git plus the repo's own verify gate. ADR 0015 retired the
audited `harness promote` verb loop that used to drive this; the topology and its
nightly automation are kept, and this reduced path is now the only one. It has no
promotion id, no ledger row, and no resumable state: a conflict or a red gate
stops the hop cold. The audit trail is ordinary git history and the PR.

## Argument resolution

Each word resolves against this repo's `CONTEXT.md` `branches:` roles first,
falling back to a literal branch ref:

1. If the word is one of the three canonical role keys — `integration`,
   `staging`, `release` — and `CONTEXT.md` defines that role, resolve to the
   branch name it names.
2. Otherwise, use the word itself as a literal branch ref.

This is why the same invocation shape works everywhere, whatever a repo calls
its branches. Take this repo's own roles (`integration: dev`, `staging:
staging`, `release: main`):

- `/promote dev to staging` — the nightly stabilization hop. `dev` matches no
  role key, so it is used literally; `staging` matches the `staging` role,
  which also resolves to `staging` here. Either path lands on the same pair.
- `/promote staging to main` — the deliberate release hop. `staging` resolves
  via the role; `main` matches no role key and is used literally.
- `/promote integration to release` resolves identically to the `dev to
  staging` example above — the canonical role names always work too.

Now take a repo whose roles are `integration: develop`, `staging: staging`,
`release: production` — a different repo, different branch names for the same
three roles. **The identical invocation drives it unchanged:**
`/promote develop to staging` — `develop` matches no role key so it is used
literally (and happens to be that repo's actual integration branch); `staging`
resolves via the role to `staging`. No per-repo command variant is needed; the
resolver is what changes, not the command.

## The loop

1. **Fetch and branch.** `git fetch origin`, then create a promotion worktree
   off the **target** branch (`<dst>`, resolved above) at its remote tip. Work
   in the worktree, never in the main checkout.
2. **Merge the source in.** Merge `<src>` into it. **On conflict: stop and
   report** — the conflicting files and a diff summary. No repair attempt,
   bounded or otherwise; this path has no repair authority at all.
3. **Gate it.** Run the repo's `CONTEXT.md` `commands.verify` gate in that
   worktree — read the command fresh from `CONTEXT.md` every run and
   never hardcode a gate command here, since this path keeps no state to
   remember one in. Capture the output. **On red: stop and report** the
   captured output. No retry.
4. **On green, publish.** The hop selects the mechanism:
   - `<dst>` is an **intermediate** branch (e.g. `staging`): push the merged
     tree directly to the target ref. No PR — the gate already made the call.
   - `<dst>` is the **release** branch (e.g. `main`): push only the promotion
     branch, never the target directly, and open a PR into the target carrying
     the commit range and the gate evidence. A human merges it.

## What this command must never do

- **Push the release branch directly.** `main` (whatever the repo's `release`
  role names) is never direct-pushed, by anyone. The release hop pushes a
  promotion branch and opens a PR; that is the whole mechanism.
- **Auto-merge the release PR.** Opening it is this command's job; merging it
  is a human/CI act.
- **Repair a conflict or a red gate.** Both are stop conditions. A promotion
  that needs a code decision is a ticket, not a retry.
- **Push anything on a gate it did not read.** A hop that could not run the
  gate is a stop, not a pass — never treat an unrunnable gate as green.

## Escalating a stop

A stopped hop is a normal outcome, not an error. Report it: the source and
target branches, the conflicting files or the gate output tail, and the branch
and worktree left in place to inspect. Where the repo has a tracker, file that
report as a ticket through the `tracker` skill so it is not lost when the
session ends, carrying exactly one assurance level chosen per `spec-authoring`
→ *Choosing assurance*. Where it does not, the report to the operator is the
record.

## Reduced by decision, not by omission

ADR 0003's 2026-07-23 amendment named this path explicitly reduced — no bounded
repair, no state machine, no ledger — and ADR 0015 made it the only path. Do not
"complete" it back into a mirror of the audited lifecycle it replaced: a
promotion needing conflict classification or a repair budget is a promotion a
human should be looking at, and growing one here is how a command drifts into a
second, unaudited implementation of a thing that was deliberately retired.
