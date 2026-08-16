"""#436 — the gate marker: the one artifact both enforcement hooks read.

``scripts/verify.sh`` writes a **gate marker** on green, named after the **git
tree object** it verified. Two hooks then read it from opposite sides of one
equality: the Stop hook asks *"does a marker cover the tree I am about to claim
is done?"* and the push guard asks *"does a marker cover the tree this push
carries?"*. ``commands/build.md`` already makes those the same object — it
refuses to integrate unless ``git rev-parse HEAD^{tree}`` equals the tree its
gate ran over — so the marker is the authorisation for both.

This module owns the writer half. The design's load-bearing choices, each with a
test here:

* **Tree identity, not session identity.** ``verify.sh`` has no access to a
  session id, so "ran green in this session" is unenforceable. Tree identity
  answers the stronger question — *did the gate exit 0 over these exact bytes* —
  which no subsequent edit can satisfy.
  :func:`test_the_tree_changes_when_a_tracked_file_changes` and
  :func:`test_the_tree_covers_uncommitted_work`.
* **A temporary index.** The gate must not stage anything as a side effect, so
  the ``git add -A`` runs against a throw-away ``GIT_INDEX_FILE``.
  :func:`test_computing_the_tree_does_not_stage_anything`.
* **The marker lives in the git directory, not the working tree.** A marker
  written into the working tree would be picked up by the very ``git add -A``
  that computes the tree, changing the OID away from the one just recorded — a
  marker that can never match, i.e. a permanent fail-closed wedge in any
  consuming repo that did not add a ``.gitignore`` rule.
  :func:`test_writing_a_marker_does_not_perturb_the_tree_it_records` measures
  exactly that, and :func:`test_writing_a_marker_leaves_the_working_tree_untouched`
  states the structural half.
* **Shared across worktrees.** The git *common* directory is shared by every
  linked worktree, and two worktrees at the same tree OID have byte-identical
  content, so cross-worktree visibility is correct rather than merely
  convenient. :func:`test_linked_worktrees_agree_on_the_marker_path`.
* **Bounded.** ``write`` prunes: markers past the max age go, and at most
  :data:`KEEP` survive. :func:`test_pruning_drops_stale_markers` and
  :func:`test_pruning_keeps_at_most_the_cap`.
* **One freshness rule, read from one place.** Both hooks re-implement the
  path and the age bound in JavaScript, so the Python side must be the
  reference. :func:`test_the_max_age_default_and_override` pins it; the
  cross-language equivalence is ``test_gate_marker_contract.py``.

The CLI is the surface ``verify.sh`` and the tests use: ``write`` (the only
mutating verb), ``path --tree <T>`` and ``tree``.
"""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from types import ModuleType

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "gate_marker.py"


def _module() -> ModuleType:
    """Import the standalone script as a module (``scripts/`` is not a package)."""
    spec = importlib.util.spec_from_file_location("gate_marker", SCRIPT)
    assert spec and spec.loader, f"cannot load {SCRIPT}"
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


gm = _module()


