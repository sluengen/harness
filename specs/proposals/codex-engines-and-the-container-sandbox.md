<!-- guidance:template-proposal@0.1.2 -->
---
proposal: codex-engines-and-the-container-sandbox
status: accepted         # draft | under-decision | accepted | shipped | rejected | split
date: 2026-08-04
decided: 2026-08-04
related:
  - specs/decisions/0002-in-container-review-engine.md
  - specs/decisions/0005-per-ticket-model-tiering.md
  - specs/decisions/0007-design-verb.md
  - specs/decisions/0012-persistent-runtime-host.md
  - specs/proposals/persistent-runtime-host.md
---

# Proposal: Codex as an in-container engine for `design` and `review`

> ADR 0002 rejected an in-container Codex engine on a cost that measurement shows is wrong; a targeted seccomp profile — no added capability — makes Codex's sandbox start, which is the precondition for cross-model review and for taking the design stage's unconditional Opus call off the Claude subscription.

## Problem / motivation

Two costs, one shared blocker.

**The gate is single-family.** `specs/architecture-principles.md` → *Review engine* records the trade deliberately: Claude reviewing a Claude-authored diff gives up the independent second opinion, and `--engine codex` "stays opt-in for a deliberate cross-model review." In practice that opt-in has never been taken inside the loop, because it cannot be: every tick drives verbs through `~/bin/harness` → `docker run`, and ADR 0002 makes Codex a host-only engine. The recorded escape hatch is unreachable from the only path that runs.

**The loop's Claude spend is concentrated where there is no alternative engine at all.** `design` runs Opus unconditionally on every run (ADR 0007), 14–17 KB of output, median 366s across 16 measured runs. `review` resolves a per-ticket tier (ADR 0005) and — measured 2026-08-04 — **zero of the 25 open issues carry a `build:` or `review:` label**, so every review resolves to the Sonnet fallback. The expensive dimension is the one with a single hardcoded engine (`DESIGN_ENGINE = "claude"`, `harness/cli/design.py:139`); the cheap dimension is the one with an engine union.

**ADR 0002's cost claim is measurably wrong.** It costs the alternative as "`CAP_SYS_ADMIN`, `--privileged`, or a custom seccomp profile" and rejects the bundle as "a real, standing security regression." Measured today against `harness:dev`, codex-cli 0.146.0, Docker server 29.6.2:

| Container config | Result |
|---|---|
| baseline, as the wrapper runs it | `unshare -U` → `Operation not permitted`; bwrap fails with the literal CAL-866 message |
| `--cap-add SYS_ADMIN`, default seccomp | userns created, then `bwrap: pivot_root: Operation not permitted` |
| `--security-opt seccomp=unconfined`, **no cap-add** | userns created, `bwrap --ro-bind / / --dev /dev true` → **rc=0** |

The gate is the seccomp profile alone. `CAP_SYS_ADMIN` — the grant the ADR's security argument is actually about — is neither sufficient nor required. Two syscall families do all the blocking: `unshare`/`clone` carrying `CLONE_NEWUSER`, which Docker's default profile permits only to a container holding `CAP_SYS_ADMIN`, and `pivot_root`, which it blocks outright.

The ADR's *conclusion* may still be right. Its *premise* is not, and it is currently steering decisions — including the sequencing advice that cross-model diversity is recoverable "on the host when wanted," which describes an act nobody performs.

**Cost of doing nothing:** the single-family gate stays permanent rather than opt-out, the design stage has no second engine to fall back to when the Claude tier is strained, and ADR 0002 keeps asserting a privilege cost that does not exist.

## Options

**Option A — Status quo: Codex stays host-only.** · Change nothing; a cross-model pass remains a manual host-side run. · No security delta, no work. Rejected by the measurement above only in its *reasoning*, not its outcome — the outcome may survive a fresh argument. Costs: the opt-in stays unreachable from the loop, and `design` keeps its single engine.

**Option B — `--security-opt seccomp=unconfined`.** · Drop Docker's syscall filter for the verb container. · One flag, measured working. Removes the entire filter to unblock two syscall families — a far wider grant than the problem needs, on a container that holds the ssh key, `GITHUB_TOKEN`, and a read-write bind mount of the repo.

**Option C — A targeted seccomp profile.** · Ship `docker/seccomp-codex.json` = Docker's default profile plus `pivot_root` and unconditional `unshare`/`clone`; the wrapper passes `--security-opt seccomp=<profile>`. No capability added. · The narrowest delta that clears the measured gate, and auditable as a diff against the published default. Costs: a vendored copy of Docker's default profile that can drift from the daemon's builtin, and a loosening that is real even if narrow.

