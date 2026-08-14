---
feature: runtime-host
status: implemented
last_updated: 2026-08-14
tickets: ["#307", "#308", "#309", "#310", "#311", "#370", "#380", "#383"]
---

# Runtime host (live)

The as-built record of `harness serve` — the persistent host-side process that
owns container construction and spawns each verb as a one-shot container. It is
the first delivery against [ADR 0012](../decisions/0012-persistent-runtime-host.md)'s
decision that *continuity belongs to the host, never to the run* (#307).

Related records: [CLI surface](cli-surface.md) (where `serve` sits among the
commands), [verb model](verb-model.md) (what the spawned containers do), [run
ledger](run-ledger.md) (the state this process deliberately does not hold).

## What shipped

Four modules, split along one hard constraint: the client runs on the host under
a bare `python3` before any container exists, so everything it touches is
stdlib-only and cannot import `harness.cli` (`tests/unit/test_hostenv_stdlib_only.py`).

| Module | Layer | Role |
|---|---|---|
| [`harness/hostenv/protocol.py`](../../harness/hostenv/protocol.py) | stdlib-only | Frame encode/decode, socket-path precedence, refusal reasons, exit mapping. |
| [`harness/hostenv/spawn.py`](../../harness/hostenv/spawn.py) | stdlib-only | The one home for `docker run` argv construction and the `--repo` rewrite. |
| [`harness/hostenv/client.py`](../../harness/hostenv/client.py) | stdlib-only | Connect → send → relay → exit, falling back to a direct spawn. |
| [`harness/cli/serve.py`](../../harness/cli/serve.py) | CLI | `harness serve`: resolve the operation surface, hold the per-repo lock, bind the socket, start the broker and the sweep scheduler. |

Two more CLI-layer modules arrived with #310: the surface derivation moved to
[`harness/cli/serve_surface.py`](../../harness/cli/serve_surface.py) (a pure
extraction, so `serve.py` had room for the scheduler's wiring inside the
500-line rule), and the scheduler itself lives under `harness/maintenance/`
— see [the maintenance scheduler](#the-maintenance-scheduler).

`docker/harness-wrapper.sh` is the live caller. Its tail is now

```bash
exec env PYTHONPATH=… "${_HOST_PY[@]}" -m harness.hostenv.client "$(pwd)" -- "$@"
```

replacing the `hostenv env` export block and the hand-rolled `docker run` — so a
running `harness serve` actually receives requests, and the subsystem has a
production caller rather than only tests. The wrapper fell from 158 to **116**
executable lines and the ratchet in `tests/unit/test_wrapper_delegates.py` was
re-baselined 165 → 120, the downward move the design predicted.

Two things stayed in bash on purpose. The **image-freshness guard** and the
**source-checkout sync** exist partly to detect "this wrapper has no checkout
behind it" — the detached-copy deployment, which is exactly the state in which
checkout-resident Python cannot be imported. A guard that cannot fire in the
deployment it was written for is not a guard.

One behaviour changed rather than moved, and it is a **hard error where there used
to be a warning**: with no usable host Python the wrapper now exits 1 naming
`HARNESS_HOST_PYTHON`. Before the rewire a missing interpreter cost only credential
resolution and the wrapper still ran its own container; now the client *is* the
runtime, and the alternative — re-implementing container construction in bash for
the degraded path — is the second security posture this change exists to delete.

### Credentials are resolved per request

`harness.hostenv.host.resolve_container_env` is the one resolver, called by both
spawn paths on **every** request. It returns credential values (destined for the
spawned `docker` process's own environment, from which docker forwards them by
name) and the git identity (pinned by value, defaulted per field). `python3 -m
harness.hostenv env` is now a thin CLI over the same function, so the three
callers cannot drift.

Per request, not once, is the load-bearing half. A Claude OAuth token expires; a
`harness serve` is designed to outlive many of them, so bind time is the one
moment whose environment is guaranteed to be stale later. Forwarding the ambient
environment instead would also mean a server started from a shell without
credentials spawns credential-less containers forever — failing much later as an
in-container 401 that reads as a review failure (CAL-941). The workdir passed to
the resolver is the **requested repo**, not the process's cwd, because `.env`
lives in the target repo and a persistent server's cwd is whatever shell started
it. An `UnsupportedHost` stops the spawn with a named message rather than shipping
a blank credential.

The ssh-agent is resolved the same way and gated the same way the wrapper gated
it: `HostPlatform.ssh_agent_is_live` runs `ssh-add -l`, and only a socket whose
agent actually holds a key is forwarded. `SSH_AUTH_SOCK` routinely outlives the
agent it names, so its presence is not evidence — forwarding a dead socket mounts
it, joins group 0, and makes every `git push` over SSH fail against a healthy
agent instead of falling back to tokenized https. The probe runs only when there
is a socket to check.

**The mount source is Docker's bridge, not that socket.** Docker Desktop exposes
the host agent inside the VM at the fixed `/run/host-services/ssh-auth.sock`; the
host's own `SSH_AUTH_SOCK` on macOS is a per-session launchd path that exists only
host-side. The spawner mounted the latter, which forwards nothing — caught by the
retargeted hardening guard when the wrapper stopped being the live caller, and
fixed here to the wrapper's proven spelling. The host socket is the liveness
*signal*. Choosing the source per platform **landed in #308**: the pairing is now
`HostPlatform.ssh_agent_forwarding`, and macOS is the only provider that returns
the bridge — a native Linux daemon mounts the probed socket directly, and under
WSL the bridge reaches a different agent entirely. See
[host-platform](host-platform.md).

### Where the container guards moved

Nine guards asserted container properties as **text inside the wrapper** — the ssh
and codex mounts, the `known_hosts` path, `--group-add 0`, the TTY flags, the
`/workspace` mount, the pinned allowlist, the ssh gate, and the bytecode pin. Their
subject moved, so they were retargeted at the **constructed argv** rather than
deleted; reading the argv the spawner actually builds is the stronger form of the
same assertion, and it covers both spawn paths at once. Two changed shape rather
than home: the TTY guard dropped its bash-specific `SC2046` clause (a list cannot
word-split) and now asserts the behaviour that clause protected — `-it` when stdin
is a terminal, and *no* argument otherwise. The `/workspace`-seam derivation over
`docker/` no longer finds the wrapper, which is now correct rather than a
regression; because a text scan cannot see a mount built from constants, the
programmatic seam gained its own behavioural guard alongside.

`tests/unit/test_hostenv_per_request_credentials.py` asserts both halves against a
provider that **rotates its token on every read** — a cached implementation hands
the second container the first container's token and fails. Nothing resolved is
retained: the value dies with the call, which keeps ADR 0012's "no run state" true
of credentials too.

**#309 scoped this rule; it did not weaken it.** Everything above stays true of the
tracker credentials, the git identity and the three spawn concerns, on every path,
and of the whole client direct-spawn path including its agent credential. The one
exception is the **agent** credential over the socket, which a production `harness
serve` now brokers — see [the credential broker](#the-credential-broker) below. The
rotating-provider guard was re-pointed accordingly: it asserts rotation of
`GITHUB_TOKEN` and `LINEAR_API_KEY`, because asserting it of
`CLAUDE_CODE_OAUTH_TOKEN` had become a claim production deliberately contradicts,
and it kept passing only because that fixture builds a `VerbServer` with no broker.
The property it stopped asserting is asserted better, at the call site, by
`tests/unit/test_serve_credential_brokering.py::test_the_brokered_request_path_reads_no_store_and_calls_no_refresh`;
`test_a_stale_agent_token_is_refreshed_before_the_container_is_spawned` is unchanged
and still holds the client path's freshness rule.

### The credential broker

ADR 0012 names the persistent host process *"a credential broker, a spawner, and a
scheduler"*. #307 shipped the spawner and #310 the scheduler (below);
[`harness/hostenv/broker.py`](../../harness/hostenv/broker.py) is the broker, and it
is a fifth stdlib-only module in that layer (it imports `container_env`, `host` and
`credentials`, and nothing from `harness.cli`).

**Where a request's agent credential comes from is a seam.**
`container_env.AgentCredentialSource` has two implementations that answer opposite
questions about refusing:

| Source | Used by | Resolves on the request path | Can refuse |
|---|---|---|---|
| `container_env.RequestRefreshingSource` (the default) | the client's direct spawn, `python3 -m harness.hostenv env`, and any `VerbServer` built without a broker | yes — today's `resolve_agent_credential`, verbatim | **no, structurally** |
| `broker.BrokeredSource` | a `VerbServer` from `serve.build_server`, i.e. production `harness serve` | **no** — the broker's own credential | yes |

`AgentCredentialSource.refusal` is a concrete base method returning `None`, and
`RequestRefreshingSource` does not override it. CAL-941's rule is therefore
preserved on that path as *the absence of a branch* rather than as a policy
sentence — see [host-platform](host-platform.md), which owns the request-resolving
rule. `resolve_container_env` gained a `credentials=` keyword defaulting to that
source, which is why `client.py` and `__main__.py` are a **zero diff** across #309.

**The schedule is derived, not guessed.** A healthy credential is renewed
`RENEWAL_LEAD_MS` = 20 minutes before expiry, because the longest a single engine
call may run is `loop.engine_timeout_seconds` (900s) and the request path begins
refusing inside `REFRESH_WINDOW_MS` (300s); 20 minutes therefore leaves any credential
served in a healthy system at least fifteen minutes of life, which a twelve-minute
`review` fits inside. `next_delay_ms` is a pure function of the last record: `VALID`
wakes `RENEWAL_LEAD_MS` before expiry, `ABSENT` re-checks every 5 minutes so an
operator running `claude` and `/login` is picked up without a restart, and `FAILED`
retries every 60 seconds because the request path is refusing for as long as that
state lasts. Every wake is floored at `MIN_RENEWAL_INTERVAL_MS` = 30s, which is what
stops a store with an unknown expiry (`expires_at_ms == 0`, which reads as stale)
spinning the thread.

The load-bearing relation is asserted behaviourally rather than as a comparison of
constants: `test_the_schedule_wakes_before_the_request_path_would_refuse` measures
that `now + next_delay_ms(record, now) < expires_at_ms - REFRESH_WINDOW_MS`. That
property is **bounded, not universal**, and the boundary is pinned by its own test:
any floor makes the strict inequality false somewhere, and that somewhere is exactly
`MIN_RENEWAL_INTERVAL_MS + REFRESH_WINDOW_MS` of remaining life, where the wake
coincides with the first refusing moment.
`test_at_the_derived_headroom_the_floor_governs_rather_than_the_lead` states that
boundary rather than leaving it implicit; below it the credential is already being
retried every 60 seconds, which is the regime the refusal exists for.

**Lifecycle.** `build_server` detects the host, constructs the broker and calls
`prime()` **synchronously before the socket serves**, so no request observes an
unknown state and the first request cannot trigger a renewal. `prime()` is
deliberately the same cycle as `renew_once()` — a priming path that differed would
be a second code path exercised once per process. `serve_command` then calls
`broker.start()`, which runs `while not sleeper(delay): renew_once()` on a
`daemon=True` thread, and `broker.stop()` from its `finally`. `stop()` sets the
event that *is* the default sleeper, so a thread in a twenty-minute wait returns
immediately, then joins for `RENEWAL_JOIN_SECONDS` = 1.0 and no longer: a thread
mid-`claude -p ok` is abandoned to die with the process. Shutdown is never blocked,
for the same recorded reason `block_on_close` is off. `stop()` is safe on a broker
that was never started and safe to call twice.

The credential and its record are committed together under a `threading.Lock` held
for the pointer swap only, **never across the refresh subprocess** — a request
queueing behind a sixty-second `claude -p ok` is precisely the cost this ticket
deleted. `snapshot()` returns both under one acquisition, because a reader taking
them separately could pair a fresh credential with the previous cycle's verdict.

**Three states, three answers.** A cycle records `VALID` (a usable credential is
held), `ABSENT` (the store holds nothing) or `FAILED` (a credential is held and
renewal did not take). An absent store spawns normally with no
`CLAUDE_CODE_OAUTH_TOKEN` and is **never** refused; a present credential outside the
window spawns with the broker's value; a present credential inside the window is
refused. A `FAILED` record is logged **every** cycle rather than only on transition —
it is the operator's one notice and the refusals it explains keep happening — while
`VALID`/`ABSENT` log only on change, so a healthy broker does not write a line every
twenty minutes. An exception escaping a cycle is caught by the loop, logged, and
recorded as `FAILED`: it surfaces twice, as a line and as the next request's
refusal, and nothing is swallowed. The broker and the request audit trail share one
`log` sink, so an operator sees renewal failures in the same stream as the refusals
they explain.

**The failure predicate is the observable, never a subprocess status.**
`HostPlatform.refresh_agent_credential` swallows everything and returns `None` — it
can exit 0 and write nothing at all. So a cycle judges itself by **re-reading the
store**, and the request-time predicate is re-evaluated against *current* time
rather than trusting the last cycle's verdict:

> Renewal failed ⇔ a credential is present **and** it satisfies `is_stale(now_ms)`
> at the moment the request is evaluated.

Re-evaluating is what stops a renewal thread that died, or a machine suspended for
two hours, from keeping a `VALID` record serving an expired token. This is #302's
rule: the acceptance criterion sits on the observable, not on a status that can fail
silently open.

**Tracker credentials stay per request.** `.env` is read from the *requested* repo,
so a brokered tracker credential needs a cache keyed by repo path — per-repo state
whose values are secrets, held across requests, for a credential with no expiry to
schedule against. Worse on both the ADR 0012 axis and the security axis, for no
measured gain. Rejected.

**`build_server` returns `tuple[VerbServer, CredentialBroker | None]`.** The `None`
is not defensive typing: on `UnsupportedHost` at detection there is genuinely no
broker, and the constructor falls back to `RequestRefreshingSource` so the socket
still binds and each request refuses at the existing per-request site with the
existing message. Host detection failing is a degradation to yesterday's behaviour,
not a new way for `serve` to die.

### The maintenance scheduler

ADR 0012 names three host roles. #307 shipped the spawner, #309 the broker, and
#310 the scheduler: `harness serve` runs a daemon thread that sweeps every
managed repo under its allowed roots on a timer and records each cycle, so the
recurring reclamation a one-shot CLI has nowhere to put stops depending on
somebody remembering. Three new modules, split where `broker.py` already splits
— the pure schedule apart from the thread that obeys it:

| Module | Role |
|---|---|
| [`harness/maintenance/schedule.py`](../../harness/maintenance/schedule.py) | Pure: `SweepConfig`, `next_delay_ms`, `sweep_lag_ms`, `sweep_overdue`. Integers in, one out; no clock, no I/O. |
| [`harness/maintenance/ledger.py`](../../harness/maintenance/ledger.py) | The `maintenance_sweeps` sibling table, its Pydantic models, and `check_sweeps` — the predicate `harness doctor` reads. |
| [`harness/maintenance/sweep.py`](../../harness/maintenance/sweep.py) | `sweepable_repos`, `sweep_steps`, and `MaintenanceScheduler` — the thread. |

They live under `harness/maintenance/`, not `harness/hostenv/`: `ledger.py`
needs `aiosqlite` and `pydantic`, and the stdlib-only guard over `hostenv` would
rightly refuse them there.

**One step, and the narrowing is deliberate.** The timer runs `reclaim --stale`
and nothing else. The ticket's disk evidence — 34 orphaned worktree directories,
427 MB — is reclaimed only by `worktrees cleanup --age`, and `--age` removes a
directory by mtime *regardless of uncommitted work, by recorded design*
([`harness/cli/worktrees.py`](../../harness/cli/worktrees.py): vetoing there
would re-open the cruft leak CAL-767 closed). Putting it on a timer therefore
contradicts #310's own criterion that no timer-driven sweep may remove a
worktree holding uncommitted work, and changing what `--age` does was out of
scope. So the scheduler ships with one step and the disk-reclamation half is
filed separately, where an operator can decide whether an abandoned directory's
uncommitted changes may be destroyed. Adding a second step later is one entry in
`sweep_steps`.

`reclaim --stale` is the profile a timer may drive: three independent clocks
must *all* be stale before it reclaims, its false positive is reversible by
`reclaim --undo`, and it **preserves** the worktree and the branch. What the
timer runs lives in one function, `sweep_steps`, which both the executing path
and the guards read — a guard that re-spelled the argv would be the change
agreeing with itself — and the floor beside it (the table is non-empty and names
the verb it runs) is what stops an empty table satisfying the property for every
possible implementation.

**The staleness threshold is delegated, not forwarded.** The sweep emits no
`--older-than`, so `reclaim`'s existing resolution of
`loop.wall_clock_budget_minutes` stays the one source (#260). An implementation
that read the value and passed it along would be the second copy the criterion
forbids, which is what the guard falsifies — measured against a repo configured
with an unusual budget, so the absence is structural rather than an accident of
`110` not appearing in the argv.

**It spawns; it does not call.** Each step is a one-shot container through
`VerbServer.spawn` — the second half of ADR 0012's decision sentence, *"Every
verb remains a one-shot container"*, and not decoration: `reclaim` makes tracker
network calls and mutates the ledger, and in-process a bug in it could not be
bounded by a container exit. Going through `VerbServer.spawn` rather than
building a second `docker run` is the rule the client fallback already follows,
so the sweep is a third caller of one construction rather than a third security
posture; the argv passes through the same `spawn.rewrite_repo_argument` the
socket handler calls. The cost is stated rather than hidden: with the docker
daemon down a step exits non-zero and the cycle records `failed`.

**Which repos.** `allowed_roots()` is the one repo source — the allowlist is
where a repo becomes reachable at all, so the timer can never touch a path a
request cannot. A root is swept if it is itself a managed repo, otherwise its
immediate children are; one level deep, never a walk, because a recursive
descent reaches `.worktrees/` and every vendored submodule. Two conditions make
a directory managed, each closing a distinct hazard: `.git` must be a
**directory** (a `.git` *file* is a linked worktree, and sweeping a run's
worktree as if it were a repo is the #214 defect on a timer —
`workspace.is_git_top_level` accepts one on purpose and is deliberately not
reused), and `.harness/` must already exist (`store.connect` creates its parent,
so sweeping every checkout under a workspace root would *create* a ledger in
repos the operator never asked the harness to manage; having a ledger is what
makes a repo harness-managed). Overlapping roots are deduplicated, so a repo
under two of them is swept and recorded once per cycle.

**The repo lock is taken non-blocking, for the whole cycle.** One thread serves
every repo, so blocking on a twelve-minute `review` in repo A would make repo
B's sweep that much later, and per-repo isolation is what the lock exists to
preserve. Contention writes a `skipped` / `lock_contended` row and the next wake
retries — the lateness is a record rather than a silence, and real work always
wins. This required `_repo_locks` to hold `threading.RLock`: the sweep holds the
repo lock and then calls `spawn`, which takes the same lock across its
subprocess, and with a plain `Lock` that is a thread deadlocking against itself,
wedging with no error anywhere. Reentrancy is **per thread**, so the
cross-thread serialization recorded under [Concurrency](#concurrency) is
unchanged: the two overlap tests are its floor, and
`test_a_repo_lock_held_by_one_thread_is_refused_to_another` pins that the
widening did not become a global "always acquire". A third test observes the
*release* from another thread, and that placement is load-bearing — a reentrant
lock re-acquires on its own thread whether or not it was ever released, so the
same assertion made on the acquiring thread would be vacuous.

**The record is the schedule's only memory.** Every cycle writes one row into a
`maintenance_sweeps` sibling table in that repo's own `.harness/harness.db`,
**including a no-op** — which is the point: it is what makes "the sweep found
nothing" distinguishable from "the sweep stopped running". `runs` and `events`
are untouched, and that is measured rather than asserted (see the
[run ledger](run-ledger.md)). The one deviation from the broker is that there is
**no synchronous prime**: priming would put a `docker run` per repo in front of
the socket bind, and no request depends on a sweep having happened. The first
wake is derived from the ledger instead — a repo with a recorded sweep is due
one interval after it, a repo never swept is due now, floored at one minute — so
a fresh host sweeps shortly after start, a restarted host does not re-sweep a
repo swept five minutes ago, and a crash-restart loop is bounded to one sweep
per repo per minute.

**Absence is observable, and it is a measured quantity.** `harness doctor` gains
a `sweeps` check reporting the lag against the configured interval: `PASS` under
one interval, `WARN` past it, and a third distinct message when nothing is
recorded at all, naming the remedy (`harness serve` is probably not running).
The comparison is strict, so a sweep that fired exactly one interval ago is due
rather than late — a non-strict bound would make every healthy host warn once
per interval and train an operator to ignore the check. `WARN`, never `FAIL`:
`doctor` exits 1 on any FAIL and a repo whose host has never run `serve` is not
broken, the treatment `check_db` already gives an absent ledger. A repo
configured with `maintenance_interval_minutes: 0` reports `PASS` with
"disabled", because making the escape hatch cost a permanent warning is the same
as not having one. What the check reads is the newest row's *timestamp*: a host
whose cycles are all failing is surfaced on the log line and in the row's
`outcome`, not yet by this check.

**The cadence is one `loop:` key.** `maintenance_interval_minutes` (default
`60`) rides in `CONTEXT.md`'s `loop:` block on `review_model`'s precedent — it
bounds no run, but it is configured in the same block and read on the same path,
so the scheduler resolves one object rather than two. `60` is derived rather
than guessed: `DEFAULT_WALL_CLOCK_BUDGET_MINUTES`' own comment reasons about an
hourly tick, and this makes the in-process sweep the equivalent of the hourly
Build-routine pre-flight `reclaim --stale` was written for. `0` disables sweeps
for that repo, unclamped, on `untracked_file_limit`'s convention: a repo that
runs `serve` for the spawner and the broker but drives reclamation from its own
scheduler otherwise has no escape hatch short of not running the host process.
The key is read **per cycle**, from each repo's own `CONTEXT.md`, because
`serve` outlives many edits of it.

**No new principal, and no new argv surface.** The sweep runs a verb the
operator can already run, with credentials resolved per call by the same
`resolve_container_env` every request uses, against repos already in the
allowlist, at a cadence the operator configures. Nothing caller-derived reaches
it: `sweep_steps` takes a resolved path and returns a wholly host-constructed
argv, which is why the record stores that argv in full where the socket audit
line deliberately records the verb and nothing else — there is no untrusted
token, ticket title or `--reason` body that could land in it.

**Where the host is containerized (#312), the record write is the open half.**
The spawn half already goes through `spawn.build_docker_argv` and survives
unchanged; writing a row into `<repo>/.harness/harness.db` from inside a
container is the same mount question #312 owns. Noted, not built for.

## The two properties that define it

**It spawns; it does not proxy.** The caller names a verb and a repo. The host
chooses the image, the mount, the privilege and the env. ADR 0012 rejected
mounting the docker socket into callers precisely to keep this property — the
docker socket is root-equivalent on the host, so anything reaching it can
`docker run -v /:/host`.

The property is enforced **positionally**, not by sanitizing: every
caller-derived token is appended *after* the image, where docker has stopped
parsing options and is assembling the container's command line. `harness start
--privileged` is therefore an argument to `start`, which rejects it as an unknown
flag. A blocklist of dangerous option names would be defeated by the next docker
release; a positional rule enumerates nothing, so there is nothing for a new
option to slip past. The wire schema is the same argument one layer up: exactly
three keys (`protocol`, `repo`, `argv`) are accepted and anything else is
refused, which is what makes `image` / `volumes` / `privileged` / `env`
*inexpressible* rather than merely ignored.

The one caller-derived value that must sit in the docker-option region is the
resolved repo path, since it is the mount source. It is therefore the one value
validated by content: a `:` in it would inject `-v` field structure and is
refused.

**It holds no run state.** ADR 0012: *"if the host process ever holds run state,
it has exceeded the carve-out."* The close gate rests on the ledger being the
only memory of a run, so a host caching run status would break that property
while appearing to work. The server's entire state after a request is two
attributes, and the scheduler beside it adds a third entry to the same account:

- `_repo_locks` — a mutex per resolved repo path, which names no run, ticket, verb
  or argv, and whose empty state after a restart is a correct one.
- `credentials` — the `AgentCredentialSource` (#309). On the brokered path it
  references a `CredentialBroker` holding one `AgentCredential` and one
  `RenewalRecord`. It names no run, ticket, verb, argv or repo; a fresh broker after
  a restart is a correct one; and — decisively — **nothing on the request path
  writes it**. It is exactly the "credential broker" ADR 0012 names in the same
  sentence as "spawner" and "scheduler".
  `test_serve_credential_brokering.py::test_a_request_writes_nothing_into_the_broker`
  holds it: it snapshots the record and `repr(vars(server))`, drives requests
  carrying sentinel tickets, and asserts neither the record moved nor a sentinel was
  retained.
- `MaintenanceScheduler` (#310) — the roots it was built with, the log sink, a
  stop event, its sleeper seam and its thread. That is process lifecycle and host
  configuration; none of it names a run, ticket, verb, argv or repo. Nothing per
  repo and nothing per cycle survives a cycle: the schedule is re-derived from
  each repo's own recorded sweeps on **every wake** rather than cached, because a
  `{repo → last swept}` dict would be the first thing here that describes work
  rather than configuration, and it buys nothing a four-row SQLite read does not
  already give. It could not describe a run even in principle — it never reads
  `runs`, never reads `events`, never resolves a ticket and never holds a
  `run_id`; which run is stale, which is attended and which is closable are
  decided *inside* the spawned container by `reclaim`, against the ledger,
  exactly as when a human runs the verb. **The host decides *when*, never
  *what*.** A fresh scheduler after a restart is a correct one.
  `test_maintenance_sweep.py::test_the_scheduler_holds_no_state_across_a_cycle`
  holds it, with the planted-attribute floor beside it.

Two consequences follow that read as implementation detail and are not:

- The response frame carries **no verb output**. Output crosses on the caller's
  own file descriptors (`SCM_RIGHTS`), so a twelve-minute `review` streams live
  instead of arriving at the end — and the server never accumulates a run's
  output in memory, which would be run-describing state.
- `block_on_close` is explicitly off. Left at its `socketserver` default it
  lazily installs a `_threads` list on the instance at the first request — state
  created *by a request* — and makes shutdown wait for in-flight handlers.
  Waiting is also wrong: a verb's container is owned by the docker daemon and
  runs to completion whether or not this process is alive.

## Decisions settled here

**Operation surface: derived, not an allowlist.** `serve` resolves the leading
tokens of argv against the leaf set of the registered Typer app, longest-prefix
first, so `promote start` and `worktrees cleanup` resolve as leaves. The retired
launcher's hardcoded `OPERATIONS` frozenset went stale as soon as a verb was
added and was six verbs behind by the time it was deleted. Derivation makes that
drift structurally impossible, so #311's guard did land as a floor rather than
the mechanism: what it holds is not the derivation restated but the *pairing* of
enumeration with resolution, plus the `SOCKET_EXCLUSIONS` declaration this
surface now subtracts (empty today). Both are recorded in
[cli-surface.md](cli-surface.md), *The socket surface is derived from the
registered set* — the rule belongs to the command surface, this decision to the
host. The derivation moved to its own module,
[`harness/cli/serve_surface.py`](../../harness/cli/serve_surface.py), in #310 —
one idea with one recorded decision, on the seam convention the `review_*` /
`close_*` / `reclaim_*` modules follow. It is a pure move: `serve.py` re-exports
both names, so the decision and its tests are unchanged. `operation_surface`
still imports `harness.cli` *inside the function body*, because the host runs
this code before any container exists.

**Supervision: none in this ticket; the fallback is the visibility mechanism.**
`harness serve` is a foreground process the operator starts. *Client-side
autostart* was rejected: a verb call would spawn a long-lived credential broker
as a side effect, inheriting that call's environment, cwd and tty into a process
outliving it; two concurrent clients would race to start two servers; and it
makes an outage invisible, which is exactly what ADR 0012 warns against. *launchd
socket activation* was rejected as macOS-only with no WSL equivalent. A shipped
launchd/systemd unit belongs to the deployment ticket (#312). "Not running"
surfaces instead as one stderr line from the client, and the verb still runs.

**The brokered path refuses; the request-resolving path structurally cannot (#309).**
CAL-941 recorded that a refresh which fails, hangs, or finds no CLI leaves the
stale-but-present token in play, because refusing costs a call that would have
worked while proceeding costs a 401 the container reports. That asymmetry **runs the
other way once renewal is scheduled**: the broker already tried, with the whole
inter-request interval to succeed, so a credential still inside the window is
evidence that renewal is failing rather than evidence of bad luck. The token such a
request would carry has under five minutes left, a `review` legitimately runs twelve,
and the 401 then arrives mid-run having burned the wall-clock budget and reading as a
review failure. Refusing at the boundary costs one verb the operator retries after
`claude` + `/login`; proceeding costs a run.

The rule is scoped **by source**, so CAL-941 is untouched where it was decided:
`RequestRefreshingSource` has no scheduler and no second chance, and it keeps the old
behaviour by having no code path that could refuse. *Rejected: invert CAL-941
everywhere.* It would break exactly the deployment CAL-941 protects — a token five
minutes from expiry, offline, with a verb that would have completed. *Rejected:
refuse on `refresh_agent_credential`'s outcome.* It has none, and a subprocess that
exits 0 without rewriting the store would still pass.

**The refusal is keyed on credential state, never on which verb was asked.** A dead
refresh token therefore refuses every verb over the socket, including ones that never
needed the Claude credential. This is an accepted cost, taken deliberately over the
alternative: *rejected — refuse only for verbs that need the agent credential*, which
needs a hand-maintained "verbs needing Claude" mapping, the exact defect the retired
`OPERATIONS` frozenset embodied and which *operation surface: derived, not an
allowlist* above records as settled. There is no derivable source for "this verb calls
the engine". The residual is bounded rather than open: the refusal names its own
remedy, the broker retries every 60 seconds and recovers without a restart, and the
client's direct-spawn fallback is unaffected because it uses the other source.

**An absent credential is never a refusal, and an exported token short-circuits
before the refusal is asked.** A host with no Claude at all must still run `status`
and `worktrees cleanup`, so `ABSENT` spawns normally with no token — there is nothing
to renew, so nothing failed to renew. And a caller who already exported
`CLAUDE_CODE_OAUTH_TOKEN` is never asked the credential question at all. That
short-circuit is one predicate, `container_env.agent_credential_is_needed`, consulted
by `container_env.credential_refusal`, which is itself the **single** function called
by both the socket's pre-flight and `resolve_container_env`. One function, two
callers: a second copy of that ordering is a second thing to get wrong, and getting
the order wrong means an exported token stops short-circuiting.

**The mount stays `/workspace`, not ADR 0012's path-equivalent mount.**
`runs.worktree_path` is recorded container-absolute as
`/workspace/.worktrees/harness/<run_id>`, so changing the mount point rewrites
the meaning of every already-recorded path and strands every in-flight run across
the cutover. **#308 settled this without a migration:** it delivers the property
ADR 0012 wanted — a file reference means the same thing on both sides — as
*mapping* equivalence, one `WorkspaceMount` both spawn paths compute with and
that refuses a mount it cannot round-trip. The literal `-v <repo>:<repo>` form
remains available as a later variant if a migration ticket wants it.

## The fallback, and its one asymmetry

The client falls back to spawning the container itself when the socket is
unreachable — absent, stale, a plain file, or permission denied all collapse to
one answer, because the action is identical in all four cases. ADR 0012 requires
this "built in from the start rather than added after the first outage", and both
paths call the same `spawn.build_docker_argv`: two constructions would be two
security postures, and the fallback runs on exactly the days the socket is
broken.

**Falling back is a connect-time decision only.** Once the request bytes are on
the wire the verb may already be running, so a lost *response* exits 1 and names
the ledger as the record rather than re-spawning. Running a `close` twice —
merging and pushing twice — is the worst failure this design can produce, and is
strictly worse than reporting an uncertain outcome.

## Concurrency

Requests naming the same resolved repo are **serialized**; requests naming
different repos run concurrently. ADR 0012 requires serialization until
parallel-writer behaviour against the ledger over a bind mount is measured, and
that measurement gates enabling concurrency rather than following it. The lock is
per repo rather than global because a `status` on one repo must not queue behind
a twelve-minute `review` on another — and the test asserting different repos
*do* overlap is the non-vacuity floor for the serialization test, which a server
that simply never ran anything in parallel would otherwise satisfy.

### The measurement, and its result

ADR 0012 required parallel-writer behaviour against a bind-mounted ledger to be
measured before concurrency is enabled. It was measured for #307 and the result
is **negative**, which is why serialization ships rather than merely being
proposed.

Six `harness start` containers were run concurrently against one bind-mounted
repo on macOS, bypassing the per-repo lock (going through it would report a clean
result on every possible filesystem). Across three runs, 0–3 of 6 writers
succeeded, and the failures were not lock contention — no writer ever reported
`database is locked`. They were worse:

- `table runs has no column named resumed_from` — two containers raced to
  initialize the schema and one observed a **half-migrated** database;
- `unable to open database file`;
- exit 135 (SIGBUS), the signature of SQLite's mmap over a bind mount.

So the failure mode is concurrent *schema initialization and mmap*, not row-level
write contention, and it is silent enough that a writer can exit 0 with a run id
whose row is not on the ledger. Enabling concurrency is therefore blocked on more
than a lock-timeout setting. The measurement lives in the ticket rather than in
the suite: it is a one-time result, and as a permanent test it would be slow and
inherently flaky.

### The second measurement: where a failing verb's payload went (#370)

A failing verb captured over the socket carried its `{"error": ...}` object
locally and, on the GitHub runner, reported `['start', '1', '--json'] exited 1:
b''`. Because the socket's whole design is that the container writes to the
*caller's own* file descriptor, "the transport drops the payload on the runner"
was a live hypothesis against this record, and #369's diagnosis had already been
misread twice for want of an answer. #370 settled it by measurement rather than
inference.

**The capture, not the transport, was the blind spot.** `_capture` in
`tests/integration/test_serve_socket.py` opened a real fd for stdout and
`/dev/null` for stderr. Every failure route out of a verb *other* than
`run_verb`'s `--json` writer — a non-`VerbError` traceback, a failure under
`docker/entrypoint.sh`'s `set -euo pipefail`, `uv run`'s own diagnostics — writes
to stderr and exits non-zero, and each produces exactly (exit 1, empty stdout).
The observation `b''` therefore could not distinguish a payload that was written
and lost from one that was never written. Both streams now get a real fd, and
`tests/_capture.py`'s `Capture.diagnosis` renders both with their exact bytes
including the empty ones, so an unread stream can no longer read as an empty one.

**The result, read off the runner** ([CI
31242012837](https://github.com/sluengen/harness/actions/runs/31242012837)): the
container's stderr carried a full traceback ending in `PermissionError: [Errno
13] Permission denied: '/workspace/.harness'`, raised by `db_path.parent.mkdir`
inside `harness/state/store.py`'s `init_db`. That is not a `VerbError`, so
`run_verb`'s `--json` branch never ran and stdout was **legitimately empty**. The
transport lost nothing: every byte the verb produced was delivered to the
descriptor the caller passed, and thrown away by a capture that had opened
`/dev/null` for it. The socket is exonerated, and #307's byte-identity property
above is unaffected.

Two things follow, and both shipped or were filed rather than left as inference:

- **The writing end was fixed.** An unexpected exception under `--json` now emits
  the uniform payload on stdout as well as its traceback on stderr — the [verb
  model](verb-model.md) records that contract. The same CI job now reports
  `stdout: b'{"error": "PermissionError: ...", "reason": "unexpected_error"}'`
  ([CI 31242459008](https://github.com/sluengen/harness/actions/runs/31242459008)).
- **The cause the measurement exposed was a different defect**, filed as #380 and
  fixed there rather than here: the image ran as uid 1000 while the runner's
  bind-mounted fixture repo is owned by another uid, so the container could not
  create `.harness/` inside it. `docker/Dockerfile`'s comment stated the
  assumption that fails — Docker Desktop maps bind-mount ownership to the
  run-time uid, a native Linux daemon does not — which is why it reproduced only
  in CI.

  **#380 resolved it** by giving the provider seam a third spawn concern: the host
  pins `--user <uid>:<gid>` to the invoking user wherever the daemon shares its
  kernel namespace, and `MacOSHost` alone declines, because there the daemon
  already remaps ownership. `HOME` is pinned by value alongside it and the image's
  `/home/harness` is `1777`, both measured necessary and neither sufficient alone.
  `test_a_mutating_verbs_contract_is_unaltered_by_the_socket` passes on the runner
  as of [CI 31245840169](https://github.com/sluengen/harness/actions/runs/31245840169).
  The mechanism belongs to the provider seam, so [host-platform](host-platform.md)
  owns the record; what matters here is that **the non-root property this record's
  security boundary rests on is preserved and narrowed, not traded away**. The
  pinned uid comes from the host, never from the request, and `uid == 0` is refused
  at construction — over the socket as `REPO_NOT_ALLOWED`, through the fallback as
  exit 2, before docker is touched — so a `serve` process started under `sudo`
  refuses rather than handing untrusted content a root container. On a native
  daemon the container now runs with *less* authority than before, as a user who
  owns only the repo they were handed.

  Fixing the docker stage also un-shadowed a latent failure in the stage after it.
  `scripts/verify.sh` runs `-m docker` first under `set -euo pipefail`, so from
  #307 until #380 the parallel stage never executed on Linux at all, and
  `test_wrapper_is_shellcheck_clean` — which skips on the macOS host, where
  shellcheck is absent — had never run anywhere. It failed on SC2155 at
  `docker/harness-wrapper.sh:304`, a line #307 wrote and #380 does not touch.
  **#383 fixed it** by splitting that `export` from its assignment, which is a
  behaviour change rather than lint hygiene: the old line masked a failing
  `_wrapper_status` under the wrapper's own `set -e`. The wrapper contract in
  [host-platform](host-platform.md) owns that record. Noted here because "the
  docker stage is green and the job is still red" was otherwise a confusing state
  to inherit, and this is where that state was first written down.

**`Capture.contract` is deliberately narrow.** The two comparisons that assert
#307's AC-1 (`over_socket` vs `directly`, and before vs after a host restart) are
`(exit code, stdout)` and stay so. Reading stderr for diagnosis is not a licence
to widen a byte-identity claim onto a stream carrying per-environment noise — a
credential-resolution note, a docker warning — which would make a passing test
depend on the host it ran on. The claim's strength is unchanged in both
directions: neither comparison was weakened, and neither was extended.

## Security boundary

The socket's only authentication is filesystem permissions — parent dir `0700`,
socket `0600`. Anyone who can `connect()` can run any registered verb against any
allowlisted repo with the host's credentials injected, which is operator-
equivalent authority. It is deliberately *not* a privilege boundary between
processes of the same uid; it is one between the docker socket and everything
else.

Validation order, every step before `docker` is executed: single-message size cap
→ strict three-key schema → derived-verb lookup → allowlist and colon rejection on
`repo` → mount and container-user equivalence → **credential availability (#309)** →
`--repo` agreement. Secrets are resolved by the host and injected **by name**
(`-e NAME`), so no value ever lands in an argv or in `ps` output.

The credential step sits before `--repo` agreement so no argv work happens for a
request that cannot run, and — like every step above it — it is observable as *no
container was spawned*, which is what
`test_a_failed_renewal_refuses_on_the_wire_before_docker` asserts rather than
asserting the exit status. A caller reaching `VerbServer.spawn` directly, bypassing
the handler, gets the same answer: `resolve_container_env` raises
`CredentialRenewalFailed`, which `spawn` carries in the same backstop `except` chain
as the two provider refusals (log, `return 2`).

**A new wire reason, not a reused one.** `Reason.CREDENTIAL_UNAVAILABLE =
"credential_unavailable"` maps to exit **2**, the invocation-refusal code every
refusal but `spawn_failed` uses. Reusing `repo_not_allowed` was rejected on the
`UnsafeContainerUser` precedent's own test — does the existing string still *describe*
the refusal? It stretches over "this host/repo combination cannot be served" and not
over a credential outage, and it would make the audit line — the socket's only record
of who asked for what — attribute a credential event to the repo allowlist.
`PROTOCOL_VERSION` is not bumped: a new refusal string is additive, not a frame
change.

**The skew that adding a reason creates was closed in the same change.** Before this,
a client decoding an unknown reason hit `Reason(payload["reason"])` → `ValueError` →
`BadRequest`, whose handler says *"the verb may have run. The ledger is the record."*
— the worst available message for a refusal where nothing was spawned. `decode_response`
now treats an unrecognised reason on an `ok=False` frame as a well-formed refusal from
a newer server: `Response(ok=False, reason=None, error=f"{raw}: {message}")`, which
`exit_code_for` already maps to 1, preserving the server's own message and claiming
nothing ran. That frame moved out of the malformed-frame table and into its own test;
a paired discriminator holds that known reasons still decode to their enum member, so
a `decode_response` that gave up on every reason would fail.

**What the broker changes about the security posture is memory residency, and only
that.** The agent token used to exist in this process for the duration of one `spawn`
call; it now lives in the broker continuously. That creates no new principal: the
socket already grants operator-equivalent authority, so an attacker who can
`connect()` can already obtain the credential's full effect without reading it, and an
attacker who can read this process's memory holds the same uid and can read the
Keychain item or credential file directly. Exactly one window widens — a core dump or
process-memory scrape now yields the token at any moment rather than only during a
spawn — and both stronger capabilities were already sufficient. Three properties keep
the widening from becoming a leak, each held by a test rather than by convention:

- **No value-carrying `__repr__` on the path.** `CredentialBroker`, `BrokeredSource`,
  `AgentCredentialLease` and `RenewalRecord` render outcome and expiry only, and
  `AgentCredential.token` is now `field(repr=False)`. The repr was **narrowed, not
  emptied**: `expires_at_ms` still renders, is not a secret (it is forwarded as
  `CLAUDE_CODE_OAUTH_EXPIRES_AT`), and is the field an operator debugging a refusal
  needs — asserted as a floor alongside each ban.
- **No value in any log line.** The renewal line names the outcome, `expires_at_ms`
  and a `detail` describing what was observed; the audit line records
  `refused=credential_unavailable`, the reason value and never the message.
- **No value in argv.** Unchanged, and now guarded rather than assumed:
  `ContainerEnv.values` gains no key, and
  `test_every_credential_name_the_resolver_emits_is_one_the_argv_forwards` derives
  the emitted set from a real `resolve_container_env` call under **both** sources and
  asserts it is a subset of `client.FORWARDED_ENV_NAMES`. That closes the one way this
  change could have blinded the existing review-container push-credential ban, which
  scans that tuple and would go silent — not red — if the resolver started emitting
  under a name the tuple does not carry.

**One line per request is the audit trail**, written to stderr by default and
redirectable by the host: timestamp, resolved verb, resolved repo, and the
outcome (`exit=<n>` or `refused=<reason>`). A refusal is the security-interesting
event, so it is logged rather than being the one thing that goes unrecorded. The
line carries the resolved **verb** and nothing else from argv — a ticket title, a
`--reason` body, or a token-shaped argument must not be able to land in a log an
operator may paste elsewhere. This is the only record of who asked for what, so
its absence would leave operator-equivalent authority unattributable after the
fact.

The allowlist applies at the socket, not to the client's local fallback: that
path runs with the invoking operator's own authority over their own argv, exactly
as the wrapper does today, so there is no boundary to check. The container's own
`HARNESS_WORKSPACE_ROOTS=/workspace` check still applies inside, on both paths.

## What is not here

The reachability guard (#311), deployment via image and entrypoint (#312), and WSL
validation on a real Windows host (#313). This record covers the process, the
socket, the spawner, the fallback, the credential broker, and the maintenance
scheduler. Reclaiming the accumulated worktree *directories* is not here either:
#310 shipped the scheduler with `reclaim --stale` as its only step, and putting
`worktrees cleanup --age` on the timer is filed separately because it carries an
operator decision (see [the maintenance scheduler](#the-maintenance-scheduler)).
Platform-specific spawn
concerns **shipped in #308** and are recorded in
[host-platform](host-platform.md), which owns the provider seam they extend.

**The mount half of #351 is not here.** The wrapper is rewired (above), and the
*argv* half of `--repo` translation ships in `spawn.rewrite_repo_argument`: an
explicit `--repo` naming the mounted repo is rewritten to `/workspace`, and one
naming another repo is refused `repo_mismatch`. But the mount still follows
`$(pwd)` — the client is invoked as `… client "$(pwd)" -- "$@"` — so naming a
different repo is refused rather than mounted, and `.env` is still read from the
invoking directory. Making the mount follow the flag is #351, which the rewire
unblocks in two ways: construction is now Python, and the wrapper's line ratchet
(the measured blocker, 158 against a 165 bound) is no longer in the way at 116
against 120.
