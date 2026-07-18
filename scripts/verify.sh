#!/usr/bin/env bash
# Canonical verification gate — run before merging or tagging.
# All checks must pass; any failure exits immediately.
set -euo pipefail

# Toolchain preflight (CAL-1160). The checks below need ruff, mypy, and pytest
# runnable under `uv run --extra dev`. If the toolchain cannot even launch (a
# missing tool, a broken venv — infrastructure, not a red tree; the observed live
# failure was `error: Failed to spawn: ruff`), exit with the reserved code the
# promotion gate maps to `blocked` rather than `needs_ticket`, so `promote
# escalate` does not file a false Linear ticket blaming the code. A red tree still
# exits the tool's own non-zero code (1). Keep this literal in sync with
# harness.gate.GATE_UNRUNNABLE_EXIT (test_verify_gate_unrunnable locks them).
GATE_UNRUNNABLE_EXIT=97
for _tool in ruff mypy pytest; do
  if ! uv run --extra dev "$_tool" --version >/dev/null 2>&1; then
    echo "gate precondition failed: '$_tool' is not runnable under 'uv run --extra dev' — toolchain unavailable (infrastructure, not a code failure)" >&2
    exit "$GATE_UNRUNNABLE_EXIT"
  fi
done

echo "=== ruff ==="
uv run --extra dev ruff check .

echo "=== mypy ==="
uv run --extra dev mypy harness

echo "=== pytest ==="
# --cov-fail-under enforces the coverage floor: the gate fails if line coverage
# of the harness package drops below 90% (baseline 91%, 2026-07-06). CAL-1015.
uv run --extra dev pytest --durations=20 --cov=harness --cov-fail-under=90

echo "=== CLI smoke ==="
uv run --extra dev python -m harness.cli version
uv run --extra dev python -m harness.cli --help >/dev/null

echo ""
echo "All checks passed."
