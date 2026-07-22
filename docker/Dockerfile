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
#     harness:dev start CAL-123

# ---------------------------------------------------------------------------
# git-build stage — Debian trixie (the python:3.11-slim base) freezes git at
# 2.47.3, but harness worktrees need git >= 2.48 for relative-path pointers
# (worktree.useRelativePaths). Relative pointers are the only form that resolves
# identically across the host<->container mount boundary (/Users/... vs
# /workspace), which is what eliminates the manual gitdir-pointer flip (CAL-935).
# git >= 2.48 also stamps the repo extension `relativeWorktrees`, which git < 2.48
# refuses outright — so the image git MUST be >= 2.48, not merely able to read a
# relative pointer. apt cannot supply it on trixie, so we compile from source in
# this throwaway stage and copy only the result into the runtime image, isolated
# under /opt/git (blast radius = git alone; the rest of the toolchain is
# unchanged). Version pinned to match the host git (2.50.x).
# ---------------------------------------------------------------------------
FROM python:3.11-slim AS git-build
ARG GIT_VERSION=2.50.1
# Authentic upstream sha256 of git-2.50.1.tar.xz (kernel.org) — pins provenance.
ARG GIT_SHA256=7e3e6c36decbd8f1eedd14d42db6674be03671c2204864befa2a41756c5c8fc4
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential curl ca-certificates \
        libssl-dev libcurl4-openssl-dev libexpat1-dev zlib1g-dev gettext \
    && curl -fsSL "https://mirrors.edge.kernel.org/pub/software/scm/git/git-${GIT_VERSION}.tar.xz" -o /tmp/git.tar.xz \
    && echo "${GIT_SHA256}  /tmp/git.tar.xz" | sha256sum -c - \
    && mkdir -p /tmp/git && tar -xJf /tmp/git.tar.xz -C /tmp/git --strip-components=1 \
    && make -C /tmp/git prefix=/opt/git -j"$(nproc)" NO_TCLTK=1 NO_GITWEB=1 all \
    && make -C /tmp/git prefix=/opt/git NO_TCLTK=1 NO_GITWEB=1 install \
    && rm -rf /tmp/git /tmp/git.tar.xz

FROM python:3.11-slim

# Link the published image to its source repo so GHCR connects the package to
# sluengen/harness and "Inherit access from repository" can govern who may pull
# it (CAL-623). The registry tag is published by .github/workflows/release.yml.
LABEL org.opencontainers.image.source=https://github.com/sluengen/harness

# OS deps (git comes from the git-build stage below, NOT apt — see that stage):
#   curl             — Linear / API calls
#   ca-certificates  — HTTPS to Anthropic / Linear
#   jq               — JSON wrangling in the verbs and helper scripts
#   nodejs/npm       — required to install the Claude Code CLI
#   openssh-client   — `ssh` binary for `git push` over SSH on the close verb
#                      (without it `git push` fails: "cannot run ssh: No such file or directory")
#   libcurl4/libexpat1/zlib1g — shared libs the source-built git links against at
#                      runtime (their -dev headers live only in the builder stage)
RUN apt-get update && apt-get install -y --no-install-recommends \
        curl ca-certificates jq nodejs npm openssh-client \
        libcurl4 libexpat1 zlib1g \
    && rm -rf /var/lib/apt/lists/*

# gh CLI — `harness promote pr`'s release-hop publication step shells out to
# `gh pr create` (harness/promotion_pr.py, #187); nothing else in the image
# needs it. Installed from GitHub's own apt repository (the officially
# documented path, cli.github.com/packages) rather than a pinned binary
# tarball, so `dpkg --print-architecture` resolves the right package on both
# amd64 and arm64 without an arch-conditional COPY. `gh` reads GITHUB_TOKEN
# from the environment automatically — the wrapper already forwards it
# (docker/harness-wrapper.sh) — so no `gh auth login` step is needed here.
RUN mkdir -p -m 755 /etc/apt/keyrings \
    && curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg -o /etc/apt/keyrings/githubcli-archive-keyring.gpg \
    && chmod go+r /etc/apt/keyrings/githubcli-archive-keyring.gpg \
    && echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" > /etc/apt/sources.list.d/github-cli.list \
    && apt-get update && apt-get install -y --no-install-recommends gh \
    && rm -rf /var/lib/apt/lists/*

# git >= 2.48 compiled from source in the git-build stage (Debian trixie ships
# only 2.47.3, which cannot write or even open relative-path worktrees). Copied
# under an isolated prefix and put first on PATH so `git` resolves to it.
COPY --from=git-build /opt/git /opt/git
ENV PATH=/opt/git/bin:$PATH

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

# ---------------------------------------------------------------------------
# Non-root runtime user (CAL-1008). The container reviews UNTRUSTED ticket/diff
# content with LLM agents, so an in-container compromise must not be root: as
# root it has write access to the mounted repo (incl. .git) and any mounted host
# credential (~/.ssh, ~/.codex). Drop the *runtime* process to an unprivileged
# user. Everything above (apt, source-built git, `npm -g`, `uv sync`) needs root
# and bakes into image layers; only the process that runs untrusted content drops
# privilege here.
#
# No `chown` of /opt/harness is needed: `uv sync` writes the venv world-readable
# (drwxr-xr-x) and UV_NO_SYNC=1 makes `uv run` read-only at runtime, so uid 1000
# can execute it as-is (a `chown -R` would only duplicate the venv into a fat
# extra layer). The mounted /workspace is writable because Docker Desktop maps
# bind-mount ownership to the run-time uid; per-user scratch goes under $HOME.
#
# uid is fixed at 1000 and $HOME is /home/harness so the wrapper mounts host
# credentials under the user's home (/home/harness/.ssh, /home/harness/.codex) —
# where a non-root process can read them. /root is mode 700 and unreadable to
# this user, so mounts MUST NOT target /root/... The ~/bin/harness wrapper in
# docker/README.md mounts to /home/harness/... to match.
# ---------------------------------------------------------------------------
RUN useradd --create-home --uid 1000 --shell /bin/bash harness
USER harness

# One image, two entrypoints: the script dispatches `agent <TICKET>` (headless
# per-session agent runtime) vs. `verb <args…>` / bare-verb (one-shot verb).
# Bare-verb stays backward compatible with the launcher / ~/bin/harness wrapper,
# which pass `start …` directly with no mode selector.
ENTRYPOINT ["/opt/harness/entrypoint.sh"]
