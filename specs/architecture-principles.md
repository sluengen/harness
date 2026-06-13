<!-- guidance:template-architecture@0.1.0 -->
---
spec: architecture-principles
last_updated: 2026-06-13  # CAL-647: record the app vs. installed-surface boundary principle
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

### Self-enforcing guardrails

**A deterministic guardrail must self-enforce its invariant, never assume the calling agent established the precondition.** An invariant the caller can violate by accident is not enforced. A verb that depends on a precondition checks it itself and refuses on violation — it does not auto-correct the tree into compliance, and it does not trust an upstream step to have held the line. The concrete instance: `close` refuses a `dirty_worktree` rather than auto-committing, because uncommitted edits are not in HEAD and so were never reviewed — and `stale_review` (which catches commit-*after*-review by an advanced HEAD) cannot catch edit-*without*-committing (HEAD is unchanged). Auto-committing would silently merge unreviewed content; trusting the agent to have committed leaves the invariant to chance. *Derived from: CODE-INSIGHT-2 (evidence CODE-1 / CAL-586) and the Enforcement principle above — the gate's correctness depends on the tree it binds to being exactly what was reviewed.*

### Routing discipline

**Every *run-lifecycle* git and ticket mutation goes through a verb.** The audit trail (the `runs` ledger) is complete only if nothing in the verb loop hand-rolls a `git merge`/`push` or a Linear GraphQL mutation for the run lifecycle. Guidance-mandated in the `/harness run` skill, with `close` validating against the ledger as a backstop. The scope is the run lifecycle, not *all* mutations: the agent-led backup flow (`/start` → `/review` → `/ship`) sits outside this guarantee by design — it hand-rolls its Linear lifecycle transition (`issueUpdate … stateId` in `skills/linear-sync.md`) and is not recorded in the `runs` ledger. That is acceptable precisely because it is the non-harness path, run only when a task does not fit the verb loop; it never merges through `close`, so the gate it bypasses is one it was never meant to hold. *Derived from: the audit-trail guarantee above.*

### App vs. installed surface

**One repo holds two things that must never bleed into each other: the harness *app*, and the *surface* it installs into other repos.** After the guidance merge the boundary is a convention inside a single tree rather than a repo wall, so it is recorded here to stay enforceable.

- **App** — `harness/ docker/ bin/ scripts/ specs/ tests/`. This is the harness itself: its Python, its container, its launcher, its build/verify scripts, its design specs, its test suite. The app **never** installs into a target repo.
- **Surface** — *exactly* the `files:` membership of `registry.yaml`: `commands/ skills/ agents/ templates/ hooks/ process/ settings/`, plus the artifacts the installer derives in the target tree (`AGENTS.md` / `CLAUDE.md` / `GEMINI.md` and `.claude/settings.json`). Nothing is surface unless `registry.yaml` lists it.
- **Discriminator** — *must it be in the target repo's tree for that repo's local tooling to find or run it?* Yes → surface; no → app. **Default to the app**: a file is surface only when it earns its way onto the registry.

Two boundary cases the enumeration must keep straight: `commands/harness.md` is a **repo-owned command kept *out* of the registry** — it drives the harness's own pipeline, so it lives in the source tree but is not part of the installed surface; and `scripts/` is **app** today (`scripts/verify.sh` is the app's own gate), not surface. The app has zero coupling to the surface, and the footprint test (CAL-648) is what mechanically holds this line by asserting `registry.yaml`'s `files:` excludes every app path. *Derived from: the "Merge the guidance repo into the harness" decision below (D1/D2/D5) and `specs/proposals/merge-guidance-into-harness.md` breakdown item 2.*

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

### Decision: Merge the guidance repo into the harness — one source, app/surface boundary, branch-based distribution

*Decided 2026-06-13.*

**Context.** The harness was a *consumer* of a separate shared-guidance ("agents") repo: it carried installed copies of the universal commands/skills and a `.guidance-lock.yaml` pinning `source: agents`, while the agents repo held `registry.yaml` (the copy-list, serving a `standard` and a `harness` profile) and the installer. Cross-cutting changes — a harness change needing a guidance/doc change, or distributing the harness's own `/harness run` through a channel it did not own (CAL-624) — could not be made atomic. The product-agnostic, many-consumers premise that justified the split is speculative: there is one consumer (the author), and the guidance is a stopgap the harness is meant to absorb. Two repos institutionalised a separation the roadmap intends to erase.

**Decision.** Adopt **Option C** of proposal [`merge-guidance-into-harness`](proposals/merge-guidance-into-harness.md): collapse the two into one source tree by **promoting the harness to be the guidance source**, with a durable boundary between the harness **app** (`harness/ docker/ bin/ scripts/ specs/ tests/` — never installed into a target repo) and the installed **surface** (`commands/ skills/ agents/ templates/ hooks/ process/ settings/` + derived `AGENTS.md`/`CLAUDE.md`/`GEMINI.md` — installed via `registry.yaml`). The sub-decisions: **D1** harness becomes the source; **D2** surface at root in flat/installed shape, `registry.yaml` is the copy-list, no `surface/` tree (it would break the `.claude/` discovery symlinks); **D3** the surface is a *versioned interface* — the `guidance:<id>@x.y.z` header is the per-unit version, semver-governed (minor = invisible implementation swap, major = interface change), with a test locking the verb JSON / refusal-reason contract; **D4** clean copy-in; **D5** the harness owns `registry.yaml` + the installer and is **source-only** (drops its own `.guidance-lock.yaml`; the app's release tag is a separate version line walled off by a footprint test); **D6** all guidance comes home (both profiles) and the agents repo is **retired**; **D7** distribution is branch-based and pulled from GitHub — the harness authors and dogfoods on `dev`, external repos pull `main`, and `/update-guidance` + bootstrap fetch the harness repo at a branch ref (`source: { repo, branch, ref }`).

**Alternatives.**
- *Option A — stay split (agents source + harness consumer)* — preserves a product-agnostic source in principle, but pays the cross-cutting tax every change and maintains a separation the roadmap removes. Inferior with one consumer.
- *Option B — fully fuse, no internal boundary* — discards the working `registry.yaml` ↔ `.guidance-lock.yaml` + source/consumer freshness-hook mechanism to save a boundary that costs almost nothing to keep. Destructive of working infrastructure.
- *Option D — keep two repos + cross-repo sync tooling* — lipstick; straddling changes still are not atomic.

**Consequences.** Cross-cutting changes become one PR / one review / one atomic commit. The boundary is preserved structurally — the app has **zero coupling** to the surface (verified), and a **footprint test** asserts `registry.yaml`'s `files:` excludes every app path, eliminating (not merely mitigating) version entanglement. The harness's own role changes from consumer to source: it runs the freshness hook in SOURCE mode and carries no lock. Target-repo install footprint is unchanged (the channel, not the repo count, gates it). New coupling to own: branch-based release ties guidance to the app's `dev → main` cadence — a guidance-only hotfix cannot ship independently of an app release unless an independent promotion path / tag-based ref is added (deferred to the D7 work, CAL-653). The agents repo is retired (CAL-652). Spawned as **CAL-646 … CAL-653**.

**Supersedes.** The "guidance stays in a separate product-agnostic repo" framing in `CLAUDE.md` and `CONTEXT.md` (reconciled to the one-repo source model, CAL-651). CAL-624 (distribute `/harness run` via the agents-repo channel) is subsumed (CAL-650).
