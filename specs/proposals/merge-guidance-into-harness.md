<!-- guidance:template-proposal@0.1.1 -->
---
proposal: merge-guidance-into-harness
status: accepted            # draft | under-decision | accepted | rejected | split
date: 2026-06-13
related: [specs/proposals/harness-as-tool.md, specs/architecture-principles.md, CONTEXT.md, BOOTSTRAP.md, commands/harness.md]
---

# Proposal: Merge the guidance ("agents") repo into the harness — promote the harness to guidance source, with an app vs. installed-surface boundary

> Today the harness is a **consumer** of a separate shared-guidance ("agents") repo: it carries installed copies of the universal commands/skills and a `.guidance-lock.yaml` pinning `source: agents`. This proposes to **collapse the two into one source tree by promoting the harness to be the guidance _source_** — while keeping a clean line between the **harness app** (lives on the machine, never lands in a target repo) and the thin **installed surface** (commands, skills, templates, hooks, process, settings) that does. The distribution channel (`registry.yaml`), not the repo split, gates install footprint; so the merge changes what lands in *target* repos by zero — it changes the *harness's own* role from consumer to source. Distribution is **branch-based and pulled from GitHub**: the harness authors and dogfoods guidance on `dev`; external repos pull the *released* guidance from `main`.

## Problem / motivation

There are two repos:

- **`/Users/scottluengen/Code/agents` — the guidance source.** Holds `registry.yaml` (`registry_format: 1`; a copy-list keyed by installed path, defining two **profiles** — `standard` and `harness` — plus a `meta:` block of source-only files like the installer `BOOTSTRAP.md`). It is the source of record for the universal commands/skills/agents/templates/hooks/process/settings.
- **`/Users/scottluengen/Code/harness` — a consumer of that guidance, plus the harness app.** It carries the *installed* copies of the surface at its root and a `.guidance-lock.yaml` pinning `source: agents, ref: 35ed6cc` with per-file `{version, hash}`. The harness *app* (the Python package under `harness/`, Docker, the verbs) lives alongside.

The split was justified by keeping the guidance **product-agnostic** so many repos could install a consistent agent base (`CLAUDE.md`: "The guidance stays product-agnostic"). That boundary is now taxing the work, and the justification no longer holds:

- **Cross-cutting changes can't be atomic.** A harness change that needs a guidance/doc change (or the reverse) is two repos, two PRs, two reviews, and a round-trip through the agents repo and `/update-guidance`. The clearest case is **CAL-624** — "distribute `/harness run` + onboarding via the agents-repo channel" — which exists only *because* the harness can't ship its own command through a channel it doesn't own. When work stalls because it needs both sides at once, the repo boundary is in the wrong place.
- **The "many consumers" premise is speculative.** There is exactly one consumer — the author. "Installs anywhere, product-agnostic" is aspirational, not a constraint any real external consumer is honouring. YAGNI: we pay the two-repo tax every change to preserve a generality nobody is collecting.
- **The guidance is a stopgap, not a parallel product.** Agent-based orchestration in the guidance repo stands in for a harness that isn't ready yet. The intended end state is the harness running wherever work happens; the guidance is meant to be **absorbed** by the harness, not maintained forever alongside it. Two repos institutionalise a separation the roadmap intends to erase.

Cost of the status quo: every straddling change pays the tax, the parked tickets accrue, and the mental model ("harness = a narrow tool" beside "guidance = the agent base") fights the actual direction of travel — *harness = the whole holistic system for running a repo the agents way: the app plus the surface it installs.*

### Verified on disk (architect pass, 2026-06-13)

Three facts that de-risk the merge and were confirmed, not assumed:

- **The app has zero coupling to the surface.** `grep` across `harness/` for `skills/` / `commands/` / `process/` / `registry.yaml` returns **0 hits**. Nothing in the Python app reads the installed files — the app/surface boundary the proposal wants to "design around" already exists at the code level. The only real leak risk is the *reverse* (an app file riding the install), governed entirely by the copy-list.
- **The merge mechanism is already built and waiting.** The freshness hook (`hooks/guidance-freshness.js`) branches on `registry.yaml` present → **SOURCE-repo mode** vs. `.guidance-lock.yaml` present → **CONSUMER mode**. The harness runs in consumer mode today; the moment `registry.yaml` lands at its root it flips to source mode and begins enforcing surface-version discipline. The tooling was *built* to run in the merged configuration.
- **Install is a path transform, not an identity copy.** The agents repo keeps skills as `skills/<id>/SKILL.md`; the harness root holds the flat *installed* shape `skills/<id>.md`. The merged tree must pick one shape — this is the proposal's largest mechanical cost and drives D2/D4 (below).

## Options

