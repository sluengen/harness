# ADR 0022 — The plugin is the whole deliverable, and the declared gate is the assurance

- **Status:** Accepted
- **Date:** 2026-09-09
- **Source:** accepted proposal [`operation-nuke`](../proposals/operation-nuke.md), built as #620
- **Supersedes:** [ADR 0020](0020-authored-tree-binding.md) (the authored-tree binding) and, in effect, [ADR 0018](0018-gate-marker-convention-is-node.md) (the marker's implementation language, moot once the marker is gone)

## Context

At the 2026-09-08 process assessment this repository measured 4,056 lines of guidance — the skills, agents and templates a consumer installs — against 9,384 lines of executables and 28,065 lines of tests. Assurance per product line stood at 6.86, up from 5.36 six weeks earlier: the suite had grown 31.5% in that window while guidance grew 2.7%.

The growth was an accretion chain, and each link named the one that caused it. `gate-marker.js` binds a verdict to a git tree oid. `land.js` (585 lines) exists because that binding "modelled at 7.4 attempts to land at eight pushes an hour". `harness-refs.js` (483) exists to share gate outcomes between sessions without a service — a coordination problem the binding created. `harness-config.js` (598) exists because three hand-rolled readers of one YAML file produced four recorded parser bugs (#487, #488, #510), two of those readers being marker hooks. `plugin-version.js` is the third attempt at one version bump. Not one of them answers a problem a user has.

The binding also has a measured consumer-side cost, recorded in the decision that defends it: ADR 0020 notes 23% of commits on `calibrate`'s integration branch are reconciliation merges.

**What the machinery enforced was a posture this repo's Principles explicitly decline.** The spine's stated risk appetite accepts a defect reaching the integration branch, because the gate and the next builder catch it and a revert is cheap. P0 refuses "an assurance calibrated for a stage the product is not at". The marker complex was that assurance.

Incremental retirement had not converged: the most recent process assessment ran a full mutation sweep and its single concrete deletion candidate was a 39-line wording guard, 0.1% of the machinery.

## Decision

The plugin is the whole deliverable. Four points, each binding on future work.

### 1. No plugin-owned file persists in a consumer

The plugin stops writing `gate-marker.js`, `harness-config.js`, `scripts/package.json` and the `verify.sh` skeleton into consumer repositories. It ships **assets a consumer then owns** — the design-system tier and its token builder are the pattern — and it ships nothing it keeps rewriting. The distinction is who owns the file after it lands: a consumer-owned copy is fine, a plugin-owned copy the plugin refreshes is not.

**`verify.sh` is disowned, not removed.** It remains the gate a consumer runs at landing; it simply belongs to the repository and is no longer wired through the marker. `hydrate` neither writes it, classifies it, nor touches it.

**Nothing breaks on the plugin update.** A consumer's vendored `gate-marker.js` keeps working — `verify.sh`'s public branch execs it, it resolves `commands.verify`, spawns the internal branch and runs the stages, writing a marker no surviving hook reads. The cost is a redundant hop and dead files, not a red gate, so each repository simplifies on its own schedule against the one-off transition prompt (#629).

**This forecloses shipping executable code that runs inside a consumer repository** — no codemod, no generator, no lint rule, no migration script. A future capability needing that is a new decision.

### 2. A consumer's CI and branch protection are out of lane

The harness requires a repository to **declare** its branch roles in `harness.yaml`; it requires nothing about how those branches are protected. Skills act on the declared roles — `/routine` pushes only the integration branch, `/promote` moves between them — and nothing may require CI, branch protection, or a billing plan.

**The harness's assurance is the gate the repo declares in `commands.verify`, run and read by the builder, plus the independent review.** Server-side controls are the repository's own: neither required nor assumed. No shipped file may claim one as the harness's own — including the spine's former sentence that "the controls of record are server-side branch protection and gate output in CI", which names a control the plugin cannot require and a consumer may not have.

This repository keeps CI and branch protection **by its own choice under the same rule** — dogfooding its posture, not claiming an exemption from it.

### 3. A plugin-shipped executable reads what *is*, never what *passed*

Binding on any executable the plugin ships — a hook, or a packaged script.

**It may read:** the operation in hand (the intercepted tool call, the working directory) · what the repository declared (`harness.yaml`) · what the run declared about its own phase · what git can answer about the tree in front of it.

**It may never read a verdict** — whether a gate passed, a review happened, a human approved, CI is green, or a tree was certified.

The line falls there because a fact is answerable where the guard already stands, from inputs it already holds, while a verdict lives elsewhere and must be *found* — and finding it is step one of the chain that produced the marker, the tree resolution, three parsers and 3,110 lines of hooks. Every link was reasonable from the one before; this refuses the first.

The distinction was already latent in the data model. `.harness/run.json` carries eleven fields; the test-lock guard reads `tests_locked`, `stage` and `base_commit` and never touches `verdict`, `reviewed_tree`, `gate_marker_tree` or `review_cycles`. Its own spec says of `gate_marker_tree` that the field "never stands in for reading it". One column is what is; the other is what passed.

Every surviving executable satisfies this without a grandfathering clause: `prompt-guard` reads the tool call, `workflow-guard` the working directory, `test-lock-guard` its declared test paths and the run's own phase, the reduced `push-target-guard` the push target and declared branches, and `plugin-version.js` the declared release branch and manifest contents at a ref.

### 4. Escalate from no guard, and refuse on two grounds only

**Default to no guard.** Escalate one step at a time, with a recorded reason.

**Advisory** where the failure is recoverable and self-announcing. A missed spelling costs one un-warned action.

**Refuse** on either ground, never on general caution:

1. **The failure is unrecoverable** — which at this stage means the spine's protected areas: user data, credentials, money. Not a second vocabulary; the same three.
2. **The failure is silent *and* consequential** — it presents as success, nothing downstream surfaces it, *and* it costs quality, flow, or cost. Silence alone is insufficient: most silent failures are not worth a line of code.

The asymmetry that makes this the cost-driver: **an advisory tolerates false negatives and stays small; a refusal must not be bypassable and therefore grows a parser.** `git-push-guard.js` runs 971 lines because deciding a force-push from a raw command string needs a POSIX shell lexer — deny globs missed `-fq`, trailing `--force`, and `+HEAD:dev` with the remote omitted. A refusal buys that parser; record the purchase in the change spec's Cost line against its guard-to-change ratio.

**Point 3 takes precedence over point 4 where they disagree.** A guard scoring silent-and-consequential but requiring verdict knowledge does not get built: the escape hatch is a new decision record, never an exception. Without this the first conflict is resolved by reaching for the marker.

## Alternatives

- *Keep the marker, buy branch protection for private consumers* — closes the enforcement gap on repos that lack it. Lost on two counts: consumer protection is out of lane by point 2, and it addresses none of the maintenance burden, which was the actual complaint. Spends money to keep the thing that costs time.
- *Retain a thin advisory that reads gate state* — a warning rather than a refusal on an ungated tree. Lost because it keeps one vendored reader, so the lockstep survives in miniature, and because it is the exact shape the accretion takes next: a plugin-resident advisory reading the marker satisfies points 1 and 4 and is refused only by point 3, which is why point 3 exists.
- *Continue incremental retirement* — assess, and delete what mutation proves dead. Lost on its own evidence: 39 lines per assessment against 37,449, with the ratio moving the wrong way for six weeks.

## Consequences

**Accepted residual risk.** A red tree can reach the integration branch and sit there until something surfaces it. The builder who hits red at integration fixes it then, whatever the cause — stop the line, not stop, so no tick stalls. What remains is a narrow duplication window: an agent that branched from an already-red integration branch and has not yet rebased may spend effort on a fix another agent is landing. Rebasing before the gate closes most of it. That cost is duplicated effort measured in minutes, against a prevented defect a revert would have fixed anyway.

**Obligations this creates.** Reconciliation moves from `land.js` into `/build`'s prose, so "rebase from the integration branch before you gate" becomes an instruction rather than a mechanism — the single instruction in the new shape most worth measuring for effectiveness. The `/build` → `/promote` handoff becomes a second prose-enforced boundary, with the ticket's own state as its record.

**What is retired.** ADR 0020's tree binding and the landing posture built on it. ADR 0018's choice of JavaScript for the marker helper, moot once the helper is gone. The vendoring that ADR 0021 reasons about, and with it the open question at #617.

**What this does not touch.** The three assurance lanes, the review discipline, the tracker semantics, the improvement ledger, and `test-lock-guard.js` — which stays because it is the one guard with independent evidence behind it (over 79% of measured cheating is editing the test directly) and it satisfies both point 3 and point 4's second ground.
