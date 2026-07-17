# Local orchestrator stack — OpenCode + MLX (spike)

> **Status: spike / hypothesis — not yet validated.** Nothing in this stack is
> installed, configured, or exercised in this repo. The harness side of the
> contract below is real and verified against the live `promote` surface; the
> OpenCode and MLX side is a **recommendation to be proven**, recorded so a future
> session can pick it up without rediscovering the reasoning. Do not read this as
> current practice — `RUNBOOK.md` documents how the harness actually operates.
> The rehydration checklist at the end is the entry point.

Recorded for CAL-1134, grounding: the accepted proposal
[`specs/proposals/local-promotion-steward.md`](proposals/local-promotion-steward.md)
and [ADR 0003](decisions/0003-promotion-lifecycle.md).

## What this is for

Promotion moves completed work `dev → staging → main`. Most of that movement is
mechanical: fetch, merge, gate, push a branch, open a PR, or file a ticket when
the machine cannot proceed. The harness already owns all of it as an audited
lifecycle, so the outer agent driving it needs almost no intelligence — which
means spending Claude or Codex tokens on a nightly promotion is paying premium
rates for plumbing.

This runbook records a **cheap local alternative** for the outer-agent slot:
OpenCode in non-interactive mode as the agent shell, an MLX LM server on
localhost for the small amount of prose and bounded-repair judgment the loop
needs, and `launchd` for the schedule. The goal is not a clever local release
bot. It is the least capable thing that can drive an already-safe lifecycle.

## Why the stack stays outside harness core

The harness surface is **deterministic and model-free**. It does not depend on
MLX, Ollama, llama.cpp, MLC, or any OpenAI-compatible endpoint, and this runbook
does not propose changing that.

This is a resolved decision, not an open question. Proposal **D3 — Inference
adapter** resolved: *out of scope for harness promotion; the model powers the
outer agent, not the harness; any local review-engine adapter is a separate
proposal.* The `harness-as-tool` boundary says the same thing structurally — an
external actor occupies the trigger/orchestrator slot while the harness remains
the audited tool. OpenCode and MLX are simply one occupant of that slot. They are
**outside harness core** by design, and swapping them for Hermes, OpenClaw,
Claude, Codex, or a human must require no harness change whatsoever. If any part
of this stack ever needs a harness change to work, that is the signal the
boundary is being violated — stop and re-read D3.

The practical test: everything below could be deleted and the promotion lifecycle
would still be complete and safe.

## The contract this stack plugs into

**This runbook does not restate the promotion routine.** The agent-agnostic
contract — the two flows, the full command sequence, every lifecycle state, the
forbidden outer-agent actions, and the bounded-repair policy — lives in
`RUNBOOK.md` § *The promotion routine*. Read that first; this document only adds
what is specific to running it on OpenCode + MLX.

Two constraints from that contract are worth repeating here, because they are
what keep a small local model safe to point at a release lifecycle:

- The outer agent **must never** push a target branch, open/close/merge a PR
  outside the harness, mutate Linear promotion state out of band, or mark a
  promotion done. Only `harness promote pr` pushes, and only the promotion branch.
- Repair is **one bounded attempt**, and a promotion cannot reach `pr_ready`
  without fresh gate evidence.

A local 7B-class model is not trusted with release judgment here. It is trusted
with drafting prose from deterministic facts and with small in-policy repairs —
and the harness refuses everything else regardless of what the model attempts.
That is why a cheap model is acceptable: the safety is in the lifecycle, not in
the agent.

## The stack

| Layer | Choice for v1 | Notes |
|---|---|---|
| Scheduler | macOS `launchd` (or cron) | See *Scheduling* below — the OpenCode cron plugin is optional, later. |
| Agent shell | `opencode run` (non-interactive) | A short-lived session per promotion, not a persistent agent. |
| Harness interface | CLI JSON (v1) | The five `promote` subcommands. A local MCP adapter over the same layer is a possible v2 — not needed for v1. |
| Model server | MLX LM server, **bound to localhost** | See *The inference layer*. |
| Inference | MLX / MLX-LM | Apple-silicon local inference. |
| Model | Qwen Coder 7B-class (MLX build) | Sized for prose + bounded repair, not release judgment. |

```text
launchd (nightly)
  └─ opencode run "<the prompt below>"
       ├─ harness promote start / continue / status / pr / escalate   ← authority
       └─ MLX LM server on localhost                                  ← bounded prose/repair only
```

## The minimal prompt

The prompt stays tiny **because the harness carries the durable process**. Every
rule that matters is enforced by the verbs, so the prompt does not need to
re-teach the lifecycle to the model — it only needs to point the model at it and
name the stop conditions. A long prompt here is a smell: it means logic that
belongs in the harness is leaking into an unversioned string.

```text
Run the nightly promotion for this repo.
Use harness promote commands only.
If harness returns agent_may_fix, make at most one bounded repair.
If harness returns needs_ticket or blocked, call harness promote escalate and stop.
Never push target branches or create PRs outside harness.
```

## The command sequence and its stop conditions

The full sequence and every state are specified in `RUNBOOK.md`. For this stack,
the loop the prompt above drives is:

```text
harness promote start --repo <repo> --from dev --to staging
  → branch on the returned status:
      pr_ready       → harness promote pr --promotion-id <id>        → STOP (success)
      agent_may_fix  → one bounded repair, then
                       harness promote continue --promotion-id <id>  → re-branch on new status
      needs_ticket   → harness promote escalate --promotion-id <id>  → STOP (human owns it)
      blocked        → harness promote escalate --promotion-id <id>  → STOP (human owns it)
harness promote status --promotion-id <id> --json   (read-only, any time)
```

