# Code reassessment — 2026-06-13 (code-steward, run b)

**Filed:** CAL-634 (CODE-1 + CODE-3, finding — **actioned in this same change**) · CAL-635 (CODE-2, finding — Todo, verified, deferred to preserve atomic scope) · CAL-636 (CODE-INSIGHT-1, insight — Todo + `decision`-flagged). No actionable Todos existed in Harness v3 (CAL-633 is `decision`-parked; CAL-620–624 are Backlog), so this is the `/assess code` fallback path.

**Summary:** Gate green (576 passed, exit 0 on the verified worktree). One wholly-contained NEW finding actioned — the `harness --help` banner and package docstring still described the retired "workflow execution engine" model that SPEC §1 explicitly contradicts. A small cluster of `events/` docstrings cite §4.9 for event types that actually live in §4.7 (filed CAL-635, not actioned). Everything else checked was clean or already captured by the in-flight CAL-629/632/633 docstring-cite cluster.

Branch: `assess/code-2026-06-13b` off `dev`. Gate output: `/tmp/verify-assess-13b.txt`.

## Actioned this run (CAL-634)

CODE-1 + CODE-3 fixed test-first on this branch (commit `docs(cli): retire "workflow execution engine" framing …`):
- `harness/cli/__init__.py:43` → `help="Deterministic, audited verbs an agent calls to drive a ticket — see SPEC.md"`.
- `harness/__init__.py:1` → `"""Harness — deterministic, audited verbs an agent calls to drive a ticket. See SPEC.md."""`.
- Locks added to `tests/unit/test_cli_surface_locked.py`: `test_cli_help_banner_describes_the_verb_model` (asserts on `app.info.help`) and `test_package_docstring_describes_the_verb_model` (asserts on `harness.__doc__`) — each asserts the retired-framing regex `workflow execution|\bengine\b` does **not** match and the verb model is named. Both red before the fix, green after. Independent reviewer PASS; full gate 576 passed.

---

## Findings

### CODE-1 (High) — `harness --help` banner describes the retired engine model

- **What:** The top-level Typer app help string still calls the tool a "Deterministic workflow execution harness." That is the retired deterministic-workflow-engine framing. SPEC §1 (current) defines the harness as "a set of deterministic, audited verbs an agent calls — **not** a pipeline that drives agents," and §3's banner records that the engine was deleted in CAL-574. The `--help` banner therefore states the opposite of the current model to anyone running the CLI.
- **Where:** `harness/cli/__init__.py:43` (`help="Deterministic workflow execution harness — see SPEC.md"`). This is the literal `harness --help` output, not an internal comment.
- **Why:** As-built-prose-vs-current-model divergence on a **public-contract surface**. SPEC §1.5 names the verb surface (and by extension its help/JSON output) a public contract; the principle line in §1 is the canonical description. A user reading `--help` is told the tool is a pipeline engine that drives agents — the exact inversion the harness-as-tool proposal reversed.
- **How (test-first):** Add a unit test that invokes the CLI help (Typer `CliRunner().invoke(app, ["--help"])`) and asserts the banner does **not** contain "workflow execution" / "engine" and **does** name the verb model (e.g. asserts on "verbs" or "audited"). Watch it fail. Then change line 43 to a verb-model description, e.g. `help="Deterministic, audited verbs an agent calls to drive a ticket — see SPEC.md"`. Wholly contained: one string + one test; no behaviour change.

### CODE-2 (Medium) — `events/` docstrings cite §4.9 for event types that live in §4.7

- **What:** Three docstrings/anchors in the events module point at SPEC **§4.9** for the canonical event types. §4.9 is a *current* section but covers `harness.launcher` / `harness.workspace` / `harness.trigger` — nothing about events. The current home for the event-log writer and its event types is **§4.7** (`harness.events.emitter`). So these are live `harness/` docstrings citing the wrong *current* section (a distinct class from the retired-§ cites already captured under CAL-633, which a retired-§ grep-guard would not catch because §4.9 is live).
- **Where:** `harness/events/emitter.py:1` ("see SPEC §4.9"), `harness/events/emitter.py:76` and `:85` ("the canonical SPEC §4.9 event types"/"the canonical SPEC §4.9 set"), `harness/events/schema.py:1` ("Event type literals — see SPEC §4.9"). (`harness/events/schema.py:35` cites §4.4 for `decision_violation`, a retired event type — leave it with the CAL-633 retired-cite judgement call, see Not-flagged.)
- **Why:** Stale/wrong doc cross-reference causing confusion (code-quality: a doc pointer that resolves to the wrong section is worse than none). A reader following §4.9 lands on launcher/workspace/trigger and finds no event-type contract.
- **How:** Replace the four §4.9 references in `emitter.py` (×3) and `schema.py:1` with **§4.7**. Cite-only, atomic, no code change. If CAL-633's guard is generalised from "retired-§ cites" to "docstring §-cite resolves to the section that actually documents this module," this finding folds into it — but as written CAL-633 is scoped to retired sections only, so this is not currently covered.

