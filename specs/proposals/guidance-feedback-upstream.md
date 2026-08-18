---
proposal: guidance-feedback-upstream
status: shipped             # draft | under-decision | accepted | shipped | rejected | split
date: 2026-07-20
related: [CAL-1105, "#205"]      # GitHub Issues tracker backend (no hard dependency); #205 shipped the sole breakdown item
---

# Proposal: Route guidance feedback upstream as GitHub issues

> Now that the guidance source is a public repo with Issues enabled, teach agents to send feedback about the guidance itself upstream as a GitHub issue — instead of letting it die in the consumer's session.

## Problem / motivation

The guidance (skills, agents, commands, process doc, templates) is **universal and copied into other repos**. The source of truth is this repo, now public at `github.com/sluengen/harness` with GitHub Issues enabled.

The process doc's "Updating the guidance" section already states the model:

> Do not hand-edit installed guidance files to fix a bug in them; **fix it at the source so every repo benefits**, then update. (This repo *is* the guidance source — fixes land here directly.)

That instruction only closes for an agent working **in the source repo**. For an agent in a **consumer repo** — the audience open-sourcing was for — "fix it at the source" is not actionable: it has no push access to `sluengen/harness`. So when such an agent notices a real defect in the guidance (a skill that misdirects, a broken cross-reference, a command that doesn't behave as documented, genuine process friction), there is **no channel** and the observation is lost at the end of the session. The public issue tracker that would receive it sits unused by the very agents best positioned to find these defects.

The cost of the status quo: the dogfooding signal that keeps the guidance honest is confined to this one repo. Every consumer is a free source of "the guidance told me X but Y happened" — and right now none of it flows back.

This is a **guidance-surface** change, not a harness-engine change. It says nothing about a consumer's own product bugs (those go to the consumer's own tracker); it is strictly about feedback on *the shared guidance*.

## Options

**Option A — A rule in the process doc's "Updating the guidance" section (recommended)** · Extend the existing paragraph: when an agent finds a defect in the guidance and cannot fix it at the source, it files a GitHub issue against the upstream repo, whose URL it resolves from the consumer's `.guidance-lock.yaml` `source.repo` (no hardcoded owner/repo). The rule branches on "is this repo the source": in the source repo, fix-at-source / file in the local tracker as today; in a consumer repo, file upstream. · Trade-offs: highest visibility (the process doc is the always-loaded surface and already owns the source relationship); one small version-stamped edit; no new file to maintain. Risk of adding noise to a section that is already dense.