**Option A — Status quo: two repos (agents = source, harness = consumer + app).**
Keep the split; round-trip cross-cutting changes through the agents repo and `/update-guidance`.
*Trade-offs.* Preserves a product-agnostic guidance source *in principle*. But pays the cross-cutting tax every time, can't make straddling changes atomic, and maintains a separation the roadmap intends to remove. Correct only if multiple real external consumers of the bare guidance existed — they do not.

**Option B — Merge into one repo, fully fused (no internal boundary).**
Everything is just "the harness"; app and surface intermingle, the registry/lock channel is discarded.
*Trade-offs.* Simplest mental model, but **destructive of a working mechanism**: the `registry.yaml` ↔ `.guidance-lock.yaml` version/hash protocol and the source/consumer freshness hook are real, tested infrastructure that the merge should *keep*, not delete. B over-merges — it throws away the channel that makes the surface installable and keeps app internals out of target repos. Rejected.

**Option C — Merge into one repo with a durable app/surface boundary; promote harness to source. (Recommended.)**
One source tree. The harness becomes the guidance **source** (owns `registry.yaml` + the installer), keeping a clean line between **(a) the harness app** — Docker, Linear, the verbs; lives on the machine, never installs into a target repo — and **(b) the installed surface** — commands, skills, agents, templates, hooks, process, settings — which the channel (`registry.yaml`, consumed via `/update-guidance` / bootstrap) installs into target repos. The channel, not the repo count, is the *sole* gate on install footprint, so merging sources changes the *target-repo* footprint by zero. The surface is treated as a stable, versioned **interface** (the `guidance:<id>@x.y.z` header it already carries), so today's agent-orchestration implementations can be swapped for harness-app-backed ones without re-touching target repos.
*Trade-offs.* The harness's own role changes materially (consumer → source); it inherits `registry.yaml` ownership and the source-mode hook. But the boundary it preserves is **already enforced** by the registry/lock mechanism and the zero app→surface coupling, so C is mostly *naming and promoting an existing structure*, not building a new one. Kills the cross-cutting tax, keeps target repos clean, models the actual direction (harness absorbs guidance).

**Option D — Keep two repos, add cross-repo sync tooling.**
Shared CI, scripts to mirror changes across the split.
*Trade-offs.* Lipstick. Straddling changes still aren't atomic, and it adds machinery to maintain the very split that isn't earning its keep. Rejected.

## Recommendation

**Adopt Option C.** It extends `harness-as-tool.md` one step: that proposal made the harness *a tool, not a pipeline*; this one makes the harness *the whole system, not a consumer of a second repo*. It fits `engineering-principles` and is strongly supported by the architect pass:

- **YAGNI.** Product-agnostic, multi-consumer genericity is speculative with one consumer. Stop paying for it.
- **Simplicity / atomicity.** One source tree makes a cross-cutting change one PR, one review, one atomic commit — the harness's own atomic-commit principle, finally available across the boundary.
- **Low risk, because the mechanism exists.** Zero app→surface coupling; the freshness hook auto-switches to source mode on `registry.yaml`'s arrival. The riskiest pieces are *path mechanics and a profile-scope decision*, not architecture.

The load-bearing insight: **repo structure ≠ target-repo install footprint.** What lands in a target repo is decided by `registry.yaml`'s `files:` membership, not by how many source repos exist. Merge the sources and not one byte more installs in any *consumer*. (Framing correction the architect insisted on: "footprint changes by zero" is true for *target* repos but **not** for the harness itself — it becomes the guidance source-of-truth and runs the hook in source mode. Own that.)

### The durable boundary (survives even after the harness is ready)

- **The harness app** — Python package, Docker, the verbs — on the machine, operates on repos from outside, never installed into one. Namespaced under `harness/`, `docker/`, `bin/`, `scripts/`, `specs/`, `tests/`.
- **The installed surface** — `commands/`, `skills/`, `agents/`, `templates/`, `hooks/`, `process/`, `settings/`, plus the derived `AGENTS.md`/`CLAUDE.md`/`GEMINI.md` artifacts — installed via the channel.
- **Discriminator:** the surface is *exactly `registry.yaml`'s `files:` membership*. Equivalently: *does this have to be in the target repo's working tree for the local agent/tooling to find and run it?* Yes → surface. No → app. **Default to the app; in-repo only what must be local.** `commands/harness.md` is the one repo-owned command kept out of the registry — app surface, not distributed guidance.
- **Structural guard:** a footprint test that asserts **no path under `harness/`, `docker/`, `bin/`, `scripts/`, `specs/`, `tests/` appears in `registry.yaml`'s `files:`**. This is the enforcement the boundary needs (Breakdown 3).

### The transition risk and the interface answer

