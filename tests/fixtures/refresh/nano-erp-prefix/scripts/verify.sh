#!/usr/bin/env bash
# The canonical verification gate — the public entry point `npm run verify` runs.
#
# Two branches on one variable, and the runner owns the mint (ERP-456).
#
# PUBLIC (guard unset): build, then hand the gate to the managed runner. The
# runner resolves `commands.verify` through `harness-config.js`, whose source
# order is harness.yaml, AGENTS.md, CLAUDE.md, CONTEXT.md — so it reads
# `harness.yaml`'s "npm run verify" and spawns it with
# HARNESS_GATE_MARKER_RUNNER=1, which lands back here on the internal branch.
# Configuration is not restated in the spine for this: harness.yaml already
# declares it, and a second copy would be a second source of truth.
#
# INTERNAL (guard = 1): the eight stages, and nothing else. This branch never
# writes a marker — only `gate-marker.js run` does, after it has measured the
# status of what it spawned, and it is unreachable from here. That is the whole
# of the boundary ERP-377 established and this change preserves: evidence comes
# from a measured green, never from being reached at the end of an && chain.
#
# The build runs on the public branch because the stages need `dist/`
# (`test:compiled` runs from it), and `dist/` is gitignored, so it cannot
# perturb the oid the marker is named after.
#
# The runner captures this script with spawnSync and no maxBuffer, so nothing
# printed below appears until the gate exits, and output above ~1 MB is
# truncated and misreported as "could not launch declared gate". That is an
# accepted limitation, recorded in specs/features/gate-enforcement.md rather
# than worked around here — a bound imposed on this side would buy headroom
# without restoring the streaming, which is the half that costs every run.
set -euo pipefail

if [ "${HARNESS_GATE_MARKER_RUNNER:-}" != "1" ]; then
  npm run build
  exec node scripts/gate/gate-marker.js run
fi

npm run verify:stages
