#!/usr/bin/env bash
# Canonical verification gate — run before merging or tagging.
# All checks must pass; any failure exits immediately.
set -euo pipefail

# Toolchain preflight (CAL-1160). The checks below need ruff, mypy, and pytest
# runnable under `uv run --extra dev`. If the toolchain cannot even launch (a
# missing tool, a broken venv — infrastructure, not a red tree; the observed live
# failure was `error: Failed to spawn: ruff`), exit with a reserved code distinct
# from a red tree, so a caller can tell "the gate could not run" from "the gate
# ran and the tree is red". A red tree still exits the tool's own non-zero
# code (1).
GATE_UNRUNNABLE_EXIT=97
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
# `scripts` is the only Python tree left: v5 chunk 3 moved the Codex compile
# step out of `templates/`, which now holds markdown templates alone.
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

echo "=== codex drift guard ==="
# Fail the gate if the committed AGENTS.md or .codex/ has drifted from a
# regeneration off CLAUDE.md, agents/, commands/, and skills/ — the Codex
# surface is compiled, never hand-edited (ADR 0017; v5 chunk 3).
uv run --extra dev python scripts/generate_codex_artifacts.py --check

echo "=== gate marker ==="
# Record that the gate exited 0 over *these exact bytes* (#436). The marker is
# named after the git tree object of this working tree and lives in the git
# common directory, so it cannot be swept into the tree it records. Two hooks
# read it: the Stop hook refuses a completion claim over a tree no marker
# covers, and the push guard refuses a push to a protected branch carrying one.
# Last, because `set -e` is what makes "after every stage" mean "only on green".
uv run --extra dev python scripts/gate_marker.py write

echo ""
echo "All checks passed."
