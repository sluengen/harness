---
name: promote
description: "/promote — move completed work toward release. Use when the operator invokes `/promote` or asks to run that workflow. Operator-triggered only; the model does not fire it."
disable-model-invocation: true
---

The portable plugin root is two directories above this SKILL.md. Resolve embedded paths beginning `skills/`, `agents/`, `templates/`, `hooks/`, or `.codex/` from that root; resolve repository artifacts from the workspace root.

# /promote — move completed work toward release

Usage: `/promote <src> to <dst>`

Promotion moves completed work toward release along the role branches the
repo's `harness.yaml` `branches:` block declares — topology is per-repo
configuration (ADR 0003 as amended): `integration → release`, with a `staging`
role between them only where something deploys to a staging environment. This
command transcribes the loop once, so an agent runs `/promote` instead of
re-deriving it from prose each time.

There is **no no-arg form** — a release hop is deliberate, not inferred. Both
`<src>` and `<dst>` are required.

The mechanism is plain git plus the repo's own verify gate. ADR 0015 retired the
audited `harness promote` verb loop that used to drive this; the topology and its
nightly automation are kept, and this reduced path is now the only one. It has no
promotion id, no ledger row, and no resumable state: a conflict or a red gate
stops the hop cold. The audit trail is ordinary git history and the PR.

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

1. **Fetch and branch.** `git fetch origin`, then create a promotion worktree
   off the **target** branch (`<dst>`, resolved above) at its remote tip. Work
   in the worktree, never in the main checkout.
2. **Merge the source in.** Merge `<src>` into it. **On conflict: stop and
   report** — the conflicting files and a diff summary. No repair attempt,
   bounded or otherwise; this path has no repair authority at all.
3. **Gate it.** Run the repo's `harness.yaml` `commands.verify` gate in that
   worktree — read the command fresh from `harness.yaml` every run and
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

- **Push the release branch directly.** This command never direct-pushes the
  `release` role's branch. The release hop pushes a promotion branch and opens
  a PR; that is this command's whole mechanism. The one path that may advance
  release **unattended** is a repo's own promotion automation where its recorded
  topology decision says so (this repo's nightly `dev → main`, ADR 0003 as
  amended — see its infrastructure asset); how that automation lands the hop,
  PR or otherwise, is its script's business and never this command's.
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
