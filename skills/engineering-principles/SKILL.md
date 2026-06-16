---
name: engineering-principles
description: Use when designing or changing any code — the durable principles every change is measured against (simplicity over cleverness, smallest change, no premature abstraction, separation of concerns, errors never swallowed). Load when making a design decision or judging whether a change fits the codebase's standards.
---
<!-- guidance:engineering-principles@0.3.0 -->
# Engineering Principles

The durable values every design, change, and review is measured against. The architect designs to them, the developer builds to them, the reviewer reviews against them. When the three load the same principles, "what you build" cannot drift from "what you are judged on."

These are universal. Each repo extends them with its own principles in `CONTEXT.md` and records consequential, repo-specific choices as decisions in the spec they govern (see `architecture`). A repo principle never contradicts one here without a recorded decision that says so explicitly.

## The principles

**Simplicity over cleverness.** The reader is the constraint, not the writer. Prefer the boring solution that the next person understands in one pass over the clever one that needs a comment to defend it.

**Smallest change that satisfies the spec.** One condition is usually enough. Removing code is often the right answer. Do not add what the task did not ask for.

**No premature abstraction.** Duplicate twice before you extract. An abstraction introduced to serve one caller is a liability, not reuse. Wait for the third instance.

**Separation of concerns.** Each module owns one responsibility and one layer. Business logic does not live in a transport handler; persistence does not leak into a view. Name the layer a change belongs to before editing it.

**Stable contracts, replaceable implementations.** The interface is the asset. Design boundaries to outlast the code behind them. Implementations should be swappable without callers noticing.

**Validate at boundaries, trust within.** Untrusted input is checked once, at the edge, then flows as validated data. Do not re-validate defensively in the interior, and do not let unvalidated input past the door.

**Design for extension, not speculation.** Leave room to add, but do not build the addition until it is asked for. Speculative generality ages worse than a focused solution you replace later.

**Atomic, reversible increments.** Every commit leaves the project working. A change you cannot revert in one step is too big. Small steps are how you stay able to back out.

**Minimal dependencies.** Every dependency is a standing cost: supply chain, upgrade burden, surface area. Each must earn its keep, and one doing two jobs should be split or dropped.

**Make the right thing the easy thing.** When the correct pattern is also the path of least resistance, people follow it without enforcement. When you find yourself adding a rule, ask whether the structure could make the rule unnecessary.

**Errors surface, never swallowed.** A caught exception that is silently discarded is a bug in waiting. Handle it, or let it propagate to someone who can. Silence is the worst outcome.

## Before you write it

The principles above are values; this is the procedure that applies them at the keystroke. Before writing a piece of code, walk the rungs in order and **stop at the first one that holds** — most needs are met before the last:

1. **Does this need to exist at all?** A speculative need is no need — skip it, and say so in one line.
2. **Does the standard library do it?** Use it before you hand-roll it.
3. **Does a native platform feature cover it?** Use it before you build over it.
4. **Does an already-installed dependency solve it?** Use it; do not add a dependency for what a few lines do.
5. **Can it be one line?** Then it is one line.
6. **Only then:** the minimum code that works.

When two rungs both hold, take the higher one and move on — the ladder is a reflex, not a research project.

**Scope guard.** The ladder governs *what to build, not whether to test or what the spec requires.* It never licenses skipping the failing test first (`test-driven-development` — test-first is untouched) and never licenses dropping or trimming an acceptance criterion (`review-discipline` Stage 1 — requirements are not self-descoped). "Build less" is never "test less" or "deliver less."

## Trade-offs are conscious, not silent

These principles pull against each other. Extension fights simplicity; validation fights minimalism. Resolving the tension is the work. What is not acceptable is resolving it silently: when a change knowingly relaxes a principle, that is a decision worth recording (in the architecture-principles spec for cross-cutting choices, the change spec for local ones), not a drift to be discovered later.

## How the reviewer uses this

Principle violations are findings. A design that buries domain logic in a view, a change that adds an abstraction for one caller, a dependency that does not earn its keep: each traces to a named principle here. The reviewer cites the principle, not a personal preference.
