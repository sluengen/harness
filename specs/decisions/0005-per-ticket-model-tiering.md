# ADR 0005 — Per-ticket model tiering: two independent, label-carried dimensions

- **Status:** Superseded — the mechanism below is retired
- **Date:** 2026-07-22 (#177); retired 2026-08-05 (#321)
- **Source:** #177

> **Retired 2026-08-05 (#321).** Previously: the claude review engine's model was
> resolved per ticket from a `review:<tier>` label, and a sibling `build:<tier>`
> label recorded judged build difficulty. Changed to: one configured value,
> `CONTEXT.md` `loop.review_model` (default `sonnet`), read off the `LoopBudget`
> the review verb already loads. `harness review --model <alias>` is unchanged —
> what went is the resolution *from the ticket*.
>
> Because, measured 2026-08-04, neither dimension was doing work. `build:` is
> consumed by nothing — this ADR says so itself — and in roughly two weeks was set
> on **0 of 25** open issues. `review:` *was* a real control signal and was
> **never once set**: every review in the ledger resolved past it to the `sonnet`
> fallback, while the mechanism cost a tracker `fetch_issue` round-trip and five
> degradation branches on the review path to read a label nobody wrote. Since ADR
> [0013](0013-codex-engines-in-container.md) the tier was also claude-only by
> construction, so a per-ticket tier would have governed one of two engines.
>
> The evidence that Sonnet suffices, claude engine only, from this repo's ledger.
> Reviews before #177 ran Opus by ambient default; everything after runs Sonnet:
>
> | | pre-#177 (Opus) | post-#177 (Sonnet) |
> |---|---|---|
> | runs | 110 | 114 |
> | fail rate | 18.4% (28/152) | 17.3% (30/173) |
> | avg issues per fail | 1.39 | 1.43 |
> | one-shot pass | 76% | 64% |
> | avg review cycles | 1.38 | 1.52 |
>
> Rejection rate and issue density are unchanged, so the Sonnet reviewer is not
> rubber-stamping. The cycles difference is borderline (z≈2.0) and **confounded** —
> the builder, the guidance and the ticket mix all changed across that boundary,
> and the design verb landed *after* #177. This is observational, not controlled,
> and is not evidence of causation in either direction.
>
> The record below stands as what was believed and why; it is not the current
> design. What survives it: the *shape* of the argument that a dimension with no
> deterministic seam gets a record rather than a control, and #172's finding that
> a custom project field is invisible on the board's default view.

## Context

Automated ticks run every build and review on one model — the tick session's
model for the build, and Opus by ambient default for the review, since
`harness review` passed no `--model`. Most tickets are routine and do not need
the top tier on either dimension, so the loop spent indiscriminately. The build
and review dimensions are independent — a task can be trivial to build yet
warrant a careful review, or vice versa — and they differ in how far they can
be controlled: `review` is a genuine read-only `claude -p` subprocess the verb
constructs, but the initiating orchestrating session *is* the builder (it
writes the code and tests inline, `commands/harness.md:12,52`), so there is no
deterministic per-ticket seam to swap its model mid-run — a session spawning a
subagent is discretionary.

Board `sluengen/2` exposes only built-in fields today; #172 established that a
custom single-select is invisible on the default board view. Labels, not a
project field, are therefore the carrier — visible on the card, queryable via
`gh issue list --label`.

## Decision

Two independent per-ticket model tiers, each `sonnet` or `opus`, carried as
GitHub labels of the shape `<dimension>:<tier>` — `build:opus` /
`review:opus`. Absence of a family's label defaults that dimension to
**sonnet**: the top tier is opt-in, set by the spec author at spec-authoring
time, never inferred.

A pure resolver reads a tier off a ticket's labels with the default baked in:

```
resolve_model_tier(labels: list[str], dimension: str) -> "sonnet" | "opus"
```

(`harness/cli/review_protocol.py`.)

The two dimensions are consumed differently, because only one is a
deterministic seam:

- **`review` → control signal.** `harness review` resolves the `review`
  dimension from the run's ticket labels (`tracker_client().fetch_issue`) and
  appends `--model <alias>` to the **claude** engine command only; the codex
  branch is untouched (ADR 0002 already keeps `--engine codex` a distinct,
  host-only path; ADR [0013](0013-codex-engines-in-container.md) amends why that
  path is host-only and declines to extend this ADR's labels to the engine
  choice). An explicit `harness review --model <alias>` overrides the
  resolved tier, for host/testing use.
- **`build` → recorded judgement, not control.** No verb reads it. It is
  metadata on the ticket — the spec author's judged difficulty — so a
  completed run can be interrogated against it later ("judged `build:opus` —
  did the session actually escalate to an Opus subagent?"). This ticket
  establishes the label family; it wires no build-side behaviour.

## Alternatives rejected

- **A `model` project field instead of labels.** Rejected on #172's own
  precedent: a custom single-select field does not render on the board's
  default view, so a field-carried tier would be invisible where an operator
  actually looks. Labels are visible on the card today.
- **Deterministic per-ticket build-model control.** Rejected as unreachable
  within a single routine: the orchestrating session is the builder, and
  spawning a subagent to hold a different model is discretionary, not a
  verb-owned seam. Recording the *judgement* is the fallback that is still
  useful (post-run interrogation) without pretending to control what cannot be
  controlled deterministically.
- **One combined tier instead of two.** Rejected because build and review
  difficulty are observably independent — a trivial build can warrant a
  careful review, and vice versa — so a single label would force one axis to
  misrepresent the other.

## Consequences

- A routine ticket (no `review:*` label) reviews on Sonnet by default, cutting
  indiscriminate Opus spend on the review dimension.
- A ticket judged difficult to build can be labelled `build:opus` as a record,
  even though no verb currently acts on it — that wiring is explicitly out of
  scope here and would need its own deterministic seam (e.g. a dispatch step)
  to become controllable.
- `spec-authoring` now instructs the author to set both tiers, default
  sonnet, at spec-authoring time (see the guidance change accompanying this
  ADR).
