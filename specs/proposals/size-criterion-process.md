<!-- guidance:template-proposal@0.1.2 -->
---
proposal: size-criterion-process
status: accepted
date: 2026-07-17
related: [CAL-666, CAL-1107, CAL-1014, CAL-1139]
---

# Proposal: file size is a tripwire, never an acceptance criterion

> Keep the 500-line advisory limit and the `# size:` justification convention; mechanically check marker *presence*; forbid raw file-size acceptance criteria; give mid-build criterion renegotiation a home in the ticket.

## Problem / motivation

CAL-1107 shipped Done against the criterion "review.py under 500 lines" while the file stood at 759. The gate was green because nothing in the repo measures a line count: the CAL-666 test (`tests/unit/test_code_quality_size_justification.py`) is a text-parse guard on `skills/code-quality/SKILL.md`, not on any source file. The builder's engineering call was sound — commit `c0d9b65` argues, correctly, that reaching 500 required fragmenting the verb — but the renegotiation lives only in a commit body, so the canonical record (the Linear ticket) is wrong.

Two holes, neither of them "the number":

1. A quantity landed as an AC with no measuring test, which the repo's own rule (`code-quality` Part C: *a measurable criterion needs a measuring test*) already forbids — but nothing catches it.
2. There is no sanctioned move for a builder who discovers mid-build that a criterion is wrong. `engineering-principles` forbids self-descoping; nothing says what to do instead, so the honest disclosure went into a commit body where Linear cannot see it.

### What the limit is a proxy for

Reader-load: how much a person must hold to change the file safely, and whether unrelated concerns are accreting into one gravity well. Line count is a weak proxy for cohesion but a *good tripwire*: it is language-agnostic, zero-tooling, and cheap to check — properties no better metric (exported-symbol count, fan-in, "reasons to change") shares once the rule has to travel to consuming repos. The tripwire's value is when it fires, not what it forbids: its job is to force the cohesion argument to be written down (`# size:` marker) and, for repeat offenders, to feed the `architecture_watchlist`, which is the instrument that actually reduces gravity wells (CAL-1107's real extraction was a watchlist-trigger seam).

Calibration evidence (measured 2026-07-17, dev): 41/49 files in `harness/` under 300 lines; the over-limit set is exactly the five CLI verbs (`review.py` 759, `promote.py` 649, `close.py` 588, `start.py` 552, `reclaim.py` 525) plus the Linear transport singleton (`linear.py` 787), each carrying a substantive cohesion argument — `linear.py`'s is forced by the CAL-731 embed guard, which requires every GraphQL operation to live in that one class. 500 is binding on one architectural class and invisible everywhere else, which is what a well-placed tripwire looks like. The 6-for-6 marker rate is not a 100% opt-out from a dead rule; it is CAL-666 achieving its stated goal — before it, zero over-limit files carried a recorded decision and the steward re-found them every cycle.

## Options

**Option A — enforce 500 mechanically, no escape hatch** · a test fails any over-limit file · produces exactly the fragmentation `c0d9b65` refused; splitting a cohesive verb to satisfy a number moves reader-load up, not down.

**Option B — replace line count with a cohesion metric** · exported-symbol count, fan-in/fan-out, "reasons to change" · not mechanizable without language-specific tooling, does not travel to consuming repos, and a second criterion nobody follows is not an improvement on the first.

**Option C — drop the number, rely on reviewer judgment + watchlist** · no tripwire at all · growth is silent until the steward's periodic pass — the exact pre-CAL-666 state (CODE-INSIGHT-002) the marker rule was built to end.

**Option D — keep the tripwire, fix the process** · the recommendation below.

## Recommendation

Option D: four changes. The number does not move.

1. **File size is never an acceptance criterion.** A change spec states the *structural outcome* — "the engine-protocol layer lives in its own module; review.py holds only verb glue; no test imports change" — which is checkable by import structure and tests. If a spec author insists on a quantity, the existing Part C rule applies with no exemption: write the test that measures it and fails outside the bound, or it is not a criterion. (For line count that test is trivial to write — which is the point: being forced to write it exposes that the number was never the requirement.) Lands as a paragraph in `spec-authoring` (change-spec section) and a Stage 1 line in `review-discipline`.

2. **Mechanize marker presence.** One repo test walks the source tree, counts lines, and fails any file over the hard limit lacking a `size:` marker (language-native comment) or ticket reference. This is the measuring test the rule never had: today an unjustified over-limit file waits for a reviewer to remember Part C or for the steward's next pass; under this test it fails the gate at commit time. Config (limit, globs, declarative-file exemptions per `code-quality` Part B) reads from the repo, defaults from the skill.

