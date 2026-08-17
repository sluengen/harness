# Contributing

Thanks for your interest. First, the honest framing: **this is dogfood
infrastructure.** The harness is a verification layer and a body of guidance that
one maintainer runs on their own agent-driven development and publishes so others
can read, learn from, and adapt it — not a turnkey product with a support
commitment.

## Issues

Issues are welcome — bug reports, questions, and observations all help. Because
this is a single-maintainer project, expect responses to be **best-effort** and
sometimes slow.

## Pull requests

Pull requests are reviewed on a **best-effort** basis. Small, focused PRs with a
clear rationale are the easiest to accept; large or speculative changes may be
declined simply because keeping this coherent for its one operator takes priority.
A decline is not a judgement of the work — fork freely and adapt to taste.

If you do open a PR:

- **Stay in scope and test-first.** The repo builds test-first and runs a gate —
  `uv run --extra dev pytest`, plus `ruff` and `mypy`. See [`CONTEXT.md`](./CONTEXT.md)
  for the exact commands and [`CLAUDE.md`](./CLAUDE.md) for how work happens here.
- **Run the gate, not a subset.** `bash scripts/verify.sh` is the whole contract
  and the only thing that counts as verification: lint, types, the suite across
  your cores under a coverage floor, and the drift guards over the generated
  artifacts. It takes well under a minute. Set `HARNESS_TEST_WORKERS` to override
  the worker count — `HARNESS_TEST_WORKERS=0` runs in the controller, which is
  how you reproduce a failure that only appears under parallelism. (The suite
  used to be split into dependency tiers so a fast loop could skip the slow half.
  #435 deleted the runtime that made half of it slow, so there is no longer a
  subset worth selecting.)
- **Prove a new guard by mutating what it guards.** A test written after the
  code, or one that was green the moment it was born, has not been shown to
  measure anything. `scripts/mutate.py` runs that proof: you write a TOML table
  of exact edits, each declaring the pytest node ids it must kill, and the
  harness applies them one at a time against a pristine tree.

  ```bash
  uv run --extra dev python scripts/mutate.py check --table <table>.toml   # lands? costs nothing
  uv run --extra dev python scripts/mutate.py run   --table <table>.toml   # baseline, then each entry
  ```

  Each entry carries an `id`, the `file` it edits, the exact `old` and `new`
  text, the `kills` it predicts, an optional `note`, and — see below — an
  optional `observe`.

  It compares the observed failure set to your prediction by **equality**:
  exactly the predicted set is `killed`, the only pass, and anything else is
  `mispredicted`, which is how a collection-breaker's several hundred failures
  stop reading as the kill they resemble. A run that could not complete is
  `errored`, never a verdict.

  Killing nothing is where it gets interesting, because that is **not** by itself
  evidence of a weak guard — it is equally an edit that changed nothing, and
  #209 spent two re-derivations learning the difference the expensive way. So an
  entry may declare `observe`, argv appended to this interpreter and run inside
  the tree. On a would-be survivor it runs on both trees and the digests decide:
  differ → `survived`, printed `SURVIVED (LIVE)`, a real gap in the guard; match
  → `inert`, a defect in your table rather than in the guard. With no `observe`
  you get `SURVIVED (UNPROVEN)` — nobody has shown the edit was live, so it is
  not evidence of anything and must not be cited as though it were.

  Exit `0` when every entry killed as predicted, `1` when some did not, and `4`
  when at least one was `inert`. `4` dominates `1`: "your table proved nothing"
  is the louder answer, and it calls for different work.

  It refuses before it writes a byte, in this order: a malformed **table**, a
  **containment** failure (the wrong tree), a **landing** failure (`old` absent
  or ambiguous), a red **baseline**, a mistyped **prediction**, and an unusable
  **observable** (nondeterministic, or already failing on the pristine tree). It
  backs up every target before touching any and restores only from those
  backups. The table stays outside the repo — only the mechanism is versioned.
  Full rationale in the module docstring.

  Before you write the guard the table will prove, read
  [`skills/code-quality/SKILL.md`](skills/code-quality/SKILL.md) Part C, *A guard
  over prose owns structure and negative space, never meaning*. Most of this
  repo's guards read documentation, and that section is what decides whether the
  thing you are about to assert is a test's job at all. A sentence pinned
  verbatim is the one shape that fails both ways — it breaks on a benign
  rewording and stays green when the rule is inverted — so a mutation table over
  it proves only that the bytes are still there. The decision behind the rule,
  and the triage that applied it to the guards already in this tree, are in
  [ADR 0016](specs/decisions/0016-tests-own-structure-and-negative-space.md).

