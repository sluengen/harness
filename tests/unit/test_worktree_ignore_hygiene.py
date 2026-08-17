"""Worktree ignore hygiene — what a run leaves in a worktree stays out of the index.

The repo is public (2026-07-06 open-sourcing decision, `test_secret_hygiene.py`).
`.gitignore` already ignores `.worktrees/` — the harness's own verb-created
worktree root (`harness/identity.py`'s ``WORKTREES_SUBDIR``) — but had no entry
for `.claude/worktrees/`, the *different* root the Claude Code CLI's own
agent-dispatch worktree-isolation uses. Each such worktree is a full checkout
carrying its own `.git`, so staging one with `git add -A` risks a `160000`
gitlink entry that publishes an operator's host path and unrelated branch/SHA
history (#250).

The same rule protects the **run artifacts** a verb loop writes *into* a run
worktree. `/harness routine build` captures the verify gate to `gate.log` for
`harness review --gate-log`, and stages Step 1.5's design to `design.md` for
`--design-file` — both at the worktree root, because the `~/bin/harness` wrapper
mounts only the invoking CWD into each verb's container, so a host-only path like
`/tmp` never resolves there (`commands/harness.md` Step 1.5 / Step 3). Neither is
covered by the already-ignored `.harness/`. Left untracked each reads as a dirty
worktree to the `close` gate, which refuses after a pass; swept up by `git add -A`
each lands in the published history instead. Ignoring them is the fix in both
directions.

Any assertion evaluated directly against *this* checkout would pass today
regardless of the fix, because `.git/info/exclude` already carries local,
uncommitted rules for the same paths — those rules protect only this machine, not
a fresh clone or a CI runner. That is exactly why this class of gap stays
invisible for so long locally. The behavioural guards below therefore run in a
hermetic temp repo whose `.gitignore` is copied from the real one, so it is the
committed rule under test, not the local exclude.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from tests._gitutil import git, init_hermetic_repo, tracked_files_under
from tests.unit._prose import REPO_ROOT


def test_agent_worktree_is_ignored_by_the_committed_gitignore(tmp_path: Path) -> None:
    """A `.claude/worktrees/<name>/` directory is invisible to `git status`.

    `.claude/` already carries a tracked file (see `init_hermetic_repo`), so
    git descends into it instead of collapsing the untracked subtree into a
    single `?? .claude/` line — without that, this assertion would pass
    whether or not the new directory is actually ignored.
    """
    repo = init_hermetic_repo(tmp_path / "clone")
    stale = repo / ".claude" / "worktrees" / "zen-driscoll-4c2cf9"
    stale.mkdir(parents=True)
    (stale / "README.md").write_text("x")

    porcelain = git(repo, "status", "--porcelain").stdout
    assert ".claude/worktrees" not in porcelain


def test_gitignore_does_not_blanket_ignore_dot_claude(tmp_path: Path) -> None:
    """Only the ``worktrees/`` subpath is ignored — `.claude/` itself is tracked.

    Guards against the tempting-but-wrong "blanket ``.claude/``" alternative:
    editing the already-tracked `.claude/settings.json` must keep showing up
    in `git status` so a real settings change is never silently dropped from
    review.
    """
    repo = init_hermetic_repo(tmp_path / "clone")
    (repo / ".claude" / "settings.json").write_text('{"changed": true}\n')

    porcelain = git(repo, "status", "--porcelain").stdout
    assert ".claude/settings.json" in porcelain


def test_nested_worktree_is_not_staged_as_a_gitlink(tmp_path: Path) -> None:
    """`git add -A` never adds an agent worktree as a `160000` gitlink entry.

    A worktree with its own commit is the case that actually matters: an
    ignore rule stops `git add -A` from picking it up at all, so the index
    never gains a gitlink pointing at unrelated branch/SHA history.
    """
    repo = init_hermetic_repo(tmp_path / "clone")
    (repo / "README.md").write_text("root\n")
    git(repo, "add", "README.md")
    git(repo, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-m", "root")

    nested = repo / ".claude" / "worktrees" / "some-agent-run"
    nested.mkdir(parents=True)
    # Branch stated, not inherited from the host's `init.defaultBranch` (#369).
    git(nested, "init", "-q", "-b", "dev")
    (nested / "file.txt").write_text("x")
    git(nested, "add", "file.txt")
    git(
        nested,
        "-c",
        "user.email=t@t",
        "-c",
        "user.name=t",
        "commit",
        "-m",
        "nested",
    )

    git(repo, "add", "-A")
    listing = git(repo, "ls-files", "-s").stdout
    assert "160000" not in listing


def test_no_agent_worktree_is_tracked_in_the_live_repo() -> None:
    """The live repo's index carries nothing under `.claude/worktrees/`.

    Catches a deliberate `git add -f` that the ignore rule, by design, does
    not stop — an ignore rule only ever keeps a path from being staged by
    accident.
    """
    assert not tracked_files_under(".claude/worktrees")


def test_run_artifacts_do_not_read_as_a_dirty_worktree(tmp_path: Path) -> None:
    """`gate.log` and `design.md` at the worktree root are invisible to `git status`.

    This is the failure mode that actually bites: the `close` gate counts
    untracked files, so a run that captured its gate output — or staged its
    design for `--design-file` — would be refused with `dirty_worktree` *after*
    a passing review. `git status --porcelain` is the same view that gate takes.
    """
    repo = init_hermetic_repo(tmp_path / "clone")
    (repo / "gate.log").write_text("=== ruff ===\nAll checks passed!\n")
    (repo / "design.md").write_text("# Design\n")

    porcelain = git(repo, "status", "--porcelain").stdout
    assert "gate.log" not in porcelain
    assert "design.md" not in porcelain


def test_run_artifacts_are_not_swept_into_the_index_by_add_all(tmp_path: Path) -> None:
    """`git add -A` never stages a run artifact.

    The other direction of the same gap: the routine commits with `git add -A`,
    so an unignored `gate.log` is published into permanent history — as one
    already was, in the commit `41d7fb6` had to revert.
    """
    repo = init_hermetic_repo(tmp_path / "clone")
    (repo / "gate.log").write_text("=== ruff ===\n")
    (repo / "design.md").write_text("# Design\n")

    git(repo, "add", "-A")
    listing = git(repo, "ls-files").stdout.splitlines()
    assert "gate.log" not in listing
    assert "design.md" not in listing


def test_design_ignore_is_anchored_to_the_root_only(tmp_path: Path) -> None:
    """A `design.md` *nested* anywhere else stays visible to git.

    `design.md` is a name this repo plausibly wants to track under `docs/` or
    `specs/` — unlike `gate.log`, which is distinctive enough to leave
    unanchored. The rule is therefore written `/design.md`, and this asserts the
    anchor actually holds: silently ignoring a hand-written design doc would be
    a worse bug than the one being fixed.
    """
    repo = init_hermetic_repo(tmp_path / "clone")
    nested = repo / "docs" / "design.md"
    nested.mkdir(parents=True, exist_ok=True)
    nested.rmdir()
    nested.write_text("# A real, tracked design doc\n")

    ignored = subprocess.run(
        ["git", "check-ignore", "-q", "docs/design.md"],
        cwd=repo,
        check=False,
        capture_output=True,
        text=True,
    )
    assert ignored.returncode == 1, (
        "/design.md must anchor to the repo root — a nested docs/design.md is a "
        "document to track, not a run artifact to ignore"
    )


def test_gitignore_ignores_run_artifacts_as_whole_lines() -> None:
    """Both run-artifact rules are their own pattern lines, not trailing comments.

    Same hazard as the worktree rule below: git does not treat a trailing ``#``
    on a pattern line as a comment, so ``gate.log   # run artifact`` would
    silently match nothing.
    """
    patterns = {
        line.strip()
        for line in (REPO_ROOT / ".gitignore").read_text().splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }
    assert "gate.log" in patterns, (
        ".gitignore must ignore gate.log as a whole pattern line"
    )
    assert "/design.md" in patterns, (
        ".gitignore must ignore /design.md as a whole pattern line"
    )


def test_gitignore_ignores_agent_worktrees_as_a_whole_line() -> None:
    """The rule is its own pattern line, not a trailing comment on one.

    Git does not treat a trailing ``#`` on a pattern line as a comment, so
    ``.claude/worktrees/   # Claude Code`` would silently match nothing. This
    mirrors `test_secret_hygiene.py`'s `test_gitignore_ignores_env_files`.
    """
    patterns = {
        line.strip()
        for line in (REPO_ROOT / ".gitignore").read_text().splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }
    assert ".claude/worktrees/" in patterns, (
        ".gitignore must ignore .claude/worktrees/ as a whole pattern line"
    )
