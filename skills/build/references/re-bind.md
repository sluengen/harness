# Landing — the three cases, and how to tell them apart

Load this on the `push` stage.

A verdict binds to a tree, and the integration branch moves while the gate runs.
Under strict tree equality every move sent a run back through reconcile, delta
review, the gate, the verdict and the push, each opening a new window of the same
width. The landing posture keeps the guarantee and drops the exponential:
exactly three things can have happened, and git can tell you which.

**This is prose, and that is the change #621 made.** T3 (#539) turned the
four-step procedure into `scripts/land.js`, which decided the case for you and
refused the shapes it did not handle. That script read whether a commit's tree
carried a fresh gate marker — a verdict — which ADR 0022 point 3 forbids a
plugin-shipped executable from doing, and the marker it read no longer exists.
ADR 0022 names this instruction as the one most worth measuring for
effectiveness in the new shape: it is doing a mechanism's job with a sentence,
and if it turns out not to hold, that is a finding for the ledger rather than a
reason to rebuild the script.

## Before you push

Fetch, and ask whether the tip moved:

```bash
git fetch --quiet <remote>
git rev-list --count HEAD..<remote>/<integration-branch>
```

**Zero — the tip had not moved.** Push. Nothing reconciled, so the tree you push
is the tree the verdict bound to.

**Non-zero — merge it, and read what git did:**

```bash
git merge --no-edit <remote>/<integration-branch>
```

- **It merged cleanly.** The result is a two-parent merge git alone produced:
  first parent your reviewed tree, second parent already on the branch you are
  pushing, one merge base. That is the second shape the spine's *binding* admits,
  so it needs no re-gate and no re-review — nothing about your change was
  re-decided, and the bytes of the merge are git's own arithmetic. Push it.
- **It conflicted.** Resolve exactly the conflicted paths git named
  (`git diff --name-only --diff-filter=U`), commit the merge, then **run the full
  gate again and read it**. A resolution is bytes you authored after the verdict,
  and neither the verdict nor the earlier gate run covers them. Return the
  resolution to the reviewer as a delta before you push.

## The bounds

**Two attempts, then hold.** If the tip moves again while you are reconciling,
try once more. On the third, hold the ticket (`input`, assigned) saying the tip
would not stay still, and stop — a run that keeps chasing a moving branch is
spending the queue's time on a race it is losing.

**Never push from a shape you cannot describe.** A dirty worktree, a detached
HEAD, or a branch the repository declares no role for is not a landing; it is a
state to report. This is where `land.js` refused, and prose refuses it here for
the same reason — what you would push is not what anyone reviewed.

**Never force, in any spelling.** The eleven deny globs in
`settings/harness.json` are the host-native refusal behind this sentence, and
they are what survived the retirement of the guard that used to parse for it.
