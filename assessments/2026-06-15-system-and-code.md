# System + code assessment — 2026-06-15

**Steward:** steward (`code` + `system` scope, manual deep pass) · **Base:** `dev` @ `e9d93c2` · **Gate:** not run (read-only assessment; no code changed this pass).

## Why this pass

Harness v3's Todo queue is cleared and the next step is **deploying the surface into another repo**. Before that, a broader read than a single-scope `/assess`: is the repo lean and outcomes-focused, is purpose and audience clear, is there duplication or process theatre — and is the deployment mechanism actually built for both deployment modes (blank-slate, and a repo carrying old agents-repo guidance to supersede). Findings are grounded in the live tree (worktrees/caches excluded).

## Verdict — purpose and audience

**The stated purpose is crisp and well-defended; the core is lean and honest.** [CONTEXT.md:47-49](../CONTEXT.md#L47-L49) and the orchestration-boundary decision ([architecture-principles.md:72-87](../specs/architecture-principles.md#L72-L87)) state plainly what this is — single-user, self-hosted, no product UI, no end-users — and, unusually, what it is *not*: *"we are not running deterministic autonomy."* The three-verb model, the SQLite ledger, the HEAD-bound `close` gate, and the guidance system are well-scoped and version-coherent. Version-stamping is real and load-bearing (it is what makes `/update-guidance` able to classify drift), not ceremony.

**The gap is between that stated boundary and two pockets of the tree that were built for the world the boundary defers.** This is the source of the "agents building for a world this didn't inhabit" pattern: where the tree carries latent capability that *looks* operational, the next agent extends it. The fix is not just deletion — it is removing the ambiguity that invites the extension (insights below).

The methodology is mostly anti-theatre — the `/assess` "zero findings is a valid result" framing is the opposite of ritual, and the builder/reviewer role split is agent-context isolation, not org cosplay. The real waste is concentrated, named below.

## Deployment readiness — the two modes

The mechanism is genuinely built, not vaporware. One installer ([INSTALLER.md](../INSTALLER.md), `bootstrap@0.4.5`) does the copy-in; [BOOTSTRAP.md](../BOOTSTRAP.md) is the harness-app onboarding wrapper on top; [`/update-guidance`](../commands/update-guidance.md) pulls later changes via the per-consumer `.guidance-lock.yaml`. The lock contract closes end-to-end (installer writes it, update-guidance reads it).

- **Mode 1 (blank slate):** fully handled. No concerns.
- **Mode 2 (repo with old agents-repo guidance to supersede):** *explicitly anticipated.* [INSTALLER.md:29-34](../INSTALLER.md#L29-L34) names the exact legacy artifacts — `manifest.yaml`, nested `changes/`, and verbatim *"a repo's own `scope-discipline`, `verification-before-completion`, or `code-structure` are now folded into `code-quality`; an old `spec.md` template is now `feature.md`"* — with a no-clobber rule and "do not delete automatically." [update-guidance.md:16](../commands/update-guidance.md#L16) handles re-pointing a legacy lock whose `ref` "may even be a retired-`agents`-repo SHA."

See **SYSTEM-6** for the one real risk before relying on it.

## Findings

### SYSTEM-1 — Autonomous-dispatcher (Hermes/launcher) subsystem is carried as if operational — Medium — **DECIDED: quarantine + defer**

**What:** ~990 LOC of production code implements a host-launcher control socket for an autonomous "Hermes" dispatcher that does not exist and is explicitly deferred. [specs/hermes-orchestration.md](../specs/hermes-orchestration.md) is titled "(live)"; [query_status.py](../harness/cli/query_status.py) synthesizes fields "for Hermes consumption" that key off events (`tool_called`) and failure reasons (`ContractViolation`/`loop_exhausted`/`rejected`) **no live verb emits**.

**Where:** [launcher.py](../harness/launcher.py) (529), [launcher_client.py](../harness/launcher_client.py) (195), [serve.py](../harness/cli/serve.py) (97), [trigger.py](../harness/trigger.py) (169, imported only by tests), `specs/hermes-orchestration.md`.

**Why:** Contradicts the orchestration-boundary decision ([architecture-principles.md:76-85](../specs/architecture-principles.md#L76-L85)), which states Hermes' separate runtime "is superseded (D3); the remaining integration is a thin launch handle." The tree carries a full control-socket subsystem, not a thin handle. Inert code that reads as live invites agents to build more around it — the exact recurrence pattern.

**How:** Quarantine and defer (decided). Move `hermes-orchestration.md` to `specs/retired/` (or rename to mark it not-yet-built); delete or `specs/`-park the launcher/trigger/serve code and its observability synthesis until the autonomous loop is actually being built. Tracked by SYSTEM-INSIGHT-1.

### CODE-1 — Dead/speculative event schema and observability fields (engine residue) — Medium

**What:** [events/schema.py](../harness/events/schema.py) declares **20 event types; live code emits 2-3** (`review`, `close`, `workflow_failed`). `harness status --json` enriches `agent_session_ids` (from a `tool_called` event no verb emits), `failure_retryable` (branches on failure reasons no verb produces), and `runs --failed` (filters `status='failed'`, never written). [state/store.py:116-120](../harness/state/store.py#L116-L120) migrates a `runs.pid` column it documents as "vestigial… always NULL"; `BaseState` carries `workflow_*`/`*_json` columns written as empty.

**Where:** `harness/events/schema.py`, [harness/cli/query_status.py](../harness/cli/query_status.py), [harness/cli/query_runs.py](../harness/cli/query_runs.py), `harness/state/schema.py`, `harness/state/store.py`.

**Why:** Residue of the CAL-574 engine retirement. Dead branches that only their own tests exercise are duplicated/dead knowledge (`engineering-principles`); they inflate the surface and read as supported capability.

**How:** Prune `events/schema.py` to live types (+ a documented "legacy rows" allowance), trim `RunStatus` to `open`/`closed`/`cancelled`, drop the unreachable observability arms and the `pid`/`workflow_*` columns. Sequence after SYSTEM-1 (some of these fields exist only for Hermes).

### SYSTEM-2 — `/build` re-encodes linear-sync and the stepped trio — Medium — **DECIDED: thin driver**

**What:** [commands/build.md](../commands/build.md) (276 lines) re-implements the start→review→ship loop the trio already encodes, and embeds **17 raw GraphQL/`jq` blocks** ([build.md:26-34](../commands/build.md#L26-L34), 206-213, 244-250) duplicating the canonical recipes in [linear-sync:51-97](../skills/linear-sync/SKILL.md#L51-L97). The trio (`/start`/`/review`/`/ship`) contains zero such blocks. `/build` is also absent from the process-doc command table ([process/harness.md](../process/harness.md)).

**Where:** `commands/build.md`, `skills/linear-sync/SKILL.md`, `process/harness.md`.

**Why:** Two parallel encodings of one loop, one of which re-hardcodes Linear's API — guaranteed to drift from `linear-sync` and from the three lean commands. Duplicated knowledge (`engineering-principles`).

**How:** `/build` is the **autonomous** agent-led driver (the trio is the **stepped** driver for freeform sessions — both kept). Make `/build` a thin driver: delegate Linear ops to `linear`, worktree to `worktree-isolation`, implement to `test-driven-development`, the review prompt/`SUBMIT:` contract to `review-discipline`. What stays is only the autonomous-loop control (fix loop, convergence check, implement sub-agent spawn, abandon path) — ~80 lines, not 276. Tracked by SYSTEM-INSIGHT-2.

### SYSTEM-3 — `agents/tasks/` is a redundant layer; the steward pointer ships broken — Medium — **DECIDED: eliminate**

**What:** [agents/steward.md:24](../agents/steward.md#L24) instructs "Follow the procedure in `agents/tasks/steward.md`," but that file is **not in `registry.yaml`**, so it never installs — the reference dangles in every consumer. The task file is also stale: it defines the retired 5-domain model (`agents/tasks/steward.md:21`, *"architecture, harness, test, code, design"*) and writes to `steward-<domain>-<date>.md` at repo root (`:45`), both contradicting the live 2-scope (`code`/`system`) model and the `assessments/` convention. `agents/tasks/release.md` is the same CAL-574-era vintage, overlapping `RELEASING.md`.

**Where:** `agents/steward.md:24`, `agents/tasks/steward.md`, `agents/tasks/release.md`.

**Why:** A "task" is conceptually redundant: the durable *who* is the agent role, the durable *how* is a skill, the durable *format* is a template, and a specific *instance* belongs in Linear. The `tasks/` layer is one of those in disguise — here, a stale skill-in-disguise that ships a broken pointer.

**How:** Eliminate `agents/tasks/`. Fold the steward steps into `agents/steward.md` + `assessment-craft`/`guidance-coherence` + a `templates/assessment.md`; drop the `steward.md:24` pointer. Fold `release.md` into `RELEASING.md`. Tracked by SYSTEM-INSIGHT-3.

### SYSTEM-4 — Skill-boundary duplication — Low

**What:** The "decisions live in the spec they govern / no `decisions/` folder / supersede in place" rule is restated near-verbatim in both `architecture` and `spec-authoring`; "smallest change" + the rule-of-three appear in both `code-quality` and `engineering-principles` with no cross-reference.

**Where:** `skills/architecture/SKILL.md`, `skills/spec-authoring/SKILL.md`, `skills/code-quality/SKILL.md`, `skills/engineering-principles/SKILL.md`.

**Why:** Duplicated knowledge drifts. (The `code-quality`↔`review-discipline` shared sentence is intentional anti-drift wording — not a finding.)

**How:** Let one own each rule and the other point: `spec-authoring` owns decision mechanics, `architecture` keeps only "when is a choice decision-worthy"; `engineering-principles` owns the principle, `code-quality` references it.

### SYSTEM-5 — Engine-era `lessons/` and a split assessment home — Low

**What:** [lessons/](../lessons/) holds **19 tracked engine-era files** (`H-021`, `H-028`, `build-workflow-test/*.yaml`, `ergonomics/run-00N/scenario-*`) — workflow YAML and test-run output from the retired engine, referenced by nothing live. Assessments live in two homes: `assessments/` (15) and `docs/assessments/` (1 stray).

**Where:** `lessons/`, `docs/assessments/code-assessment-2026-06-12.md`.

**Why:** Unused files and a cosmetic inconsistency that makes the durable record harder to find.

**How:** Retire `lessons/` (or move to `specs/retired/`-style archive); move the stray report into `assessments/` and remove `docs/assessments/`.

### CODE-2 — Worktree branch/path rule has two homes — Low

**What:** The `harness/<id>` branch name and worktree path are defined in `identity.py` (`worktree_branch`/`worktree_dir`) and *again* privately in [worktree.py](../harness/worktree.py) (`_branch_for`/`worktree_path`); `start.py` even aliases identity's function to the name worktree.py uses privately.

**Where:** `harness/identity.py`, `harness/worktree.py:72,83`, `harness/cli/start.py:50`.

**Why:** Same rule spelled twice; either can drift.

**How:** Delete `worktree.py`'s private copies; use `identity.py`. Zero-risk.

### SYSTEM-6 — Mode-2 migration path is designed but unexercised, and the fold-knowledge is split across two tools — Medium (deployment risk)

**What:** The "supersede old agents-repo guidance" path has never been run — [update-guidance.md:16](../commands/update-guidance.md#L16) ends: *"the only pre-0.5 install is the harness itself… so this path is currently unexercised."* And the two migration tools disagree on where the fold-knowledge lives: `INSTALLER.md` *knows* `scope-discipline → code-quality`, but `/update-guidance` does not — it would treat the old skill as a generic "removed file" and the new one as a generic "added file," losing any local edits and the fold relationship.

**Where:** `INSTALLER.md:29-34` vs `commands/update-guidance.md` (classification table, no fold map).

**Why:** Deploying to a real Mode-2 repo would be the first execution of an untested path; the split means the *correct* tool for Mode-2 is re-bootstrap (INSTALLER), not `/update-guidance`, and that is stated nowhere.

**How:** Before deploying: (1) **dry-run the migration on a throwaway copy** of a real old-guidance repo and watch the legacy-artifact + no-clobber logic actually run; (2) add one line to INSTALLER/BOOTSTRAP stating Mode-2 uses re-bootstrap, `/update-guidance` is for repos already on a harness lock; optionally (3) collect the scattered step-2/3/4/6 legacy handling into one ordered "migrating off the agents repo" checklist.

## Systemic insights

### SYSTEM-INSIGHT-1 — Scaffolding must be labeled, not latent

Evidence: SYSTEM-1. Deferred-roadmap code that reads as operational is what invites agents to extend a world the repo doesn't inhabit yet. Concrete edit: adopt the convention (state it in `architecture-principles.md`) that **not-yet-built capability lives in `specs/retired/` or carries an explicit "design, not built" banner, and its code carries no live (non-test) caller without one** — plus a guard test that fails if a spec titled "(live)" describes a subsystem whose only callers are tests. Prevents the Hermes/launcher class.

### SYSTEM-INSIGHT-2 — One home per piece of knowledge; commands are thin drivers

Evidence: SYSTEM-2 (and it resolves the `linear` question). State in the process doc / `code-quality` that **a command must not re-encode a skill's content** — Linear ops, worktree lifecycle, the review contract — it references the skill. Concrete edits: (a) rename `linear-sync` → `linear` and make it the single home for Linear operations, leading with **type-based runtime state resolution** (resolve by the stable `type` enum, disambiguate the two `started` states by name) and demoting CONTEXT-cached UUIDs to override-only — today's [linear-sync:75](../skills/linear-sync/SKILL.md#L75) wrongly makes UUID-caching mandatory; (b) add a guard grepping for `api.linear.app` outside the `linear` skill so embedded GraphQL can't reappear in a command. Prevents the duplication class across `/build` and any future command.

### SYSTEM-INSIGHT-3 — Eliminate the `tasks/` layer: task = role + skill + template

Evidence: SYSTEM-3. Record the conceptual model (in `architecture-principles.md` or the process doc): the durable artifacts are the **command** (trigger + scope), the **agent role** (who + which skills), the **skill** (the how), and the **template** (the format); a specific instance belongs in **Linear**. There is no `tasks/` artifact — it is always one of those in disguise. Delete `agents/tasks/`. Prevents the dangling-reference + stale-procedure class at the root.

## Dimensions examined (clean)

- **Core verbs** (`start`/`review`/`close`) — clear flow, correct rollback ordering, bounded JSON output; the close gate (HEAD-bound `reviewed_sha`, dirty-tree refusal, `stale_review`) is the load-bearing correctness property and is implemented tightly.
- **Code duplication (non-trivial)** — git/`_git.py`, Linear client, `_time.py`, `_repo.py` are properly factored single-homes (prior `/assess` passes hit these). Only CODE-2 remains.
- **Exception types** — all 13 are raised in live code; none defined-but-unused.
- **Version integrity** — all header-bearing registry files match their `guidance:` headers; the stamping is load-bearing for `/update-guidance`, not ceremony.
- **Lock mechanism** — coherent end-to-end (installer writes, update-guidance reads), including legacy-lock and settings-file edge cases.
- **Security** — no `shell=True` with user input, no string-formatted SQL, no `eval`/`exec`/`pickle`; path allowlist enforced at the edge.

## Decided actions (this session)

| Item | Decision |
|---|---|
| Hermes/launcher subsystem | Quarantine + defer (stabilise current approach first) |
| `/build` structure | Thin autonomous driver; delegate to `linear` + phase skills; keep stepped trio |
| `linear-sync` → `linear` | Rename; type-based runtime resolution as default; **no** Python wrapper (parked) |
| `agents/tasks/` | Eliminate; task = role + skill + template |

These are candidates for Harness v3 tickets; filing is the next step (this report is the record until then).
