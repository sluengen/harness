---
name: code-quality
description: Use while implementing or modifying code, and again before claiming any task done. Covers scope discipline, code structure, and the verification gate — no completion claim without fresh evidence, and a measurable acceptance criterion (query count, latency, payload size, error rate) needs a test that measures it.
---
# Code Quality

How to build well during implementation: stay in scope, keep the structure sound, and prove the work before claiming it done. The developer follows this while building; the reviewer enforces the same rules (`review-discipline` references this file, so the bar is identical on both sides).

Three parts: **Scope**, **Structure**, **Verification**. They run in that order during a task.

---

## Part A — Scope

**Read first. Touch only what the task requires. Defer everything else.**

Agents drift in two predictable ways: patching off the first plausible read, and reshaping nearby code nobody asked them to touch. Both inflate blast radius.

### Before editing

1. **Read the canonical files.** The change spec, the module(s) you will change, and at least one existing call site. The files, not summaries.
2. **Name the current pattern in one sentence.** "This module does X by Y; the failing case is Z." If you cannot, you do not understand it well enough to change it. Read more.
3. **Confirm the task targets that pattern.** A plausible edit on the wrong layer is the most expensive bug to undo. If the task and the code disagree on where the change belongs, surface it before editing.

### Bound the surface

Before each edit, ask: is this file *required*, or just *tempting*?

- **Required** = the task cannot be completed without changing it.
- **Tempting** = nearby, slightly wrong, "while I'm here". Leave it alone.

Specifically, unless the task asks for it: do not rename in untouched paths, do not reformat or remove dead code in files you did not need to open, do not refactor adjacent code into shared helpers, and do not commit files that appeared in `git status` from another session. A surprise file in the diff is a signal to investigate, not to commit.

### Smallest working solution

The build-time application of `engineering-principles`' *smallest change that satisfies the spec*. One condition is usually enough. Removing code is often the answer. New abstractions, layers, and helpers are justified by the task, not introduced speculatively. This is not licence to leave work half-done: if the spec calls for a helper or a missing primitive, build it. The rule is *don't add what wasn't asked for; do build what the task requires.*

### Placeholder and stub gating

A function that returns hardcoded/faked/placeholder data in place of real logic (an OCR/share/scan stub, a `TODO: replace` body) must not be reachable from a user-facing control unless gated behind an off-by-default feature flag. Wire the flag or remove the control; do not ship a CTA whose implementation is a constant. Two instances one day apart in one repo — a share-card stub and an OCR stub, both wired to live, ungated surfaces, both filed after the fact rather than caught at merge — is the evidence for codifying this now rather than waiting for a third.

### Grep before writing a helper

Before writing a helper, grep the sibling modules for the concern it handles. If a near-identical helper exists in one other place, name it in the change spec and say why the copy is justified. If it exists in two, extract it — the third copy is not a judgement call. Per-ticket review sees only its own diff, so "consider extracting" is not enough to catch a duplication that accumulates one small, individually-reasonable copy at a time — a numeric threshold, checked before the helper is written, is what makes it checkable.

### Read the generated artifact, don't re-derive it

When the fact you need is already written by a generator to a committed artifact that carries its own drift test, read that artifact; never re-derive the fact from the generator's source inputs. The drift test guards the artifact, not your derivation, so a second derivation needs its own hand-maintained parallel inventory, told about a new input only when someone remembers. Write a new parser only where the artifact cannot carry the shape you need, and justify it in the change spec, naming what the artifact omits. Two implementations of one screen-graph consumer, a week apart against one generated flow graph — reading the artifact picked up new routes for free, re-parsing the source drifted within three tickets — are the evidence.

### A removal sweeps for its dependents

A deletion looks finished the moment the code is gone — but it is only half-done if its dependents still point at the removed name. **A removal is not complete until you grep for the removed name — constraint names in exception handlers, feature names in config / testpaths / docs — and delete or update every dependent. The diff of a removal should include its dependents.** What survives otherwise is dead contract: a handler guarding a constraint that no longer exists, a config key for a deleted feature, a doc describing a path that is gone. Grep the name; the diff is the proof the sweep happened.

### An extraction sweeps for its copies

The mirror image of a removal. An extraction is not complete until you grep the whole tree for the extracted pattern — not just the locations the ticket or finding named. A finding's location list is a starting point, not the boundary; it is only ever as wide as the grep that produced it. **Diff every copy you find against the body you are making canonical before you delete it: a copy whose body *differs* is the finding, not the leftover.** A surviving copy with a divergent body is strictly worse than the duplication you set out to remove, because the extraction's green diff now certifies a unification that did not happen.

### Carry-forward, not silent cleanup

When you spot something genuinely worth fixing but out of scope, do not fix it silently. Note it for the reviewer (a line in the handoff). The reviewer decides whether it becomes its own ticket. The exception: once the reviewer flags a small fix on code you already touched, do it in the same pass.

---

## Part B — Structure

Defaults below. A repo may override the numbers in `CLAUDE.md`; the principles do not change.

### Size

| Unit | Soft (consider splitting) | Hard (split, or justify in a comment) |
|---|---|---|
| Module / component / file | 300 lines | 500 lines (justify or ticket — see Part C) |
| Single function / handler | 40 lines | 60 lines |

Declarative files (schemas, type definitions, token maps) get a higher ceiling: their length is field lists, not logic. When a repo mechanizes the file-size limit in its linter, it declares the declarative globs as an `overrides` entry carrying the higher ceiling **in the same change**. An exemption that lives only in this skill's prose is not enforceable, and will surface as a gate failure on a commit that has nothing to do with file size. Default the declarative ceiling to 1.5x the hard limit unless the repo sets its own.

### Boundaries

