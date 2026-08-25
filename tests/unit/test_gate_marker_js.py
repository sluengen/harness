"""#500 — the gate marker's writer half, now ``scripts/gate-marker.js``.

Admission (ADR 0017 D5): class (a) — the executable behaviour of a shipped
program, driven end to end as a subprocess.

``scripts/verify.sh`` writes a **gate marker** on green, named after the **git
tree object** it verified, and two hooks read it from opposite sides of one
equality: the Stop hook asks *"does a marker cover the tree I am about to claim
is done?"* and the push guard asks *"does a marker cover the tree this push
carries?"*. ADR 0018 moves the writer into the runtime the readers were already
forced into, so the convention has one language rather than two.

This module is the re-home of ``tests/unit/test_gate_marker.py``, which died
with ``scripts/gate_marker.py``. A deletion pass that moves a definition must
move its killer (craft.md → *A deletion pass that moves a definition must move
its killer*), so every property that module asserted is carried here explicitly,
one test per property; the enumeration below is that module's own order,
which is not everywhere this file's:

tree matches ``HEAD^{tree}`` clean · tree covers uncommitted work · tree changes
on a tracked edit · tree ignores what git ignores · computing the tree stages
nothing · tree works with no commits · the marker lives in the git common
directory · writing perturbs neither the working tree nor the tree it records ·
linked worktrees agree on the path · preflight refuses a visible nested worktree
and writes no marker directory · preflight treats a newline in a path as data ·
preflight allows an ignored one · preflight allows an absent prunable one ·
preflight fails closed on an indeterminate ``check-ignore`` · the payload fields ·
the filename carries the claim · the max-age default and override · the
degenerate max-age spellings · prune drops stale · prune keeps at most ``KEEP`` ·
write prunes · write before the first commit records what it can · each
subcommand's stdout · a refusal outside a repository.

The port also adds cases the Python module had no subject for — the ``status``
subcommand ``scripts/mutate.py`` now queries, the usage exit ``scripts/verify.sh``
now distinguishes from a refusal, and the scratch index nothing else sweeps. Two
of the additions are different in kind: they exist because **the port could be
wrong and green without them**, and each names a way JavaScript does not inherit
what Python gave for free:

* :func:`test_preflight_allows_a_sibling_worktree_sharing_the_roots_path_prefix`
  — Python got the descendant test for free from ``Path.relative_to``; JavaScript
  has no equivalent, and the obvious ``candidate.startsWith(root)`` spelling
  reads a sibling at ``<root>-other`` as a descendant.
* :func:`test_pruning_survives_a_marker_that_vanishes` — a **declared departure**
  from the Python behaviour, not a port. Python's ``prune`` documented itself as
  best-effort and was not: it sorted by ``Path.stat().st_mtime``, so a marker
  unlinked by a concurrent gate run in another worktree between the sort and the
  loop raised — *after* the marker was written, turning a green gate red with the
  evidence already on disk. This repo runs many worktrees concurrently. The port
  skips a file that has vanished instead.

Where each test reads its operand, because that decides the mutation instrument
(#490 — an index-reading guard is out of ``scripts/mutate.py``'s reach and prints
SURVIVED with no defect):

* every behavioural case below spawns ``REPO_ROOT/scripts/gate-marker.js`` — the
  **working file**, which is what ``scripts/mutate.py`` edits, so they are
  reachable by a mutation table;
* the AC-6 cases at the foot read the **git index**, and are provable only by a
  staged probe.
"""

from __future__ import annotations

import ast
import json
import os
import shutil
import subprocess
import time
from pathlib import Path

import pytest

from tests._gitutil import indexed_text, tracked_files_under, tracked_py_sources
from tests.unit._prose import REPO_ROOT

HELPER = REPO_ROOT / "scripts" / "gate-marker.js"


def _node() -> str:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node not available")
    return node


def _git_binary() -> str:
    binary = shutil.which("git")
    if binary is None:
        pytest.skip("git not available")
    return binary


def _git(repo: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", *args], cwd=repo, check=True, capture_output=True, text=True
    )
    return completed.stdout.strip()


