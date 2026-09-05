# Landing — the three cases, and the script that decides them

Load this on the `push` stage. It replaces the four-step post-verdict re-bind
procedure this file used to carry: T3 (#539) turned that procedure into
`scripts/land.js`, which is what the steps below invoke. Nothing restates a git
invocation for landing; there is one home for the mechanics and it is the script.

A verdict binds to a tree, and the integration branch moves while the gate runs.
Under strict tree equality every move sent a run back through reconcile, delta
review, the gate, the verdict and the push, each opening a new window of the same
width. The landing posture keeps the guarantee and drops the exponential: exactly
three things can have happened, and git can tell you which.

From the worktree, after PASS and after the `HEAD^{tree}` comparison:

```bash
node <plugin-root>/scripts/land.js plan
```

Act on the one `decision` it prints:

| `decision` | What happened, and what you do |
|---|---|
| `push` | The tip had not moved, or git merged it cleanly and `plan` left the merge committed. Run the `push_command` it gives, then `land.js done`. |
| `resolve` | The merge conflicted; the worktree is left conflicted for you. Resolve exactly the paths in `conflicts`, commit the merge, run the `scope_command` and **read its output**, then `land.js finish` — and act on its decision the same way. |
| `hold` | Reconciliation is spent, or the tip moved again past its second attempt. Hold the ticket (`input`, assigned) with the reason it printed, and stop. |
| `refused` | Not a shape this script decides — a dirty worktree, a detached HEAD, a branch the repo declares no role for. The reason names which. |

**Why a clean merge needs no re-gate and no re-review.** `hooks/push-target-guard.js`
accepts a push carrying a merge git alone produced over a gated tree: two parents,
the first certified by a fresh unscoped marker, the second already on the branch
being pushed, one merge base, and the tree reproduced by `git merge-tree`. That is
the spine's *binding*, second acceptance path, and it is proven by recomputation
rather than by anything this workflow asserts. Where the merge conflicted, the
resolution bytes are the only thing nobody verified, so the scoped re-gate covers
exactly those and the marker records the scope — `commands.test_scoped` if the
repo declares one, the whole gate if it does not (D3).

**Three things the script leaves to you, deliberately.**

- **It never pushes a branch.** It runs as one Bash command, so a branch push it
  made would be invisible to the PreToolUse guard — the script would be the way
  around the guard it exists to satisfy. The push is your own command. (`done`
  does push `refs/harness/*`: a gate record and the green pointer. Neither moves
  a branch and neither authorises anything.)
- **It never runs the gate.** Law 3 obliges *you* to run it and read the output.
- **It never resolves a conflict.** That is judgment, not a decision a script makes.

`land.js done`, after the push lands, publishes the gate record other sessions
read with one `ls-remote` and advances `refs/harness/green/<integration>` — the
base `worktree-isolation` gives the next worktree. It advances only on an
uncontended landing that actually landed: a conflicted merge carries a resolution
whose evidence is a scoped gate, which is not the whole-tree claim the pointer
makes, and a push the guard refused never reached the branch at all.