Maintain the layer separation the repo declares (a common shape: transport → service/domain → data access → model). No business logic in a transport handler. No transport concepts (request, response, status code) in a service. No queries scattered outside the data layer. Name the layer before you edit it (Part A).

### Extract on the third strike

If a load-bearing pattern (a parse routine, a permission check, a fetch-plus-loading-plus-error shape) appears three times, extract it. Twice is a coincidence; three times is duplication. Put pure logic in a lib/util, behaviour in a hook/service, shared UI in a component. Do not extract earlier (`engineering-principles`: no premature abstraction).

A permission check, an auth gate, or a domain rule that must stay in sync extracts on the **second** copy — two copies that can drift are already a latent bug, so the coincidence allowance does not apply to them.

A comment that says a helper, component, or module **mirrors**, **duplicates**, or must be **kept in sync with** a sibling is the third strike on its own. That comment is an explicit admission of duplication — you have already named the original — so the count no longer matters: extract it to its shared home **now**, regardless of how small each copy is. The admission is the trigger, not the size; the rule-of-three threshold cannot see a duplication that each copy keeps individually tiny, but the comment names it outright. The trigger applies to a duplicated rendering/structural shell exactly as it applies to a duplicated function — a component or screen carrying the admission is caught the same as a helper.

### Compose, don't inline

Top-level units are composers: they fetch, manage top-level state, and assemble smaller pieces. They do not inline 500 lines of rendering or 50 fields of form parsing. When a unit mixes two concerns, split by concern, named by the symbols that handle each.

### Conditional checks

When code fetches a URL derived from user input, third-party pages, or
page-declared content, load [`skills/code-quality/references/untrusted-fetch.md`](references/untrusted-fetch.md).
For security-control tests, files over the hard limit, guards over derived sets,
cross-layer aggregates, or nullable narrowing, load
[`skills/code-quality/references/specialized-verification.md`](references/specialized-verification.md)
and apply only the matching section.

---

## Part C — Verification

**No completion claim without fresh evidence.**

Any statement implying the work is finished ("done", "fixed", "passing", "ready for review", "all green") requires that you *just ran* the verifying command and *read* its output in this session.

### The gate, in order

1. **Identify** the command that proves the claim (see `CLAUDE.md` for the repo's lint / type / test commands).
2. **Execute** it now. Not "I ran it earlier" — you have changed code since.
3. **Read** the full output: exit code, pass/fail counts, warnings.
4. **Verify** the output actually supports the claim. "5 passed, 1 skipped" means explain the skip. A warning means investigate it.
5. **Then claim.**

### Order matters

Lint first, then type-check (if the language has a separate one), then tests. Each is a blocker. Do not run the slow gate on code the fast gate already rejects.

| Claim | Required evidence |
|---|---|
| Tests pass | Full suite run, output shown |
| Lint clean | Linter run, output shown |
| Bug fixed | The regression test, shown passing |
| Measurable criterion met ("≤ N queries", "< X ms") | A test that measures that quantity, shown asserting the bound |
| Ready for review | All of the above that apply |

Skipping a step is not efficiency. It is claiming something you have not checked.

### A measurable criterion needs a measuring test

When an acceptance criterion is stated as a quantity — "uses N queries instead of M", "responds in under X ms", "at most N requests", a cache-hit or error rate — the only evidence is a test that *measures that quantity* and asserts the bound. A structural change that ought to reduce it is not proof that it did. Write the test that counts the thing (queries, calls, allocations, bytes) and fails outside the bound; the measurement tool is repo-specific (`CLAUDE.md`).

### A new guard cites the occurrence it prevents

A guard earns its place by naming the defect that already happened: the entry in `skills/review-discipline/references/craft.md` whose class it belongs to, or the incident — the red gate, the shipped defect, the ticket — where the class was observed in this tree. Write that citation beside the assertion, in the guard's docstring or its comment, where the next reader deciding whether it still earns its keep will find it. A guard nobody can trace to an occurrence is **speculative**, and a speculative guard costs the same to read, run, and maintain as a real one while defending nothing that has ever gone wrong.

The rule has a consequence worth taking, and it runs backwards over the guards already in the tree: an architecture assessment can read a guard with no citable occurrence as a **deletion candidate** rather than as untouchable prose. That is what makes the rule affordable — it prunes as well as it gates, so the corpus does not simply grow one well-intentioned guard at a time.

### A guard over prose owns structure and negative space, never meaning

A test that reads documentation can assert two things honestly: what the prose must **not** contain (retired vocabulary, a forbidden identifier, a path that does not install into a consuming repo), and what must structurally **correspond** (a mirror is byte-identical, a version matches its manifest entry, a generated artifact matches its source). Whether the prose affirmatively **says** the right thing is the reviewer's, because no regex reads meaning.

That is why pinning a sentence is the worst of both worlds. The pin is **brittle** — a benign rewording that preserves the rule exactly breaks the build — and **vacuous** at the same time, because an edit can satisfy the pinned bytes while inverting the rule in the next paragraph. Term co-occurrence is no better: co-occurrence has no direction, so the guard passes just as green when the rule is reversed.

Where a rule is load-bearing enough to deserve a tripwire, write the minimal one: the section exists in its canonical home, plus at most a small term set the rule cannot be stated without, plus the negation token inside the match window where the rule has a polarity. **One tripwire per rule-home, not per sentence.** And apply the same test to the tripwire itself — if you cannot distinguish the defect from legitimate prose without an exemption list, the guard is asserting meaning and belongs to the reviewer instead.

### A green suite is only evidence if its inputs are real

A passing test proves nothing when it feeds the code inputs or events no production path emits: it exercises a branch the live system never reaches and reports false confidence. Before a green run counts as evidence, confirm each test drives on what real code actually produces, not on synthesized data (`test-driven-development`).
