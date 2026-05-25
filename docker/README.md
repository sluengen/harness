# slate-harness — Docker

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
docker build -t slate-harness:dev -f docker/Dockerfile .
```

Or via compose:

```bash
docker compose -f docker/docker-compose.yml build harness
```

The image tag `slate-harness:dev` is what the integration test
(`tests/integration/test_docker.py`) builds and asserts against.

## Sanity check

```bash
docker run --rm slate-harness:dev version
# → slate-harness 0.1.0
```

## Required environment variables

The harness reads its secrets from the environment at run time. None are
baked into the image.

| Variable | Required | Notes |
|----------|----------|-------|
| `ANTHROPIC_API_KEY` | yes (for AI nodes) | Claude API key. |
| `LINEAR_API_KEY` | yes (for workflows that fetch Linear) | Personal API key. |
| `OPENAI_API_KEY` | optional | Used by OpenAI-compatible adapters (e.g. local Ollama via the OpenAI SDK). |
| `OLLAMA_BASE_URL` | optional | Defaults to `http://host.docker.internal:11434/v1` so the container can reach Ollama running on the host. |

Pass them in via `-e VAR` (which forwards from the host shell) or with an
`--env-file`.

## Invocation — running against another repo

Mount the target repo at `/workspace` and tell the harness to run a workflow.
The harness reads workflow YAMLs that ship inside the image
(`/opt/harness/workflows/`), but writes state and worktrees to `/workspace`
(i.e. the host filesystem).

### Plain `docker run`

```bash
# In one terminal — build once.
docker build -t slate-harness:dev -f docker/Dockerfile .

# In another terminal — run a workflow against calibrate-coffee.
cd /abs/path/to/calibrate-coffee
docker run --rm -it \
  -v "$(pwd)":/workspace -w /workspace \
  -e ANTHROPIC_API_KEY \
  -e LINEAR_API_KEY \
  slate-harness:dev \
  run steward --domain=architecture
```

### Via compose

`docker-compose.yml` honours `HARNESS_TARGET_REPO` — set it to point at any
project on disk.

```bash
# Build once.
docker compose -f docker/docker-compose.yml build harness

# Run a workflow against another repo on disk.
HARNESS_TARGET_REPO=/abs/path/to/calibrate-coffee \
  docker compose -f docker/docker-compose.yml run --rm harness \
    run steward --domain=architecture
```

Omit `HARNESS_TARGET_REPO` to run the harness against the harness repo
itself (useful for nightly self-reviews).

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
