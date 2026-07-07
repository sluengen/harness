#!/usr/bin/env bash
# Canonical verification gate — run before merging or tagging.
# All checks must pass; any failure exits immediately.
set -euo pipefail

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