3. **Renegotiation lives in the ticket.** When a builder discovers a criterion is wrong mid-build — stale estimate, impossible bound, wrong target — the move is: comment on the Linear issue with the evidence, amend the AC there, then build to the amended spec. The reviewer's Stage 1 checks the ticket's *current* criteria and flags any amendment in the review report; a criterion renegotiated only in a commit body or PR description is a Stage 1 FAIL even when the engineering call is right. This is the CAL-1107 fix that matters most: `c0d9b65`'s argument was correct and belonged on the ticket.

4. **Retroactively amend CAL-1107** per rule 3: a comment linking `c0d9b65`, the AC corrected to the structural outcome that actually shipped, so Done stops being false.

This traces to `engineering-principles`: *make the right thing the easy thing* (the tripwire triggers a recorded decision instead of demanding a split), *trade-offs are conscious, not silent* (the marker is the record), and the scope guard (*requirements are not self-descoped* — rule 3 supplies the sanctioned alternative).

### Mechanically checked vs reviewer judgment

| Concern | Mechanism |
|---|---|
| Over-limit file has a `size:` marker or ticket | Test (new, item 2) |
| Quantity-AC has a measuring test | Reviewer, Stage 1 (existing rule, now with no size-AC carve-out) |
| The justification is substantive, not a rubber stamp | **Reviewer judgment — irreducibly.** A good marker names the cohesion argument and what splitting would scatter; no test can score that. The steward audits marker quality on assessment passes. This proposal does not pretend otherwise. |
| Repeat-offender gravity wells | `architecture_watchlist` + watchlist trigger (existing) |

### The six existing markers

All six survive — each already meets the bar. The rule still bites: the *seventh* over-limit file cannot ship unmarked (item 2 fails the gate), no ticket can again promise a raw number (item 1), and the two watchlisted files stay under active extraction pressure independent of any count.

### Guidance-source constraint

Line count + language-native comment marker travels to any repo in any language with no tooling. The skill text carries the rule and the default numbers; the checking test is a ~30-line walker installed per repo with `CONTEXT.md` overrides. A consuming repo without a test suite falls back to reviewer enforcement — degraded, but no worse than today's state everywhere.

### The counter-argument hardest to dismiss

"A gate that never fails is ritual: if all six markers survive and any future over-limit file passes by adding a comment, you have mechanized the writing of comments, not the keeping of files small." This is true, and accepted deliberately: the property the tripwire protects is *the decision being recorded*, not the size — cohesion itself is reviewer judgment plus the watchlist, and no test reaches it. The alternative that does hard-fail was effectively tried by CAL-1107's AC, and its outcomes are the two bad ones: fragmentation, or a falsely-Done ticket. The residual risk — markers degrading to rubber stamps in a repo with a weaker review culture — is real (six substantive markers is six data points from one repo) and is assigned to the steward's assessment pass, where marker quality is auditable.

## Open decisions

All three resolved by the operator, 2026-07-17 (this session):

| Decision | Outcome | Recorded in |
|---|---|---|
| Adopt "size is never an AC" + the renegotiation protocol as universal guidance | **Yes — universal** | `spec-authoring` + `review-discipline` (CAL-1155) |
| Ship the marker-presence test in this repo, and whether to distribute a reference implementation | **Yes — here, plus a distributed reference** | `code-quality` Part C + `registry.yaml` (CAL-1156) |
| Retroactively amend CAL-1107's AC to the structural outcome that shipped | **Yes — amend** | CAL-1107 (Linear), via CAL-1157 |

## Breakdown

Spawned as Linear issues 2026-07-17:

1. **CAL-1155 — Skill amendments** — `spec-authoring` (no size ACs; renegotiation protocol), `review-discipline` (Stage 1 checks the ticket's current criteria; commit-body-only renegotiation is a FAIL), `code-quality` Part C (marker presence is mechanically checked; justification substance stays reviewer judgment). One change spec: the three edits are one rule stated from three vantage points, and shipping them separately would leave the skills contradicting each other mid-sequence.
2. **CAL-1156 — Marker-presence test** — test-first: red on a fixture over-limit file without a marker, green on the current tree; config for limit/globs/exemptions; reference implementation distributed via `registry.yaml`.
3. **CAL-1157 — Amend CAL-1107 on Linear** per the renegotiation protocol, linking `c0d9b65` — plus the CAL-666 test docstring correction (it claims to "convert silent drift into an auditable choice" but only guards the rule text; item 2's test is that conversion).

## Risks / unknowns

- Marker-quality drift in consuming repos (accepted; steward-audited).
- The renegotiation protocol adds a Linear round-trip mid-build; for an unattended run an AC amendment may sit outside `autoMode.allow` — if the write is denied, the run defers rather than self-descopes.
- Item 2's test must respect Part B's higher ceiling for declarative files; a wrong exemption list would either exempt real logic or fail schema files spuriously.

---

**Lifecycle.** A proposal ends in one explicit state: **accepted** (spawn the change specs as Linear issues; record its decisions in the relevant specs), **rejected** (keep this file as the record of why), or **split** (replace with smaller proposals). It does not sit half-decided. Lives in `specs/proposals/`.
