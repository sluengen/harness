### None — a test-only tightening of #347's doc guard (no-ticket-repeat-timeout-doc-guard)

`test_the_infra_wall_paragraph_bounds_the_re_run` pinned the bare token `once` as
its proof that `commands/harness.md` bounds the infra-wall re-run. That token is
common enough in running prose to reappear by accident: a rewrite dropping the
bound outright — "re-run it with care", plus an ordinary "read the verdict once
the engine returns" elsewhere in the same region — still satisfied it, verified
by mutating the doc and watching the guard pass. It now asserts the claim the
paragraph makes ("not until it works") instead of a word inside it.

No production code and no user-visible behaviour changes.
