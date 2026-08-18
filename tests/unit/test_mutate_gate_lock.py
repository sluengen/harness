"""#473 — mutate's first refusal is the tree-keyed lockfile.

Admission (ADR 0017 D5): class (a) — executable behaviour of ``scripts/mutate.py``.

A mutation run's verdicts are only meaningful over a tree the gate has passed:
the harness's own green-baseline refusal proves the *selection* runs clean, but
nothing proved the whole gate had — so a table could be run, and its report
cited, over a tree that lint, types, or the unselected half of the suite would
have refused. The gate already writes the artifact that says otherwise:
``scripts/verify.sh`` records ``<git-common-dir>/harness/gate/<tree-oid>.json``
via ``scripts/gate_marker.py``, and the enforcement hooks read that same
convention. mutate reuses it rather than growing a second one.

The contract, each direction its own test:

* ``run`` against a tree no fresh marker covers is **refused before anything
  else** — before the table is even read, which is what "first refusal" means
  and what the missing-table fixture proves; nothing is written (exit 2, the
  standing refusal convention).
* a **fresh marker admits the run**: the same missing-table fixture now refuses
  on the *table*, proving the gate refusal stepped aside rather than the run
  aborting for its own reason.
* a **stale marker is no marker** — the freshness bound is the hooks' own
  (``HARNESS_GATE_MARKER_MAX_AGE_SECONDS``, default a day), read through
  ``gate_marker.max_age_seconds`` so a third parser cannot drift.
* ``check`` needs no marker: it writes nothing and runs nothing, and a table
  author must be able to get a table to land before spending a gate run.

The fixture is a real repository — the marker convention keys on the git common
directory and the tree oid, so nothing less would exercise the real path — and
the marker is written by ``gate_marker.write_marker`` itself, the same writer
the gate uses, so the two computations of "the current tree" cannot drift apart
in this module's favour.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from tests.unit._prose import REPO_ROOT

sys.path.insert(0, str(REPO_ROOT / "scripts"))

import gate_marker  # noqa: E402
import mutate  # noqa: E402


def _repo_tree(tmp_path: Path) -> Path:
    """A real repository with one committed file — the tree a run would mutate."""
    tree = tmp_path / "tree"
    tree.mkdir()
    for cmd in (
        ["git", "init", "-q", "-b", "main"],
        ["git", "config", "user.email", "t@example.com"],
        ["git", "config", "user.name", "t"],
    ):
        subprocess.run(cmd, cwd=tree, check=True, capture_output=True)
    (tree / "gate.txt").write_text("sentinel\n")
    (tree / "code.py").write_text("VALUE = 1\n")
    subprocess.run(["git", "add", "-A"], cwd=tree, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-q", "-m", "fixture"], cwd=tree, check=True, capture_output=True
    )
    return tree


def _landing_table(tmp_path: Path, *, sentinel_text: str = "sentinel") -> Path:
    """A minimal table whose targets land in :func:`_repo_tree`'s tree."""
    table = tmp_path / "table.toml"
    table.write_text(
        f"""
select = ["tests"]
sentinel_file = "gate.txt"
sentinel_text = "{sentinel_text}"

[[mutation]]
id = "flip-value"
file = "code.py"
old = "VALUE = 1"
new = "VALUE = 2"
kills = ["tests/test_value.py::test_value"]
"""
    )
    return table


def test_run_refuses_an_ungated_tree_before_reading_the_table(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """No marker, no run — and the gate refusal comes first.

    The table path names no file, so a run that reached ``load_table`` would
    refuse with reason ``table``. Seeing ``gate`` instead is what proves the
    lockfile is checked before anything else is read.
    """
    tree = _repo_tree(tmp_path)
    rc = mutate.main(["run", "--table", str(tmp_path / "absent.toml"), "--tree", str(tree)])
    assert rc == 2
    err = capsys.readouterr().err
    assert "refused (gate)" in err, err
    assert "scripts/verify.sh" in err, (
        f"the refusal must name the remedy — running the gate — but said: {err!r}"
    )


def test_a_fresh_marker_admits_the_run(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """With a fresh marker over the exact tree, the gate refusal steps aside.

    The same missing-table fixture now refuses on the *table* — the next rung —
    which distinguishes "admitted past the lock" from "aborted for its own
    reason".
    """
    tree = _repo_tree(tmp_path)
    gate_marker.write_marker(tree)
    rc = mutate.main(["run", "--table", str(tmp_path / "absent.toml"), "--tree", str(tree)])
    assert rc == 2
    err = capsys.readouterr().err
    assert "refused (table)" in err, err
    assert "refused (gate)" not in err


def test_a_stale_marker_is_refused(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A marker past the freshness bound is no marker — the hooks' own rule."""
    tree = _repo_tree(tmp_path)
    marker = gate_marker.write_marker(tree)
    expired = marker.stat().st_mtime - gate_marker.max_age_seconds(os.environ) - 60
    os.utime(marker, (expired, expired))
    rc = mutate.main(["run", "--table", str(tmp_path / "absent.toml"), "--tree", str(tree)])
    assert rc == 2
    err = capsys.readouterr().err
    assert "refused (gate)" in err, err
    assert "stale" in err, f"a stale marker must be named as stale, not merely absent: {err!r}"


def test_an_edit_after_the_marker_is_refused(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The marker binds to the exact bytes: one more edit invalidates it."""
    tree = _repo_tree(tmp_path)
    gate_marker.write_marker(tree)
    (tree / "code.py").write_text("VALUE = 3\n")
    rc = mutate.main(["run", "--table", str(tmp_path / "absent.toml"), "--tree", str(tree)])
    assert rc == 2
    assert "refused (gate)" in capsys.readouterr().err


def test_check_mode_needs_no_marker(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """``check`` writes nothing and runs nothing, so it is not behind the lock."""
    tree = _repo_tree(tmp_path)
    table = _landing_table(tmp_path)
    rc = mutate.main(["check", "--table", str(table), "--tree", str(tree)])
    out = capsys.readouterr()
    assert rc == 0, out.err
    assert "table ok" in out.out


def test_a_tree_outside_any_repository_is_refused_as_ungated(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """No repository means no marker convention to answer for the tree.

    Refused with the same ``gate`` reason rather than crashing: not being a
    repository is a fact about the tree, not an infrastructure failure.
    """
    bare = tmp_path / "not-a-repo"
    bare.mkdir()
    rc = mutate.main(["run", "--table", str(tmp_path / "absent.toml"), "--tree", str(bare)])
    assert rc == 2
    assert "refused (gate)" in capsys.readouterr().err
