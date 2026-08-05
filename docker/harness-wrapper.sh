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
# Resolved unconditionally: the host-environment helper below needs it to locate
# the harness package even when an explicit HARNESS_IMAGE skips the guard.
_source_root=$(_wrapper_source_root)

if [[ "$IMAGE" == "$DEFAULT_IMAGE" ]]; then
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

# Everything below here used to be this wrapper's real work: resolving
# credentials and git identity, then hand-rolling a `docker run` with a dozen
# mounts and `-e` flags. #307 moved both into `harness.hostenv`, which the
# control-socket client drives:
#
#   * `harness.hostenv.spawn` is the one home for container construction, shared
#     by `harness serve` and by the client's own fallback — two copies would be
#     two security postures, and the fallback runs on exactly the days the socket
#     is broken.
#   * Credentials are resolved per request by the host providers and handed to
#     docker through the subprocess `env=`. No credential value passes through
#     this shell any more, so the quoting, temp-file and NUL-record handling that
#     the `hostenv env` import needed is gone rather than made safe.
#
# What stays in shell, deliberately: the image-freshness guard and the
# source-checkout sync above. Their whole job includes detecting "this wrapper has
# no checkout behind it" (the detached-copy deployment, CAL-1153) — which is
# exactly the state in which checkout-resident Python cannot be imported. A guard
# that cannot fire in the deployment it was written for is not a guard.
#
# Interpreter ladder: an explicit override, then the checkout's own venv, then a
# bare `python3` pointed at the checkout. The venv step is load-bearing rather
# than defensive — macOS system `python3` is frequently 3.9, below what the
# package needs.
_HOST_PY=()
if [[ -n "${HARNESS_HOST_PYTHON:-}" ]]; then
  _HOST_PY=("$HARNESS_HOST_PYTHON")
elif [[ -n "${_source_root:-}" && -x "${_source_root:-}/.venv/bin/python" ]]; then
  _HOST_PY=("$_source_root/.venv/bin/python")
elif command -v python3 >/dev/null 2>&1; then
  _HOST_PY=(python3)
fi

# A hard stop, not a warning. Before #307 a missing interpreter cost only
# credential resolution and the wrapper still ran its own `docker run`; now the
# client *is* the runtime, so continuing would mean re-implementing container
# construction here — the second posture this rewire exists to delete. Failing
# with the fix in the message is the honest answer.
#
# Both failures are checked, because they are different deployments with the same
# remedy: no interpreter at all, and an interpreter that cannot import the package
# (the detached-copy install, CAL-1153, where there is no checkout to import from
# and no native `uv tool install` either). Left to `exec`, the second arrives as a
# bare ModuleNotFoundError naming neither the cause nor the fix.
_PY_HINT="set HARNESS_HOST_PYTHON to a Python 3.11+ interpreter with the harness package importable, or symlink this wrapper into its checkout (see docker/README.md)."
if [[ ${#_HOST_PY[@]} -eq 0 ]]; then
  echo "harness: no usable host Python found, and one is now required — the wrapper delegates to harness.hostenv.client, which builds and runs the verb container." >&2
  echo "harness: $_PY_HINT" >&2
  exit 1
fi
if ! PYTHONPATH="${_source_root:-}${PYTHONPATH:+:$PYTHONPATH}" \
  "${_HOST_PY[@]}" -c 'import harness.hostenv.client' 2>/dev/null; then
  echo "harness: ${_HOST_PY[*]} cannot import harness.hostenv.client, which the wrapper now delegates to." >&2
  echo "harness: $_PY_HINT" >&2
  exit 1
fi

# The status string is computed here because it describes *this wrapper* — whether
# it is a symlink into a checkout or a detached copy — which is knowable only from
# the shell that resolved it. The client reads it from the environment and pins it
# into the container by value.
export HARNESS_WRAPPER_STATUS="$(_wrapper_status)"

exec env PYTHONPATH="${_source_root:-}${PYTHONPATH:+:$PYTHONPATH}" \
  "${_HOST_PY[@]}" -m harness.hostenv.client "$(pwd)" -- "$@"