Today the surface *is* the agent-orchestration stopgap. As the app comes online, the same commands become thin clients that call the harness, and orchestration migrates from in-repo agent flows into the app. The architect's key find: **`commands/harness.md` is already a thin client over a versioned CLI contract** — `SPEC.md` already names the verb surface (stable flags, exit codes, JSON output, structured refusals) a public contract. So the transition is *already designed* for `/harness run`; D3 extends that same discipline to the universal commands. The rule that makes the swap invisible:

- **patch** — wording, no behavioural change. Auto-pulls.
- **minor** — **implementation swap** (body now calls the harness app; invocation + output contract unchanged). Auto-pulls. *This is the stopgap→app migration, a minor bump by definition.*
- **major** — the **interface** changed (command renamed, argument/output/refusal-reason changed). Surfaces to the consuming repo as a decision.

Get it right: rebuild the engine without re-touching N repos. Get it wrong: cross-cutting churn returns, just inside one repo.

### Distribution: branch-based, pulled from GitHub (D7)

The harness repo is **both the source and the first consumer.** Guidance is authored on **`dev`** and run in place — that *is* the dogfooding; the harness needs no lock of its own (D5), because its working tree on `dev` is the source. When a guidance change has proven out on `dev`, the existing **`dev` → `main`** promotion (the repo's release model, `CONTEXT.md` `branches`) ships it to the release channel. **External repos pull `main`** — they never see in-flight `dev` guidance, so the harness is the canary for every guidance change before it reaches anyone else.

This makes `/update-guidance` (and bootstrap) **pull from the harness GitHub repo at a branch ref**, not a local path — `.guidance-lock.yaml.source` becomes `{ repo, branch, ref }` (external `branch: main`). The command already anticipates this (`update-guidance.md:11` reads "the path/**remote** in `.guidance-lock.yaml → source`"); D7 makes the remote concrete and wires guidance release to `dev → main`.

## Open decisions

Architect pass complete (2026-06-13); recommendations below are **pending the user's accept**.

| Decision | Recommendation / who | Recorded in |
|---|---|---|
| **D1 — Confirm the merge + direction.** Promote harness to guidance source (vs. reverse, vs. stay split). | **user** — effectively settled by this conversation | this proposal + architecture-principles |
| **D2 — Internal layout.** | *Architect:* keep the surface at root in **installed/flat** shape (no `surface/` tree — it would break the `.claude/` discovery symlinks); promote `registry.yaml` as the copy-list (path-transformed from `skills/<id>/SKILL.md` → flat `skills/<id>.md`, dropping the unused directory-per-skill nesting); footprint test is a hard gate. | architecture-principles + CONTEXT.md |
| **D3 — Surface-as-interface contract** *(load-bearing)*. | *Architect:* formalise via the **existing** `guidance:<id>@x.y.z` header + `registry.yaml` (no new interface-registry file); record the semver rule (minor = invisible impl swap; major = interface change) as a new architecture principle; add a test locking the verb JSON / refusal-reason contract. | architecture-principles + `SPEC.md` §public-contract |
| **D4 — Merge mechanics.** History-preserving import vs. clean copy-in. | **Working decision (user did not object to the default): clean copy-in** — the flattening (D2) and the already-mirrored agents content make history-preservation low-value and messier. Flip if you want the agents history kept. | the merge change spec |
| **D5 — Channel + versioning ownership.** | *Architect:* harness becomes the source (owns `registry.yaml` + installer); **drop the harness's `.guidance-lock.yaml`** (a source repo doesn't self-lock); the app's release tag is a separate version line walled off by the footprint test. | architecture-principles + BOOTSTRAP.md |
| **D6 — Profile scope.** `registry.yaml` serves **two** profiles. | **Resolved (user, 2026-06-13): bring all guidance home.** The harness becomes the source for both profiles (`standard` + `harness`); the agents repo is fully absorbed and **retired**. | this proposal + architecture-principles |
| **D7 — Distribution model** *(new — user requirement)*. How do consumers get the guidance? | **Resolved (user, 2026-06-13): branch-based, pulled from GitHub.** Harness authors + dogfoods on `dev`; external repos pull `main`; guidance ships via the existing `dev → main` promotion. `/update-guidance` + bootstrap fetch from the harness GitHub repo at a branch ref (`source: {repo, branch, ref}`), not a local path. | architecture-principles + `commands/update-guidance.md` + BOOTSTRAP.md |

## Breakdown

Provisional; each shippable on its own, spawned as Linear issues once the user lifts the hold (D6 = all guidance home → full scope).

