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

harness wraps `claude_agent_sdk`, which wraps Claude Code. Auth
follows Claude Code's conventions — there are three paths, in order of
preference:

### Option A — Mount your local Claude credentials (recommended)

If you've run `claude /login` on the host, your OAuth credentials live at
`~/.claude/`. Mount that into the container and `claude_agent_sdk` picks
them up. **Subscription pricing.** Nothing else to set.

```bash
docker run --rm -it \
  -v "$(pwd)":/workspace -w /workspace \
  -v "$HOME/.claude":/root/.claude:ro \
  harness:dev \
  run steward --domain=architecture
```

### Option B — `CLAUDE_CODE_OAUTH_TOKEN` env var

For CI or any context where the `~/.claude` mount is awkward, generate a
long-lived OAuth token once and pass it as an env var. **Subscription
pricing**, no mount needed.

```bash
# One-time on the host
export CLAUDE_CODE_OAUTH_TOKEN="$(claude setup-token)"  # sk-ant-oat01-...

# Then any container invocation
docker run --rm -it \
  -v "$(pwd)":/workspace -w /workspace \
  -e CLAUDE_CODE_OAUTH_TOKEN \
  harness:dev \
  run steward --domain=architecture
```

### Option C — `ANTHROPIC_API_KEY` (fallback, API rates)

Pay-per-token, no subscription. Use only when neither OAuth path is
available (e.g. CI without OAuth access). The SDK picks this up only if
no OAuth source is found.

```bash
docker run --rm -it \
  -v "$(pwd)":/workspace -w /workspace \
  -e ANTHROPIC_API_KEY \
  harness:dev \
  run steward --domain=architecture
```

## Other environment variables

Pass via `-e VAR` or `--env-file`.

| Variable | Required | Notes |
|----------|----------|-------|
| `LINEAR_API_KEY` | yes (for workflows that fetch Linear) | Personal API key. |
| `HARNESS_WORKFLOWS_DIR` | — | **Baked into the image** as `/opt/harness/workflows`. Override only when using custom workflows. |
| `OPENAI_API_KEY` | optional | Used by OpenAI-compatible adapters (e.g. local Ollama via the OpenAI SDK). v1.5+. |
| `OLLAMA_BASE_URL` | optional | Defaults to `http://host.docker.internal:11434/v1` so the container can reach Ollama running on the host. v1.5+. |

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

To call the containerised harness as if it were a native binary, install a
thin wrapper on your `PATH`. Create `~/bin/harness` (or any directory that is
on your `PATH`):

```bash
#!/usr/bin/env bash
# ~/bin/harness — thin wrapper around the harness Docker image.
#
# Usage: harness run build --linear=HAR-123
#   (identical to the native CLI; the container mounts the current directory.)
set -euo pipefail

IMAGE="${HARNESS_IMAGE:-harness:dev}"

exec docker run --rm -it \
  -v "$(pwd)":/workspace \
  -w /workspace \
  -v "$HOME/.claude":/root/.claude:ro \
  -e LINEAR_API_KEY \
  ${ANTHROPIC_API_KEY:+-e ANTHROPIC_API_KEY} \
  ${CLAUDE_CODE_OAUTH_TOKEN:+-e CLAUDE_CODE_OAUTH_TOKEN} \
  "$IMAGE" \
  "$@"
```

Make it executable and place it on your `PATH`:

```bash
chmod +x ~/bin/harness
# Ensure ~/bin is on PATH (add to ~/.zshrc or ~/.bashrc if needed):
export PATH="$HOME/bin:$PATH"
```

Then run workflows from any directory:

```bash
cd /path/to/your-repo
harness run build --linear=HAR-123
```

Set `HARNESS_IMAGE` to point at a specific tag or registry image if you are
not using the locally-built `harness:dev`.

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
