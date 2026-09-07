# Conditional sections of a change spec

Load this while writing a change spec, to decide which of these three sections
the change owes. Each is present only when its trigger fires, and absent
otherwise — an unconditional copy in every spec is noise that teaches readers
to skim the section.

## Watchlist trigger

Fires when the files the change will touch intersect the repo's
`architecture_watchlist.files`. Record exactly one of two outcomes:

- a small behaviour-preserving seam extraction, with tests or a smoke check
  proving behaviour is unchanged; or
- an explicit deferral naming why extraction is deferred this time — no safe
  seam in this diff, too risky without a redesign, blocked on a decision.

Either outcome is valid; an unrecorded one is not. The mechanism — the
intersection, the two outcomes, the no-op for a repo that has not opted in —
belongs to `architecture`; this section is only where the result is written
down. A repo with no `architecture_watchlist` has no trigger, so omit the
section rather than writing "not applicable".

## Lifecycle sweep

Fires for any operation that mutates stored state — a create, update, delete,
or anything that changes something durable.

Enumerate the affected entity's **derived artifacts** — caches and query keys,
share tokens, counts and aggregates, sessions — and state, per artifact, what
happens to it. "Unaffected" is an acceptable answer; silence is not.

This is the sweep that catches the write path shipping its primary mutation
while dropping a derived artifact: the stale cache, the unrevoked share token,
the count left un-decremented. Review keeps finding those one artifact at a
time, which is the expensive way; design time is when one person is looking at
the whole entity. A change that mutates no stored state has no sweep to do.

## Instrument replacement

Fires when a change **replaces** an information source rather than adding one —
a guard rewritten, a document migrated or distilled into a new form, one report
replacing another.

Name what the new form must retain from the old one, and review that comparison
against the prior source. Use an existing executable or structural check where
one proves the contract; a document's semantic reach is reviewed directly, not
converted into a wording predicate. A change that adds a source rather than
replacing one has no prior reach to compare.
