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
#   ca-certificates  — HTTPS to Anthropic / Linear
#   jq               — required by every script node (set-in-progress, verify, …)
#   postgresql-client — psql for per-run DATABASE_URL provisioning in the verify node
RUN apt-get update && apt-get install -y --no-install-recommends \
        git ca-certificates jq postgresql-client \
    && rm -rf /var/lib/apt/lists/*

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
COPY workflows/ ./workflows/
COPY prompts/ ./prompts/

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
    UV_NO_SYNC=1 \
    # Tell the harness CLI where to find workflow YAMLs inside the image. Without this
    # the CLI would look for ./workflows relative to the container's CWD (/workspace,
    # the mounted target repo), which does not contain the harness workflows.
    HARNESS_WORKFLOWS_DIR=/opt/harness/workflows

ENTRYPOINT ["uv", "run", "harness"]
