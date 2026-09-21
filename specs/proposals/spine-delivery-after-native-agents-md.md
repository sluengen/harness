---
proposal: spine-delivery-after-native-agents-md
status: accepted
date: 2026-09-21
related:
  - specs/decisions/0021-copy-or-bridge-by-failure-mode.md
  - specs/features/plugin-surface.md
  - skills/hydrate/SKILL.md
---

# Proposal: retire the derived host copy now that Claude Code reads `AGENTS.md`

> Claude Code v2.1.277 reads `AGENTS.md` as project instructions when no `CLAUDE.md` is present, which retires the reason the spine is copied byte for byte into a second file — but not, on measurement, the reason a `CLAUDE.md` exists at all.

## Problem / motivation

**The premise is confirmed, with a caveat that changes the answer.** Claude Code v2.1.277 (released 2026-09-18, shipped as the built-in `agents-md` plugin) reads `AGENTS.md` as project instructions when the working directory and its ancestors carry no `CLAUDE.md`, `.claude/CLAUDE.md` or `CLAUDE.local.md`. The behaviour is a default, not a guarantee: it is governed by a per-**user** `instructionFiles` setting with four values, and it is unavailable on Amazon Bedrock and other third-party providers, in sessions with telemetry disabled, under `disableAllHooks` or `allowManagedHooksOnly`, on versions before 2.1.277, and in the first session after an upgrade.

Four probes, run 2026-09-21 against `claude -p` at **v2.1.278** in this environment, each a fresh scratch repository:

| Fixture | Files at the repo root | Result |
|---|---|---|
| A | `AGENTS.md` carrying a codeword | codeword returned — **`AGENTS.md` was read** |
| B — control | `README.md` only | `NONE` — the probe can fail |
| C | `AGENTS.md` + an unrelated `CLAUDE.local.md` | **`NONE`** — and the session named `CLAUDE.local.md` as its only project file |
| D | `AGENTS.md` + `CLAUDE.md` (`@AGENTS.md` + deltas) + `CLAUDE.local.md` | both codewords returned |

Fixture C is the finding. A developer keeping personal uncommitted notes in `CLAUDE.local.md` — an ordinary act the host documents — **silently suppresses the entire spine**: laws, lanes, stop rules, verdict vocabulary, all absent, no error, nothing in the tree to see it. That is the textbook silent-and-consequential failure [ADR 0021](../decisions/0021-copy-or-bridge-by-failure-mode.md) was written about, now measured rather than argued.

**What the status quo costs.** The derived copy is one of the most expensive mechanisms on the surface relative to what it delivers, and every line of it exists to keep two files byte-equal:

| Cost | Size |
|---|---|
| `tests/unit/test_spine_template_parity.py` — *the second correspondence* (prefix relation + #594 boundary marker), lines 755–1201 | 447 lines |
| `tests/unit/test_plugin_version_script.py` — three tests pinning the copy as a version home | ~67 lines |
| `scripts/plugin-version.js` — the `CLAUDE.md` candidate and the eight-line comment earning it | 9 lines |
| `skills/hydrate/SKILL.md` step 12 — the derivation, its four states and the mandatory overwrite report; the longest step in a 113-line skill | ~3.5 kB |
| `agents/harness-audit.md` — *The derived copy* check | 4 lines |
| `scripts/harness-config.js` — `CLAUDE.md` in `SOURCES` | 1 entry |
| `specs/features/plugin-surface.md` — *The host copy*, *The boundary marker*, the five-homes count | ~6 paragraphs |

Roughly **530 lines of test and script**, plus hydration's largest step and an audit check, all in service of a copy. The `<!-- spine:copy:end -->` marker (#594) exists only because the first edit to either file destroyed the boundary — machinery guarding machinery.

Nothing is on fire. Doing nothing costs the table above, indefinitely, for a mechanism whose stated justification — that the alternative depends on host grace nothing in the tree observes — now has to be re-read against a host that reads `AGENTS.md` natively.

## Options

**Option A — Status quo.** `CLAUDE.md` stays a byte copy of `AGENTS.md` plus deltas, derived by hydration, held by the prefix guard. · *For:* nothing to do; the laws load on every host, every provider, every version, regardless of settings; ADR 0021 stands unamended. · *Against:* pays the whole table above for a property the host now largely provides by default; keeps a second copy of a 88-line document and a 447-line guard over it; keeps the boundary marker, whose only job is to survive drift in the copy. Refused by P0 (*a second defence that shares an operand with the first*; *an assurance calibrated for a stage the product is not at*) and P2 (*a second copy*; *a guard that re-implements a host feature*).

**Option B — `AGENTS.md` alone.** Delete `CLAUDE.md`; fold the *Claude Code deltas* into `AGENTS.md` under their own heading below the generated block; hydration writes one spine and stops. · *For:* one file, full stop — the largest simplification available, and the whole table above retires; matches the ecosystem shape `research/01-instruction-files.md:118` records. · *Against:* fixture C — any `CLAUDE.local.md` at or above the working directory silently voids the spine, and the plugin cannot see or prevent one; the unavailability list (Bedrock, telemetry off, `disableAllHooks`, pre-2.1.277) voids it too; Codex reads ~33 lines of Claude-only instructions every session; the deltas lose the scoping that is their entire reason for existing; the loading behaviour is a **per-user** setting the repository cannot pin, so two developers in one clone can disagree about whether the laws are in force.

**Option C — Retire the derivation, keep a thin hand-owned `CLAUDE.md`.** `CLAUDE.md` becomes `@AGENTS.md` followed by the host deltas — roughly 35 lines, written once, generated by nothing, guarded by nothing, versioned by nothing. Hydration writes it where absent and never touches it again. · *For:* retires the same ~530 lines Option B retires, because the cost is in the *derivation*, not the file; fixture D measured the spine loading through the import with a `CLAUDE.local.md` present; works on every provider, every version, every setting value, including `claude-md`; the host documents that an `@AGENTS.md` import never double-loads, whichever `instructionFiles` value is set; deltas stay host-scoped; `InstructionsLoaded` hooks fire and `/context` lists the file, neither of which is true for a natively-read `AGENTS.md`. · *Against:* two files where the operator asked for one; depends on `@`-import expansion, which ADR 0021 calls host grace — though the same objection now applies to native reading, and with a wider failure surface.

**Option D — Ship both shapes and let each consumer choose.** Hydration asks, or leaves whichever shape it finds. · *For:* every consumer gets the trade-off they want. · *Against:* ADR 0021 already rejected *decide per host capability* — it produces a different answer per host for one document, and "is how the design layer reached two files that must agree and nothing keeping them in agreement". Two shapes doubles hydration's state machine to retire a derivation; P0 refuses it.

## Recommendation

**Option C.** Retire the derivation; keep `CLAUDE.md` as `@AGENTS.md` plus the deltas.

The operator's instinct is right about what is expensive and slightly off about where the expense sits. **The cost is the derivation, not the file.** Option C deletes every line in the cost table — the 447-line guard, the version home, hydration's longest step, the audit check, the boundary marker — and what remains is a static 35-line file that nothing generates and nobody must keep in sync. Option B buys one fewer file on top of that, and pays for it with fixture C.

Three arguments carry it:

1. **The guard dies with its subject, which is the legitimate retirement.** ADR 0017 D5 requires prose-about-prose guards to die *with their subjects, in the same change, never before*. Under Option C there is no copy, so there is nothing that can diverge, and the 447 lines go because their subject went — not because the bar was lowered.
2. **Fixture C is the measured version of ADR 0021's own argument.** That record chose the copy because "a repo-side test cannot detect a reader-side failure". Native `AGENTS.md` reading does not answer that objection — it widens it, because the condition is now a per-user setting and the presence of any `CLAUDE.md`-family file anywhere above the working directory. The import is the one shape measured to survive both.
3. **Stay in our lane cuts toward C, not B.** This repo cannot see a consumer's provider, their Claude Code version, their `instructionFiles` value, or their `CLAUDE.local.md`. Option B makes the laws conditional on all four; Option C makes them conditional on none. The plugin's job is to deliver the spine, not to assume a consumer's environment.

ADR 0021 needs amending either way, and its own text says how: the discriminator (*choose by what happens when the guidance is missing*) survives intact, and it is the **option set** that changed — the choice was copy-or-bridge, and native reading adds a third that is strictly weaker than the bridge on every failure mode measured here. That is a new reopening condition, not the answered one.

**The counter-argument the operator should weigh before deciding.** If the consuming population is only repositories the operator controls, on current Claude Code, with default settings and no `CLAUDE.local.md` convention, Option B's residual risk reduces to a discipline — don't create one — and it costs one fewer file and one fewer concept. That is a legitimate call at this stage, and it is the operator's; it is the first open decision below.

## Target outcome — decided 2026-09-21

**Option C, with `CLAUDE.md` carrying host-specific content and nothing else.** Three bodies of content, and the file boundary is what separates them:

| | Content | True on both hosts? | Lands in |
|---|---|---|---|
| 1 | The generated spine block — principles, laws, lifecycle, contract | yes | `AGENTS.md`, between the `spine:generated` markers |
| 2 | Repo specifics — `## This repo`, *Repo principles*, *Where deeper truth lives* | yes | `AGENTS.md`, below the end marker |
| 3 | Host deltas — `# Claude Code deltas` | **no** | `CLAUDE.md`, below the import |

```
AGENTS.md     <- 1 + 2.  The source, and the file Codex reads.
CLAUDE.md     <- @AGENTS.md, then 3.  Nothing else.
```

**The split rule, which is what makes the boundary self-explaining:** a line belongs in `CLAUDE.md` if and only if it is **false or absent on the other host**. Nothing else earns a place there, and no guard is needed, because the rule is decidable by reading the line.

Why row 3 does not move up into `AGENTS.md`, which would leave a pure one-line shim: Codex reads `AGENTS.md` as its only root instruction file — it has `.codex/agents/`, `.codex/rules/` and `.codex/config.toml`, but no markdown spine of its own — and several deltas are not merely irrelevant there but **false**: the `/harness:<name>` invocation prefix, the Artifact rendering in `/propose` step 3, and `agents/` as the role directory. Hoisting them would oblige a counter-section for Codex, leaving `AGENTS.md` carrying two host sections that every reader must filter — worse than letting the file boundary filter for free. A secondary consequence, recorded because it is the reason the shape survives a later reader: a one-line shim is a file whose purpose is invisible, and the deltas are what make `CLAUDE.md` visibly earn its place.

## Not doing

- **A gate check that the host actually loaded the spine** (`InstructionsLoaded` in CI) — ADR 0021's clause of 2026-09-10 answered this: the instrument runs inside a session reading a file, not over the tree in `scripts/verify.sh`. Reopen if the gate gains a way to observe a load over the tree rather than inside a session.
- **A symlinked `CLAUDE.md`** — ADR 0021 refuses it and the host documents the same failure: a `core.symlinks=false` clone produces a regular file whose content is the nine bytes `AGENTS.md`, loaded as the rule. Reopen never; this is present-and-wrong, the worst failure mode available.
- **Writing `instructionFiles` into settings for the consumer** — it is a per-user setting the host ignores in project and local settings files. Out by construction, and by *Stay in our lane*. Reopen if the host makes it project-scoped.
- **Touching the design layer's bridge** — ADR 0021's design half is untouched by this proposal, and its reasoning is unaffected. Reopen only if the design layer's own failure mode changes.
- **Changing `.claude/rules/` delivery** — rules files do not count for the `AGENTS.md` check and keep loading alongside it either way. Nothing to decide.
- **Deleting a consumer's existing `CLAUDE.md` during hydration** — hydration never rewrites a repo-owned file, and this proposal does not make it start. It reports and retains; the consumer migrates when they choose.
- **A guard that a `CLAUDE.local.md` is absent** — unenforceable from the tree (the file may sit above the repository) and pointless under Option C. Reopen only if Option B is chosen, where it becomes a real and unsatisfiable obligation.

## Open decisions

| Decision | Who decides | Resolution | Recorded in |
|---|---|---|---|
| Option B or Option C — is the residual silent-failure surface of `AGENTS.md`-alone acceptable for the consuming population? | operator | **Option C**, 2026-09-21. The measured `CLAUDE.local.md` suppression is not accepted. | ADR (amends 0021), item 1 |
| Do the host deltas sit below the import in `CLAUDE.md`, or hoist into `AGENTS.md` as a `## Claude Code` section, leaving a pure shim? | operator | **Below the import**, 2026-09-21, under the split rule in *Target outcome*. Raised at hand-over; several deltas are false on Codex, which reads `AGENTS.md`. | ADR (amends 0021), item 1 |
| Does the spine's own *This repo* guidance gain a line about the host-file shape, or does it stay in `plugin-surface.md`? | architect | open — not blocking; item 1 settles it at design time | `specs/features/plugin-surface.md` |
| Under B only: what, if anything, the plugin says about `CLAUDE.local.md` to consumers | operator | **moot** — B was not chosen | — |

## Breakdown

The four-dimension test fires on **blast** (the shape reaches hydration, the audit agent, the version script, two test modules and the config reader) and **comprehension** (the operator cannot steer items 2 and 3 without the shape settled). So item 1 carries the decision and lands the shape, and is held for the operator.

Filed 2026-09-21. Issues created, lanes labelled, dependencies declared (#706 and #707 both blocked by #705) and #705 held with `input`. **Board placement and priority are unset**: Projects v2 is GraphQL-only and every `gh project` write from this session returned `unknown owner type`, so the three filings are incomplete under `tracker` → *`create`* until a session with GraphQL sets Status and Priority.

1. **[#705](https://github.com/sluengen/harness/issues/705) — Record the decision and land the shape** — amend ADR 0021 with the new option set, the probe evidence, the chosen delivery and the split rule from *Target outcome*; land this repo's own `CLAUDE.md` as `@AGENTS.md` plus the *Claude Code deltas* and nothing else; update the *Repo principles* bullet that counts three `spine:generated` markers. `assurance:complex` (a contract change and a consequential decision). **Held with `input`.**
2. **[#706](https://github.com/sluengen/harness/issues/706) — Retire the derivation from the shipped surface** — `skills/hydrate/SKILL.md` step 12 collapses to write-once-if-absent-never-rewrite; `agents/harness-audit.md` loses *The derived copy*; the `<!-- spine:copy:end -->` marker retires with it. `assurance:simple`. Depends on 1.
3. **[#707](https://github.com/sluengen/harness/issues/707) — Retire the guard and the version home** — delete the second correspondence in `tests/unit/test_spine_template_parity.py` (lines 755–1201), the `CLAUDE.md` candidate in `scripts/plugin-version.js` and its three tests, and the `SOURCES` entry in `scripts/harness-config.js`; five version homes become four. `assurance:simple`. Depends on 1; independent of 2, so the two run in parallel.

## Risks / unknowns

- **The probes measured one host, one version, one environment.** v2.1.278 under Claude Code on the web, 2026-09-21. They are evidence about a behaviour, not a contract — the same limitation ADR 0021 states about the two import probes before them. They do not measure a consumer's host, and nothing in this repository can.
- **Under Option B, fixture C is a live defect in every consumer, not a hypothetical.** The failure is silent, the remedy is a per-user setting, and the blast radius is the whole spine.
- **Retiring the 447-line guard removes the only tree-side detector of spine/host-file divergence.** Legitimate under Option C, where the subject dies with it; under Option A it would be a loosened bar. Worth naming so a later reviewer does not read the deletion as the latter.
- **`plugin-version.js` drops from five homes to four.** Its `already-ahead` and `stale-base` logic is home-count-agnostic, but the three deleted tests are the only pins on the candidate-membership rule, so item 3 should confirm what still holds membership by construction rather than assume it.
- **What would invalidate the recommendation:** the host making `instructionFiles` project-scoped, or shipping a tree-observable load report, either of which collapses the asymmetry Option C is buying against. Also a measurement that `@AGENTS.md` expansion has become conditional in the way native reading is — three probes have now found otherwise.
