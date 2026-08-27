"""#473 / #500 — mutate's first refusal is the tree-keyed lockfile.

Admission (ADR 0017 D5): class (a) — executable behaviour of ``scripts/mutate.py``.

A mutation run's verdicts are only meaningful over a tree the gate has passed:
the harness's own green-baseline refusal proves the *selection* runs clean, but
nothing proved the whole gate had — so a table could be run, and its report
cited, over a tree that lint, types, or the unselected half of the suite would
have refused. The gate already writes the artifact that says otherwise:
``scripts/verify.sh`` records ``<git-common-dir>/harness/gate/<tree-oid>.json``
via ``scripts/gate-marker.js``, and the enforcement hooks read that same
convention. mutate reuses it rather than growing a second one.

**#500 changed how it reaches it, not what it decides.** The convention moved
into Node (ADR 0018), so mutate no longer imports a sibling Python module: it
makes exactly one read-only subprocess query — ``node scripts/gate-marker.js
status``, three facts and no verdict — and composes its own three refusals from
the answer. The alternative was a Python re-implementation of the freshness
parse, which would have been a **fourth** parser of
``HARNESS_GATE_MARKER_MAX_AGE_SECONDS`` and the only one no equivalence test
covers. The spawn is held to that exact argv shape by
``tests/unit/test_mutate.py::test_the_module_spawns_only_this_interpreter_and_one_read_only_query``.

The contract, each direction its own test:

* ``run`` against a tree no fresh marker covers is **refused before anything
  else** — before the table is even read, which is what "first refusal" means and
  what the missing-table fixture proves; nothing is written (exit 2, the standing
  refusal convention).
* a **fresh marker admits the run**: the same missing-table fixture now refuses
  on the *table*, proving the gate refusal stepped aside rather than the run
  aborting for its own reason.
* a **stale marker is no marker** — the freshness bound is the hooks' own
  (``HARNESS_GATE_MARKER_MAX_AGE_SECONDS``, default a day), read out of the
  helper's ``status`` so a fourth parser cannot drift.
* the bound **crosses the process boundary**: a caller-supplied environment
  reaches the helper, which is the one thing the new architecture could silently
  get wrong.
* the helper, not mutate, is the **oracle** for tree and marker path.
* a host without a runnable ``node`` is **infrastructure** (exit 3), never a
  refusal: ``RefusalError(reason="gate")`` is a fact about the tree, and a
  missing node says nothing about the tree.
* ``check`` needs no marker: it writes nothing and runs nothing, and a table
  author must be able to get a table to land before spending a gate run.

The fixture is a real repository — the marker convention keys on the git common
directory and the tree oid, so nothing less would exercise the real path — and
the marker is written by ``node scripts/gate-marker.js run`` itself, the same
runner the gate delegates to, so the two computations of "the current tree" cannot drift
apart in this module's favour.
"""

from __future__ import annotations

import json
import os
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from tests.unit._gate_marker_runner import install_internal_gate
from tests.unit._prose import REPO_ROOT

sys.path.insert(0, str(REPO_ROOT / "scripts"))

import mutate  # noqa: E402

HELPER = REPO_ROOT / "scripts" / "gate-marker.js"


def _node() -> str:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node not available")
    return node


def _helper(tree: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [_node(), str(HELPER), *args], cwd=tree, capture_output=True, text=True, timeout=60
    )


def _write_marker(tree: Path) -> Path:
    """Produce a marker through the production runner and return its path."""
    install_internal_gate(tree)
    proc = _helper(tree, "run")
    assert proc.returncode == 0, proc.stderr
    return Path(proc.stdout.split("->", 1)[1].strip())


def _default_bound(tree: Path) -> int:
    """The helper's own default bound, read from it rather than restated."""
    proc = _helper(tree, "status")
    assert proc.returncode == 0, proc.stderr
    return int(json.loads(proc.stdout)["max_age_seconds"])


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
    _write_marker(tree)
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
    marker = _write_marker(tree)
    expired = marker.stat().st_mtime - _default_bound(tree) - 60
    os.utime(marker, (expired, expired))
    rc = mutate.main(["run", "--table", str(tmp_path / "absent.toml"), "--tree", str(tree)])
    assert rc == 2
    err = capsys.readouterr().err
    assert "refused (gate)" in err, err
    assert "stale" in err, f"a stale marker must be named as stale, not merely absent: {err!r}"