def _cli(
    repo: Path, *args: str, env: dict[str, str] | None = None, path_prefix: Path | None = None
) -> subprocess.CompletedProcess[str]:
    """Run the shipped CLI in ``repo``.

    ``path_prefix`` prepends a directory to ``PATH`` so a shim can intercept the
    ``git`` the helper resolves — the subprocess-level replacement for the
    ``monkeypatch.setattr`` the Python module allowed, and the stronger of the
    two: it exercises the shipped code rather than a patched attribute.
    """
    environ = {**os.environ, **(env or {})}
    if path_prefix is not None:
        environ["PATH"] = f"{path_prefix}{os.pathsep}{environ['PATH']}"
    return subprocess.run(
        [_node(), str(HELPER), *args],
        cwd=repo,
        capture_output=True,
        text=True,
        timeout=60,
        env=environ,
    )


def _exec(repo: Path, body: str, env: dict[str, str] | None = None) -> str:
    """Evaluate ``body`` against the helper's exports, in ``repo``.

    ``require``ing the helper does not run it — the entry point sits behind
    ``require.main === module``, exactly as every hook does — so this reads the
    shipped implementation rather than a restatement of it.
    """
    script = "const h = require(process.env.HELPER_PATH);" + body
    proc = subprocess.run(
        [_node(), "-e", script],
        cwd=repo,
        capture_output=True,
        text=True,
        timeout=60,
        env={**os.environ, **(env or {}), "HELPER_PATH": str(HELPER)},
    )
    assert proc.returncode == 0, f"{body!r} failed (rc={proc.returncode}): {proc.stderr.strip()}"
    return proc.stdout.strip()


def _eval(repo: Path, expression: str, env: dict[str, str] | None = None) -> str:
    return _exec(repo, f"process.stdout.write(String({expression}));", env)


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


def _tree(repo: Path) -> str:
    """The CLI's own tree oid.

    The success assertion lives **here** rather than in each caller because
    without it a failing CLI answers ``""`` and every equality between two of
    these answers holds by agreeing about nothing — measured on this module's
    first (RED) run, where two cases passed against a tree that had no helper at
    all (craft.md → *Born green*).
    """
    proc = _cli(repo, "tree")
    assert proc.returncode == 0, f"gate-marker.js tree failed: {proc.stderr.strip()}"
    oid = proc.stdout.strip()
    assert len(oid) == 40, f"expected a tree oid, got {oid!r}"
    return oid


def _marker_path(repo: Path, tree: str) -> Path:
    proc = _cli(repo, "path", "--tree", tree)
    assert proc.returncode == 0, proc.stderr
    return Path(proc.stdout.strip())


# --- tree identity ------------------------------------------------------------


def test_the_tree_matches_head_on_a_clean_worktree(repo: Path) -> None:
    """The keystone equality ``commands/build.md`` already relies on."""
    assert _tree(repo) == _git(repo, "rev-parse", "HEAD^{tree}")


def test_the_tree_covers_uncommitted_work(repo: Path) -> None:
    """An untracked file is part of what a completion claim covers, so it is part
    of the tree. This is what makes "the marker is one edit stale" a detectable
    state rather than an invisible one."""
    clean = _tree(repo)
    (repo / "b.txt").write_text("two\n")

    assert _tree(repo) != clean


def test_the_tree_changes_when_a_tracked_file_changes(repo: Path) -> None:
    before = _tree(repo)
    (repo / "a.txt").write_text("one, edited\n")

    assert _tree(repo) != before


def test_the_tree_ignores_what_git_ignores(repo: Path) -> None:
    """``git add -A`` honours ``.gitignore``, so ``gate.log`` and a venv are
    excluded exactly as they are excluded from any commit. Without this the
    marker would be stale the moment the gate wrote its own log."""
    (repo / ".gitignore").write_text("gate.log\n")
    _git(repo, "add", ".gitignore")
    _git(repo, "commit", "-q", "-m", "ignore")
    before = _tree(repo)
    (repo / "gate.log").write_text("=== ruff ===\n")

    assert _tree(repo) == before
    # The paired control. Without it this equality also holds for an
    # implementation that ignores *every* untracked file — or that never looks
    # at the working tree at all — so the ignored half would prove nothing.
    (repo / "not-ignored.txt").write_text("visible\n")
    assert _tree(repo) != before


