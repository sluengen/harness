# Reviewing with `--engine codex`

Load this only when `--engine codex` was passed.

Claude is the default reviewer sub-agent; this is the alternative, not a
replacement. Resolve the engine at set-up and record which one ran.

Run the independent Codex reviewer from the worktree in a **read-only sandbox**
on the same review packet the Claude reviewer would receive, which
`agents/reviewer.md` → *Your context is the packet* defines, plus the two this
engine adds: the committed candidate's lint output and `reviewed_tree`.
**A read-only sandbox cannot run the gate**, so the review stage's complete gate is
the driving run's on this engine, at the point a reviewer would run its own: once
the Codex reviewer returns no blocking finding, run `commands.verify` over
`reviewed_tree` and read all of it. Red is a FAIL for this cycle; green completes
the review stage's evidence and is its full-suite claim. A cycle that FAILs on
findings runs no gate, as on the default engine. Never the
implementer's conversation. A second list drifts from the first, and this one
had: it named the lint output and omitted the canonical record.

- **A usage-limit message triggers the Claude fallback, once.** Fall back to a fresh Claude reviewer sub-agent and record the fallback in the run report.
- **A second malformed invocation is a review finding**, not a second fallback.
- The result must still be one of PASS, FAIL or DEFER. Readiness is not a verdict and is never parsed as one.
