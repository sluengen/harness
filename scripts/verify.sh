#!/usr/bin/env bash
# Canonical verification gate — run before merging or tagging.
# All checks must pass; any failure exits immediately.
set -euo pipefail

# The public gate delegates marker ownership to the fixed Node runner.  The
# runner re-enters this script in internal mode after it has established the
# boundary that only a measured successful run may create evidence.
if [ "${HARNESS_GATE_MARKER_RUNNER:-}" != "1" ]; then
  exec node scripts/gate-marker.js run
fi

# Toolchain preflight (CAL-1160). The checks below need ruff, mypy, and pytest
# runnable under `uv run --extra dev`. If the toolchain cannot even launch (a
# missing tool, a broken venv — infrastructure, not a red tree; the observed live
# failure was `error: Failed to spawn: ruff`), exit with a reserved code distinct
# from a red tree, so a caller can tell "the gate could not run" from "the gate
# ran and the tree is red". A red tree still exits the tool's own non-zero
# code (1).
GATE_UNRUNNABLE_EXIT=97

# The host binaries the suite resolves off PATH (#478 for node; #491 for the
# rule and the rest). The membership rule is recorded in
# specs/architecture-principles.md -> "The gate's toolchain preflight probes
# what the suite resolves off PATH": a binary belongs here exactly when a test
# resolves it with shutil.which at run time. That set is *derived* from the
# tracked test sources by tests/unit/_toolchain.py and held against this list in
# both directions by tests/unit/test_verify_toolchain_preflight.py, which
# executes this script under a stubbed PATH rather than reading its text — so
# adding a resolution to the suite without a probe here fails, and a probe here
# for a binary no test resolves fails too.
#
# Why resolution and not spawning: a binary the suite spawns by name is absent
# *loudly* (FileNotFoundError, a red test), while a binary it resolves and skips
# on is absent *invisibly* — the gate then writes a marker claiming a tree
# verified while the guards the marker exists to serve never ran. Same reserved
# code as the probes below: this is the toolchain, not the tree.
#
#   node — the suite executes the enforcement and advisory hooks (hooks/*.js)
#          under it and skips those tests without it (#478: a node linked
#          against a moved soname turned a green tree into 51 failures plus a
#          collection error, mid-review).
#   git  — the Stop-hook scope guard resolves it to build a spawn-counting shim.
#   jq   — the promotion guards evaluate scripts/promotion-step.sh's three
#          `--jq` programs with a real engine, instead of asserting pre-filtered
#          fixture text past them (#491).
#
# This loop runs FIRST since #500, and the reason is the preflight below it: that
# preflight is now itself a `node` invocation, so node's runnability has to be
# established before it. A node that is present and unrunnable — the #478 shape —
# would otherwise make the preflight exit non-zero on account of the runtime
# rather than the repository, and the wrapper below has only that exit code to
# go on: it would report the helper, never node, at the one moment an operator
# acts on it. These are `--version` probes, not stages: everything
# expensive still runs under `uv`, below the preflight.
for _tool in node git jq; do
  if ! "$_tool" --version >/dev/null 2>&1; then
    echo "gate precondition failed: '$_tool' is not runnable — the suite resolves it off PATH and skips or degrades without it, so a gate without $_tool verifies a tree minus the guards that need it (toolchain unavailable, not a code failure)" >&2
    exit "$GATE_UNRUNNABLE_EXIT"
  fi
done

# A registered worktree nested below this checkout is safe only when Git
# ignores it. Otherwise every temp-index `git add -A` can absorb the agent's
# whole checkout and certify a tree nobody intended to ship (#494 / ERP-349).
# This is an infrastructure precondition and runs before every expensive stage.
#
# The diagnostic splits on the helper's exit code (#500), because one message for
# two causes is a false claim about whichever cause it does not describe: exit 2
# is the helper reporting a fact about the repository, and any other non-zero
# means the helper could not run at all. Written as `|| _preflight_status=$?` so
# the status is both captured and protected from `set -e`.
#
# Exit 2 covers every refusal the helper reports — git failed, there is no
# repository, a nested worktree is visible, an indeterminate check-ignore — and
# this wrapper cannot tell them apart from the code alone. It therefore points at
# the helper's own message, which named the cause on the line above, and offers
# the nested-worktree remedy conditionally rather than asserting that cause.
_preflight_status=0
node scripts/gate-marker.js preflight || _preflight_status=$?
if [ "$_preflight_status" -eq 2 ]; then
  echo "gate precondition failed: the gate-marker preflight refused — the cause is in its message above; if that names a registered nested worktree visible to git, ignore .worktrees/ and .claude/worktrees/ before verification (infrastructure, not a code failure)" >&2
  exit "$GATE_UNRUNNABLE_EXIT"
elif [ "$_preflight_status" -ne 0 ]; then
  echo "gate precondition failed: the gate-marker helper could not run ('node scripts/gate-marker.js preflight' exited $_preflight_status) — infrastructure, not a code failure" >&2
  exit "$GATE_UNRUNNABLE_EXIT"
fi

for _tool in ruff mypy pytest; do
  if ! uv run --extra dev "$_tool" --version >/dev/null 2>&1; then
    echo "gate precondition failed: '$_tool' is not runnable under 'uv run --extra dev' — toolchain unavailable (infrastructure, not a code failure)" >&2
    exit "$GATE_UNRUNNABLE_EXIT"
  fi
done

# `-n` is pytest-xdist's flag (#358). Without the plugin installed pytest exits 4
# (usage error) — indistinguishable from a red tree to anything reading only the
# exit code. A venv predating the parallel gate is infrastructure, not a code
# failure, so it gets the same reserved code as a missing ruff/mypy/pytest
# above. Probed by import rather than by `pytest --help`, so the answer does not
# depend on parsing help text.
if ! uv run --extra dev python -c "import xdist" >/dev/null 2>&1; then
  echo "gate precondition failed: 'pytest-xdist' is not importable under 'uv run --extra dev' — run 'uv sync --extra dev' (toolchain unavailable, not a code failure)" >&2
  exit "$GATE_UNRUNNABLE_EXIT"
fi

echo "=== ruff ==="
uv run --extra dev ruff check .

echo "=== mypy ==="
# `scripts` is the only Python tree left, and smaller since #537 retired the
# Codex compile step entirely; `templates/` holds markdown and yaml templates.
uv run --extra dev mypy scripts

echo "=== pytest ==="
# One stage, across the host's cores. The two-stage `-m docker` / `-m "not
# docker"` partition went with the container (#435): every docker-marked test
# built and ran the `harness:test` image, and no surviving test spawns a
# process, opens SQLite or drives a CLI. HARNESS_TEST_WORKERS overrides the
# worker count; unset, xdist's `auto` derives it from the host. Set it to 0 to
# run in the controller when reproducing an order-dependence failure.
#
# Coverage measures `scripts/` — the only executable code the repo still owns.
# The floor is set just under the measured value at the time of the teardown
# and is a ratchet, not a target: raise it when coverage rises, and treat a drop
# below it as the regression it is.
uv run --extra dev pytest -n "${HARNESS_TEST_WORKERS:-auto}" --durations=20 --cov=scripts --cov-fail-under=82

echo "=== design-token drift guard ==="
# Fail the gate if docs/index.html's generated :root block has drifted from
# design/03-tokens/tokens.json — the source of truth (#242). ADR 0004,
# narrowed (#243): the guidance catalog above stays guarded and hand-authored;
# this block is mechanical, generated content instead.
uv run --extra dev python scripts/build_design_tokens.py --check

echo ""
echo "All checks passed."
