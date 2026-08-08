---
feature: host-platform
status: partial
last_updated: 2026-08-08
tickets: ["#305", "#308", "#380", "#383"]
---

# Host platform abstraction

> How the harness resolves credentials and commit identity on the **host**, before any
> container exists, in a way that is not specific to macOS.

## Behaviour

`docker/harness-wrapper.sh` needs four things from the host before it can `docker run`:
the Claude OAuth credential, the tracker credential, a commit identity, and a way to
bound a subprocess. Until #305 all four were macOS-shaped bash inside the wrapper —
unreachable from the native `uv tool install` entry point, and unable to express
Windows-via-WSL, which ADR 0012 makes a supported platform.

They now live in `harness/hostenv/`, a **stdlib-only** package. The wrapper calls it
once and imports the result.

### The layering

`host.py` answers *what does this platform do*; `container_env.py` answers *what does
this request need*, driving the providers once per verb invocation. #308 introduced that
boundary — the resolver moved up a layer when the two spawn concerns moved down into the
providers. The import edge runs one way, and both callers of the resolver (the `serve`
socket path and the client's fallback) want the whole layer and none of the provider
internals. `detect_host` is reached *through* the module rather than bound at import, so
it stays the substitutable seam every provider test uses.

### The provider seam

`detect_host(platform, osrelease_path, env)` returns a `HostPlatform`. Every input is
injected, so each branch is exercised on any machine — a macOS dev box can prove the
WSL branch, which detection from ambient state cannot.

| Host | Provider | Credential store |
|---|---|---|
| `darwin` | `MacOSHost` (`name="macos"`) | login Keychain, service `Claude Code-credentials` |
| Linux with a WSL marker | `LinuxHost` (`name="wsl"`) | JSON file |
| Linux otherwise | `LinuxHost` (`name="linux"`) | JSON file |
| anything else | — | raises `UnsupportedHost` |

WSL is distinguished from plain Linux by `/proc/version` content or `WSL_DISTRO_NAME`,
because `sys.platform` reports `linux` for both. Since #308 that distinction is
load-bearing rather than anticipatory: `WslHost` is its own provider, overriding
**only** the spawn concerns below. Everything else — the credential store, tracker
credentials, git identity, bounded execution — stays on `LinuxHost`/the ABC, so this
provider's unverified status cannot contaminate logic that is not platform-dependent.

### The three spawn concerns (#308, #380)

Each was a macOS constant — or a macOS *silence* — inlined in
`spawn.build_docker_argv`. None was wrong on macOS; they are the wrapper's proven
behaviour. Reusing them elsewhere is *silently* wrong, which is the failure class
this seam exists to end, and the container user is the case that proved it: the
constant nobody wrote down was "the container runs as whatever uid the image baked",
and it held for a month on one platform's accident. No new decision was needed for
any of them: [ADR 0012](../decisions/0012-persistent-runtime-host.md) already says the
host constructs the invocation and the caller never specifies the privilege, and this
seam is where "the host" gets to mean something different per platform.

| Provider | `ssh_agent_forwarding()` (live agent) | `workspace_mount(repo)` | `container_user()` |
|---|---|---|---|
| `MacOSHost` | mounts Docker Desktop's bridge, `--group-add 0` | default mapping | `None` — the image's baked uid 1000 |
| `LinuxHost` | mounts the probed socket itself, no group grant | default mapping | `ContainerUser(os.getuid(), os.getgid())` |
| `WslHost` | mounts the probed socket itself, no group grant | refuses a Windows-filesystem path | inherits `LinuxHost`'s (the ABC default) |

**macOS is the exception in both the first column and the last, for opposite
reasons.** For the agent it is the exception because its own answer does not work:
`SSH_AUTH_SOCK` names a path that exists only host-side, so the provider has to reach
for a bridge. For the container user it is the exception because its answer already
works: Docker Desktop remaps bind-mount ownership to whatever uid the container runs
as, so the baked 1000 owns the mount by construction and pinning a uid would change
the operator's daily driver to buy nothing. Everywhere the daemon shares the host's
kernel namespace, a bind mount carries the host's *real* ownership instead, and a
container left on uid 1000 cannot write a repo owned by anyone else.

`ContainerUser` holds two `int`s and renders `uid:gid` — never text, which is what
keeps it safe in the option region without a content check (below). It refuses
`uid == 0` at construction with `UnsafeContainerUser`, so an operator running the
harness under `sudo` gets a refusal rather than a root container: not running
untrusted content as root is the property CAL-1008 bought and
[ADR 0013](../decisions/0013-codex-engines-in-container.md)'s threat model rests on,
and this change *lowers* privilege on native daemons rather than widening it.
`gid == 0` is deliberately allowed — that is the invoking user's own primary group, a
privilege they already hold on the host.

Two things ride with the pinned uid, both measured rather than reasoned about, and
each was measured **insufficient alone**. `HOME` is pinned by value to
`spawn.CONTAINER_HOME` on *every* platform: docker resolves `HOME` from `/etc/passwd`,
and a numeric `--user` with no entry there gets `HOME=/`, where `uv` cannot create its
cache and no verb starts at all. And `docker/Dockerfile` chmods `/home/harness` to
`1777`, because `useradd --create-home` leaves it `drwx------` — not even *traversable*
by another uid, so both `:ro` credential mounts under it are unreadable and `close`'s
push would fail after `start` had succeeded. The mode is sticky rather than plain
`0777`: world-writable is a boundary between principals, and this container has one —
one uid, one verb, `--rm`, nothing running afterwards to plant a file for. Pinning
`HOME` only where a user is pinned would make "the container's home is
`CONTAINER_HOME`" true by a passwd lookup on one platform and by an env var on the
rest, which is how it would drift from the credential mounts that target it.

**macOS is the only platform where the probed socket is not the mounted one.** Its
`SSH_AUTH_SOCK` is a per-session launchd path that exists only host-side, so Docker
Desktop bridges the agent into the VM at a fixed path instead; the host socket is the
liveness *signal*, the bridge is the source. `--group-add 0` rides with it because that
bridged socket is root-owned and group-rw while the image runs as uid 1000 — so the
grant is now *narrower* than before, since a provider mounting a socket the invoking
user owns asks for no group at all.

Keeping `probed` and `source` on one object is what makes the pairing statable and
testable. Under WSL, reusing the macOS constant would probe an agent **inside the
distro** and forward the **Windows** agent — different key sets, so every push fails
`Permission denied (publickey)` against a healthy agent, with nothing in the output
naming the cause.

Moving forwarding behind the seam put a **second** value in docker's option region.
`spawn`'s positional rule keeps caller-derived values after the image, and until now
the resolved repo path was the only exception — the one value validated by content,
because a `:` in it injects `-v` field structure. The agent socket is now the other:
`LinuxHost` and `WslHost` mount `SSH_AUTH_SOCK` verbatim, so it is environment-derived
rather than a fixed per-platform constant. `SshAgentForwarding.__post_init__` refuses a
`:` in either `source` or `target` with `UnsafeAgentSocket`, the sibling of
`UnsafeRepoPath`. It is checked at construction rather than at argv assembly so a
provider cannot build the malformed object and carry it to spawn time, where the symptom
is a docker parse error that names docker instead of the value.

#380 put a **third** value there and deliberately did not add a third content refusal.
`--user uid:gid` is rendered from two integers the host read from `os.getuid()`, so
there is no text for a separator to hide in; it is refused for what it *means* (uid 0)
rather than for what it could inject. The positional rule is unchanged and now has a
collision to survive: a caller writing `harness start --user 0:0` puts two `--user`
tokens in one argv, and only their position separates the privilege the host chose from
the one a ticket asked for. `tests/unit/test_hostenv_spawn.py`'s escape table is
therefore parametrised over **both** constructions — pinned and unpinned — because the
row that mattered (`"--user": 0`) was true only while the host emitted none.

**Path equivalence is asserted, not assumed.** `WorkspaceMount` carries the host↔container
mapping as one object: its `target` is emitted as the `-v` target, as `-w` **and** as
`HARNESS_WORKSPACE_ROOTS`, so those three cannot disagree, and `validate` refuses a source
that is not the resolved path of the repo the caller named (the docker daemon resolves the
source in *its* namespace, so an unresolved `..` can mount a directory nobody asked for).
The mount point deliberately stays `/workspace` — see
[runtime-host](runtime-host.md) for why relocating it would strand every recorded
`runs.worktree_path`.

#### Scenario: a repo owned by a uid other than the image's

- GIVEN a daemon sharing the host's kernel namespace (native Linux, a self-hosted or
  GitHub runner) and a repo owned by any uid but 1000
