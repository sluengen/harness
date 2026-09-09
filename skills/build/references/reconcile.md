# Reconcile with the integration branch

Load this on entering the `reconcile` stage — after the reviewer reports
readiness, immediately before the certifying gate. That placement is the point:
reconciling last means the gate you spend is spent over the bytes that will
actually land, rather than over a tree the base has already moved out from
under.

Fetch the integration branch and merge it into the candidate. The rules, and
this is their only home:

- **Base movement is normal concurrency** — never a stop, never a question for the operator.
- Resolve textual conflicts on their plain meaning. A fresh conflict-resolution sub-agent may be dispatched.
- **Bounded: two attempts.** Spend both and the ticket is preserved and pushed, then held (`input`, assigned) with a comment naming what would not reconcile — the run stops rather than trying a third time.
- **The monotonic-field trap.** A field both sides advanced independently — a version number, a migration ordinal, a sequence id — converges on identical text, so the merge raises no conflict marker and the merged tree is a third state shipping under a value each side already claimed. Identical text is not agreement: treat a same-valued monotonic field as a collision to detect, and advance past both sides. **A value both sides derived from the same fixed point is the exception.** Where both branches compute the value from a predecessor that cannot move while they run, they reach the same value honestly: the identical text is agreement, and advancing past both sides would move the value once per concurrent ticket. Ask what each side derived the value from before treating a match as a collision, and treat it as one only where the two predecessors differ. Where both sides raised such a value to *different* levels, git raises an ordinary conflict and the resolution is the **higher** of the two, never the lower.
- **The only escalation is a genuine functional conflict** — both changes individually correct but wanting incompatible behaviour, a design call. Hold the ticket (`input`, assigned) with a comment naming the two behaviours in tension. A textual overlap with an evident resolution is not that case.

A resolution is bytes you authored, and no gate run before it covers them:
re-gate after reconciling, never before.
