<!-- guidance:spec-driven-development@0.2.0 -->
# Spec-Driven Development

How a task flows from "idea" to "shipped and recorded" with the least ceremony that still guarantees quality. This is the spine the other skills hang off. How to *write* each spec is in `spec-authoring`; this is *when* each one is produced.

## Three specs, three moments

| Spec | Holds | Lives in | Lifespan |
|---|---|---|---|
| **Proposal spec** | An idea not yet confirmed — needs a decision, or is too big to be one change | `specs/proposals/<slug>.md` | Until decided / broken up |
| **Change spec** | What one piece of work *intends* to do (incl. its design) | The **Linear issue** | While the task is in flight |
| **Feature spec** | What the product *actually does* today | `specs/features/<feature>.md` | Permanent |

**There is no `manifest.yaml`.** Linear is the queue of in-flight work and the home of the change spec (see `linear-sync`). A proposal (when needed) is decided and broken into change specs; each change is built, and its delivered behaviour is recorded into the feature spec. Small, clear work skips the proposal. All three are prose; keep them honest (`writing-quality`).

## The separation that makes it work

**The builder writes the change spec and builds. The reviewer records what actually shipped.** The agent that promises is not the agent that records delivery. This catches the failure mode "I said I'd do X, I did Y, and I forgot to mention it": the reviewer writes the feature spec from the diff, not from the builder's claim.

The builder does **not** edit `specs/features/`. If a builder touches the feature spec, that is a process violation the reviewer flags.

## The flow

0. **Propose first if it is unconfirmed or large.** If the work needs a decision, carries real unknowns, or is too big to be one change, write a proposal spec (`/propose`, `spec-authoring`) and get it decided before opening Linear issues. Skip this for small, clear work.
1. **The Linear issue is the front door.** Open it first. If the work was described in chat, create the issue before starting (see `linear-sync`). Set it **In Progress**.
2. **Write the change spec into the Linear issue.** Problem, approach, **design** (data model / interface / scenarios, scaled to size), acceptance criteria, out of scope (`spec-authoring` → change spec). A one-line bug fix needs one line.
3. **Branch and isolate.** Work on a feature branch in a worktree (see `worktree-isolation`). Never build on the default branch.
4. **Build test-first, in scope.** Follow `test-driven-development` for behaviour and `code-quality` for how to build without overreach. Design against `engineering-principles`.
5. **If scope shifts, update the change spec.** Silent divergence between the spec and the work is a process violation. Edit the change spec in place the moment the plan changes.
6. **Hand off to review.** Set the issue **In Review**. The reviewer checks output *and* process (`code-review`).
7. **On PASS, the reviewer records reality.** The reviewer updates `specs/features/<feature>.md` to match what shipped, as the last commit before merge.
8. **Ship and close.** Integrate per the repo's branch model (see the `/ship` command and `CONTEXT.md`), set the issue **Done**. The change spec stays on the Linear issue as history; the durable record is now in `specs/features/`.

## No claim without evidence

Steps 4 and 6 are gated by the verification rule in `code-quality`: no "done", "passing", or "ready for review" without a fresh command run and its output read in this session. Confidence is not evidence.

## When you are blocked

If you cannot proceed because information is missing, do not guess. State the specific question on the Linear issue, move it back to the backlog, and stop. A wrong assumption shipped is more expensive than a question asked.

## Profile note

The harness/infrastructure profile uses a leaner flow (build → review, with design-doc specs rather than user-facing feature specs). See `process/harness.md` in that profile.
