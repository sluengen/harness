#!/usr/bin/env bash
# Cloud environment bootstrap — provisions a bare checkout so it can run
# /build and /routine immediately: uv, a 3.11 interpreter, the dev toolchain,
# node, jq, and gh. Version-controlled, so a change here reaches every
# environment the next time it provisions, with no out-of-band configuration
# to keep in sync. Idempotent — safe to re-run against an already-provisioned
# host, including this one.
#
# Runs automatically in a remote/cloud session via the SessionStart hook in
# .claude/settings.json (scripts/session-start-bootstrap.sh gates it on
# CLAUDE_CODE_REMOTE). This script itself carries no such gate — it always
# runs when invoked directly, so it stays usable for manual provisioning or
# testing:
#
#   bash scripts/setup-cloud-env.sh
#
# Deliberately not `set -e`: a missing optional tool (gh, node) should not
# abort before the rest of the report prints. Failures are tracked in
# `status` and surfaced as a nonzero exit at the end instead.
set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT" || exit 1

status=0
warn() { echo "WARN: $*" >&2; }
fail() { echo "ERROR: $*" >&2; status=1; }
ok() { echo "OK: $*"; }

SUDO=""
if [ "$(id -u)" -ne 0 ] && command -v sudo >/dev/null 2>&1; then
  SUDO="sudo"
fi

install_node() {
  if command -v apt-get >/dev/null 2>&1; then
    $SUDO apt-get update -y && $SUDO apt-get install -y nodejs
  elif command -v dnf >/dev/null 2>&1; then
    $SUDO dnf install -y nodejs
  elif command -v apk >/dev/null 2>&1; then
    $SUDO apk add --no-cache nodejs
  elif command -v brew >/dev/null 2>&1; then
    brew install node
  else
    echo "no supported package manager found (apt-get/dnf/apk/brew)" >&2
    return 1
  fi
}

install_jq() {
  if command -v apt-get >/dev/null 2>&1; then
    $SUDO apt-get update -y && $SUDO apt-get install -y jq
  elif command -v dnf >/dev/null 2>&1; then
    $SUDO dnf install -y jq
  elif command -v apk >/dev/null 2>&1; then
    $SUDO apk add --no-cache jq
  elif command -v brew >/dev/null 2>&1; then
    brew install jq
  else
    echo "no supported package manager found (apt-get/dnf/apk/brew)" >&2
    return 1
  fi
}

install_gh() {
  # apt's default repos don't reliably carry a current `gh` package, so this
  # follows GitHub's own recipe (add the keyring, add the apt source, install)
  # rather than a plain `apt-get install gh` that may 404 or install stale.
  if command -v apt-get >/dev/null 2>&1; then
    $SUDO mkdir -p -m 755 /etc/apt/keyrings
    curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg \
      | $SUDO tee /etc/apt/keyrings/githubcli-archive-keyring.gpg >/dev/null
    $SUDO chmod go+r /etc/apt/keyrings/githubcli-archive-keyring.gpg
    $SUDO mkdir -p -m 755 /etc/apt/sources.list.d
    echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" \
      | $SUDO tee /etc/apt/sources.list.d/github-cli.list >/dev/null
    $SUDO apt-get update -y && $SUDO apt-get install -y gh
  elif command -v dnf >/dev/null 2>&1; then
    $SUDO dnf install -y 'dnf-command(config-manager)' || true
    $SUDO dnf config-manager --add-repo https://cli.github.com/packages/rpm/gh-cli.repo || true
    $SUDO dnf install -y gh
  elif command -v apk >/dev/null 2>&1; then
    $SUDO apk add --no-cache github-cli
  elif command -v brew >/dev/null 2>&1; then
    brew install gh
  else
    echo "no supported package manager found (apt-get/dnf/apk/brew)" >&2
    return 1
  fi
}

echo "=== harness cloud environment setup ==="
echo "repo: $REPO_ROOT"

# --- uv — the gate (scripts/verify.sh) and the dev toolchain run entirely
# through `uv run --extra dev` / `uv sync --extra dev`. -----------------------
if ! command -v uv >/dev/null 2>&1; then
  echo "--- installing uv ---"
  if command -v curl >/dev/null 2>&1; then
    curl -LsSf https://astral.sh/uv/install.sh | sh
    export PATH="$HOME/.local/bin:$PATH"
  else
    warn "no curl — cannot run the uv installer"
  fi
