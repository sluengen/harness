"""#352 — no tracked path may point outside the repository.

A `.venv -> /tmp/review-venv/.venv` symlink was committed by `git add -A`,
because `.gitignore` carried `.venv/` — a trailing slash matches a *directory*
only, and `uv` leaves a **symlink** whenever the environment lives elsewhere.
Nothing noticed until a reviewer ran the gate on a clean checkout.

What made one stray entry expensive is that git *recreates* it: every fresh
clone, worktree and CI checkout materialised a dangling symlink at the repo
root, where it shadowed the real environment. `scripts/verify.sh` then exited 97
at its toolchain preflight, and `tests/_gitutil.tracked_files_under` — which
resolves each tracked path and calls `Path.relative_to` — raised `ValueError` at
*import* of every guard built on it, aborting collection rather than failing a
test. So the tree that a gate was run on and the tree that would have merged
were different trees, which is the one property the gate exists to guarantee.

The guard is two assertions over the tracked tree, both cheap:

* no tracked symlink resolves outside the repository — the property that broke
  the derived-set guards, stated directly. A dangling target counts as outside:
  it resolves nowhere, which is the shape the defect actually had;
* `.gitignore` matches the environment directory in **both** shapes, so
  `git add -A` cannot track it again.

A blanket "no tracked symlinks" rule was written first and is **not** what
shipped: the repo has 21 legitimate ones (`.codex/skills/*`, relative links into
`skills/`), and a rule that flags them would be a rule with an allowlist, which
is how a guard turns into a hole. What distinguishes the defect from those is not
that it is a symlink but *where it points* — outside the tree, at a path only one
machine has — so that is what is measured.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]


def _tracked_entries() -> list[tuple[str, str]]:
    """``(mode, path)`` for every tracked entry, straight from the index.

    Read via ``git ls-files -s`` rather than by walking the filesystem, because
    the mode is what identifies a symlink (``120000``) and a *dangling* one
    cannot be classified any other way — ``Path.is_symlink`` would answer, but
    only for entries that were materialised, and the index is the thing that
    made this reproduce everywhere.
    """
    out = subprocess.run(
        ["git", "-C", str(_REPO_ROOT), "ls-files", "-s"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    entries: list[tuple[str, str]] = []
    for line in out.splitlines():
        if not line.strip():
            continue
        meta, _, path = line.partition("\t")
        entries.append((meta.split()[0], path))
    return entries


TRACKED = _tracked_entries()

#: git's mode for a symbolic link.
_SYMLINK_MODE = "120000"


def test_the_tracked_corpus_is_non_empty() -> None:
    """Non-vacuity floor: a failed ``git ls-files`` would make both guards silent.

    Membership, not cardinality — a count would be the drift the guard removes.
    """
    paths = {path for _, path in TRACKED}
    assert "harness/assurance.py" in paths
    assert ".gitignore" in paths


#: Every tracked symlink, by repo-relative path. Derived from the index rather
#: than the filesystem: the mode is what identifies one, and it is the *index*
#: entry that git recreates in every clone.
TRACKED_SYMLINKS = [path for mode, path in TRACKED if mode == _SYMLINK_MODE]


def test_the_symlink_corpus_reaches_the_links_this_repo_really_has() -> None:
    """Non-vacuity floor on the derived subject set.

    The sweep below is parametrized over ``TRACKED_SYMLINKS``; an empty
    derivation would make it a green no-op that reads as "no bad symlinks". This
    repo genuinely carries some, so name one — and the assertion doubles as the
    record that the blanket ban was rejected for a reason, not overlooked.
    """
    assert ".codex/skills/writing-quality" in TRACKED_SYMLINKS


def _resolves_outside(path: str) -> bool:
    """Does the tracked symlink at ``path`` point anywhere but inside the repo?

    Read with ``readlink`` against the *index*, not the filesystem, so a link
    that was never materialised is still judged. A dangling target answers
    ``True``: it resolves nowhere, which is the defect's own shape.
    """
    blob = subprocess.run(
        ["git", "-C", str(_REPO_ROOT), "cat-file", "-p", f"HEAD:{path}"],
        capture_output=True,
        text=True,
    )
    target = blob.stdout.strip() if blob.returncode == 0 else ""
    if not target:
        # Not in HEAD yet (a staged addition) — fall back to the working tree.
        link = _REPO_ROOT / path
        target = str(link.readlink()) if link.is_symlink() else ""
    if not target:
        return True
    resolved = (_REPO_ROOT / path).parent / target
    try:
        resolved.resolve(strict=True).relative_to(_REPO_ROOT.resolve())
    except (ValueError, OSError):
        return True
    return False


@pytest.mark.parametrize("path", TRACKED_SYMLINKS, ids=lambda p: p)
def test_no_tracked_symlink_escapes_the_repository(path: str) -> None:
    """The rule: a tracked link may point within the tree, never out of it.

    git recreates the index entry in every clone, worktree and CI checkout, so a
    target that exists on one machine — or on none — becomes a property of every
    checkout, and the tree a gate runs on stops being the tree that merges.
    """
    assert not _resolves_outside(path), (
        f"{path} is a tracked symlink resolving outside the repository. Every "
        f"clone and worktree will materialise it, so whatever it points at "
        f"becomes a precondition of checking this repo out."
    )


def test_the_environment_directory_is_ignored_in_both_shapes() -> None:
    """`.gitignore` must match `.venv` as a symlink *and* as a directory.

    The hole that let the defect in: an entry written ``.venv/`` matches only a
    directory, and ``uv`` writes a symlink whenever the environment lives
    outside the tree. Asserted through ``git check-ignore`` — the real matcher —
    rather than by reading the file, because what matters is git's answer, not
    the presence of a line that looks right.
    """
    for candidate in (".venv", ".venv/", "venv", "venv/"):
        result = subprocess.run(
            ["git", "-C", str(_REPO_ROOT), "check-ignore", "-q", candidate],
            capture_output=True,
        )
        assert result.returncode == 0, (
            f"git does not ignore {candidate!r}; `git add -A` can therefore "
            f"track an environment left in that shape"
        )
