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
`start` / `review` / `close` / read command.

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
breaking anything.

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
| `LINEAR_API_KEY` | yes (`start` / `close` fetch and transition the ticket) | Personal API key. |
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
  [ADR 0002](../specs/decisions/0002-in-container-review-engine.md)) — nothing in
  the container writes `~/.codex`.
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
  tag is the caller's to manage.
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
repo — every `git pull` that fixes the wrapper (as CAL-1008 and CAL-1122 did)
propagates automatically, so the installed tool can never silently drift from
its versioned source:

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
