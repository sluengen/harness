<!-- guidance:template-proposal@0.1.1 -->
---
proposal: pre-launch-consolidation
status: shipped          # draft | under-decision | accepted | shipped | rejected | split
date: 2026-06-15
related: [specs/proposals/harness-as-tool.md, specs/architecture-principles.md, commands/build.md, commands/build-codex.md, commands/harness.md, commands/assess.md, agents/code-steward.md, agents/system-steward.md, skills/assessment-craft/SKILL.md, harness/cli/review.py, four-loops.html]
---

# Proposal: Pre-launch consolidation — unify the review engine, the stewards, and the routines

> Two pre-launch workstreams, organised by one idea: there are **two execution surfaces** — *harness-tooled* (the audited `/harness run` verb loop) and *agent-orchestrated* (the `/build` fallback when the agent drives directly) — and they should be **parallel, not duplicated**. **A** makes the review **engine an argument** (Claude default, Codex opt-in) on *both* surfaces, with a **Codex→Claude fallback** when the tier is exhausted. **B** collapses the two steward agents into **one** (command = *what*, agent = *process*, skills = *domain standards* pulled just-in-time), broadens `/assess` with a deep pass, and versions the routine prompts — each routine, like build, getting a tool-primary and an agent-led fallback. A is the launch-blocker.

## Problem / motivation

Four things are true approaching launch, and they share a root: **the same work is expressed twice, and the two copies drift.**

**1. The review surface is duplicated and the engine is hard-wired.** `harness review` only runs Codex — [`review.py:192`](harness/cli/review.py:192) shells `codex exec --dangerously-bypass-approvals-and-sandbox --ephemeral -` with no engine parameter, no fallback, no usage-limit handling. The agent-orchestrated layer mirrors the split as a *copy*: [`build.md`](commands/build.md) and [`build-codex.md`](commands/build-codex.md) are ~95% identical — the **only** real difference is the Review step. Every build-loop edit is made twice.

**2. We exhaust Codex mid-week.** On the current tier, usage runs out early in the week. Agent-orchestrated, the orchestrator notices and substitutes a Claude review. But the **harness verb has no grace**: an exhausted Codex yields a `fail` verdict or a missing `SUBMIT` line, and the gate degrades to a false negative exactly when we depend on it.

**3. The reviewing session is invoked inconsistently, and the weaker path is the tempting one.** There is **no Claude Agent SDK** anywhere in `harness/`; the only Claude invocation is `claude -p` — the headless CLI — at [`trigger.py:57`](harness/trigger.py:57), chosen for auto-compaction. The SDK weakness worth naming — no compaction, no sub-agents, **crashes when context is exhausted** — only bites if a *future* Claude reviewer reaches for `query()`. The thing that is SDK-shaped today is the ad-hoc "spawn a Task sub-agent to review when Codex is down" fallback; blessing that bakes in the fragile path.

**4. The process is expressed twice in two more places.**
   - **Stewards.** `/assess` ([`assess.md`](commands/assess.md)) dispatches one of *two* agents — [`code-steward`](agents/code-steward.md) (8 code-domain areas) and `system-steward` (7 guidance-domain areas) — that share a methodology ([`assessment-craft`](skills/assessment-craft/SKILL.md)) and a procedure (`agents/tasks/steward.md`). The *same assessment process* lives in two agent files; the only real difference is *which domain standards apply*. That is precisely the MECE duplication `system-steward` exists to flag.
   - **Routines.** The prompts that drive the unattended loops live only in the Claude Code app's scheduled-task config — not the repo. [`four-loops.html`](four-loops.html) describes them; nothing in `commands/` encodes "hourly Build routine: pull the Linear Todo, pick the lowest-ID build-actionable ticket, run it, else assess." The logic that runs unattended is unversioned and un-uplift-able, against four-loops' own *version the logic, not the schedule*. And the weekly arm has no broad assess to run — `code-steward` covers structure/tests/architecture/deps/security *patterns*, but not test-coverage quantity, design-system adherence, or cross-spec/doc coherence.

