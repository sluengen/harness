---
name: code-quality
description: Use while implementing or modifying code, and again before claiming any task done. Covers scope discipline, code structure, and the verification gate — no completion claim without fresh evidence, and a measurable acceptance criterion (query count, latency, payload size, error rate) needs a test that measures it.
---
<!-- guidance:code-quality@0.14.0 -->
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

### Grep before writing a helper

Before writing a helper, grep the sibling modules for the concern it handles. If a near-identical helper exists in one other place, name it in the change spec and say why the copy is justified. If it exists in two, extract it — the third copy is not a judgement call. Per-ticket review sees only its own diff, so "consider extracting" is not enough to catch a duplication that accumulates one small, individually-reasonable copy at a time — a numeric threshold, checked before the helper is written, is what makes it checkable.

### A removal sweeps for its dependents

A deletion looks finished the moment the code is gone — but it is only half-done if its dependents still point at the removed name. **A removal is not complete until you grep for the removed name — constraint names in exception handlers, feature names in config / testpaths / docs — and delete or update every dependent. The diff of a removal should include its dependents.** What survives otherwise is dead contract: a handler guarding a constraint that no longer exists, a config key for a deleted feature, a doc describing a path that is gone. Grep the name; the diff is the proof the sweep happened.

### An extraction sweeps for its copies

The mirror image of a removal. An extraction is not complete until you grep the whole tree for the extracted pattern — not just the locations the ticket or finding named. A finding's location list is a starting point, not the boundary; it is only ever as wide as the grep that produced it. **Diff every copy you find against the body you are making canonical before you delete it: a copy whose body *differs* is the finding, not the leftover.** A surviving copy with a divergent body is strictly worse than the duplication you set out to remove, because the extraction's green diff now certifies a unification that did not happen.

### Carry-forward, not silent cleanup

When you spot something genuinely worth fixing but out of scope, do not fix it silently. Note it for the reviewer (a line in the handoff). The reviewer decides whether it becomes its own ticket. The exception: once the reviewer flags a small fix on code you already touched, do it in the same pass.

---

## Part B — Structure

Defaults below. A repo may override the numbers in `CONTEXT.md`; the principles do not change.

### Size

| Unit | Soft (consider splitting) | Hard (split, or justify in a comment) |
|---|---|---|
| Module / component / file | 300 lines | 500 lines (justify or ticket — see Part C) |
| Single function / handler | 40 lines | 60 lines |

Declarative files (schemas, type definitions, token maps) get a higher ceiling: their length is field lists, not logic.

### Boundaries

Maintain the layer separation the repo declares (a common shape: transport → service/domain → data access → model). No business logic in a transport handler. No transport concepts (request, response, status code) in a service. No queries scattered outside the data layer. Name the layer before you edit it (Part A).

### Extract on the third strike

If a load-bearing pattern (a parse routine, a permission check, a fetch-plus-loading-plus-error shape) appears three times, extract it. Twice is a coincidence; three times is duplication. Put pure logic in a lib/util, behaviour in a hook/service, shared UI in a component. Do not extract earlier (`engineering-principles`: no premature abstraction).

A comment that says a helper **mirrors**, **duplicates**, or must be **kept in sync with** a sibling is the third strike on its own. That comment is an explicit admission of duplication — you have already named the original — so the count no longer matters: extract the helper to its shared home **now**, regardless of how small each copy is. The admission is the trigger, not the size; the rule-of-three threshold cannot see a duplication that each copy keeps individually tiny, but the comment names it outright.

### Compose, don't inline

Top-level units are composers: they fetch, manage top-level state, and assemble smaller pieces. They do not inline 500 lines of rendering or 50 fields of form parsing. When a unit mixes two concerns, split by concern, named by the symbols that handle each.

### Fetching untrusted URLs

The concrete application of `engineering-principles`' *Validate at boundaries, trust within* to the network-fetch boundary. When code issues a request to a URL drawn from untrusted content — a third-party page, a user-supplied link, a page-declared asset — the fetch itself is the boundary and the URL is hostile until proven otherwise. Before a batch or single fetch surface ships, it carries four checks:

1. **Scheme allowlist.** Accept `http`/`https` only for any URL derived from untrusted content; reject `file:`, `data:`, `gopher:`, and every other scheme outright.
2. **Host allowlist / reject internal addresses.** Refuse loopback, private, link-local, reserved, and cloud-metadata addresses (the SSRF surface) — an allowlist of expected hosts where one exists, an explicit denylist of those ranges otherwise.
3. **Download size cap.** Stream the body and abort once it passes a byte cap; never buffer a whole untrusted response into memory.
4. **Decompression / pixel cap; re-validate after redirects.** Bound the *decoded* size of compressed or media payloads (a decompression and pixel cap, not just the wire size), and re-run checks 1–2 on the final URL after every redirect — a redirect target is as untrusted as the original.

