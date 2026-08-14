<!-- guidance:harness-routine-quality@0.2.0 -->
# /harness routine quality

This unattended advisory loop catches cumulative code health issues. It never declares attendance and does not block a merge.

- Idle arm: run `/assess code`, action the highest-priority finding, and file the rest through `tracker.create` — each carrying exactly one assurance level chosen per `spec-authoring` → *Choosing assurance* — into the configured project when set, otherwise the tracker's default backlog with no project.
- Weekly arm: run `/assess code --deep`, adding coverage quantity, layer-gated design-system adherence, and spec/doc coherence.

The steward follows `commands/assess.md` and its routed skills. `/assess` commits the dated report directly to the integration branch because the report is the product of the read-only pass; findings live in the tracker. If the pass finds nothing actionable, exit cleanly rather than inventing work.