def _git(repo: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A throw-away repository with one commit, on a named branch (#369)."""
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-q", "--initial-branch=dev")
    _git(root, "config", "user.email", "t@example.com")
    _git(root, "config", "user.name", "t")
    (root / "a.txt").write_text("one\n")
    _git(root, "add", "a.txt")
    _git(root, "commit", "-q", "-m", "first")
    return root


# --- tree identity ------------------------------------------------------------


def test_the_tree_matches_head_on_a_clean_worktree(repo: Path) -> None:
    """The keystone equality ``commands/build.md`` already relies on."""
    assert gm.current_tree(repo) == _git(repo, "rev-parse", "HEAD^{tree}")


def test_the_tree_covers_uncommitted_work(repo: Path) -> None:
    """An untracked file is part of what a completion claim covers, so it is
    part of the tree. This is what makes "the marker is one edit stale" a
    detectable state rather than an invisible one."""
    clean = gm.current_tree(repo)
    (repo / "b.txt").write_text("two\n")

    assert gm.current_tree(repo) != clean


def test_the_tree_changes_when_a_tracked_file_changes(repo: Path) -> None:
    before = gm.current_tree(repo)
    (repo / "a.txt").write_text("one, edited\n")

    assert gm.current_tree(repo) != before


def test_the_tree_ignores_what_git_ignores(repo: Path) -> None:
    """``git add -A`` honours ``.gitignore``, so ``gate.log`` and a venv are
    excluded exactly as they are excluded from any commit. Without this the
    marker would be stale the moment the gate wrote its own log."""
    (repo / ".gitignore").write_text("gate.log\n")
    _git(repo, "add", ".gitignore")
    _git(repo, "commit", "-q", "-m", "ignore")
    before = gm.current_tree(repo)
    (repo / "gate.log").write_text("=== ruff ===\n")

    assert gm.current_tree(repo) == before


def test_computing_the_tree_does_not_stage_anything(repo: Path) -> None:
    """The gate must not stage as a side effect — hence the temporary index."""
    (repo / "b.txt").write_text("two\n")
    before = _git(repo, "status", "--porcelain")

    gm.current_tree(repo)

    assert _git(repo, "status", "--porcelain") == before
    assert _git(repo, "diff", "--cached", "--name-only") == ""


def test_the_tree_works_in_a_repository_with_no_commits(tmp_path: Path) -> None:
    """``git read-tree HEAD`` fails before the first commit; the fallback to an
    empty index is what keeps a fresh repo from crashing the gate."""
    root = tmp_path / "empty"
    root.mkdir()
    _git(root, "init", "-q", "--initial-branch=dev")
    (root / "a.txt").write_text("one\n")

    assert len(gm.current_tree(root)) == 40


# --- where the marker lives ---------------------------------------------------


def test_the_marker_lives_in_the_git_common_directory(repo: Path) -> None:
    common = Path(_git(repo, "rev-parse", "--path-format=absolute", "--git-common-dir"))
    path = gm.marker_path("0" * 40, repo)

    assert path.parent == (common / "harness" / "gate").resolve()
    assert path.name == "0" * 40 + ".json"


def test_writing_a_marker_leaves_the_working_tree_untouched(repo: Path) -> None:
    """The other half of the self-perturbation argument: the marker home cannot
    be tracked by construction, so no consuming repo needs a ``.gitignore``
    rule to adopt this — and a gate run adds nothing for a human to explain
    away in ``git status``."""
    (repo / "b.txt").write_text("two\n")
    before = _git(repo, "status", "--porcelain")

    gm.write_marker(repo)

    assert _git(repo, "status", "--porcelain") == before


def test_writing_a_marker_does_not_perturb_the_tree_it_records(repo: Path) -> None:
    """The measuring test for the marker-home decision.

    A marker under ``.harness/`` in a repo without that ``.gitignore`` rule
    would be swept up by the next ``git add -A``, so the tree the marker names
    would never again be the tree the gate computes — a silent, permanent
    fail-closed wedge. Measured by recomputing the tree after the write.
    """
    recorded = gm.write_marker(repo)

    assert gm.current_tree(repo) == json.loads(recorded.read_text())["tree"]


def test_linked_worktrees_agree_on_the_marker_path(repo: Path, tmp_path: Path) -> None:
    """Two worktrees of one repo share the common directory, so a gate run in a
    detached gate worktree writes a marker the build worktree can read. Two
    worktrees at the same tree OID have byte-identical content, so this is
    correctness rather than convenience."""
    linked = tmp_path / "linked"
    _git(repo, "worktree", "add", "-q", "--detach", str(linked))

    assert gm.marker_path("0" * 40, linked) == gm.marker_path("0" * 40, repo)


# --- the payload --------------------------------------------------------------


def test_the_marker_records_the_tree_it_covers(repo: Path) -> None:
    path = gm.write_marker(repo)
    payload = json.loads(path.read_text())

    assert payload["tree"] == path.stem
    assert payload["schema"] == gm.SCHEMA
    assert payload["exit"] == 0
    assert payload["head"] == _git(repo, "rev-parse", "HEAD")
    assert payload["branch"] == "dev"
    assert Path(payload["worktree"]).resolve() == repo.resolve()
    assert payload["writer"].startswith("gate_marker.py@")


def test_the_filename_carries_the_claim_not_the_body(repo: Path) -> None:
    """No hook parses the marker body. The decision predicate is the filename
    plus the mtime, which is honest: anyone who can write the file can write
    valid JSON, so parsing buys nothing. Pinned so a later change that starts
    depending on a body field has to argue with this test."""
    path = gm.write_marker(repo)

    assert path.name == gm.current_tree(repo) + ".json"


# --- freshness ----------------------------------------------------------------


def test_the_max_age_default_and_override() -> None:
    """The bound exists for **toolchain drift under an unchanged tree** — the
    venv is not in the tree, ``uv.lock`` is — not for session scope."""
    assert gm.max_age_seconds({}) == 86400
    assert gm.max_age_seconds({gm.MAX_AGE_ENV: "60"}) == 60


@pytest.mark.parametrize("value", ["", "0", "-5", "soon", "60s"])
def test_an_unusable_max_age_falls_back_to_the_default(value: str) -> None:
    """Both hooks re-implement this parse, so the degenerate cases have to have
    one agreed answer. An unusable value must not read as "never fresh" (which
    would wedge every session) nor as "always fresh" (which would disarm the
    bound); it reads as unset."""
    assert gm.max_age_seconds({gm.MAX_AGE_ENV: value}) == 86400


# --- pruning ------------------------------------------------------------------


def test_pruning_drops_stale_markers(repo: Path) -> None:
    directory = gm.marker_dir(repo)
    directory.mkdir(parents=True, exist_ok=True)
    stale = directory / ("a" * 40 + ".json")
    stale.write_text("{}")
    old = time.time() - 10_000
    os.utime(stale, (old, old))
    fresh = directory / ("b" * 40 + ".json")
    fresh.write_text("{}")

    gm.prune(directory, max_age=100, keep=gm.KEEP)

    assert not stale.exists()
    assert fresh.exists()


def test_pruning_keeps_at_most_the_cap(repo: Path) -> None:
    directory = gm.marker_dir(repo)
    directory.mkdir(parents=True, exist_ok=True)
    now = time.time()
    for index in range(gm.KEEP + 5):
        marker = directory / (f"{index:040x}.json")
        marker.write_text("{}")
        os.utime(marker, (now - index, now - index))

    gm.prune(directory, max_age=86400, keep=gm.KEEP)

    assert len(list(directory.glob("*.json"))) == gm.KEEP


def test_writing_prunes(repo: Path) -> None:
    """The prune runs on the write path, so the directory stays bounded without
    anything else having to remember to call it."""
    directory = gm.marker_dir(repo)
    directory.mkdir(parents=True, exist_ok=True)
    stale = directory / ("a" * 40 + ".json")
    stale.write_text("{}")
    old = time.time() - 10 * 86400
    os.utime(stale, (old, old))

    gm.write_marker(repo)

    assert not stale.exists()


# --- the CLI, which is what verify.sh runs ------------------------------------


def _cli(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        cwd=repo,
        capture_output=True,
        text=True,
        timeout=60,
    )


def test_writing_a_marker_before_the_first_commit_records_what_it_can(
    tmp_path: Path,
) -> None:
    """A repository with no commits still has a tree, so the gate can still run
    green over it and still leave evidence.

    The commit and branch fields degrade to empty rather than failing the write:
    they are diagnostics for a human reading the file, and no hook reads the
    body. Losing the whole marker over a field nobody consults would fail the
    gate closed on the one shape where the tree is least ambiguous.
    """
    root = tmp_path / "unborn"
    root.mkdir()
    _git(root, "init", "-q", "--initial-branch=dev")
    (root / "a.txt").write_text("one\n")

    payload = json.loads(gm.write_marker(root).read_text())

    assert payload["tree"] == gm.current_tree(root)
    assert payload["head"] == ""
    assert payload["branch"] == ""


def test_main_writes_and_announces_in_process(repo: Path, monkeypatch, capsys) -> None:
    """``main`` exercised directly, not only through a subprocess.

    The CLI cases below run the shipped file end to end, which is what proves the
    argv wiring; this one reaches the same code where a failure is attributable
    to a line rather than to an exit status.
    """
    monkeypatch.chdir(repo)

    assert gm.main(["write"]) == 0

    tree = gm.current_tree(repo)
    out = capsys.readouterr().out.strip()
    assert out == f"gate marker: {tree} -> {gm.marker_path(tree, repo)}"


def test_main_prints_the_tree_and_the_path_in_process(repo: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(repo)

    assert gm.main(["tree"]) == 0
    assert capsys.readouterr().out.strip() == gm.current_tree(repo)

    assert gm.main(["path", "--tree", "d" * 40]) == 0
    assert capsys.readouterr().out.strip() == str(gm.marker_path("d" * 40, repo))


def test_main_reports_a_git_failure_rather_than_raising(tmp_path, monkeypatch, capsys) -> None:
    """A gate wrapper reads an exit status, not a traceback. The failure goes to
    stderr with git's own words, which is the best diagnosis available."""
    monkeypatch.chdir(tmp_path)

    assert gm.main(["tree"]) == 2

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "gate_marker:" in captured.err


def test_the_write_subcommand_creates_the_marker_and_announces_it(repo: Path) -> None:
    """The announcement is diagnostic, not mechanism: it puts the tree the gate
    covered into the session record and into ``gate.log``."""
    proc = _cli(repo, "write")

    assert proc.returncode == 0, proc.stderr
    tree = gm.current_tree(repo)
    path = gm.marker_path(tree, repo)
    assert path.exists()
    assert proc.stdout.strip() == f"gate marker: {tree} -> {path}"


def test_the_tree_subcommand_prints_the_tree(repo: Path) -> None:
    proc = _cli(repo, "tree")

    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == gm.current_tree(repo)


def test_the_path_subcommand_prints_the_marker_path(repo: Path) -> None:
    proc = _cli(repo, "path", "--tree", "c" * 40)

    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == str(gm.marker_path("c" * 40, repo))


def test_the_cli_refuses_outside_a_repository(tmp_path: Path) -> None:
    """A gate run outside a repository has nothing to record, and saying so
    beats writing a marker somewhere arbitrary."""
    proc = _cli(tmp_path, "tree")

    assert proc.returncode != 0
    assert proc.stderr.strip()
