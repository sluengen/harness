"""The polluted-worktree measurement — #359.

``harness/cli/review_pollution.py`` answers one question before ``review``
spawns an engine: how far past its own git index has this run worktree drifted?

The measurement is the half that carries the *quantities*, so it is pinned here,
away from the CLI: the bound at its exact boundary, the scan cap that keeps the
guard from becoming its own version of the burn it prevents, and the fail-open
contract that makes every unanswerable case a *no opinion* rather than a
refusal. ``tests/unit/test_review_polluted_worktree.py`` drives the same rule
through the verb.

Why ``excess`` is ``scanned - tracked`` rather than the size of the set
difference: the counts are immune to a *path-spelling* mismatch between what
``git ls-files`` prints and what ``os.walk`` returns. macOS normalizes filenames
(NFD on disk against git's NFC), so a set-membership test misses on every
non-ASCII name and counts a tracked file as excess — a false refusal, the one
direction this guard must never fail in. Subtraction cannot make that mistake,
and it errs the safe way besides: a tracked file deleted in the working tree
lowers ``scanned`` without lowering ``tracked``, so the error runs toward *not*
refusing.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from harness import _git
from harness.cli.review_pollution import measure_worktree_pollution


def _git_cmd(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(repo), *args], check=True, capture_output=True, text=True
    )


@pytest.fixture
def worktree(tmp_path: Path) -> Path:
    """A git top-level with three tracked files."""
    root = tmp_path / "wt"
    root.mkdir()
    _git_cmd(root, "init", "-b", "dev")
    _git_cmd(root, "config", "user.email", "t@e.c")
    _git_cmd(root, "config", "user.name", "T")
    (root / "README.md").write_text("hi\n")
    (root / "pkg").mkdir()
    (root / "pkg" / "a.py").write_text("a = 1\n")
    (root / "pkg" / "b.py").write_text("b = 2\n")
    _git_cmd(root, "add", "-A")
    _git_cmd(root, "commit", "-m", "initial")
    return root


def _seed(root: Path, segment: str, count: int) -> None:
    """Write ``count`` untracked files under ``root/segment``."""
    directory = root / segment
    directory.mkdir(parents=True, exist_ok=True)
    for i in range(count):
        (directory / f"f{i}.bin").write_text("x")


# --- The bound, measured at its boundary (AC-3) --------------------------------


def test_excess_equal_to_the_limit_does_not_refuse(worktree: Path) -> None:
    """The bound refuses on *more than*, never on equal.

    Seeded from the limit under test rather than from a literal, so retuning the
    default cannot leave this asserting a boundary that no longer exists.
    """
    limit = 20
    tracked = 3
    # The tracked files are on disk too, so ``excess`` is exactly what is seeded.
    _seed(worktree, "junk", limit)

    measured = measure_worktree_pollution(worktree, limit=limit)

    assert measured is not None
    assert measured.tracked == tracked
    assert measured.scanned == tracked + limit
    assert measured.excess == limit
    assert measured.refuses is False


def test_one_file_past_the_limit_refuses(worktree: Path) -> None:
    """One file more than the boundary above flips the verdict, and nothing else."""
    limit = 20
    _seed(worktree, "junk", limit + 1)

    measured = measure_worktree_pollution(worktree, limit=limit)

    assert measured is not None
    assert measured.excess == limit + 1
    assert measured.refuses is True


def test_the_arithmetic_and_the_largest_segment(worktree: Path) -> None:
    """``tracked`` / ``scanned`` / ``excess`` reconcile, and the polluter is named."""
    _seed(worktree, ".venv", 40)
    _seed(worktree, "extra", 5)

    # A limit whose cap (tracked + 4 * limit) comfortably clears the tree, so
    # this case measures the arithmetic rather than the truncation.
    measured = measure_worktree_pollution(worktree, limit=100)

    assert measured is not None
    assert measured.tracked == 3
    assert measured.scanned == 3 + 40 + 5
    assert measured.excess == 45
    assert measured.largest[0].segment == ".venv"
    assert measured.largest[0].files == 40
    assert measured.truncated is False


def test_a_deleted_tracked_file_lowers_scanned_and_never_raises_excess(
    worktree: Path,
) -> None:
    """The subtraction errs toward *not* refusing.

    A tracked file missing from the working tree shrinks ``scanned`` while
    ``tracked`` still counts it, so ``excess`` falls. It must clamp at 0 rather
    than going negative and reading as a bizarre measurement.
    """
    (worktree / "pkg" / "a.py").unlink()
    (worktree / "pkg" / "b.py").unlink()
    (worktree / "README.md").unlink()

    measured = measure_worktree_pollution(worktree, limit=10)

    assert measured is not None
    assert measured.scanned == 0
    assert measured.excess == 0
    assert measured.refuses is False


# --- The scan cap: the guard must not become the burn it prevents --------------


def test_the_scan_stops_at_the_cap_and_says_so(worktree: Path) -> None:
    """A hostile or merely enormous tree is bounded into constant work.

    The cap is ``tracked + 4 * limit`` entries: enough to decide (it needs only
    ``limit + 1`` excess) and enough for the attribution to be accurate, but not
    proportional to the tree.
    """
    limit = 25
    _seed(worktree, "huge", 10 * limit)

    measured = measure_worktree_pollution(worktree, limit=limit)

    assert measured is not None
    assert measured.truncated is True
    assert measured.scanned <= measured.tracked + 4 * limit
    # Truncated or not, a tree this far past its index still refuses.
    assert measured.refuses is True


def test_a_tree_inside_the_cap_is_not_marked_truncated(worktree: Path) -> None:
    """The floor for the assertion above — ``truncated`` must discriminate."""
    _seed(worktree, "some", 30)

    measured = measure_worktree_pollution(worktree, limit=25)

    assert measured is not None
    assert measured.truncated is False
    assert measured.scanned == 33


# --- Fail-open: every unanswerable case is *no opinion* ------------------------


def test_a_zero_limit_disables_the_check_without_touching_git(
    worktree: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``0`` is the off switch: no subprocess, no walk, no measurement."""
    called: list[int] = []

    def _spy(*args: object, **kwargs: object) -> None:
        called.append(1)
        return None

    monkeypatch.setattr("harness.cli.review_pollution.tracked_paths", _spy)
    _seed(worktree, ".venv", 500)

    assert measure_worktree_pollution(worktree, limit=0) is None
    assert called == []


