# ADR 0006 — Three hold kinds: a held ticket records what kind of human input it waits on

- **Status:** Accepted
- **Date:** 2026-07-23
- **Source:** `specs/proposals/promote-and-decision-commands.md`

## Context

When an unattended run finds a Todo ticket that is not wholly actionable, it
defers: `harness defer` posts a comment, applies a hold label, and assigns the
ticket to the operator, and `work-discovery` thereafter skips anything assigned.
That is the outbound half of the loop and it works.

There is no inbound half. Nothing drains the held pile, so it is drained by the
operator retyping an ad-hoc prompt into a fresh session. The proposal introduces
`/decision` as the versioned return path — but it can only sweep automatically
if it can tell, without re-reading and re-judging every ticket, which holds it is
allowed to clear.

The current vocabulary cannot express that. `--needs` takes two kinds,
`decision` and `operator`, and they do not partition the space the operator
actually cares about. The exclusion the operator states is: *purely calls I can
make in the turn* — not tickets that need an interactive session, and not
tickets waiting on the operator to supply a work item or stand up
infrastructure. That third case has no kind of its own today, so a deferring run
must file it under `decision` (wrong — `/decision` would surface it and the
operator cannot clear it in the turn) or `operator` (wrong — it is not an
interactive session, it is a blocked dependency on the operator).

Without a third kind, `/decision` has to re-triage each ticket on every sweep,
re-deriving a distinction the deferring run already knew and could have
recorded. That fails the same test `work-discovery` applies to its own judgment:
one home, recorded once, not re-derived per caller.

## Decision

`harness defer --needs` takes **three** kinds, and they partition held work by
*what kind of human input the ticket waits on*:

- **`decision`** — a judgment call. Direction, a detail, a trade-off the
  operator can resolve by answering. Clearable in a turn, from the ticket alone.
- **`input`** — the operator must supply something the run cannot: a work item,
  a credential, an environment, infrastructure stood up. Not answerable; it
  needs the operator to go do a thing.
- **`operator`** — an interactive, hands-on session is needed: setup at the
  keyboard, a visual check, anything requiring a human driving the tools.

The kind's value remains the label name, so a held ticket carries both the
machine-readable assignment (the skip signal) and a label saying why.

`work-discovery` **skips all three** — the hold semantics are unchanged, and
assignment stays the authoritative skip signal. Only the *return path* reads the
kind: `/decision` selects `decision` and nothing else.

## Alternatives

- **Keep two kinds; `/decision` re-triages each ticket per sweep** — no engine
  change, but it re-derives on every sweep a distinction the deferring run
  already made and threw away, and gets it wrong silently. The operator's stated
  exclusion stays a per-sweep judgment rather than a queryable fact.
- **Keep two kinds; file input-blocked tickets under `operator`** — conflates
  "come to the keyboard" with "you owe this ticket something", so the operator's
  two filters stop meaning what they say and the `operator` list becomes a
  mixed pile.
- **A project field rather than a label** — #172 established that a custom
  single-select is invisible on the board's default view. Labels are visible on
  the card and queryable with `gh issue list --label`.

## Consequences

- `/decision` selects with a query, not a judgment: hold kind `decision`, and
  the ticket is by construction clearable in a turn.
- The `operator` label's meaning **narrows** — it now means only an interactive
  session, not "a human owes this something". Any existing ticket filed under
  `operator` for an input reason should be re-kinded. There are none today
  (counted 2026-07-23: zero open issues on `sluengen/harness` carry either
  label), so this costs no migration now — but it will if the kinds ship after
  the queue starts using them.
- `work-discovery` gains a third kind to name and the return-path test; its
  skip rule is unchanged, which is the point — adding a kind must not perturb
  the outbound half.
- A deferring run now makes a three-way call instead of two-way. The
  distinguishing question is stated once in `work-discovery`: *can the operator
  clear this by answering, by doing, or by sitting down at the keyboard?*
