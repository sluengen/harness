# Reviewing with `--engine codex`

Load this only when `--engine codex` was passed.

Claude is the default reviewer sub-agent; this is the alternative, not a
replacement. Resolve the engine at set-up and record which one ran.

Run the independent Codex reviewer from the worktree in a **read-only sandbox**
on the same review packet the Claude reviewer would receive, which
`agents/reviewer.md` → *Your context is the packet* defines, plus what this
engine adds: the committed candidate's lint output, its complete gate output, and
`reviewed_tree`. **A read-only sandbox cannot run the gate**, so on this engine the
builder still runs `commands.verify` over the committed candidate before hand-off,
as every builder did before #731, and the reviewer judges that output — say so in
the packet, as context, so it does not try a gate its sandbox would fail; `/promote`
always runs its own landing gate after a review on this engine. Never the
implementer's conversation. A second list drifts from the first, and this one
had: it named the lint output and omitted the canonical record.

- **A usage-limit message triggers the Claude fallback, once.** Fall back to a fresh Claude reviewer sub-agent and record the fallback in the run report.
- **A second malformed invocation is a review finding**, not a second fallback.
- The result must still be one of PASS, FAIL or DEFER. Readiness is not a verdict and is never parsed as one.
