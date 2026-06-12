# Code Steward assessment — harness — 2026-06-12 (reassessment 4)

**Filed:** CAL-625 (CODE-1, reopened — see below) — actioned in this same change. Labelled `review-finding` / `source:review-finding`, priority Medium.

**Summary:** No `Todo` issues in Harness v3 (the launcher/as-built cluster is fully shipped; the 5 open items CAL-620–624 are deliberately parked in `Backlog`). Assessment fallback found one concrete, wholly-contained defect: **CAL-625 was marked Done but its fix never landed on `dev`.** The codebase is otherwise healthy — ruff clean, mypy clean, full fast suite green (527 passed). This run completes the unfinished fix and reopens the ticket to reflect reality.

---

## Findings

### CODE-1 (reopened) — CAL-625 closed Done, but `worktrees cleanup --merged` docs still say "main" — Medium

- **What:** CAL-625 / CODE-1 (filed in reassessment-3) was marked **Done**, but the two user-facing surfaces it named were never changed on `dev`. `harness/cli/worktrees.py:13` (module docstring) and `:199` (Typer `--help`) still claimed the `--merged` filter checks `main`, while the implementation (`_branch_merged_into_*`, line 171) tests `dev`, `main`, **and** `master`. The only edit in the area was the internal function docstring (line 166), changed incidentally by `c79c006` ("default base branch from main to dev") — not by any CAL-625 commit.
- **Where:**
  - `harness/cli/worktrees.py:13` — module docstring (stale "merged into `main`").
  - `harness/cli/worktrees.py:199` — Typer `--help` (stale "merged into main.").
  - `harness/cli/worktrees.py:165` — `_branch_merged_into_main` name vs. its `("dev", "main", "master")` body (the name-vs-body divergence the original finding also noted).
- **Why:** As-built divergence (area 9). A user reading `--help` believes a branch merged only into `dev` (the common case here — `dev` is the integration branch) is **not** a cleanup candidate, when in fact it is. The premature close also masked the gap: the ticket said "fixed" while `dev` still shipped the stale docs.
- **How (actioned, branch `assess/code-2026-06-12c`):**
  - `worktrees.py:13` → "fully merged into `dev`, `main`, or `master` (the integration/release bases)".
  - `worktrees.py:199` → "Remove worktrees whose branch is merged into dev, main, or master."
  - Renamed `_branch_merged_into_main` → `_branch_merged_into_base`; single internal caller (line 224) updated.
  - Tests (test-first) added to `tests/unit/test_cli_query.py`: `test_worktrees_cleanup_help_lists_all_merge_bases` (help-text guard — red on stale "main"-only help, green after); `test_worktrees_cleanup_merged_removes_branch_merged_into_dev` (behavioural lock — `--merged` removes a branch merged into `dev`; `--merged` previously had zero coverage).
  - CAL-625 reopened to In Progress with a comment recording the premature close.

---

## Not flagged (checked, deliberately excluded)

- **`specs/cli.md:260`** — same stale "merged into `main` or `master`" wording, but the file is **banner-superseded** (engine-era CLI, kept for historical reference). Out of scope for as-built cross-check, consistent with reassessment-3's treatment.
- **`SPEC.md`** — shows only the `cleanup [--age <duration>] [--merged]` signature, no merge-base wording; no edit needed.
- **Backlog items CAL-620–624** — real future work (agents-repo delivery, GHCR publish, tokenized-https push, per-repo config, BOOTSTRAP packaging), deliberately parked in `Backlog`, not `Todo`. Not pulled.

---

## Systemic insights

**Insight — a `review-finding` ticket can be closed Done without its fix landing.** CAL-625 went to Done while `dev` still shipped the exact stale strings the finding named; nothing in the loop verified the fix was present at close time. The closing actor likely conflated "CODE-2 (CAL-626) shipped in this change" with "CODE-1 also done" because they were filed together. This is the second-order risk of compressing find→file→action into one run: the *close* is not gated on fresh evidence the way the universal flow requires ("No completion claim without fresh evidence", CLAUDE.md). Worth a small guard — when closing a `review-finding`, grep for the named stale strings/locations and confirm they're gone before transitioning to Done. One finding, not yet a recurring pattern, but a clear failure mode of the assess→action shortcut.
