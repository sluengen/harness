# Certifying a candidate

Load this when a review is about to PASS — when no blocking finding stands and
you are deciding what has to be true before the verdict is issued. Nothing here
applies on a FAIL: there is nothing settled to record, and the record is
drafted fresh from the next diff.

## Record reality — the as-built-record gate

The trigger is a **documented-behaviour change, in any lane**: a screen, route,
endpoint, CLI command, or any behaviour the as-built record documents, matched
from the changed paths. The review either folds the matching as-built-record
update into this change, or records an explicit deferral naming the reason. A
shipped behaviour change to such a surface with neither is a FAIL — the
canonical record rots silently otherwise, and no later per-change reviewer
catches the gap because no future change re-touches it.

The feature lane always reaches this trigger, because a feature changes
documented behaviour by definition. The fix lane never should, and a fix whose
diff does reach it is not a fix: upgrade the lane rather than writing the
record under it.

Recording reality is the reviewer's job, written from what the diff actually
does, never the builder's. Where a surface has no as-built record yet, the
first ticket touching it creates one; a surface may not accumulate more than
one shipped ticket without one, because the record is where a gap between
tickets becomes visible and it cannot do that retroactively.

The record states no bare count: a figure names the commit it was measured at,
or a guard derives it, or the record restates the invariant the number was
evidence for.

## Sweep for twins

A mechanism in this tree often has a **twin** — a template shipped to consuming
repos, a byte-identical mirror of a canonical document, a hook and the guard
that measures it, a rule and the reference that renders its shape. When the
diff changes such a mechanism, the twin is updated in the same branch or the
review records an explicit deferral naming why.

Derive the question from the changed paths — what else in this tree is
generated from, restates, or measures the thing that moved — rather than
waiting to be told a twin exists. A stale twin ships green by construction:
every guard over the original still passes, and the copy the next reader
reaches is the one describing behaviour that was retired.

## Close the candidate before you certify it

The tree you verify and the tree your verdict covers are the tree that merges.
So the as-built-record update goes into the candidate **first**: draft it from
the diff, commit it onto the branch, and only then run the verify gate and
decide. Nothing lands after that — a later commit, documentation included, is
uncertified tree content and voids the pass.

Ordered the other way round, the record edit is never gate-checked, and that
matters because a record is delivered tree content a link, generated-doc or
drift guard can reject.

Two consequences worth stating. When the certifying gate goes red **because of
your own record edit**, you wrote it, so you fix it and re-run — bounded at two
attempts, then FAIL carrying the gate output — never the implementation, which
would make you the builder. And a deferral is ordering-neutral: it lands in the
report and on the ticket, not in the tree.

**The verdict binds to a tree, not a commit.** Report the `reviewed_tree` —
git's tree object for the certified candidate, which `git write-tree` prints
over a staged tree. The flow that ships integrates only while the tree at HEAD
still equals it, or carries a merge git alone made from it; the spine's
*binding* states both acceptance paths. Because the gate's own evidence is
named after that tree object, an amend rewriting no bytes voids nothing. A
report may also name the commit sha for a human reader, but the shipping
equality is tree to tree.
