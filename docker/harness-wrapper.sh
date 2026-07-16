#!/usr/bin/env bash
# ~/bin/harness — thin wrapper around the harness Docker image.
#
# This is the SINGLE VERSIONED SOURCE of the wrapper (CAL-1123). Install it by
# symlinking or copying this file onto your PATH as `harness` — see
# docker/README.md "Thin shell wrapper". Do not hand-copy a snapshot of the
# script into ~/bin/harness: a detached copy silently rots (it missed CAL-1008's
# credential-path fix for 12 days). Symlinking to this file keeps ~/bin/harness
# in lockstep with the repo on every `git pull`.
#
# Usage: harness start CAL-123   (then review / close — the verb loop)
#   (identical to the native CLI; the container mounts the current directory.)
#
# Auth:
#   Claude Code  — OAuth token extracted from macOS Keychain on each invocation.
#   Codex        — subscription OAuth; ~/.codex is mounted so the CLI can read
#                  auth.json (same auth_mode as Claude, no API key needed).
#
# Override the image with HARNESS_IMAGE=harness:some-tag harness start ...
set -euo pipefail

IMAGE="${HARNESS_IMAGE:-harness:dev}"

# Pull LINEAR_API_KEY from the shell or a local .env file.
if [[ -z "${LINEAR_API_KEY:-}" && -f "$(pwd)/.env" ]]; then
  LINEAR_API_KEY=$(grep -E '^(export[[:space:]]+)?LINEAR_API_KEY=' "$(pwd)/.env" | head -1 | cut -d= -f2- | tr -d '\r')
  export LINEAR_API_KEY
fi

# Workspace allowlist (CAL-584): the verbs reject any --repo outside
# HARNESS_WORKSPACE_ROOTS, failing closed when it is unset. The wrapper always
# mounts CWD as /workspace, so /workspace is the only valid root *inside the
# container*. Do NOT forward a host-side value: a host path (e.g. an exported
# HARNESS_WORKSPACE_ROOTS=/Users/me/Code for native runs) is meaningless in the
# container and would reject the mounted repo, breaking cross-repo runs. Pin it.

# Pull the Claude OAuth token from the macOS Keychain (containers can't read the
# Keychain directly). The stored access token is short-lived (a few hours), so
# passing it verbatim long after `claude /login` makes every in-container `claude`
# call 401 — which surfaces as a false `review` failure (CAL-941). So read the
# token AND its expiry, and if the token is missing or within 5 min of expiring,
# trigger the Claude CLI's own refresh host-side (`claude -p ok` makes the CLI
# exchange the stored refreshToken and write a fresh token back to the Keychain),
# then re-read. Both are forwarded (CLAUDE_CODE_OAUTH_EXPIRES_AT too) so
# `harness doctor` can flag a stale token instead of failing silently in review.
if [[ -z "${CLAUDE_CODE_OAUTH_TOKEN:-}" ]]; then
  _read_claude_token() {
    security find-generic-password -s "Claude Code-credentials" -w 2>/dev/null \
      | python3 -c "import sys,json;d=json.load(sys.stdin)['claudeAiOauth'];t=d.get('accessToken') or '';print(t, int(d.get('expiresAt') or 0)) if t else None" 2>/dev/null
  }
  read -r CLAUDE_CODE_OAUTH_TOKEN CLAUDE_CODE_OAUTH_EXPIRES_AT < <(_read_claude_token) || true
  _now_ms=$(python3 -c "import time; print(int(time.time()*1000))")
  if [[ -z "${CLAUDE_CODE_OAUTH_TOKEN:-}" || "${CLAUDE_CODE_OAUTH_EXPIRES_AT:-0}" -le "$((_now_ms + 300000))" ]]; then
    if command -v claude >/dev/null 2>&1; then
      # macOS ships no `timeout`; use it (or coreutils `gtimeout`) when present.
      if command -v timeout >/dev/null 2>&1; then _t=(timeout 60)
      elif command -v gtimeout >/dev/null 2>&1; then _t=(gtimeout 60)
      else _t=(); fi
      ${_t[@]+"${_t[@]}"} claude -p ok >/dev/null 2>&1 || true
      read -r CLAUDE_CODE_OAUTH_TOKEN CLAUDE_CODE_OAUTH_EXPIRES_AT < <(_read_claude_token) || true
    fi
  fi
  export CLAUDE_CODE_OAUTH_TOKEN CLAUDE_CODE_OAUTH_EXPIRES_AT
fi

# Forward the host ssh-agent for `git push` over SSH (the close verb).
# Docker Desktop bridges the host agent into the container at the fixed in-VM
# path /run/host-services/ssh-auth.sock. That path exists ONLY inside the Docker
# VM — it is never present on the macOS host — so we must NOT test for it here:
# the old `[[ -S /run/host-services/ssh-auth.sock ]]` gate ran host-side, was
# always false, and silently disabled forwarding (forcing the tokenized-https
# fallback on every close). Gate on the host actually having a reachable agent
# holding a key, and let Docker Desktop supply the socket at mount time. Falls
# back to no-agent on hosts without one.
#
# The forwarded socket is `srw-rw---- root root` inside the container. The image
# runs as `harness` (uid 1000, CAL-1008), which is not root and not in group
# root, so it cannot connect() to it: every `git push` over SSH fails
# `Permission denied (publickey)` with an otherwise healthy host agent. The
# socket is group-rw, so join group 0 to reach it. This does NOT weaken CAL-1008:
# /root stays mode 700, no mounted credential is group-root, and the only
# group-0-writable paths are /tmp, /var/tmp and /run/lock, already 1777.
# Mounting the key instead is a dead end — on macOS it is passphrase-protected in
# the Keychain and unusable from the mounted file (see "SSH credentials" above).
SSH_AGENT_ARGS=()
if [[ -n "${SSH_AUTH_SOCK:-}" ]] && ssh-add -l >/dev/null 2>&1; then
  SSH_AGENT_ARGS=(
    -v /run/host-services/ssh-auth.sock:/ssh-agent
    -e SSH_AUTH_SOCK=/ssh-agent
    --group-add 0
  )
fi

exec docker run --rm $([[ -t 0 ]] && echo "-it") \
  -v "$(pwd)":/workspace \
  -w /workspace \
  -v "$HOME/.ssh":/home/harness/.ssh:ro \
  -v "$HOME/.codex":/home/harness/.codex:ro \
  ${SSH_AGENT_ARGS[@]+"${SSH_AGENT_ARGS[@]}"} \
  -e LINEAR_API_KEY \
  -e HARNESS_WORKSPACE_ROOTS=/workspace \
  -e CLAUDE_CODE_OAUTH_TOKEN \
  -e CLAUDE_CODE_OAUTH_EXPIRES_AT \
  -e 'GIT_SSH_COMMAND=ssh -F /dev/null -o StrictHostKeyChecking=accept-new -o UserKnownHostsFile=/home/harness/.ssh/known_hosts' \
  -e "GIT_AUTHOR_NAME=$(git config --global user.name 2>/dev/null || echo 'Harness')" \
  -e "GIT_AUTHOR_EMAIL=$(git config --global user.email 2>/dev/null || echo 'harness@local')" \
  -e "GIT_COMMITTER_NAME=$(git config --global user.name 2>/dev/null || echo 'Harness')" \
  -e "GIT_COMMITTER_EMAIL=$(git config --global user.email 2>/dev/null || echo 'harness@local')" \
  "$IMAGE" \
  "$@"
