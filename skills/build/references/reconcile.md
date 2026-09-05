# Reconcile with the integration branch

Load this on entering the `reconcile` stage — after the reviewer reports
readiness, immediately before final binding. That placement is the point: it
closes the review-wide window in which the base could move, by putting
reconciliation adjacent to the gate and verdict that bind the result.

Fetch the integration branch and merge it into the candidate. The rules, and
this is their only home:

- **Base movement is normal concurrency** — never a stop, never a question for the operator.
- Resolve textual conflicts on their plain meaning. A fresh conflict-resolution sub-agent may be dispatched.
- **Bounded: two attempts.** Spend both and the ticket is preserved and pushed, then held (`input`, assigned) with a comment naming what would not reconcile — the run stops rather than trying a third time.
- **The monotonic-field trap.** A field both sides advanced independently — a version number, a migration ordinal, a sequence id — converges on identical text, so the merge raises no conflict marker and the merged tree is a third state shipping under a value each side already claimed. Identical text is not agreement: treat a same-valued monotonic field as a collision to detect, and advance past both sides.
- **The only escalation is a genuine functional conflict** — both changes individually correct but wanting incompatible behaviour, a design call. Hold the ticket (`input`, assigned) with a comment naming the two behaviours in tension. A textual overlap with an evident resolution is not that case.

If reconciliation changes the tree, return the reconciliation delta to the
reviewer. The reviewer examines both the delta and its implications for the
whole change, resolves any findings through the normal cycle, and updates the
as-built record when the integrated behaviour changed. **No tree identity,
marker, readiness report, or verdict is inherited across this change** — the
same rule a resume applies to `run.json`'s cached oids.
