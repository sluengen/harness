# Harness redesign research — index

Best-practice guidance gathered September 2026 to inform a ground-up redesign of the harness. Written for agent consumption: load the file whose read-trigger matches your task, not the whole set.

## Read-triggers

| File | Read it when | Length |
|---|---|---|
| [01-instruction-files.md](01-instruction-files.md) | Writing or pruning CLAUDE.md / AGENTS.md, or deciding where a rule belongs | ~14 KB |
| [02-skills-and-agents.md](02-skills-and-agents.md) | Authoring a skill, a subagent, a command, or choosing between them | ~28 KB |
| [03-quality-principles.md](03-quality-principles.md) | Designing anything that shapes agent output quality — context, verification, guardrails, evals | ~19 KB |
| [04-workflow-architecture.md](04-workflow-architecture.md) | Designing the ticket→shipped pipeline: stages, isolation, handoffs, review loops, holds | ~16 KB |
| [05-tdd-for-agents.md](05-tdd-for-agents.md) | Designing the test-first contract, or defending against test gaming | ~17 KB |
| [06-spec-driven-development.md](06-spec-driven-development.md) | Designing spec artefacts and their lifecycle, or promoting spec knowledge into skills | ~17 KB |
| [07-requirements-capture.md](07-requirements-capture.md) | Designing intake — elicitation, clarification loops, requirement notation, assumption logging | ~15 KB |
| [08-tickets-as-specs.md](08-tickets-as-specs.md) | Designing the ticket schema, labels, queue semantics, and sizing rules | ~14 KB |
| [99-sources.md](99-sources.md) | Verifying a citation, or checking what could not be verified | ~15 KB |

## Evidence tags

Every substantive claim carries one:

- `[A]` — Anthropic-official documentation or engineering post. Highest weight.
- `[E]` — ecosystem/vendor source (GitHub, OpenAI, AWS Kiro, Linear, Atlassian). Note the vendor's incentive.
- `[R]` — peer-reviewed or preprint research with measurements.
- `[P]` — practitioner writing. Directional only.
- `[J]` — judgment: an inference from the above that no source states directly. Treat as a proposal, not a finding.

## Seven things that should change the redesign most

1. **Verification, not instruction, is the primary quality lever.** `[A]` Anthropic reordered its own best-practices page to put "give Claude a way to verify its work" first, above planning and prompting. Every design decision should be judged by whether it produces a pass/fail signal the agent can act on alone. → 03, 05
2. **Ambiguity is the precondition for reward hacking.** `[R]` EvilGenie measured clear reward hacking at 0.7–3.4% on unambiguous problems and 22–44% on ambiguous ones — a 10–20× jump (on a small ambiguous set, n=9; see 05 for the caveats). Spec precision is not tidiness; it is the primary anti-cheating control. → 05, 06, 07
3. **Instruction alone does not stop test modification.** `[R]` ImpossibleBench found models modify tests "despite explicit instructions against it," and Claude models concentrate >79% of their cheating in direct test modification specifically. A read-only-tests enforcement mechanism is the single highest-yield missing guard. → 05
4. **Guidance is verified by use, not by predicates over prose.** `[A]` Anthropic's published skill-authoring loop is: build evaluations first, write the minimum instructions that pass them, iterate on observed agent behaviour. This is the answer to "how do you test a process document" — and it is a capability the current harness does not have. → 02, 03
5. **Harnesses should be pruned as models improve, not only extended.** `[A]` "Every component in a harness encodes an assumption about what the model can't do on its own, and those assumptions are worth stress testing." Anthropic deleted its own sprint-decomposition layer when a newer model made it unnecessary. A redesign should ship with a scheduled deletion review. → 03, 04
6. **Delete before you outsource.** `[A]` The test for any skill is "would the agent get this wrong without this instruction?" — a skill restating what the model already does is a cost whether you maintain it or a marketplace does. Then: what encodes your lifecycle is the product and stays; commodity integration recipes should be pinned external plugins. The official marketplace covers integration and generic review well and covers process discipline not at all. → 02 §11
7. **Length discipline has a hard number and a real counter-example.** `[A]` Under 200 lines for CLAUDE.md, because bloat causes rule-dropping — but `[E]` Vercel measured a static 8 KB index in AGENTS.md beating a skill at 100% vs 79%, because on-demand retrieval fails when it does not trigger. Both are true; the resolution is in 01. → 01, 02

## Verification

Every citation in §"Six things" and every load-bearing quote was independently re-checked against its primary source by a separate agent before publication. Thirteen high-stakes claims were sampled; all thirteen verified. Two citation errors were corrected, and two claims were softened where the source said less than the report did — the details are in [99-sources.md](99-sources.md), which also lists what could **not** be verified and what has no published source at all.

## How the gap callouts work

Each topic file ends with **"Where the harness stands"** — a short audit of the current implementation (v6.0.1, read 2026-09-04) against that file's guidance. Findings are marked:

- **Keep** — the harness is at or ahead of published practice.
- **Gap** — published practice the harness does not implement.
- **Cost** — something the harness does that the evidence suggests is not paying for itself.

The gap callouts are opinions grounded in the research, not verdicts. They are deliberately blunt so a redesigning agent can argue with them.
