#!/usr/bin/env bash
# The nightly `dev -> staging` promotion, as one shell.
#
# It lives here rather than inside the workflow's `run:` block so a test can
# *execute* it against stubbed git instead of reading its text
# (specs/architecture-principles.md -> "CI logic lives in a script, not in a
# `run:` block"). The executing guard is
# tests/unit/test_promotion_step_script.py.
#
# Extracting the shell split which ref supplies it, so note where each half comes
# from. GitHub reads a scheduled workflow from the default branch (`main`), while
# `actions/checkout` fills $GITHUB_WORKSPACE from `ref: dev` and a `run:` step's
# working directory is that checkout — so `main`'s workflow invokes `dev`'s copy
# of this file, where the inline block it replaced came wholly from `main`. A
# change here therefore reaches the next nightly as soon as it lands on `dev`,
# rather than waiting to be promoted the rest of the way.
#
# ADR 0015 retires the `harness promote` verb, not the promotion. The topology
# (`dev -> staging -> main`) and this nightly automation are kept by decision;
# what the verb used to supply — a ledgered candidate, a `HARNESS_WORKSPACE_ROOTS`
# allowlist, a five-state machine, a bounded repair — is gone, and the properties
# that actually matter are re-expressed in plain git below:
#
#   * the gate decides, and only a green gate advances the branch;
#   * nothing is ever repaired, merged or forced — the job stops and reports;
#   * the ref moves only as a fast-forward, checked here and again by the server.
#
# Two environment inputs, both supplied by Actions and both required:
# GITHUB_WORKSPACE (the checkout the gate runs in) and RUNNER_TEMP (where the
# gate log is captured). They are asserted below before anything mutates, which
# is the fail-closed direction; `set -u` is the backstop, not the check.
set -euo pipefail

: "${GITHUB_WORKSPACE:?the promotion step needs GITHUB_WORKSPACE (the checkout to gate and promote)}"
: "${RUNNER_TEMP:?the promotion step needs RUNNER_TEMP (where the gate log is captured)}"

#: The hop. Named rather than inlined so the two branches appear once each and
#: the ::error:: annotations can say which ref stalled.
SOURCE_BRANCH="dev"
TARGET_BRANCH="staging"

cd "$GITHUB_WORKSPACE"

candidate="$(git rev-parse HEAD)"

# The gate's exit code is *observed*, never rounded. `set +e` around it only so a
# red gate reaches the report below instead of aborting the script anonymously;
# `set -e` is restored immediately after.
gate_log="$RUNNER_TEMP/promotion-gate-$candidate.log"
set +e
bash scripts/verify.sh > "$gate_log" 2>&1
gate_exit=$?
set -e

if [ "$gate_exit" -ne 0 ]; then
  tail -n 40 "$gate_log"
  echo "::error::The gate exited $gate_exit on $SOURCE_BRANCH@$candidate; $TARGET_BRANCH was not advanced. No automated repair is permitted."
  exit 1
fi

# A fast-forward, or nothing. Checked here so the refusal names the reason; the
# plain (unforced) push below refuses the same case server-side, which is the
# guard that holds if this branch is ever edited away. A target that does not yet
# exist is created by the push, so the ancestry check is skipped rather than
# failing on an unknown ref.
if git ls-remote --exit-code --heads origin "$TARGET_BRANCH" >/dev/null 2>&1; then
  git fetch --no-tags --quiet origin "+refs/heads/$TARGET_BRANCH:refs/remotes/origin/$TARGET_BRANCH"
  if ! git merge-base --is-ancestor "refs/remotes/origin/$TARGET_BRANCH" "$candidate"; then
    echo "::error::$TARGET_BRANCH holds commits $SOURCE_BRANCH@$candidate does not contain, so advancing it would not be a fast-forward; $TARGET_BRANCH was not advanced. The nightly never merges or forces — resolve it by hand."
    exit 1
  fi
fi

git push origin "$candidate:refs/heads/$TARGET_BRANCH"
echo "Promoted $SOURCE_BRANCH@$candidate to $TARGET_BRANCH."