def test_a_path_that_is_not_a_git_top_level_is_no_opinion(tmp_path: Path) -> None:
    """Without the anchor, git walks *up* and reports the main checkout's index."""
    plain = tmp_path / "plain"
    plain.mkdir()
    (plain / "a.txt").write_text("a\n")

    assert measure_worktree_pollution(plain, limit=1) is None


def test_an_empty_index_is_no_opinion(tmp_path: Path) -> None:
    """0 tracked files is the input that makes every file look like excess."""
    fresh = tmp_path / "fresh"
    fresh.mkdir()
    _git_cmd(fresh, "init", "-b", "dev")
    _seed(fresh, "stuff", 50)

    assert measure_worktree_pollution(fresh, limit=1) is None


@pytest.mark.parametrize("failure", ["nonzero", "timeout"])
def test_a_degraded_git_probe_is_no_opinion(
    worktree: Path, monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    """A corrupt index or a wedged git must not refuse a run.

    Driven through the real :func:`tracked_paths` — only ``run_git`` is stubbed —
    so this exercises the enumeration's own failure handling rather than a stub
    of the thing under test.
    """
    real = _git.run_git

    def _degraded(cwd: Path, *args: str, **kwargs: object) -> object:
        if args[:1] == ("ls-files",):
            if failure == "timeout":
                raise subprocess.TimeoutExpired(["git", "ls-files"], 15)
            return subprocess.CompletedProcess(["git"], 128, "README.md\0", "corrupt")
        return real(cwd, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(_git, "run_git", _degraded)
    _seed(worktree, ".venv", 500)

    assert measure_worktree_pollution(worktree, limit=1) is None


# --- The walk cannot leave the worktree, and cannot be stopped by it -----------


def test_a_symlink_out_of_the_worktree_is_counted_once_not_followed(
    worktree: Path, tmp_path: Path
) -> None:
    """``followlinks=False``: a symlink is one entry and is never descended into.

    Without it a link to ``/`` (or to a parent) enumerates paths outside the
    worktree — and can make the scan non-terminating.
    """
    outside = tmp_path / "outside"
    outside.mkdir()
    for i in range(50):
        (outside / f"o{i}.txt").write_text("o")
    (worktree / "link").symlink_to(outside, target_is_directory=True)

    measured = measure_worktree_pollution(worktree, limit=100)

    assert measured is not None
    # The 50 files behind the link are not enumerated; the link itself is not a
    # file to ``os.walk`` either, so the tree reads exactly as its tracked set.
    assert measured.scanned == 3
    assert measured.excess == 0


def test_the_git_directory_is_never_walked(worktree: Path) -> None:
    """``.git`` is pruned — its object churn is not the operator's pollution.

    A linked worktree's ``.git`` is a *file*, and a main checkout's is a
    directory holding thousands of objects; counting either would measure git
    rather than the tree.
    """
    measured = measure_worktree_pollution(worktree, limit=10)

    assert measured is not None
    assert measured.scanned == 3
    assert all(entry.segment != ".git" for entry in measured.largest)


def test_an_unreadable_directory_is_skipped_rather_than_raising(
    worktree: Path,
) -> None:
    """The contents being measured are untrusted; a permission error is not fatal."""
    locked = worktree / "locked"
    locked.mkdir()
    (locked / "x.bin").write_text("x")
    locked.chmod(0o000)
    try:
        measured = measure_worktree_pollution(worktree, limit=10)
    finally:
        locked.chmod(0o755)

    assert measured is not None
    assert measured.refuses is False


def test_root_level_files_are_aggregated_and_never_named(worktree: Path) -> None:
    """Only depth-1 segments are ever reported.

    A confidentiality property, not an implementation accident: a root-level
    ``.env.production`` must reach neither the ledger nor the orchestrator's
    context. It is aggregated under a fixed placeholder instead.
    """
    (worktree / ".env.production").write_text("SECRET=1\n")
    (worktree / "notes.txt").write_text("n\n")

    measured = measure_worktree_pollution(worktree, limit=1)

    assert measured is not None
    segments = [entry.segment for entry in measured.largest]
    assert ".env.production" not in segments
    assert "notes.txt" not in segments
    assert any(entry.segment == "(root)" for entry in measured.largest)


# --- The two shapes a real run worktree has that a `git init` fixture does not --


def test_a_linked_worktrees_git_file_is_counted_once_and_not_a_directory(
    worktree: Path, tmp_path: Path
) -> None:
    """The production shape: in a linked worktree ``.git`` is a **file**.

    Every fixture above builds its tree with ``git init``, where ``.git`` is a
    directory and the prune is what keeps it out. A ``harness start`` worktree is
    not that — ``.git`` there is a one-line gitdir *pointer file*, so the prune
    never fires and the pointer is counted as one ordinary root-level file.

    That is the right answer (one file is not pollution), but until this case
    existed nothing measured the shape the guard actually runs against, and the
    module's own docstring claims to handle both. Raised as a coverage gap by the
    review of #359.
    """
    linked = tmp_path / "linked"
    subprocess.run(
        ["git", "-C", str(worktree), "worktree", "add", "-q", str(linked), "-b", "wt"],
        check=True, capture_output=True, text=True,
    )
    assert (linked / ".git").is_file(), "premise: a linked worktree's .git is a file"

    measured = measure_worktree_pollution(linked, limit=100)

    assert measured is not None
    # The three tracked files, plus the gitdir pointer as a single root entry.
    assert measured.tracked == 3
    assert measured.scanned == 4
    assert measured.excess == 1
    assert measured.refuses is False
    assert all(entry.segment != ".git" for entry in measured.largest)


def test_a_nested_git_repository_is_counted_as_ordinary_pollution(
    worktree: Path,
) -> None:
    """A checkout someone left inside the worktree is pollution, and counts.

    Its *working files* are exactly the bulk that drowns the engine, so they
    count — which is also why the walk is not delegated to git, whose own tooling
    treats a nested repository as opaque and would report it as a single entry.

    Its ``.git`` does **not** count: the prune drops any directory of that name at
    any depth, not only the worktree's own. Object churn is git's, never the
    operator's pollution, and it is not what the operator can act on. The exact
    equality below is what pins that — the nested repo's internals are dozens of
    files, so a prune scoped to depth 0 would fail here rather than pass quietly.
    """
    nested = worktree / "vendored"
    nested.mkdir()
    _git_cmd(nested, "init", "-b", "dev")
    for i in range(30):
        (nested / f"v{i}.py").write_text("x = 1\n")

    measured = measure_worktree_pollution(worktree, limit=100)

    assert measured is not None
    assert measured.largest[0].segment == "vendored"
    assert measured.largest[0].files == 30
    assert measured.excess == 30
