<!-- guidance:code-quality@0.1.1 -->
# Code Quality

How to build well during implementation: stay in scope, keep the structure sound, and prove the work before claiming it done. The developer follows this while building; the reviewer enforces the same rules (`code-review` references this file, so the bar is identical on both sides).

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

One condition is usually enough. Removing code is often the answer. New abstractions, layers, and helpers are justified by the task, not introduced speculatively. This is not licence to leave work half-done: if the spec calls for a helper or a missing primitive, build it. The rule is *don't add what wasn't asked for; do build what the task requires.*

### Carry-forward, not silent cleanup

When you spot something genuinely worth fixing but out of scope, do not fix it silently. Note it for the reviewer (a line in the handoff). The reviewer decides whether it becomes its own ticket. The exception: once the reviewer flags a small fix on code you already touched, do it in the same pass.

---

## Part B — Structure

Defaults below. A repo may override the numbers in `CONTEXT.md`; the principles do not change.

### Size

| Unit | Soft (consider splitting) | Hard (split, or justify in a comment) |
|---|---|---|
| Module / component / file | 300 lines | 500 lines |
| Single function / handler | 40 lines | 60 lines |

Declarative files (schemas, type definitions, token maps) get a higher ceiling: their length is field lists, not logic.

### Boundaries

Maintain the layer separation the repo declares (a common shape: transport → service/domain → data access → model). No business logic in a transport handler. No transport concepts (request, response, status code) in a service. No queries scattered outside the data layer. Name the layer before you edit it (Part A).

### Extract on the third strike

If a load-bearing pattern (a parse routine, a permission check, a fetch-plus-loading-plus-error shape) appears three times, extract it. Twice is a coincidence; three times is duplication. Put pure logic in a lib/util, behaviour in a hook/service, shared UI in a component. Do not extract earlier (`engineering-principles`: no premature abstraction).

### Compose, don't inline

Top-level units are composers: they fetch, manage top-level state, and assemble smaller pieces. They do not inline 500 lines of rendering or 50 fields of form parsing. When a unit mixes two concerns, split by concern, named by the symbols that handle each.

---

## Part C — Verification

**No completion claim without fresh evidence.**

Any statement implying the work is finished ("done", "fixed", "passing", "ready for review", "all green") requires that you *just ran* the verifying command and *read* its output in this session.

### The gate, in order

1. **Identify** the command that proves the claim (see `CONTEXT.md` for the repo's lint / type / test commands).
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
| Ready for review | All of the above that apply |

Skipping a step is not efficiency. It is claiming something you have not checked.
