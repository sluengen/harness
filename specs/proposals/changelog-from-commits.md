---
proposal: changelog-from-commits
status: shipped         # draft | under-decision | accepted | shipped | rejected | split
date: 2026-08-04
decided: 2026-08-04      # operator; Option B. Decisions recorded in specs/decisions/0014-changelog-from-commits.md
related:
  - specs/proposals/rebase-stable-certification.md
  - specs/decisions/0010-rebased-tree-recertification.md
---

# Proposal: the changelog derives from commits; the fragment system is deleted

***Shipped, then partly outlived.** The rule was decided as [ADR 0014](../decisions/0014-changelog-from-commits.md) — the commit body *is* the entry, and the fragment system was deleted. The `CHANGELOG.md` it assembled into was itself deleted by [ADR 0015](../decisions/0015-harness-v4-thin-verification-layer.md), since with no runtime there is nothing to release: the derive-from-commits rule stands, its assembly target does not.*

> 1,874 lines of enforcement have produced zero released changelog entries, and a fifth of the files it compels say "no entry warranted". The conflict fix underneath it was earned; the ceremony on top of it was not.

> **Decided 2026-08-04 — Option B.** The drafted recommendation was Option D (commits by default, fragment as an optional override). The operator's answer to the audience question — "nobody yet, realistically" — removed the override's only justification. Both are kept below: the options as drafted, and the reasoning as decided.

## Problem / motivation

The changelog machinery has three layers welded together, and only one of them is carrying its weight.

**What is earned.** ADR 0010 / #267 moved `CHANGELOG.md`'s `[Unreleased]` block to per-change `changelog.d/` fragments because two concurrent runs conflicted at a shared insertion point **by construction** — on a file whose correct merge semantics are "keep both lines". That cost run `01KYR7T7B5E3QDC3WP7ZGYHTGV` two full rebase → gate → re-review → close rounds and went on to refuse a close on two further ticks. `merge=union` was rejected on direct evidence from the same run. That reasoning holds and any replacement must preserve its property: **no shared append point.**

