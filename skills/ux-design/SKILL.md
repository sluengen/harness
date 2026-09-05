---
name: ux-design
description: Use when designing, prototyping, or reviewing any user-facing interface — how humans think and behave, information architecture, flow, and every state (empty/loading/error/edge). The design-the-right-thing skill; then use design-system to materialize it.
---
# UX Design

User-experience craft: how humans think and behave, applied to any user-facing interface you mock up, build, or review. This is the **design the right thing** skill — the human, the psychology, the flow, the states. Its sibling `design-system` is the **don't degrade the system** skill — tokens, primitives, conformance. When you design or prototype a new surface, start here for the shape; then use `design-system` to materialize it in real tokens and primitives (so a mockup is faithful and convertible, never bespoke throwaway markup).

Where the repo has a design system (the `design_system` layer is on; its location is in `harness.yaml`), **its brand and UX principles are the source of truth and override these general heuristics.** This skill is the portable craft; the system is the local law.

## Ground yourself first

Before designing a surface, read what already constrains it — wherever `harness.yaml` points:

- **Brand & mission** — and the things the product is deliberately *not* (its anti-pillars).
- **Audience & context of use** — who is this person, what are they feeling, on what device, first-time or power user.
- **Voice & tone** — microcopy is part of the experience (`authoring` → *Prose* for the prose craft itself).
- **The design system's own UX principles** — they win over anything below.
- **Tokens, primitives, patterns** — the materials you build with (`design-system` for the discipline of using them).

No design system in this repo? The craft below still applies — you are establishing the principles as you go rather than inheriting them.

## Understand the human first

Before building, answer three questions. If the audience hasn't been given to you, check what `harness.yaml` points to before proceeding.

1. **Who is using this?** What are they feeling (stressed, curious, rushed, anxious)? What is *their* goal — not the business goal? What is their context (mobile, desktop, first-time, power user)?
2. **What is the problem space?** What exists today? What conventions do users already know from similar products? How do other industries solve this same underlying problem?
3. **What are the constraints?** Devices, performance budget, the existing design system, content availability, technical limits.

## Design with psychology

### Cognitive load
Working memory holds ~4 chunks. Every element competes for them.
- **Progressive disclosure** — show only what the current step needs.
- **Sensible defaults** — pre-select the most common option.
- **Chunking** — group into sets of 3–5.
- **Recognition over recall** — show the options; don't make people remember them.
- **Consistency** — the same action looks and behaves the same way every time.

### Visual hierarchy
Users scan in ~3 seconds; they don't read. Design for the scan.
- Most important thing first, supporting context second, actions third.
- One hero element per view. If everything is emphasised, nothing is.
- F-pattern for text-heavy pages, Z-pattern for visual pages.

### Decision architecture
How you present choices changes what people choose.
- **Default bias** — most people accept defaults, so make the default the best choice *for the user*.
- **Anchoring** — the first option sets expectations for the rest.
- **Choice paralysis** — past ~5–7 options, decision quality drops (Hick's Law).
- **Commitment escalation** — small yeses lead to big yeses (ask for email before credit card).
- **Loss aversion** — "Don't lose your progress" beats "Save your progress" — but don't overuse it; chronic loss framing breeds anxiety.

## Information architecture and flow

### Navigation
- A user should always know: where am I, where can I go, how do I get back.
- Breadth over depth — 7 top-level items beat 3 levels of nesting.
- Consistent navigation placement across screens (spatial memory).
- "Where am I?" should be answerable in a second on any screen.

### Design the flow, not just the screen
A screen in isolation hides the work. Design the whole journey and every state it can be in.
- **Happy path** — the ideal route from start to finish.
- **Edge cases** — 0 items? 1,000 items? Long names? Missing data?
- **Error recovery** — every error needs a clear path back to success.
- **Empty states** — often the first thing a new user sees; make it useful, not "no data".
- **Loading states** — prefer skeletons (show the structure) for content; inline feedback for actions; never a blocking spinner over work the user is mid-way through. Use the design system's loading primitives and motion guidance.

## Verification checklist

Run before presenting work. Fix failures before showing anything.

- [ ] A new user understands what to do within ~5 seconds.
- [ ] The most important action is visually dominant.
- [ ] Interactive elements are obviously interactive.
- [ ] Every action gives visible feedback.
- [ ] Error states are specific, helpful, and recoverable.
- [ ] Works with the keyboard alone.
- [ ] Loading state is appropriate — skeleton for content, inline for action feedback, never blocking mid-task.
- [ ] Empty state is useful, not just "no data found".
- [ ] The flow handles edge cases (0, 1, many, missing).
- [ ] Copy is clear, specific, and actionable (`authoring` → *Prose*).
- [ ] On mobile it feels right one-handed, not merely "fits".
- [ ] Values come from tokens and primitives, not bespoke markup (`design-system`).

## Never

- **Never** start building before you understand who uses the interface.
- **Never** present a screen without considering all its states (empty, loading, error, success, edge).
- **Never** ignore mobile — if it doesn't work one-handed, it doesn't work.
- **Never** make hover the only way to reveal critical functionality.
- **Never** hide essential navigation more than one level deep.
- **Never** build a flow without an escape route at every step.
- **Never** assume users read — they scan.
- **Never** animate without a communication purpose (the design system's motion guidance).
- **Never** hand-write a value where a token or primitive exists (`design-system`).
