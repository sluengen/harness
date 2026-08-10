<!-- guidance:template-proposal@0.1.3 -->
---
proposal: promotion-guard-instrument
status: accepted
date: 2026-08-11
related: [specs/features/cli-surface.md, specs/decisions/0012-persistent-runtime-host.md, specs/architecture-principles.md]
---

# Proposal: replace the nightly promotion guard's text-derivation instrument

> The guard that checks the nightly promotion workflow passes a legal `--repo` has taken four tickets in four attempts, and it structurally forbids the one-line refactor that would remove the defect class outright. The instrument is the problem, not the regex inside it.

## Problem / motivation

`tests/unit/test_nightly_promotion_workflow.py` derives `harness … --repo <arg>` call sites out of the workflow's shell text with a regex, then asserts each argument is the allowlisted root. It exists for a real reason: `HARNESS_WORKSPACE_ROOTS` fails closed, so a bad `--repo` is an exit-2 refusal at 14:00 UTC rather than a CI failure.

It has needed four tickets, each teaching the pattern one more way shell can spell the same call:

| Ticket | What escaped | Cycles |
|---|---|---|
| #390 | the allowlist was never exported at all | 1 |
| #391 | backslash continuations — the line model | 1 |
| #393 | flag order — the pattern's reach | 2 |
| #394 | `--repo=<arg>` — the joiner; and a pre-existing last-wins fail-open it exposed | 2 |

Four of the six cycles carried a blocking or medium finding. Known residuals remain, all the same class: a `--repo` behind a shell variable, an empty glued value, a separator inside a quoted flag value, and a bare `--repo` inside a later quoted value.

The count is not the argument, though. This is:

**The guard forbids its own fix.** The workflow writes `--repo "$GITHUB_WORKSPACE"` three times, six lines below the `export` that already defines that value. Defining the flag once and referencing it three times is the change that makes a wrong `--repo` unrepresentable. Measured against the guard as shipped on `dev`:

```
as shipped : [(65, 'promote start', '"$GITHUB_WORKSPACE"'),
              (85, 'promote continue', '"$GITHUB_WORKSPACE"'),
              (94, 'promote pr', '"$GITHUB_WORKSPACE"')]
refactored : []
GUARD ON THE REFACTOR: RED -> no `harness … --repo` call site was derived from the workflow
```

The anti-vacuity floor fires, correctly by its own logic, and the refactor cannot land. So the instrument requires the workflow to keep repeating the literal at three call sites — which is exactly the repetition that creates the hazard the guard polices. Every ticket has taught the regex a new spelling; none has reduced the number of chances to be wrong, which has been three throughout.

This also corrects a claim in #394's change spec. It recorded the `$REPO_FLAG` shape as "not statically derivable, and **correctly** recorded as a residual." It is a residual because the instrument cannot see it, not because the spelling is wrong. It is the better spelling.

The underlying mismatch: the property that matters is *every verb invocation on the runner receives a path inside the allowlist* — a runtime property. Text derivation is a proxy for it, and the proxy has now been wrong four times.

Doing nothing costs a fifth ticket on the next spelling, and leaves the workflow pinned to its most error-prone form.

## Options

**Option A — single-source the flag, shrink the guard.** The workflow defines `repo=( --repo "$GITHUB_WORKSPACE" )` once and expands it at each call. The guard stops deriving invocations and instead asserts one `--repo` literal exists, that it names the allowlisted root, that it follows the export, and that no `harness` call bypasses it. · Cheap, and it deletes the whole spelling problem by removing the parse rather than improving it. Still text analysis, so a future workflow that reintroduces a second literal needs the guard to notice — which the "exactly one" assertion does handle. Does not verify the runtime property.

**Option B — execute the step against a stubbed `harness`.** Put a fake `harness` on `PATH` that records its argv, run the step's script with a synthetic `GITHUB_WORKSPACE`, and assert every recorded invocation resolved a path inside the allowlist. · Tests the property that actually matters and is immune to spelling entirely, including variable indirection. Cannot be done against the current step as written: that one `run:` block also runs the full verify gate and three `python -c` JSON reads, so executing it means executing all of that. Practical only after Option C.

**Option C — move the calls into `scripts/promotion-step.sh`.** The three verb calls, the export, and the status checks become a script; the workflow step becomes `bash scripts/promotion-step.sh`. This is the pattern `ci.yml` and `release.yml` already use for `bash scripts/verify.sh`, so it introduces no new convention. The guard becomes "the workflow invokes only the wrapper", and the script is ordinary shell that Option B can drive. · Best structure, and it fixes the general problem that logic inside a `run:` block is untestable. Touches the production nightly path. Moderate size.

