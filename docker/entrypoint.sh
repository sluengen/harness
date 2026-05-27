#!/usr/bin/env bash
# Container entrypoint — see SPEC §13.
# slate-harness runs as a one-shot process; the container exits when the workflow completes.
set -euo pipefail
exec uv run slate-harness "$@"
