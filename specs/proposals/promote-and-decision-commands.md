---
proposal: promote-and-decision-commands
status: shipped         # draft | under-decision | accepted | shipped | rejected | split
date: 2026-07-23
related:
  - specs/decisions/0003-promotion-lifecycle.md
  - skills/work-discovery/SKILL.md
  - commands/harness.md
---

# Proposal: two missing loop commands — `/promote` and `/decision`

***Shipped.** Both commands exist: `commands/promote.md` drives `dev` → `staging` → `main` with plain git, and `commands/decision.md` drains the tickets held for the operator's input.*

> Two operator moves are performed repeatedly today from unversioned prose or a retyped ad-hoc prompt. Both should become versioned guidance commands: `/promote` to drive a branch hop, `/decision` to drain the queue of tickets held for a judgment call.

## Problem / motivation

The autonomous build loop has two recurring operator interactions that never became commands. Both are done by hand today, and each hand-run is a fresh reconstruction of logic that already exists somewhere less useful than a command file.

**Promotion.** The promotion lifecycle shipped as five audited verbs (`harness promote start | continue | status | pr | escalate`, ADR 0003, CAL-1112–1118). What never shipped is the *caller*. The orchestration — which state to branch on, when to run the gate host-side, when to stop — exists only as prose in `RUNBOOK.md` §"The promotion routine", inside this repo, describing a nightly cron trigger that the operator instead fires by hand. That prose is not version-stamped, is not installed into any other repo on this guidance, and is not addressable as `/<verb>`. Every promotion is therefore an agent re-reading a runbook and improvising the loop, in a repo that already decided *version the logic, not the schedule*. Repos without the harness app have nothing at all: they hand-roll `git merge` + gate + PR each release, which is precisely the hand-rolled-merge the ledger's audit guarantee depends on nobody doing.