fi
if command -v uv >/dev/null 2>&1; then
  ok "uv $(uv --version)"
else
  fail "uv is not on PATH — see https://docs.astral.sh/uv/getting-started/installation/"
fi

# --- python 3.11+ (pyproject.toml: requires-python >=3.11). uv manages its
# own interpreter, so this does not depend on whatever `python3` the host
# ships (often older — 3.9 on this host at time of writing). -----------------
if command -v uv >/dev/null 2>&1; then
  uv python install 3.11 || fail "uv python install 3.11 failed"
fi

# --- dev toolchain: pytest, pytest-cov, pytest-xdist, pytest-timeout, ruff,
# mypy (pyproject.toml [project.optional-dependencies].dev). Pre-installing
# here means the first `/build` run doesn't pay this cost mid-gate. -----------
if command -v uv >/dev/null 2>&1; then
  echo "--- uv sync --extra dev ---"
  uv sync --extra dev || fail "uv sync --extra dev failed"
fi

# --- git — worktree-isolation and every branch operation need it. No
# reasonable cloud sandbox lacks it, so this checks rather than installs. -----
if command -v git >/dev/null 2>&1; then
  ok "git $(git --version | awk '{print $3}')"
else
  fail "git is not installed — required for worktree isolation and every branch operation"
fi

# --- node — the gate's own suite exercises the enforcement/advisory hooks
# (.claude/hooks/*.js) under node, and verify.sh's preflight refuses to run
# (exit 97) without it (#478): a gate that can't see node silently skips the
# hook tests rather than failing, so the preflight exists to catch that. ------
if ! command -v node >/dev/null 2>&1; then
  echo "--- installing node ---"
  install_node || warn "automatic node install failed — install manually: https://nodejs.org/"
fi
if command -v node >/dev/null 2>&1; then
  ok "node $(node --version)"
else
  fail "node is not installed — scripts/verify.sh's preflight refuses to run without it"
fi

# --- jq — the promotion guards evaluate scripts/promotion-step.sh's `--jq`
# programs with a real engine, so jq is a gate dependency under the same rule
# node is (#491: a binary belongs in the preflight exactly when a test resolves
# it off PATH). verify.sh's preflight refuses to run (exit 97) without it. -----
if ! command -v jq >/dev/null 2>&1; then
  echo "--- installing jq ---"
  install_jq || warn "automatic jq install failed — install manually: https://jqlang.github.io/jq/"
fi
if command -v jq >/dev/null 2>&1; then
  ok "jq $(jq --version)"
else
  fail "jq is not installed — scripts/verify.sh's preflight refuses to run without it"
fi

# --- gh — harness.yaml declares tracker: github; /build and /routine read and
# write tickets through it via the `tracker` skill. Not required for the
# verify gate itself, so its absence is a warning, not a failure. ------------
if ! command -v gh >/dev/null 2>&1; then
  echo "--- installing gh ---"
  install_gh || warn "automatic gh install failed — install manually: https://cli.github.com/"
fi
if command -v gh >/dev/null 2>&1; then
  ok "gh $(gh --version | head -1)"
  if gh auth status >/dev/null 2>&1; then
    ok "gh is authenticated"
  else
    warn "gh is installed but not authenticated — /build and /routine need it for tracker: github. Run 'gh auth login', or set GITHUB_TOKEN / GH_TOKEN."
  fi
else
  warn "gh is not installed — needed for tracker: github ticket read/write, not for the verify gate itself"
fi

# --- readiness check — the same preconditions scripts/verify.sh's own
# preflight asserts, run here so a provisioning failure surfaces at setup
# time instead of on the first /build's gate. ---------------------------------
if command -v uv >/dev/null 2>&1; then
  echo "--- readiness check ---"
  for tool in ruff mypy pytest; do
    if uv run --extra dev "$tool" --version >/dev/null 2>&1; then
      ok "$tool runnable under uv run --extra dev"
    else
      fail "$tool is not runnable under 'uv run --extra dev'"
    fi
  done
  if uv run --extra dev python -c "import xdist" >/dev/null 2>&1; then
    ok "pytest-xdist importable"
  else
    fail "pytest-xdist is not importable under 'uv run --extra dev'"
  fi
fi

echo ""
if [ "$status" -eq 0 ]; then
  echo "=== setup complete — run 'bash scripts/verify.sh' to confirm the gate is green ==="
else
  echo "=== setup finished with errors — see ERROR lines above ==="
fi
exit "$status"
