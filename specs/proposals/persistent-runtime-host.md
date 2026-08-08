<!-- guidance:template-proposal@0.1.2 -->
---
proposal: persistent-runtime-host
status: accepted         # draft | under-decision | accepted | shipped | rejected | split
date: 2026-08-03
decided: 2026-08-03      # operator; decisions recorded in specs/decisions/0012-persistent-runtime-host.md
related:
  - specs/features/verb-model.md
  - specs/features/cli-surface.md
  - specs/features/worktree-lifecycle.md
  - specs/decisions/0002-in-container-review-engine.md
---

# Proposal: a persistent runtime host for the verbs

> The wrapper has become a credential broker, a deployment controller, and a container spawner that re-derives all three on every single verb call — and one of its jobs is structurally impossible in that shape. Give those responsibilities a process that stays up, while every verb stays a one-shot container.

## Problem / motivation

`docker/harness-wrapper.sh` is 380 lines of bash on the path of every verb invocation. Per call it fast-forwards the source checkout, compares the image against it and rebuilds when stale, computes its own drift status, resolves the tracker credential through three fallbacks, reads and conditionally refreshes the Claude OAuth token from the macOS Keychain, probes the ssh-agent, and constructs the `docker run` with mounts, env, and git identity.

That is a runtime host's job list. It is currently discharged by a script that exists only for the duration of one call, and four costs follow from the shape rather than from any defect in the script.

**It cannot deploy a fix to itself.** `~/bin/harness` is a symlink into a live working tree, so wrapper text is served from whatever that tree currently holds. A shipped wrapper fix is not live until the tree advances — including the fix whose purpose is to make the tree advance. This is recorded as #286: the shipping run had to perform the fast-forward by hand or the ship was notional. The self-sync guard added there closes the *ongoing* case and cannot close the *bootstrap* case, because no version of "a script served from a working tree" can. The delivery mechanism has a floor it cannot get under.

