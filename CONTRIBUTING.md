# Contributing

Thanks for your interest. First, the honest framing: **this is dogfood
infrastructure.** The harness is an audit/process layer that one maintainer runs
on their own agent-driven development and publishes so others can read, learn
from, and adapt it — not a turnkey product with a support commitment.

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
- **Use the tiers for the fast loop.** Every test is assigned a dependency tier
  at collection — `unit` (nothing outside the process), `guard` (reads the
  checked-out tree) or `integration` (a real repo or worktree, the
  SQLite ledger, a spawned process, or a whole verb through `CliRunner`). Run
  `uv run --extra dev pytest -m "unit or guard"` while iterating: ~2,900 tests
  in about nine seconds, against roughly four minutes to run the whole suite
  serially. Add `-m integration` — or `-m "integration and not docker"` without a
  daemon — for the rest. The tier is *derived* from your module's imports, so
  there is no marker to write; if a `unit`-tier test of yours spawns a process it
  fails with `TierViolationError`, and [`tests/_tiers.py`](./tests/_tiers.py)
  explains the escape hatch. **A tier selection is still not a gate run** —
  `bash scripts/verify.sh` runs everything, and only that counts as verification.
  It does so in two stages: the tests sharing the `harness:test` Docker image tag
  run serially, and the rest run across your cores (about a minute on eight),
  under one coverage floor measured on the union. Set `HARNESS_TEST_WORKERS` to
  override the worker count — `HARNESS_TEST_WORKERS=0` runs in the controller,
  which is how you reproduce a failure that only appears under parallelism.
- **Prove a new guard by mutating what it guards.** A test written after the
  code, or one that was green the moment it was born, has not been shown to
  measure anything. `scripts/mutate.py` runs that proof: you write a TOML table
  of exact edits, each declaring the pytest node ids it must kill, and the
  harness applies them one at a time against a pristine tree.

  ```bash
  uv run python scripts/mutate.py check --table <table>.toml   # lands? costs nothing
  uv run python scripts/mutate.py run   --table <table>.toml   # baseline, then each entry
  ```

  It compares the observed failure set to your prediction by **equality**, which
  is what makes both directions of a dishonest table visible: an edit that
  changes no behaviour kills nothing, and one that breaks collection kills
  everything, and neither can be recorded as the kill it appears to be. It backs
  up every target before touching any and restores only from those backups, and
  it refuses to start against a wrong tree, an ambiguous edit, a red baseline or
  a mistyped prediction. The table stays outside the repo — only the mechanism
  is versioned. Full rationale in the module docstring.

- **Describe the problem and the approach**, not just the diff.

## Inbound licensing

This repo is split: the engine is **AGPL-3.0-only** ([`LICENSE`](./LICENSE)) and
the guidance the installer copies into other repos is **MIT**
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