def test_computing_the_tree_stages_nothing(repo: Path) -> None:
    """The gate must not stage as a side effect — hence the temporary index."""
    (repo / "b.txt").write_text("two\n")
    before = _git(repo, "status", "--porcelain")
    assert before, "the fixture is clean, so an equality over `status` measures nothing"

    _tree(repo)

    assert _git(repo, "status", "--porcelain") == before
    assert _git(repo, "diff", "--cached", "--name-only") == ""


def test_the_tree_works_in_a_repository_with_no_commits(tmp_path: Path) -> None:
    """``git read-tree HEAD`` fails before the first commit; the fallback to an
    empty index is what keeps a fresh repo from crashing the gate."""
    root = tmp_path / "empty"
    root.mkdir()
    _git(root, "init", "-q", "--initial-branch=dev")
    (root / "a.txt").write_text("one\n")

    proc = _cli(root, "tree")

    assert proc.returncode == 0, proc.stderr
    assert len(proc.stdout.strip()) == 40


def test_the_scratch_index_is_removed(repo: Path) -> None:
    """The temporary index lives in the marker directory, not ``TMPDIR``, and is
    removed in a ``finally``. Pinned because a leftover is *not* swept by the
    prune — the prune globs ``*.json`` and a scratch index is named
    ``.index-…`` — so nothing else would ever notice one accumulating."""
    _tree(repo)
    directory = _marker_path(repo, "0" * 40).parent

    assert [p.name for p in directory.iterdir() if p.name.startswith(".index-")] == []


# --- where the marker lives ---------------------------------------------------


def test_the_marker_lives_in_the_git_common_directory(repo: Path) -> None:
    common = Path(_git(repo, "rev-parse", "--path-format=absolute", "--git-common-dir"))
    marker = _marker_path(repo, "0" * 40)

    assert marker.parent == (common / "harness" / "gate").resolve()
    assert marker.name == "0" * 40 + ".json"


def test_writing_a_marker_leaves_the_working_tree_untouched(repo: Path) -> None:
    """The marker home cannot be tracked by construction, so no consuming repo
    needs a ``.gitignore`` rule to adopt this — and a gate run adds nothing for a
    human to explain away in ``git status``."""
    (repo / "b.txt").write_text("two\n")
    before = _git(repo, "status", "--porcelain")
    assert before, "the fixture is clean, so an equality over `status` measures nothing"

    assert _cli(repo, "write").returncode == 0

    assert _git(repo, "status", "--porcelain") == before


def test_writing_a_marker_does_not_perturb_the_tree_it_records(repo: Path) -> None:
    """The measuring test for the marker-home decision.

    A marker under ``.harness/`` in a repo without that ``.gitignore`` rule would
    be swept up by the next ``git add -A``, so the tree the marker names would
    never again be the tree the gate computes — a silent, permanent fail-closed
    wedge. Measured by recomputing the tree after the write.
    """
    proc = _cli(repo, "write")
    assert proc.returncode == 0, proc.stderr
    recorded = Path(proc.stdout.split("->", 1)[1].strip())

    assert _tree(repo) == json.loads(recorded.read_text())["tree"]


def test_linked_worktrees_agree_on_the_marker_path(repo: Path, tmp_path: Path) -> None:
    """Two worktrees of one repo share the common directory, so a gate run in a
    detached gate worktree writes a marker the build worktree can read. Two
    worktrees at the same tree OID have byte-identical content, so this is
    correctness rather than convenience."""
    linked = tmp_path / "linked"
    _git(repo, "worktree", "add", "-q", "--detach", str(linked))

    assert _marker_path(linked, "0" * 40) == _marker_path(repo, "0" * 40)


# --- the nested-worktree preflight --------------------------------------------


def test_preflight_refuses_a_registered_nested_worktree_visible_to_git(repo: Path) -> None:
    """#494 / ERP-349: ``git add -A`` must not sweep in an agent worktree.

    Also AC-4's unit-level witness that the refusal happens **before** anything
    materialises a tree: ``currentTree``'s first act is to create the marker
    directory, so the directory's absence is the observable that orders them.
    """
    nested = repo / ".worktrees" / "task"
    _git(repo, "worktree", "add", "-q", "-b", "task/nested", str(nested))
    assert "?? .worktrees/" in _git(repo, "status", "--porcelain")

    proc = _cli(repo, "preflight")

    assert proc.returncode == 2, proc.stderr
    assert "registered nested worktree is visible to git" in proc.stderr
    assert str(nested) in proc.stderr
    common = Path(_git(repo, "rev-parse", "--path-format=absolute", "--git-common-dir"))
    assert not (common / "harness" / "gate").exists(), (
        "a refused preflight materialised the marker directory, so it ran after "
        "the tree computation rather than before it"
    )