**Option D — `--cap-add SYS_ADMIN`.** · Grant the capability, keep the default profile. · **Measured insufficient** — `pivot_root` still fails — so it would have to be combined with a profile change anyway, while granting the capability the security argument is most concerned about. Strictly worse than C.

**Option E — Run the engine host-side, brokered by the runtime host.** · ADR 0012's `harness serve` spawns the engine subprocess on the host, where bwrap works and `~/.codex` lives; no container privilege changes at all. · Structurally the cleanest, and #308 is already chartered to make the path equivalence it needs real. Costs: it depends on the entire ADR 0012 chain (#305–#308) landing first; it puts untrusted diff content in front of an engine running *outside* the container, which is a strictly larger threat-model change than C, not a smaller one; and the operation does not exist in ADR 0012, so it is a new decision either way.

## Recommendation

**Option C for the sandbox, and Codex as a selectable engine on both verbs — sequenced so the sandbox change is verifiable on its own.**

C is the smallest change that removes the blocker (`engineering-principles` — smallest change that fully solves the problem). It is preferred over B because "remove the filter" and "allow two syscall families" are not the same grant and only the second is justified by evidence, and over E because E's security delta is larger than C's while its dependency chain is much longer — E moves untrusted content outside the container boundary, where C keeps it inside a container that gains no capability.

The security argument C must win is narrower than ADR 0002's, and worth stating plainly for the decider: the container **already** holds the ssh key, the tracker token, and a read-write mount of the repo. Seccomp is not what protects those from a prompt-injected diff — the engine's own read-only sandbox is, and today that sandbox cannot start, which is why the Codex path degrades rather than protects. Loosening two syscall families to switch that sandbox on trades a narrower host-kernel boundary for a working capability boundary around credentials that are already in reach. That is a real trade and it may still be declined; it is not the trade ADR 0002 declined.

**The engine is chosen at invocation, not on the ticket.** `/harness run` takes a `--codex` flag that it passes through to both engine verbs as `--engine codex`, mirroring what `commands/build.md` already does for its review step. The reason is that the choice answers "which subscription has headroom this hour", which is a property of the moment, not of the work — so the hourly tick's thin caller carries the flag and the ticket carries nothing. This deliberately does **not** extend ADR 0005: its `<dimension>:<tier>` labels carry a per-ticket judgment made at spec-authoring time, and an operational capacity toggle is a different question with a different lifetime. Provenance stays auditable regardless, because the ledger already records `engine` per event — the run says which engine judged it even though the ticket never did.

One flag covers both verbs rather than one per dimension: capacity is shared between them, so splitting the control would create a combination nobody has a reason to select.

On the engines: `review` needs no engine work — `--engine codex` already exists and the usage-limit fallback (CAL-702) already degrades a depleted tier to *available* rather than *false-fail*. `design` needs the engine union built for the first time, and its output channel is the interesting part: the primary channel is a file written under a `claude`-shaped `--settings` grant (`design_protocol.py:358`), which has no Codex equivalent, while the existing stdout fallback (`HARNESS-DESIGN <nonce>` marked block) is engine-agnostic and needs no write capability at all. Codex should deliver on the marked-block channel — but that channel is currently also a *detector* for a broken permission grant, and using it as a normal channel for one engine disarms that detector unless the expectation becomes per-engine.

## Open decisions

