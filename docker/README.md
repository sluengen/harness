# harness — Docker

Container image and compose setup for running the harness against any target
project. Reference: SPEC.md §13.

## What this gives you

A self-contained Python 3.11-slim image with the harness pre-installed via
`uv`. The host project repo is mounted at `/workspace`, so worktrees and the
SQLite state database (`.harness/harness.db`) live on the host filesystem.

The image is **not** a long-running service. The harness CLI is a one-shot
process: each `docker run` invokes one workflow and exits.

## Files

| Path | Purpose |
|------|---------|
| `docker/Dockerfile` | Image definition. Python 3.11-slim, deps via `uv sync --frozen --no-dev`, ENTRYPOINT `uv run harness`. |
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
# → harness 0.1.0
```

## Authentication for AI nodes

The harness image runs two AI agents — Claude Code and Codex — both using
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
  run steward --domain=architecture
```

> **Do not mount `~/.claude` read-only.** Claude Code writes session state
> to that directory during execution. A `:ro` mount causes silent stalls
> where the agent runs for minutes then exits without calling submit.

### Codex — `~/.codex` volume mount

Codex uses subscription auth (`auth_mode: chatgpt`) stored in
`~/.codex/auth.json`. The wrapper mounts the directory into the container so
the `codex` CLI can read its credentials. No `OPENAI_API_KEY` is needed or
passed.

```bash
docker run --rm -it \
  -v "$(pwd)":/workspace -w /workspace \
  -v "$HOME/.codex":/root/.codex \
  -e CLAUDE_CODE_OAUTH_TOKEN \
  harness:dev \
  run build-codex --linear=CAL-123
```

## Other environment variables

Pass via `-e VAR` or `--env-file`.

| Variable | Required | Notes |
|----------|----------|-------|
| `LINEAR_API_KEY` | yes (for workflows that fetch Linear) | Personal API key. |
| `CLAUDE_CODE_OAUTH_TOKEN` | yes (for Claude nodes) | Extracted from macOS Keychain automatically by `~/bin/harness`. |
| `HARNESS_WORKFLOWS_DIR` | — | **Baked into the image** as `/opt/harness/workflows`. Override only when using custom workflows. |

## Invocation — running against another repo

Mount the target repo at `/workspace` and tell the harness to run a workflow.
The harness reads workflow YAMLs that ship inside the image
(`/opt/harness/workflows/`), but writes state and worktrees to `/workspace`
(i.e. the host filesystem).

### Plain `docker run`

```bash
# In one terminal — build once.
docker build -t harness:dev -f docker/Dockerfile .

# In another terminal — run a workflow against your-repo.
cd /abs/path/to/your-repo
docker run --rm -it \
  -v "$(pwd)":/workspace -w /workspace \
  -v "$HOME/.claude":/root/.claude:ro \
  -e LINEAR_API_KEY \
  harness:dev \
  run steward --domain=architecture
```

