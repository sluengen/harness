# Recording a decision

Load this when a change makes a choice somebody later will have to honour, and
you need to know where the record goes. `architecture` decides *whether* a
choice rises to a decision; this file is *where it is written and how it is
superseded*.

## Embedded is the default

A decision is recorded in the spec it governs, so the what and the why stay
together:

- a decision about **one feature** becomes a Decision block in that feature
  spec — `templates/decision.md` gives the shape: context, decision,
  alternatives rejected, consequences;
- a **cross-cutting** decision becomes a principle plus its rationale in the
  architecture-principles spec.

The reader then meets the reasoning in place rather than in a separate file
they have to find and correlate.

**Supersede in place.** Update the block where it stands, with a dated note on
what changed and why — *"Superseded YYYY-MM-DD: previously X; changed to Y
because Z."* — then update the code, comments and specs that relied on the old
choice. A superseding decision is never a new numbered file beside the old one;
two records of one choice is how a reader ends up honouring the retired half.

## Name the roles the decision binds, and check each one can reach it

A decision is recorded once. It is read by whoever opens the document it was
recorded in, and that is a narrower set than the roles it obliges. Before the
record is finished, name the roles it binds — builder, reviewer, architect, an
unattended run — and confirm each one's own entry document reaches it. A rule
filed in a reference only one role loads is invisible to every other role the
same rule governs, and invisible is indistinguishable from absent.

#690 is the shape. The rule that a fix whose diff reaches the as-built trigger
is not a fix, and the lane is raised instead, was recorded in
`skills/review-discipline/references/certifying.md` → *Record reality*. The
reviewer loads that file at PASS — but the fix lane dispatches no reviewer, so
the rule about the fix lane sat in the one document nobody in that lane opens,
while the spine and `/build`, which the *builder* reads, still carried the
pre-decision text. Read together the two were jointly unsatisfiable, and the
builder had no way to find that out. `nano-erp`'s ERP-571 cost a cycle to the
same shape.

Reaching it is a pointer, not a copy. The role's own entry document names the
canonical record and stops; restating the reasoning there gives the choice two
records, which is what *Supersede in place* above refuses, and leaves a reader
free to honour the retired half. The pointer also runs the right way — the role
that acts on the decision cites the record, never the record enumerating the
roles that will later read it.

## A configured decision directory is the only switch

Where a repo declares `paths.decisions` in `harness.yaml`, that directory is
home to its architecture decision records. A repo declaring none has no
standalone records and embeds exclusively. There is no second strategy setting
to keep in step: the optional path is the whole signal.

A configured directory holds only decisions that are **cross-cutting,
consequential and expensive to reverse** — branch topology, tracker
architecture, security posture, certification invariants. A decision that
merely touches several files does not clear that bar, and one governing a
single feature never does; both stay embedded.

Each qualifying decision has **one canonical record**. The feature specs it
affects link to it and must not restate its reasoning, so superseding the
record leaves them correct.

Placement, numbering and supersession *inside* that directory are the repo's
own convention — defer to its architecture index (the architecture-principles
spec, or the decisions index named in `harness.yaml`) rather than assuming one.
Universal guidance names the `paths.decisions` key and stops there.
