---
feature: runtime-host
status: implemented
last_updated: 2026-08-08
tickets: ["#307", "#308", "#370", "#380"]
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
| [`harness/cli/serve.py`](../../harness/cli/serve.py) | CLI | `harness serve`: derive the operation surface, hold the per-repo lock, bind the socket. |

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
of credentials too. Brokering with background renewal remains #309.

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
while appearing to work. The server's entire mutable state after a request is
`_repo_locks` — a mutex per resolved repo path, which names no run, ticket, verb
or argv, and whose empty state after a restart is a correct one.

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
drift structurally impossible, which leaves #311's guard as a floor rather than
the mechanism.

**Supervision: none in this ticket; the fallback is the visibility mechanism.**
`harness serve` is a foreground process the operator starts. *Client-side
autostart* was rejected: a verb call would spawn a long-lived credential broker
as a side effect, inheriting that call's environment, cwd and tty into a process
outliving it; two concurrent clients would race to start two servers; and it
makes an outage invisible, which is exactly what ADR 0012 warns against. *launchd
socket activation* was rejected as macOS-only with no WSL equivalent. A shipped
launchd/systemd unit belongs to the deployment ticket (#312). "Not running"
surfaces instead as one stderr line from the client, and the verb still runs.

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
  shellcheck is absent — had never run anywhere. It fails on SC2155 at
  `docker/harness-wrapper.sh:304`, a line #307 wrote and #380 does not touch.
  Filed as its own follow-up; noted here because "the docker stage is green and
  the job is still red" is otherwise a confusing state to inherit.

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
`repo` → `--repo` agreement. Secrets are resolved by the host and injected **by
name** (`-e NAME`), so no value ever lands in an argv or in `ps` output.

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

Credential brokering with background renewal (#309), periodic maintenance sweeps
(#310), the reachability guard (#311), deployment via image and entrypoint
(#312), and WSL validation on a real Windows host (#313). This record covers the
process, the socket, the spawner, and the fallback. Platform-specific spawn
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
