---
feature: plugin-surface
status: implemented
last_updated: 2026-08-19
---

# The plugin surface

> The harness is a spec-driven development process shipped as a Claude Code plugin — skills, commands, agents, and enforcement hooks under one version — plus the gate and guards that make a green tree the only path to a shared branch. This record is the canonical answer to "what is the harness now" (v5, ADR 0017); its retired predecessor is `specs/retired/guidance-system.md`.

## Behaviour

### One plugin, one version

The repository root **is** the plugin: `.claude-plugin/plugin.json` names it `harness` at one semver (`5.0.0` at this record's date), and `.claude-plugin/marketplace.json` makes the repo its own marketplace (`source: "./"`). There are no per-file versions, no `guidance:` headers, no `registry.yaml`, and no consumer lock file — the whole distribution channel ADR 0017 retired. Commands arrive runtime-namespaced (`/harness:build`); in practice only `/harness:init` needs the prefix spoken, to avoid the host's native `/init`.

The shipped inventory, counted from the tree (all counts derived, at this record's date):

| Surface | Count | Where |
|---|---|---|
| Skills | 14 directories | `skills/*/SKILL.md` (`architecture`, `assessment-craft`, `design-system`, `engineering`, `github-issues`, `infrastructure`, `linear`, `review-discipline`, `spec-authoring`, `systematic-debugging`, `ux-design`, `work-discovery`, `worktree-isolation`, `writing-quality`) |
| Commands | 9 files | `commands/*.md` (`assess`, `build`, `capture`, `digest`, `init`, `promote`, `propose`, `review`, `routine`) |
| Agents | 4 files | `agents/*.md` (`architect`, `dev`, `reviewer`, `steward`) |
| Hooks | 5 scripts | `hooks/*.js`, wired by `hooks/hooks.json` via `${CLAUDE_PLUGIN_ROOT}`; `hooks/package.json` pins CommonJS |
| Templates | 9 files | `templates/*.md` — referenced from the skill bodies as their assets (e.g. `spec-authoring` → `templates/change.md`); the physical directory is shared rather than per-skill |

The build/design/operate triad follows the how/what pattern (ADR 0017 D3): the skill body states the method, a plugin asset argues it (`skills/engineering/references/principles.md`; `skills/review-discipline/references/craft.md` is the running precedent), and a repo-owned asset records local reality (`specs/architecture-principles.md` for design, `specs/infrastructure.md` for operations, the spine's *Repo principles* section for build).

### The spine

`CLAUDE.md` is the one always-loaded file: the six iron laws, the lifecycle (fast lane / ticket / proposal), the shared contract (ticket states, holds, assurance levels, the PASS/FAIL/DEFER verdict vocabulary, the tree-oid binding, tracker dispatch, filing rules), an enforcement summary, and the repo's machine-readable config block (`commands:`, `branches:`, `loop:`, `layers:`, `paths:`). Skills are conditional depth behind it and may assume it is loaded; nothing restates the contract elsewhere. The generated block sits between `<!-- spine:generated:begin … -->` / `<!-- spine:generated:end -->` markers and is byte-identical to `templates/spine.md`'s block; everything after the end marker is repo-owned. The whole file is 98 lines at this record's date, under the ≤250-line target ADR 0017 set.

#### Scenario: the fast lane

- GIVEN a small fix that changes no documented behaviour, spans one commit, and needs no independent review
- WHEN an agent is asked to "fix X"
- THEN it works on its own branch in its own worktree, runs the gate, and ships without a ticket — no command carries the fast lane, and the hooks enforce exactly as for ticketed work.

### The enforcement loop

`scripts/verify.sh` is the gate: a toolchain preflight (ruff, mypy, pytest, pytest-xdist, **node** — exit 97, reserved, when the toolchain itself cannot run, so infrastructure failure never reads as a red or green tree), then ruff → mypy over `scripts/` → pytest with coverage (floor 82% over `scripts/`) → the design-token drift guard (`scripts/build_design_tokens.py --check`) → the Codex drift guard (`scripts/generate_codex_artifacts.py --check`) → `scripts/gate_marker.py write`, last, so `set -e` makes the marker mean *green over these exact bytes*. The marker is `<git-common-dir>/harness/gate/<tree-oid>.json`, named by git tree object, fresh for `HARNESS_GATE_MARKER_MAX_AGE_SECONDS` (default 86400).

Three hooks refuse and two advise, all reading that convention:

- `gate-evidence-guard.js` (Stop) refuses ending a turn that claims completion with no fresh marker over any tree the session worked.
- `push-target-guard.js` (PreToolUse: Bash) refuses a `git push` targeting a branch the spine's `branches:` block declares unless a fresh marker covers the pushed tree. It resolves the push's real directory (`cd`, literal-target `pushd`/bare `popd`, `git -C`), denies what it cannot resolve statically (globs, expansions, `--git-dir`/`GIT_DIR=` spellings — the #477 closure), and denies `--mirror` unconditionally and `--all` where a protected branch exists.
- `git-push-guard.js` refuses history rewrites (`--force` in any spelling, `+refspec`, hidden in wrappers) and lends the other two its shell lexer.
- `prompt-guard.js` and `workflow-guard.js` advise on injection-shaped writes and out-of-worktree source edits.

Both branch-reading hooks parse the spine's `branches:` block first and fall back to `CONTEXT.md` for a repo hydrated before v5 (`hooks/push-target-guard.js` `declaredBranches`/`protectedBranches`; `hooks/gate-evidence-guard.js` equivalents; the two parsers are held equivalent by `tests/unit/test_context_branch_parsing_contract.py`). Parsing the name is not resolving it: `gate-evidence-guard.js` turns the declared integration branch into a tip through `integrationTip`, a fallback chain of `refs/heads/<b>` then `refs/remotes/origin/<b>` — local first, so nothing changes wherever a local ref exists, and `origin` hardcoded to match the remote `protectedBranches` already reads via `refs/remotes/origin/HEAD` rather than assuming a second one. Resolving it as a local ref alone was #483: every clone that carries the branch only as a remote-tracking ref — a cloud session, CI, `--single-branch`, a worktree-only task checkout — answered null, which reads as *nothing to claim*, so the Stop guard allowed unconditionally with nothing on stderr and the install looked healthy. Hooks fail open loudly when they cannot run at all; the two push guards then fail closed on facts they cannot establish, where the Stop hook deliberately still fails open — a branch resolving under neither spelling is genuinely ambiguous, and a Stop hook that blocked on ambiguity would wedge the session with no way out. The controls of record remain server-side branch protection and CI gate output.

`scripts/mutate.py` — the instrument that proves guards can fail — refuses to `run` before anything else unless a fresh gate marker covers the target tree (the #473 gate lock, reusing `gate_marker`'s convention; `check` mode needs no marker).

### The guards

`tests/unit/` holds 25 test modules (~11.1k lines, both derived from the tracked tree at this record's date, its three helper modules excluded from the count) admitted under ADR 0017 D5's rule: (a) behaviour of executable code, (b) a property of the spine, (c) integrity of shipped assets, (d) frontmatter compliance, (e) tree-consistency — existence and correspondence of two things both in the tree, never prose meaning. The prose-guard corpus (118 modules on `dev` at 2026-08-17) is deleted; what survives executes the hooks under node, the gate scripts, the mutation instrument, and the workflows' contract modules. New guards are admitted against the rule, not by momentum.

### The assessment layer

`/assess` writes one dated report per pass to `assessments/<YYYY-MM-DD>-<scope>.md` in the `templates/assessment.md` format. That template owns the **retention convention**; `commands/assess.md` step 4 applies it after each pass, folding every superseded report into a one-line entry in the rolling `assessments/LOG.md` and deleting the file. The rule keeps the latest report per scope plus any report with an open finding, and since #468 a **retired scope** is its one exception: a report whose scope the current `/assess` can no longer produce — ADR 0015 narrowed the scopes to `code | architecture` — is superseded once none of its findings are open, with the open-finding bound still binding until then. The clause had one live subject and the same change folded it: `assessments/2026-08-04-system.md`, the last `system` pass, whose nine findings' tickets (#327, #329–#333, #342–#344) plus the two filed alongside it that day by the `code` and `architecture` passes (#328, #334) were all verified closed against the tracker before the deletion. `assessments/` holds three reports at this record's date — `2026-07-19-pre-publication-readiness.md`, which exempts itself from the rotation in its own header, `2026-08-04-architecture.md`, and `2026-08-17-code.md` — plus `LOG.md`.

### The Codex surface, compiled

`scripts/generate_codex_artifacts.py` compiles the secondary surface from the canonical files: `AGENTS.md` (the spine verbatim plus a generated index of commands and skills), `.codex/agents/*.toml`, `.codex/skills/<skill>` symlinks, and a `command-<name>` skill adapter per command (Codex discovers skills, not repo-local slash commands). The outputs are committed; `--check` runs as a gate stage, so a stale compile is a red gate. Hooks do not port — Codex sessions never had them, and enforcement of record is runtime-independent.

### Hydration — `/harness:init`

`commands/init.md`: interview for the repo values, write the spine from `templates/spine.md` (merging above an existing `CLAUDE.md`, never discarding repo content), scaffold `specs/{proposals,features,decisions}/`, seed `specs/infrastructure.md` with the branch topology, declare the plugin's provenance, and add gate plumbing (a `scripts/verify.sh` skeleton plus a copy of the plugin's `scripts/gate_marker.py` only where no gate exists). Working-tree only — the operator reviews and commits. `--refresh` regenerates the content between the spine markers after a plugin update and touches nothing else, so a declaration already written survives it. A consuming repo owns five things afterward: spine, gate + marker writer, `.claude/settings.json` (hook wiring plus the marketplace declaration), and the specs scaffold; no lock, no registry, no `CONTEXT.md`. `MIGRATION.md` carries the lock-file consumer's path, with its honest limits stated.

**Provenance — where the plugin comes from** (#484). The enablement (`enabledPlugins`) names `harness@harness`; the marketplace that name resolves through is registered per machine, so a repo carrying only the enablement degrades silently on a fresh clone — no commands, no skills, and no enforcement hooks, with no error naming what is missing. That is what the first performed consumer migration left behind. `commands/init.md` step 5 now merges the machine-readable declaration into the same settings file — `extraKnownMarketplaces: {"harness": {"source": {"source": "github", "repo": "sluengen/harness"}}}` — and writes the same fact as prose into the spine's repo section, which `templates/spine.md` carries for a host too old to read the key; `MIGRATION.md` step 3 covers a repo hydrated before the step existed. The key, the repository-scope file it is read from, and its **wrapped** entry shape (`{"<name>": {"source": {…}}}`, not a bare source) are measured against the shipped CLI's own settings schema, against the entry it constructs for its official-marketplace fallback, and against the wrapper it writes itself when it registers a marketplace — not inferred. This repo carries the declaration **without** the enablement: `.claude/hooks` is a symlink to `hooks/` and `.claude/settings.json` wires those five files directly, so enabling the plugin here would register `hooks/hooks.json` on top of that wiring and fire every hook twice. `tests/unit/test_marketplace_provenance.py` holds the declaration to both manifests it must correspond with — `.claude-plugin/marketplace.json`'s `name` and the spine's `github.repo` — and asserts the settings file is tracked, since a declaration a clone never receives is the same silent degradation one layer down.

### Two-branch topology

This repo runs `dev` (integration) → `main` (release) — ADR 0003 as amended by ADR 0017 D6, recorded in `specs/infrastructure.md` → *Branch topology*. `.github/workflows/nightly-promotion.yml` checks out `dev`, runs `scripts/promotion-step.sh` (gate on the exact candidate; fast-forward or nothing; never merge, force, or repair), and advances `main` directly on green. `.github/workflows/ci.yml` runs the gate on push/PR to `main` and `dev`. Three-role topologies remain available to repos that deploy to staging — the roles are per-repo configuration in the spine's `branches:` block.

## Data model

No persistent state beyond the tree itself and the gate marker: one JSON file per verified tree oid under `<git-common-dir>/harness/gate/`, freshness by mtime. Markers live in the git directory, so they cannot be committed into the tree they attest.

## Interface surface

- `bash scripts/verify.sh` — the canonical gate; exit 0 green, 97 reserved for an unrunnable toolchain, tool exit codes otherwise. Production callers: `.github/workflows/ci.yml`, `scripts/promotion-step.sh`, every completion claim.
- `scripts/gate_marker.py write` — marker writer; called by `verify.sh`, read by the hooks and `mutate.py`.
- `scripts/generate_codex_artifacts.py [--check] [--root]` — Codex compile / drift guard; called by `verify.sh` and at release.
- `scripts/mutate.py check|run` — mutation instrument; usage in `CONTRIBUTING.md`.
- `scripts/promotion-step.sh` — the nightly's whole logic; called by `nightly-promotion.yml`, executed by `tests/unit/test_promotion_step_script.py`.
- The plugin surface itself (skills/commands/agents/hooks) — consumed by Claude Code via `.claude-plugin/` and, in this repo's dogfood, via `.claude/` symlinks into the source directories.

## Known limitations

- **Hooks are Claude-side only.** Codex sessions run without them; accepted, since enforcement of record is server-side (ADR 0017).
- **The spine can go stale in a consumer** that never runs `/harness:init --refresh`; the generated markers and the refresh command are the remedy. Spine growth is a first-`/assess` metric.
- **The landing page's guidance catalog is unguarded** between the deletion of `scripts/check_landing_page_guidance.py` and its rebuild against a post-v5 source (#482, D8); the design-token guard still holds `docs/index.html` to `design/`.
- **One lock-file consumer has performed the migration** — nano-erp, 2026-08-18. `MIGRATION.md` carries its edges in *Edges from performed migrations* and still states, in *Honest limits*, what remains untested: later migrations should expect repo-specific edges, and the interview, the `CLAUDE.md` merge and uninstall ordering are instruction rather than tested code.
- **Nothing guards the provenance *instructions*.** `tests/unit/test_marketplace_provenance.py` asserts this repo's own declaration corresponds to its two manifests (class (e)); that `commands/init.md` and `MIGRATION.md` still tell a hydration to write one is prose, and ADR 0017 D5 admits no guard over it. The one instance in this tree is the whole mechanical check.
- **`hooks/hooks.json` has no integrity guard** (class (c) would admit one); the manifest is exercised only by installation.
- **No guard enforces the assessment retention convention.** Deriving a report filename from an `assessments/LOG.md` line means parsing that line's prose into a path, which ADR 0017 D5 class (e) excludes — it admits a *cited* path and the file it names, not a constructed one. The retired `test_assessments_retention.py` went in the v5 cull on that ground and was not revived; the state is checked by a reviewer against `git ls-files`.
- The proposals-ledger and tracker behaviours (D7's sweep, holds, boards) are tracker-side and leave no footprint in this tree beyond the provider skills.

## Decisions

- [ADR 0017 — v5: the guidance ships as a plugin](../decisions/0017-harness-v5-plugin-shaped-guidance.md) — the shape of everything above, including the guard admission rule.
- [ADR 0003 — promotion lifecycle](../decisions/0003-promotion-lifecycle.md), as amended 2026-08-17 — topology is per-repo configuration; this repo's is `dev → main`.
- [ADR 0015 — v4: thin verification layer](../decisions/0015-harness-v4-thin-verification-layer.md) — why there is no runtime.
- One licence — everything is MIT: Decision block in [`specs/architecture-principles.md`](../architecture-principles.md).

**Deliberately absent** — a runtime (ADR 0015), a registry / per-file versions / an installer (`BOOTSTRAP.md`) / `/update-guidance` (ADR 0017 D1), a `CONTEXT.md` (absorbed into the spine, D2), and the `staging` role in this repo (D6).

## Cross-references

- specs/retired/guidance-system.md — the registry-era predecessor, retired 2026-08-18.
- specs/infrastructure.md — the operational record this feature's topology section summarises.