- **Shared test helpers live in underscore modules** — [`tests/_gitutil.py`](tests/_gitutil.py)
  for git, [`tests/unit/_prose.py`](tests/unit/_prose.py) for reading prose out of the
  tree, [`tests/unit/_hooks.py`](tests/unit/_hooks.py) for captured host payloads. The
  moment a second test module needs a helper, the helper moves there; a `test_*.py`
  module is never an import target.

  This is not tidiness. A test module that is also a library cannot be deleted,
  renamed or converted without an importer audit, and #467 found 30 modules
  importing out of their siblings — enough that the ADR 0016 triage had to annotate
  one module "Must keep exporting `_sentences`" in the middle of a pass whose whole
  purpose was deciding what to delete. Helpers whose semantics genuinely differ keep
  their own names in the shared home rather than being unified into one signature;
  helpers local to a single guard stay in that guard.

- **Describe the problem and the approach**, not just the diff.

## Inbound licensing

This repo is split: its own code — the gate, the mutation instrument and the
guard suite — is **AGPL-3.0-only** ([`LICENSE`](./LICENSE)) and the guidance the
installer copies into other repos is **MIT**
([`GUIDANCE-MIT.md`](./GUIDANCE-MIT.md)). A contribution is licensed under
whichever of the two already covers the file it touches.

Beyond that, **by opening a pull request you grant the maintainer a perpetual,
worldwide, irrevocable, royalty-free right to use, modify, relicense and
sublicense your contribution, including under terms other than the two above.**
You keep your copyright — this is a grant, not an assignment, and you can still
do whatever you like with your own work.

**Patents.** You also grant the maintainer and anyone who receives software from
this project a perpetual, worldwide, non-exclusive, no-charge, royalty-free,
irrevocable patent licence to make, have made, use, offer to sell, sell, import
and otherwise transfer your contribution. That licence covers only the patent
claims you can license which your contribution — alone, or combined with this
project — necessarily infringes. It is not a licence to your patent portfolio at
large. If any entity starts patent litigation alleging that your contribution or
this project infringes a patent, the patent licences granted to **that entity**
under this section end on the day the suit is filed. (This is Apache-2.0's
arrangement, near enough its wording.)

**Your right to submit.** You represent that each contribution is your own
original work, or that you otherwise have the right to submit it under the terms
above; that you are legally entitled to grant these rights — in particular, if
your employer has rights to work you produce, that you have their permission to
contribute, or they have waived those rights; and that you are not knowingly
including third-party material under terms incompatible with the licences above.
If a contribution does contain third-party material, identify its source and
licence in the pull request. Contributions are provided as-is, with no warranty
of any kind — you are giving code away, not taking on an obligation.

The patent and right-to-submit paragraphs are ordinary — they are what every
contributor agreement says, and near enough Apache's words for a reason: standard
text has been argued over for twenty years, and something drafted fresh here would
only be worse.

The **relicensing** grant is the unusual one, so here is why, plainly rather than
buried. Copyright in this repo currently sits with one person, which is what makes
it possible to offer someone a licence other than the AGPL later — a commercial
exception, say, or a move to a different licence entirely if the AGPL turns out to
be the wrong call. Absent that grant, contributions arrive AGPL-only, the
copyright becomes shared, and that option closes permanently the first time an
outside PR is merged, because no one can relicense code they do not own.

If you would rather not give any of this, say so in the PR — the change can still
be discussed, and small fixes are easy to reimplement independently.

## Security

For anything security-sensitive, do **not** open a public issue — follow
[`SECURITY.md`](./SECURITY.md) to report it privately.