- WHEN a mutating verb runs
- THEN the argv carries `--user <uid>:<gid>` and `-e HOME=/home/harness`, the container
  creates `.harness/harness.db` and the run's worktree inside the mount **owned by the
  invoking user**, and the verb exits 0 with its JSON contract

Before #380 this was an unhandled `PermissionError: '/workspace/.harness'` out of
`store.init_db` — a traceback that read as a harness crash rather than an environment
mismatch, and the second defect standing behind the same CI assertion #369 had already
been blamed for. It was unobservable on the machine the harness is developed on: Docker
Desktop remaps mount ownership, so `ls -ldn /workspace` under `--user 4242` reports
`4242 4242` there. That is why AC-1 was discharged **on the runner** rather than from a
green local gate.

#### Scenario: the harness is invoked as root

- GIVEN an operator running a verb under `sudo`, or a `harness serve` process running as
  uid 0
- WHEN any verb runs
- THEN `ContainerUser` raises `UnsafeContainerUser` naming the uid it refused — over the
  socket as `REPO_NOT_ALLOWED`, through the client's fallback as exit 2, **before docker
  is touched** — and no container is spawned

Refused rather than forwarded, on all three paths (the socket handler's pre-flight,
`VerbServer.spawn`'s backstop, and the client's direct-spawn fallback), because "the
container does not run as root" is a property the image bought, not a default to
inherit from whoever invoked the harness. `REPO_NOT_ALLOWED` is reused rather than a new
wire reason being grown, following the precedent `UnsupportedHost` already set for a
refusal whose exit code is the same 2.

