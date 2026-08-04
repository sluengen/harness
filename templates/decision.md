<!-- guidance:template-decision@0.2.0 -->
# Decision block (embeddable)

A consequential decision is **not a standalone file** unless the repo declares `paths.decisions`. Paste this block into the spec it governs — a feature decision into that feature spec, a cross-cutting one into the architecture-principles spec (`spec-authoring`, `architecture`). Keep the what and the why together. Drop sub-headings the decision does not need.

Where a repo *has* configured a decision directory, these same four parts are the **body** of the record filed there: only decisions that are cross-cutting, consequential, and expensive to reverse qualify, and the repo's architecture index owns the naming and numbering.

---

### Decision: {short title — the choice made, e.g. "Rename water_weight_g → water_g"}

*Decided {YYYY-MM-DD}.*

**Context.** What forced the choice — the specific problem, the constraints that were non-negotiable, what happens by default if nothing is decided. Be specific.

**Decision.** What was chosen, in one or two sentences. State it plainly.

**Alternatives.** What was considered and rejected, and why. Undocumented rejections get relitigated.
- *{Option}* — {what it was} · {why it lost}

**Consequences.** What this enables, what it costs or constrains, what it forecloses or makes necessary next.

---

**Superseding.** When this decision changes, update it in place: replace the decision text and add a dated note — *"Superseded {date}: previously X; changed to Y because Z."* Then update any code/specs that relied on the old choice. The spec shows the current decision with its history inline, not a chain of separate files.
