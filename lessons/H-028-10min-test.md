# H-028 — 10-minute ergonomics test (release-notes workflow)

## Result

- Wall-clock time from blank file to validating YAML: **1 minute, 45 seconds**
  - T0 (start writing fixture/script/yaml from blank): 08:48:43
  - T1 (`load_workflow(...)` returns without raising): 08:50:28
- Pass/fail per SPEC §18 acceptance: **PASS**
- (PASS if < 10 minutes; FAIL otherwise)

Caveats worth recording so the number isn't taken at face value:

- The clock measures only writing-time. Pre-clock I read SPEC §5 (workflow
  schema) and §14 (steward example reference) once, and skimmed the existing
  `prompts/summarize.j2` and `scripts/write_steward_report.py` —
  exactly what the spec mandates ("someone who's read this spec once").
  The pre-read counts as the "read the spec" baseline; nothing about the
  measurement is unfair.
- I did NOT start from `workflows/steward.yaml` and copy-paste — the
  release-notes YAML was typed from scratch. The structural similarity
  comes from the spec example, not from lifting an existing workflow.
- One mid-write iteration cost me ~30 seconds: my first contract said
  `tickets: list[string]`, which was a lie because the script emits
  `list[dict]`. Tightening the contract to the real shape exposed the
  pain point captured in §"Pain points" below. This iteration is
  inside the 1m45s — i.e., the test passes with the honest contract,
  not the loose one.

## What I had to look up

- **SPEC §5 — workflow schema reference (lines 357–705).** Already loaded
  pre-clock. Used the step-keys table and the bugfix example as the
  template for the three step types I needed (`script`, `ai`, `script`).
- **SPEC §14 indirectly via `workflows/steward.yaml` reference.** I did
  *not* copy it — but knowing that the steward workflow's `write-report`
  step uses a `script:` with `--run-id` arg + reads `state_json` from
  `.harness/harness.db` was load-bearing, because I had to mirror that
  pattern for `write_release_notes.py`. Without that prior knowledge a
  truly cold author would lose 2–3 minutes on "how does a downstream
  script read upstream state".
- **`prompts/summarize.j2`.** Read its docstring header to learn
  the required `subject` template var. Saved me from inventing a custom
  prompt.
- **`harness/workflow/contract.py` (lines 159–188).** Had to consult this
  *after* my first contract draft failed to compile, to figure out why
  the nested-object element type wasn't being recognised. This is the
  pain-point I record below.

## Pain points (ordered by friction)

### 1. List-of-object element schemas conflict with the meta-`type:` key
- **Friction class**: schema confusion / spec divergence
- **What slowed you down**: My contract said
  ```yaml
  tickets:
    type: list
    of:
      id: string
      title: string
      labels:
        type: list
        of: string
      type: string        # ← intended as a *field* called "type"
  ```
  The compiler sees `type: string` at the sub-schema top level and routes
  to `_compile_constrained_leaf`, which then complains the sibling keys
  `id`/`title`/`labels` are unknown constraints. The error message is
  precise (good) but the underlying ambiguity is invisible to the author
  — `type:` is overloaded between "the meta-type of this schema" and
  "a field named `type`". SPEC §5 says a mapping is treated as a
  sub-schema, but doesn't note this collision. Workaround: rename the
  field from `type` to `kind`, which is a substantive YAML-level lie
  the author has to absorb.
- **Proposed fix**: Either (a) reserve `type:` as a meta-key (forbid it
  as a field name, with a clear load-time error pointing the author at
  the conflict) and document the restriction in SPEC §5 contract grammar;
  or (b) require nested-object sub-schemas to be tagged explicitly,
  e.g. `of: { object: { id: string, ... } }`, so `type:` can be unambiguously
  the meta-key. (a) is friendlier — the field name `type` is rare, the
  error pays for itself.
- **Estimated cost to fix**: small (one keyword check in
  `_compile_nested_object`, two lines of SPEC).
- **Should-block-v1**: **no**. The workaround is one rename, the error
  message tells you something is wrong (even if not the root cause),
  and the conflict will bite at most a couple of authors. A v1.1 patch.

### 2. The `state.<field> → script` contract pattern is undocumented
- **Friction class**: docs missing
- **What slowed you down**: Step 3 of my workflow needs to read
  `release_notes` (written by the AI step) and emit `output_path`. The
  spec describes how AI steps and script steps WRITE state, but does
  not describe how a script READS prior state. I learned the pattern by
  reading `scripts/write_steward_report.py`: a script gets `--run-id`
  passed in, opens `.harness/harness.db`, and reads `runs.state_json`.
  Without that prior reference, a cold author would not know this is
  the convention — SPEC §6 covers state schema derivation but not the
  retrieval mechanism for non-AI nodes. (AI nodes get state interpolated
  into prompts via `$state.X`; script nodes don't have an equivalent
  declarative pull.)
