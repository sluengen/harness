<!-- guidance:process-harness@0.2.1 -->
# How work happens here (harness profile)

This is the process for an **infrastructure / pipeline-harness repo** — a tool or library that other repos depend on, with no end-users and no product UI. It is a deliberate variant of the standard process: same skills and standards, a leaner flow, and design-doc specs instead of user-facing feature specs. Everything repo-specific is in [`CONTEXT.md`](CONTEXT.md); read that first.

## How this differs from the standard process

| | Standard | Harness |
|---|---|---|
| Spec of record | `specs/features/<feature>.md` (what the product does) | design docs / `SPEC.md` (how the system is built) |
| Roles | PM → architect → dev → reviewer | dev → reviewer (architect for cross-cutting design) |
| Design system | optional layer | none |
| `feature_specs` layer | on | off |

The reason: an infrastructure repo's "behaviour" *is* its design. There is no separate user-facing surface to describe, so the canonical record is the design spec, kept current as the system changes.

The three-spec model (`spec-authoring`) still applies: **proposal specs** (`specs/proposals/`) for unconfirmed or large ideas, **change specs** (the Linear issue) for one piece of work, and the **design spec** playing the feature-spec role as the as-built record.

## The shape of a task

0. If the work is unconfirmed or too big for one change, `/propose` it first.
1. The Linear issue is the front door. Open it, move it to In Progress.
2. Read the relevant design spec (`SPEC.md` or `specs/`) before changing behaviour — it is the contract.
3. Write a change spec into the issue: problem, approach, design, acceptance criteria (`spec-authoring`).
4. Branch into a worktree (`worktree-isolation`). Build test-first (`test-driven-development`), in scope (`code-quality`), to the principles (`engineering-principles`).
5. Hand to review. The reviewer checks output and process (`code-review`), runs the verification gate independently, and — on PASS — updates the design spec to match what shipped.
6. Ship per the branch model (`/ship`, `CONTEXT.md`), close the ticket.

No completion claim without fresh evidence (`code-quality` Part C).

## Skills, agents, commands

Same library as the standard profile, minus the design-system skill. The load-bearing ones: `spec-driven-development` (read its profile note), `engineering-principles`, `test-driven-development`, `code-quality`, `code-review`, `architecture`, `systematic-debugging`, `writing-quality`, `worktree-isolation`, `linear-sync`, `assessment-craft`.

Agents: `dev`, `reviewer`, `architect`, `code-steward`, `harness-steward`. Commands: `/propose`, `/start`, `/review`, `/ship`, `/assess`, `/update-guidance`.

Domain-specific knowledge for *this* harness (its workflow schema, its CLI, how to author workflows) lives in the repo itself — in `CONTEXT.md` and the repo's own docs — not in the shared guidance. The guidance stays product-agnostic.

## Command namespacing

The universal guidance commands own the **bare names** (`/start`, `/review`, `/ship`, `/propose`, `/assess`, `/update-guidance`) and mean the same agent-led process here as in every other repo. The harness repo also has its **own** commands — launching the harness on a ticket, authoring a workflow, ingesting — and those would collide on the bare names (the harness's own "start" means *run the harness pipeline*, not *begin the agent-led process*).

Resolve it by **namespacing the harness's own commands under `/harness <verb>`** (e.g. `/harness run`, `/harness build-workflow`, `/harness ingest`). The bare names stay with the universal commands. This is not just to avoid confusion: the bootstrap installs the guidance's `/start` at `commands/start.md`, so the harness's own `start` must move out of that path first (the bootstrap refuses to clobber it — see `BOOTSTRAP.md` step 2).

Keeping the agent-led commands available here is deliberate: when a task does **not** fit the harness's own pipeline shape, run it through the standard `/start → /review → /ship` flow as a backup.

## When you are confused

Open the ticket, read `CONTEXT.md`, then the design spec for the area you are touching. For a cross-cutting decision, the `architecture` skill and the architecture-principles spec.
