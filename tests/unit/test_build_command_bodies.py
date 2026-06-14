"""Guards for the harness-owned ``/build`` + ``/build-codex`` command bodies (CAL-659).

The harness is the SOURCE of the universal ``/build`` and ``/build-codex`` commands
(their canonical bodies were housed here by CAL-657, imported byte-identical from the
retiring ``agents`` source). A Codex review of the imported bodies surfaced four latent
defects — all pre-existing in the source, none introduced by the import. They must be
fixed before the source distributes these commands. These tests pin the fixes so a
regression (or a re-import from the stale source) is caught by the verify gate.

The command bodies are Markdown, not code, so they are parsed as text and asserted at
the substring level — strong enough to catch the specific defect, loose enough to
survive incidental prose edits.

The four defects (see CAL-659):

* **[P1] Empty review diff.** Both bodies captured the review diff with
  ``git diff "$base_branch"...HEAD``, but the implement sub-agent is told NOT to commit
  → ``HEAD == base`` → the diff is empty → the review runs against nothing. The capture
  must read the working-tree/index instead.
* **[P1] Unsandboxed Codex reviewer.** ``build-codex.md`` launched Codex with
  ``--dangerously-bypass-approvals-and-sandbox``; the diff and Linear description are
  untrusted prompt content, so prompt-injection could run arbitrary host commands. Codex
  must run read-only.
* **[P2] Codex runs from the wrong cwd.** The Codex invocation inherited the orchestrator
  cwd, not ``worktree_path``, so it read the base checkout, not the implementation under
  review. It must ``cd`` into the worktree first.
* **[P2] Broken jq GraphQL mutation.** The DEFER (``issueCreate``) and abandoned-run
  (``commentCreate``) payloads embedded ``$t``/``$title``/``$p``/``$id``/``$body`` inside a
  plain JSON *string* literal where jq does not interpolate them, and declared no GraphQL
  variables → Linear received the literal text and silently rejected → the follow-up
  ticket / comment was never created. The mutations must declare GraphQL variables and
  pass a ``variables`` object.

*Source:* CAL-659.
"""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent.parent
BUILD = REPO_ROOT / "commands" / "build.md"
BUILD_CODEX = REPO_ROOT / "commands" / "build-codex.md"

#: Both bodies carry the same review-diff capture and the same jq mutations.
BOTH = (BUILD, BUILD_CODEX)


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
    text = _read(BUILD_CODEX)
    assert "--dangerously-bypass-approvals-and-sandbox" not in text, (
        "build-codex.md launches Codex with --dangerously-bypass-approvals-and-sandbox; "
        "the diff and Linear description are untrusted prompt content → prompt-injection "
        "could run arbitrary host commands. Run Codex read-only."
    )


def test_codex_reviewer_runs_read_only() -> None:
    """The Codex reviewer must be constrained to a read-only sandbox."""
    text = _read(BUILD_CODEX)
    assert "--sandbox read-only" in text, (
        "build-codex.md must run the Codex reviewer with '--sandbox read-only' so untrusted "
        "review content cannot mutate the host"
    )


# --- [P2] Codex runs from the worktree --------------------------------------


def test_codex_reviewer_runs_from_the_worktree() -> None:
    """Codex must read the implementation under review, not the orchestrator's checkout."""
    text = _read(BUILD_CODEX)
    codex_lines = [ln for ln in text.splitlines() if "codex exec" in ln]
    assert codex_lines, "build-codex.md must invoke 'codex exec'"
    for ln in codex_lines:
        assert 'cd "$worktree_path" &&' in ln, (
            "the 'codex exec' invocation must 'cd \"$worktree_path\"' first so Codex reads "
            f"the implementation under review, not the base checkout — got: {ln!r}"
        )


# --- [P2] GraphQL mutations use variables, not string-embedded jq args ------


def test_no_jq_args_embedded_in_graphql_string_literals() -> None:
    """The broken un-parameterized mutations (literal $t/$id in the query string) are gone."""
    for path in BOTH:
        text = _read(path)
        assert "mutation{issueCreate(input:{teamId:$t" not in text, (
            f"{path.name}: DEFER issueCreate embeds $t/$title/$p in a plain JSON string "
            "where jq does not interpolate them — declare GraphQL variables instead"
        )
        assert "mutation{commentCreate(input:{issueId:$id" not in text, (
            f"{path.name}: abandoned-run commentCreate embeds $id/$body in a plain JSON "
            "string where jq does not interpolate them — declare GraphQL variables instead"
        )


def test_graphql_mutations_declare_and_pass_variables() -> None:
    """Both mutations must declare typed GraphQL variables and pass a ``variables`` object."""
    for path in BOTH:
        text = _read(path)
        # issueCreate (DEFER path) — parameterized signature + variables payload.
        assert "mutation($t:String!,$title:String!,$p:String)" in text, (
            f"{path.name}: the DEFER issueCreate mutation must declare GraphQL variables "
            "(mutation($t:String!,$title:String!,$p:String){...})"
        )
        assert "variables:{t:$t,title:$title,p:$p}" in text, (
            f"{path.name}: the DEFER issueCreate call must pass a variables object so jq "
            "substitutes the team id / title / parent"
        )
        # commentCreate (abandoned-run path).
        assert "mutation($id:String!,$body:String!)" in text, (
            f"{path.name}: the abandoned-run commentCreate mutation must declare GraphQL "
            "variables (mutation($id:String!,$body:String!){...})"
        )
        assert "variables:{id:$id,body:$body}" in text, (
            f"{path.name}: the abandoned-run commentCreate call must pass a variables object "
            "so jq substitutes the issue id / body"
        )
