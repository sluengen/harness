# Code reassessment — 2026-06-13 (run d)

**Steward:** code-steward · **Branch:** `assess/code-2026-06-13d` (off `origin/dev`) · **Gate:** green (`scripts/verify.sh` → ruff clean, mypy clean on 32 source files, 578 pytest passed, CLI smoke ok).

**Summary:** Codebase is healthy — no size-limit breaches, no dead code, no stale TODOs, no duplication or security-gap clusters. Two contained as-built SPEC-cite divergences in live docstrings, both mechanically fixable with an unambiguous correct target and both distinct from the already-tracked CAL-633/CAL-636 cluster.

---

## Findings

### CODE-1 — `harness/__init__.py` describes the package as the *retired* workflow engine (Medium)

- **What.** The package's top-line docstring is `"""Harness — deterministic workflow execution engine. See SPEC.md."""`. The "deterministic workflow execution engine" is the model retired in CAL-574; the harness is now "a set of deterministic, audited verbs an agent calls — not a pipeline that drives agents" (SPEC guiding principle, §1–2). This is the package's own self-description — the first thing a reader of `harness/` sees — and it asserts the superseded identity as current. The two *other* live files that mention the engine frame it correctly as retired (`harness/worktree.py:5` "there is no longer a workflow engine routing", `harness/state/schema.py:4` "CAL-574 retired the workflow engine"); only `__init__.py` still presents it as the package's present identity.
- **Where.** `harness/__init__.py:1`.
- **Why.** As-built SPEC divergence: live prose contradicts the current SPEC §1–2 verb model and its guiding principle. CONTEXT.md "Spec before code … update the spec/docs when what ships diverges". Not the CAL-633 class (that is retired-*§-number* cites in schema/store/events/query docstrings; this is a prose model-name divergence with no §-cite at all).
- **How.** Rewrite the docstring to the verb model, e.g. `"""Harness — deterministic, audited verbs an agent calls to drive a ticket. See SPEC.md."""`. One-line, no §-cite judgement, no behaviour change.

### CODE-2 — `harness/cli/cancel.py` cites retired SPEC §5 for "the public verb contract" (Low)

- **What.** Line 25: `This keeps the public verb contract (SPEC §5) and the launcher ``cancel`` op honest`. SPEC §5 is "YAML Workflow Schema" — retired/superseded engine content (banner: §3, §5–10, §12–14 retired), about workflow YAML keys, not the verb contract. The verb-surface-is-a-public-contract claim lives in SPEC §1 core principle 5 (titled exactly "The verb surface is a public contract", and it names `cancel` among the verbs). The same file already cites §11 correctly for exit codes (line 29), and `harness/cli/__init__.py:3` makes the identical "public contract" claim with no competing §-cite — so the correct target is unambiguous.
- **Where.** `harness/cli/cancel.py:25`.
- **Why.** A cross-reference that resolves to a retired section misleads the reader (the CAL-635 rationale: "a cross-reference that resolves to the wrong section is worse than none"). Distinct from CAL-633: `cancel.py` is not in CAL-633's enumerated set (`state/schema.py`, `store.py`, `events/emitter.py`, `cli/query*.py`), and unlike that cluster the correct §-home here is settled (§1), not an open judgement call. Distinct from the CAL-635 guard, which is scoped to the §4.9-vs-§4.7 events confusion only.
- **How.** Change `(SPEC §5)` to `(SPEC §1)`. Single-token edit, no behaviour change.

### Evidence appended to CAL-633 (already-tracked — not re-filed)

Additional instances of the CAL-633 retired-§ docstring-cite class found this pass (§6/§7/§12 schema/row-shape cites — the unresolved §-home judgement call):
- `harness/cli/query.py:14` — "SPEC §12 documents the row shapes".
- `harness/cli/query_status.py:3`, `query_runs.py:3`, `_query_common.py:10`, `query_events.py:6,31` — "SPEC §12 documents the row shape(s)".
- `harness/state/store.py:37`, `harness/events/emitter.py:8` — "Schema (SPEC §12)".
- `harness/state/schema.py:1,20,76` (§6, §7, §6), `:39` (§12).
- `harness/events/schema.py:35` — §4.4 for retired `decision_violation` (explicitly noted out-of-scope by the CAL-635 guard; CAL-633's judgement call).

These belong to the CAL-633/CAL-636 decision-parked cluster (the §-home for the retained SQLite schema and base-state is genuinely unsettled — §12/§6/§7 are the schema's only home but are flagged retired). Listed here as evidence; no new finding opened.

---

## Systemic insights

No insights this cycle. The recurring class (docstring cites resolving to a retired or wrong SPEC section) is already owned by CAL-633 (structural grep-guard for retired-§ cites) and CAL-636 (broaden it to wrong-current-§ cites). CODE-1 and CODE-2 are within the *type* CAL-636 anticipates; the proposed guard there would prevent their recurrence, so a new insight would duplicate it.

---

## Filing & action (run d)

- **CODE-1 → [CAL-637](https://linear.app/calibrate-coffee/issue/CAL-637) — ACTIONED this run.** `harness/__init__.py:1` rewritten to the verb-model description; guarded by `tests/unit/test_engine_retired.py::test_package_docstring_describes_verb_model_not_engine` (the package docstring must carry no "execution engine" identity claim and must name the verb model). Test-first: guard written red, docstring fixed green. Gate re-run green — **579** pytest passed (578 → +1 guard), ruff/mypy clean, CLI smoke ok.
- **CODE-2 → [CAL-638](https://linear.app/calibrate-coffee/issue/CAL-638) — filed (Low), deferred.** Split out to keep CODE-1's change atomic; clean mechanical `§5→§1` fix for a future run, not part of the parked CAL-633 contested-§-home class.
- **CAL-633 — evidence comment added** (the §6/§7/§12 cluster instances above); not re-filed.