def test_preflight_treats_a_newline_in_a_registered_path_as_path_data(repo: Path) -> None:
    """Porcelain framing, not line splitting, owns untrusted worktree paths."""
    nested = repo / ".worktrees" / "agent\ncontinued"
    _git(repo, "worktree", "add", "-q", "-b", "task/newline", str(nested))

    proc = _cli(repo, "preflight")

    assert proc.returncode == 2, proc.stderr
    assert "registered nested worktree is visible" in proc.stderr
    assert str(nested) in proc.stderr


def test_preflight_allows_an_ignored_registered_nested_worktree(repo: Path) -> None:
    """The same registered layout is safe once Git excludes its parent."""
    (repo / ".gitignore").write_text(".worktrees/\n")
    _git(repo, "add", ".gitignore")
    _git(repo, "commit", "-q", "-m", "ignore worktrees")
    nested = repo / ".worktrees" / "task"
    _git(repo, "worktree", "add", "-q", "-b", "task/nested", str(nested))

    proc = _cli(repo, "preflight")

    assert proc.returncode == 0, proc.stderr


def test_preflight_allows_an_absent_prunable_registered_nested_worktree(repo: Path) -> None:
    """A stale registration cannot be swept into the candidate tree."""
    nested = repo / ".worktrees" / "gone"
    _git(repo, "worktree", "add", "-q", "-b", "task/gone", str(nested))
    shutil.rmtree(nested)
    listing = _git(repo, "worktree", "list", "--porcelain")
    assert f"worktree {nested}" in listing
    assert "prunable " in listing

    proc = _cli(repo, "preflight")

    assert proc.returncode == 0, proc.stderr


def test_preflight_allows_a_sibling_worktree_sharing_the_roots_path_prefix(
    repo: Path, tmp_path: Path
) -> None:
    """The case Python got for free and JavaScript does not.

    ``Path.relative_to`` raises for a non-descendant; the obvious JS spelling,
    ``candidate.startsWith(root)``, reads ``<root>-other`` as a descendant and
    refuses a perfectly safe sibling — the gate would become unrunnable for
    anyone whose worktree naming shares a prefix, which is this repo's own
    convention (``harness`` / ``harness-work-500``). Not ignored and not absent,
    so the *only* thing keeping it out of the refusal is the descendant test.
    """
    sibling = tmp_path / "repo-other"
    _git(repo, "worktree", "add", "-q", "-b", "task/sibling", str(sibling))
    assert str(sibling).startswith(str(repo)), (
        "the fixture no longer shares the root's path prefix, so it cannot "
        "distinguish a prefix test from a descendant test"
    )

    proc = _cli(repo, "preflight")

    assert proc.returncode == 0, (
        f"a sibling worktree at {sibling} was read as nested below {repo}: {proc.stderr!r}"
    )


def test_preflight_fails_closed_when_git_cannot_decide_ignore_status(
    repo: Path, tmp_path: Path
) -> None:
    """An infrastructure query error is not evidence that the descendant is safe.

    Reached with a ``git`` shim on ``PATH`` that answers ``check-ignore`` with
    128 and ``exec``s the real git for everything else, so the shipped code runs
    unmodified — the Python module could only reach this by monkeypatching one of
    its own attributes.
    """
    nested = repo / ".worktrees" / "task"
    _git(repo, "worktree", "add", "-q", "-b", "task/nested", str(nested))
    bindir = tmp_path / "shim"
    bindir.mkdir()
    shim = bindir / "git"
    shim.write_text(
        "#!/bin/sh\n"
        'if [ "$1" = "check-ignore" ]; then\n'
        '  echo "bad index" >&2\n'
        "  exit 128\n"
        "fi\n"
        f'exec {_git_binary()} "$@"\n'
    )
    shim.chmod(0o755)

    proc = _cli(repo, "preflight", path_prefix=bindir)

    assert proc.returncode == 2, proc.stderr
    assert "check-ignore" in proc.stderr
    assert "128" in proc.stderr