**What is not.** On top of that sits a presence guard (`require`) compelling every change to produce a fragment or an explicit exemption, plus a structural guard, a per-fragment byte budget, a fragment-count bound, a reserved no-ticket stem class (#287, shipped 2026-08-04), and a doc-guard suite asserting `RELEASING.md` describes all of it. Measured on 2026-08-04:

| | |
|---|---|
| Machinery | 486 lines of guard, 1,388 lines of test, a 107-line runbook |
| Tests | 47 across three modules |
| **Released entries produced by it** | **0** |
| Pending fragments | 24, of which **5 (21%) are `### None`** exemptions |
| Fragment vs. its own commit body | ~2.5 KB each, **44–54% vocabulary overlap** (#281, #291) |
| Releases ever | **1** (`v1.0.0`, 2026-05-27 — three months *before* the fragment system existed) |

`CHANGELOG.md` contains exactly one `## ` heading — `[Unreleased]` — holding 12 entries that predate #267 and are frozen there by the may-not-grow ratchet. **The fold has never run.** Every bound the system enforces — the per-fragment byte budget, the count ceiling, the file's byte and line ratchets — is calibrated against zero observed releases.

In fairness, #267 shipped on 2026-08-01, three days ago. "Has produced no output" is partly youth, not only waste. What it is *not* partly is this: the enforcement was built ahead of any evidence about what the output should look like, and has since grown two more layers (the byte budget, then #287's stem class) without that evidence arriving.

**The duplication is already documented in the system's own error message.** The per-fragment byte guard fails with: *"Reasoning longer than that belongs in the change spec, the commit body, or the review record — where it already lives in full, and where nobody pays a context tax to skip it."* It correctly identified that the fragment duplicates the commit and responded with a cap on the duplicate rather than asking why there are two.

**Why the duplication is structural, not a discipline problem.** The argument for write-time fragments is a good one in general: capture the *user-facing* entry while context is fresh, in the reader's language rather than the implementer's. This repo does not realize it, because the same agent writes the fragment and the commit body in a single pass with no change of audience. The #287 fragment shipped today talks about `_sort_key`'s `int(...)` and `merge-base..HEAD`. That is implementer language in both files.

**The convention that could replace it already holds.** All **80 of the last 80** non-merge commits on `dev` carry a valid `type` (`feat` / `fix` / `chore` / `docs` / `refactor` / `test` / `spec`), and 77 carry a scope as well. `harness/cli/release.py` contains **zero** references to the changelog, so nothing in the release verb depends on the fragment format.

Doing nothing is defensible on the grounds that the system is three days old. The cost of doing nothing is that the next edge case gets another layer, as #287 just did.

## Options

**Option A — Keep it, and wait for a release before judging.** The system is young; one fold would produce the evidence every bound was set without. · Costs nothing today and is the honest scientific answer. But it leaves the 21% exemption rate, the duplication, and the #287 stem class in place, and each further edge case adds a layer that a later simplification must then unwind.

**Option B — Derive the changelog from commits at release; delete the fragment system entirely.** `git log <last-tag>..HEAD --no-merges`, grouped by `type`, edited once by a human at release. · Deletes ~1,800 lines and ~40 tests. Solves #267's conflict *more* completely than fragments — there is no shared file and no second file to forget. Loses the ability to write an entry in different words from the commit, and makes commit subjects load-bearing (they already are, at 80/80).

**Option C — Delete the presence guard only; keep fragments as an optional artifact.** `require` goes; `check` and `fold` stay. An author writes a fragment when there is something worth saying and writes nothing when there is not. · Removes the ceremony and the whole exemption concept — absence *is* the exemption — while keeping the curated-prose escape hatch. But with no backstop, an entry that should have been written is simply lost, and nothing notices.

**Option D — Commits are the default source; a fragment is an optional override.** The release assembles from commits, and where a `changelog.d/<ticket>.md` exists it **replaces** the derived entry for that ticket. `require` and the exemption concept are deleted; `check` stays for the fragments that do exist. · Keeps every property that was earned and drops every one that was not. More moving parts than B — two sources to merge at fold time — and the merge rule has to be unambiguous.

## Recommendation

> **Decided 2026-08-04: Option B**, with breakdown item 1 gating the rest. This section records the reasoning as accepted; the drafted recommendation was Option D, and the paragraph below explains why the operator's answer to the audience question makes B the better call.

**Option B — derive from commits, delete the fragment system entirely.**

The audience question settled it. The drafted recommendation was Option D, whose entire justification is the *fragment as an optional override*: a place to write an entry in the reader's language when the commit subject will not serve. **That value is conditional on there being a reader.** With the audience answered as "nobody yet, realistically", the override preserves an escape hatch for an audience that does not exist, and pays for it with two sources, a merge rule, and the `check` guard that keeps the format honest. Option D would be right the moment a real external reader appears; today it is machinery held in reserve.

What B keeps, and why each piece survives:

- **No shared append point** — the property ADR 0010 bought with two rebase → review → close rounds — holds *more* strongly than under fragments. Commits never conflict, and there is no second file to forget, mis-name, or exempt.
- **The record still exists.** A changelog is cheap when derived: `git log <tag>..HEAD --no-merges`, grouped by `type`, edited once by a human at release. Cheap enough to keep for the reader who may yet arrive, which is the right posture for an unverified audience — versus the current posture, which pays a per-change tax against the same uncertainty.
- **The exemption disappears entirely.** Not every commit becomes an entry; the release editor drops what does not matter. That is what 5 of the 24 pending fragments are laboriously saying in prose.

Stating the cost plainly rather than burying it: **I built #287 today, and this decision makes it dead code.** That is not an argument against the decision — it is the strongest evidence for it. A guard that needs a reserved filename class to accommodate its own process outputs has stopped serving the thing it was built for. #287 was a correct fix and it unblocked real commits; it should not have been necessary, and its necessity is the symptom being acted on. Discount any defence of the current system from its author accordingly.

This follows *smallest change that fully solves the problem* only if the problem is stated correctly. The problem is not "changes lack changelog entries" — it is "the record of a change is written twice, and the second copy is compelled". B deletes the compulsion and the second copy while keeping the record.

**Sequencing, decided: item 1 gates the rest.** Nothing ships before the fold has run and its output has been read. ADR 0009's precedent applies — measure before the fix the measurement is meant to justify — and #267 itself rejected `merge=union` on measured evidence rather than reasoning. With B chosen the gate's *purpose* shifts: it is no longer "does the fragment system produce good output" (it is being deleted either way) but **"what is the pending window holding, and does any of it need preserving before the machinery that reads it goes?"** It retains the standing to stop the proposal — if the folded section reads better than anything `git log` could produce, that is evidence for Option A and this decision should be revisited.

## Item 1 evidence — the fold ran (#322, 2026-08-05)

Item 1's gate has been executed. The window was drained and the two forms compared
against a rubric **specified in the change spec's design before either was produced**
(the anti-post-hoc control ADR 0009 set as precedent).

**What was drained.** 43 fragments — 39 releasable, 4 `### None` exemptions consumed and
never emitted — folded as `## [Unreleased on dev] — 2026-08-05`, then rotated with the
root's 12 pre-#267 entries into [`CHANGELOG-archive/2026.md`](../../CHANGELOG-archive/2026.md).
No tag was cut. Conservation: 74 + 39 + 12 = **125** archive entries; the root holds 0.
`CHANGELOG.md` went 156 lines / 45,923 B → **7 lines / 388 B**, and its ratchet was
re-baselined *down* (160 → 11 lines, 46,500 → 965 bytes).

**Range.** `921a888~1..a0ae5ee` — `921a888` created `changelog.d/`, so `~1` makes the
range the fragment era exactly. **84 non-merge commits** (`docs` 26, `fix` 19, `test` 13,
`feat` 12, `spec` 8, `chore` 4, `refactor` 2).

### Verdict against the pre-stated rubric

| # | Question | Result | Winner |
|---|---|---|---|
| 1 | **Coverage** — does each of the 39 fragments have an attributable commit? | **38/39.** The one miss, `267`, is a known false negative: its commit `921a888` established the `(#nnn)` convention and so predates it. | **Tie** |
| 2 | **Signal-to-noise** — editing needed to reach a releasable set | 84 commits → 31 derived entries → 39 curated. Derived needs ~53 drops; curated needs none. | Fold (does not clear the bar alone) |
| 3 | **Audience** — user-facing or implementer language? | Both implementer language, as this proposal already concedes. Five matched pairs below are the evidence. | **Tie** |
| 4 | **Uniquely-present information** | **4 of 39** fragments (10%) carry reasoning absent from a commit body ≥400 B; only **2** (`283`, `285`) are sole carriers. 73/84 commits carry bodies, median **1,365 B**. | Fold, but narrowly |

**Two corrections made while measuring, both recorded because they change the numbers.**
A first pass parsed only a trailing `(#nnn)` and reported 13 tickets vanishing; the repo
also uses `type(#nnn):` in the *scope*, and handling both took coverage from 26/39 to
38/39. A first anecdote — #305, whose fragment records a design reversal (the
image-freshness guard *staying* in shell) found in neither its empty commit body nor its
issue, which proposes the opposite — looked decisive until the population was measured and
proved it a 10% case, not the rule.

### AC-4 gate call: **the fold is NOT materially better. The gate does not fire.**

The bar was "wins on (1) or (4) with content a release editor could not reconstruct from
the commit body and the linked issue." It wins on neither: (1) is a tie, and (4) is a 10%
minority against 90% of fragments restating reasoning that already exists in a commit body
averaging 1,365 bytes. That 90% **is** the proposal's thesis measured — "the record of a
change is written twice, and the second copy is compelled."

**Consequence: Option A is not reinstated, the decision stands, and #323–#325 are not
blocked.** Recorded explicitly, as AC-4 requires.

**One residual, carried to #323 rather than silently dropped.** The 2 sole-carrier
fragments share a shape: a build that *reversed* its ticket's stated plan. Neither the
commit subject nor the issue can hold that, because the issue predates the reversal. The
assembler cannot fix this, but the release editor can be told to look for it — a
one-line addition to #323's runbook, not a reason to keep 1,800 lines of machinery.

### Five matched pairs, shown both ways

Chosen to span the range rather than to flatter either form — the fold's best case first,
its worst last. These are the evidence for rubric question 3 (audience); read them before
accepting the "Tie".

**#305** — **The fold's best case.** The commit body is empty and the issue proposes the *opposite* of what shipped, so the carve-out rationale exists nowhere else.

*Fragment (1427 B):*

> ### Changed — host-platform abstraction and credential port out of the wrapper (#305)
>
> Credential resolution, subprocess bounding and git-identity resolution move out of `docker/harness-wrapper.sh` into `harness/hostenv/`, a stdlib-only package behind a `HostPlatform` seam with macOS (Keychain) and Linux/WSL (file store) providers. The wrapper becomes a delegating shim: one `python3 -m harness.hostenv env` call whose NUL-terminated records it imports with `export`, never `eval`. The logic is now …

*Derived, from 5 commit subject(s):*

> - fix(specs): frontmatter must start at byte zero (#305)
> - docs(hostenv): as-built record and changelog fragment (#305)
> - feat(wrapper): delegate credential and identity resolution to harness.hostenv (#305)
> - test(hostenv): behavioural cover for staleness, refresh and tracker precedence (#305)
> - feat(hostenv): host-platform seam with macOS and Linux/WSL credential providers (#305)

---

**#283** — **A sole carrier.** Every commit for this ticket has an empty body.

*Fragment (186 B):*

> ### Changed — Require reviewers to refresh an edited as-built record's currency stamp (#283)
>
> The review guidance now treats a stale `last_updated` frontmatter value as a Medium finding.

*Derived, from 1 commit subject(s):*

> - docs(review): require refreshed as-built record stamps (#283)

---

**#300** — **The typical case.** The commit body already carries the reasoning; the fragment restates it.

*Fragment (1460 B):*

> ### Fixed — `close` reports the merge/push failure reason it already computed (#300)
>
> `harness close` classified its own step-6 failures precisely — `close_merge` raises seven distinct reasons — and then discarded every one of them, so a merge conflict (needs work on the run branch) and a lost push race (a plain retry) both surfaced as a bare exit 1 with no `reason` key. An orchestrating agent had to parse the human message or guess. The reason is now propagated rather than translated: `close_merge` …

*Derived, from 3 commit subject(s):*

> - docs(close): correct _CloseError's account of which raise sites tag a reason (#300)
> - test(close): make the reason derivation prove it reads source (#300)
> - fix(close): propagate the merge/push failure reason close_merge computed (#300)

---

**#350** — **Derived wins on brevity.** One subject says what the entry says.

*Fragment (715 B):*

> ### Fixed — release-cadence bounds no longer halt the build queue (#350)
>
> The `changelog.d/` count bound and `CHANGELOG.md`'s size ratchets moved from the pytest stage of `scripts/verify.sh` to `scripts/cadence.py`, which the release path enforces (`check`) and the gate only reports (`report`, always exit 0). A breach describes accumulated repo state that no single change caused or can fix; inside the gate it made `verify.sh` red on `origin/dev` independent of any diff, so `review` …

*Derived, from 1 commit subject(s):*

> - fix(gate): move release-cadence bounds out of the correctness gate (#350)

---

**#327** — **A multi-commit ticket.** Three subjects collapse to one curated entry.

*Fragment (2635 B):*

> ### Changed — the universal lifecycle is tracker-neutral, dispatching on `tracker:` (#327)
>
> `CONTEXT.md`'s top-level `tracker:` is now the only guidance-level tracker switch. The process doc, `spec-driven-development`, `spec-authoring`, `review-discipline`, `/start`, `/build`, `/ship`, `/propose`, `/assess` and the change/proposal/feature templates no longer require Linear: each routes tracker operations through the new **`tracker`** skill, which reads `tracker:` and dispatches to a provider recipe. A …

*Derived, from 1 commit subject(s):*

> - feat(guidance): the universal lifecycle is tracker-neutral (#327)

---
Question 3 reads **Tie** on these five: both forms are implementer language. The fragment
is more complete; neither is written for a non-contributor. That is what this proposal
already concedes, and these pairs are the check on that concession rather than a restatement
of it.

### The derived form — all 84 subjects

Listed in full, kept **and** dropped, because the coverage and signal-to-noise claims above
are only auditable if a reader can see what a derivation would discard. The folded section
is not inlined: at 76,021 bytes it is 10× this proposal, and it is committed in
[`CHANGELOG-archive/2026.md`](../../CHANGELOG-archive/2026.md). **That asymmetry — 5.7 KB of
subjects against 76 KB of entries — is itself a finding**, not an editorial convenience.

**Kept — the 31 entries a type-filtered derivation emits.**

*Added*

- delegate credential and identity resolution to harness.hostenv (#305)
- host-platform seam with macOS and Linux/WSL credential providers (#305)
- absorb transient merge/transition failures with a bounded retry (#301)
- the universal lifecycle is tracker-neutral (#327)
- the cycle budget counts cycles spent, and exhaustion is surfaced (#329)
- /harness run declares attended; guard no routine path does (#298)
- sweep an attended run at attended_idle_minutes (#297)
- scope the wall-clock breaker to unattended runs (#296)
- record declared attendance on the run (#295)
- record the model the engine actually ran with (#293)
- record a bounded excerpt of an unparseable SUBMIT payload (#277)
- per-change changelog.d/ fragments remove the conflict class

*Fixed*

- frontmatter must start at byte zero (#305)
- move release-cadence bounds out of the correctness gate (#350)
- propagate the merge/push failure reason close_merge computed (#300)
- map a lazily-raised tracker config error to blocked (#328)
- route escalation through the tracker abstraction (#328)
- scope supersession, and make three guards measure (#330)
- the as-built record lands inside the reviewed tree (#331)
- refuse a shallow clone's graft boundary instead of reading it as a spec's last commit (#326)
- run-ledger.md names the payload module, not eight of its ten classes (#282)
- a feature spec's last_updated is measured against git, not just required (#280)
- document and test the no-ticket exemption (#287)
- a ticket-less commit gets a stated exemption path (#287)
- declare CommonJS so the hooks survive an ESM consumer root (#302)
- collect the design from a file, not a JSON line on stdout (#294)
- the three loop knobs carry one value in three places (#291)
- the staleness guard measures the ref the loop actually ships to
- pin PYTHONDONTWRITEBYTECODE=1 at both mounting seams (#278)
- a watchlist note may not contradict the file it describes (#272)
- classify a no-SUBMIT-line reviewer as infra, not a fail verdict (#270)

**Dropped by the type filter — the other 53, listed individually (not counted), because a reader auditing coverage needs to see what a derivation would discard.**

*`chore:` — 4*

- arm the architecture watchlist on reclaim.py (#281)
- gitignore the design run artifact, guard both
- code assessment 2026-08-01 (pm) — one finding, two insights; retention fold
- code assessment 2026-08-01 — one finding, one insight; retention fold

*`docs:` — 26*

- as-built record and changelog fragment (#305)
- guard code-owned prose sets (#285)
- require refreshed as-built record stamps (#283)
- watchlist repeated seam extractions (#284)
- correct _CloseError's account of which raise sites tag a reason (#300)
- record #328 on the as-built spec's ticket list
- decision storage is repo-configurable, embedded-first (#330)
- single-home the review stop policy in review-discipline (#329)
- record the attended-run spend scope where it is read (#299)
- deep repo health assessment
- surface commands as Codex skills
- generate local Codex surface
- record the persistent-runtime-host carve-out and its bound in §16 (#304)
- derive Codex-native artifacts
- cover the Windows junction workaround and the header-less set (#302)
- derive the read-only claim instead of listing where it was made (#294)
- stop calling the design engine read-only, and guard the claim (#294)
- the one-ceiling rationale cites the measurement, not a refuted premise (#292)
- record the review event's model field (#293)
- 2026-08-01 code assessment (evening) — four findings, three insights
- a seam extraction must also say where the extracted module's tests went
- the guard's own docstring must not go stale about its scope (#275)
- a seam extraction must refresh the watchlist entry it invalidates
- record the design departure behind the AC-2 guard (#272)
- re-home §15 / §17 / §18 to specs/retired/spec-engine.md (#271)
- record rebase-stable-certification and retire item 3 unbuilt (#268)

*`refactor:` — 2*

- the async runner has one home, guarded against copy 27 (#279)
- record the SUBMIT excerpt as typed evidence, not prose (#277)

*`spec:` — 8*

- derive the changelog from commits and delete the fragment system — ADR 0014
- link the codex-engine breakdown to its filed tickets (#314–#320)
- codex as an in-container engine for design and review — proposal accepted, ADR 0013
- record the changelog exemption for the ADR 0012 spec commit
- a persistent runtime host for the verbs — proposal accepted, ADR 0012
- scope the wall clock to unattended runs — proposal + ADR 0011
- reject the per-engine timeout split — the ledger refutes its premise
- land the stranded ADR 0009 / 0010 decision records

*`test:` — 13*

- behavioural cover for staleness, refresh and tracker precedence (#305)
- make the reason derivation prove it reads source (#300)
- guard the exhaustion recipe and the inherit path's flags (#329)
- cover the refused-fast-forward and docker-only-delta branches
- split the real-git source-sync tests into their own module
- move the closable arm out; refresh the size record (#274)
- move the liveness arms to tests/unit/test_reclaim_liveness.py (#274)
- move the --undo arm to tests/unit/test_reclaim_undo.py (#274)
- extract the shared reclaim fixtures to tests/_reclaim.py (#274)
- scope the size-marker guard to every tracked Python tree (#275)
- measure the currency map AC-3 only asserted in prose (#271)
- bind the record guard to the claim, not a substring of it (#268)
- pin the fold's symlink containment refusal

<!-- total subjects listed: 84 -->

## Open decisions

Four were settled by the operator on 2026-08-04; one is dissolved by that outcome and one remains.

| Decision | Who decides | Outcome | Recorded in |
|---|---|---|---|
| **Who reads this changelog?** The repo has one release, an AGPL/MIT split, and unverified self-hosters. | user | **Settled — "nobody yet, realistically."** This is the decision that drives the rest: it removes the only justification for keeping a curated-prose override, and so converts the recommendation from D to B. | ADR 0014 + `RELEASING.md` |
| Default source: D, B, C, or A? | user | **Settled — Option B.** Derive from commits; delete the fragment system entirely. | ADR 0014 + `RELEASING.md` |
| Does the `### None` exemption concept survive? | user | **Settled — no.** It is deleted with the rest. Absence of an entry is the exemption; the release editor drops what does not matter. | ADR 0014 |
| Does #287's `no-ticket-<slug>` stem class get reverted or kept? | architect | **Dissolved by Option B** — the module it lives in is deleted, so there is nothing to revert separately. Its reasoning is preserved in the deleting change's commit body. | the deleting change spec |
| Does item 1 gate the rest? | user | **Settled — yes.** Nothing ships until the fold has run and been read. | this proposal, updated in place |
| Where does the folded pending window land, given `CHANGELOG.md` has **4 lines and 577 bytes** of headroom against its ratchet and the window holds 24 fragments? | architect | **Settled — `CHANGELOG-archive/2026.md`**, per `RELEASING.md` step 3, which already prescribed the rotation. The root drained to 7 lines and its ratchet re-baselined *down*. See the item 1 evidence above. | item 1's change spec (#322) |

## Breakdown

Four items, ordered. Item 1 **gates** items 2–4 and may stop them.

1. [#322] **Drain the pending window: fold the 24 fragments, read the output, land it.** No new code. Produces the released section the system has never produced, decides where it lands (the `CHANGELOG.md` ratchet has 4 lines of headroom, so almost certainly `CHANGELOG-archive/2026.md`), and re-baselines the ratchet. **Gate:** if the folded section is materially better than what `git log` over the same window would yield, that is evidence for Option A and this proposal is revisited before item 2 starts. Record the comparison either way — it is the evidence every existing bound was set without.
2. [#323] **Build the commit-derived assembler** — `git log <tag>..HEAD --no-merges`, `type` → Keep-a-Changelog category, ticket id parsed from the subject. Output only, alongside the existing system; nothing is deleted yet, so the two can be compared on the same window.
3. [#324] **Delete the fragment system** — `scripts/changelog_fragments.py` (`check` / `require` / `fold`), `changelog.d/`, the three test modules, the per-fragment byte budget, the fragment-count bound, and #287's no-ticket stem class. Roughly 1,800 lines and 40 tests. The commit body carries why each guard existed, so the reasoning survives its mechanism.
4. [#325] **Rewrite `RELEASING.md`'s changelog section and its 14 doc guards** — the runbook describes a mechanism that will no longer exist, and those guards enforce the description. Ships with or immediately after item 3, never before.

Explicitly **not** in this breakdown: reconciling the three places history is recorded (`README.md`'s era summary, `CHANGELOG.md`, `CHANGELOG-archive/2026.md`). See the risks below — with the audience answered as "nobody yet", that may be the more valuable change, and it deserves its own proposal rather than being smuggled in here.

## Risks / unknowns

**The evidence for the whole proposal is three days old, and so is the thing it criticises.** #267 shipped 2026-08-01. A system that has not survived one release cycle is being judged on not having produced release output. Item 1 exists precisely so this is settled by looking rather than by argument, and if the fold's output is good, Option A is the right answer and this proposal should be rejected on its own terms.

**Commit subjects become load-bearing.** They already are at 80/80, but that is a *current* rate under a convention nothing enforces mechanically. If derived entries become the record, a sloppy subject becomes a sloppy changelog line — where today it is invisible. Whether that warrants a subject-format guard is a question for item 2, and adding one would recreate a compulsion this proposal exists to remove; the honest answer may be that the release editor fixes it by hand.

**A derived entry is written for the wrong audience by default.** The commit subject is implementer language. The claim that a human editing pass at release fixes this is untested here, because no release has happened under any of these systems. Item 1 partially probes it.

**Three places already record history** — `README.md`'s era summary, `CHANGELOG.md` (12 frozen entries), and `CHANGELOG-archive/2026.md` (74 entries). This proposal touches only how the pending window is produced, and deliberately does not reconcile the three. If the audience question above resolves to "nobody", that reconciliation is the more valuable change and this one should be reconsidered against it.

**The audience answer cuts deeper than this proposal acts on.** "Nobody yet, realistically" is a reason to make the changelog cheap, which is what B does. It is also a reason to ask whether *three* records of history are warranted at all — `README.md`'s era summary, `CHANGELOG.md`'s 12 frozen entries, and `CHANGELOG-archive/2026.md`'s 74. B reduces the cost of producing one of them and reconciles none of them. That is a deliberate boundary, not an oversight: consolidating the three is a larger question with a different blast radius, and folding it in here would repeat the mistake this proposal is correcting — solving an unmeasured problem with machinery. It should be its own proposal, informed by item 1's output.

**What would invalidate the decision.** Item 1 producing a release section materially better than `git log` over the same window. That would show the system works and is merely young, making Option A correct — and it is the reason item 1 gates the rest rather than merely preceding them. A weaker signal pointing the same way: if writing the assembler in item 2 turns out to need a subject-format guard to produce usable output, the compulsion has simply moved from the fragment to the commit subject, and the saving is smaller than claimed.
