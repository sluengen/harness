# Code assessment (reassessment) — 2026-06-15

**Steward:** code (scope) · **Base:** `origin/dev` @ `8ca27fe` (assessed tree) · **Gate:** PASS (924 passed, `scripts/verify.sh` clean)

## Context

Triggered by the scheduled `harness-work-pull` run: the **Harness v3 Todo queue was empty** — all 90 project issues are `Done` (CAL-699, the prior run's last in-repo pick, merged to `dev` as `8ca27fe`; CAL-687 and CAL-675 are likewise Done). The earlier `2026-06-15-code.md` assessment's one open follow-up (CODE-2 / CODE-INSIGHT-2 — extend the retired-surface scan to `.py` docstrings) shipped as **CAL-699** and is now the current `dev` HEAD, so that report is fully closed out. The run therefore fell through to a fresh `/assess code`.

A full pass across all eight `code` dimensions surfaced **one Low-severity spec/doc-coherence finding** paired with one enabling systemic insight. No High/Critical findings; no dead code, stale TODOs, cross-file duplication, cross-cutting security gaps, architecture drift, or dependency problems.

The finding (**CODE-1 + CODE-INSIGHT-1**) was actioned this run.

## Gate result

`bash scripts/verify.sh` → **PASS**. ruff clean, `mypy harness` clean, **924 passed in ~22s**, CLI smoke (`harness 0.2.1`) ok. Output captured at `/tmp/steward-verify2.txt`.

## Findings

### CODE-1 — Onboarding/ops docs show stale `harness version` output (`harness 0.1.0`) — Low — **ACTIONED**

**What:** `harness version` prints `harness <__version__>` (`harness/cli/version.py`), which is `harness 0.2.1` on the current tree (`harness/__init__.py`, `pyproject.toml`). Two docs show that command's output as a sanity-check example but hardcode the old `harness 0.1.0` — a documented behaviour the code no longer has.

**Where:** `BOOTSTRAP.md:60` (`docker run --rm harness:dev version    # → harness 0.1.0`) and `docker/README.md:47` (`# → harness 0.1.0`).

**Why:** Nothing ties a documented version-output example to the real version, so each release silently drifts the examples. The version has bumped `0.1.0 → 0.2.1` since these examples were written and both went stale. A reader running the sanity check sees a mismatch against what onboarding promised.

**How (done):** Updated both examples to `harness 0.2.1`, and added the guard below so the class cannot recur silently.

## Systemic insights

### CODE-INSIGHT-1 — Pin documented version-output examples to `harness.__version__` with a suite gate — **ACTIONED**

The drift survived because the rule "doc examples of `harness version` match the real version" was enforced by human attention only. Shipped `tests/unit/test_doc_version_examples.py`: globs git-tracked `*.md` (excluding `CHANGELOG.md` and `assessments/`, which legitimately record *historical* versions) and fails for any `harness X.Y.Z` example that does not equal `harness.__version__`. This converts a recurring find→fix into a permanent gate — the same text-structural form as `test_retired_spec_cites` (CAL-633) and `test_source_file_size_justification` (CODE-1, `2026-06-15-code.md`): a manual drift check made a structural check. The next release that forgets to update the docs now fails the gate instead of shipping a stale example.

## Dimensions examined (clean)

- **Size/structure drift:** the three write-verb modules sit over the 300-line soft limit (`review.py` 479, `start.py` 399, `close.py` 382) but under the 500 hard limit; each is cohesive around its single verb, and `launcher.py` (529) carries its `# size:` justification. No unjustified hard-limit crossing — not flagged (premature to split a cohesive verb under the hard limit).
- **Cross-file duplication:** run resolution is centralized in `cli/_runs.py` (CAL-631); db-path resolution in `cli/_query_common.py` + `cli/_repo.py`. `cancel.py` resolves by a status *allowlist* (a distinct concern from the open-run resolver) and correctly does not reuse it. No duplicated load-bearing pattern.
- **Dead code:** none found by grep — every exported `harness/` symbol has a production caller or is documented public surface.
- **Stale TODOs:** zero `TODO`/`FIXME`/`HACK`/`XXX` in `harness/` or `tests/`.
- **Test health:** **924 passed**; `assert ... is not None` uses precede real consumption (not weak presence checks); verbs carry AC-mapping comments; unit tests use in-process SQLite/`tmp_path`, Docker tests marked `integration`.
- **Security:** no `shell=True`, no string-formatted SQL, no `eval`/`exec`/`pickle` in production; the allowlist/workspace check runs once at the edge.
- **Architecture drift:** `specs/features/` (verb-model, cli-surface, run-ledger, worktree-lifecycle) and architecture-principles D1–D7 still match the code.
- **Dependency health:** pydantic 2 / typer / aiosqlite / ulid-py / mypy — current, minimal.
