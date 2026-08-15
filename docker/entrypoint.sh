#!/usr/bin/env bash
# Container entrypoint — one harness verb, or the client installer.
#
# Two roles:
#
#   install [--source-root <abs path>]  emit the ~/bin/harness client on stdout
#   verb <args…> / <args…>              run one audited verb (start/review/…)
#
# The verb role is the original and is unchanged: an explicit `verb` selector is
# a token this script *strips*, and with no selector the whole argv is treated as
# a verb invocation, so the wrapper keeps working exactly as before. `install`
# (#312) is therefore the first real branch here, and it is deliberately placed
# ahead of the strip so that neither role can shadow the other.
#
# `install` is what closes #286's bootstrap case: the client is emitted from the
# image, so updating it needs neither a checkout, nor a network, nor the previous
# client. `exec` rather than a call, so the producer's own exit code and its
# refusals reach the operator unaltered — an install that produced no client must
# never report success. The producer is resolved beside this script (both land in
# /opt/harness/), which also makes the role reachable from the checkout, where the
# host-side tests execute the same two files.
#
# (The launcher-socket `agent` mode for an autonomous per-session runtime was the
# deferred Hermes-dispatch scaffolding, removed in CAL-712 — see
# specs/retired/hermes-orchestration.md.)
#
# harness runs as a one-shot process; the container exits when the verb completes.
set -euo pipefail

if [[ "${1:-}" == "install" ]]; then
  shift
  exec "$(cd -P "$(dirname "${BASH_SOURCE[0]}")" && pwd)/install-client.sh" "$@"
fi

if [[ "${1:-}" == "verb" ]]; then
  shift
fi
exec uv run harness "$@"