### CODE-3 (Low) — package docstring repeats the retired engine framing

- **What:** The top-level package docstring describes the harness as a "deterministic workflow execution engine" — same retired framing as CODE-1, but in the package `__init__` rather than user-facing help.
- **Where:** `harness/__init__.py:1` (`"""Harness — deterministic workflow execution engine. See SPEC.md."""`).
- **Why:** As-built-prose drift; lower severity than CODE-1 because it is not a user-visible surface (no `--help` exposure), only read by maintainers opening the file.
- **How:** Align with the verb model, e.g. `"""Harness — deterministic, audited verbs an agent calls. See SPEC.md."""`. Naturally bundles with CODE-1 in one cite-only commit.

---

## Not flagged (checked, deliberately excluded)

- **Retired-§ docstring-cite cluster (CAL-629 / CAL-632 / CAL-633).** Confirmed still present on `dev` and correctly out of scope:
  - `worktree.py:1` (§9) and `identity.py:1` (§8) — CAL-632 fixes (PR #80), verified still §9/§8 on `dev` (PR not yet merged), in-flight.
  - `_time.py` (§12) — CAL-629 (PR #78), in-flight.
  - `state/schema.py:1` (§6), `:20` (§7), `:39` (§12); `state/store.py:37` (§12); `events/emitter.py:8` (§12); `cli/query_*` (§12) — deliberately deferred under CAL-633's grep-guard insight. Not re-filed. CODE-2 is a *separate* class (wrong **current** §, not a retired §), which the CAL-633 retired-cite guard would not catch.
  - `events/schema.py:35` (§4.4 for `decision_violation`) — left to CAL-633's §12/retired judgement call; it cross-references a retired event type, so it belongs to that cluster's deferral rather than CODE-2.
- **Banner-superseded specs** (`specs/cli.md`, engine-era SPEC §3/§5–10/§12–14, `hermes-orchestration.md`, `engine-*.md`): out of scope by design; `cancel.py:25` (§5) and the §11/§12 query-command cites resolve into this superseded range and are not flagged.
- **Size/structure:** Largest module is `launcher.py` (446 lines); `cli/close.py` 414, `worktree.py` 410, `cli/start.py` 398, `cli/review.py` 393. All single-concern, none mixing unrelated concerns. No size-limit violation worth flagging.
- **Dead code:** No `TODO`/`FIXME`/`XXX` in `harness/`. No obviously-orphaned exports spotted; `EVENT_TYPES`/`EventType` derive-pair is intentionally coupled.
- **Open-run resolution de-dup (review + close):** CAL-631 (PR #79), in-flight — not re-reported.
- **Dependencies:** `pydantic>=2.5`, `typer>=0.9`, `aiosqlite>=0.19`, `ulid-py>=1.1`; dev pins healthy. Nothing stale or risky.
- **As-built §4 verb prose vs code:** §4.1 command inventory (status/logs/events/runs/worktrees/cancel/doctor/serve/version + start/review/close) matches `cli/__init__.py` registrations exactly. §4.2–4.4 rollback/gate/dirty-tree prose matches the cited tests. No new divergence.

---

## Systemic insights

**CODE-INSIGHT-1 (decision-flagged).** CAL-633 proposes a grep-guard for **retired-§** docstring cites. CODE-2 shows the adjacent failure mode — a docstring citing the *wrong current* section (§4.9 vs §4.7) — which a retired-§ allowlist will not catch. If/when CAL-633's guard is authored, consider broadening its contract from "no cite to a retired §" to "each module's docstring §-cite resolves to the section whose header names that module," which would catch both classes in one structural check. Evidence: CODE-2. Flagged as a decision, not actioned (it changes CAL-633's scope, which is a judgement call already parked).

No other insights this cycle.
