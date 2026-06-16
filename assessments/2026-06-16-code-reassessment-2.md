# Code assessment (reassessment) — 2026-06-16

**Steward:** steward (`code` scope) · **Base:** `dev` @ `dd2a9f9` · **Gate:** PASS — 969 tests, ruff clean, mypy clean, CLI smoke clean.

## Why this pass

A scheduled `harness-work-pull` run found no actionable Todo in `Harness v3` — the single remaining Todo, CAL-717, is `decision`-labelled and blocked on a steering decision a headless run cannot make (name a real old-guidance repo, or authorise a synthetic-fixture rehearsal). Per the run contract it fell through to `/assess code`.

The regular eight-lens scope was exhausted twice earlier today (`2026-06-16-code.md` @ `19404cd`, `2026-06-16-code-reassessment.md` @ `30e191c`, both clean save the now-shipped CODE-1 retired-cite fix), and the broad pass (`2026-06-16-code-deep.md` @ `e768370`) added the coverage and spec/doc-coherence lenses. The deep pass surfaced one finding — SPEC §4.1 hand-listing a partial ops-command set — and explicitly **deferred its gate run to the fix's PR**. That fix has since merged: PR #128 (`dd2a9f9`) brings `5d064fb` (CAL-746, applying CODE-INSIGHT-1 / CAL-747) onto the deep-pass base. This pass verifies the merged HEAD and supplies the gate evidence the deep pass left to the PR.

## Verdict

The codebase is clean at the current dev HEAD. The only code delta since the deep pass is the CAL-746 fix itself, and it is sound and complete: SPEC §4.1 now names the verb *categories* and defers the exact registered set to §11 — the single source already locked by `test_cli_surface_locked.py` — so no second hand-list remains to drift. The fix ships its own guard (`test_spec_41_does_not_partially_enumerate_the_command_surface`) asserting §4.1 enumerates *all-or-none* of the registered ops commands, never a misleading proper subset. The full gate passes at `dd2a9f9` (969 tests). There is nothing to action.

## Findings

**Zero findings.** The one open finding from the deep pass (CODE-1) is fixed and merged (CAL-746); its systemic insight (CODE-INSIGHT-1) is applied (CAL-747). No new finding surfaced in the merged delta.

## Systemic insights

No insights this cycle. The merged change *applies* the deep pass's insight (CODE-INSIGHT-1: "don't keep a second, unguarded copy of the command surface") rather than raising a new class.

## Dimensions examined (clean)

- **Spec/doc coherence (the deep-pass finding, re-verified)** — SPEC §4.1 contains the deferral prose ("this section deliberately does not re-list it") and no longer enumerates an ops subset; the new lock plus `test_spec_command_surface_equals_registered` jointly hold §4.1 ⊆ {all, none} of the registered ops set and §11 == registered. Both pass.
- **Test health / coverage** — 969 tests pass (one more than the `30e191c` reassessment's 968, the delta being the new §4.1 guard); the surface-lock suite is 156 green. No module left uncovered by the change.
- **Size/structure, duplication, dead code, stale TODOs, cross-cutting security, architecture drift, dependency health** — unchanged since the two regular passes (`19404cd`, `30e191c`) and the deep pass (`e768370`) reported them clean; the merged delta is docs (`SPEC.md`) plus one test, introducing no new code path.
