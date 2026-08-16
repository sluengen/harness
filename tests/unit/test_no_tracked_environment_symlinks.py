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

The guard is two properties, both cheap — one read straight off the tracked
tree, one measured in a throwaway repo:

* no tracked symlink resolves outside the repository — the property that broke
  the derived-set guards, stated directly. A dangling target counts as outside:
  it resolves nowhere, which is the shape the defect actually had;
* `.gitignore` matches the environment directory in **both** shapes, so
  `git add -A` cannot track it again. Measured *as* `git add -A`, in a throwaway
  repo carrying this repo's `.gitignore` — see
  :func:`_environment_tracked_after_add_all` for why the obvious probe cannot
  answer this one.

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

from tests.unit.test_worktree_ignore_hygiene import _git, _init_hermetic_repo

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
    The first anchor named ``harness/assurance.py`` until #435 deleted the
    package; it is now the gate script, which this repo cannot lose without
    noticing.
    """
    paths = {path for _, path in TRACKED}
    assert "scripts/verify.sh" in paths
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


#: The environment directory names this repo's `.gitignore` must cover, and the
#: two shapes an environment is left in. `uv` writes a real directory when the
#: environment lives in the tree and a **symlink** when it lives outside it, and
#: the shape is the whole point: the defect was a symlink, and an entry written
#: `.venv/` matches only the directory.
_ENVIRONMENT_NAMES = (".venv", "venv")
_ENVIRONMENT_SHAPES = ("symlink", "directory")


def _materialise_environment(repo: Path, outside_root: Path, name: str, shape: str) -> Path:
    """Leave an environment at ``repo/name`` in ``shape``, as `uv` would.

    Split out from the probe below so :func:`test_the_two_shapes_are_two_shapes`
    can assert the two branches really differ. Collapse them — ignore ``shape``,
    or point the "symlink" at a path inside the repo — and every parametrized
    case still runs, still passes, and the symlink question this guard exists
    for stops being asked. That is the defect being fixed here, one level up.
    """
    env = repo / name
    if shape == "directory":
        env.mkdir()
        (env / "pyvenv.cfg").write_text("home = /usr/bin\n")
    else:
        outside = outside_root / name
        outside.mkdir(parents=True)
        (outside / "pyvenv.cfg").write_text("home = /usr/bin\n")
        env.symlink_to(outside)
    return env


def _environment_tracked_after_add_all(
    tmp_path: Path, gitignore: str, name: str, shape: str
) -> set[str]:
    """What `git add -A` tracks at or under ``name``, given ``gitignore``.

    Asked as ``git add -A`` in a throwaway repo rather than as
    ``git check-ignore``, because the spelling that carries the symlink shape is
    exactly the spelling ``check-ignore`` refuses to answer. Measured on git
    2.50.1, with `.venv` a symlink to an out-of-tree environment::

        git check-ignore -q .venv    -> 0     ignored
        git check-ignore -q .venv/   -> 128   fatal: pathspec '.venv/' is
                                              beyond a symbolic link

    ``check-ignore`` has three exits, not two, and the guard this replaced read
    ``128`` as ``1`` — reporting a missing ignore rule it never observed, in the
    one environment it was written for (#442). ``--no-index`` does not dodge it:
    the refusal is pathspec resolution against the working tree, so no
    ``check-ignore`` invocation can answer that question once `.venv` is a link.

    So ask the question the exit code was standing in for. ``git add -A`` is the
    defect's own mechanism — the original `.venv -> /tmp/review-venv/.venv` was
    committed *by* `git add -A` — it has no third exit to misread, and it is
    equally answerable in both shapes.

    Hermetic: `_init_hermetic_repo` copies this repo's `.gitignore` into a repo
    whose ``info/exclude`` is comments-only, so the answer comes from the ignore
    rules this repo ships and not from an ambient exclude file. ``gitignore``
    overrides that copy, which is how the killer below feeds in a stripped one.
    """
    repo = _init_hermetic_repo(tmp_path / "clone")
    (repo / ".gitignore").write_text(gitignore)
    _materialise_environment(repo, tmp_path / "outside", name, shape)

    _git(repo, "add", "-A")
    tracked = _git(repo, "ls-files").stdout.split()
    return {p for p in tracked if p == name or p.startswith(f"{name}/")}


def _without_environment_entries(gitignore: str, name: str) -> str:
    """``gitignore`` with the entries for ``name`` — both spellings — removed."""
    keep = [
        line for line in gitignore.splitlines(keepends=True) if line.strip().rstrip("/") != name
    ]
    return "".join(keep)


def test_the_swept_names_and_shapes_are_the_ones_that_matter() -> None:
    """Membership floor on both subject tuples, and deliberately unparametrized.

    Everything else here — the sweep, the killer, and the shape floor below —
    is parametrized over these two tuples, so a tuple that lost a member would
    shrink all three together and leave the suite green while the question this
    guard exists to ask stopped being asked. Measured rather than supposed:
    setting ``_ENVIRONMENT_SHAPES`` to ``("directory", "directory")`` killed
    nothing anywhere in the tree, with the symlink shape gone from the sweep
    entirely. A floor carried as one more parametrized case cannot see that.

    Membership, never length — ``("directory", "directory")`` satisfies a
    length-2 check forever — and a subset rather than an equality, so adding a
    third name later is not a failure while dropping either of these two is.
    """
    assert {"symlink", "directory"} <= set(_ENVIRONMENT_SHAPES)
    assert {".venv", "venv"} <= set(_ENVIRONMENT_NAMES)


@pytest.mark.parametrize("name", _ENVIRONMENT_NAMES)
def test_the_two_shapes_are_two_shapes(tmp_path: Path, name: str) -> None:
    """Non-vacuity floor on the branch: the two shapes must actually differ.

    The sweep below runs twice per name and reads as covering both shapes. What
    makes that true is only that :func:`_materialise_environment` branches — so
    measure the branch rather than trusting it. The "symlink" case must be a
    symlink whose target is outside the repo, because a link pointing *inside*
    is a shape git answers about happily and would test nothing new; the
    "directory" case must not be a link at all.

    The target is **resolved against the link's own directory** before it is
    judged. ``readlink()`` returns whatever was written, and a relative target
    is never ``is_relative_to`` an absolute parent — so comparing the raw value
    answers "outside the repo" for every relative link, however far inside it
    points. Measured: rewriting the branch to link at a relative path inside the
    repo survived the whole suite while this assertion was reading the raw
    value.
    """
    symlinked = _materialise_environment(
        _init_hermetic_repo(tmp_path / "link-repo"), tmp_path / "outside", name, "symlink"
    )
    assert symlinked.is_symlink()
    target = (symlinked.parent / symlinked.readlink()).resolve()
    assert not target.is_relative_to(symlinked.parent.resolve())

    real = _materialise_environment(
        _init_hermetic_repo(tmp_path / "dir-repo"), tmp_path / "unused", name, "directory"
    )
    assert not real.is_symlink()
    assert real.is_dir()


@pytest.mark.parametrize("shape", _ENVIRONMENT_SHAPES)
@pytest.mark.parametrize("name", _ENVIRONMENT_NAMES)
def test_the_environment_directory_is_ignored_in_both_shapes(
    tmp_path: Path, name: str, shape: str
) -> None:
    """`.gitignore` must match `.venv` as a symlink *and* as a directory (AC-1).

    The hole that let the defect in: an entry written ``.venv/`` matches only a
    directory, and ``uv`` writes a symlink whenever the environment lives
    outside the tree. Asserted by running the real matcher over the real
    `.gitignore` — what matters is git's behaviour, not the presence of a line
    that looks right.
    """
    tracked = _environment_tracked_after_add_all(
        tmp_path, (_REPO_ROOT / ".gitignore").read_text(), name, shape
    )
    assert tracked == set(), (
        f"`git add -A` tracked {sorted(tracked)} — git does not ignore {name!r} "
        f"in its {shape} shape, so an environment left there reaches the index"
    )


@pytest.mark.parametrize("shape", _ENVIRONMENT_SHAPES)
@pytest.mark.parametrize("name", _ENVIRONMENT_NAMES)
def test_removing_the_environment_entries_is_caught_in_both_shapes(
    tmp_path: Path, name: str, shape: str
) -> None:
    """The exclusive killer: strip the entries and the sweep above must fail (AC-2).

    This is the assertion that stops AC-1 being satisfied by swallowing an
    unanswerable probe — a guard that reported "fine" on git's ``128`` would be
    off in exactly the environment it exists for, and would still read green.
    Same function, same inputs, one variable changed, so a sweep that has gone
    blind cannot pass both.

    The stripped `.gitignore` is derived from the real one rather than written
    out here: if this repo ever stops carrying those entries, the strip removes
    nothing and this control goes inert — which the first assertion catches
    instead of letting it pass as a control that flags nothing.
    """
    gitignore = (_REPO_ROOT / ".gitignore").read_text()
    stripped = _without_environment_entries(gitignore, name)
    assert stripped != gitignore, (
        f"`.gitignore` carries no entry for {name!r}, so this control strips "
        f"nothing and proves nothing about the sweep it inverts"
    )

    tracked = _environment_tracked_after_add_all(tmp_path, stripped, name, shape)
    assert tracked != set(), (
        f"with every {name!r} entry removed from `.gitignore`, `git add -A` "
        f"still tracked nothing in the {shape} shape — the sweep above is not "
        f"measuring whether the entries are there"
    )
