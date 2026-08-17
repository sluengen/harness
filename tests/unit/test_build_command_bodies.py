"""Guards for the harness-owned ``/build`` command body (CAL-659, CAL-703, CAL-715).

The harness is the SOURCE of the universal ``/build`` command (its canonical body was
housed here by CAL-657, imported byte-identical from the retiring ``agents`` source). A
Codex review of the imported bodies surfaced four latent defects — all pre-existing in the
source, none introduced by the import. They must be fixed before the source distributes
the command. These tests pin the fixes so a regression (or a re-import from the stale
source) is caught by the verify gate.

CAL-703 collapsed the former ``build.md`` + ``build-codex.md`` split into one
engine-arg ``build.md`` (``/build <TICKET> [--engine codex]``); the Codex-engine
assertions below now bind to that single file. The dedicated consolidation guards live in
``test_build_command_consolidated.py``.

The command body is Markdown, not code, so it is parsed as text and asserted at the
substring level — strong enough to catch the specific defect, loose enough to survive
incidental prose edits.

The four CAL-659 defects (the first three still guarded here):

* **[P1] Empty review diff.** The body captured the review diff with
  ``git diff "$base_branch"...HEAD``, but the implement sub-agent is told NOT to commit
  → ``HEAD == base`` → the diff is empty → the review runs against nothing. The capture
  must read the working-tree/index instead.
* **[P1] Unsandboxed Codex reviewer.** The Codex review step launched Codex with
  ``--dangerously-bypass-approvals-and-sandbox``; the diff and Linear description are
  untrusted prompt content, so prompt-injection could run arbitrary host commands. Codex
  must run read-only.
* **[P2] Codex runs from the wrong cwd.** The Codex invocation inherited the orchestrator
  cwd, not ``worktree_path``, so it read the base checkout, not the implementation under
  review. It must ``cd`` into the worktree first.
* **[P2] Broken jq GraphQL mutation — eliminated at the root by CAL-715.** The DEFER
  (``issueCreate``) and abandoned-run (``commentCreate``) payloads once embedded raw
  Linear GraphQL inline; CAL-715 thinned ``/build`` to a delegating driver that
  references the ``linear`` skill instead of embedding any ``api.linear.app`` call, so the
  whole class is gone — there is no embedded mutation left to mis-parameterize. The two
  guards that pinned the *parameterized embed* are therefore retired; the stronger
  invariant (``build.md`` embeds **no** Linear GraphQL at all) is owned by
  ``test_linear_skill.py`` (``test_no_command_embeds_linear_graphql``, whose
  allowlist is now empty, so the sweep is absolute).

*Source:* CAL-659, CAL-703, CAL-715.
"""

from __future__ import annotations

from pathlib import Path

from tests.unit._prose import REPO_ROOT

BUILD = REPO_ROOT / "commands" / "build.md"

#: The single command body carries the review-diff capture and the jq mutations.
BOTH = (BUILD,)


def _read(path: Path) -> str:
    return path.read_text()


# --- [P1] Empty review diff -------------------------------------------------


def test_review_diff_does_not_use_empty_head_range() -> None:
    """The review diff must not be captured as ``base...HEAD`` (always empty, no commit)."""
    for path in BOTH:
        text = _read(path)
        assert '"$base_branch"...HEAD' not in text, (
            f"{path.name}: review diff still uses 'git diff \"$base_branch\"...HEAD' — "
            "the implement agent never commits, so HEAD==base and the diff is empty; "
            "capture the working-tree/index diff instead"
        )
        assert "...HEAD" not in text, (
            f"{path.name}: a base...HEAD range diff is empty without a commit"
        )


def test_review_diff_captures_the_working_tree() -> None:
    """The review must diff the staged working tree against the worktree's own HEAD.

    The capture diffs against ``HEAD`` — the immutable commit the worktree was created
    from — not the moving ``$base_branch`` ref. If the integration branch advances mid-run,
    diffing against the branch tip would fold unrelated upstream changes (and apparent
    deletions) into the review; the implement agent never commits, so ``HEAD`` stays at the
    creation point and isolates exactly the patch under review.
    """
    for path in BOTH:
        text = _read(path)
        assert "git add -A && git diff --cached HEAD" in text, (
            f"{path.name}: review diff must stage the working tree ('git add -A', so new "
            "untracked files are included) then diff the index against the worktree's "
            "immutable HEAD ('git diff --cached HEAD'), not the moving $base_branch ref"
        )
        assert 'git diff --cached "$base_branch"' not in text, (
            f"{path.name}: do not diff the index against the moving $base_branch ref — if "
            "the integration branch advances mid-run the review folds in unrelated upstream "
            "changes; diff against the worktree's HEAD instead"
        )


# --- [P1] Unsandboxed Codex reviewer ----------------------------------------


def test_codex_reviewer_is_not_unsandboxed() -> None:
    """Codex must never review untrusted diff content with sandbox + approvals disabled."""
    text = _read(BUILD)
    assert "--dangerously-bypass-approvals-and-sandbox" not in text, (
        "build.md launches Codex with --dangerously-bypass-approvals-and-sandbox; "
        "the diff and Linear description are untrusted prompt content → prompt-injection "
        "could run arbitrary host commands. Run Codex read-only."
    )


def test_codex_reviewer_runs_read_only() -> None:
    """The Codex reviewer must be constrained to a read-only sandbox."""
    text = _read(BUILD)
    assert "--sandbox read-only" in text, (
        "build.md must run the Codex reviewer with '--sandbox read-only' so untrusted "
        "review content cannot mutate the host"
    )


# --- [P2] Codex runs from the worktree --------------------------------------


def test_codex_reviewer_runs_from_the_worktree() -> None:
    """Codex must read the implementation under review, not the orchestrator's checkout."""
    text = _read(BUILD)
    codex_lines = [ln for ln in text.splitlines() if "codex exec" in ln]
    assert codex_lines, "build.md must invoke 'codex exec'"
    for ln in codex_lines:
        assert 'cd "$worktree_path" &&' in ln, (
            "the 'codex exec' invocation must 'cd \"$worktree_path\"' first so Codex reads "
            f"the implementation under review, not the base checkout — got: {ln!r}"
        )


# --- [P2] Broken jq GraphQL mutation — eliminated at the root by CAL-715 ------
#
# The two guards that lived here (``test_no_jq_args_embedded_in_graphql_string_literals``
# and ``test_graphql_mutations_declare_and_pass_variables``) pinned the *correct
# parameterization* of the Linear GraphQL embedded in ``build.md``. CAL-715 removed the
# embed entirely — ``/build`` now references the ``linear`` skill rather than carrying any
# ``api.linear.app`` call — so there is no embedded mutation left to parameterize. The
# stronger successor invariant (no embedded Linear GraphQL at all) is owned by
# ``tests/unit/test_linear_skill.py``; retaining the old presence-guards here would assert
# content the same ticket deliberately deleted.