**Its correctness depends on ambient shell state.** `$(pwd)` is mounted as `/workspace` and is the only channel for saying which repo a verb acts on. Every call therefore means something different depending on where the calling shell happens to be. This has broken verb calls on five separate occasions (#146, #147, #150, #155, #159) — always the same way, always after the fix for the previous one. A caller cannot state its intent; it can only arrange its environment and hope.

**Work that should be periodic is per-call, and work that should be periodic does not happen at all.** The fixed overhead measured on this machine is ~3.2s per verb call, dominated by a 2.9s `git fetch` — a network round-trip on the path of every verb, bounded only by a 30s timeout, repeated five or more times per run. Meanwhile `reclaim --stale` and `worktrees cleanup` are correct and nothing runs them: 34 orphaned worktree directories and seven live ones, ~1.16 GB, accumulated until a manual sweep on 2026-08-01. A one-shot CLI has nowhere to put a recurring task, so recurring tasks are somebody's memory.

**The credential path is macOS-shaped and unreusable.** `security find-generic-password` is the only route to the Claude token, and the "refresh if within five minutes of expiry" heuristic exists because a short-lived token is being read by a process that will not be alive to renew it. None of that logic is available to the native `uv tool install` entry point, and a Linux self-hoster has no equivalent path at all. The refresh strategy is a workaround for having no process that persists.

Doing nothing is a real option and has worked so far — every one of these has been met by adding bash. The question is whether the next one should be too.

## Options

**Option A — Keep hardening the wrapper.** Continue the current approach: each defect gets a guarded bash fix plus an executing test against stubbed `git`/`docker`. · Cheapest per fix, and the existing test approach genuinely works. But it cannot reach the self-deployment floor at all, leaves the CWD coupling and the missing maintenance runner untouched, and grows the amount of load-bearing logic that only exists on macOS and only inside one script.

**Option B — Port the wrapper's logic to a tested Python module, still one-shot.** The wrapper becomes a shim that calls `harness` code; the credential resolution, staleness comparison, and `docker run` construction become functions with unit tests, shared with the native entry point. · Strictly better than A on portability and reuse, and it is a prefix of Option C rather than a detour. It does not touch self-deployment, the CWD coupling, or the missing periodic runner — the per-call shape is unchanged.

**Option C — `harness serve`: a persistent host process, thin client, one-shot verbs.** A long-lived host-side process owns credentials, image freshness, container construction, and periodic maintenance, exposing the verb surface over a local unix socket. `~/bin/harness` becomes a thin client that forwards argv plus an explicit repo. Verbs remain one-shot `docker run` containers spawned by it; the process holds no run state. · Addresses all four costs. Costs a process that must be installed, supervised, and versioned; a socket protocol that must stay in step with the verb surface; and it reopens two SPEC §16 non-goals (see Open decisions).

**Option D — Make the harness container itself persistent.** The literal reading of "run the harness as a service": a long-lived container serving verb requests in-process. · Rejected. A container cannot read the macOS Keychain, so the credential problem is made worse rather than better. More importantly, holding run state in a live process undermines the property the close gate rests on — the ledger is the only memory, so a crashed verb can leave no half-state anywhere. This trades away the guarantee the system exists to provide.

## Recommendation

**Option C, reached through Option B**, with one constraint that makes it safe:

> The persistent process holds no run state. It is a credential broker, a spawner, and a scheduler. Every verb remains a one-shot container whose only durable output is the ledger and the git tree.

Under that constraint the persistent process is not the harness becoming a service — it is the harness acquiring a runtime host, in the same relation launchd already stands in. The verb model, the SHA-bound close gate, and the ledger-is-the-only-memory property are all untouched, because none of them depend on the *caller* being short-lived; they depend on the *verb* being short-lived, which does not change.

Sequencing through B is not ceremony. B is a strict prefix of C — the logic has to leave bash before it can be hosted — and it ships value on its own (portability, unit-testable credential resolution, a native entry point that stops being second-class). If C stalls on the open decisions below, B is not wasted work.

This follows *smallest change that fully solves the problem*: the problem is a per-call process discharging responsibilities that need continuity, and the change is to give exactly those responsibilities continuity, without extending it to anything else.

Note that some of this existed. `harness/cli/serve.py`, `harness/launcher.py`, and `harness/launcher_client.py` shipped and were deleted in `84d73d0` (CAL-712) on the grounds that they were scaffolding for a consumer that did not exist. That reasoning was correct then and is not what this proposal relies on — the case above is entirely about the wrapper's own defects and would stand if no other consumer ever appeared. The deleted code is recoverable from `84d73d0^` and should be read as prior art, not restored wholesale: its operation surface predates `design`, `defer`, `checkpoint`, `reclaim`, `promote`, and `release`.

## Open decisions

Three were settled by the operator on 2026-08-03; two remain and are carried into the tickets that need them.

| Decision | Who decides | Outcome | Recorded in |
|---|---|---|---|
| Does a host-side spawner reopen SPEC §16's "long-running daemon / server" and "built-in scheduling" non-goals, or is it outside them because it is not the harness? | user | **Settled — amend §16.** Build the full host process. The carve-out is bounded by the no-run-state constraint below: the harness itself remains one-shot, and §16's intent (the CLI runs, completes, exits; state persists in SQLite) is preserved for every verb. | `SPEC.md` §16 + ADR 0012 |
| Does the thin client keep the implicit-CWD form for compatibility, or is an explicit repo required? | user | **Settled — explicit required, warn first.** Accept the explicit argument now, deprecation-warn on the implicit form for one release, then remove it. Every existing caller keeps working through the transition. | `specs/features/cli-surface.md` |
| Is the host process macOS-only by construction, or does it take a pluggable credential provider? | user | **Settled — cross-platform is a requirement, with Windows served through WSL.** This is broader than credentials; see *Scope consequence* below. | `specs/features/verb-model.md` + ADR 0012 |
| Is the socket's operation surface an explicit allowlist or derived from the registered command set? An allowlist was already stale within two tickets last time. Recommendation: derive, plus a drift guard. | architect | Open — settled inside breakdown item 4. | `specs/features/cli-surface.md` |
| How is the process supervised — launchd agent, socket activation, or client-side autostart? This determines whether "not running" is a failure mode or invisible. Cross-platform support makes this harder: launchd has no WSL equivalent, so the answer must be either per-platform or supervisor-agnostic. | user | Open — settled inside breakdown item 4. | `RUNBOOK.md` |

### Scope consequence of the cross-platform decision

Supporting WSL is not a second credential provider bolted onto an otherwise macOS design. Four host couplings in the current wrapper are macOS-specific, and only the first is about credentials:

- **Credential store.** `security find-generic-password` does not exist on WSL; Claude Code on Linux uses a file-based store. Two providers behind one interface.
- **ssh-agent forwarding.** `/run/host-services/ssh-auth.sock` is a Docker Desktop for Mac path. The Windows/WSL2 backend exposes the agent differently, and `close` is the verb that pushes — so getting this wrong breaks shipping, not something cosmetic.
- **Bind-mount path translation.** A repo inside the WSL filesystem mounts cleanly; one on `/mnt/c/...` crosses the Windows filesystem boundary with different performance and permission behaviour. The path-equivalence requirement (the workspace resolving to the same absolute path for host, client, and verb container) is what makes this load-bearing rather than a preference.
- **`timeout` / `gtimeout` availability and git identity resolution**, both currently probed with macOS assumptions.

The honest consequence: this decision converts "port the wrapper" into "port the wrapper and define a host-platform abstraction," and it adds a target that cannot be tested on the development machine. Both are reflected in the breakdown and the risks.

## Breakdown

Ordered by dependency. Items 1–3 stand on their own and deliver value if 4–8 never ship; that is deliberate, per the *what would invalidate this* clause below.

1. [#304] **Amend SPEC §16 and point it at ADR 0012** — records the carve-out and its bound. Doc-only; unblocks everything after it.
2. [#305] **Host-platform abstraction and the credential port** — move credential resolution, `timeout` selection, and git-identity resolution out of bash into a tested module behind a platform interface, with macOS (Keychain) and WSL/Linux (file store) providers. The wrapper delegates; the native entry point gains the same path.
3. [#306] **Explicit repo argument on every verb, deprecation-warning the implicit form** — removes the CWD trap class. Independent of the host process.
4. [#307] **`harness serve` — unix socket, verb spawner, no run state** — the client speaks it and falls back to spawning the container directly when it is not up. Settles the two remaining open decisions (operation surface, supervision) inside its change spec.
5. [#308] **Platform-specific spawn concerns** — ssh-agent forwarding and bind-mount path translation per platform, with path equivalence asserted rather than assumed.
6. [#309] **Credential brokering moves into the host process** — background renewal replacing the five-minute expiry heuristic.
7. [#310] **Periodic maintenance inside the host process** — `reclaim --stale` and `worktrees cleanup` on a timer, each sweep recorded in the ledger.
8. [#311] **Protocol/verb-surface drift guard** — a registered verb the socket cannot reach fails the gate.
9. [#312] **Deployment via image and entrypoint rather than a symlinked working tree** — closes #286's bootstrap case. Ships last because it changes how everything else arrives.
10. [#313] **WSL end-to-end validation on a real Windows host** — the one item that cannot be done on the development machine. Explicitly separated so its absence is visible rather than assumed away.

## Risks / unknowns

**A process that must be running is a failure mode the script does not have.** The one-shot wrapper is never down. Mitigation is the fallback in item 3 — a client that cannot reach the socket spawns the container directly — which must be built in from the start, not added after the first outage.

**SQLite under genuine parallel writers is untested.** WAL is enabled and runs use distinct worktrees and ULIDs, so distinct-row concurrency is sound in principle. What is untested is WAL over a bind mount from container to macOS host FS with concurrent writers, which today is masked because invocations serialize. A host process that admits concurrent requests changes that regime. Serialize per repo until it is measured; treat the measurement as a gate on item 3, not a follow-up.

**Protocol drift is the failure that would repeat.** The prior operation surface went stale the moment a verb was added. Item 6 exists specifically for this and should not be deferred behind item 3.

**The convention CAL-712 established still binds.** Its guard (`tests/unit/test_hermes_retired.py`) asserts that scaffolding for a non-existent consumer stays out of the tree, and that is a good rule. Revisiting the guard is legitimate only because the justification here is the wrapper's own defects; if this proposal ever needs a hypothetical consumer to carry it, that is the signal it has failed.

**A supported platform that cannot be tested locally is a claim, not a capability.** WSL support is now a requirement and the development machine is macOS. Everything in items 2 and 5 will be written against documentation rather than observation, and the failure mode is silent: a WSL user hits it, not the author. Item 10 exists to keep that visible. Until it passes, WSL should be described as untested in `README.md` rather than supported — an untrue support claim is worse than an absent one.

**Cross-platform supervision has no shared answer.** launchd is the macOS mechanism and has no WSL equivalent; systemd under WSL2 requires opt-in configuration. The supervision decision deferred into item 4 may not resolve to one mechanism, in which case client-side autostart is the only portable option — which in turn makes "the process is not running" invisible rather than an error, and that has to be designed for rather than discovered.

**What would invalidate the recommendation.** If measurement shows the fixed per-call overhead is not on any critical path and the maintenance sweeps can be driven adequately by the existing scheduled-task mechanism, then only the self-deployment and CWD costs remain — and items 3 and 9 address those with no host process at all. That measurement should be taken before item 4 is built, not after. Equally, if item 2 shows the platform abstraction is substantially larger than the wrapper logic it wraps, the cross-platform requirement should be re-examined on its own terms rather than carried silently into every item after it.