(Replace the `-v "$HOME/.claude":/root/.claude:ro` line with `-e CLAUDE_CODE_OAUTH_TOKEN` or `-e ANTHROPIC_API_KEY` per the [Authentication](#authentication-for-ai-nodes) section above.)

### Via compose

`docker-compose.yml` honours `HARNESS_TARGET_REPO` — set it to point at any
project on disk.

```bash
# Build once.
docker compose -f docker/docker-compose.yml build harness

# Run a workflow against another repo on disk.
HARNESS_TARGET_REPO=/abs/path/to/your-repo \
  docker compose -f docker/docker-compose.yml run --rm harness \
    run steward --domain=architecture
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
  (`Claude Code-credentials`) on each invocation. No manual token setup or
  `~/.claude` mount needed; the Keychain is the source of truth on macOS.
- **Codex OAuth** — mounts `~/.codex` into the container. Codex uses
  subscription auth (`auth_mode: chatgpt`) stored in `~/.codex/auth.json`;
  no `OPENAI_API_KEY` is required or passed.
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
  rejects) is ignored; auth comes from the forwarded agent.
- **TTY detection** — passes `-it` only when stdin is a real terminal, so the
  same wrapper works in scripts and CI.

### Installation

Create `~/bin/harness`:

```bash
#!/usr/bin/env bash
# ~/bin/harness — thin wrapper around the harness Docker image.
#
# Usage: harness run build --linear=CAL-123
#   (identical to the native CLI; the container mounts the current directory.)
#
# Auth:
#   Claude Code  — OAuth token extracted from macOS Keychain on each invocation.
#   Codex        — subscription OAuth; ~/.codex is mounted so the CLI can read
#                  auth.json (same auth_mode as Claude, no API key needed).
#
# Override the image with HARNESS_IMAGE=harness:some-tag harness run ...
set -euo pipefail

IMAGE="${HARNESS_IMAGE:-harness:dev}"

# Pull LINEAR_API_KEY from the shell or a local .env file.
if [[ -z "${LINEAR_API_KEY:-}" && -f "$(pwd)/.env" ]]; then
  LINEAR_API_KEY=$(grep -E '^LINEAR_API_KEY=' "$(pwd)/.env" | cut -d= -f2- | tr -d '\r')
  export LINEAR_API_KEY
fi

# Pull Claude OAuth token from macOS Keychain (containers can't access Keychain directly).
if [[ -z "${CLAUDE_CODE_OAUTH_TOKEN:-}" ]]; then
  CLAUDE_CODE_OAUTH_TOKEN=$(security find-generic-password -s "Claude Code-credentials" -w 2>/dev/null \
    | python3 -c "import sys,json; d=json.load(sys.stdin); print(d['claudeAiOauth']['accessToken'])" 2>/dev/null || true)
  export CLAUDE_CODE_OAUTH_TOKEN
fi

# Forward the host ssh-agent for `git push` over SSH (the close verb).
# On macOS Docker Desktop exposes the host agent at a fixed path; the key itself
# is Keychain-backed and not usable from the mounted file, so the agent socket is
# what actually authenticates. Falls back to no-agent on hosts that lack it.
SSH_AGENT_ARGS=()
if [[ -S /run/host-services/ssh-auth.sock ]]; then
  SSH_AGENT_ARGS=(
    -v /run/host-services/ssh-auth.sock:/ssh-agent
    -e SSH_AUTH_SOCK=/ssh-agent
  )
fi

exec docker run --rm $([[ -t 0 ]] && echo "-it") \
  -v "$(pwd)":/workspace \
  -w /workspace \
  -v "$HOME/.ssh":/root/.ssh:ro \
  -v "$HOME/.codex":/root/.codex \
  ${SSH_AGENT_ARGS[@]+"${SSH_AGENT_ARGS[@]}"} \
  -e LINEAR_API_KEY \
  -e CLAUDE_CODE_OAUTH_TOKEN \
  -e 'GIT_SSH_COMMAND=ssh -F /dev/null -o StrictHostKeyChecking=accept-new -o UserKnownHostsFile=/root/.ssh/known_hosts' \
  -e "GIT_AUTHOR_NAME=$(git config --global user.name 2>/dev/null || echo 'Harness')" \
  -e "GIT_AUTHOR_EMAIL=$(git config --global user.email 2>/dev/null || echo 'harness@local')" \
  -e "GIT_COMMITTER_NAME=$(git config --global user.name 2>/dev/null || echo 'Harness')" \
  -e "GIT_COMMITTER_EMAIL=$(git config --global user.email 2>/dev/null || echo 'harness@local')" \
  "$IMAGE" \
  "$@"
```

Make it executable and ensure `~/bin` is on your `PATH`:

```bash
chmod +x ~/bin/harness
# Add to ~/.zshrc or ~/.bashrc if not already present:
export PATH="$HOME/bin:$PATH"
```

### Usage

```bash
cd /path/to/any-repo
harness run build --linear=CAL-123
```

Set `HARNESS_IMAGE` to point at a specific tag or registry image if you are
not using the locally-built `harness:dev`.

### Token expiry

The OAuth token extracted from the Keychain has an expiry. The wrapper fetches
a fresh token on every invocation, so as long as your local Claude Code session
is active the token will be valid. If you see auth errors, run `claude /login`
on the host to refresh the Keychain entry.

## Notes / caveats

- **Image is self-contained.** Source is `COPY`'d in, not bind-mounted, so
  the running container is reproducible. For local iteration on harness
  code, rebuild the image or run the harness natively with `uv run`.
- **Workflow scripts.** Workflows that invoke local `scripts/*.py` (e.g.
  `release-notes`, `steward`) resolve script paths relative to the working
  directory — i.e. the mounted target repo at `/workspace`. The target
  repo must therefore contain a matching `scripts/` tree, or the workflow
  YAML must reference scripts via an absolute path inside the image
  (planned for a later harness milestone — see SPEC §6).
- **Linux host networking.** `host.docker.internal` is auto-provisioned on
  Docker Desktop (macOS / Windows). On Linux, the compose file's
  `extra_hosts: host.docker.internal:host-gateway` adds it explicitly so
  the same Ollama URL works everywhere.
- **No tests inside the image.** `tests/` is in `.dockerignore`; runtime
  images don't ship test files. The integration test in
  `tests/integration/test_docker.py` runs on the host and shells out to
  `docker build` / `docker run`.
