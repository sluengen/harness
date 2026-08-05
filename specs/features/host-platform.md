---
feature: host-platform
status: partial
last_updated: 2026-08-05
tickets: ["#305"]
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
because `sys.platform` reports `linux` for both and the follow-on ADR 0012 work (bind-mount
path translation, ssh-agent forwarding) turns on exactly that difference. Both flavours
share one class today — only the *store* varies, so tracker credentials, git identity and
bounded execution live once on the ABC.

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

## Verification

- `tests/unit/test_hostenv_host.py` — provider detection (every branch injected), both
  credential stores, git identity, bounded execution on both providers.
- `tests/unit/test_hostenv_credentials.py` — the staleness boundary, the refresh flow,
  tracker precedence, `.env` parsing including the embedded-`=` case.
- `tests/unit/test_hostenv_stdlib_only.py` — the package imports with site-packages off
  the path; the banned-dependency set is derived from `pyproject.toml`, not listed.
- `tests/unit/test_wrapper_delegates.py` — AC-2, with a negative control proving the
  predicate distinguishes a live call from a comment describing one.
- `tests/unit/test_wrapper_image_staleness.py`, `tests/unit/test_wrapper_source_sync.py` —
  pass **unmodified**, which is what shows the port changed no wrapper behaviour.