| Decision | Who decides | Resolution (2026-08-04) | Recorded in |
|---|---|---|---|
| Is the targeted seccomp loosening acceptable on a container that reviews untrusted diffs — i.e. does ADR 0002's conclusion survive its corrected premise? | user | **Settled — targeted profile.** Option C. The conclusion does not survive: a profile delta with no capability grant is a different trade from the one ADR 0002 declined. | ADR 0013; amendment to ADR 0002 |
| Does `design` get an `--engine` flag (amending ADR 0007's "Claude only, no engine union"), or does Codex-for-design stay unbuilt until the sandbox change has run in anger? | architect | **Settled — build it, sequenced after the sandbox ships.** Design is where the unconditional-Opus cost sits, so it is the point of the exercise; it does not lead. | ADR 0013; amendment to ADR 0007 |
| Is Codex's design channel the stdout marked block, and if so how is the broken-grant detector preserved for the claude engine? | architect | Open — settled inside breakdown item 6's change spec. | `specs/features/verb-model.md` |
| How is the engine selected per run? | user | **Settled — an invocation flag, not a ticket property.** `/harness run --codex` passes `--engine codex` to both engine verbs; the hourly tick carries the flag when capacity says so. ADR 0005 is **not** extended. | ADR 0013 |
| Does the profile land on `docker/harness-wrapper.sh` now, or wait for the ADR 0012 spawner (#307/#308) that is chartered to replace it? | user | **Settled — wrapper now.** The #304–#313 chain is ten unstarted tickets; a one-flag change does not wait behind it. Moving it into the spawner is accepted rework. | ADR 0013; #307/#308 change specs |

A sixth question is adjacent and worth settling in the same pass, because it distorts any spend comparison made afterwards: **nothing sets the ADR 0005 tier labels at spec-authoring time**, so the review dimension's current cost profile is a fallback, not a decision. That is its own small ticket, not part of this proposal.

## Breakdown

Each is shippable alone. 1 and 2 stand without any engine work; 3–7 depend on 1.

1. **Targeted seccomp profile** — vendor `docker/seccomp-codex.json` (Docker's default + `pivot_root` + unconditional `unshare`/`clone`), wrapper passes `--security-opt`, no capability added. The acceptance criterion is behavioural: bwrap starts in-container, and a control syscall the profile does not grant stays blocked. Asserting the flag is present would prove nothing.
2. **Amend ADR 0002** — record the measurement, correct the cost claim, and point at ADR 0013 for the decision the corrected premise produced.
3. **`doctor` reports the in-container Codex verdict from a probe, not a constant** — `harness/cli/doctor.py:259` currently encodes ADR 0002's conclusion in its remediation text, so it will keep reporting the engine unusable after it becomes usable.
4. **`/harness run --codex`** — the flag, its passthrough to both engine verbs as `--engine codex`, and a guard that the routine command can carry it. `review` needs no verb change; keep `is_sandbox_blocked_defer` armed, since it is the right response if the profile ever regresses.
5. **`design` engine union** — `Engine` type, `--engine` flag, Codex command builder, per-engine channel expectation. The ledger needs no schema change: the design event already carries generic `engine` and `model` fields (`harness/events/payloads.py:440`).
6. **Amend ADR 0007** — "Claude only" becomes engine-selectable; restate what "Opus unconditionally" means when the engine is not Claude, and state the design stage's behaviour when a Codex design fails with no fallback engine.
7. **Measure whether diversity bought anything** — a ledger query comparing verdict distribution and issue categories by engine. Without it, "cross-model review" stays an assumption; ADR 0005 and `specs/proposals/per-engine-timeout-ceiling.md` both set the precedent that these claims get measured before they are believed.

## Risks / unknowns

- **Nothing downstream of "bwrap starts" is verified.** There is no Codex subscription on this machine, so the probe stopped at sandbox init — which is the wall ADR 0002 documents, and is genuinely measurable without auth. That a real `--engine codex` review completes end-to-end (auth, model turn, per-command sandboxing across a full review) is untested. Item 1 should ship on the bwrap-start criterion and item 5 should not be claimed done without a real run.
- **The wrapper is being replaced underneath this.** ADR 0012 moves container construction into `harness serve` (#307) and platform-specific spawn concerns into #308. A `--security-opt` added to `harness-wrapper.sh` must move; sequencing item 1 before or after that chain is the open decision above, and doing it twice is the cost of getting it early.
- **A vendored seccomp profile drifts.** Docker's builtin evolves; a copy pinned in this repo silently diverges. The guard should assert the *behaviour* (bwrap starts, and a control syscall stays blocked), not the file's contents.
- **`design` has no engine fallback.** `review` degrades a depleted Codex tier to Claude (CAL-702). ADR 0007's design failure path is degrade-and-record — a failed Codex design produces *no design*, and the run continues without one. Moving the unconditional-Opus stage onto the tier-limited engine without an equivalent fallback trades spend for a stage that silently stops happening.
- **Disarming the stdout detector.** The design fallback channel exists to catch a permission-grant regression that no test can reach, because no test spawns a real `claude`. Making it a normal channel for Codex must not make `channel='stdout'` unremarkable for Claude.
- **What would invalidate the recommendation:** a Codex release that drops bundled bwrap for landlock/seccomp (0.146.0 still ships `codex-resources/bwrap`, and `codex debug` exposes no landlock subcommand) would remove the blocker without any profile change — re-probe before building item 1.
