<!-- guidance:process-harness@0.12.0 -->
# How work happens here

This is the **one shared process** for working in a repo set up with this guidance. It is universal: everything specific to *this* repo — stack, commands, paths, tracker, principles, and which **layers** are on — lives in [`CONTEXT.md`](CONTEXT.md). Read that first, then this.

There is a single surface and a single process. What used to be a `standard` vs `harness` *profile* split is retired: repos differ by **per-repo configuration** (`CONTEXT.md` `layers:`), not by a profile. The guidance files referenced below (`skills/`, `agents/`, `commands/`) are version-stamped; do not rewrite their content here — point to them.

## Layers — what varies between repos

A repo turns capabilities on or off in its `CONTEXT.md` `layers:` block. The process below is written once and reads conditionally on these:

| Layer | On | Off |
|---|---|---|
| `feature_specs` | The as-built record is a **feature spec** in `specs/features/` (use `templates/feature.md`); the reviewer records what shipped there. | The as-built record is the **design doc / `SPEC.md`** — an infrastructure repo's behaviour *is* its design, so the design spec is the canonical record. |
| `design_system` | Frontend work uses the repo's design system; the `design-system` skill applies. | No design system; `design-system` does not engage. (`ux-design` is **not** gated by this layer — it applies wherever there is a user-facing surface.) |

**The tracker is a field, not a layer.** `CONTEXT.md`'s top-level `tracker:` (`linear` | `github` | `none`) is the single switch for whether a tracker is wired and which backend, and the `tracker` skill is the backend-neutral protocol every lifecycle step routes through. It is deliberately not in the table above: a layer turns a capability on or off, whereas this selects between backends.

This repo's settings are in its `CONTEXT.md`. `design_system` is off wherever there is no design system. `feature_specs` is a per-repo choice about the **shape of the as-built record**: a **product** repo typically turns it on; an infrastructure tool may leave it off and let its design docs stand as the record. The harness itself sets `feature_specs: true` — it dogfoods the feature-spec record it publishes.

## The shape of a task

Work is spec-driven with minimal ceremony. Three specs serve three moments (`spec-authoring`): a **proposal spec** (`specs/proposals/`) for an idea not yet confirmed, a **change spec** (the tracker issue) for one piece of work, and the **as-built record** — a feature spec (`feature_specs` on) or the design doc / `SPEC.md` (`feature_specs` off). The full flow is in `spec-driven-development`; the short version:

0. If the work is unconfirmed or too big for one change, `/propose` it first and get it decided. Small, clear work skips this.
1. The tracker issue is the front door. Open it, move it to In Progress. Route every tracker operation through the `tracker` skill, which reads `CONTEXT.md`'s `tracker:` field and dispatches to the matching provider recipe. (The tracker is the queue — there is no `manifest.yaml`.)
2. Read the relevant as-built record before changing behaviour — the feature spec, or `SPEC.md` / `specs/` for an infra repo. It is the contract.
3. Write a change spec into the issue: problem, approach, **design** (data model / interface / scenarios), acceptance criteria, out of scope (`spec-authoring`).
4. Branch into a worktree (`worktree-isolation`) — never build on the default branch. Build test-first (`test-driven-development`), in scope (`code-quality`), against the principles (`engineering-principles`).
5. Hand to independent review. The reviewer checks output and process (`review-discipline`), records what shipped (to `specs/features/` when `feature_specs` is on, otherwise updates the design spec) **into the candidate**, and only then runs the verification gate independently and decides — the tree the verdict covers is the tree that merges (`review-discipline`'s *final-evidence ordering* rule).
6. Ship per the repo's branch model (`CONTEXT.md`), close the issue.

The load-bearing rules throughout — non-negotiable, and written out here so they bind even if no skill file gets opened:

- **Test-first.** Write the failing test before the code and watch it fail for the right reason (`test-driven-development`). A test added afterward proves nothing.
- **A measurable criterion needs a measuring test.** Any acceptance criterion stated as a quantity — query count, response time, payload size, error rate — needs a test that measures that quantity and asserts the bound. A structural change is not evidence it worked (`code-quality` Part C).
- **No completion claim without fresh evidence.** Run the gate (`CONTEXT.md`), read its output this session, and name the test that proves each acceptance criterion before you claim done (`code-quality` Part C).

## Separation of concerns

The builder writes the change spec and builds. The reviewer records what actually shipped. The agent that promises is not the agent that records delivery — this is what keeps the canonical record honest.

## Driving a ticket

The process is agent-led, and there is one way to drive it. Unattended, that is `/build <TICKET>` — implement, verify, review, and ship, end to end (`--engine codex` runs the review through Codex). Attended, it is the same lifecycle taken a step at a time: `/start → /review → /ship`. Both are available in every repo on this guidance, and neither depends on any tool beyond the agent host and the repo's own verify gate.

`/build` carries the assurance stages, the isolated review agent, and the evidence requirements. What it deliberately does not carry is a wall-clock budget or a run ledger: the bounds that matter are the review→fix stop rule (`review-discipline`) and the verify gate, both of which are properties of the work rather than of a runtime.

## Enforcement hooks

Two of this rulebook's rules are enforced mechanically rather than by prose. The verify gate writes a **gate marker** on green — a file named after the git **tree object** it verified, in the repository's git directory — and two Claude Code hooks read it:

| Hook | Event | Refuses |
|---|---|---|
| `gate-evidence-guard.js` | `Stop` | Ending a turn that claims the work is finished when no fresh marker covers the current tree of any worktree this session worked in — the session's own directory first, then the worktrees its transcript records it in, intersected with `git worktree list` for the same repository. |
| `push-target-guard.js` | `PreToolUse: Bash` | A `git push` whose **target** is a branch `CONTEXT.md` `branches:` declares, unless a fresh marker covers the tree of the commit being pushed. Deleting such a branch is refused outright, as is `--mirror` (it makes the remote match this clone, so it deletes any protected branch the clone does not hold); `--all` is refused wherever a protected branch exists to move. |

The marker is named by tree, not by session, so the claim it licenses is *the gate exited 0 over these exact bytes* — which one more edit invalidates and no rewording can talk past. **There is no exemption for a particular command:** `/ship`, `/routine` and `/promote` are authorised because they push a gated tree, which is the only authorisation a hook can actually check. Clearing either refusal is the same one move — run `CONTEXT.md`'s `commands.verify` where the claim is being made, and read its output.

The Stop hook can force exactly one extra turn per stop-chain; it is a nudge with a memory, not a lock. Both hooks fail **open** when they cannot run at all, and both say so on stderr. They are evidence plumbing, not an authority — anything with shell access can forge a marker — so the controls of record remain server-side branch protection and the gate output in CI. What they buy is that the default path now requires the gate to have actually run, and that faking it is a deliberate, visible act instead of a silent omission.

`BOOTSTRAP.md` installs both; a repo that wants neither removes the entries from its `.claude/settings.json`.

## Skills (the durable rules)

| Skill | When |
|---|---|
| `spec-driven-development` | The lifecycle. Everyone. |
| `spec-authoring` | Writing any spec (proposal / change / as-built) — the craft, incl. design. |
| `engineering-principles` | What every design and change is measured against. |
| `test-driven-development` | All implementation. Iron law. |
| `code-quality` | Building: scope, structure, verification. |
| `review-discipline` | Reviewing, and self-review before handoff. |
| `architecture` | Design decisions, recorded in the spec they govern. |
| `systematic-debugging` | Any failing test or bug. |
| `writing-quality` | Specs, decisions, any prose. |
| `worktree-isolation` | Any multi-commit work. |
| `tracker` | Any tracker operation — the backend-neutral protocol. Dispatches to `linear` or `github-issues`, and owns the proposals ledger. |
| `assessment-craft` | The methodology for any `/assess` pass (the steward). |
| `ux-design` | Designing, prototyping, or reviewing any user-facing surface — its flow, information architecture, and states. Any repo with a user-facing surface (independent of the `design_system` layer). |
| `design-system` | Frontend work without degrading the design system — only when the `design_system` layer is on. |

## Agents (who does the work)

Dispatch via the host tool's sub-agent mechanism; in tools without one, read the agent file and follow it.

| Agent | Role |
|---|---|
| `dev` | Implementation, test-first, in scope. |
| `reviewer` | The final gate; records what shipped. |
| `architect` | Data models, contracts, decisions. Produces designs, not code. |
| `steward` | Periodic health assessment; `/assess <scope>` selects code or architecture. |

## Commands

| Command | Does |
|---|---|
| `/propose <idea>` | Work an unconfirmed or large idea into a decided proposal, then spawn change specs. |
| `/bug <description>` | Capture a bug noticed in actual use straight to Todo — no escape hatch; the fix direction is already "make it match." |
| `/tweak <description>` | Capture a small upgrade straight to Todo, with an escape hatch to `/propose` when it turns out to carry a real decision or spawn more than one change. |
| `/start <TICKET>` | Set up the workspace and build through to review-ready. |
| `/review` | Run the final gate on the current branch. |
| `/ship` | Integrate and close, per the repo's branch model. |
| `/build <TICKET>` | Autonomous agent-led driver: implement, verify, review, and ship a ticket end-to-end (`--engine codex` runs the review through Codex). The unattended form of the `/start → /review → /ship` lifecycle. |
| `/promote <src> to <dst>` | Drive a promotion (`dev → staging → main`) with plain git — merge, gate, then publish — resolving `<src>`/`<dst>` against `CONTEXT.md` `branches:` roles. |
| `/decision` | Interactive sweep that drains tickets held for the operator's input — present each one, capture the operator's call, write it into the change spec, release the ticket. No build handoff. |
| `/routine` | One unattended build-cycle tick: discover the next actionable ticket (`work-discovery`), `/build` it, ship to the integration branch; hold the ticket on a red gate or conflict. The versioned home of the standing prompt scheduled runs paste. |
| `/digest` | Read-only morning report: input holds, overnight run outcomes, work parked for a verdict, entries new to the proposals ledger, operator errands. Never mutates ticket state. |
| `/assess <scope>` | Run the steward over the codebase — `code` or `architecture` (`--deep` for the broad pass) — and drain the proposals ledger with the operator. |
| `/update-guidance` | Pull upstream guidance changes into this repo. |

Three of these are front doors for work at a different moment, and the boundary is deliberate, not incidental: `/propose` **decides the unconfirmed** (an idea that needs a decision or is too big for one change); `/bug` / `/tweak` **capture the confirmed-small** (an adjustment to as-built behaviour, surfaced by actual use, filed straight to Todo through the shared `templates/adjustment.md`); `/start` **picks up the filed** (a ticket already on the board, ready to build). Do not run a confirmed bug or small tweak through `/propose`, and do not file an unconfirmed idea straight via `/bug`/`/tweak`.

## Command namespacing

The universal guidance commands own the **bare names** (`/start`, `/review`, `/ship`, `/propose`, `/promote`, `/decision`, `/routine`, `/digest`, `/assess`, `/update-guidance`) and mean the same agent-led process in every repo. A repo with its own slash commands namespaces them under a repo prefix (e.g. `/<repo> <verb>`) so they do not collide — the installer will not overwrite a command the repo already owns.

The collision that matters is a repo command whose name reads as a lifecycle step but means something else — a `/start` that launches the repo's own pipeline rather than beginning the agent-led process. Move it under the prefix before installing, or an agent reading `/start` in this document gets the wrong one. (`BOOTSTRAP.md` step 2 is where the installer stops on such a collision rather than clobbering it.)

## When you are confused

Open the ticket first — it is the front door. Then read `CONTEXT.md`, then the as-built record for the area you are touching (`SPEC.md` / `specs/` for an infra repo, the feature spec otherwise). For any user-facing task, `ux-design` to shape the surface; when the `design_system` layer is on, `design-system` to materialize it. For a cross-cutting design decision, the `architecture` skill and the architecture-principles spec.

## Updating the guidance

These files are version-stamped. To pull upstream changes, run `/update-guidance`. Do not hand-edit installed guidance files to fix a bug in them; fix it at the source so every repo benefits, then update. (This repo *is* the guidance source — fixes land here directly.)

When you notice a guidance defect, real process friction, or a feature idea while following this process, route it upstream: search existing issues first, then draft a GitHub issue (title + body) against the repo recorded as your guidance `source.repo` — resolved from `.guidance-lock.yaml`, never hardcoded — keeping the body scoped to the guidance itself, never the consumer's proprietary code, and surface the draft to the operator to review and send (never send it unattended). If you are in the source repo and can fix the defect at source, do that too — the issue stays the public record; fix-at-source is the resolution, not a substitute for filing. If there is no `.guidance-lock.yaml`, or its `source.repo` does not resolve, surface the feedback to the operator directly instead of guessing a URL.
