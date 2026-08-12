#!/usr/bin/env bash
# The nightly `dev -> staging` promotion, as one shell.
#
# It lives here rather than inside the workflow's `run:` block so a test can
# *execute* it against stubbed verbs instead of reading its text
# (specs/architecture-principles.md -> "CI logic lives in a script, not in a
# `run:` block"; specs/proposals/promotion-guard-instrument.md). The executing
# guard is tests/integration/test_promotion_step_script.py.
#
# Extracting the shell split which ref supplies it, so note where each half comes
# from. GitHub reads a scheduled workflow from the default branch (`main`), while
# `actions/checkout` fills $GITHUB_WORKSPACE from `ref: dev` and a `run:` step's
# working directory is that checkout — so `main`'s workflow invokes `dev`'s copy
# of this file, where the inline block it replaced came wholly from `main`. A
# change here therefore reaches the next nightly as soon as it lands on `dev`,
# rather than waiting to be promoted the rest of the way.
#
# Two environment inputs, both supplied by Actions and both required:
# GITHUB_WORKSPACE (the checkout, and the one allowlisted root) and RUNNER_TEMP.
# `set -u` aborts before any verb runs if either is missing, which is the
# fail-closed direction.
set -euo pipefail

# Every verb resolves `--repo` through the HARNESS_WORKSPACE_ROOTS allowlist,
# which fails closed: unset means no allowed roots, so the verb refuses the path
# with exit 2 before it does anything. The Docker wrapper (~/bin/harness) pins
# that allowlist for a developer; a runner has no wrapper, so the job pins it
# here, once, for all three calls.
export HARNESS_WORKSPACE_ROOTS="$GITHUB_WORKSPACE"

promotion_json="$RUNNER_TEMP/promotion.json"
uv run harness promote start --repo "$GITHUB_WORKSPACE" --from dev --to staging > "$promotion_json"

promotion_id="$(python -c 'import json, sys; print(json.load(open(sys.argv[1]))["promotion_id"])' "$promotion_json")"
status="$(python -c 'import json, sys; print(json.load(open(sys.argv[1]))["status"])' "$promotion_json")"
if [ "$status" != "gate_pending" ]; then
  cat "$promotion_json"
  echo "::error::Promotion $promotion_id stopped at $status; no automated repair is permitted."
  exit 1
fi

worktree="$(python -c 'import json, sys; print(json.load(open(sys.argv[1]))["worktree_path"])' "$promotion_json")"
gate_log="$RUNNER_TEMP/promotion-gate-$promotion_id.log"
set +e
(
  cd "$worktree"
  bash scripts/verify.sh
) > "$gate_log" 2>&1
gate_exit=$?
set -e

uv run harness promote continue --repo "$GITHUB_WORKSPACE" --promotion-id "$promotion_id" \
  --gate-exit "$gate_exit" --gate-log "$gate_log" > "$promotion_json"
status="$(python -c 'import json, sys; print(json.load(open(sys.argv[1]))["status"])' "$promotion_json")"
if [ "$status" != "pr_ready" ]; then
  cat "$promotion_json"
  echo "::error::Promotion $promotion_id stopped at $status; staging was not advanced."
  exit 1
fi

uv run harness promote pr --repo "$GITHUB_WORKSPACE" --promotion-id "$promotion_id"
