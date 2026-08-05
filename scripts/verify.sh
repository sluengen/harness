#!/usr/bin/env bash
# Canonical verification gate — run before merging or tagging.
# All checks must pass; any failure exits immediately.
set -euo pipefail

# Toolchain preflight (CAL-1160). The checks below need ruff, mypy, and pytest
# runnable under `uv run --extra dev`. If the toolchain cannot even launch (a
# missing tool, a broken venv — infrastructure, not a red tree; the observed live
# failure was `error: Failed to spawn: ruff`), exit with the reserved code the
# promotion gate maps to `blocked` rather than `needs_ticket`, so `promote
# escalate` does not file a false Linear ticket blaming the code. A red tree still
# exits the tool's own non-zero code (1). Keep this literal in sync with
# harness.gate.GATE_UNRUNNABLE_EXIT (test_verify_gate_unrunnable locks them).
GATE_UNRUNNABLE_EXIT=97
for _tool in ruff mypy pytest; do
  if ! uv run --extra dev "$_tool" --version >/dev/null 2>&1; then
    echo "gate precondition failed: '$_tool' is not runnable under 'uv run --extra dev' — toolchain unavailable (infrastructure, not a code failure)" >&2
    exit "$GATE_UNRUNNABLE_EXIT"
  fi
done

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

echo "=== landing-page drift guard ==="
# Fail the gate if docs/index.html names a command/skill/agent the registry no
# longer has (a renamed or removed piece of guidance the page still references).
# Lean guard, not a generator — ADR 0004 (CAL-1202). Stdlib only.
uv run --extra dev python scripts/check_landing_page_guidance.py

echo "=== design-token drift guard ==="
# Fail the gate if docs/index.html's generated :root block has drifted from
# design/03-tokens/tokens.json — the source of truth (#242). ADR 0004,
# narrowed (#243): the guidance catalog above stays guarded and hand-authored;
# this block is mechanical, generated content instead.
uv run --extra dev python scripts/build_design_tokens.py --check

echo "=== changelog fragment guard ==="
# Two guards, cause and symptom, because neither subsumes the other (#267).
# `check` is structural and base-independent, so it is meaningful wherever the
# gate runs. `require` is the direct presence check but needs a merge base, and
# abstains with a printed reason where one cannot be resolved (a shallow CI
# checkout, a detached `promote` worktree). The base-independent half that
# holds the line either way is the CHANGELOG ratchet in
# tests/unit/test_changelog_rotation.py.
uv run --extra dev python scripts/changelog_fragments.py check
uv run --extra dev python scripts/changelog_fragments.py require

echo "=== release cadence (report only) ==="
# Cadence bounds describe accumulated repo state, not this change: no change
# here caused a breach and none can fix one, so a breach must never be this
# gate's verdict (#350 — it wedged the build queue for five ticks). `report`
# exits 0 regardless and is deliberately the LAST stage, so the breach line
# lands inside the bounded gate-log tail `review` and `promote` already record.
# The enforcing half is `cadence.py check`, run by the release-cadence CI job on
# a PR into main and by RELEASING.md step 3.
uv run --extra dev python scripts/cadence.py report

echo ""
echo "All checks passed."
