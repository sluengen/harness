# harness — runtime image
# See SPEC.md §13 (Docker Setup).
#
# Build from the repo root:
#   docker build -t harness:dev -f docker/Dockerfile .
#
# Run, mounting a host project at /workspace:
#   docker run --rm \
#     -v "$(pwd)":/workspace -w /workspace \
#     -e ANTHROPIC_API_KEY -e LINEAR_API_KEY \
#     harness:dev run steward --domain=architecture
FROM python:3.11-slim

# OS deps:
#   git              — worktree operations
#   curl             — Linear/API calls in script nodes
#   ca-certificates  — HTTPS to Anthropic / Linear
#   jq               — required by every script node (set-in-progress, verify, …)
#   postgresql-client — psql for per-run DATABASE_URL provisioning in the verify node
#   nodejs/npm       — required to install Claude Code CLI (claude_agent_sdk transport)
#   openssh-client   — `ssh` binary for `git push` over SSH on the close verb
#                      (without it `git push` fails: "cannot run ssh: No such file or directory")
RUN apt-get update && apt-get install -y --no-install-recommends \
        git curl ca-certificates jq postgresql-client nodejs npm openssh-client \
    && rm -rf /var/lib/apt/lists/*

# Claude Code CLI — required by claude_agent_sdk (SubprocessCLITransport).
# OpenAI Codex CLI — required by CodexAgent (codex exec --json).
RUN npm install -g @anthropic-ai/claude-code @openai/codex

# uv handles dependency resolution and the project venv inside the image.
RUN pip install --no-cache-dir uv

WORKDIR /opt/harness

# Layer 1: dependency manifest only — maximises Docker cache reuse across source edits.
# README.md is required because pyproject.toml's `readme = "README.md"` is validated
# whenever uv resolves the local project.
COPY pyproject.toml uv.lock README.md ./

# Pre-install third-party dependencies without the project itself. The local package
# (hatchling-built `harness`) needs its source tree to install, which arrives in the
# next layer; deferring it here keeps the dep layer reusable across source edits.
RUN uv sync --frozen --no-dev --no-install-project

# Layer 2: runtime sources. Tests are intentionally excluded (see .dockerignore).
COPY harness/ ./harness/

# The two-entrypoint dispatch script (decision #3 — one image, two entrypoints).
# .dockerignore excludes docker/ wholesale, then re-includes just this file.
COPY docker/entrypoint.sh /opt/harness/entrypoint.sh
RUN chmod +x /opt/harness/entrypoint.sh

# Install the harness package itself into the venv so `uv run harness`
# resolves the console script declared in pyproject.toml (project.scripts.harness).
RUN uv sync --frozen --no-dev

ENV PYTHONUNBUFFERED=1 \
    # `uv run` discovers the project from these env vars regardless of the working
    # directory the container is invoked with — required because users mount their
    # target repo at /workspace and `uv` would otherwise fail to locate pyproject.toml.
    UV_PROJECT=/opt/harness \
    # The image is fully built; suppress uv's implicit reinstall-on-run behaviour so
    # `harness <cmd>` starts fast and doesn't try to mutate the immutable image FS.
    UV_NO_SYNC=1

# One image, two entrypoints: the script dispatches `agent <TICKET>` (headless
# per-session agent runtime) vs. `verb <args…>` / bare-verb (one-shot verb).
# Bare-verb stays backward compatible with the launcher / ~/bin/harness wrapper,
# which pass `start …` directly with no mode selector.
ENTRYPOINT ["/opt/harness/entrypoint.sh"]
