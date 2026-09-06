---
name: capture
description: "/capture — file an already-decided change straight to Todo. Use when the operator invokes `/capture` or asks to run that workflow. Operator-triggered only; the model does not fire it."
disable-model-invocation: true
model: inherit
effort: medium
---

The portable plugin root is two directories above this SKILL.md. Resolve embedded paths beginning `skills/`, `agents/`, `templates/`, `hooks/`, or `.codex/` from that root; resolve repository artifacts from the workspace root.

# /capture — file an already-decided change straight to Todo

Usage: `/capture <description>` (kind inferred: bug or tweak)

Something noticed in actual use has nowhere lightweight to land: `/propose` decides the unconfirmed, and hand-filing a tracker issue is fiddly and trap-laden. `/capture` fills the capture sections of `templates/change.md` and files the result straight to Todo, ready for `/build` to pick up. It is the inverse of `/propose` — `/propose` decides, then files; `/capture` files the already-decided. (Smaller still? The fix lane needs no ticket at all — the spine's lifecycle section owns that boundary.)

Two kinds, inferred from the description and recorded in the body:

- **`bug`** — the as-built behaviour contradicts the intent. No escape hatch: there is nothing to decide, the fix direction is "make it match." Capture requires a repro — the steps or input that trigger it.
- **`tweak`** — the current behaviour is correct and is being upgraded. No repro needed; nothing is broken.

## Steps

**1 — gather.** From the description: what actually happens today (plus the repro, for a bug), what tipped you off — what you were doing, what you expected — and the desired outcome, not the implementation.

**2 — clarify, until the questions stop mattering.** There is no cap on the questions and no licence for a formality round. Keep asking while any question remains whose answer would change **the architecture, a contract, the data model, or the test design**; stop when none does. Rank by impact so the consequential ones come first, and integrate each answer into the spec as it arrives, *replacing* the sentence it supersedes rather than accumulating beside it.

Attended, ask with `AskUserQuestion`. Unattended, a question you cannot answer is not a guess: hold the ticket for the operator (`input` label, assigned — the spine's hold contract). Where a question is material but the filing should still land, write `[NEEDS CLARIFICATION: …]` inline in the sentence its answer would change; `/build` refuses to start while one remains.

A question left unasked here is asked at build time with a paid context waiting on it, or it is guessed — and guessing is the measured precondition for a build that cheats. That is why this step has a stop condition rather than a budget.

**3 — the escape hatch (`tweak` only).** A tweak that carries a real decision (more than one reasonable direction) or would spawn more than one change is not a tweak. Stop and say so:

```
This reads like more than one small upgrade — use /propose <idea> instead so
it can be decided and broken down.
```

A clear capture proceeds; there is no bespoke confirm gate. Where this step and the cost line both refuse, cite this one: an idea carrying two directions has no single cost to state, so the missing cost line is its symptom rather than a second finding.

**4 — write the cost line, and refuse the filing without it.** One line naming what this costs, what it buys, which principle it serves and which it spends against, and which waste it removes or adds (`templates/change.md` → *Cost*). A capture that cannot state what the work buys has not been decided, whatever the description says, and it is filed as nothing until it can: say which half is missing and stop. This is the one refusal in the workflow, and it is here because cost is uncomputable later — after a build, the spend is sunk and the line becomes a rationalisation.

**5 — fill the capture sections.** Immediately before authoring the change spec, load `authoring` → *Prose*. Fill the headings `templates/change.md` actually carries: **Problem** — the kind, the area, what happens today, what is wanted, and the situation that surfaced it — then **Cost**, **Approach**, **Lane**, **Acceptance criteria** (specific outcomes that name what they protect), **Assumptions**, **Protected areas**, and **Out of scope**. Grounding and Design stay empty; `/build` fills them at build time.

**6 — file it.** The title is **verb + where**. Then the UTF-8 body file and exactly one assurance level — chosen per `authoring` → *Choosing assurance*, never restated here — through `tracker`'s `create` operation, with the twin search and the mandatory explicit Todo placement the spine's Filing contract owns. If the provider reports a partial creation, surface the identifier and URL and stop; never retry by creating a duplicate.

## Report

Print the filed ticket's identifier and URL, then:

```
Next: /build <TICKET>
```
