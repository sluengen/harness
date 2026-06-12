# Code reassessment — 2026-06-13 (run e)

**Steward:** code-steward (read-only health pass)
**Package under assessment:** `harness/` (Typer verb CLI, SQLite ledger, git-worktree lifecycle, Codex review dispatch) + specs/docs.
**Branch:** `assess/code-2026-06-13e` (off `dev`).

## Summary

A whole-codebase sweep against the SPEC contract (README + SPEC §1–2/§4/§11 = current
verb model; §3, §5–§10, §12–§14 = superseded retired-engine sections) found **one**
genuinely-new, atomic, mechanically-actionable as-built divergence: the top-level
`harness --help` description string still advertises the retired deterministic workflow
engine. Every other user-facing surface (README, SPEC §1–2, the module docstring directly
above the string, and all per-verb help strings) was migrated to the verb model; this one
Typer `help=` was missed in the CAL-574 migration.

The known retired-§ docstring-cite cluster (CAL-633 / CAL-636) was confirmed present and
**not re-filed** per instructions. No new dead code, stale TODOs (none exist in the package),
test gaps, or security gaps surfaced beyond that parked cluster.

## Findings

### CODE-1 — Top-level `harness --help` describes the retired deterministic engine (Medium)

- **What:** The Typer app's top-level help string still reads
  `"Deterministic workflow execution harness — see SPEC.md"`. This describes the YAML
  workflow engine that was **retired in CAL-574**; the harness is now a set of audited
  verbs (`start` / `review` / `close`). The string is user/agent-facing output — it is the
  first line printed by `harness --help` and `harness` with no args (the app sets
  `no_args_is_help=True`). It directly contradicts the as-built model that the module
  docstring three lines above it already states correctly (`"CLI entrypoint — see SPEC §11.
  The CLI is the public contract ... The harness exposes verbs ..."`), the README
  (`"A set of deterministic, audited verbs an agent calls ... The earlier deterministic YAML
  workflow engine was retired in CAL-574"`), and SPEC §11.
- **Where:** `harness/cli/__init__.py:43` —
  `help="Deterministic workflow execution harness — see SPEC.md",`
  (introduced 2026-05-11 in commit `60ec20c`, before the verb-model migration; confirmed via
  `git blame` as the lone surviving "Deterministic workflow execution" instance across
  `harness/`, `tests/`, `docker/`, `specs/`, `README.md`, `SPEC.md`, `commands/`).
- **Why:** As-built divergence — public verb-surface prose describing behavior the code no
  longer has. SPEC §4.1 and §11 make the CLI surface a public contract; the harness's own
  CLAUDE.md / code-quality bar treats stale doc/prose that contradicts the as-built model as
  a defect (the same class as CAL-625/CAL-635, both shipped this month). The help text is the
  most-visible single line of CLI prose and is the one place an operator typing `harness`
  with no flags lands first.
- **How:** Replace the string with a verb-model description, e.g.
  `help="Deterministic, audited verbs an agent calls to drive a ticket — see SPEC.md §11",`
  (mirroring the README tagline / SPEC §11). One-line, cite-only edit. No behavior change.
  Verified atomic: no test asserts the description string — `test_smoke.py::test_cli_help_runs`
  and `test_cli_close.py::test_close_command_registered` only assert exit code 0 and the
  presence of `"harness"` / `"close"`; `test_cli_surface_locked.py` does not lock help prose.
  A guard test asserting the top-level help no longer contains `"workflow"` / `"engine"`
  could be added alongside (optional, low-cost) to prevent regression.

## Insights

No new systemic insight this cycle. CODE-1 is a one-off straggler from the CAL-574 migration,
not a recurring class — the migration sweep simply missed one string, and the existing
docs-consistency / surface-lock tests already cover the broader surface. Filing a third
insight here would be invention.

## Items confirmed and deliberately NOT re-filed

- The retired-§ module-docstring-cite cluster (CAL-633 / CAL-636, DECISION-PARKED):
  `harness/state/schema.py` (§6/§7/§12), `harness/state/store.py:37` (§12),
  `harness/events/emitter.py` (§12), `harness/events/schema.py` (§12), and the
  `harness/cli/query*.py` / `_query_common.py` (§12) cites. Present, unchanged, parked.
- `harness.state.schema.BaseState` is referenced only by a test guard
  (`test_engine_retired.py`), not by live verb code — this is the deliberate schema-reference
  retention noted in its module docstring, **not** dead code worth filing.
- `runs.workflow_name` / `workflow_version` columns (written empty/`0` by `start`, surfaced by
  `status`/`runs`) are retained-schema, not divergence — documented as such in
  `start.py:352-356` and `state/schema.py`.
