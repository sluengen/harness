---
name: spec-driven-development
description: Use at the start of a tracked task to follow the spec-driven flow from idea to shipped-and-recorded with minimal ceremony — when each spec (proposal, change, feature) is produced and what handoff means. The spine the other skills hang off.
---
# Spec-Driven Development

How a task flows from "idea" to "shipped and recorded" with the least ceremony that still guarantees quality. This is the spine the other skills hang off. How to *write* each spec is in `spec-authoring`; this is *when* each one is produced.

## Three specs, three moments

| Spec | Holds | Lives in | Lifespan |
|---|---|---|---|
| **Proposal spec** | An idea not yet confirmed — needs a decision, or is too big to be one change | `specs/proposals/<slug>.md` | Until decided / broken up |
| **Change spec** | What one piece of work *intends* to do (incl. its design) | The **tracker issue** | While the task is in flight |
| **Feature spec** | What the product *actually does* today | `specs/features/<feature>.md` | Permanent |

**There is no `manifest.yaml`.** The tracker is the queue of in-flight work and the home of the change spec. Route every tracker operation through the `tracker` skill: it reads `CONTEXT.md`'s `tracker:` field and dispatches to the matching provider recipe (`linear` → the `linear` skill, `github` → the `github-issues` skill, `none` → its documented degrade). A proposal (when needed) is decided and broken into change specs; each change is built, and its delivered behaviour is recorded into the feature spec. Small, clear work skips the proposal. All three are prose; keep them honest (`writing-quality`).

## The separation that makes it work

**The builder writes the change spec and builds. The reviewer records what actually shipped.** The agent that promises is not the agent that records delivery. This catches the failure mode "I said I'd do X, I did Y, and I forgot to mention it": the reviewer writes the feature spec from the diff, not from the builder's claim.

The builder does **not** edit `specs/features/`. If a builder touches the feature spec, that is a process violation the reviewer flags.

## The flow

0. **Propose first if it is unconfirmed or large.** If the work needs a decision, carries real unknowns, or is too big to be one change, write a proposal spec (`/propose`, `spec-authoring`) and get it decided before opening tracker issues. Skip this for small, clear work.
1. **The tracker issue is the front door.** Open it first. If the work was described in chat, create the issue before starting (see `tracker`). Set it **In Progress**. **Capture on-ramp:** a bug or small tweak noticed in actual use can skip straight here — `/bug` / `/tweak` file a pre-framed change spec (`templates/adjustment.md`) directly to Todo, and `/start` extends it with Grounding and Design (steps 2–3 below) at build time. It is the inverse of a proposal: a proposal decides, then files; capture files the already-decided.
2. **Ground the spec in current reality.** Before writing the change spec, verify the facts it will rest on that name a **file / function / flag / version / decision** against the *current* code — recalled facts (memory, system-reminders) reflect what was true when written, and a spec built on a stale one reverts to blocked mid-build. Where a sub-agent host is available, the agent-led `/start` flow dispatches a read-only `researcher` agent that investigates in its own context and returns a distilled **grounding brief**; where none is available, the executor self-grounds inline (the fallback). Either way, record the result as the change spec's `Grounding` section (`spec-authoring`). Grounding always happens; the sub-agent is the richer delivery where available.
3. **Write the change spec into the tracker issue.** Problem, approach, **design** (data model / interface / scenarios, scaled to size), acceptance criteria, out of scope (`spec-authoring` → change spec). A one-line bug fix needs one line.
4. **Branch and isolate.** Work on a feature branch in a worktree (see `worktree-isolation`). Never build on the default branch.
5. **Build test-first, in scope.** Follow `test-driven-development` for behaviour and `code-quality` for how to build without overreach. Design against `engineering-principles`.
6. **If scope shifts, update the change spec.** Silent divergence between the spec and the work is a process violation. Edit the change spec in place the moment the plan changes.
7. **Hand off to review.** Set the issue **In Review**. The reviewer checks output *and* process (`review-discipline`).
8. **On PASS, the reviewer records reality.** The reviewer updates `specs/features/<feature>.md` to match what shipped, committed **into the candidate before the certifying gate and the verdict** — the tree the verdict covers is the tree that merges (`review-discipline`'s *final-evidence ordering* rule). When a surface's as-built record does not exist yet, the first ticket touching that surface creates it — a feature spec in `specs/features/` where `feature_specs` is on, otherwise the section of the design doc / `SPEC.md` that governs the surface. A surface is not permitted to accumulate more than one shipped ticket without an as-built record; the record is where a gap between tickets becomes visible, and it cannot do that job retroactively.
9. **Ship and close.** Integrate per the repo's branch model (see the `/ship` command and `CONTEXT.md`), set the issue **Done**. The change spec stays on the issue as history; the durable record is now in `specs/features/`.

## No claim without evidence

Steps 5 and 7 are gated by the verification rule in `code-quality`: no "done", "passing", or "ready for review" without a fresh command run and its output read in this session. Confidence is not evidence.

## When you are blocked

If you cannot proceed because information is missing, do not guess. State the specific question on the issue, move it back to the backlog, and stop. A wrong assumption shipped is more expensive than a question asked.

## Layer note

The as-built record's shape is a per-repo choice, not a profile: with the `feature_specs` layer on the record is a feature spec in `specs/features/`; off, it is the design doc / `SPEC.md`. See `CONTEXT.md` `layers:` for what a given repo uses, and `process/harness.md` for the one shared flow.
