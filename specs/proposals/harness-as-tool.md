<!-- guidance:template-proposal@0.1.1 -->
---
proposal: harness-as-tool
status: accepted            # draft | under-decision | accepted | rejected | split
date: 2026-06-09
related: [SPEC.md, specs/retired/hermes-control-model.md, specs/retired/build-workflow.md, commands/harness.md]
---

# Proposal: Harness as agent tool — invert the orchestration boundary

> Stop building the harness as a pipeline that drives agents. Rebuild it as a small set of deterministic, audited verbs (`start` / `review` / `close`) that one agent calls while it does the implementation itself — with process enforcement living in the `close` gate. There is **one execution model** (an agent using the harness as a tool); it has **two triggers** (a human, or Hermes).

## Problem / motivation

The harness is hard to operationalise, and the difficulty is structural, not incidental. The current design (`SPEC.md` §1–2, `specs/retired/hermes-control-model.md`) makes the **harness the orchestrator**: it owns the entire build loop (fetch ticket → set in-progress → worktree → implement → review → loop → commit → merge → close) as a deterministic run, and it *spawns its own* `ClaudeAgent` / `CodexAgent` sessions to do the implementing and reviewing. An external agent only launches the run and polls it for status.

That shape produces four recurring costs, all observed in practice:

- **Brittle mechanics.** Every git and Linear operation is hand-encoded as `script` nodes inside `build.yaml` (GraphQL CURL for state transitions, `git merge --no-ff`, push). When one breaks mid-run, the whole run fails, and there is no agent in the loop to adapt — the orchestrator is a YAML walker, not a problem-solver.
- **Lost context.** The implementing agent is a *fresh subprocess* with no conversational history. Everything it needs must be re-fetched and re-passed through state. The agent that understood the ticket is not the agent that writes the code.
- **All-or-nothing failure.** A harness fault takes the run down. There is no graceful degradation to "let the agent just drive it manually."
- **A whole second runtime to build.** The deterministic model only works if something supervises it. `specs/retired/hermes-control-model.md` specs that supervisor as a separate runtime with sibling-container deployment, secret scoping, and an async bridge (subprocess → socket → HTTP, plus polling and a deferred daemon question). None of that is built, and all of it exists only to let one process watch another process do the work.

Meanwhile, the workflow that actually gets used is the opposite: a Claude session orchestrates *manually* — runs the scripts, implements inline, launches codex, loops, cleans up. It works because an interactive agent is genuinely good at orchestration. What it lacks is an **audit trail** and an **enforced review gate**: nothing records that the process was followed, and nothing stops the agent from skipping review.

The status quo optimises for **end-to-end reproducibility** (same inputs → same run). But the harness is, today, a tool a developer reaches for at their desk — an interactive context with a human present. There, reproducibility of the *journey* is worth little, and the costs above are paid every run. We carry the price of autonomy in a setting that is not autonomous — and still owe ourselves the unbuilt supervisor runtime before the "real" design even works unattended.

## Options

**Option A — Status quo: harness orchestrates the whole build (deterministic mega-workflow + a supervisor drives it).**
The harness owns the full loop and spawns its own agent sessions; an external orchestrator only launches and monitors via the polling bridge.
*Trade-offs.* Maximal determinism and reproducibility; the review gate is un-skippable because it lives inside the run. But it pays all four costs above and requires building the supervisor runtime + async bridge before it works unattended. Right answer for a mode (headless deterministic execution) we do not run.