**Cost of the status quo:** the build loop, the assess process, and the routines each exist in two drifting copies; the gate silently degrades on a depleted tier; and the fragile review path is the path of least resistance. Not acceptable at launch.

### Verified on disk (2026-06-15)
- `review.py` runs `codex exec ... --ephemeral -` via `asyncio.create_subprocess_exec` behind a `_default_runner` seam ([`review.py:185–226`](harness/cli/review.py:185)); the seam exists, the engine choice does not. No usage-limit / fallback / engine-selection code anywhere in `harness/`.
- `build.md` / `build-codex.md` diverge only at the Review step; both `@1.2.1`, both in `registry.yaml`.
- The Codex verb uses `--dangerously-bypass-approvals-and-sandbox`; the guidance the harness *publishes* ([`build-codex.md:169`](commands/build-codex.md:169)) uses `--sandbox read-only` because the diff is untrusted. The in-harness reviewer is **less** sandboxed than the guidance it ships.
- Two steward agents + one shared `assessment-craft` skill + one shared `agents/tasks/steward.md` procedure — the methodology is already shared; the agents differ only by domain.

## The organising principle — two surfaces, never duplicated

Everything below follows one rule:

> There are **two execution surfaces** for any repeatable job — **harness-tooled** (primary: the audited verb loop, `/harness run`, ledger-backed) and **agent-orchestrated** (fallback: the agent drives `start → review → ship` directly, `/build`). They are *parallel expressions of the same job*, differing only in **who owns the control loop and the gate** — not in policy. So a policy choice (which engine reviews; how the loop picks work) is decided **once** and honoured by both surfaces; it is never copied into a second file that can drift.

Applied: engine selection + Codex→Claude fallback is a policy that both surfaces honour. Build, assess, and the routines each get *one* primary tool path and *one* agent-led fallback — not two hand-maintained variants.

## Options

**Option A — Ship as-is.** Keep Codex hard-wired, two build files, two stewards, unversioned routines. *Trade-offs.* Zero work, but every launch-blocker above ships. Rejected.

**Option B — Consolidate to one expression per job, engine as an argument, fallback on both surfaces, one steward. (Recommended.)** `harness review` and `/build` take `--engine claude|codex` (default **claude**) behind the existing seam; Codex auto-falls-back to Claude on a usage-limit signal; the ledger records the engine. `build-codex.md` retires into `build.md`. The two stewards merge into one `steward` agent the command parameterises by scope. The routine prompts move into versioned `/harness routine` commands, each with a tool-primary and an agent-led fallback. *Trade-offs.* Real work in the verb and a guidance refactor of the stewards; changes the **default reviewer Codex→Claude** (a deliberate availability-for-independence trade, see Open decisions). But it removes every drifting copy (YAGNI), makes the gate survive a dead tier (fallback is explicit and *recorded*, never swallowed), and picks the robust CLI path for both engines — consistent with the orchestrator's existing `claude -p`.

**Option C — Make Codex resilient (retry/backoff), no Claude default.** *Trade-offs.* Backoff can't conjure quota when the *week's* tier is gone; leaves all the duplication. Rejected — it treats a quota wall as a transient error.

## Recommendation

**Adopt Option B**, sequenced **A before B**. It is squarely on `engineering-principles`:

- **YAGNI / simplicity.** One build command, one steward, one routine-per-job with a fallback — not lockstepped pairs. One review seam, thin engine adapters.
- **Errors never swallowed.** The Codex→Claude fallback is an *explicit, recorded* transition (the ledger names the engine and the fallback), not a silent retry hiding a dead tier.
- **Separation of concerns.** The engine is swapped behind `_default_runner`; the verdict contract (`SUBMIT:` line, SHA binding, gate) is engine-independent. And the assess layering — **command = the *what* (scope); agent = the *process*; skills = the *domain standards*, pulled just-in-time** — puts each concern in exactly one place.
- **Smallest correct change.** The CLI-subprocess shape and the seam already exist; the steward methodology and procedure are already shared. We are *parameterising and merging*, not rebuilding.