**Option D — remove the need for the flag.** Have the verbs resolve the workspace root from `GITHUB_WORKSPACE` when `--repo` is omitted, so the workflow passes nothing. · Deletes the surface entirely, but reopens ADR 0012 (#306), which deprecated the implicit form deliberately and routed every command through one seam (`harness/cli/_repo.py`) to warn on it. Reversing that for one caller trades a narrow test problem for a cross-cutting contract change, and the deprecation exists to make ambient CWD resolution unrepresentable — the same "unrepresentable" argument this proposal rests on, pointing the other way.

## Recommendation

**C, then B, with A as the intermediate if the nightly path should not move yet.**

C and B together are the root-cause fix: C reduces the call sites the property must hold at from three to one and makes the logic reachable by a test; B then verifies the real runtime property instead of a textual proxy. That ordering matters — B is not practical before C, and C without B leaves a simpler text guard still standing in for behaviour.

This follows `engineering-principles` on making invalid states unrepresentable, and it is the smaller change in the sense that counts: it removes a category of future work rather than adding one more special case to a pattern that has needed four.

A is worth taking on its own if C is judged too risky to schedule now. It captures most of the benefit — the spelling problem disappears with the parse — for a fraction of the change, and it does not conflict with C later.

D is not recommended. It would work, but it pays for a test-instrument problem with an architectural reversal, and ADR 0012's reasoning still holds.

## Open decisions

| Decision | Resolved | Recorded in |
|---|---|---|
| C+B, or A alone as an intermediate? | **C+B** — extract to a script, then verify by execution | this proposal; `specs/architecture-principles.md` |
| Is moving the nightly path acceptable now? | **Yes** | this proposal |
| Extraction as a general rule, or a one-off? | **General** — a `run:` block carrying logic moves to `scripts/` | `specs/architecture-principles.md` → *CI logic lives in a script* |

## Breakdown

**Decided 2026-08-11: C+B, moving the nightly path is acceptable, and the extraction rule is general.**

The first draft of this breakdown listed extraction, single-sourcing, the executable test, and the reduced text guard as four independent items. That was wrong, and the coupling is worth stating because it is the same fact the proposal turns on: moving the three calls out of the YAML makes the *current* guard derive nothing from the workflow, so its anti-vacuity floor fires. The instrument must be swapped in the same change that moves the code — there is no ordering in which extraction lands first and green.

1. **Swap the instrument** — extract `scripts/promotion-step.sh` (export, three verb calls, status checks; behaviour-identical), replace `_REPO_RESOLVING_CALL` and its residual lists with an executable test that stubs `harness` on `PATH` and asserts every recorded invocation resolves inside the allowlist, and reduce the workflow's own text guard to "invokes the wrapper and carries no bare `harness` call". Atomic by the coupling above.
2. **Single-source the `--repo` flag** — define once inside the script, expand at each call. Depends on 1, and is the payoff: it is what the old instrument forbade, and it is safe the moment the test asserts argv rather than text.
3. **Generalize the rule** — record the extraction principle in `specs/architecture-principles.md` (done at acceptance) and add a guard that a workflow `run:` block does not accrete logic, so this does not regrow elsewhere.

Item 2 is the change that removes the defect class; items 1 and 3 are what make it landable and keep it landed.

Filed 2026-08-11: **#396** (item 1, `assurance:complex`), **#397** (item 2, `assurance:simple`, blocked on #396), **#398** (item 3, `assurance:simple`).

## Risks / unknowns

- **The nightly is young.** Its first successful firing was 2026-08-09 (run `31318225157`); before that it had never once run to completion. Changing this path now risks the thing that just started working.
- **A scheduled workflow runs the default branch's copy of itself** (#390). So none of this can be validated by the nightly until it reaches the default branch, and a mistake surfaces at 14:00 UTC rather than in CI. Items 1–2 should land with the executable test (item 3) in the same change, not ahead of it.
- **Stubbing `harness` verifies argv, not the allowlist's own behaviour.** `tests/integration/test_nightly_promotion_workspace_allowlist.py` already executes the export line against the production resolver and should stay — item 3 replaces the *derivation* guard, not that one.
- **Unknown:** whether the status-check logic moves cleanly out of YAML, since it currently uses `RUNNER_TEMP` and `::error::` annotations. Both have plain equivalents, but this is unverified.
- **What would invalidate the recommendation:** if extraction turns out to need the workflow's environment in ways a script cannot reproduce, C loses its value and A becomes the answer.