The principle has one home in `engineering-principles`; this checklist is its build-time application at the fetch boundary, so the reviewer (`review-discipline`, which shares this file's bar) and the next fetch surface both get a concrete bar by default.

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
| Measurable criterion met ("≤ N queries", "< X ms") | A test that measures that quantity, shown asserting the bound |
| Ready for review | All of the above that apply |

Skipping a step is not efficiency. It is claiming something you have not checked.

### A measurable criterion needs a measuring test

When an acceptance criterion is stated as a quantity — "uses N queries instead of M", "responds in under X ms", "at most N requests", a cache-hit or error rate — the only evidence is a test that *measures that quantity* and asserts the bound. A structural change that ought to reduce it is not proof that it did. Write the test that counts the thing (queries, calls, allocations, bytes) and fails outside the bound; the measurement tool is repo-specific (`CONTEXT.md`).

### A security-contract test asserts the predicate, not the name

When a test proves a security control is in place — an RLS policy, an auth guard, a CSP directive, a permission grant — asserting that the control *exists* (by name, by presence in a list) proves only that someone typed the right string. Assert what it evaluates to: the policy's `USING`/`WITH CHECK` expression, the guard's refusal, the directive's value. Pair it with a negative fixture whose control is present but *wrong*, and watch the test fail.

### A green suite is only evidence if its inputs are real

A passing test proves nothing when it feeds the code inputs or events no production path emits: it exercises a branch the live system never reaches and reports false confidence. Before a green run counts as evidence, confirm each test drives on what real code actually produces, not on synthesized data (`test-driven-development`).

### A file over the hard limit is an auditable choice, not silent drift

A file past the hard line limit (Part B — 500 lines for a module/file by default) must carry, at its top, a one-line size justification: a language-native comment containing `size: <reason>` (`# size: <reason>` in Python or shell, `// size: <reason>` in JS/TS/C, `/* size: <reason> */` in CSS), or reference an open tracking ticket. The reviewer **rejects** an over-limit file that has neither. An unjustified over-limit file is silent drift: the steward re-finds it every assessment cycle, and no one ever decided it should grow. The `size:` line (or the ticket) records that decision and makes it auditable — the same standard the hard-limit cell in Part B implies, made concrete and enforced at review.

Marker *presence* and marker *substance* are checked differently, and only presence is mechanizable. **Presence** — that an over-limit file carries a `size:` marker or a ticket at all — should be checked by a repo test that walks the source tree, counts lines, and fails any over-limit file carrying neither, so the rule is enforced at the gate at commit time rather than waiting for a reviewer to remember it or the steward's next pass (the walker's config — limit, globs, the higher declarative-file ceiling from Part B — is set as constants the adopting repo edits in its copy, defaulting to the numbers here; a reference implementation ships in `templates/size-guard.md`). **Substance** — whether the `size:` reason names a real cohesion argument or is a rubber stamp — no test can score; that stays reviewer judgment, audited by the steward on assessment passes. Presence is mechanized; substance is judged. The tripwire's value is that the decision gets recorded, not that the file stays small — cohesion itself is reviewer judgment plus the architecture watchlist.

### Re-deriving what another layer owns is an auditable choice, not a default

When a change adds code that aggregates — averages, sums, counts, groups — over a collection it fetched from a layer that already owns that domain (Part B — Boundaries; `CONTEXT.md` names the layers this repo declares), the change spec must name why the owning layer does not own the aggregate, or reference the ticket that moves it. The reviewer **rejects** a re-derivation that names neither.

This is the duplication that review is least equipped to catch, because nothing is wrong yet when it lands. A re-derivation is correct in isolation and its change looks complete: the numbers agree on the day it ships. It turns into a defect only once a sibling surface renders the owning layer's number for the same quantity beside it — and then the two contradict each other while neither change is wrong on its face. The contradiction lives in the accumulation, so neither reviewer was positioned to see it, and it surfaces in an assessment pass long after both shipped. Spec time is the one point where a single person is looking at both layers, which is why the justification is owed there and not at review.

### Narrowing a nullable is a whole-call-graph change, not a grep-and-replace

When a change narrows a nullable at a boundary — coercing an absent or null value to a concrete one, or asserting it non-null — the worklist is every *transitive consumer* of that field, enumerated by following the type to its readers, not the callsites a grep for the coercion operator returns. A coercion and the reader it feeds are frequently in different files: grepping the operator finds where the value is narrowed; it does not find a downstream reader, one or more files away, that still assumes the old nullable contract and does arithmetic or a comparison on the coerced value.

The type system enumerates the readers for free — widen or retype the field and follow what breaks to each consumer. A grep for the coercion is a starting point for that enumeration, never its boundary: the callsite that reads the narrowed value without knowing it was narrowed is exactly the one the operator search cannot see, and it is where the defect lands.
