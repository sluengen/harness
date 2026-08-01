#!/usr/bin/env bash
# ~/bin/harness — thin wrapper around the harness Docker image.
#
# This is the SINGLE VERSIONED SOURCE of the wrapper (CAL-1123). Install it by
# symlinking or copying this file onto your PATH as `harness` — see
# docker/README.md "Thin shell wrapper". Do not hand-copy a snapshot of the
# script into ~/bin/harness: a detached copy silently rots (it missed CAL-1008's
# credential-path fix for 12 days). Symlinking to this file keeps ~/bin/harness
# in lockstep with the checkout, which the guard below now fast-forwards to its
# upstream on each run (#286) — so a shipped wrapper fix reaches the next
# invocation without anyone running `git pull` by hand.
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

DEFAULT_IMAGE="harness:dev"
IMAGE="${HARNESS_IMAGE:-$DEFAULT_IMAGE}"

# Image-staleness guard (CAL-1144). Nothing rebuilds the image after a merge to
# `dev`, so a verb that ships is invisible to the next unattended tick: the loop
# sees only `No such command '<verb>'` and diagnoses missing code rather than a
# stale image. That happened for real with the `defer` verb (CAL-1143). The check
# lives here because the wrapper is the one component every verb goes through —
# `doctor` is not run every tick, which is the failure mode being fixed.
#
# WHICH ref it measures is the whole correctness question, and the answer is not
# the obvious one: it measures the checked-out branch in `_source_root`, which no
# verb advances. `_sync_source_checkout` below fast-forwards that branch to its
# upstream first, so the comparison reads the tip the loop actually ships to
# (#286). Without that, this guard cannot fire at all once nobody pulls by hand.
#
# When the source is newer than the image we rebuild rather than refuse: the loop
# is unattended, and a hard error would trade a silent stale image for a queue
# that wedges every hour until a human rebuilds. The rebuild fires only when the
# source actually moved — once per merge, against a warm layer cache — never per
# invocation, which would be unaffordable (a cold --no-cache build costs ~165s).
#
# Everything below writes to STDERR: stdout carries the verbs' JSON contract,
# which the orchestrating loop parses.