A repo the *invoking user* cannot write for ordinary filesystem reasons is deliberately
**not** refused pre-spawn. That is a host-permissions failure rather than a
container-construction one, and since #370 it arrives self-diagnosing as
`{"error": …, "reason": "unexpected_error"}` with the traceback on stderr. Only uid 0 is
refused, because that one is a security refusal rather than a permissions guess.

#### Scenario: a repo on the Windows filesystem under WSL

- GIVEN a WSL host and a repo under `/mnt/c/...`
- WHEN any verb runs
- THEN it refuses with `WorkspaceNotEquivalent` naming the path, the filesystem type, and
  `#313`, and suggesting a clone inside the WSL filesystem — over the socket as
  `REPO_NOT_ALLOWED`, through the client's fallback as exit 2, **before docker is touched**

**Refusing is the decided behaviour** (#308 AC-4), not an omission. A drvfs bind mount does
not carry the distro's permission, symlink and case semantics, and the verbs depend on all
three: mode bits on hooks, the `.git` *file* of a linked worktree whose `gitdir:` pointer
must resolve, and case-sensitive comparison in the workspace allowlist. Warning and
proceeding would reproduce exactly the silent breakage this ticket ends; calling it
supported would be a claim nobody has exercised. Moving the repo is a remedy the operator
controls, and #313 is where "supported" gets earned.

Detection reads the fstype of the repo's longest-matching `/proc/mounts` entry — `drvfs`,
`9p` or `cifs` — rather than matching on `/mnt/`, because `wsl.conf` can set a non-default
automount `root`, and an ordinary `/mnt/data` on ext4 must not be condemned. When the table
is unreadable it falls back to the documented `/mnt/<drive letter>/` prefix: with no
evidence, treating such a repo as fine is the one answer that reproduces the silent failure.

There is deliberately **no operator override**. The `HARNESS_CLAUDE_CREDENTIALS_FILE`
precedent does not transfer — that is a *value* an operator can know to be correct, whereas
whether drvfs preserves the semantics the verbs need is not something an env var can assert.

#### Scenario: an unsupported host

- GIVEN `sys.platform` is `win32`
- WHEN a verb runs
- THEN the helper exits 2 with a message naming the platform and the missing provider,
  emitting **no** credential records, and the wrapper exits without running `docker`

This is the case a blank credential used to turn into an in-container 401 much later.

#### Scenario: the file store is not where we guessed

- GIVEN a WSL host whose Claude credential store is not at the default path
- WHEN a verb runs
- THEN the credential is absent, a diagnostic **names the path searched**, and the verb
  still runs — an absent store is not an unsupported host

### Credential resolution

The agent credential is refreshed when it is at or inside a five-minute window
(`is_stale` uses `<=`, mirroring the bash `-le`): `claude -p ok` makes the CLI exchange
its refresh token and rewrite its own store, then the store is re-read. A refresh that
fails, hangs, or finds no CLI leaves the stale-but-present token in play — the
container's own 401 is where that belongs (CAL-941). An already-exported
`CLAUDE_CODE_OAUTH_TOKEN` short-circuits the whole path: no store read, no refresh.

Tracker credentials resolve **env → `.env` → `gh auth token`**, per key, with `gh`
consulted only for `GITHUB_TOKEN` and only when it is still unset (issue #170). A `.env`
that omits a key yields an empty value and resolution continues — issue #171's guarantee,
now a property of the parser rather than of a trailing `|| true` on every grep.

### The wrapper contract

The wrapper is a delegating shim. It resolves an interpreter via a ladder
(`$HARNESS_HOST_PYTHON` → the checkout's `.venv` → bare `python3` with `PYTHONPATH`)
and execs `harness.hostenv.client`, which spawns the verb container. Secrets cross
into the container **by name** (`-e GITHUB_TOKEN`), keeping them out of the
container's argv where `ps` could read them.

**Superseded in part by [#307](../../specs/features/runtime-host.md).** Until then the
shim called `python3 -m harness.hostenv env --workdir "$(pwd)"` and imported
NUL-terminated `KEY=value` records back into bash with `export "$KEY=value"` — never
`eval`, and never newline-delimited, so a credential carrying shell metacharacters or a
newline could not be executed or split. That import is gone: `harness.hostenv.client`
now calls `resolve_container_env` in-process and hands the values to `docker` through
the subprocess environment, so no credential value passes through the shell at all and
the class of problems the record-format rules guarded against no longer exists.
`python3 -m harness.hostenv env` remains as a thin CLI over the same resolver — the
records and their format are unchanged — but the wrapper is no longer its caller.

The other half of that supersession is the degraded path. It **used to** warn once and
proceed with whatever environment was set, because failing closed would turn a wrapper
deployed without its checkout from degraded into dead. Since #307 the client *is* the
runtime, so there is nothing left to degrade to short of re-implementing container
construction in bash; a missing interpreter is now a hard exit naming
`HARNESS_HOST_PYTHON`.

**The shim runs under `set -euo pipefail`, and no command it runs may hide behind a
builtin's exit status (#383).** The wrapper computes one value the client cannot —
`HARNESS_WRAPPER_STATUS`, the symlink/copy/detached/drifted verdict `harness doctor`
reports — and until #383 it computed it as `export NAME="$(_wrapper_status)"`. That is
a single command whose status is `export`'s, so a failing `_wrapper_status` never
reached `set -e`: the wrapper carried on and spawned the container with an empty
verdict, which `doctor` then reads as "no wrapper mediated this". Assignment and
`export` are now separate commands, so the probe's own status stops the wrapper. The
rule generalises past this one line, which is why a source guard holds it rather than
the shellcheck run alone — shellcheck's SC2155 is satisfiable by a `disable` directive
that leaves the masking in place, and it does not run on a host without shellcheck
installed, which is every developer machine here.

## Data model

No persisted state: no ledger table, no schema, no migration. `AgentCredential`,
`TrackerCredentials`, `GitIdentity` and `HostPlatform` are in-process value objects.

## What is deliberately **not** here

**The image-freshness guard and the source-checkout sync stay in shell.** Their job
includes detecting *this wrapper has no checkout behind it* — the detached-copy
deployment (CAL-1153) — which is exactly the state in which checkout-resident Python
cannot be imported. A guard that cannot fire in the deployment it was written for is not
a guard. That retained half keeps its own `timeout`/`gtimeout` probe to bound a
`git fetch`, because the one mechanism that would replace it (`bounded_run`) is
unavailable precisely there. `tests/unit/test_wrapper_delegates.py` pins that boundary so
the probe cannot spread back into paths that *can* reach Python.

**WSL is unverified.** `LINUX_CREDENTIALS_RELPATH` (`~/.claude/.credentials.json`) is
documentation-derived; it has not been checked against an installed Claude CLI under WSL,
because the machine this was built on is macOS. It is one named constant rather than a
search over candidate paths, so the blast radius of being wrong is one line, and
`HARNESS_CLAUDE_CREDENTIALS_FILE` is the operator's correction seam. ADR 0012 already
records WSL as a claim until exercised on a real Windows host; **#313 is that ticket**.
This is why `status:` above is `partial` rather than `implemented`.

**The compose seam still carries the #380 defect.** `tests/unit/test_container_hardening.py`
derives the repo's *mounting seams* from `docker/` — the files that bind-mount a host
tree at `/workspace` — and finds exactly two: the programmatic one in
`harness.hostenv.spawn`, and `docker/docker-compose.yml`. #380 fixed the first and
rewrote `docker/README.md`'s three hand-written `docker run` recipes to carry
`--user "$(id -u):$(id -g)" -e HOME=/home/harness`. It did **not** touch the compose
file, which has neither `user:` nor a `HOME` entry, so a Linux operator invoking
`docker compose … run harness start …` still gets the exact `PermissionError` this
ticket exists to end. Compose cannot call `id -u` inline the way a shell recipe can, so
the fix needs a decided invocation contract (exported `UID`/`GID`, or harness-specific
variables) rather than a one-line copy — which is why it is recorded here as a known gap
rather than silently carried. The cross-seam property that *is* enforced today is
`PYTHONDONTWRITEBYTECODE=1` (#278); writability is not yet one.

#308 added two more claims to that list, and deliberately did not pretend otherwise.
Whether Docker Desktop's WSL2 backend can bind-mount a socket out of the distro
filesystem is unverified — but the failure is *loud* either way (docker fails at run
time, or the target is an empty directory and ssh reports `Error connecting to agent` in
push output), and the private key never crosses regardless. That is the whole reason the
provider mounts the probed socket rather than guessing the bridge: a wrong guess there
would be silent. Whether drvfs could in fact carry the semantics the verbs need is
likewise unverified, which is why that case refuses rather than warns. #313 remains where
both are earned.

## Verification

- `tests/unit/test_hostenv_host.py` — provider detection (every branch injected), both
  credential stores, git identity, bounded execution on both providers; the per-provider
  `(probed, source)` agent pairing with a floor asserting only macOS returns the bridge,
  and the `/mnt/c` refusal including the non-default-automount and unreadable-table cases,
  with a negative control that a non-WSL provider does **not** refuse a `/mnt` path.
  For #380: that only `MacOSHost` declines to pin a container user (floored so a table
  collapsing to all-`None` is red), that `LinuxHost` reads the *invoking* uid rather
  than a second copy of the image's constant — asserted with `os.getuid`/`getgid`
  monkeypatched to 4242/4243, because a live read cannot discriminate a hardcoded 1000
  on a uid-1000 box — and that uid 0 is refused where the object is built.
- `tests/unit/test_hostenv_spawn.py` — the mapping round-trip, each `WorkspaceMount`
  refusal (including `from_container`'s outside-the-target branch, whose wrong answer
  would resolve a run to a directory that is not its worktree), the colon refusal on a
  forwarded agent socket with a well-formed-still-accepted floor, and that the three
  emissions of `target` agree with each other (floored by an assertion that the default
  is still `/workspace`). For #380: `--user` lands in the option region with both
  fields and is absent when the provider pins nothing; a caller's own `--user 0:0` is
  forwarded to the verb without displacing the host's; no provider on any uid can emit
  a `0:`-prefixed user (the subject set is derived by walking the three real providers
  across a uid range including 0, with a floor asserting it is non-empty); and `HOME` is
  pinned by value to the directory the credential mounts target.
- `tests/unit/test_container_hardening.py` — the macOS argv asserted through the real
  provider, so it is evidence the refactor changed no macOS behaviour; and that no bearer
  push credential reaches the `review` container, with a negative control proving that ban
  can fail. The ban reads `client.FORWARDED_ENV_NAMES` — the list production actually
  forwards — rather than a literal supplied by the test: scanning a test-owned list would
  hold whatever production did, which is the vacuous shape #181 records, and was measured
  to pass with `GH_TOKEN` added to the real tuple before it was pointed at production.
  Since #380 it also holds the two image-source invariants: that a `chmod` grants
  other-traverse+write on `spawn.CONTAINER_HOME` (path read from the module that emits
  the mounts, so a home that moved without the Dockerfile moving is red), and AC-3 —
  that the `/workspace`-writability comment names the mechanism token the production
  argv actually emits and names the platform whose daemon remaps ownership, so it can no
  longer read as the unconditional Docker Desktop claim it used to be. Both are source
  re-reads and neither is the evidence; the docker-marked tests below are.
  Since #383 it also holds the exit-status rule above:
  `test_no_export_masks_the_status_of_the_command_it_runs` reads the wrapper for an
  `export NAME=` whose value is a command substitution. It sits beside
  `test_wrapper_is_shellcheck_clean` rather than behind it, because a
  `# shellcheck disable=SC2155` makes that one pass while leaving the masking, and it
  skips outright where shellcheck is absent. Its predicate is proven on synthetic
  source (`test_the_masking_predicate_discriminates_on_synthetic_source`), including
  the `disable`-directive shape. It reads `export` only, so the same masking spelled
  `local`, `declare -x`, or `readonly` is still shellcheck's to catch.
- `tests/unit/test_cli_serve.py`, `tests/unit/test_hostenv_client.py` — a refused repo is
  refused on **both** spawn paths with nothing spawned, and since #380 a root invocation
  is too; and the provider's container user reaches docker on **both**, which matters
  because a dropped argument at either call site is invisible on macOS, where `None` is
  also the correct answer.
- `tests/unit/test_hostenv_per_request_credentials.py` — the resolver carries the
  provider's container user rather than the field's `None` default, pinned to ids nobody
  on the machine has so the value can only have come from the provider.
- `tests/integration/test_docker.py` (docker-marked) — the runtime evidence, both
  building their argv through `spawn.build_docker_argv` rather than a hand-rolled
  `docker run`: a verb runs under uid 4242, which the image has no passwd entry for
  (measured red before the fix on *every* host, so it is vacuous nowhere), and a mutating
  verb writes a bind-mounted repo whose ledger comes back owned by the invoking uid. The
  second carries an explicit skip at `os.getuid() == 1000`, where the assertion cannot
  tell the fix from the baked uid working anyway; the runner is not 1000, and CI shows it
  ran rather than skipped.
- `tests/unit/test_hostenv_credentials.py` — the staleness boundary, the refresh flow,
  tracker precedence, `.env` parsing including the embedded-`=` case.
- `tests/unit/test_hostenv_stdlib_only.py` — the package imports with site-packages off
  the path; the banned-dependency set is derived from `pyproject.toml`, not listed. It
  covers `container_env.py` automatically, because the set is derived over the package.
- `tests/unit/test_wrapper_delegates.py` — AC-2, with a negative control proving the
  predicate distinguishes a live call from a comment describing one.
- `tests/unit/test_wrapper_image_staleness.py`, `tests/unit/test_wrapper_source_sync.py` —
  pass **unmodified**, which is what shows the port changed no wrapper behaviour.