**Held decisions.** `harness defer` parks a not-yet-actionable ticket three ways — comment, `decision` or `operator` label, assignment to the operator — and `work-discovery` skips anything assigned. That is the correct outbound half. There is no inbound half. Nothing in the guidance drains the held pile, so the operator retypes some variant of *"there are pending decisions blocking the build cycles, let's go through them one by one"* into a fresh session. The cost compounds: every unresolved `decision` ticket is a permanently-skipped queue entry, so the Build arm falls through to idle assessment passes while real work sits held. The current empty Todo queue (tick #84) sits alongside a held pile nobody sweeps — the loop looks starved when it is actually blocked.

The two exclusions the operator names for this sweep are already encoded, imperfectly: `operator` labels the *interactive session* case. Tickets needing the operator to supply a work item or stand up infrastructure are today filed under whichever label the deferring run guessed.

## Options

**Option A — one command each, in universal guidance (`commands/promote.md`, `commands/decision.md`)** · Two new version-stamped bare-name commands installed into every repo on this guidance. `/promote` reads `CONTEXT.md` `branches:` to resolve the hop, drives the `harness promote` verbs when the app is present, and falls back to an agent-orchestrated merge → gate → PR when it is not. `/decision` reads the tracker for held-for-decision tickets, presents them one at a time, records each resolution into the ticket, and releases it back to the queue. · *Trade-offs:* two more files in the universal surface, and `/decision` must encode tracker reads that the `linear` skill and the GitHub backend own separately. Both stay small because each delegates to an existing seam.

**Option B — namespace both under `/harness`** · `/harness promote`, `/harness decisions` — repo-local commands next to `/harness run`. · *Trade-offs:* honest about the harness dependency, and no new bare names to defend. But it strands both in this repo: the fallback path (`/promote` without the app) is the whole point of shipping promotion to other repos, and held-ticket triage is tracker-level, not harness-level. Namespacing an agent-led process under the tool it optionally uses inverts the CLAUDE.md rule — bare names mean *the same agent-led process in every repo*.

**Option C — promotion as a command, decisions as a mode of an existing one** · `/promote` as in A; the decision sweep folded into `/harness routine build` as a pre-flight, or into `/assess`. · *Trade-offs:* no new bare name, and it puts the sweep where the queue is already read. But the sweep is inherently interactive — it needs the operator in the turn to make the calls — and `routine build` is the unattended arm. Wedging a blocking human prompt into an unattended loop is the wrong shape; the loop would have to skip it, which is what already happens.

**Option D — do nothing; keep the runbook prose and the ad-hoc prompt** · *Trade-offs:* zero cost now. Leaves promotion logic unversioned and unavailable to other repos, and leaves the held pile draining only when the operator remembers to type the prompt. The status quo is what motivated the proposal.

## Recommendation

**Option A**, with `/decision` delegating its judgment to the existing `work-discovery` skill rather than restating it.

Promotion first. The verbs are the deterministic seam; the command is the documented caller. Moving the loop from `RUNBOOK.md` prose into `commands/promote.md` costs almost nothing new — it is a transcription plus the fallback branch — and buys version-stamping, installation into every repo, and one addressable name. The fallback matters more than it looks: a repo without the harness app still has a `dev → staging → main` topology in its `CONTEXT.md` and still needs someone to run the gate on the merged tree before opening the PR. `/promote` gives that repo the same shape without the ledger, which is the `/build`-is-available-everywhere pattern applied to release movement. *Smallest change*: no new engine surface, no new verb — a command file over an existing contract.

For `/decision`, the judgment about what is and is not actionable already has exactly one home, and `work-discovery` says so explicitly ("this skill is the single home of that judgment"). The return path is the same judgment run backwards: a held ticket is resolvable when the only thing missing is a call the operator can make in the turn. Restating that test inside the command would fork it. The command owns control flow — pull the held set, order it, present one, capture the answer, write it back, release the ticket — and the skill owns *is this the kind of hold I can clear*.

Releasing the ticket is the load-bearing step and the reason this is a command and not a prompt: resolving a decision means writing the answer into the change spec, removing the hold label, **and unassigning the operator**, because `work-discovery` treats assignment as the authoritative skip signal. A sweep that records answers without unassigning leaves every ticket held forever — the failure mode the ad-hoc prompt has today.

## Open decisions

All six were decided on 2026-07-23 by the operator. Resolutions below; the two
cross-cutting ones (argument resolution through `CONTEXT.md` roles, and the third
hold kind) are recorded in the specs they govern.

| Decision | Resolution | Recorded in |
|---|---|---|
| `/promote` argument form | **Natural-language roles** — `/promote dev to staging`. The word is matched against `CONTEXT.md` `branches:` roles first, falling back to a literal branch name. Not no-arg: a release hop must be deliberate, not inferred. | `commands/promote.md` |
| Do env names resolve through `CONTEXT.md` `branches:` roles? | **Yes** — role first (`integration` / `staging` / `release`), literal ref as fallback, so a repo naming its branches `develop` / `production` works unchanged. | `commands/promote.md`, ADR 0003 (amended) |
| How faithful is the no-harness fallback? | **Reduced** — worktree off target, merge, run `CONTEXT.md` `commands.verify`, PR (or advance the intermediate branch) on green, stop and report on conflict or red. No bounded repair, no state machine, no ledger. Deliberately less, so it cannot drift into a second implementation of the lifecycle. | `commands/promote.md` |
| Does `/decision` select on the `decision` label alone, or re-triage? | **Neither** — the exclusion becomes machine-readable via a third hold kind (below). `/decision` selects on the judgment-call kind only. | ADR 0006 |
| Is a third hold kind needed? | **Yes** — `harness defer --needs` gains a kind separating "needs a call from the operator" from "needs the operator to supply a work item or stand up infrastructure". `/decision` shows only the first; the input and interactive kinds stay held. | ADR 0006, `harness/cli/defer.py`, `skills/work-discovery/SKILL.md` |
| After a resolution, does `/decision` also hand off to `/harness run`? | **No** — it writes the answer into the change spec and releases the ticket (comment, hold label removed, unassigned). The Build arm picks it up on its next tick. Sweeping and building are two jobs. | `commands/decision.md` |
| Command names | **`/decision` and `/promote`** as bare universal names, as the operator named them. | `CLAUDE.md` command table |

## Breakdown

Each item is shippable on its own and becomes a GitHub issue on `sluengen/2`.
Ordered by dependency: the hold kind must exist before `/decision` can select on it.

1. **[#189](https://github.com/sluengen/harness/issues/189) — `commands/promote.md`, harness-backed path.** The versioned command over the five `promote` verbs: role-resolving argument parsing, the state branch table, host-side gate execution, terminal-state stop rule. `RUNBOOK.md` §promotion reduces to a pointer. No engine change. Documents the manual PR step until #187 lands.
2. **[#190](https://github.com/sluengen/harness/issues/190) — `commands/promote.md`, agent-orchestrated fallback.** The no-harness branch, reduced by decision: detect absence, merge into a worktree off the target, run `commands.verify`, PR or advance on green, stop and report on conflict or red. Explicit about what is lost without the ledger.
3. **[#191](https://github.com/sluengen/harness/issues/191) — `harness defer --needs` gains a third hold kind** separating a judgment call from an operator-supplied input (work item or infrastructure). ADR 0006 records the kind vocabulary; `work-discovery` skips all three, `/decision` selects one.
4. **[#192](https://github.com/sluengen/harness/issues/192) — `work-discovery`, the return path.** The inverse test: when a held ticket is clearable, and what "released" means (comment + hold label removed + unassigned). Version bump; `/decision` points here rather than restating the judgment.
5. **[#193](https://github.com/sluengen/harness/issues/193) — `commands/decision.md`, the held-ticket sweep.** Pull tickets held for a judgment call, order them, present one at a time with the deferring comment as context, capture the call, write it into the change spec, release the ticket. Stops there — no handoff to `/harness run`.

Items 1 and 2 could land as one change; splitting them keeps the fallback's design honest rather than an afterthought paragraph. #191 blocks #193; #192 is independent of both but should land with #193 so the two halves of the judgment stay in one home. All five are filed Todo on `sluengen/2`.

## Risks / unknowns

- **`/decision` is interactive and the rest of the surface is not.** Every other command here is drivable unattended. A command that blocks on a human is a new shape for this guidance; if it turns out awkward, it may belong as a documented prompt rather than a command. That is the strongest argument for Option D on the `/decision` half specifically.
- **Tracker coupling.** `/decision` needs list-by-label, comment, remove-label, and unassign across both `linear` and `github` backends. The `linear` skill covers one; the GitHub path is currently exercised only through harness verbs. The sweep may need a `harness` verb after all — which would make it Option B for that half.
- **Bare-name collision.** `/promote` and `/decision` claim two more universal names. `/promote` is defensible (it is the release process). `/decision` is a broad word for a narrow sweep; `/decisions` or `/triage` may read truer.
- **The fallback may drift from the verb path.** Two implementations of promotion in one command file will diverge unless the fallback is deliberately reduced rather than mirrored.
- **Measured: the held pile is empty.** Counted 2026-07-23 — zero open issues on `sluengen/harness` carry `decision` or `operator`; neither label appears to have been used since the tracker cut over to GitHub (tick #69). The operator's pain is real but predates the cutover, so `/decision` would ship against a pile of nothing and only pay off as the loop starts deferring again. **Decided to build it anyway:** the pile is empty *because* nothing drains it and the loop has not deferred since the cutover, so the return path should exist the first time a ticket is held rather than being retyped as a prompt again. Accepted with eyes open — if the labels stay unused for several months, item 5 was premature.
- **`/promote`'s harness-backed path is broken today.** Open issue #187 — `promote pr` cannot publish because the runtime image has no `gh` binary — means a `staging → main` hop cannot finish through the verbs as shipped; #188 (`promote continue` accepts an unreadable `--gate-log` and records empty evidence) weakens the gate evidence the command would rely on. Both are unfiled on the board. `/promote` item 1 either depends on #187 or must document the manual PR step until it lands.

---

**Lifecycle.** A proposal ends in one explicit state: **accepted** (spawn the change specs as issues; record its decisions in the relevant specs), **rejected** (keep this file as the record of why), or **split** (replace with smaller proposals). It does not sit half-decided. Lives in `specs/proposals/`.