Two load-bearing rules to record downstream: **(1) a review engine is a CLI subprocess that emits the `SUBMIT:` contract — never the Agent SDK** (this is the whole of concern #3); **(2) a repeatable job has one tool-primary and one agent-led fallback surface, sharing policy** (concern #1, #4-routines).

## Open decisions

The three majors were decided with the user (2026-06-15); the tweaks of 2026-06-15 are folded in. Recommended answers for the rest.

| Decision | Who decides | Recorded in | Status / recommendation |
|---|---|---|---|
| Default review engine | user | architecture-principles | **DECIDED:** Claude default; `--engine codex` opt-in; Codex→Claude fallback on usage limit. |
| Cross-model independence trade-off | user / architect | architecture-principles | Claude-default ⇒ Claude reviews Claude by default. **Recommend accept**, mitigated: a *fresh, isolated* `claude -p` session (diff + ticket only), and `--engine codex` is the one-flag path to true cross-model review. |
| One steward, not two | user | architecture-principles | **DECIDED (tweak):** merge `code-steward` + `system-steward` → one `steward`. Command selects scope; skills hold domain standards JIT. |
| Where the guidance-coherence standards live | architect | change spec B1 | system-steward's 7 areas (version integrity, universal/repo boundary, MECE, lean, profile coherence, reference resolution, CONTEXT currency) are *domain standards*. **Recommend** extracting them into a `guidance-coherence` skill the `steward` pulls for the `system` scope — honouring "skills hold domain standards" — rather than leaving them inline in the agent. |
| Routines on both surfaces | user | change spec B2 | **DECIDED (tweak):** each routine has a harness-tooled primary and an agent-orchestrated fallback, mirroring `/harness run` vs `/build`. |
| Engine-selection syntax | architect | change spec A1 | **Recommend** `--engine claude\|codex` (explicit, extensible) over positional. |
| Usage-limit detection signal | architect | change spec A2 | **Unknown to verify at build** — what `codex exec` emits on an exhausted tier. A2 must match a stable signal; a non-limit failure must NOT fall back. |
| Deep-assess invocation surface | architect | change spec B1 | **Recommend** a `--deep` modifier on the scope (e.g. `/assess code --deep`) over a new domain. |

## Breakdown

Each item is a shippable change spec → Linear issue (team **CAL**, project **Harness v3**), built test-first via `/harness run`. Sequenced A before B.

> **Filed 2026-06-15:** [CAL-701](https://linear.app/calibrate-coffee/issue/CAL-701) (A1) → [CAL-702](https://linear.app/calibrate-coffee/issue/CAL-702) (A2) · [CAL-703](https://linear.app/calibrate-coffee/issue/CAL-703) (A3) — both blocked by A1; [CAL-704](https://linear.app/calibrate-coffee/issue/CAL-704) (B1) → [CAL-705](https://linear.app/calibrate-coffee/issue/CAL-705) (B2). Linear `blocks` relations set: A1▸A2, A1▸A3, B1▸B2.

**Workstream A — Unified review engine (launch-blocker):**

1. **A1 — Engine-selectable, read-only `harness review` verb (Claude default, Codex opt-in) + provenance.** *[harness-tool surface.]* Add `--engine claude|codex` (default `claude`); implement a `claude -p` engine emitting the same `SUBMIT:` contract behind `_default_runner`; run **both** engines read-only (aligning the `review.py:194` bypass to the published `--sandbox read-only` intent, Claude engine equivalently no-write); record the `engine` in `ReviewOutput` + the review event. Small doc touch on the [`/harness run`](commands/harness.md) review step to note the new default + how to opt into Codex. *(If the sandbox alignment bloats the diff, it splits to A1b.)*
2. **A2 — Codex→Claude usage-limit fallback in the verb.** *[harness-tool surface.]* When `--engine codex` is selected and Codex signals an exhausted tier, retry once via the Claude engine; record the fallback (`engine=claude`, `fallback_from=codex`). A non-limit Codex failure records `fail` and does **not** fall back. Depends on A1.
3. **A3 — Consolidate `/build` + `/build-codex` into one engine-arg command.** *[agent-orchestrated surface only — does not touch `/harness run`.]* Collapse the two files into one `build.md` (`/build <TICKET> [--engine codex]`, default Claude) whose agent-orchestrated review supports both engines and the agent-led Codex→Claude fallback; retire `build-codex.md` + its registry entry; bump versions; CHANGELOG; update references to the two-command split.

**Workstream B — One steward, deeper assess, versioned routines:**

4. **B1 — Merge the stewards into one `steward`; `/assess` selects scope; domains are skills (JIT); add the deep pass.** Merge `code-steward` + `system-steward` → one `agents/steward.md` (process), building on the shared `agents/tasks/steward.md` + `assessment-craft` (methodology). `/assess <scope>` names the *what* (`code` / `system` / `--deep`); domain standards live in skills the agent pulls JIT (`code-quality`, `test-driven-development`, `architecture`, `engineering-principles`, `design-system` [layer-gated], and a new/extracted `guidance-coherence` for the `system` scope — see Open decisions). The `--deep` scope adds test-coverage quantity, design-system adherence, and spec/doc-coherence lenses. Registry/version/CHANGELOG + agent-table updates across `process/harness.md`, `CLAUDE.md`, `AGENTS.md`, `GEMINI.md`. *(May split: B1a unify + rewire; B1b the deep lenses.)*
5. **B2 — Version the routine prompts, each on both surfaces.** `/harness routine build` (hourly: pull Linear Todo for Harness v3 → lowest-ID build-actionable ticket → run it → loop/idle-fallthrough) and `/harness routine quality` (idle → `/assess code`; weekly → `/assess code --deep`). Each routine specifies a **harness-tooled primary** (`/harness run`) and an **agent-orchestrated fallback** (`/build`), selected by tool availability — the same duality as build. The scheduled task becomes a thin trigger that calls the command. Register/version/CHANGELOG + `process/harness.md` command table. Depends on B1 (wires the deep pass).

## Risks / unknowns

- **Codex usage-limit signal (A2).** The fallback hinges on distinguishing "tier exhausted" from an ordinary failure. The exact signal is unverified — A2's first job is to capture what `codex exec` emits out of quota and match something stable; over-broad falls back on every hiccup, under-broad misses the wall.
- **Steward-merge blast radius (B1).** Merging two distributed agents touches the registry, version headers, the `AGENTS/CLAUDE/GEMINI` mirrors, and the cite/footprint guards. Mitigation: it is the system-steward's *own* domain (guidance coherence), well-specified, and the methodology/procedure are already shared — the merge mostly deletes duplication. The `guidance-coherence` extraction is the one genuinely new artifact; flagged as an Open decision.
- **`claude -p` `SUBMIT:` discipline.** The Claude engine must end on the single `SUBMIT: {json}` line. If chattier than Codex, the prompt/parse may need tightening; the existing no-`SUBMIT` path already records `fail`, so the failure mode is safe.
- **Independence regression.** Claude-default loses cross-model separation by default (recorded). Mitigation: fresh isolated session + one-flag Codex; if launch shows the default missing a class Codex caught, the arg makes revisiting the default a config change, not a rebuild.
- **Routines stay local.** Per prior decision, a cloud routine can't reach the local `~/bin/harness`. B2 versions the *logic*; the *trigger* stays a local scheduled task on both surfaces.

---

**Lifecycle.** On **accepted**: create the five change specs as linked Linear issues in CAL / Harness v3. The two principles — (1) engine-is-a-CLI-subprocess + the Claude-default trade-off, and (2) the two-surfaces / one-steward layering — are recorded in `specs/architecture-principles.md` (`templates/decision.md`) as explicit acceptance criteria of **A1** and **B1** respectively, so each lands through the gate with version discipline rather than as an out-of-band edit.