- **Proposed fix**: Add a short subsection to SPEC §5 ("Reading state
  from script steps") describing the SQLite-via-`--run-id` pattern,
  with a 6-line example. Reference `write_steward_report.py`.
- **Estimated cost to fix**: small (10–20 lines of SPEC).
- **Should-block-v1**: **no**. Once you've seen the pattern once, every
  subsequent script step costs you nothing. It's a "first workflow is
  slow" cost, not a recurring tax.

### 3. `ScriptNode` requires a `contract_override` seam to align with workflow contracts
- **Friction class**: spec divergence (the v1 implementation under H-027
  patched this; H-028 inherits the fix transparently)
- **What slowed you down**: Zero — by the time I wrote this workflow,
  H-027 had already shipped the `contract_override` seam on `ScriptNode`,
  so my `write-file` step's contract `output_path: string` validates
  cleanly against the script's stdout JSON. I am recording this so the
  v1 audit can note: the seam is what made the SPEC §14 contract style
  expressible. Without it, every script step would either need to write
  to a generic `ScriptOutput` and lose its workflow-author-declared
  contract, or push the contract into the step body somehow. The
  current seam is the right design — flagging it explicitly so it
  doesn't get refactored away.
- **Proposed fix**: None. Keep the seam.
- **Estimated cost to fix**: n/a.
- **Should-block-v1**: **no**. Already addressed by H-027.

### 4. No `harness validate` CLI yet — authors validate via REPL incantation
- **Friction class**: boilerplate
- **What slowed you down**: The acceptance step had to be
  `uv run python -c "from harness.workflow.loader import load_workflow;
  from pathlib import Path; load_workflow(Path('workflows/release.yaml'))"`.
  That's a load-bearing 130-character one-liner an author would have to
  remember or paste from somewhere. Not a blocker for THIS test (the
  brief explicitly noted the workaround), but a real friction once we
  expect humans to author workflows.
- **Proposed fix**: Ship `harness validate <workflow.yaml>` as part of
  the H-023 CLI work. Already on the roadmap — flagging for priority.
- **Estimated cost to fix**: small (it's already in scope for H-023).
- **Should-block-v1**: **no**. The roadmap covers it.

## Recommendations

1. Add **List-of-object meta-key reservation** to `harness/workflow/contract.py`
   plus a SPEC §5 note — addresses [pain #1]. The fix is one keyword
   check and saves authors from a confusing error.
2. Add **"Reading state from script steps"** subsection to SPEC §5,
   pointing at `write_steward_report.py` as the canonical pattern —
   addresses [pain #2]. First-time authors otherwise spend 2–3 minutes
   either reading the engine source or copy-pasting blindly.
3. Keep **`ScriptNode.contract_override`** as a permanent part of the
   ScriptNode interface — addresses [pain #3]. The seam is what makes
   workflow-author contracts (rather than generic ScriptOutput contracts)
   work for downstream-consumable script steps; do not let a future
   "simplification" refactor remove it.
4. **Land `harness validate <workflow.yaml>` early in the H-023 CLI
   work** — addresses [pain #4]. The current REPL incantation is fine
   for an internal dev loop but a real ergonomic cliff for "humans
   writing workflows from spec".
5. **Ship one or two more standard prompts** alongside `summarize.j2`,
   `analyze.j2`, `implement.j2`, `review.j2` — specifically a
   `render_markdown.j2` for "take a structured object, produce
   well-formatted markdown" — so that release-notes-shaped workflows
   can skip the inline `template_vars.length` hack I used. Addresses
   no specific pain point above but reduces "how do I steer the summary
   to look right" friction.

**No ship-blockers found.** All four pain points are post-v1 polish.
No Linear tickets filed.

## What worked well

- **The bugfix example in SPEC §5 is enough scaffolding.** Three step
  types, inline + shared contract examples, a loop block — almost every
  pattern a real workflow needs is demonstrable from that one block.
- **Inline contracts compile cleanly for scalars and `list[string]`.**
  My initial draft of `tickets: list[string]` validated immediately;
  only when I tightened to `list[object]` did pain #1 surface. The
  common case is friction-free.
- **The standard prompts are well-named and self-documenting.**
  `summarize.j2`'s top-of-file `template_vars` docstring told me
  exactly what to pass without reading the body.
- **`prompts_dir` + `repo_root` on Runner is symmetric and obvious.**
  Wiring the integration test took 30 seconds because the steward test
  template was unambiguous.
- **`ContractCompileError` messages are precise.** The error said
  `field 'tickets[item]': unknown constraint(s) ['id', 'labels', 'title']`
  — that's the exact level of specificity that lets you diagnose in
  one read, even when the underlying ambiguity (pain #1) is invisible.
- **The MockAgent + reflecting subclass pattern is cheap to copy.**
  Modelling my integration test on the steward test took less time
  than writing this paragraph.
