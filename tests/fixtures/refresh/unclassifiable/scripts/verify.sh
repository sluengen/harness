#!/usr/bin/env bash
# Synthetic fixture (tests/fixtures/refresh/MANIFEST.md documents it as such).
# Five distinguishable HARNESS_GATE_MARKER_RUNNER sites, lettered (a)-(e) to
# match the manifest's notes. Site (e) is the one ordinary top-level guard
# that must be rewritten; (a)-(d) must be reported and left.
set -euo pipefail

# (a) inside a shell function body — the caller that reaches this comparison
# is consumer-owned, so this step never opens it.
check_runner() {
  if [ "${HARNESS_GATE_MARKER_RUNNER:-}" = "1" ]; then
    echo "internal path (function)"
  fi
}

# (b) compared against another variable, not the literal 1.
expected_runner="1"
if [ "${HARNESS_GATE_MARKER_RUNNER:-}" = "$expected_runner" ]; then
  echo "internal path (variable comparison)"
fi

# (c) a case statement.
case "${HARNESS_GATE_MARKER_RUNNER:-}" in
  1)
    echo "internal path (case)"
    ;;
esac

# (d) an assignment, then a later test of the assigned variable.
MODE="${HARNESS_GATE_MARKER_RUNNER:-0}"
# ... later ...
if [ "$MODE" = "1" ]; then
  echo "internal path (assigned variable)"
fi

# (e) an ordinary top-level public-path guard — must be rewritten to
# [ -z "${HARNESS_GATE_MARKER_RUNNER:-}" ].
if [ "${HARNESS_GATE_MARKER_RUNNER:-}" != "1" ]; then
  exec node scripts/gate-marker.js run
fi

node scripts/gate-marker.js preflight
echo "internal stages would run here"