1. **Promote the harness to guidance source** — bring in `registry.yaml` (path-transformed to flat shape, D2) + the installer; **drop `.guidance-lock.yaml`** and declare the harness **source-only / not self-bootstrapped** (D5); verify the freshness hook switches to source mode. The mechanical merge.
2. **Record the app/surface boundary principle** — the discriminator + "default to the app" rule, enumerating the **full** surface (commands, skills, agents, templates, hooks, process, settings) and the derived artifacts, in `specs/architecture-principles.md`. (Correct the surface enumeration: `scripts/` is currently *app* — `scripts/verify.sh` — not surface.)
3. **Footprint test as a hard gate** — assert `registry.yaml`'s `files:` excludes every `harness/` / `docker/` / `bin/` / `scripts/` / `specs/` / `tests/` path. This eliminates (not merely mitigates) the versioning-entanglement risk.
4. **Surface as versioned interface** (D3) — the semver-on-header principle + a test locking the verb JSON / refusal-reason contract; record in architecture-principles + `SPEC.md`.
5. **Supersede CAL-624** — "distribute `/harness run` via the agents-repo channel" is subsumed once the harness owns the channel; reconcile and close it. *(CAL-621 `.harness.toml` and CAL-623 GHCR are independent and unaffected; CAL-622 is already Done.)*
6. **Doc reconciliation** — BOOTSTRAP.md, CONTEXT.md ("where deeper truth lives"), README, CHANGELOG ownership; **resolve the BOOTSTRAP.md path question** (the harness onboarding doc vs. the agents installer `meta:` file must not collide).
7. **Retire the agents repo** — bring the `standard` profile + its product-only files (design-system, ux-design, feature template) home; confirm the harness is the home of all guidance; archive/retire `/Users/scottluengen/Code/agents`.
8. **GitHub-pull distribution (D7)** — make `/update-guidance` + bootstrap fetch from the harness GitHub repo at a branch ref (external consumers = `main`); extend `.guidance-lock.yaml.source` to `{repo, branch, ref}`; wire guidance release to the `dev → main` promotion. (The command already anticipates a "path/remote" source — make the remote concrete.)

## Risks / unknowns

- **The source↔installed duality is the real work.** The merged tree must be both the source and (if it keeps dogfooding) a consumer of itself. Resolved by D2 (hold the flat installed shape; `registry.yaml` is the version source of truth) + D5 (declare source-only, drop the lock) — but it must be resolved *before* accept, because it sets whether the merge is a file-move or a self-hosting redesign.
- **Softer boundary enforcement, hardened by a test.** The app/surface line is now a convention inside one repo, not a repo wall — but the footprint test (Breakdown 3) plus the verified zero app→surface coupling make it a structural guard, not a hope. This is the primary risk and it is *mitigable to elimination* if the test exists.
- **The interface is the real long-term bet.** The merge removes the *repo* tax; it does not remove the *coupling* tax if the surface interface (D3) is badly drawn. A bad interface reintroduces cross-cutting churn inside one repo.
- **Versioning entanglement — eliminated, not just mitigated** — by the footprint-exclusion test: nothing under `harness/` is in `registry.yaml`, so app churn has no surface version to bump.
- **History loss** if clean copy-in is chosen (D4) — low-value here (agents content already mirrored via the lock) but decide deliberately.
- **If real external consumers later appear**, the single-repo source must still emit a clean installable artifact. The channel-as-gate design preserves this; revisit if N grows beyond one.
- **Branch-based release couples guidance to the app's `dev → main` cadence (D7).** A guidance change can't reach external repos without a `dev → main` promotion that also carries whatever app changes sit on `dev`. Usually fine (the harness gates both), but a guidance-only hotfix can't ship independently of the app release. Decide whether that coupling is acceptable or whether guidance needs an independent promotion path.
- **GitHub-pull adds a network + git-auth dependency (D7).** `/update-guidance` shifts from a local-path copy to fetching a remote ref; consumers need read access to the harness repo. And `dev` must stay runnable, since the harness dogfoods it (already the integration-branch expectation).

---

**Lifecycle.** **Accepted 2026-06-13.** Architect pass complete (verdict **accept-with-amendments**, folded into D2/D3/D5 + Breakdown). Decisions recorded in `specs/architecture-principles.md` (*Decision: Merge the guidance repo into the harness*): **D1** merge; **D2** flat-root layout; **D3** versioned-interface surface; **D4** clean copy-in; **D5** harness source-only; **D6** all guidance home / agents repo retired; **D7** branch-based GitHub distribution (`dev` dogfood → `main` release). Breakdown spawned as **CAL-646 … CAL-653** (CAL / Harness v3, all Todo; CAL-646 blocks 647–653). CAL-624 superseded → **CAL-650** (related + commented); CAL-621 / CAL-623 independent, CAL-622 already Done. Extends `specs/proposals/harness-as-tool.md`. Lives in `specs/proposals/`.
