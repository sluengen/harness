#!/usr/bin/env bash
# Container entrypoint — one image, two entrypoints (decision #3, CAL-576/585).
#
# See specs/hermes-orchestration.md §Runtime topology → "Launch handle and
# decision record". A single image ships both runtime roles; the first argument
# selects which:
#
#   agent <TICKET> [extra…]   per-session agent runtime — drives the full verb
#                             loop headless (decision #2) via /harness run.
#   verb  <args…>             a single one-shot harness verb (start/review/close/…).
#
# Backward compatibility: when the first argument is neither `agent` nor `verb`,
# the whole argv is treated as a verb invocation. The CAL-579 launcher and the
# ~/bin/harness wrapper invoke `<image> start CAL-1 --repo …` directly, with no
# mode selector, and must keep working unchanged.
#
# harness runs as a one-shot process; the container exits when the role completes.
set -euo pipefail

mode="${1:-}"
case "$mode" in
  agent)
    shift
    ticket="${1:-}"
    if [[ -z "$ticket" ]]; then
      echo "harness entrypoint: agent mode requires a ticket id (agent <TICKET>)" >&2
      exit 2
    fi
    # Decision #1: the agent runtime holds the launcher control socket, never the
    # docker socket. Put a `harness` shim ahead on PATH that routes every verb
    # the /harness run loop issues (start/review/close/status/events/…) through
    # the socket client, so the loop spawns each verb as a one-shot sibling
    # *outside* this runtime without any docker authority here.
    shim_dir="$(mktemp -d)"
    cat > "$shim_dir/harness" <<'SHIM'
#!/usr/bin/env bash
exec uv run python -m harness.launcher_client "$@"
SHIM
    chmod +x "$shim_dir/harness"
    export PATH="$shim_dir:$PATH"
    # Decision #2: the autonomous path runs the agent runtime headless; Claude
    # Code drives start → implement → review* → close non-interactively.
    exec claude -p "/harness run $ticket"
    ;;
  verb)
    shift
    exec uv run harness "$@"
    ;;
  *)
    # Backward-compatible bare-verb form (launcher / ~/bin/harness wrapper).
    exec uv run harness "$@"
    ;;
esac