# --- the payload --------------------------------------------------------------


def test_the_marker_records_the_tree_it_covers(repo: Path) -> None:
    proc = _cli(repo, "write")
    assert proc.returncode == 0, proc.stderr
    marker = Path(proc.stdout.split("->", 1)[1].strip())
    payload = json.loads(marker.read_text())

    assert payload["tree"] == marker.stem
    assert payload["schema"] == int(_eval(repo, "h.SCHEMA"))
    assert payload["exit"] == 0
    assert payload["head"] == _git(repo, "rev-parse", "HEAD")
    assert payload["branch"] == "dev"
    assert Path(payload["worktree"]).resolve() == repo.resolve()
    assert payload["writer"].startswith("gate-marker.js@"), (
        "the payload must name the implementation that produced it; after #500 "
        f"that is the JavaScript writer, not the retired Python one: {payload['writer']!r}"
    )


def test_the_filename_carries_the_claim_not_the_body(repo: Path) -> None:
    """No hook parses the marker body. The decision predicate is the filename
    plus the mtime, which is honest: anyone who can write the file can write
    valid JSON, so parsing buys nothing. Pinned so a later change that starts
    depending on a body field has to argue with this test."""
    proc = _cli(repo, "write")
    assert proc.returncode == 0, proc.stderr
    marker = Path(proc.stdout.split("->", 1)[1].strip())

    assert marker.name == _tree(repo) + ".json"


def test_writing_a_marker_before_the_first_commit_records_what_it_can(tmp_path: Path) -> None:
    """A repository with no commits still has a tree, so the gate can still run
    green over it and still leave evidence.

    The commit and branch fields degrade to empty rather than failing the write:
    they are diagnostics for a human reading the file, and no hook reads the body.
    Losing the whole marker over a field nobody consults would fail the gate
    closed on the one shape where the tree is least ambiguous.
    """
    root = tmp_path / "unborn"
    root.mkdir()
    _git(root, "init", "-q", "--initial-branch=dev")
    (root / "a.txt").write_text("one\n")

    proc = _cli(root, "write")
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(Path(proc.stdout.split("->", 1)[1].strip()).read_text())

    assert payload["tree"] == _tree(root)
    assert payload["head"] == ""
    assert payload["branch"] == ""


# --- freshness ----------------------------------------------------------------


def test_the_max_age_default_and_override(repo: Path) -> None:
    """The bound exists for **toolchain drift under an unchanged tree** — the
    venv is not in the tree, ``uv.lock`` is — not for session scope."""
    env_name = _eval(repo, "h.MAX_AGE_ENV")

    assert _eval(repo, "h.maxAgeSeconds({})") == "86400"
    assert _eval(repo, f'h.maxAgeSeconds({{"{env_name}": "60"}})') == "60"


@pytest.mark.parametrize("value", ["", "0", "-5", "soon", "60s", "+60", " 60 "])
def test_an_unusable_max_age_falls_back_to_the_default(repo: Path, value: str) -> None:
    """Three implementations re-implement this parse, so the degenerate cases have
    to have one agreed answer. An unusable value must not read as "never fresh"
    (which would wedge every session) nor as "always fresh" (which would disarm
    the bound); it reads as unset.

    ``+60`` and `` 60 `` are here because the retired Python parser and the two
    JavaScript ones genuinely disagreed on them — ``int()`` accepted both, the
    digits-only regex accepts neither — and nothing sampled them. With the writer
    in JavaScript the answer is the regex's, pinned here rather than inherited.
    """
    env_name = _eval(repo, "h.MAX_AGE_ENV")

    assert _eval(repo, f"h.maxAgeSeconds({json.dumps({env_name: value})})") == "86400"


# --- pruning ------------------------------------------------------------------


def _marker_dir(repo: Path) -> Path:
    directory = _marker_path(repo, "0" * 40).parent
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def _keep(repo: Path) -> int:
    return int(_eval(repo, "h.KEEP"))


def _prune(repo: Path, directory: Path, *, max_age: int, keep: int) -> None:
    _exec(
        repo,
        f"h.prune({json.dumps(str(directory))}, "
        f"{{maxAge: {max_age}, keep: {keep}}});",
    )


