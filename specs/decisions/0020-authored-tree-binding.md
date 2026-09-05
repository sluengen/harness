# ADR 0020 — The verdict binds to the authored tree, proven by recomputing the merge

- **Status:** Accepted
- **Date:** 2026-09-05
- **Source:** accepted proposal [`lifecycle-reset`](../proposals/lifecycle-reset.md) → *The landing posture* (D2–D5), built as #539

## Context

A verdict binds to a git tree, and until now the tree that shipped had to **equal** the tree the verdict covered. The integration branch does not hold still while a gate runs. Every move of it sent a run back through reconcile, delta review, the full gate, the verdict and the push, and each of those stages opened a fresh window of the same width. With a ten-minute gate and several agents landing per hour the expected number of attempts to land is `e^(λW)` — modelled at 7.4 attempts for eight pushes an hour, against 23% of commits on `calibrate`'s integration branch already being reconciliation merges. Making a retry cheaper does not change the shape; only taking λ out of the exponent does.

The proposal decided the shape on 2026-09-04 (D2 to D5) after eight probes. Its statement of the proof was *"one merge base, parents exactly the passed commit and the incoming tip, a clean index and worktree, no staged resolution"*. Three of those four are unobservable at the point enforcement happens: a `PreToolUse` hook sees a `git push`, by which time the merge is committed and the index, the worktree and any resolution are gone.

## Decision

**A push to a branch the repo declares is authorised by a fresh gate marker over the pushed tree, or by a merge git alone produced over a tree one covers. There is no third path.**

The second path holds when all of the following are true, and each is read from git after the fact:

1. the pushed commit has exactly two parents;
2. the **first** parent's tree carries a fresh, **unscoped** marker — git's own convention makes parent 1 the branch you were on, which under the landing loop is the commit that received the verdict;
3. the **second** parent is an ancestor of, or equal to, the remote-tracking ref for the branch being pushed, so only bytes that branch already carried may enter this way;
4. the two parents have exactly one merge base;
5. `git merge-tree --write-tree` over the two parents reproduces the pushed tree.

Where (5) reproduces a *different* tree, the paths where the two differ are the bytes somebody **authored**, and they are authorised only by a fresh marker over the pushed tree whose `scope` contains every one of them. A repo declares `commands.test_scoped` to re-gate those paths; declaring nothing runs the whole gate and earns an unscoped marker, which is the same authorisation it always was.

**The instrument is recomputation, not observation.** `merge-tree` replays the merge from the two parents, which is checkable at push time. Where it is unavailable (git before 2.38) the second path is simply absent and the strict equality stands; there is no new fallback and no degradation.

**What the path proves is that no agent authored these bytes — not that these bytes were gated.**

## Alternatives rejected

- **Requiring the two changed-path sets to be disjoint.** D2 considered and rejected it: two people editing different functions in one file is ordinary, and denying it reintroduces the serialisation this decision exists to remove.
- **Observing the merge as it happens.** The enforcement point is the push. A hook that tried to watch the merge would be watching a different tool call, or trusting the agent's account of one.
- **Trusting the parents without condition (3).** Without it the path is unsound, and the attack is two commands: branch from the tip, commit the payload, merge it into the gated candidate. Two parents, one merge base, `merge-tree` reproduces it exactly, the authored set is empty, and the payload lands having never been through a gate.
- **Accepting a merge made with `-s` or `-X`.** `merge-tree --write-tree` is always ort, so any strategy option produces a tree it will not reproduce and every byte reads as authored. That is the honest answer: nothing verified the side the option silently dropped.
- **A distinct filename for a scoped marker.** It would have kept the filename-only contract, but it splits one artefact into two shapes for every reader, and `hooks/gate-evidence-guard.js` would then be blind to a real gate run. Reading one field, in one hook, on the deny side, was the smaller change.

## Consequences

**Accepted risks, and each has a named backstop.**

- **A clean merge of two individually green changes can be wrong.** D2 accepted this: the composite gate on the *next* build is what catches it, rather than a CI job these repos do not run.
- **A `merge=union` attribute or a custom merge driver lands bytes in neither parent, with an empty authored set.** Both `git merge` and `merge-tree` honour the `merge` attribute, so the recomputation agrees and the guard allows. It is not an escalation — a custom driver's command must be in `.git/config`, which git requires precisely so that a tree cannot make itself execute code, and anyone who can write that can write a marker by hand. It is the textual sibling of the risk above, and the same backstop applies.
- **A remote-tracking ref is local and forgeable.** Condition (3) raises the attack from "make a commit" to "forge a tracking ref and a matching history", which is the same class as writing a marker by hand — a limit `hooks/push-target-guard.js` has always conceded in its own docstring. Server-side branch protection remains the control of record; nothing here is an authority.

**What changes elsewhere.** The spine's law 3 and its *binding* now state the authored-tree claim and both acceptance paths; `scripts/land.js` decides the three landing cases and retires the four-step prose procedure `/build` carried; the marker payload gains `scope`, `started_at` and an atomic write, and ADR 0018 is amended in place for the one field a hook now reads.
