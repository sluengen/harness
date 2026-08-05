---
feature: host-platform
status: partial
last_updated: 2026-08-05
tickets: ["#305", "#308"]
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
**only** the two spawn concerns below. Everything else — the credential store, tracker
credentials, git identity, bounded execution — stays on `LinuxHost`/the ABC, so this
provider's unverified status cannot contaminate logic that is not platform-dependent.

### The two spawn concerns (#308)

Both were macOS constants inlined in `spawn.build_docker_argv`. They are not wrong on
macOS — they are the wrapper's proven behaviour — but reusing them elsewhere is
*silently* wrong, which is the failure class this ticket exists to end.

| Provider | `ssh_agent_forwarding()` (live agent) | `workspace_mount(repo)` |
|---|---|---|
| `MacOSHost` | mounts Docker Desktop's bridge, `--group-add 0` | default mapping |
| `LinuxHost` | mounts the probed socket itself, no group grant | default mapping |
| `WslHost` | mounts the probed socket itself, no group grant | refuses a Windows-filesystem path |

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

**Path equivalence is asserted, not assumed.** `WorkspaceMount` carries the host↔container
mapping as one object: its `target` is emitted as the `-v` target, as `-w` **and** as
`HARNESS_WORKSPACE_ROOTS`, so those three cannot disagree, and `validate` refuses a source
that is not the resolved path of the repo the caller named (the docker daemon resolves the
source in *its* namespace, so an unresolved `..` can mount a directory nobody asked for).
The mount point deliberately stays `/workspace` — see
[runtime-host](runtime-host.md) for why relocating it would strand every recorded
`runs.worktree_path`.

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
- `tests/unit/test_hostenv_spawn.py` — the mapping round-trip, each `WorkspaceMount`
  refusal, and that the three emissions of `target` agree with each other (floored by an
  assertion that the default is still `/workspace`).
- `tests/unit/test_container_hardening.py` — the macOS argv asserted through the real
  provider, so it is evidence the refactor changed no macOS behaviour; and that no bearer
  push credential reaches the `review` container, with a negative control proving that ban
  can fail.
- `tests/unit/test_cli_serve.py`, `tests/unit/test_hostenv_client.py` — a refused repo is
  refused on **both** spawn paths with nothing spawned.
- `tests/unit/test_hostenv_credentials.py` — the staleness boundary, the refresh flow,
  tracker precedence, `.env` parsing including the embedded-`=` case.
- `tests/unit/test_hostenv_stdlib_only.py` — the package imports with site-packages off
  the path; the banned-dependency set is derived from `pyproject.toml`, not listed. It
  covers `container_env.py` automatically, because the set is derived over the package.
- `tests/unit/test_wrapper_delegates.py` — AC-2, with a negative control proving the
  predicate distinguishes a live call from a comment describing one.
- `tests/unit/test_wrapper_image_staleness.py`, `tests/unit/test_wrapper_source_sync.py` —
  pass **unmodified**, which is what shows the port changed no wrapper behaviour.
