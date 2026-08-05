# harness — Docker

Container image and compose setup for running the harness against any target
project. Reference: SPEC.md §13.

## What this gives you

A self-contained Python 3.11-slim image with the harness pre-installed via
`uv`. The host project repo is mounted at `/workspace`, so worktrees and the
SQLite state database (`.harness/harness.db`) live on the host filesystem.

The image ships **git 2.50.x compiled from source** rather than the base OS
package. `harness start` creates each run's worktree in-container but that same
worktree is operated on from the host, so its `.git`/`gitdir` pointers must be
written in **relative** form to resolve across the `/workspace`↔`/Users/...`
mount boundary (`worktree.useRelativePaths`, git ≥ 2.48). Debian trixie freezes
git at 2.47.3, which cannot write — or even open — a relative-pointer worktree,
so the Dockerfile's `git-build` stage compiles a matching git and copies it in
(see [`specs/features/worktree-lifecycle.md`](../specs/features/worktree-lifecycle.md)).
A **host** using this layout likewise needs git ≥ 2.48.

The image is **not** a long-running service. The harness CLI is a one-shot
process: each `docker run` invokes one verb (or one headless agent run) and
exits. The entrypoint selects the role — `agent <TICKET>` drives the full
`/harness run` loop headless, `verb <args…>` (or a bare verb) runs a single
`start` / `design` / `review` / `close` / read command.

The image is the harness's **own** runtime, not the target project's. It carries
only what the verbs themselves need; it does **not** carry the target repo's
toolchain, and the target's verify gate runs **host-side**, not in this
container. The orchestrator runs `CONTEXT.md → verify:` in the worktree and hands
the result to `review` (`--gate-exit`/`--gate-log`) — the evidence model that
lets a recorded `pass` mean "the gate ran green" without the image needing every
target's build tools (CAL-1082; no image can carry an arbitrary repo's
toolchain, e.g. an Xcode target never runs in a Linux container).

## Files

| Path | Purpose |
|------|---------|
| `docker/Dockerfile` | Image definition. Python 3.11-slim, a `git-build` stage compiling git 2.50.x (relative worktrees need ≥ 2.48; trixie ships 2.47.3), deps via `uv sync --frozen --no-dev`, ENTRYPOINT `uv run harness`. |
| `docker/docker-compose.yml` | Dev compose with mount, working dir, env vars, and `host.docker.internal` bridge. |
| `.dockerignore` (repo root) | Excludes `.venv/`, `tests/`, `.git/`, `.worktrees/`, `.harness/`, `__pycache__/`, etc. |

## Build

From the repo root:

```bash
docker build -t harness:dev -f docker/Dockerfile .
```

Or via compose:

```bash
docker compose -f docker/docker-compose.yml build harness
```

The image tag `harness:dev` is what the integration test
(`tests/integration/test_docker.py`) builds and asserts against.

## Sanity check

```bash
docker run --rm harness:dev version
# → harness 0.2.1
```

## Authentication

