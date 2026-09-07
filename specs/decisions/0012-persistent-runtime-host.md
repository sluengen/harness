# ADR 0012 — The verbs get a persistent runtime host; the verbs themselves stay one-shot

- **Status:** Accepted
- **Date:** 2026-08-03
- **Source:** the `persistent-runtime-host` proposal (settled; removed from the tree by #547, kept in git history)

## Context

`docker/harness-wrapper.sh` is 380 lines of bash on the path of every verb invocation. Per call it fast-forwards the source checkout, compares the image against it and rebuilds when stale, computes its own drift status, resolves the tracker credential through three fallbacks, reads and conditionally refreshes the Claude OAuth token from the macOS Keychain, probes the ssh-agent, and constructs the `docker run`. Those are a runtime host's responsibilities, discharged by a process that exists for the duration of one call. Four costs follow from the shape rather than from any defect in the script:

- **The delivery mechanism cannot deliver a fix to itself.** `~/bin/harness` symlinks into a live working tree, so wrapper text is whatever that tree currently holds; a shipped wrapper fix is not live until the tree advances, including the fix whose purpose is to advance it (#286). The self-sync guard added there closes the ongoing case and cannot close the bootstrap case.
- **Correctness depends on ambient shell state.** `$(pwd)` is the only channel for naming the target repo, so every call means something different depending on where the shell happens to be. This has broken verb calls five times (#146, #147, #150, #155, #159).
- **Periodic work has no runner.** Fixed overhead measured at ~3.2s per call, dominated by a 2.9s `git fetch` on the path of every verb; meanwhile `reclaim --stale` and `worktrees cleanup` are correct and nothing invokes them — 34 orphaned worktree directories and seven live ones, ~1.16 GB, accumulated until a manual sweep on 2026-08-01.
- **The credential path is macOS-shaped and unreusable.** The "refresh if within five minutes of expiry" heuristic exists precisely because a short-lived token is read by a process that will not be alive to renew it.

SPEC §16 lists both "long-running daemon / server" and "built-in scheduling" as explicit non-goals, so this cannot be built without amending it.

## Decision

**A persistent host-side process owns credentials, image freshness, container construction, and periodic maintenance. Every verb remains a one-shot container. The host process holds no run state.**

- **The no-run-state constraint is the whole safety argument, not a design preference.** The close gate rests on the ledger being the only memory of a run: a verb that dies mid-flight leaves no half-state anywhere, because there is nowhere for it to live. A host process that cached run status, held an open transaction, or tracked in-flight verbs would break that property while appearing to work. It is a credential broker, a spawner, and a scheduler — nothing that outlives a request describes a run.
- **SPEC §16 is amended, not overruled.** The non-goals' intent — the CLI runs, completes, exits; state persists in SQLite — is preserved for every verb. What changes is that the harness supplies its own runtime host rather than borrowing launchd's. The carve-out is bounded by the constraint above: if the host process ever holds run state, it has exceeded the carve-out.
- **A verb's target repo is stated, not inferred.** Verbs accept an explicit repo argument; the implicit-CWD form emits a deprecation warning for one release and is then removed. Ambient shell state is not an interface.
- **The host is cross-platform, with Windows served through WSL.** Credential store, ssh-agent forwarding, bind-mount path translation, and subprocess-timeout selection all sit behind a platform interface with macOS and WSL/Linux providers, rather than macOS assumptions inlined at each site.
- **Path equivalence is asserted, not assumed.** The workspace must resolve to the same absolute path for the host process, the client, and every verb container. Diverging mount points fail silently, and the cross-platform decision multiplies the ways they can diverge.

The general rule this sets: **continuity belongs to the host, never to the run.** Anything that must survive between calls is infrastructure; anything that describes a run belongs in the ledger.

## Alternatives rejected

- **Keep hardening the wrapper.** Every defect so far has been met with a guarded bash fix plus an executing test against stubbed `git`/`docker`, and that has worked. Rejected because it cannot reach the self-deployment floor at all — no script served from a working tree can — and because it continues to accrete load-bearing logic that exists only on macOS and only inside one file.
- **Port the wrapper to Python but keep it one-shot.** Fixes portability and reuse, and is a genuine improvement. Rejected as the *destination* (it is retained as the first step) because it leaves self-deployment, the CWD coupling, and the missing periodic runner exactly as they are; the per-call shape is the thing causing three of the four costs.
- **Make the harness container itself persistent.** The literal reading of "run the harness as a service." Rejected on two grounds: a container cannot read the macOS Keychain, so the credential problem worsens rather than improves; and holding run state in a live process undermines the ledger-is-the-only-memory property the close gate rests on. This trades away the guarantee the system exists to provide, in exchange for convenience.
- **Mount the docker socket into callers instead of building a spawner.** Simpler, no shim. Rejected on the reasoning already recorded for the in-container engine (ADR 0002) and the retired launcher design: the docker socket is root-equivalent on the host, so anything reaching it can mount the whole filesystem. The load-bearing property of a spawner is that the caller never specifies the mount, image, privilege, or env — it names a verb and a repo, and the host constructs the invocation.

## Consequences

- **A process that must be running is a failure mode the script does not have.** The client must fall back to spawning the container directly when the socket is unreachable, built in from the start rather than added after the first outage.
- **The supervision mechanism may not be portable.** launchd has no WSL equivalent and systemd under WSL2 requires opt-in configuration, so client-side autostart may be the only shared answer — which makes "not running" invisible rather than an error, and must be designed for.
- **WSL support is a claim until it is exercised on a real Windows host.** The development machine is macOS; the platform-provider code will be written against documentation. Until validated, WSL is described as untested rather than supported.
- **Parallel writers against the ledger change regime.** WAL is enabled and runs use distinct worktrees and ULIDs, but WAL over a bind mount from container to host FS with concurrent writers is untested and currently masked by serialized invocation. Serialize per repo until measured; the measurement gates the host-process change rather than following it.
- **The socket's operation surface will drift unless derived.** The prior launcher's hardcoded operation list went stale as soon as a verb was added, and six verbs have been added since. A guard is required, not optional.
- **This supersedes nothing, and revives no deferred consumer.** `harness/cli/serve.py`, `harness/launcher.py`, and `harness/launcher_client.py` shipped and were deleted in `84d73d0` (CAL-712) as scaffolding for a consumer that did not exist. That reasoning was correct and still holds: the justification here is the wrapper's own measured defects, and the decision would stand if no additional consumer ever appeared. The deleted code is prior art recoverable from `84d73d0^`, not a restoration target — its operation surface predates `design`, `defer`, `checkpoint`, `reclaim`, `promote`, and `release`. The convention its guard encodes — scaffolding for a hypothetical consumer stays out of the tree — remains in force.
