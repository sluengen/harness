#!/usr/bin/env bash
# Canonical verification gate — run before merging or tagging.
# All checks must pass; any failure exits immediately.
set -euo pipefail

# This repository's own gate, declared at `commands.verify` in `harness.yaml` and
# run directly. #621 removed the Node runner this script used to `exec` into: the
# runner existed to write a marker naming the tree it had verified, and ADR 0022
# retires that whole complex — a plugin-shipped executable reads what *is*, never
# what *passed*.
#
# So this script runs stages and exits, and it writes no evidence. The claim a
# green run licenses is law 3's, held by the builder who ran it and read it, not
# by a token left on disk for a later hook to find. Nothing may infer
# authorisation from the fact that this script once exited zero.

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
# on is absent *invisibly* — the run then reports green over a suite that
# silently dropped every guard needing that binary, and green is what the builder
# reads law 3's claim off. Same reserved code as the probes below: this is the
# toolchain, not the tree.
#
#   node — the suite executes the enforcement and advisory hooks (hooks/*.js)
#          under it and skips those tests without it (#478: a node linked
#          against a moved soname turned a green tree into 51 failures plus a
#          collection error, mid-review).
#   jq   — the promotion guards evaluate scripts/promotion-step.sh's three
#          `--jq` programs with a real engine, instead of asserting pre-filtered
#          fixture text past them (#491).
#
# `git` left this list at #621. It was here for the Stop-hook scope guard, which
# resolved it to build a spawn-counting shim; that hook and its guard are gone,
# and no surviving test resolves git off PATH. The derivation above is what said
# so — a probe for a binary no test resolves fails this list in the second
# direction, which is the half that keeps it from accreting.
#
# This loop runs FIRST, and since #621 removed the node preflight it used to
# guard, the surviving reason is #478 on its own: a node that is present but
# unrunnable turned a green tree into 51 failures plus a collection error,
# mid-review, because the suite executes the hooks under it. Establishing that
# here reports the runtime once, plainly, instead of as a wall of red tests.
# These are `--version` probes, not stages: everything expensive runs under `uv`
# below.
for _tool in node jq; do
  if ! "$_tool" --version >/dev/null 2>&1; then
    echo "gate precondition failed: '$_tool' is not runnable — the suite resolves it off PATH and skips or degrades without it, so a gate without $_tool verifies a tree minus the guards that need it (toolchain unavailable, not a code failure)" >&2
    exit "$GATE_UNRUNNABLE_EXIT"
  fi
done

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
# The floor is set just under the measured value and is a ratchet, not a target:
# raise it when coverage rises, and treat a drop below it as the regression it
# is. #621 raised it 82 -> 85: deleting the marker helper and the landing pair
# removed 1,000-odd lines whose coverage was dragging the ratio down, and the
# measured value moved to 85.31%. Leaving the floor at 82 after that would have
# banked three points of slack the tree no longer needs.
uv run --extra dev pytest -n "${HARNESS_TEST_WORKERS:-auto}" --durations=20 --cov=scripts --cov-fail-under=85

echo "=== design-token drift guard ==="
# Fail the gate if docs/index.html's generated :root block has drifted from
# design/03-tokens/tokens.json — the source of truth (#242). ADR 0004,
# narrowed (#243): the guidance catalog above stays guarded and hand-authored;
# this block is mechanical, generated content instead.
uv run --extra dev python scripts/build_design_tokens.py --check

echo ""
echo "All checks passed."