def test_the_freshness_bound_crosses_the_process_boundary(tmp_path: Path) -> None:
    """The caller's environment reaches the helper, so the bound is one number.

    The whole reason the lock queries the helper instead of parsing
    ``HARNESS_GATE_MARKER_MAX_AGE_SECONDS`` itself is that a fourth parser would
    be the only one no equivalence test covers. That only holds if the variable
    actually crosses the boundary — a bound silently defaulted on the far side
    would leave the lock enforcing a day while the caller asked for a second, and
    every other test here would still pass.
    """
    tree = _repo_tree(tmp_path)
    marker = _write_marker(tree)
    aged = marker.stat().st_mtime - 10
    os.utime(marker, (aged, aged))

    with pytest.raises(mutate.RefusalError) as caught:
        mutate.check_gate_marker(
            tree, env={**os.environ, "HARNESS_GATE_MARKER_MAX_AGE_SECONDS": "1"}
        )

    assert caught.value.reason == "gate"
    assert "stale" in str(caught.value)
    # The control: the same ten-second-old marker under the default bound is
    # fresh, so the refusal above is the caller's bound and not the marker's age.
    assert mutate.check_gate_marker(tree, env={**os.environ}) == marker


def test_the_helper_is_the_oracle_for_the_tree_and_the_marker(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """mutate asks the helper where to look; it does not recompute the answer.

    Driven with a ``node`` shim whose ``status`` names a marker the test created
    somewhere the real convention would never look. If mutate still computed the
    path itself it would find nothing and refuse on the gate — which is exactly
    what it did before #500, and is this test's RED.

    Deliberately the only stubbed case in this module: everything else drives the
    shipped helper, so this isolates *who decides* without becoming a test of a
    stub.
    """
    tree = _repo_tree(tmp_path)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    marker = elsewhere / ("e" * 40 + ".json")
    marker.write_text("{}")
    payload = json.dumps({"tree": "e" * 40, "marker": str(marker), "max_age_seconds": 86400})
    bindir = tmp_path / "shim"
    bindir.mkdir()
    shim = bindir / "node"
    shim.write_text(f"#!/bin/sh\nprintf '%s\\n' {shlex.quote(payload)}\n")
    shim.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bindir}{os.pathsep}{os.environ['PATH']}")

    rc = mutate.main(["run", "--table", str(tmp_path / "absent.toml"), "--tree", str(tree)])

    assert rc == 2
    err = capsys.readouterr().err
    assert "refused (table)" in err, (
        f"mutate did not accept the helper's answer about where the marker is: {err!r}"
    )


def test_a_host_without_node_is_infrastructure_not_a_refusal(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """``RefusalError(reason="gate")`` is a fact about the tree. A host with no
    runnable node says nothing about the tree, so it is exit 3 — the same code an
    unrunnable pytest gets — and the message names what is missing.

    ``mutate check`` stays node-free, which the ``check`` case below pins.
    """
    tree = _repo_tree(tmp_path)
    _write_marker(tree)
    monkeypatch.setenv("PATH", str(tmp_path / "no-such-bin"))

    rc = mutate.main(["run", "--table", str(tmp_path / "absent.toml"), "--tree", str(tree)])

    assert rc == 3, "a missing node must not read as a refusal about the tree"
    err = capsys.readouterr().err
    assert "runner unavailable" in err, err
    assert "node" in err, f"the operator is not told what to install: {err!r}"


def test_an_edit_after_the_marker_is_refused(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The marker binds to the exact bytes: one more edit invalidates it."""
    tree = _repo_tree(tmp_path)
    _write_marker(tree)
    (tree / "code.py").write_text("VALUE = 3\n")
    rc = mutate.main(["run", "--table", str(tmp_path / "absent.toml"), "--tree", str(tree)])
    assert rc == 2
    assert "refused (gate)" in capsys.readouterr().err


def test_check_mode_needs_no_marker(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """``check`` writes nothing and runs nothing, so it is not behind the lock.

    Run with ``node`` off ``PATH`` as well, which states the second half of ADR
    0018's consequence: node is a precondition of ``run``, never of ``check``.
    """
    tree = _repo_tree(tmp_path)
    table = _landing_table(tmp_path)
    monkeypatch.setenv("PATH", str(tmp_path / "no-such-bin"))
    rc = mutate.main(["check", "--table", str(table), "--tree", str(tree)])
    out = capsys.readouterr()
    assert rc == 0, out.err
    assert "table ok" in out.out


def test_a_tree_outside_any_repository_is_refused_as_ungated(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """No repository means no marker convention to answer for the tree.

    Refused with the same ``gate`` reason rather than crashing, and rather than
    the infrastructure exit: not being a repository is a fact about the tree.
    """
    bare = tmp_path / "not-a-repo"
    bare.mkdir()
    rc = mutate.main(["run", "--table", str(tmp_path / "absent.toml"), "--tree", str(bare)])
    assert rc == 2
    assert "refused (gate)" in capsys.readouterr().err
