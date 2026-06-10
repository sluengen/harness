#!/usr/bin/env bash
# Canonical verification gate — run before merging or tagging.
# All checks must pass; any failure exits immediately.
set -euo pipefail

echo "=== ruff ==="
uv run --extra dev ruff check .

echo "=== mypy ==="
uv run --extra dev mypy harness intake

echo "=== pytest ==="
uv run --extra dev pytest --durations=20

echo "=== CLI smoke ==="
uv run --extra dev python -m harness.cli version
uv run --extra dev python -m harness.cli --help >/dev/null

echo ""
echo "All checks passed."
