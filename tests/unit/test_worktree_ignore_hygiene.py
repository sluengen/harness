"""Worktree ignore hygiene — agent-dispatch worktrees stay out of the index.

The repo is public (2026-07-06 open-sourcing decision, `test_secret_hygiene.py`).
`.gitignore` already ignores `.worktrees/` — the harness's own verb-created
worktree root (`harness/identity.py`'s ``WORKTREES_SUBDIR``) — but had no entry
for `.claude/worktrees/`, the *different* root the Claude Code CLI's own
agent-dispatch worktree-isolation uses. Each such worktree is a full checkout
carrying its own `.git`, so staging one with `git add -A` risks a `160000`
gitlink entry that publishes an operator's host path and unrelated branch/SHA
history (#250).

Any assertion evaluated directly against *this* checkout would pass today
regardless of the fix, because `.git/info/exclude` already carries a local,
uncommitted rule for the same path — that rule protects only this machine, not
a fresh clone or a CI runner. The behavioural guard below therefore runs in a
hermetic temp repo whose `.gitignore` is copied from the real one, so it is the
committed rule under test, not the local exclude.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from tests._gitutil import tracked_files_under

_REPO_ROOT = Path(__file__).resolve().parents[2]


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    """Synchronous git invocation for test setup/assertions."""
    return subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )


def _init_hermetic_repo(path: Path) -> Path:
    """``git init`` a repo whose ``info/exclude`` is comments-only, with a
    tracked `.claude/settings.json` — the real repo's shape, where `.claude/`
    is itself a tracked directory (`test_agent_worktree_is_ignored_by_the_committed_gitignore`'s
    docstring explains why that tracked file has to exist *before* the
    untracked-worktree assertions: otherwise `git status --porcelain` collapses
    a wholly-untracked `.claude/` into a single `?? .claude/` line and every
    assertion about a path *under* it passes vacuously, ignored or not.

    A plain ``init_repo`` (``tests._gitutil``) still runs on *this* machine, so
    its default ``info/exclude`` is whatever the local git config templates in
    — never this repo's `.claude/worktrees/` line (that lives in *this* repo's
    own `.git/info/exclude`, not the git template), but hermetic on principle:
    the guard must derive its ignore behaviour from the copied `.gitignore`
    alone, not from any ambient exclude file.
    """
    path.mkdir(parents=True, exist_ok=True)
    _git(path, "init", "-q")
    (path / ".gitignore").write_text((_REPO_ROOT / ".gitignore").read_text())
    (path / ".claude").mkdir()
    (path / ".claude" / "settings.json").write_text("{}\n")
    _git(path, "add", ".gitignore", ".claude/settings.json")
    _git(path, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-m", "init")
    return path


def test_agent_worktree_is_ignored_by_the_committed_gitignore(tmp_path: Path) -> None:
    """A `.claude/worktrees/<name>/` directory is invisible to `git status`.

    `.claude/` already carries a tracked file (see `_init_hermetic_repo`), so
    git descends into it instead of collapsing the untracked subtree into a
    single `?? .claude/` line — without that, this assertion would pass
    whether or not the new directory is actually ignored.
    """
    repo = _init_hermetic_repo(tmp_path / "clone")
    stale = repo / ".claude" / "worktrees" / "zen-driscoll-4c2cf9"
    stale.mkdir(parents=True)
    (stale / "README.md").write_text("x")

    porcelain = _git(repo, "status", "--porcelain").stdout
    assert ".claude/worktrees" not in porcelain


def test_gitignore_does_not_blanket_ignore_dot_claude(tmp_path: Path) -> None:
    """Only the ``worktrees/`` subpath is ignored — `.claude/` itself is tracked.

    Guards against the tempting-but-wrong "blanket ``.claude/``" alternative:
    editing the already-tracked `.claude/settings.json` must keep showing up
    in `git status` so a real settings change is never silently dropped from
    review.
    """
    repo = _init_hermetic_repo(tmp_path / "clone")
    (repo / ".claude" / "settings.json").write_text('{"changed": true}\n')

    porcelain = _git(repo, "status", "--porcelain").stdout
    assert ".claude/settings.json" in porcelain


def test_nested_worktree_is_not_staged_as_a_gitlink(tmp_path: Path) -> None:
    """`git add -A` never adds an agent worktree as a `160000` gitlink entry.

    A worktree with its own commit is the case that actually matters: an
    ignore rule stops `git add -A` from picking it up at all, so the index
    never gains a gitlink pointing at unrelated branch/SHA history.
    """
    repo = _init_hermetic_repo(tmp_path / "clone")
    (repo / "README.md").write_text("root\n")
    _git(repo, "add", "README.md")
    _git(repo, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-m", "root")

    nested = repo / ".claude" / "worktrees" / "some-agent-run"
    nested.mkdir(parents=True)
    _git(nested, "init", "-q")
    (nested / "file.txt").write_text("x")
    _git(nested, "add", "file.txt")
    _git(
        nested,
        "-c",
        "user.email=t@t",
        "-c",
        "user.name=t",
        "commit",
        "-m",
        "nested",
    )

    _git(repo, "add", "-A")
    listing = _git(repo, "ls-files", "-s").stdout
    assert "160000" not in listing


def test_no_agent_worktree_is_tracked_in_the_live_repo() -> None:
    """The live repo's index carries nothing under `.claude/worktrees/`.

    Catches a deliberate `git add -f` that the ignore rule, by design, does
    not stop — an ignore rule only ever keeps a path from being staged by
    accident.
    """
    assert not tracked_files_under(".claude/worktrees")


def test_gitignore_ignores_agent_worktrees_as_a_whole_line() -> None:
    """The rule is its own pattern line, not a trailing comment on one.

    Git does not treat a trailing ``#`` on a pattern line as a comment, so
    ``.claude/worktrees/   # Claude Code`` would silently match nothing. This
    mirrors `test_secret_hygiene.py`'s `test_gitignore_ignores_env_files`.
    """
    patterns = {
        line.strip()
        for line in (_REPO_ROOT / ".gitignore").read_text().splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }
    assert ".claude/worktrees/" in patterns, (
        ".gitignore must ignore .claude/worktrees/ as a whole pattern line"
    )