The harness image uses two agents — Claude Code (agent mode, which drives the
`/harness run` loop) and Codex (the `review` verb's reviewer) — both via
subscription OAuth (no API keys). The `~/bin/harness` wrapper handles all
credential wiring automatically.

### Claude Code — `CLAUDE_CODE_OAUTH_TOKEN`

On macOS, OAuth credentials live in the Keychain — not in a file that can be
mounted. The wrapper extracts the token on each invocation and passes it as an
env var.

```bash
# Manually (or in CI):
CLAUDE_CODE_OAUTH_TOKEN=$(security find-generic-password -s "Claude Code-credentials" -w \
  | python3 -c "import sys,json; d=json.load(sys.stdin); print(d['claudeAiOauth']['accessToken'])")

docker run --rm -it \
  -v "$(pwd)":/workspace -w /workspace \
  -e CLAUDE_CODE_OAUTH_TOKEN \
  harness:dev \
  start CAL-123
```

> **Do not mount `~/.claude` read-only.** Claude Code writes session state
> to that directory during execution. A `:ro` mount causes silent stalls
> where the agent runs for minutes then exits without calling submit.

### Codex — `~/.codex` volume mount

Codex uses subscription auth (`auth_mode: chatgpt`) stored in
`~/.codex/auth.json`. The wrapper mounts the directory into the container so
the `codex` CLI can read its credentials. No `OPENAI_API_KEY` is needed or
passed.

The mount is **read-only** (`:ro`). Unlike `~/.claude` — which the in-container
Claude engine writes session state to, so it must stay read-write — the
in-container review engine is Claude, not Codex (`--engine codex` is host-only,
[ADR 0002](../specs/decisions/0002-in-container-review-engine.md)). Nothing in
the container writes `~/.codex`, so read-only removes that write surface without
breaking anything. [ADR 0013](../specs/decisions/0013-codex-engines-in-container.md)
amends ADR 0002's *reason* — the wall is a seccomp profile, not a capability
grant — and decides to run Codex in-container behind one. **The read-only mount
is not loosened by that decision**: it holds while the profile is unshipped, and
whether a Codex engine that actually runs here needs write access is for the
tickets that enable it to establish, not something to grant ahead of them.

```bash
docker run --rm -it \
  -v "$(pwd)":/workspace -w /workspace \
  -v "$HOME/.codex":/home/harness/.codex:ro \
  -e CLAUDE_CODE_OAUTH_TOKEN \
  harness:dev \
  review --run-id 01J...
```

## Other environment variables

Pass via `-e VAR` or `--env-file`.

| Variable | Required | Notes |
|----------|----------|-------|
| `LINEAR_API_KEY` | yes for `tracker: linear` (`start` and `close` fetch and transition the ticket) | Personal API key. The wrapper reads it from `.env` in the target repo. |
| `GITHUB_TOKEN` | yes for `tracker: github` (the Projects v2 tracker backend, CAL-1105) | A token with the `repo` and `project` scopes. The wrapper resolves it **env → `.env` → `gh auth token`** and forwards it into the container. The `gh auth token` fallback (issue #170) fetches a fresh token each invocation — a `gh` OAuth token rotates (~8h, auto-refreshed from the keyring), so a static `.env` snapshot would go stale and break the unattended loop; a consuming repo's long-lived PAT in `.env` still takes precedence. |
| `CLAUDE_CODE_OAUTH_TOKEN` | yes (agent mode, and any Claude use) | Extracted from macOS Keychain automatically by `~/bin/harness`. |
| `HARNESS_WORKSPACE_ROOTS` | yes (verbs fail closed if unset) | Colon-separated allowlist of host roots a `--repo` may resolve under (CAL-584). The wrapper sets it to `/workspace` (the mounted CWD) automatically. |

## Invocation — running against another repo

Mount the target repo at `/workspace` and call a verb (or agent mode). The
harness writes the worktree and SQLite ledger under `/workspace` (i.e. the host
filesystem).

### Plain `docker run`

```bash
# In one terminal — build once.
docker build -t harness:dev -f docker/Dockerfile .

# In another terminal — open a run against your-repo.
cd /abs/path/to/your-repo
docker run --rm -it \
  -v "$(pwd)":/workspace -w /workspace \
  -v "$HOME/.claude":/home/harness/.claude:ro \
  -e LINEAR_API_KEY \
  -e GITHUB_TOKEN \
  harness:dev \
  start CAL-123
```

(Replace the `-v "$HOME/.claude":/home/harness/.claude:ro` line with `-e CLAUDE_CODE_OAUTH_TOKEN` or `-e ANTHROPIC_API_KEY` per the [Authentication](#authentication) section above. The mount targets `/home/harness` because the container runs as the non-root `harness` user — see [Thin shell wrapper](#thin-shell-wrapper-binharness).)

### Via compose

`docker-compose.yml` honours `HARNESS_TARGET_REPO` — set it to point at any
project on disk.

```bash
# Build once.
docker compose -f docker/docker-compose.yml build harness

# Open a run against another repo on disk.
HARNESS_TARGET_REPO=/abs/path/to/your-repo \
  docker compose -f docker/docker-compose.yml run --rm harness \
    start CAL-123
```

Omit `HARNESS_TARGET_REPO` to run the harness against the harness repo
itself (useful for nightly self-reviews).

## Trap — the host and the container share one `.venv`

**Rule: never run a container against a worktree while a host gate runs there.
Serialize them.**

The mount that makes everything above work is also a trap. `-v "$(pwd)":/workspace`
bind-mounts the target repo, and `<worktree>/.venv` lives *inside* that mount — so
the host and the container share one virtualenv directory while needing **different
platforms**. A Linux container venv and a macOS host venv cannot both occupy it.
Whichever runs second overwrites the other, and the loser's interpreter becomes a
dangling symlink.

In practice the container is the one that wins the race and the host gate is the
one that breaks: the venv is left pointing at `/usr/local/bin/python3`, which does
not exist on an Apple Silicon host.

### The signature

This failure is precise and cheap to recognise — worth knowing by sight, because
it looks far worse than it is:

- **Exactly 5 tests fail**; the other ~1880 pass.
- Each fails with `FileNotFoundError: .../.venv/bin/python`.
- The five are the only ones that spawn `sys.executable` as a **subprocess**
  (`test_cli_module_entrypoint_still_works`, two in `test_cli_review`, two in
  `test_smoke`).

That ratio is the tell. A clobbered venv **only bites processes spawned after
it** — pytest's own parent interpreter is already loaded in memory, so every test
that stays in-process passes normally. A broad breakage would not spare 1880 tests.

### The diagnostic

```bash
grep home <worktree>/.venv/pyvenv.cfg
```

A healthy **host** venv reads `/opt/homebrew/...` or
`~/.local/share/uv/python/cpython-3.11-macos-aarch64-none`. A clobbered one reads
`home = /usr/local/bin` — the container's Linux interpreter.

### The fix

```bash
rm -rf <worktree>/.venv
```

Then re-run the gate; it rebuilds the venv for the host. Nothing else is damaged —
the venv is derived state.

### What actually triggers it (scoped to what has been observed)

Both observations were of an **ad-hoc container run against a worktree** — a
hand-run diagnostic probe, where the mechanism was plausibly a `.claude` hook
invoking the container's `uv`. That is the only confirmed trigger.

`harness review` runs the same image against the same cwd and is therefore a
**suspect**, but it has **never been observed** clobbering the venv across ~30
ticks of fail→fix→re-gate, and a mid-review check found the venv still macOS. So
do **not** remove the venv prophylactically: reach for the fix when you see the
signature above, not as a ritual. Treating an unproven cause as fact would mask
the real trigger if this resurfaces.

The gate never does this to itself — `scripts/verify.sh` contains no `docker` at
all.

## Thin shell wrapper (`~/bin/harness`)

**This is the recommended way to run the harness.** Install once; use from any
directory with no flags or env-var setup.

### What the wrapper does automatically

- **`LINEAR_API_KEY`** — reads from a `.env` file in the current directory if
  not already in the shell environment.
- **Claude OAuth** — extracts the access token from the macOS Keychain
  (`Claude Code-credentials`) on each invocation, and **refreshes it first if it
  is expired or about to expire** (via `claude -p ok`, which makes the CLI write a
  fresh token back to the Keychain) so a stale token never reaches the container
  (CAL-941). No manual token setup or `~/.claude` mount needed; the Keychain is
  the source of truth on macOS.
- **Codex OAuth** — mounts `~/.codex` **read-only** into the container. Codex
  uses subscription auth (`auth_mode: chatgpt`) stored in `~/.codex/auth.json`;
  no `OPENAI_API_KEY` is required or passed. Read-only is safe because the
  in-container review engine is Claude, not Codex (`--engine codex` is host-only,
  [ADR 0002](../specs/decisions/0002-in-container-review-engine.md), whose reason
  [ADR 0013](../specs/decisions/0013-codex-engines-in-container.md) amends) —
  nothing in the container writes `~/.codex`. Read-only stays read-only until a
  ticket that runs Codex here shows otherwise.
- **Image freshness** — rebuilds `harness:dev` when this repo's `harness/`
  source is newer than the image (CAL-1144). Nothing else rebuilds the image
  after a merge to `dev`, so a verb that ships is otherwise invisible to the next
  run, which sees only `No such command '<verb>'` and reads it as missing code
  rather than a stale image. The check compares `docker image inspect` against
  `git log -1 --format=%ct -- harness/`, costs ~10ms, and fires a build **only**
  when the source actually moved — once per merge, against a warm layer cache. A
  rebuild that fails exits non-zero rather than falling through to the stale
  image, and all of its output goes to **stderr** so the verbs' JSON contract on
  stdout stays parseable. An explicit `HARNESS_IMAGE` is never rebuilt: a pinned
  tag is the caller's to manage. The guard needs a source tree to compare
  against, so it runs only from a **symlinked** install; a **copied** wrapper
  (see [Copy](#installation) below) resolves outside any checkout, and once an
  image exists it warns once on stderr — naming the detached-copy cause and the
  symlink remedy — then runs the verb unguarded rather than failing (CAL-1153).
  Symlink the wrapper to arm the guard.
- **Source-checkout sync** — fast-forwards the wrapper's own checkout to its
  upstream before that freshness comparison runs (#286). It is what makes the
  comparison mean anything: the loop transacts entirely in `origin/<base>`
  (`close` merges and pushes from a throwaway worktree, `start` bases each
  worktree off the remote ref), so `refs/heads/<base>` — the ref the guard
  measures — is the one ref nothing advances. Left alone it freezes, and the
  freshness check above can never fire again. Observed: the checkout sat 37
  commits behind `origin/dev` with a shipped, closed fix not in effect and no
  signal of any kind. It uses `fetch` + `merge --ff-only` rather than `pull` so
  operator gitconfig cannot change what it does, takes its target from git's own
  `@{upstream}`, and **only ever fast-forwards** — a diverged checkout (a stray
  local commit) is reported on stderr with both counts and left untouched, never
  rebased. A missing upstream, an unreachable remote, or a refused fast-forward
  each warn and continue; none changes the exit code, because wedging the
  unattended queue would be worse than the staleness it guards. An explicit
  `HARNESS_IMAGE` suppresses the sync too — a pinned tag means the operator's
  tree should not be written either.
- **Git identity** — passes `GIT_AUTHOR_NAME/EMAIL` and
  `GIT_COMMITTER_NAME/EMAIL` from the host git config so commits inside the
  container are attributed correctly.
- **SSH credentials** — mounts `~/.ssh` read-only (for `known_hosts`) **and
  forwards the host ssh-agent** so `git push` over SSH works on the close verb.
  On macOS the signing key is passphrase-protected in the Keychain and is *not*
  usable from the mounted file, so the agent socket
  (`/run/host-services/ssh-auth.sock`, provided by Docker Desktop) is forwarded
  into the container instead. `GIT_SSH_COMMAND` is set with `-F /dev/null` so the
  macOS `~/.ssh/config` (which carries `UseKeychain yes`, an option Linux ssh
  rejects) is ignored; auth comes from the forwarded agent. Docker Desktop
  exposes that socket as `root`-owned, group-rw, so the wrapper adds
  `--group-add 0` — the non-root `harness` user (uid 1000) otherwise cannot
  connect to it and every push fails `Permission denied (publickey)`.
  > **Scope the forwarded key.** The container runs untrusted diff content, and a
  > forwarded agent can authenticate as you to **any** host your loaded keys
  > reach. Load only a key **scoped to the target remote(s)** into the agent for
  > a harness run (e.g. a deploy key for the repo, not your account-wide key), so
  > an in-container compromise cannot push to unrelated hosts on your behalf.
- **Non-root user** — the container runs as the unprivileged `harness` user
  (uid 1000), not root (CAL-1008), so an in-container compromise is not root over
  the mounted repo or credentials. Host credentials are therefore mounted under
  that user's home (`/home/harness/.ssh`, `/home/harness/.codex`) — reachable by
  a non-root process — **not** `/root/...`, which is mode `700` and unreadable to
  it.
- **TTY detection** — passes `-it` only when stdin is a real terminal, so the
  same wrapper works in scripts and CI.

### Installation

The wrapper is versioned at [`docker/harness-wrapper.sh`](harness-wrapper.sh) —
a single, `bash -n`-clean source (guarded by
`tests/unit/test_container_hardening.py`), **not** a copy-pasted blob. Its full
behaviour is documented in [What the wrapper does automatically](#what-the-wrapper-does-automatically)
above; install it by putting it on your `PATH` as `harness`.

**Symlink (recommended).** A symlink keeps `~/bin/harness` in lockstep with the
repo — a wrapper fix (as CAL-1008 and CAL-1122 were) propagates automatically, so
the installed tool can never silently drift from its versioned source. Since
[#286](https://github.com/sluengen/harness/issues/286) the wrapper fast-forwards
that checkout itself, so this no longer depends on anyone remembering to `git
pull`; the fix lands on the next invocation:

```bash
mkdir -p ~/bin
ln -sf "$(pwd)/docker/harness-wrapper.sh" ~/bin/harness
```

**Copy** if you prefer a detached snapshot (re-copy after each `git pull` to pick
up fixes — this is the drift path CAL-1123 exists to avoid):

```bash
cp docker/harness-wrapper.sh ~/bin/harness && chmod +x ~/bin/harness
```

Then ensure `~/bin` is on your `PATH`:

```bash
# Add to ~/.zshrc or ~/.bashrc if not already present:
export PATH="$HOME/bin:$PATH"
```

### Usage

```bash
cd /path/to/any-repo
harness start CAL-123          # then: harness review --run-id <id> → harness close CAL-123
```

Set `HARNESS_IMAGE` to point at a specific tag or registry image if you are
not using the locally-built `harness:dev`.

### Token expiry

The OAuth token extracted from the Keychain is short-lived (a few hours). The
wrapper reads its `expiresAt` and, when the token is missing or within 5 minutes
of expiring, triggers the Claude CLI's own refresh host-side (`claude -p ok`,
which exchanges the stored refresh token and writes a fresh access token back to
the Keychain) before passing it in — so a run started long after `claude /login`
still authenticates in the container (CAL-941). The freshness (`expiresAt`) is
forwarded as `CLAUDE_CODE_OAUTH_EXPIRES_AT`, and `harness doctor` fails loudly on
an expired token rather than letting `review` 401 silently. If the refresh cannot
run — the stored refresh token is itself dead, or `claude` is not on `PATH` — the
wrapper falls back to the stale token and `doctor` reports it; run `claude /login`
on the host to re-establish the Keychain entry.

## Notes / caveats

- **Image is self-contained.** Source is `COPY`'d in, not bind-mounted, so
  the running container is reproducible. For local iteration on harness
  code, rebuild the image or run the harness natively with `uv run`.
- **Linux host networking.** `host.docker.internal` is auto-provisioned on
  Docker Desktop (macOS / Windows). On Linux, the compose file's
  `extra_hosts: host.docker.internal:host-gateway` adds it explicitly so a
  host-served endpoint resolves the same way everywhere.
- **No tests inside the image.** `tests/` is in `.dockerignore`; runtime
  images don't ship test files. The integration test in
  `tests/integration/test_docker.py` runs on the host and shells out to
  `docker build` / `docker run`.