The four stop conditions, and what this orchestrator does on each:

| State | The local orchestrator's action |
|---|---|
| `pr_ready` | Clean merge and a green gate. Call `promote pr`, then **stop**. On the staging hop it lands the candidate on `staging` and is done (`promoted`); on the release hop the model may draft PR prose from the harness's deterministic facts, and the PR then waits for a human/CI merge — the harness never auto-merges. |
| `agent_may_fix` | A small, in-policy conflict or gate failure. The local model may attempt **one** bounded repair in the worktree, then `promote continue`. If the re-gate fails, the attempt is spent — do not try a second. |
| `needs_ticket` | Beyond local repair authority. `promote escalate` and **stop**. Do not repair, and do not re-run `start` to retry. |
| `blocked` | Infrastructure, not code — missing credentials, remote permission, unclean base. `promote escalate` and **stop**. A local model cannot fix these and must not try. |

`status` is the source of truth: the orchestrator reads these off the JSON, it
never scrapes prose. Every terminal (`promoted`, `pr_opened`, `escalated`) ends the
run — the orchestrator does not loop past them.

## Scheduling

**v1 is `launchd`** (cron on a non-macOS host). It is already the substrate for
the harness's own loops (ADR 0001 — always-on local is the default), it is
outside the agent entirely, and it fails visibly. One `launchd` job fires one
`opencode run` per night; if OpenCode is broken or absent, the job fails and
nothing silently half-promotes.

**The OpenCode cron plugin is optional, and later.** Scheduling inside the agent
shell couples the trigger to the tool: the schedule then only exists where
OpenCode does, and swapping the agent takes the schedule with it. It buys
convenience, not capability. The versioned rule is *version the logic, not the
schedule* — the loop's logic belongs in the repo, and the trigger stays a thin
caller. Reach for the plugin only if `launchd` proves inadequate for a concrete
reason worth recording.

## The inference layer

**The MLX LM server must bind to localhost only.** It is an unauthenticated
inference endpoint on a developer machine; binding it to `0.0.0.0` exposes it to
anything on the network. Localhost-only is the requirement, not the default to be
relaxed for convenience.

**Local inference powers the outer agent, not the harness.** This is D3, restated
because it is the line most likely to erode in practice: the model may draft PR
prose from the harness's deterministic facts and judge whether an
`agent_may_fix` conflict is worth its one bounded repair. It may not sit inside
the harness surface, and no harness verb may acquire a dependency on it. The
harness returns facts, classifications, evidence, and state; what the model does
with them is the outer agent's business.

If a local OpenAI-compatible engine is ever wanted for the **`review`** verb,
that is a separate review-engine proposal with its own decision record — not this
stack, and not a quiet extension of it.

## Known risks

- **Local model quality is variable.** A 7B-class model is appropriate for
  summaries and bounded repairs, not release judgment. The policy — not the model
  — is what keeps authority narrow.
- **PR prose can hallucinate.** The model drafts from the commit list, Linear IDs,
  spec changes, and gate evidence the harness supplies. Those facts are the source
  of truth; prose invented from raw diff context is not.
- **Credentials fail separately.** `launchd`, git push auth, GitHub PR creation,
  Linear, and the MLX server each have their own. The harness surfaces missing
  auth as a structured `blocked` result rather than a generic failure — that is
  the intended path, and it escalates.
- **Agent runtime choice may drift.** OpenCode may not be the right shell in six
  months. Because the contract is agent-agnostic, replacing it should cost
  nothing on the harness side. If it ever costs something, see *Why the stack
  stays outside harness core*.

## Rehydration checklist

For the future session that picks this spike up. In order:

1. **Read the accepted proposal** —
   [`specs/proposals/local-promotion-steward.md`](proposals/local-promotion-steward.md),
   especially D2 (the MVP surface) and D3 (inference is out of scope for the
   harness). Then `RUNBOOK.md` § *The promotion routine* for the agent-agnostic
   contract this stack plugs into.
2. **Inspect the promotion command contracts** as they are *now*, not as
   described here: `harness promote --help`, and the JSON each subcommand emits.
   The live surface and its lifecycle states are the contract; this document is
   downstream of them and may have drifted (the CAL-1134 doc tests guard the
   subcommand names and stop conditions, so a drift should have failed the gate —
   check them first).
3. **Confirm the MLX and OpenCode config** — MLX LM server reachable on
   localhost and bound there only; a Qwen Coder 7B-class MLX model pulled;
   `opencode run` working non-interactively and pointed at the local endpoint.
   This is the step with the most unknowns: **none of it has been validated**, so
   expect the tool details to differ from the hypothesis above and record what is
   actually true.
4. **Run a dry-run promotion against a test repo/branch** — never against real
   `dev → staging` on first contact. Drive the loop end to end and confirm the
   orchestrator branches correctly on each status it encounters.
5. **Verify escalation behaviour** — force a `needs_ticket` or `blocked`
   promotion (a deliberate conflict in a guarded path, or absent credentials) and
   confirm the orchestrator escalates and **stops** rather than retrying or
   repairing. This is the one behaviour that must hold before the stack is
   trusted on a schedule: a loop that stops correctly is safe even when the model
   is weak.
