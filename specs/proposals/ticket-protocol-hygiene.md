---
proposal: ticket-protocol-hygiene
status: shipped
date: 2026-07-18
related: []
---

# Proposal: Ticket protocol and hygiene — assignment, placement, and what a label means

***Shipped** into `skills/tracker/SKILL.md`, where its substance is live: assignment as the hold signal, mandatory Todo placement on create, and the Todo-vs-Backlog line. One definition did not survive intact — the `decision` hold label this proposal defined was merged into `input` by [ADR 0015](../decisions/0015-harness-v4-thin-verification-layer.md), leaving exactly two hold labels.*

> Codify the ticket protocol the queue already needs: assignment as the "a human holds this" signal, mandatory project attachment, explicit Todo-vs-Backlog filing rules, and an end to the `decision` label doing three jobs.

## Problem / motivation

Status is well codified — the `linear` skill's lifecycle table maps pipeline events to states, and the verbs enforce the transitions. The rest of the protocol is folk practice, and it shows in four places:

- **In Review carries two meanings the guidance cannot distinguish.** (a) An agent review inside a live harness run, and (b) a closed run parked for a human because verification is visual. `work-discovery` handles this by never touching In Review at all — safe but blunt: nothing signals *which* In Review tickets are waiting on the operator, so the human must open each one to find out.
- **The `decision` label is overloaded.** `work-discovery` defines it as "waiting on a human decision," but it is the only lever that attracts human attention, so it gets applied to anything needing a human — including interactive setup that is hands, not judgment (CAL-1149's `ln -sf` relink travelled as a `decision`). The label currently answers "should the loop skip this?" when it should answer "what does this need?"
- **Assignment is unused.** No skill, command, or verb mentions assignees. There is no first-class "a human holds this" signal; the label is standing in for one. (Agents authenticate with the operator's API key and have no Linear identity of their own, so the assignee field is entirely free to carry this meaning.)
- **Project attachment is unenforced.** `work-discovery` pulls only from `CONTEXT.md` → `repo.project`, so an issue created without a project is *invisible to the loop* — a silent orphan, not a triaged deferral. The `linear` skill's `issueCreate` recipe does not even carry a `projectId` parameter.
- **Todo vs Backlog is defined on the pull side only.** "Only Todo issues are pulled; Backlog waits for an answer" covers consumption, and "blocked → Backlog" covers parking — but nothing covers *filing*: where does a new ticket land? Each run decides ad hoc (the unattended tick that filed CAL-1144 chose Backlog by reasoning from an `autoMode.allow` clause bound, because no written protocol answered the question).

Cost of the status quo: the operator scans a queue where "needs my decision," "needs my hands," and "awaiting my visual check" all look alike; the loop occasionally skips or re-litigates wrongly; and an issue filed without a project falls out of the queue with no one noticing.

## Options

Three dimensions, decided independently.

**Dimension 1 — the human-hold signal.**

**Option 1A — assignee is the signal.** A ticket assigned to a human is held by that human: the unattended loop never picks it, whatever its state. Labels become *explanatory* (why it is held), not load-bearing. One skip rule; a first-class field visible in every Linear view; "my issues" is the operator's worklist for free. Also disambiguates In Review: assigned = human/visual review, unassigned = agent handoff.
**Option 1B — grow the label taxonomy instead.** Add `operator` / `human-review` labels beside `decision`; assignee stays unused. No engine or filter changes beyond label checks — but N labels means N skip rules, labels are easy to forget, and the board does not surface them the way assignment surfaces.

**Dimension 2 — what a label says (given 1A, labels explain the hold).**

**Option 2A — split `decision` into two: `decision` and `operator`.** `decision` = a direction or detail call is needed (judgment). `operator` = an interactive session is needed (hands: setup, relinks, visual checks). Both imply assignment to the human. Two filterable views that match the two real backlogs the operator works through.
**Option 2B — keep one `decision` label, let the comment carry the nuance.** Smaller taxonomy; but the operator cannot filter "things I can knock out at the keyboard in 5 minutes" from "things I need to think about," which is the actual working distinction.

**Dimension 3 — Todo vs Backlog filing semantics.**

**Option 3A — Todo = confirmed, Backlog = existence-uncertain.** Todo receives anything already decided to be done: review follow-ups, deferred findings from a change's review, decided improvements. Backlog receives only work whose *existence* is uncertain — might-not-do ideas, and trigger tickets whose deliverable is a `/propose` or a direction call. A ticket blocked on a *detail* decision of confirmed work stays in Todo, assigned + labelled (it is still confirmed; it is just held) — replacing today's "blocked → Backlog" rule.
**Option 3B — status quo.** Backlog doubles as both "uncertain" and "confirmed but blocked," which is exactly the ambiguity that forces ad-hoc filing choices.

**Sub-question under 3A — unattended `/assess` findings.** The current `autoMode.allow` clause sanctions unattended filing as "a new item for a human to triage." Filing straight to Todo makes the loop self-feeding: it invents work and builds it next tick with no human in between. Options: (i) unattended assess findings file to **Backlog** (human triage preserved; interactive/attended filings go to Todo per 3A); (ii) all findings file to Todo and the clause is widened. Recommendation below is (i).

## Recommendation

**1A + 2A + 3A.** On the sub-question the recommendation was (i) (unattended findings → Backlog); the operator decided **(ii) — findings file to Todo always**, attended or unattended, accepting the self-feeding loop with the assessment severity bar and the merge-time review gate as the guards. The protocol in one table:

| Signal | Meaning | Who reads it |
|---|---|---|
| **Assignee = a human** | that human holds the ball; the unattended loop never picks it, in any state | the loop's single skip rule |
| **`decision` label** | held for a judgment call (direction or detail) | the operator's "to think about" filter |
| **`operator` label** | held for an interactive session (setup, hands-on, visual check) | the operator's "to do at the keyboard" filter |
| **In Review, assigned** | closed run awaiting human/visual review | both |
| **In Review, unassigned** | agent review inside a live run | the loop (never touch) |
| **Todo** | confirmed work (follow-ups and review findings file here) | the pull queue |
| **Backlog** | existence uncertain, or a proposal/direction trigger | triage |
| **Project** | mandatory on every create — a project-less issue is invisible to the loop | loop visibility |

Why this wins: it uses Linear's first-class fields for the machine-readable part (assignee → skip; project → visibility) and keeps labels for the human-readable part (why it is held), instead of making one label carry both. It is the smallest change that gives the loop one skip rule and the operator two honest worklists — consistent with *simplicity over cleverness* and *separation of concerns* (the loop's signal and the human's explanation are different concerns and get different fields).

**Single-operator note.** The rule is expressed as "assigned to *any human*," not "assigned to Scott" — agents have no Linear identity here, so assigned-at-all ≈ human-held, and the rule survives a second human joining the workspace.

**Transition note.** During rollout the loop's skip rule is "assigned **or** `decision`-labelled" so existing deferred tickets stay safe until the backfill (breakdown item 4) assigns them.

## Open decisions

All resolved by the operator, 2026-07-18:

| Decision | Outcome | Recorded in |
|---|---|---|
| Assignee as the sole machine-readable skip signal (1A), labels advisory | **Decided: 1A** — assigned-to-a-human is the skip signal | `linear` + `work-discovery` skills (breakdown 1–2) |
| Split `decision` → `decision` + `operator` (2A), or keep one label | **Decided: split (2A)** — `operator` label created in the workspace at acceptance | `linear` skill label table (breakdown 1) |
| Todo = confirmed / Backlog = existence-uncertain (3A), replacing "blocked → Backlog" | **Decided: 3A** | `linear` skill (breakdown 1) |
| Unattended assess findings → Backlog vs Todo | **Decided: Todo always** (over the recommendation) — guards are the severity bar and the merge-time review gate; requires the widened autoMode clause, approved verbatim at build time | `commands/assess.md` + both settings copies (breakdown ticket) |
| `harness defer` engine change now or guidance-first | **Decided: engine change now**, shipped adjacent to the `work-discovery` bump (transitional OR covers the gap) | the defer ticket's change spec |

## Breakdown

1. **`linear` skill 0.5.0** — filing-placement rules (the table above), project mandatory on create, `projectId`/`assigneeId` recipes and runtime resolution, assignment protocol, label table gains `operator`. Registry + CHANGELOG.
2. **`work-discovery` 0.3.0** — skip rule keyed on assignment (with the transitional `decision`-label OR), pull filter documented; deferral instruction becomes "assign + label + comment."
3. **`harness defer` v2 (engine, TDD)** — `--needs decision|operator` selects the label; the verb also assigns the ticket to the operator. Includes the matching `autoMode.allow` clause rewording (operator approves the clause text verbatim, per standing rule).
4. **Queue hygiene backfill (one-off, interactive)** — sweep the live CAL/Harness-v3 queue: attach projects, assign held tickets, split mislabelled `decision`s, re-shelve per the new Todo/Backlog semantics.
5. **Hygiene check (optional, small)** — a routine pre-flight or `/assess system` lens that reports project-less issues and unassigned In Review tickets older than a threshold.

## Spawned work

Filed 2026-07-18, all attached to project Harness v3 (dogfooding the mandatory-project rule at filing time):

1. CAL-1165 — linear skill 0.5.0 (Todo, P2)
2. CAL-1166 — work-discovery 0.3.0 (Todo, P2)
3. CAL-1167 — harness defer v2 (Todo, P3; assigned + `decision` pending verbatim clause approval)
4. CAL-1168 — assess findings → Todo + widened clause (Todo, P3; assigned + `decision` pending verbatim clause approval)
5. CAL-1169 — queue hygiene backfill (Todo, P3; assigned + `operator` — interactive sweep)
6. CAL-1170 — queue hygiene check (Backlog, P4 — a design-decision trigger, existence-uncertain by the new semantics)

## Risks / unknowns

- **The loop reads guidance, not code, for the skip rule** — if `work-discovery` and the `defer` verb ship out of step, a deferred ticket could be assigned but not labelled or vice versa. Mitigation: the transitional OR rule, and shipping items 2 and 3 adjacent.
- **autoMode clause drift** — changing `defer`'s writes (assignment is a new write class: it *does* touch existing work, which the current clause explicitly disclaims) without the clause update would make unattended defers fail. They change together in item 3, and the clause text goes to the operator verbatim.
- **Assignment semantics elsewhere** — Linear automations or views that key on assignee (none known in this workspace) would pick up new meaning. Low risk, worth a one-time check during item 4.
- **"No project" today may be load-bearing somewhere** — e.g. cross-repo tickets deliberately outside Harness v3. The rule is "every issue gets *a* project," not "the Build project"; item 4 verifies no orphan was intentional.

---

**Lifecycle.** A proposal ends in one explicit state: **accepted** (spawn the change specs as Linear issues; record its decisions in the relevant specs), **rejected** (keep this file as the record of why), or **split** (replace with smaller proposals). It does not sit half-decided. Lives in `specs/proposals/`.