def test_pruning_drops_stale_markers(repo: Path) -> None:
    directory = _marker_dir(repo)
    stale = directory / ("a" * 40 + ".json")
    stale.write_text("{}")
    old = time.time() - 10_000
    os.utime(stale, (old, old))
    fresh = directory / ("b" * 40 + ".json")
    fresh.write_text("{}")

    _prune(repo, directory, max_age=100, keep=_keep(repo))

    assert not stale.exists()
    assert fresh.exists()


def test_pruning_keeps_at_most_the_cap(repo: Path) -> None:
    directory = _marker_dir(repo)
    keep = _keep(repo)
    now = time.time()
    for index in range(keep + 5):
        marker = directory / f"{index:040x}.json"
        marker.write_text("{}")
        os.utime(marker, (now - index, now - index))

    _prune(repo, directory, max_age=86400, keep=keep)

    assert len(list(directory.glob("*.json"))) == keep


def test_pruning_survives_a_marker_that_vanishes(repo: Path) -> None:
    """A **declared departure** from the retired Python writer, not a port.

    Python's ``prune`` said it was best-effort and was not: it sorted by
    ``p.stat().st_mtime``, so a marker unlinked by a concurrent gate run in
    another worktree between the sort and the loop raised — *after* the marker
    was written, so a green gate exited red with the evidence already on disk.
    This repo runs many worktrees at once, which is what makes the window real.

    The dangling symlink is an **instrument for that race**, not a scenario
    anyone will meet: it is the deterministic way to make ``statSync`` throw
    ENOENT for a name ``readdirSync`` just returned. The assertion is that the
    prune completes and the fresh marker survives.
    """
    directory = _marker_dir(repo)
    vanished = directory / ("c" * 40 + ".json")
    vanished.symlink_to(directory / "no-such-marker.json")
    assert not vanished.exists() and vanished.is_symlink()
    fresh = directory / ("d" * 40 + ".json")
    fresh.write_text("{}")

    _prune(repo, directory, max_age=86400, keep=_keep(repo))

    assert fresh.exists()


def test_writing_prunes(repo: Path) -> None:
    """The prune runs on the write path, so the directory stays bounded without
    anything else having to remember to call it."""
    directory = _marker_dir(repo)
    stale = directory / ("a" * 40 + ".json")
    stale.write_text("{}")
    old = time.time() - 10 * 86400
    os.utime(stale, (old, old))

    assert _cli(repo, "write").returncode == 0

    assert not stale.exists()


# --- the CLI, which is what verify.sh and mutate.py run -----------------------


def test_the_tree_subcommand_prints_the_tree(repo: Path) -> None:
    """The first-written case of the port (#500 AC-1)."""
    proc = _cli(repo, "tree")

    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == _git(repo, "rev-parse", "HEAD^{tree}")


def test_the_write_subcommand_creates_the_marker_and_announces_it(repo: Path) -> None:
    """The announcement is diagnostic, not mechanism — but its **format** is
    mechanism: ``tests/unit/test_gate_evidence_hook.py`` parses the tree back out
    of it with ``split(":", 1)[1].split("->")[0]``, so the shape is pinned here
    rather than left to a reader's eye."""
    proc = _cli(repo, "write")

    assert proc.returncode == 0, proc.stderr
    tree = _tree(repo)
    marker = _marker_path(repo, tree)
    assert marker.exists()
    assert proc.stdout.strip() == f"gate marker: {tree} -> {marker}"
    assert proc.stdout.split(":", 1)[1].split("->")[0].strip() == tree


def test_the_path_subcommand_prints_the_marker_path(repo: Path) -> None:
    proc = _cli(repo, "path", "--tree", "c" * 40)

    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == str(_marker_dir(repo) / ("c" * 40 + ".json"))


def test_the_status_subcommand_reports_facts_not_a_verdict(repo: Path) -> None:
    """``scripts/mutate.py``'s gate lock reads this, and it is the whole reason
    the lock needs no second parser of the freshness variable.

    Three facts and no verdict: mutate composes them into its own three refusal
    messages, which is where that distinction already lives.
    """
    proc = _cli(repo, "status")

    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["tree"] == _tree(repo)
    assert payload["marker"] == str(_marker_path(repo, payload["tree"]))
    assert payload["max_age_seconds"] == 86400
    assert set(payload) == {"tree", "marker", "max_age_seconds"}