# The versioned wrapper lives at <repo>/docker/harness-wrapper.sh and is symlinked
# onto PATH, so its own resolved location — not $(pwd) — identifies the source to
# compare against. $(pwd) is the *target* repo, which is frequently not this one.
_wrapper_source_root() {
  local src="${BASH_SOURCE[0]}"
  local dir
  while [[ -L "$src" ]]; do
    dir=$(cd -P "$(dirname "$src")" && pwd)
    src=$(readlink "$src")
    if [[ "$src" != /* ]]; then src="$dir/$src"; fi
  done
  (cd -P "$(dirname "$src")/.." && pwd)
}

# Source-checkout sync (#286). The staleness guard below measures the source tree
# at `_source_root`, i.e. `refs/heads/<checked-out branch>` — and that is the one
# ref the loop never advances. `close` merges and pushes `origin/<base>` from a
# throwaway worktree and never touches the main checkout (CAL-1154 Option 1), and
# `start` bases each worktree off `origin/<base>`. So once nobody runs `git pull`
# by hand, `_source_committed` is frozen and non-increasing, and the guard below
# can never fire again — failing open in exactly the case it was written for. It
# happened: the checkout sat 37 commits behind `origin/dev`, and #278's shipped,
# reviewed, closed fix was not in effect on the machine running the loop, with no
# signal of any kind that the engine and the record disagreed.
#
# Fast-forwarding here rather than measuring `origin/<base>` and building from a
# detached worktree is deliberate: `~/bin/harness` is a SYMLINK into this working
# tree, so the wrapper script itself is served from the checkout. Measuring the
# remote would rebuild the image correctly and still execute stale wrapper text —
# leaving a wrapper fix (which #278 was) exactly as un-live as before. Advancing
# the tree fixes the image and the wrapper together. The lag it cannot close: a
# fast-forward cannot re-exec the wrapper already running, so a wrapper change
# takes effect on the NEXT invocation.
#
# `fetch` + `merge --ff-only` rather than `pull --ff-only`: operator gitconfig
# (`pull.rebase`, `pull.ff`) must not be able to change what this does, and a
# network failure and a divergence need different messages — `pull` collapses
# them into one exit code. The upstream comes from git's own `@{upstream}`, not
# from `CONTEXT.md`: in a cross-repo run the nearest CONTEXT.md is the TARGET
# repo's, and an operator parked on `staging` for a promotion should not be
# dragged onto `dev`. A checkout with no upstream (detached HEAD, no tracking
# branch, a detached wrapper copy) is a silent no-op.
#
# This only ever fast-forwards. It never commits, rebases, creates a merge, or
# changes which branch is out; a state that cannot be fast-forwarded is REPORTED,
# never repaired. Only `_source_root` is written — `$(pwd)` is the target repo,
# frequently not this one, and is never touched. No outcome changes the exit code.

# Set by _sync_source_checkout when the fast-forward moved a path under harness/.
_ff_touched_harness=0

_sync_source_checkout() {
  local root="$1"
  local upstream ahead behind ff_from

  # No upstream -> nothing to sync against. Covers a detached copy (not a
  # checkout at all), a detached HEAD, and a clone with no tracking branch.
  upstream=$(git -C "$root" rev-parse --abbrev-ref --symbolic-full-name '@{upstream}' 2>/dev/null || true)
  if [[ -z "$upstream" ]]; then
    return 0
  fi

  # Bounded and non-interactive: an unreachable or hijacked remote must not hang
  # the unattended loop or prompt for a credential that no human is there to type.
  local -a fetch_cmd=(git -C "$root" fetch --quiet)
  if command -v timeout >/dev/null 2>&1; then
    fetch_cmd=(timeout 30 "${fetch_cmd[@]}")
  elif command -v gtimeout >/dev/null 2>&1; then
    fetch_cmd=(gtimeout 30 "${fetch_cmd[@]}")
  fi
  if ! GIT_TERMINAL_PROMPT=0 "${fetch_cmd[@]}" 2>/dev/null; then
    echo "harness: could not fetch $upstream — continuing against the last-known remote ref, which may leave the image built from a tip older than what shipped." >&2
  fi

  local counts
  counts=$(git -C "$root" rev-list --left-right --count "HEAD...$upstream" 2>/dev/null || true)
  if [[ -z "$counts" ]]; then
    return 0
  fi
  ahead=${counts%%[[:space:]]*}
  behind=${counts##*[[:space:]]}

  if [[ "$behind" -eq 0 ]]; then
    return 0
  fi

  # Diverged: no fast-forward can heal this, and repairing it (a rebase) is a
  # judgment call the loop must not make on the operator's commits. Report it —
  # proceeding SILENTLY on a stale engine is the failure this whole guard exists
  # to remove.
  if [[ "$ahead" -gt 0 ]]; then
    echo "harness: source checkout has DIVERGED from $upstream ($ahead ahead, $behind behind) — cannot fast-forward, so the image may be built from commits that never shipped." >&2
    echo "harness: resolve it by hand in $root (rebase or drop the local commits): git -C \"$root\" rebase $upstream" >&2
    return 0
  fi

  ff_from=$(git -C "$root" rev-parse HEAD 2>/dev/null || true)
  if ! git -C "$root" merge --ff-only "$upstream" --quiet 2>/dev/null; then
    echo "harness: could not fast-forward the source checkout to $upstream ($behind behind) — continuing as-is, which may build a stale image. Check for uncommitted changes or a stale index.lock in $root." >&2
    return 0
  fi
  echo "harness: source checkout was $behind commit(s) behind $upstream — fast-forwarded to $(git -C "$root" rev-parse --short HEAD)." >&2

  # Whether the fast-forward moved harness/ is its own rebuild trigger, and it is
  # load-bearing rather than an optimisation: `git log -1 --format=%ct -- harness/`
  # is NOT monotonic across a fast-forward. History simplification resolves a
  # merge to the feature commit's own committer date, which can predate the image
  # — so the timestamp comparison below can stay false even though the tree moved.
  # Trusting it alone would reinstate the silent-stale-engine defect.
  if [[ -n "$ff_from" ]] && ! git -C "$root" diff --quiet "$ff_from" HEAD -- harness/ 2>/dev/null; then
    _ff_touched_harness=1
  fi
}

# Wrapper-drift status (CAL-1149). `doctor` runs in-container and cannot read the
# on-PATH wrapper (`~/bin/harness` is host-only, never mounted), so here — where
# both the invoked wrapper and its versioned source are readable — is the only
# place the comparison can be made. Compute the verdict and forward it as
# HARNESS_WRAPPER_STATUS; `check_wrapper` surfaces it. A wrapper predating this
# does not set the var, and doctor uses its own container-presence to tell that
# stale wrapper from a native run with no wrapper at all. Emits one of:
#   symlink  — a symlink into the checkout; stays in lockstep on `git pull`
#   copy     — a byte-identical copy today, but it will silently rot
#   drifted  — a copy that has already fallen behind its versioned source
#   detached — a copy outside any checkout; no source tree to track (the real
#              ~/bin/harness deployment this ticket exists to catch)
_wrapper_status() {
  local invoked="${BASH_SOURCE[0]}"
  local versioned
  versioned="$(_wrapper_source_root)/docker/harness-wrapper.sh"
  if [[ ! -f "$versioned" ]]; then
    echo detached
  elif [[ -L "$invoked" ]]; then
    echo symlink
  elif cmp -s "$invoked" "$versioned"; then
    echo copy
  else
    echo drifted
  fi
}

# `docker image inspect` reports RFC3339 UTC with nanoseconds; git `%ct` reports
# epoch seconds. Normalise to epoch so neither timezone nor precision can skew
# the comparison (`stat -f %SB` prints local time — do not reach for it).
_rfc3339_to_epoch() {
  python3 -c '
import datetime, re, sys
s = sys.argv[1].strip().replace("Z", "+00:00")
s = re.sub(r"\.(\d{6})\d+", r".\1", s)
print(int(datetime.datetime.fromisoformat(s).timestamp()))
' "$1" 2>/dev/null
}

# Only guard the default tag. An explicit HARNESS_IMAGE is the caller's to
# manage: rebuilding a deliberately-pinned tag off this tree would clobber it.
if [[ "$IMAGE" == "$DEFAULT_IMAGE" ]]; then
  _source_root=$(_wrapper_source_root)
  # Advance the checkout BEFORE measuring it, so the comparison below reads the
  # ref the loop actually ships to (#286). `|| true` is load-bearing under
  # `set -euo pipefail`: no sync outcome may abort the wrapper.
  _sync_source_checkout "$_source_root" || true
  _image_created=$(docker image inspect "$IMAGE" --format '{{.Created}}' 2>/dev/null || true)
  _source_committed=$(git -C "$_source_root" log -1 --format=%ct -- harness/ 2>/dev/null || true)
  # Three cases, split so the middle one is reachable (CAL-1153):
  #   image + source present -> compare, and rebuild if stale (below).
  #   image present, source absent -> this wrapper is a detached COPY, not a
  #     symlink into its checkout, so there is no source tree to compare the
  #     image against and the guard cannot run. Warn once — do not fail: the verb
  #     still works, and refusing would break a working deployment for a guard
  #     that is only a convenience.
  #   image absent -> nothing to guard yet (about to build, or fails on its own
  #     terms). Stay a silent no-op.
  if [[ -n "$_image_created" && -n "$_source_committed" ]]; then
    _image_epoch=$(_rfc3339_to_epoch "$_image_created" || true)
    if [[ -n "${_image_epoch:-}" ]] && { [[ "$_source_committed" -gt "$_image_epoch" ]] || [[ "$_ff_touched_harness" -eq 1 ]]; }; then
      echo "harness: $IMAGE is stale — harness/ has moved since the image was built ($_image_created)." >&2
      echo "harness: rebuilding it now (docker build -t $IMAGE -f docker/Dockerfile . in $_source_root)" >&2
      if ! docker build -t "$IMAGE" -f "$_source_root/docker/Dockerfile" "$_source_root" >&2; then
        echo "harness: rebuild FAILED — refusing to run a stale $IMAGE." >&2
        echo "harness: a verb that shipped since $_image_created would be missing from it," >&2
        echo "harness: surfacing as \"No such command\". Fix the build, or rebuild by hand:" >&2
        echo "harness:   docker build -t $IMAGE -f docker/Dockerfile ." >&2
        exit 1
      fi
    fi
  elif [[ -n "$_image_created" && -z "$_source_committed" ]]; then
    echo "harness: image-freshness guard disabled — this wrapper is a detached copy, not a symlink into its checkout, so $IMAGE cannot be checked against its source and a stale image would run unguarded." >&2
    echo "harness: symlink it to restore the guard (see docker/README.md): ln -sf <repo>/docker/harness-wrapper.sh \"\$(command -v harness)\"" >&2
  fi
fi

# Pull LINEAR_API_KEY from the shell or a local .env file. The trailing `|| true`
# is load-bearing under `set -euo pipefail` (issue #171): when .env exists but has
# no matching line, `grep` exits 1 and the pipeline would abort the whole wrapper
# — so a repo whose .env omits this key (e.g. a github-only repo) could not run any
# verb. Guarded, a no-match yields an empty value and the container's own error (if
# the credential is genuinely required) reports it cleanly instead.
if [[ -z "${LINEAR_API_KEY:-}" && -f "$(pwd)/.env" ]]; then
  LINEAR_API_KEY=$(grep -E '^(export[[:space:]]+)?LINEAR_API_KEY=' "$(pwd)/.env" | head -1 | cut -d= -f2- | tr -d '\r' || true)
  export LINEAR_API_KEY
fi

# Pull GITHUB_TOKEN (the GitHub tracker backend's credential, CAL-1105) the same
# way — shell first, else a local .env — so a `tracker: github` repo authenticates
# inside the container exactly as `tracker: linear` does with LINEAR_API_KEY. The
# `|| true` is essential here (issue #171): removing the static token from .env
# (the intended #170 state) leaves .env with no GITHUB_TOKEN line, so an unguarded
# grep would abort the wrapper before the `gh auth token` fallback below runs.
if [[ -z "${GITHUB_TOKEN:-}" && -f "$(pwd)/.env" ]]; then
  GITHUB_TOKEN=$(grep -E '^(export[[:space:]]+)?GITHUB_TOKEN=' "$(pwd)/.env" | head -1 | cut -d= -f2- | tr -d '\r' || true)
  export GITHUB_TOKEN
fi

# Fresh-token fallback (issue #170). A `gh` OAuth token rotates (~8h) and `gh`
# auto-refreshes it from the keyring, so a *static* GITHUB_TOKEN (a `.env` snapshot
# or a stale exported value) goes stale — which silently breaks the UNATTENDED
# Build loop, where no human is present to refresh it. When the token is still
# unset and `gh` is logged in on the host, fetch a fresh one each invocation, the
# same way the Claude OAuth token is pulled from the Keychain above. Precedence is
# env → .env → gh, so a consuming repo's long-lived PAT in `.env` still wins.
if [[ -z "${GITHUB_TOKEN:-}" ]] && command -v gh >/dev/null 2>&1; then
  GITHUB_TOKEN=$(gh auth token 2>/dev/null || true)
  export GITHUB_TOKEN
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

# Allocate a TTY only for an interactive stdin. Built as an array so the empty
# case passes NO argument (an unquoted `$(…)` command substitution would word-split
# — shellcheck SC2046 — and a quoted "" would pass a bogus empty argument to
# `docker run`). Mirrors the SSH_AGENT_ARGS idiom above.
TTY_ARGS=()
if [[ -t 0 ]]; then
  TTY_ARGS=(-it)
fi

# PYTHONDONTWRITEBYTECODE=1 below is load-bearing, not hygiene (#278). The repo
# is bind-mounted read-write at /workspace, so any Python the container runs
# leaves `__pycache__/*.pyc` in the HOST tree whose embedded source paths are the
# container's. CPython validates a cache entry against the source's mtime and
# size, not its content, so the next host-side gate run loads those entries and
# anything using `inspect.getsource` / `linecache` fails with "could not get
# source code" — a false red on the gate that certifies a review. Pinned to the
# literal `1`, never forwarded as a bare `-e PYTHONDONTWRITEBYTECODE`: CPython
# treats only a NON-EMPTY value as on, so a host exporting it empty would
# silently disable the protection (the same reason HARNESS_WORKSPACE_ROOTS is
# pinned). It is set here rather than as a Dockerfile `ENV` because the staleness
# guard above compares the image against `git log -1 --format=%ct -- harness/` —
# a path a docker/-only change never touches — so an image-level default would
# not take effect until something unrelated forced a rebuild.
exec docker run --rm ${TTY_ARGS[@]+"${TTY_ARGS[@]}"} \
  -v "$(pwd)":/workspace \
  -w /workspace \
  -v "$HOME/.ssh":/home/harness/.ssh:ro \
  -v "$HOME/.codex":/home/harness/.codex:ro \
  ${SSH_AGENT_ARGS[@]+"${SSH_AGENT_ARGS[@]}"} \
  -e LINEAR_API_KEY \
  -e GITHUB_TOKEN \
  -e HARNESS_WORKSPACE_ROOTS=/workspace \
  -e PYTHONDONTWRITEBYTECODE=1 \
  -e "HARNESS_WRAPPER_STATUS=$(_wrapper_status)" \
  -e CLAUDE_CODE_OAUTH_TOKEN \
  -e CLAUDE_CODE_OAUTH_EXPIRES_AT \
  -e 'GIT_SSH_COMMAND=ssh -F /dev/null -o StrictHostKeyChecking=accept-new -o UserKnownHostsFile=/home/harness/.ssh/known_hosts' \
  -e "GIT_AUTHOR_NAME=$(git config --global user.name 2>/dev/null || echo 'Harness')" \
  -e "GIT_AUTHOR_EMAIL=$(git config --global user.email 2>/dev/null || echo 'harness@local')" \
  -e "GIT_COMMITTER_NAME=$(git config --global user.name 2>/dev/null || echo 'Harness')" \
  -e "GIT_COMMITTER_EMAIL=$(git config --global user.email 2>/dev/null || echo 'harness@local')" \
  "$IMAGE" \
  "$@"
