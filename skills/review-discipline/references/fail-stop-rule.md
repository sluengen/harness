<!-- guidance:review-discipline-fail-stop-rule@0.1.0 -->
# On a FAIL — the review→fix stop rule

Load this when a review returns **FAIL**. Nothing else routes here: a PASS ends
the loop and a DEFER never entered it, so this is the only verdict that spends a
review→fix cycle.

Return the blocking findings to the builder and re-review. How many times that
may happen is **one policy, owned here**. Every other agent and command points
at the core skill's *On a FAIL* section, which routes here, rather than
restating it; the numbers it names live in `CONTEXT.md` → `loop:` so a repo
tunes its own budget without forking the rule.

A run may spend `loop.max_review_cycles` review→fix cycles in total. Three windows:

- **The unconditional window** — the first `loop.unconditional_review_cycles`. A FAIL here is normal iteration: fix the root cause and re-review, no justification owed. Most work that converges converges inside it.
- **The judged window** — every cycle after that, up to the budget. Before spending one, make a convergence judgment and **write it down**: name which findings are new and which are carried over, and continue only when the findings are peeling back layers and the work is materially approaching PASS. Stop early when the pattern says the problem is the design, the requirements, or the implementation approach rather than the remaining defects — more cycles do not fix any of those. The judgment is recorded so it stays honest rather than optimistic; an unwritten one is reliably a rationalisation for another cycle.
- **Exhausted** — the budget is spent and the last cycle did not PASS. **Stop regardless of how converging it looked.** A run that still reads as converging on its last allowed cycle is exactly the case the budget exists to bound: the read has been wrong every cycle so far.

**An exhausted ticket goes on operator hold — it does not go back to the queue.** Preserve the work (push the branch), then put the ticket in a state the unattended loop will not pick up: apply the operator-hold label **and assign the ticket to the operator**. Assignment is the load-bearing half — `work-discovery` skips an assigned ticket, so this is what stops the next tick re-picking the work and starting a fresh budget on it. A human decides what happens next: re-scope it, split it, or authorise a continuation. Nothing automated may clear the hold or reset the budget, because "start again with five more cycles" is the one outcome that turns a bounded loop back into an unbounded one.

Reach that end state through the `tracker` skill: push the branch, post the reason, apply the `operator` label, assign the operator. The reason is written by you, from the cycle count and the branch — not a paste of the reviewing agent's own prose, which is derived from an untrusted diff.

Nothing enforces this budget mechanically. It is a rule the reviewing agent keeps, which is why the convergence judgment above is written down: the record is the only evidence the window was spent deliberately rather than drifted through.
