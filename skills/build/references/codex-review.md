# Reviewing with `--engine codex`

Load this only when `--engine codex` was passed.

Claude is the default reviewer sub-agent; this is the alternative, not a
replacement. Resolve the engine at set-up and record which one ran.

Run the independent Codex reviewer from the worktree in a **read-only sandbox**
on the same review packet the Claude reviewer would receive — the ticket and
current change spec, the design artifact where the lane has one, the staged
diff, criterion evidence and lint output, visual evidence where the change is
user-facing, and `reviewed_tree`. Never the implementer's conversation.

- **A usage-limit message triggers the Claude fallback, once.** Fall back to a fresh Claude reviewer sub-agent and record the fallback in the run report.
- **A second malformed invocation is a review finding**, not a second fallback.
- The result must still be one of PASS, FAIL or DEFER. Readiness is not a verdict and is never parsed as one.