def test_the_status_bound_follows_the_environment(repo: Path) -> None:
    """The one thing the new architecture could silently get wrong: the bound has
    to cross the process boundary rather than being re-derived on the far side."""
    env_name = _eval(repo, "h.MAX_AGE_ENV")

    proc = _cli(repo, "status", env={env_name: "77"})

    assert proc.returncode == 0, proc.stderr
    assert json.loads(proc.stdout)["max_age_seconds"] == 77


def test_the_cli_refuses_outside_a_repository(tmp_path: Path) -> None:
    """A gate run outside a repository has nothing to record, and saying so beats
    writing a marker somewhere arbitrary."""
    proc = _cli(tmp_path, "tree")

    assert proc.returncode == 2
    assert proc.stdout == ""
    assert "gate-marker:" in proc.stderr


@pytest.mark.parametrize(
    "argv",
    [(), ("frobnicate",), ("path",), ("path", "--tree")],
    ids=["none", "unknown", "no-flag", "no-oid"],
)
def test_a_usage_error_is_distinct_from_a_refusal(repo: Path, argv: tuple[str, ...]) -> None:
    """``scripts/verify.sh`` reads the exit code to decide what to *print*: exit 2
    means a registered nested worktree is visible, and anything else means the
    helper could not do what it was asked. Python conflated a usage error with a
    git refusal at 2, so a typo in the gate would have been reported to an
    operator as a nested worktree — a diagnostic that is false exactly where
    someone acts on it (#487)."""
    proc = _cli(repo, *argv)

    assert proc.returncode == 64, proc.stderr
    assert "usage" in proc.stderr


# --- AC-6: the Python writer is gone, and nothing imports it ------------------
#
# The cases in this section read the **git index**, never the working tree: the
# subject is what a fresh clone and a hydrating consumer receive, and a guard over
# the on-disk file passes on the machine that wrote it (#484). That puts them outside
# ``scripts/mutate.py``'s reach — see the module docstring.


def test_the_python_writer_is_gone() -> None:
    """The durable floor under AC-6's deletion half.

    Floored on **both** sides (#486 — the unfloored operand is the one a defect
    empties): an absence assertion over an empty tracked set is constant-true, so
    the derivation must be non-empty *and* must contain the replacement. A
    ``git ls-files`` query, never a grep: a typo in a pattern and a real absence
    are indistinguishable (craft.md → *Assert absence from the git index, never by
    grep*). The subject is this repository's index, so this takes no fixture
    repository, exactly as
    :func:`test_nothing_imports_the_retired_python_writer` does not.
    """
    tracked = {path.name for path in tracked_files_under("scripts")}

    assert tracked, "no tracked file under scripts/ — the derivation read nothing"
    assert "gate-marker.js" in tracked, (
        f"the replacement writer is not tracked, so the absence below would pass "
        f"for the wrong reason. scripts/ holds: {sorted(tracked)}"
    )
    assert "gate_marker.py" not in tracked


def test_nothing_imports_the_retired_python_writer() -> None:
    """AC-6's invoking half, over every tracked Python source.

    Derived from the tree rather than path-listed: an exclusion list would need
    both a stale and an admitting direction, which is this repo's most-repeated
    defect class (#449 → #458). The corpus is *every* tracked ``.py``, the
    predicate is an AST import, and there is no exemption to go stale.

    Floored: the corpus must be non-empty and must yield imports at all, so a
    broken extractor cannot report "nothing imports it" over nothing (#467).
    """
    offenders: list[str] = []
    modules: set[str] = set()
    sources = tracked_py_sources(".")
    for source in sources:
        relative = source.relative_to(REPO_ROOT).as_posix()
        for node in ast.walk(ast.parse(indexed_text(relative), filename=relative)):
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or ""]
            else:
                continue
            modules.update(names)
            if any(name.split(".")[0] == "gate_marker" for name in names):
                offenders.append(f"{relative}:{node.lineno}")

    assert sources, "no tracked Python source was read"
    assert modules, "the extractor found no import anywhere, so it read nothing"
    assert offenders == [], (
        "these tracked sources still import the retired Python writer, which "
        f"ADR 0018 deletes: {offenders}"
    )
