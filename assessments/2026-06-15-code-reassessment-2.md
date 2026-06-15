# Code assessment (reassessment 2) — 2026-06-15

**Steward:** code (scope) · **Base:** `origin/dev` @ `8297a33` (assessed tree) · **Gate:** PASS (927 passed, `scripts/verify.sh` clean) · **Result: ZERO findings**

## Context

Triggered by the scheduled `harness-work-pull` run. The **Harness v3 Todo queue is empty** — all 90 project issues are `Done` (queried live; no `backlog`/`unstarted`/`started` issues remain). The run therefore fell through to a fresh `/assess code`.

This is the **second** code reassessment today. The earlier `2026-06-15-code.md` and `2026-06-15-code-reassessment.md` passes examined all eight `code` dimensions; the latter's one Low finding (CODE-1 — stale `harness 0.1.0` version examples in onboarding docs) was actioned and shipped as the current `dev` HEAD `8297a33`, along with its guard `tests/unit/test_doc_version_examples.py`. The only change to the tree since the prior report is that fix landing.

An independent sweep across all eight dimensions this run surfaced **no new findings**. No findings filed; no insights to record. This report is recorded as evidence the assessment ran.

## Gate result

`bash scripts/verify.sh` → **PASS** (run fresh this session). ruff clean, `mypy harness` clean, **927 passed in ~23s**, CLI smoke (`harness 0.2.1`) ok.

## Findings

**None.** A high-bar sweep found nothing specific, real, and ticket-worthy beyond what the two prior passes already closed.

## Dimensions examined (clean)

- **Size/structure drift:** `launcher.py` (529) carries its `# size:` justification; the three write-verb modules (`review.py` 479, `start.py` 399, `close.py` 382) sit under the 500 hard limit and stay cohesive around a single verb. No unjustified hard-limit crossing. `test_source_file_size_justification.py` holds.
- **Cross-file duplication:** run resolution centralized in `cli/_runs.py`; db-path in `cli/_query_common.py` + `cli/_repo.py`. The `_seed_open_run` test helper varies intentionally per test file (distinct defaults) — not load-bearing duplication.
- **Dead code:** every exported `harness/` symbol has a production caller or is documented public surface.
- **Stale TODOs:** zero `TODO`/`FIXME`/`HACK`/`XXX` in `harness/` or `tests/`.
- **Test health:** 927 passed; `assert ... is not None` precedes real consumption; verbs carry AC-mapping comments; unit tests use in-process SQLite/`tmp_path`; Docker tests marked `integration`; no skips/xfail without a removal condition.
- **Security:** no `shell=True`, no string-formatted SQL, no `eval`/`exec`/`pickle` in production; allowlist/workspace check runs once at the edge.
- **Architecture drift:** `specs/features/` (verb-model, cli-surface, run-ledger, worktree-lifecycle) all `status: implemented` and consistent with the code; architecture-principles D1–D7 hold.
- **Dependency health:** pydantic 2 / typer / aiosqlite / ulid-py / mypy / ruff — current, minimal, no risky pins.

## Guards confirmed holding

`test_source_file_size_justification.py`, `test_doc_version_examples.py`, `test_cli_surface_locked.py`, `test_retired_spec_cites.py`, `test_verb_contract_locked.py` — all present and green in the 927-test run. The structural guards from prior find→fix cycles are converting recurring manual checks into permanent gates as intended.

## Conclusion

The codebase is clean across all eight dimensions on `8297a33`. Prior findings shipped, guards hold, no new work surfaced. Per `/assess` discipline, no findings are filed and no work is invented. The yield from repeated same-day `/assess code` passes has thinned to zero — future scheduled runs hitting an empty queue can reasonably exit cleanly rather than re-running a full sweep on an unchanged tree.
