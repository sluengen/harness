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
- **Describe the problem and the approach**, not just the diff.

## Security

For anything security-sensitive, do **not** open a public issue — follow
[`SECURITY.md`](./SECURITY.md) to report it privately.
