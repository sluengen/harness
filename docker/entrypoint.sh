#!/usr/bin/env bash
# Container entrypoint — a single one-shot harness verb.
#
# The image runs one audited verb per container (start/review/close/status/…),
# exactly as the ~/bin/harness wrapper invokes `<image> start CAL-1 --repo …`.
# An explicit `verb` selector is accepted for symmetry; with no selector the
# whole argv is treated as a verb invocation, so the wrapper keeps working
# unchanged.
#
# (The launcher-socket `agent` mode for an autonomous per-session runtime was the
# deferred Hermes-dispatch scaffolding, removed in CAL-712 — see
# specs/retired/hermes-orchestration.md.)
#
# harness runs as a one-shot process; the container exits when the verb completes.
set -euo pipefail

if [[ "${1:-}" == "verb" ]]; then
  shift
fi
exec uv run harness "$@"
