# Reconcile with the integration branch — the `rebase` stage

Load this on entering the `rebase` stage. There are **two** of them and this is
their one home: `/build` rebases *before* the review, so the reviewer reads the
branch as it will land; `/promote` rebases again *before* the gate it pushes on,
so that gate is spent over the bytes that will actually land rather than over a
tree the base has already moved out from under. The stage was called `reconcile`
and sat between two review stages until #623; the delta review that placement
required is gone, and the rules below did not depend on it.

**The stage is named `rebase` and the operation is a merge.** Fetch the
integration branch and merge it into the candidate — never `git rebase`, which
rewrites commits anything else may already have fetched. The rules:

- **Base movement is normal concurrency** — never a stop, never a question for the operator.
- Resolve textual conflicts on their plain meaning. A fresh conflict-resolution sub-agent may be dispatched.
- **Bounded: two attempts.** Spend both and the ticket is preserved and pushed, then held (`input`, assigned) with a comment naming what would not reconcile — the run stops rather than trying a third time.
- **The monotonic-field trap.** A field both sides advanced independently — a version number, a migration ordinal, a sequence id — converges on identical text, so the merge raises no conflict marker and the merged tree is a third state shipping under a value each side already claimed. Identical text is not agreement: treat a same-valued monotonic field as a collision to detect, and advance past both sides. **A value both sides derived from the same fixed point is the exception.** Where both branches compute the value from a predecessor that cannot move while they run, they reach the same value honestly: the identical text is agreement, and advancing past both sides would move the value once per concurrent ticket. Ask what each side derived the value from before treating a match as a collision, and treat it as one only where the two predecessors differ. Where both sides raised such a value to *different* levels, git raises an ordinary conflict and the resolution is the **higher** of the two, never the lower.
- **The only escalation is a genuine functional conflict** — both changes individually correct but wanting incompatible behaviour, a design call. Hold the ticket (`input`, assigned) with a comment naming the two behaviours in tension. A textual overlap with an evident resolution is not that case.

A resolution is bytes you authored, and no gate run before it covers them:
re-gate after reconciling, never before. At `/build`'s rebase that gate is the
reviewer's own; at `/promote`'s it is the one that licenses the push.
