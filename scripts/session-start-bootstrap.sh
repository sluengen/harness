#!/usr/bin/env bash
# SessionStart hook entry point — registered only in this repo's own
# .claude/settings.json (`hooks.SessionStart`), never in the plugin's
# hooks/hooks.json: this is this repo's own cloud environment bootstrap, not
# a capability the harness plugin ships to repos that install it.
#
# `CLAUDE_CODE_REMOTE` is not a documented Claude Code interface (checked
# 2026-08-19: absent from the hooks/env-var reference, and absent from this
# repo's own env even in a session described as remote). It is used here
# anyway, on the operator's explicit call, in preference to auto-detecting
# "remote" some other way. Consequence accepted: if a future host does not
# set it, this hook stays a no-op everywhere, local and remote alike — the
# failure mode is silent inertness, not an unwanted local provisioning run.
[ "${CLAUDE_CODE_REMOTE:-}" = "true" ] || exit 0

exec bash "$(dirname "${BASH_SOURCE[0]}")/setup-cloud-env.sh"