**Option B — A dedicated `guidance-feedback` skill** · A standalone skill describing when and how to raise upstream feedback. · Trade-offs: a skill is the wrong altitude — skills are durable *craft*, and this is a two-sentence routing rule, not a discipline. It would be the thinnest skill in the set and would rarely be loaded at the moment it is needed (an agent isn't going to invoke a "should I give feedback" skill mid-task). Violates the lean standard.

**Option C — Extend `/update-guidance` only** · Put the rule in the command doc, next to its existing LOCAL-edit "suggest pushing the change upstream" branch. · Trade-offs: only fires when someone runs `/update-guidance`, but the feedback moment is *during ordinary work*, not during an update. Wrong trigger. Worth a cross-reference, not the primary home.

**Option D — Do nothing; rely on `CONTRIBUTING.md`** · The human-facing docs already say "Issues are welcome." · Trade-offs: `CONTRIBUTING.md` is for humans and is not part of the distributed guidance surface, so no consumer *agent* ever reads it. The agents that hit the friction never learn the channel exists. This is the status quo, restated.

## Recommendation

**Option A.** Add a short, universal rule to the process doc's "Updating the guidance" section, with a one-line cross-reference from `/update-guidance` (Option C as a pointer, not the home). Key properties:

- **URL is resolved, never hardcoded.** The guidance is universal; it must not name `sluengen/harness`. The consumer's `.guidance-lock.yaml` already records `source: { repo, branch, ref }` (per `registry.yaml`), so the rule says "the repo recorded as your guidance `source.repo`" and the agent derives the Issues URL from it. This keeps a fork's feedback flowing to *its* source, not ours.
- **Branches on source-vs-consumer,** cleanly extending the sentence that already does: source repo → fix at source (unchanged); consumer repo → file upstream.
- **Scoped to the guidance surface.** The rule explicitly excludes the consumer's own project bugs, which belong in the consumer's own tracker.

This fits `engineering-principles` (smallest change that closes the gap; no new abstraction) and the guidance-system lean/MECE standards (the rule lives in the one section that already owns the upstream relationship).

**Resolved decisions fold the rule into a near-universal shape.** With the source repo also filing GitHub issues (decision 3), the file-a-GitHub-issue action is universal — every agent, in any repo, drafts an issue against the guidance `source.repo`. The source-vs-consumer branch narrows to a single clause: *if you are in the source repo and can fix the defect at source, do that too* — the issue remains the public record; fix-at-source is the resolution, not a substitute for the channel.

## Open decisions — resolved

| Decision | Resolution | Recorded in |
|---|---|---|
| **Scope of feedback** | **Defects + friction + ideas.** Guidance bugs, real process friction encountered while following it, and feature suggestions all route upstream. Broad signal from consumers; mitigated by "search existing issues first" and the draft-and-surface gate. | this proposal → process doc wording (breakdown item 1) |
| **Autonomy posture** | **Draft and surface.** The agent drafts the issue (title + body) and presents it for the operator to review and send. Filing to a public tracker is outward-facing and can leak private-repo context, so a human stays in the loop; no unattended public write, no `autoMode.allow` clause needed. | process doc wording (breakdown item 1) |
| **Does the harness's own agents also file GitHub issues?** | **Yes.** The source repo files GitHub issues for guidance feedback too, making the channel the one public inbox. Linear (CAL) remains the harness's build/task queue — the GitHub issue is the public record of the feedback, which is then triaged into Linear if it becomes work. | process doc wording (breakdown item 1) |

## Breakdown

1. **[#205](https://github.com/sluengen/harness/issues/205) — Route guidance feedback upstream (process doc)** — Shipped. (Originally tracked as CAL-1199, Linear-era; that ticket got diverted into an unrelated fix and the doc edit never landed — re-filed and shipped as #205.) Edit `process/harness.md` "Updating the guidance" section to add the rule: on a guidance defect / friction / idea, **draft a GitHub issue** against the repo recorded as your guidance `source.repo` (resolve the Issues URL from `.guidance-lock.yaml`; never hardcode an owner/repo) and **surface it to the operator** to send — search existing issues first, keep the body about the *guidance* not the consumer's proprietary code, and if you are in the source repo and can fix the defect at source, do that too. Bump the process doc's `guidance:` header and its `registry.yaml` version (and the registry's own version). Add a one-line cross-reference in `commands/update-guidance.md` next to its existing LOCAL-edit "suggest pushing upstream" branch. Single shippable, version-stamped change; no `autoMode.allow` clause needed (draft-and-surface is not an unattended write).

## Risks / unknowns

- **Noise / low-value issues.** An eager agent could file duplicates or trivia. Mitigated by scoping to defects and by a draft-and-surface default (pending the autonomy decision), and by asking the agent to search existing issues first.
- **Consumer without a lock file.** A repo that vendored the guidance without `.guidance-lock.yaml` has no `source.repo` to resolve. The rule degrades gracefully: "if you can identify the source repo, file there; otherwise surface the feedback to your operator."
- **Fork attribution.** Resolving from `source.repo` correctly sends a fork's feedback to the fork's chosen source — a feature, not a bug, but worth stating so no one hardcodes our URL later.
- **Outward-facing posture.** Filing a public issue can leak context from a private consumer repo. The wording must caution the agent to keep issue bodies about the *guidance*, not the consumer's proprietary code.

---

**Lifecycle.** A proposal ends in one explicit state: **accepted** (spawn the change specs as Linear issues; record its decisions in the relevant specs), **rejected** (keep this file as the record of why), or **split** (replace with smaller proposals). It does not sit half-decided. Lives in `specs/proposals/`.
