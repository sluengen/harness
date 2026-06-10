<!-- guidance:template-architecture@0.1.0 -->
---
spec: architecture-principles
last_updated: 2026-06-11
---

# Architecture Principles

How this system is built — the technical principles that govern design *here*. They extend the universal `engineering-principles` with this repo's specifics, and they are where **cross-cutting decisions** are recorded (`spec-authoring`, `architecture`). A **reference spec**: update it when the architecture changes.

> Distinct from product principles (what we build and why). These define *how* we build it.

## Principles

### Orchestration boundary

**The agent orchestrates and implements; the harness is deterministic verbs, a ledger, and a gate.** Work executes one way — a Claude session drives `start → implement → review → (fix → review)* → close`, calling the harness verbs and doing the implementation itself. The harness does not own the build loop and does not spawn its own implementing/reviewing agents. *Derived from: `engineering-principles` (do the simplest thing that works; don't reimplement the agent tool-loop) and SPEC §1's "external layer decides what to run; harness decides how it runs."*

### Determinism

**Determinism lives in the verbs, not the journey.** Each verb (`start`, `review`, `close`) is a one-shot, audited, reproducible operation over the SQLite ledger. The *orchestration* between verbs varies with the agent and is no longer reproducible — that is a deliberate trade (see the decision below). SPEC principles #2/#4 (deterministic execution, reproducibility) now apply to the verbs, not to an end-to-end YAML run. *Derived from: `engineering-principles`.*

### Enforcement

**Process enforcement is a gate inside `close`, bound to the reviewed tree.** `review` records the git SHA it reviewed; `close` refuses to merge unless the ledger holds a `start` for the ticket **and** a `verdict=pass` whose reviewed SHA equals the worktree's current HEAD. This closes the stale-pass hole and is the safety rail that makes unattended (Hermes-triggered) dispatch trustworthy. *Derived from: product requirement — no ticket merges unreviewed.*

### Routing discipline

**Every git and ticket mutation goes through a verb.** The audit trail (the `runs` ledger) is complete only if nothing hand-rolls a `git merge`/`push` or a Linear GraphQL mutation for the run lifecycle. Guidance-mandated in the `/harness run` skill, with `close` validating against the ledger as a backstop. *Derived from: the audit-trail guarantee above.*

## Cross-cutting decisions

Decisions whose scope crosses features live here as Decision blocks (`templates/decision.md`), recorded in place rather than as standalone files. Each states context, decision, alternatives rejected, and consequences; superseding updates it inline with a dated note.

### Decision: Invert the orchestration boundary — harness becomes verbs, the agent orchestrates

*Decided 2026-06-09.*

**Context.** The original design (`SPEC.md` §1–2, `specs/hermes-orchestration.md`) made the **harness the orchestrator**: a deterministic mega-workflow (`build.yaml`) owned the entire build loop — fetch ticket → In Progress → worktree → implement → review → loop → merge → close — and spawned its own `ClaudeAgent` / `CodexAgent` subprocesses to do the implementing and reviewing. An external agent only launched a run and polled it. In practice this produced four recurring costs: brittle hand-encoded git/Linear `script` nodes that fail the whole run with no agent in the loop to adapt; lost context (the implementing agent is a fresh subprocess, not the one that understood the ticket); all-or-nothing failure; and a whole second runtime (the Hermes supervisor + async bridge) that had to be built before the deterministic model even worked unattended. The harness is, today, a tool a developer reaches for interactively — a setting where reproducibility of the *journey* is worth little, yet all four costs are paid every run.

**Decision.** Adopt **Option C** of proposal [`harness-as-tool`](proposals/harness-as-tool.md). One Claude session orchestrates **and** implements; the harness is reduced to three deterministic, audited verbs — `start` / `review` / `close` — over the existing SQLite ledger, with enforcement as a **gate inside `close`** (HEAD-bound passing review; decision D2). The deterministic workflow engine is retired (D1). There is **one execution model** (an agent using the harness as a tool) with **two triggers**: a human (`/harness run <ticket>`) or Hermes occupying the trigger slot a human would (D3) — both produce the identical execution path.

**Alternatives.**
- *Option A — status quo (harness orchestrates the whole build; a supervisor drives it)* — maximal determinism and an un-skippable in-run gate, but pays all four costs above and requires building the unbuilt supervisor runtime + async bridge for a headless mode we do not run.
- *Option B — pure agent orchestration, no harness in the loop (today's actual practice)* — maximal flexibility and full context, but no audit trail and nothing enforces the review gate; the agent can skip codex and merge.
- *Option D — coroutine handshake (harness stays top-level, hands control to the interactive agent mid-run and takes it back)* — the literal "best of both worlds" sketch and the hardest to build: two orchestrators passing a baton across the host↔container boundary, reintroducing the brittle machinery, with handshake faults the agent cannot rescue. Right division of labour, wrong shape — Option C delivers it by collapsing the two orchestrators into one and turning "hand back" into "a function returns."

**Consequences.** Keeps full context (the orchestrator is the implementer); removes mechanical toil from the agent's hands without losing the audit trail; degrades gracefully (a verb failure drops to Option-B manual driving). Gives up end-to-end reproducibility — SPEC principles #2/#4 now apply to the verbs, not the journey (own this; it is acceptable because we are not running deterministic autonomy). Softens enforcement from "cannot skip" to "caught at the gate"; the gate's correctness therefore hinges on `review`/`close` binding to the **same** SHA (D2) — if they do not, the gate is theatre. Requires retiring the engine, which also removes `release.yaml`/`steward.yaml` (never run; both convert cleanly to verb-shaped agent tasks). Audit completeness depends on routing discipline (D5): a hand-rolled commit or Linear mutation leaves a hole in the ledger. Hermes' separate-runtime + async-bridge design is superseded (D3); the remaining integration is a thin launch handle (follow-up CAL-576) plus a host-side launcher that exposes the verb operations without the docker socket (CAL-579).

**Supersedes.** The harness-as-orchestrator framing in `SPEC.md` §1–2 (reconciled to the verb model, CAL-575) and the control half of `specs/hermes-orchestration.md` (dated supersede note, CAL-575).
