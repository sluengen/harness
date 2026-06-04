#!/usr/bin/env bash
# Canonical verification gate — run before merging or tagging.
# All checks must pass; any failure exits immediately.
set -euo pipefail

echo "=== ruff ==="
uv run ruff check .

echo "=== mypy ==="
uv run mypy harness intake

echo "=== pytest ==="
uv run pytest --durations=20

echo "=== CLI smoke ==="
uv run harness version

echo "=== mock run ==="
uv run harness validate workflows/build.yaml

echo ""
echo "All checks passed."
