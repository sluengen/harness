<!-- guidance:process-harness@0.4.4 -->
# How work happens here

This is the **one shared process** for working in a repo set up with this guidance. It is universal: everything specific to *this* repo — stack, commands, paths, Linear workspace, principles, and which **layers** are on — lives in [`CONTEXT.md`](CONTEXT.md). Read that first, then this.

There is a single surface and a single process. What used to be a `standard` vs `harness` *profile* split is retired: repos differ by **per-repo configuration** (`CONTEXT.md` `layers:`), not by a profile. The guidance files referenced below (`skills/`, `agents/`, `commands/`) are version-stamped; do not rewrite their content here — point to them.

## Layers — what varies between repos

A repo turns capabilities on or off in its `CONTEXT.md` `layers:` block. The process below is written once and reads conditionally on these:

| Layer | On | Off |
|---|---|---|
| `feature_specs` | The as-built record is a **feature spec** in `specs/features/` (use `templates/feature.md`); the reviewer records what shipped there. | The as-built record is the **design doc / `SPEC.md`** — an infrastructure repo's behaviour *is* its design, so the design spec is the canonical record. |
| `design_system` | Frontend work uses the repo's design system; the `design-system` skill applies. | No design system; `design-system` does not engage. (`ux-design` is **not** gated by this layer — it applies wherever there is a user-facing surface.) |
| `linear` | Linear is the task queue and front door. | The repo's own tracker stands in for the Linear steps. |

This repo's settings are in its `CONTEXT.md`. `design_system` is off wherever there is no design system. `feature_specs` is a per-repo choice about the **shape of the as-built record**: a **product** repo typically turns it on; an infrastructure tool may leave it off and let its design docs stand as the record. The harness itself sets `feature_specs: true` — it dogfoods the feature-spec record it publishes.

## The shape of a task

Work is spec-driven with minimal ceremony. Three specs serve three moments (`spec-authoring`): a **proposal spec** (`specs/proposals/`) for an idea not yet confirmed, a **change spec** (the Linear issue) for one piece of work, and the **as-built record** — a feature spec (`feature_specs` on) or the design doc / `SPEC.md` (`feature_specs` off). The full flow is in `spec-driven-development`; the short version:

0. If the work is unconfirmed or too big for one change, `/propose` it first and get it decided. Small, clear work skips this.
1. The Linear issue is the front door. Open it, move it to In Progress. (Linear is the queue — there is no `manifest.yaml`.)
2. Read the relevant as-built record before changing behaviour — the feature spec, or `SPEC.md` / `specs/` for an infra repo. It is the contract.
3. Write a change spec into the issue: problem, approach, **design** (data model / interface / scenarios), acceptance criteria, out of scope (`spec-authoring`).
4. Branch into a worktree (`worktree-isolation`) — never build on the default branch. Build test-first (`test-driven-development`), in scope (`code-quality`), against the principles (`engineering-principles`).
5. Hand to review. The reviewer checks output and process (`review-discipline`), runs the verification gate independently, and — on PASS — records what shipped (to `specs/features/` when `feature_specs` is on, otherwise updates the design spec).
6. Ship per the repo's branch model (`CONTEXT.md`), close the Linear issue.

The load-bearing rules throughout — non-negotiable, and written out here so they bind even if no skill file gets opened:

- **Test-first.** Write the failing test before the code and watch it fail for the right reason (`test-driven-development`). A test added afterward proves nothing.
- **A measurable criterion needs a measuring test.** Any acceptance criterion stated as a quantity — query count, response time, payload size, error rate — needs a test that measures that quantity and asserts the bound. A structural change is not evidence it worked (`code-quality` Part C).
- **No completion claim without fresh evidence.** Run the gate (`CONTEXT.md`), read its output this session, and name the test that proves each acceptance criterion before you claim done (`code-quality` Part C).

## Separation of concerns

The builder writes the change spec and builds. The reviewer records what actually shipped. The agent that promises is not the agent that records delivery — this is what keeps the canonical record honest.

## Execution options

A ticket can be driven two ways within the one surface — the choice is per-invocation / per-repo, not a profile:

- **Harness tooling** — `/harness run <TICKET>`, the audited verb loop (`start → review → close`) whose `review` is the Codex review. Available where the repo hosts the harness app.
- **Agent-led** — `/build` (with `--engine codex` to opt into the Codex review), or the `/start → /review → /ship` sequence, driven by the agent directly.

Use the option your repo provides; its `CONTEXT.md` says which. A repo without the harness app uses the agent-led option — `/build` is available everywhere.

**If this repo is the harness** (its `CONTEXT.md` `repo.name` is `harness`): it is the **source** of the canonical `/build` command and carries its full body for distribution, but drives its *own* tickets with `/harness run` (whose `review` already does the Codex review) — or `/start → /review → /ship` as a backup — and does **not** invoke `/build` on its own tickets. This rule is specific to the harness repo; elsewhere `/build` is the normal agent-led option.

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
| `linear` | Reading and updating Linear. |
| `assessment-craft` | The methodology for any `/assess` pass (the steward). |
| `guidance-coherence` | Domain standards for the `/assess system` scope (guidance coherence). |
| `ux-design` | Designing, prototyping, or reviewing any user-facing surface — its flow, information architecture, and states. Any repo with a user-facing surface (independent of the `design_system` layer). |
| `design-system` | Frontend work without degrading the design system — only when the `design_system` layer is on. |

## Agents (who does the work)

Dispatch via the host tool's sub-agent mechanism; in tools without one, read the agent file and follow it.

| Agent | Role |
|---|---|
| `dev` | Implementation, test-first, in scope. |
| `reviewer` | The final gate; records what shipped. |
| `architect` | Data models, contracts, decisions. Produces designs, not code. |
| `steward` | Periodic health assessment; `/assess <scope>` selects code or guidance. |

## Commands

| Command | Does |
|---|---|
| `/propose <idea>` | Work an unconfirmed or large idea into a decided proposal, then spawn change specs. |
| `/start <TICKET>` | Set up the workspace and build through to review-ready. |
| `/review` | Run the final gate on the current branch. |
| `/ship` | Integrate and close, per the repo's branch model. |
| `/build <TICKET>` | Autonomous agent-led driver: implement, verify, review, and ship a ticket end-to-end (`--engine codex` runs the review through Codex). The unattended form of the `/start → /review → /ship` lifecycle. |
| `/assess <scope>` | Run the steward over the codebase or guidance (`--deep` for the broad pass). |
| `/update-guidance` | Pull upstream guidance changes into this repo. |

## Command namespacing

The universal guidance commands own the **bare names** (`/start`, `/review`, `/ship`, `/propose`, `/assess`, `/update-guidance`) and mean the same agent-led process in every repo. A repo with its own slash commands namespaces them under a repo prefix (e.g. `/<repo> <verb>`) so they do not collide — the installer will not overwrite a command the repo already owns.

For example, in the harness repo the harness's own commands are namespaced under **`/harness`** (`/harness run`, `/harness ingest`, and the unattended-loop commands `/harness routine build` / `/harness routine quality`): its "start" means *run the harness pipeline*, not *begin the agent-led process*, so it cannot take the bare `/start` name. (The installer copies the guidance's `/start` to `commands/start.md`, so the repo's own command must move out of that path first — see `INSTALLER.md` step 2.) Other repos apply the same rule to their own commands, if any. The `/harness routine` commands version the logic of the unattended loops (Build hourly, Quality idle/weekly) so it lives in the repo, not only in a scheduled-task config — *version the logic, not the schedule*; they are local-trigger only.

## When you are confused

Open the ticket first — it is the front door. Then read `CONTEXT.md`, then the as-built record for the area you are touching (`SPEC.md` / `specs/` for an infra repo, the feature spec otherwise). For any user-facing task, `ux-design` to shape the surface; when the `design_system` layer is on, `design-system` to materialize it. For a cross-cutting design decision, the `architecture` skill and the architecture-principles spec.

## Updating the guidance

These files are version-stamped. To pull upstream changes, run `/update-guidance`. Do not hand-edit installed guidance files to fix a bug in them; fix it at the source so every repo benefits, then update. (This repo *is* the guidance source — fixes land here directly.)
