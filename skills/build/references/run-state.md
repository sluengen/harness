# Run state — `.harness/run.json`

Load this when writing or resuming a run.

**The rule that bounds the file:** `run.json` records *where the run is*, never
*what is true of the tree*. Every oid, marker and verdict it holds is a cache
key that must be re-derived from git and compared before use, and on a mismatch
the file's copy is discarded — never git's.

It is gitignored (`/harness:init` seeds `.harness/` into the gate-ignore block),
so it never reaches the tree the verdict binds to.

## Fields

| Field | Type | Values |
|---|---|---|
| `version` | integer | exactly `1`. An unknown version is a malformed file, not a guess. Adding a field is not a bump; changing what one *means* is |
| `ticket` | string \| null | tracker id, or `null` for an untracked run |
| `lane` | string | `fix` \| `change` \| `feature`, from the `assurance:` label (`trivial`/`simple`/`complex`). Rewritten upward only; the *reason* goes on the ticket |
| `stage` | string | one of the names below |
| `tests_locked` | boolean | strictly boolean. `false` at set-up, `true` in the same write that sets `stage: "implement"` |
| `base_commit` | string | the commit the worktree branched from. The test lock asks this tree whether a test file is new |
| `reviewed_tree` | string \| null | tree oid |
| `gate_marker_tree` | string \| null | the tree the last read marker named. The marker itself is the gate's, at the path the spine's *binding* contract gives; this field caches which tree it named and never stands in for reading it |
| `verdict` | string \| null | `PASS` \| `FAIL` \| `DEFER` — transcribed from the reviewer's report, never authored |
| `review_cycles` | integer | cycles **spent**, against `loop.max_review_cycles` |
| `engine` | string | `claude` \| `codex` |
| `updated_at` | string | RFC 3339 UTC, every write |

**Only the orchestrator writes this file.** No implementer, architect,
reviewer or conflict-resolver touches it — that is what stops an agent told to
make the tests pass from clearing the flag that governs the stage it is in. A
writer rewrites the whole object and **carries through keys it does not
recognise**, so a later ticket can add fields without this writer stripping them.

## Stages

```
setup · ground · spec · design · tests · implement ·
in_review · substantive_review · reconcile · delta_review · full_gate ·
pass · tree_compare · push · tracker_done · reflect · cleanup
```

One vocabulary, spelled once. The nine from `in_review` to `tracker_done` are
the normative block in `skills/build/SKILL.md` — that block owns their order
and their authorities and is not restated here; the rest are the stages a
resume needs and the block does not have. A second vocabulary for the same word
is the defect this shape avoids.

**`tests` and `implement` are separate stages, and that is the whole mechanism.**
Law 7 forbids editing a test *while implementing against it*, so locking at the
start of implementation is what makes test-first possible: author the failing
tests at `tests` with the lock off, then one write sets `stage: "implement"` and
`tests_locked: true` together, before the first line of implementation code.
Everything after that is locked, REFACTOR included. A test that turns out wrong
returns the run to `tests` with the reason recorded on the ticket, and the
reviewer will ask for it.

**`reflect` sits after `tracker_done`.** A ledger append is a tracker write;
putting one between the push and the ticket's own state change means a failed
append leaves shipped work sitting In Review, which is worse than a shipped
ticket missing a reflection line.

## Resume

Always re-derived, every stage, no exceptions: the current tree oid
(`git add -A && git write-tree`), HEAD, the branch, whether a marker exists and
is fresh, the integration tip, and the ticket's real tracker state.

Always trusted, because they are history rather than tree facts: `ticket`,
`lane`, `engine`, `review_cycles`, and `base_commit` once it still resolves.

**The gate on the three tree-bound fields.** `reviewed_tree`,
`gate_marker_tree` and `verdict` are trusted **only** while the freshly derived
tree oid equals `reviewed_tree`. One byte of difference sets all three to null
and returns the run to `substantive_review`. This is the rule reconciliation
already states — no tree identity, marker, readiness report or verdict is
inherited across a change — and the resume path inherits it rather than
inventing a second one.

| Resuming at | Do |
|---|---|
| `setup` `ground` `spec` `design` | re-run the stage from the ticket |
| `tests` | run the tests; a remembered RED is not evidence |
| `implement` | rewrite `tests_locked: true` before the first edit — a resume re-arms, never assumes |
| `in_review` `substantive_review` `delta_review` | on a tree match, launch the next cycle's fresh reviewer; on a mismatch, discard and restart substantive review |
| `reconcile` | never resume mid-merge: `git merge --abort`, redo from the current tip, and the redo spends one of the two attempts |
| `full_gate` | reachable only when the tree still equals `reviewed_tree` — a mismatch has already sent the run back to `substantive_review` by the rule above. From there, re-run the gate unless a fresh marker names the current tree |
| `pass` | trust the verdict only on a tree match |
| `tree_compare` `push` | check whether the push already landed (`git ls-remote`) before pushing again — the crash may have been *after* it succeeded |
| `tracker_done` `reflect` `cleanup` | every step is idempotent by re-reading, never by assuming |

## Absent, malformed, unknown

- **Absent** — there is no run. Start one and write the file. The test lock is inactive. This is every ordinary session, so it is the cheapest branch.
- **Malformed** — not JSON, not an object, or an unknown `version`. **Stop and hold** (`input`, assigned): a corrupt state file over a worktree holding an unknown amount of work is P4's "continuing would compound a defect", and re-deriving the stage from the tree is a guess. Say in the hold that deleting the file and starting clean is the cheap escape.
- **An unknown `stage`** — the same. The test-lock hook never reads `stage` at all, so a stage-vocabulary change can never alter what it denies.