**Option B — Pure agent orchestration, no harness in the loop (today's actual practice).**
The agent does everything by hand: Linear CURL, gitops, launch codex, loop, clean up. The engine is not involved.
*Trade-offs.* Maximal flexibility and full context retention. But the mechanical work is inconsistent run-to-run, there is **no audit trail**, and **nothing enforces the review gate** — the agent can simply skip codex and merge. Works, but unaudited and toil-heavy.

**Option C — Invert the boundary: an agent orchestrates; the harness is deterministic verbs + ledger + gate. (Accepted.)**
One agent (a Claude session) orchestrates *and* implements. The harness stops being a pipeline and becomes three one-shot, audited, reproducible verbs — `start`, `review`, `close` — over the existing SQLite ledger. Enforcement is a **gate inside `close`**: it refuses unless the ledger shows a `start` for this ticket and a passing review **bound to the current tree**. The deterministic workflow engine is retired.
*Trade-offs.* Gives up end-to-end reproducibility (orchestration now varies with the agent) and softens enforcement from "cannot skip" to "caught at the gate." In exchange: keeps full context (the orchestrator is the implementer), removes mechanical toil from the agent's hands without losing the audit trail, and degrades gracefully (a verb failure drops to Option-B manual driving).

**Option D — Coroutine handshake (flow #3 exactly as drawn). (Rejected.)**
Keep the harness as the top-level process, but have it hand control back to the interactive agent mid-run, then take it back for codex, then hand back for fixes, then close out.
*Trade-offs.* The literal "best of both worlds" sketch, and the hardest to build: two orchestrators passing a baton across the host↔container boundary (the session and the harness process are not the same process). It reintroduces the brittle machinery we are removing, and a handshake fault is the kind of failure the agent *cannot* rescue. Right instinct (harness owns mechanics + enforcement; agent owns judgment + implementation), wrong shape. Option C delivers the same division of labour by collapsing the two orchestrators into one and turning "hand back" into "a function returns."

## Recommendation

**Adopt Option C.** Make the agent the sole orchestrator and turn the harness into a toolbox of deterministic verbs plus a ledger and a gate. This is the "harness is a tool, not a pipeline" framing taken to its conclusion, and it is *more* aligned with the harness's own principles than the current code:

- `SPEC.md` §1 already names **"external layer decides what to run; harness decides how it runs,"** and the §2 diagram lists **"Claude Code agent"** as an external orchestrator. Option C is that picture taken seriously. What violates the principle today is `build.yaml` — one workflow that absorbed the whole orchestration the spec reserved for the external layer.
- `SPEC.md` §4.7's **"rent the loop, own the deterministic layer above it"** argues against reimplementing the agent tool-loop. Orchestrating a build — deciding how to fix a finding, when to re-review, whether codex is wrong — *is* tool-loop work. Option A reimplements it as a YAML walker; Option C rents it from the agent and keeps determinism where it belongs: the verbs.

### Resolved architecture: one execution model, two triggers

The decisions below (D1 retire the engine; D3 Hermes moves up a layer) collapse the old "interactive vs headless" split. There is **one** way work executes — an agent using the harness verbs — and **two** things that can start it:

```
┌─────────────────────────────────────────────────────────────────────┐
│  TRIGGER                                                            │
│   • a human  ( /harness run HAR-42 )                                │
│   • Hermes   ( Nous' persistent agent: built-in cron dispatcher )   │
└───────────────────────────┬─────────────────────────────────────────┘
                            │ launch a session for a ticket
                            ▼
┌─────────────────────────────────────────────────────────────────────┐
│  Claude session — orchestrator + implementer  (Option C)            │
│   start → [implement] → review → (fix → review)* → close            │
│   context retained; the agent that reads the ticket writes the code │
└───────────────────────────┬─────────────────────────────────────────┘
                            │ calls verbs
                            ▼
┌─────────────────────────────────────────────────────────────────────┐
│  Harness — the tool:  start / review / close  +  ledger  +  gate    │
└─────────────────────────────────────────────────────────────────────┘
```

A human typing `/harness run HAR-42` and Hermes dispatching HAR-42 produce the **identical** execution path. Autonomy is not a separate deterministic engine — it is *Hermes occupying the trigger slot a human would otherwise occupy*. This is why "retire headless" (D1) and "Hermes runs unattended" (D3) are consistent rather than contradictory. In both, the agent runtime is *per-session* and each verb is a *per-call* one-shot container spawned **outside** it (the human's `~/bin/harness` is already a `docker run`); only the launcher differs.

### Hermes, corrected: the trigger, not the runtime

The old `specs/retired/hermes-control-model.md` casts Hermes as the thing that *drives and monitors a deterministic harness run*. That role is dissolved. Hermes is [Nous Research's Hermes](https://hermes-agent.nousresearch.com) — a **persistent containerised agent assistant with a built-in dispatcher and cron** — so work selection and scheduling already exist. It replaces the human's job of **deciding what work gets done and triggering a session for it.** It does not implement, manage worktrees, run codex, or do gitops — a Claude session does, using the harness.

| Hermes owns | Hermes does NOT own |
|---|---|
| Watching the work queue (Linear); choosing the next ticket and when (built-in cron dispatch) | Implementing, or driving the build loop |
| **Launching a Claude session** for a chosen ticket | Worktree lifecycle, codex, gitops (the session's job, via verbs) |
| **Observing outcomes by reading the ledger** (`harness status` / `events`) | Writing the harness DB or overriding the gate |
| Escalating a stalled/failed session to a human | Interpreting the implementation itself |

Two interface edges:
- **Hermes → agent runtime (launch).** Three lifetimes, not two: **Hermes** is persistent (the dispatcher); the **agent runtime** is *per-session* — one Claude per ticket, spanning `start → implement → review* → close`, and the place context lives; the **verb container** is *per-call* — a one-shot `docker run` the agent shells out to. Hermes launches the per-session agent runtime and issues `/harness run <ticket>`; the agent then spawns each verb container **outside its own runtime**, exactly as a human's Claude Code session shells out to the `harness` verbs (`~/bin/harness` *is* a `docker run`). The agent must **not** run inside a one-shot verb container — that makes it per-call and reintroduces the lost-context problem the pivot removes. Open (follow-up): where the per-session agent runtime is hosted and how it is granted a docker handle to spawn sibling verb containers (socket mount vs. host broker — the socket is root-equivalent, a real cost on the unattended path); and whether the agent runtime and the verb runner are one image in two modes or two images (claude lives in the agent runtime, codex in the `review` verb).
- **Hermes ← harness (observe, read-only).** Hermes reads the ledger to know whether a session started, passed review, and closed — or stalled. The `harness status/events --json` surface (`harness/cli/query.py`) already exists for exactly this. Hermes never drives the harness; it drives the *session*, and the session drives the harness.

**What survives from `hermes-orchestration.md`:** the observability half (status object, event stream, artifact paths) — Hermes still consumes it. **What is superseded:** the control half (start-run / cancel / resume-decision as ways to drive a deterministic workflow) and the "harness is the thing Hermes runs" framing. The **gate (D2) is the safety rail that makes unattended dispatch trustworthy** — when no human is watching, `close` refusing without a HEAD-bound passing review *is* the guarantee that no ticket merges unreviewed. So D2 is the precondition for D3.

Because the dispatcher already exists, the follow-up is small: specify the launch handle and the container-invocation topology, plus how Hermes reads the ledger back. It depends on the verbs existing first and is likely a **change spec, not a full proposal** (Breakdown item 7).

## Open decisions

| Decision | Resolution | Recorded in |
|---|---|---|
| **D1 — Keep a headless/autonomous deterministic mode?** | **Resolved: retire it entirely.** No deterministic workflow engine. Autonomy comes from Hermes triggering a session, not a YAML walker. *Consequence:* the engine also serves `release.yaml` and `steward.yaml` — those convert to agent-tasks/verbs too (Breakdown 5). | architecture-principles spec + `SPEC.md` non-goals |
| **D2 — How strict is the `close` gate?** | **Resolved: bind the passing review to HEAD.** `review` records the git SHA it reviewed; `close` requires a `verdict=pass` whose SHA equals the worktree's current HEAD. Closes the stale-pass hole and underwrites unattended dispatch (D3). | the `close`-verb design spec + architecture |
| **D3 — Fate of the Hermes runtime + bridge?** | **Resolved: Hermes moves up a layer.** Hermes (Nous' persistent containerised agent — *built-in* dispatcher + cron) occupies the trigger slot a human would; integration is a thin launch handle (`claude` + `/harness run <ticket>`), not a dispatcher to build. The separate-runtime + async-bridge design (now in `specs/retired/hermes-control-model.md`) is superseded by a dated note; the launch-handle detail is a follow-up (change spec). | `specs/retired/hermes-control-model.md` (dated supersede note) + architecture |
| **D4 — Collapse the duplicate process encodings?** | Follows from C. The process lives in one rewritten `/harness run` skill (what the agent follows) + the verbs (what enforces). Retire `build.yaml`/`build-codex.yaml`; reconcile `/build` and `/build-codex`. | architecture + the affected command specs |
| **D5 — Routing-discipline enforcement.** The audit trail is complete only if *every* git/ticket mutation goes through a verb. | Follows from C. Guidance-mandated (the skill forbids hand-rolled git/CURL), with `close` validating that HEAD's commit history matches what the ledger recorded as a backstop. | architecture |

Confirmed with the user (2026-06-09): (a) full engine retirement — `release`/`steward` were never run and are naturally verb-shaped (release = gitops + AI notes; steward = an agent review that writes a file), so they validate the verb model rather than being exceptions; (b) Hermes is Nous' persistent agent with a built-in cron dispatcher — integration is a thin launch handle; (c) the launch-handle detail is a separate follow-up. Status → **accepted**.

## Breakdown

Each item is shippable on its own. Spawned 2026-06-09: **1→[CAL-570](https://linear.app/calibrate-coffee/issue/CAL-570), 2→[CAL-571](https://linear.app/calibrate-coffee/issue/CAL-571), 3→[CAL-572](https://linear.app/calibrate-coffee/issue/CAL-572), 4→[CAL-573](https://linear.app/calibrate-coffee/issue/CAL-573), 5→[CAL-574](https://linear.app/calibrate-coffee/issue/CAL-574), 6→[CAL-575](https://linear.app/calibrate-coffee/issue/CAL-575), 7→[CAL-576](https://linear.app/calibrate-coffee/issue/CAL-576)** (blocks-relations: 1,2→3→{4,5}; 4→7). Items 1–3 are the core; 4 wires it; 5–6 keep the codebase and specs honest; 7 is the Hermes follow-up.

1. **`harness start <TICKET>` verb** — validate ticket exists + move to In Progress + create worktree + open a `runs` row (run_id, ticket, base, worktree, `status=open`); returns run_id + worktree path + ticket-context JSON. Re-homes `build.yaml`'s fetch/set-in-progress/setup mechanics as a verb.
2. **`harness review` verb** — run codex against HEAD; record `verdict`/`issues`/**reviewed-SHA** as a ledger event; return verdict JSON. Productionises the `CodexAgent` adapter (currently gated behind `proc_fn=`).
3. **`harness close <TICKET>` verb + gate** — enforce (`start` exists + a `verdict=pass` whose SHA == HEAD, per D2), then commit/merge/push + close ticket + mark run closed; structured refusal otherwise. The enforcement linchpin. *(Depends on 1–2.)*
4. **Rewrite the `/harness run` skill** — the agent orchestrates `start → implement → review* → close`, implements inline, routes all git/ticket ops through verbs (D5). Reconcile/retire `/build` and `/build-codex` (D4). *(Depends on 1–3.)*
5. **Retire the workflow engine** — delete the YAML-walking orchestration (`engine/runner|executor|loop|retry`, the node *protocol*, workflow schema, contract/derive machinery, `build*.yaml`); **re-home the mechanics that the verbs need** (worktree lifecycle, codex dispatch, git/Linear helpers, state/ledger store) as plain helpers. Convert `release.yaml` (gitops + AI release notes) and `steward.yaml` (agent review that writes a file) into agent-tasks or small verbs — both were never run and fit the verb model cleanly. *(Can be staged: re-home for the verbs first, delete the walker last.)*
6. **Spec reconciliation** — `SPEC.md` §1–2 to the one-model/two-triggers + verb surface; dated supersede note in `specs/retired/hermes-control-model.md` (D3); record the orchestration-inversion decision in the architecture-principles spec; confirm the `runs`/events schema stores reviewed-SHA + the open/closed run lifecycle (add fields if not).
7. **Hermes launch handle** (follow-up; likely a change spec) — the dispatcher already exists (Nous Hermes + cron), so this specifies only the ergonomic handle (`claude` + `/harness run <ticket>`), the container-invocation topology, and how Hermes reads the ledger for outcomes. *(Depends on 1–4.)*

## Risks / unknowns

- **Stale-pass hole** — closed by D2 (HEAD-bound passing review). The single most important correctness detail; if `review`/`close` do not actually bind to the same SHA, the gate is theatre.
- **Audit completeness depends on routing (D5).** A hand-rolled `git commit` or Linear CURL leaves a hole in the ledger. Mitigated by skill mandate + close-time history validation; residual risk remains and is stated, not hidden.
- **Reproducibility is genuinely given up.** Own it: `SPEC.md` principles #2/#4 now apply to the *verbs*, not the journey. Acceptable because we are not running deterministic autonomy — autonomy is Hermes-launches-a-session.
- **Engine-retirement scope (D1).** Retiring the engine also removes `release` and `steward` — confirmed acceptable (never run; both convert cleanly to agent-tasks). Item 5 is the largest piece and can be staged (verbs first, engine deletion last).
- **Agent-runtime hosting + docker handle are unresolved** — how the per-session agent runtime is hosted and granted the ability to spawn the one-shot verb containers (socket mount vs. host broker; the socket is root-equivalent — a real trust cost on the unattended path). The agent↔verb relationship is *settled* (agent per-session; verbs are external one-shot containers, as in the human path); only the runtime hosting + docker handle and the agent/verb image split are open. Deferred to the follow-up.
- **Where the session runs, relative to the container.** Verbs are one-shot `docker run`s over a host-mounted worktree (fits the existing container-first model). If the interactive session is host-side, the shared-worktree mount must be pinned. Settle before item 4.
- **Implementation isolation posture changes** — interactively, the agent implements directly rather than in a sandboxed worktree-in-container. Fine for a trusted developer; a real change from the isolation the current spec assumes.
- **Context exhaustion on the long single-agent loop** — the per-session agent now spans the whole build, so context pressure is real (the flip side of context retention; it is what the current spawned agents already fail on). Three-layer mitigation, all structural: (1) the headless runtime is the Claude Code CLI (`claude -p`), which **auto-compacts for free** — unlike the `claude_agent_sdk.query()` path the current spawned agents use, which exposes no steerable compaction and is the likely cause of the exhaustion; (2) verbs return compact, bounded results (codex's full output stays in the `review` container; the agent sees a verdict), which avoids compaction "thrashing" on oversized tool output; (3) the ledger + worktree are the durable anchor — because the run's authoritative state is *externalised*, a lossy compaction is survivable: the agent re-orients via `harness status` instead of relying on whatever the summariser happened to keep. Reinforce by instructing the agent to re-orient from the ledger after a compaction and to checkpoint intent (commit WIP), plus the "verbs return compact results" AC on the verb issues. (Steering compaction via a CLAUDE.md "Compact Instructions" section is an optional refinement, not load-bearing — the externalised state is the real safety net.)

---

**Lifecycle.** Accepted 2026-06-09. D1/D2 resolved; D3 resolved (Hermes = trigger via a launch handle); D4/D5 follow from C. Spawned as **CAL-570 … CAL-576** (2026-06-09), linked above; superseded **CAL-537** (bridge) and **CAL-539** (Option-B deployment) cancelled with pointers to this proposal. Decision record = this file; the formal `SPEC.md`/architecture update is CAL-575.
