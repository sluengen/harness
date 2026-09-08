# ADR 0021 — Guidance takes a copy where its absence is silent, a bridge where its absence shows in the work

- **Status:** Accepted
- **Date:** 2026-09-08
- **Source:** raised while reconciling two open proposals that need the same answer. Neither is on `dev` yet, so they are named rather than linked: `spine-vocabulary-not-rules` (branch `claude/system-modularization-proposal-39j8ym`) and `refresh-alignment` (branch `proposal/refresh-alignment`), both `under-decision`. Records the reasoning #558 acted on without stating.
- **Relates to:** [ADR 0019](0019-purpose-before-proof.md) (this is its rule applied to distribution rather than to evidence), [ADR 0017](0017-harness-v5-plugin-shaped-guidance.md) D2 and D5.

## Context

One piece of guidance often has to reach two places: two hosts read different filenames, or one rule governs several directories. Three mechanisms deliver it.

| Mechanism | Second copy | Who resolves it |
|---|---|---|
| **Copy** — write the bytes into both files | yes, and it needs a guard | nobody; the bytes are present |
| **Bridge** — a `@path` import, or a symlink | no | **the host, at load time** |
| **Generate** — a build step emits the second file | yes, plus a generator | a build step |

Generate is already retired: `research/01-instruction-files.md:120` rates it "the worst of the three", and #537 deleted the generator. The live choice is copy or bridge.

**The bridge depends on host grace.** Whether the pointer resolves is not a fact about the repository. It is a behaviour of the host's context loader. Nothing in the tree causes it and nothing in the gate observes it.

The repo has answered this question twice, in opposite directions, without writing the rule down.

- **#558 chose the copy for the spine.** `CLAUDE.md` carries the whole of `AGENTS.md` byte for byte, held by `tests/unit/test_spine_template_parity.py`. `specs/features/plugin-surface.md:72` records that it reversed #537's `@AGENTS.md` pointer "instead of arriving through an import the repo does not control", and — this is the part that matters — that **"Measured at capture, the `@AGENTS.md` line did resolve and inline on this host, so the change buys independence from that behaviour rather than recovering a load that was missing."**
- **`refresh-alignment` recommends the bridge for the design layer**, on a fresh probe measuring that same-directory and parent-relative imports both expand on lazy load.

So the question is not whether the import works. It has been measured twice and worked both times. #558 rejected a mechanism it had just watched work, and the reason it had was never recorded, which is why the same question reopened one directory down.

Left undecided, the two proposals ship opposite answers to one question with no record of why either is right.

## Decision

**Choose between copy and bridge by what happens when the guidance is missing, not by how many copies it makes.**

- Guidance whose absence is **silent and consequential** — the laws, the stop rules, the contract vocabulary, anything the enforcement layer assumes has loaded — takes the **copy**, and pays for a guard over it.
- Guidance whose absence is **visible in the work it governs** — craft rules, the design layer, "use the token, never the raw value" — takes the **bridge**. If it does not load, the diff carries the defect the rule forbids and review meets it there.

**A symlink is not an acceptable bridge for anything load-bearing on either side of that line.** Measured 2026-09-08 by the `refresh-alignment` session: git stores a symlink as mode `120000` with the target path as blob content, and a `core.symlinks=false` clone silently produces a *regular file whose content is that path*. The host then loads nine bytes reading `AGENTS.md` **as the rule**. That failure is present-and-wrong rather than absent-and-silent, which is worse than either mechanism this decision chooses between. Where a host admits no import — Codex has none — the fallback is prose in the nearest instruction file that host does read, never a link.

### Why the failure mode is the right discriminator

The two mechanisms do not merely fail differently. They differ in **detectability**, and the asymmetry is not close.

- **A copy fails loudly.** The two files diverge, and a comparison over the tracked tree reddens the gate. The failure is a property of the tree, so a test in the tree can see it.
- **A bridge fails silently.** The host does not expand the pointer, the guidance is absent from context, and nothing errors. It surfaces when an agent does the thing the missing rule forbade.

The closing argument: **a repo-side test cannot detect a reader-side failure.** A test can assert that `CLAUDE.md` contains `@AGENTS.md`. No test in this repository can assert that the host expanded it. Both probes on the record measured one host, at one version, in one session, through one tool — evidence about a behaviour, not a contract anything can be held to.

This is [ADR 0019](0019-purpose-before-proof.md)'s rule — name what the change protects, then use the cheapest evidence adequate to it — applied to how guidance is *delivered* rather than to how it is *proven*. It is an existing principle extended, not a new one.

It also answers P0's standing objection to the guard the copy needs. P0 refuses *a guard larger than the change it guards*. `test_spine_template_parity.py` is a prefix comparison over two files read from the git index, class (b) under [ADR 0017](0017-harness-v5-plugin-shaped-guidance.md) D5, defending something whose failure is otherwise unobservable. That is a guard earning its place rather than a mechanism added where a number would do.

## Alternatives

- *Bridge everywhere, on the research consensus.* `research/01-instruction-files.md:118` states the ecosystem shape — "one source of truth in `AGENTS.md`; `CLAUDE.md` is a thin bridge… Never maintain two copies of the same content" — and it is right about ordinary project instruction files. It is not written about a governance spine that a hook layer assumes has loaded. Taking it whole would put the laws behind a mechanism no gate can observe.
- *Copy everywhere, for uniformity.* Buys detectability for guidance that never needed it, and pays a second copy plus a guard for every craft document in the tree. P0 and P2 refuse it: a guard for a risk never observed, and a second copy where the failure would have been visible anyway.
- *Decide per host capability.* Claude Code has imports and path globs; Codex has placement only. Deciding by what each host can do produces a different answer per host for the same document, which is how the design layer reached two files that must agree and nothing keeping them in agreement.
- *Keep it implicit, as #558 left it.* The cost is on the record: the reasoning sat in a feature spec, the next author did not find it, and the question reopened as an option in a second proposal.

## Consequences

- **The spine stays a copy, and #558 is upheld** with the reasoning it acted on now stated. `test_spine_template_parity.py`, `scripts/plugin-version.js`'s `CLAUDE.md` candidate, and `--refresh`'s copy states all stand.
- **The design layer may take the bridge.** `refresh-alignment`'s Option B is admitted by this rule; a design rule that fails to load produces a hardcoded hex in a diff, which review meets.
- **The `refresh-alignment` proposal's D5 is answered: no symlink** for a UI directory beyond the design directory. Root-spine prose is the fallback where Codex has no import.
- **Two proposals stop blocking each other.** They need one answer, and it resolves in opposite directions for their two subjects, which is why they stay separate proposals rather than merging.
- **New guidance must state which side it is on.** A document added to the surface declares whether its absence is silent, and that declaration chooses its delivery mechanism.
- **This decision is retired by observability, not by a better probe.** If a host reports what it actually loaded, a bridge stops failing silently and the asymmetry collapses. `refresh-alignment` names an `InstructionsLoaded` hook as that instrument; **this repository contains no reference to it and `hooks/hooks.json` registers only `PreToolUse` and `Stop`** (verified 2026-09-08). Confirming such a hook exists and fires is the condition for reopening this record — a further probe that the import resolved is not, because two already have.
