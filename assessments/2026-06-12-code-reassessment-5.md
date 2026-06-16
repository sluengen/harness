# Code Steward assessment — harness — 2026-06-12 (reassessment 5)

**Filed:** CODE-501 (Low) — found *and actioned in this same change* (branch `assess/code-2026-06-12d`). The steward's original §-target was wrong; the finding below is the **verified, corrected** version.

**Summary:** No `Todo` issues in Harness v3 (launcher/as-built cluster fully shipped; the 5 open items CAL-620–624 are deliberately parked in `Backlog`). The codebase is healthy — `ruff` clean, `mypy` clean (32 source files, 0 errors), full gate green (**575 passed** incl. integration/docker), no TODO/FIXME in `harness/`, no untracked dead code, files within size limits. The assess→action fallback surfaced one small as-built-doc divergence: a single module docstring (and its mirror test comment) cite the **retired** SPEC §12 for the timestamp *format*, which §12 does not document. Fixed test-first.

---

## Findings

### CODE-501 — `_time.py` cites the retired SPEC §12 for the timestamp *format* (§12 documents the schema, not the format) — Low

- **What:** `harness/_time.py` is the sole home of the ledger's trailing-`Z` UTC timestamp **format**. Its module docstring anchored that format to `(SPEC §12; see harness.events.emitter)`. But SPEC §12 (*SQLite Schema*) is in the **retired** block (banner: `SPEC.md:4`, `SPEC.md:102` — §12–§14 superseded; "the current schema reference is `specs/state-store.md`") and documents the events/runs **table schema**, containing *no* text about the trailing-`Z` format or its `+00:00`↔`Z` round-trip. The format prose lives in `harness/events/emitter.py:20-22` and in `_time.py` itself — and `emitter.py` correctly carries **no** §-cite on its format prose.
- **Where:**
  - `harness/_time.py:5` — module docstring: `... swapped for +00:00 (SPEC §12; see harness.events.emitter).`
  - `tests/unit/test_time.py:23` — mirror comment on the `_ISO_Z` regex: `the form documented in harness/events/emitter.py (SPEC §12).`
- **Why:** As-built divergence (area 9). A reader following `§12` from `_time.py` lands in a section the SPEC's own banner marks retired, looking for a format definition that isn't there. The distinction is precise and verifiable: every *other* `§12` cite in the package (`store.py:37`, `state/schema.py:39`, the `cli/query*` modules, `emitter.py:8` "Schema (SPEC §12)") points at the **schema**, which §12 *does* contain — those are correct. `_time.py` was the lone module attaching §12 to the **format**, which §12 does not cover. Low severity: a stale internal cross-reference, no behavioural or user-facing surface.
- **How (actioned):**
  - Test-first: added `tests/unit/test_time.py::test_time_module_does_not_cite_the_retired_schema_section` — a source-grep lock (idiomatic to this file; mirrors `test_z_substitution_lives_only_in_the_time_helper` and `test_cli_surface_locked.py`) asserting `§12` is absent from `harness/_time.py`. Red on the stale cite, green after the fix.
  - `_time.py:5` → `(the format is co-documented in ``harness.events.emitter``)` — drops the retired/inaccurate §-cite, keeps the accurate module cross-reference, matching `emitter.py`'s no-§-cite-on-format-prose pattern. Docstring reflowed to stay within line length.
  - `test_time.py:23` → `the form co-documented in ``harness/events/emitter.py`` and ``harness/_time.py``.` — same mis-attribution removed.

**Correction to the original steward pass:** the first sweep proposed retargeting `§12` → `§4.7`. Independent verification rejected that: §4.7 (`harness.events.emitter`) documents the emitter's *responsibilities*, not the timestamp format or the timestamp column, so it is a *worse* pointer than §12 and would have diverged from the repo-wide §12-as-schema convention. The correct fix is to drop the retired-§ cite from the *format* sentence entirely (the format has no SPEC-section home; its prose home is the emitter/`_time.py`), which is what shipped.

---

## Not flagged (checked, deliberately excluded)

- **Repo-wide `SPEC §12` schema citations** (`store.py:37`, `state/schema.py:39`, `cli/query*.py`, `emitter.py:8`, `tests/unit/test_state_store.py`, `tests/unit/test_event_emitter.py:3`) — these cite §12 for the **schema**, which §12 *correctly contains and still matches the code*. The SPEC banner prefers `specs/state-store.md` as "the current schema reference", so there is a latent coherence question (live code citing a retired-block section while a current reference exists). But it is **not** wholly-contained (8+ files), it is **not** clearly a defect (the §12 schema text is accurate and the banner keeps §12 expressly "for the mechanics that were re-homed"), and any sweep needs a deliberate decision on the canonical reference + a measurable lock — out of scope for a drive-by autonomous run. Noted here for a future steward, not filed as action.
- **`identity.artifacts_dir()` / `identity.log_path()`** — vestigial but tested public surface tied to SPEC §8 (`tests/unit/test_identity.py`); does not meet the dead-code bar (re-confirmed from reassessment-3).
- **Backlog items CAL-620–624** — real future work, deliberately parked in `Backlog`, not `Todo`. Not pulled.

---

## Systemic insights

None this cycle — CODE-501 is a one-off citation slip in a single module, not a recurring class. (The broader §12-vs-`state-store.md` reference-coherence question noted under "Not flagged" is a candidate for a future decision but does not rise to an insight: it is one section, with a partly-intentional rationale, and no guidance-file edit would have prevented it.)

---

## Verification (run this session)

- `uv run ruff check .` → All checks passed.
- `uv run mypy harness` → Success: no issues found in 32 source files.
- `bash scripts/verify.sh` (ruff → mypy → pytest → CLI smoke) → **575 passed**, gate green.
- New test red-then-green confirmed for `test_time_module_does_not_cite_the_retired_schema_section`.
