"""#494 / #500 — the nested-worktree check runs before expensive gate stages.

Admission (ADR 0017 D5): class (a) — the shipped ``scripts/verify.sh`` is
**executed**, and the assertions are its exit code, its diagnostic, and the order
in which it launched real binaries. Nothing here reads the shell's text.

#500 moved the preflight from ``uv run … python scripts/gate_marker.py`` to a
bare ``node scripts/gate-marker.js``. The obvious rewrite — keep the ``uv``
recorder and assert it recorded nothing — is the #467 class one level worse: an
empty list over a stubbed binary is constant-true, and it would also pass if the
stub were never installed at all.

So both binaries are recorded into **one shared log**, the mechanism
``tests/unit/test_promotion_step_script.py`` already uses, with the difference
this subject forces: the ``node`` shim records and then ``exec``s the *real*
node, because the preflight has to actually run. Order is then a property of one
list rather than an inference across two.

Two runs over the same fixture, differing in exactly one variable — whether
``.worktrees/`` is ignored:

* :func:`test_a_visible_nested_worktree_is_refused_before_any_uv_stage` (Run A)
  — the refusal, and the absence of any ``uv`` line.
* :func:`test_the_preflight_precedes_the_first_uv_stage` (Run B) — **the floor**.
  It proves the recorder can see ``uv`` lines at all, so Run A's absence is an
  observation rather than an empty corpus, and it states the ordering
  *positively*, so an implementation that moved the preflight below the expensive
  stages fails here even if Run A somehow still refused. Run B's exit code is
  deliberately not asserted: the ``uv`` shim's ``shift 4`` trick survives only a
  couple of stage shapes, and what Run B measures is the log, not a verdict.

The fixture is written out of the **git index** — ``verify.sh``,
``gate-marker.js`` and ``package.json`` — which is also a free assertion that
those three files are enough for a consumer to run the preflight. Index-reading
puts this module outside ``scripts/mutate.py``'s reach; its mutations are proved
by staged probe (#490).
"""

from __future__ import annotations

import os
import re
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from tests._gitutil import indexed_text

#: The preflight line the shared log must carry. Anchored on the subcommand, not
#: merely on the file name, so a direct retired marker-write command would not
#: satisfy it.
PREFLIGHT_LINE = re.compile(r"^node .*gate-marker\.js preflight$")


def _node() -> str:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node not available")
    return node


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=repo, check=True, capture_output=True, text=True
    ).stdout.strip()


def _fixture(tmp_path: Path) -> Path:
    """A repository carrying the three shipped files a preflight needs."""
    root = tmp_path / "repo"
    (root / "scripts").mkdir(parents=True)
    for relative in ("scripts/verify.sh", "scripts/gate-marker.js", "scripts/package.json"):
        (root / relative).write_text(indexed_text(relative), encoding="utf-8")
    _git(root, "init", "-q", "--initial-branch=dev")
    _git(root, "config", "user.email", "t@example.com")
    _git(root, "config", "user.name", "t")
    (root / "a.txt").write_text("one\n")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "base")
    return root


def _recorders(tmp_path: Path) -> tuple[Path, Path]:
    """A ``bin`` dir whose ``node`` and ``uv`` append to one shared log.

    ``node`` records and then hands off to the real binary: the preflight is a
    node invocation now, and a stub that merely recorded would leave this module
    asserting the order of two things that never ran.
    """
    bindir = tmp_path / "bin"
    bindir.mkdir()
    log = tmp_path / "invocations"
    node = bindir / "node"
    node.write_text(
        "#!/bin/sh\n"
        f"printf 'node %s\\n' \"$*\" >> {shlex.quote(str(log))}\n"
        f'exec {shlex.quote(_node())} "$@"\n'
    )
    node.chmod(0o755)
    uv = bindir / "uv"
    uv.write_text(
        "#!/bin/sh\n"
        f"printf 'uv %s\\n' \"$*\" >> {shlex.quote(str(log))}\n"
        "shift 4\n"
        f'exec {shlex.quote(sys.executable)} "$@"\n'
    )
    uv.chmod(0o755)
    return bindir, log


def _run_gate(root: Path, bindir: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["/bin/bash", "scripts/verify.sh"],
        cwd=root,
        env={**os.environ, "PATH": f"{bindir}{os.pathsep}{os.environ['PATH']}"},
        capture_output=True,
        text=True,
        timeout=120,
    )


def _lines(log: Path) -> list[str]:
    return log.read_text().splitlines() if log.exists() else []


def _index_of(lines: list[str], pattern: re.Pattern[str]) -> int:
    for index, line in enumerate(lines):
        if pattern.match(line):
            return index
    return -1


# --- Run A: the refusal --------------------------------------------------------


def test_a_visible_nested_worktree_is_refused_before_any_uv_stage(tmp_path: Path) -> None:
    """The live verify script maps this infrastructure failure to exit 97.

    The negative half — no ``uv`` line anywhere — is only meaningful beside Run B,
    which proves the same recorder does see ``uv`` lines when the gate reaches
    them.
    """
    root = _fixture(tmp_path)
    nested = root / ".worktrees" / "agent"
    _git(root, "worktree", "add", "-q", "-b", "task/agent", str(nested))
    bindir, log = _recorders(tmp_path)

    proc = _run_gate(root, bindir)

    assert proc.returncode == 97, f"stdout={proc.stdout!r} stderr={proc.stderr!r}"
    assert str(nested) in proc.stderr
    lines = _lines(log)
    assert _index_of(lines, PREFLIGHT_LINE) != -1, (
        f"scripts/verify.sh never ran `node …/gate-marker.js preflight`: {lines}"
    )
    assert [line for line in lines if line.startswith("uv ")] == [], (
        "an expensive `uv`-launched stage ran despite the refusal, so the "
        f"preflight is not before them: {lines}"
    )
    common = Path(_git(root, "rev-parse", "--path-format=absolute", "--git-common-dir"))
    assert not (common / "harness" / "gate").exists(), (
        "the refused preflight materialised the marker directory, so it ran "
        "after the tree computation rather than before it"
    )


# --- Run B: the floor and the positive ordering --------------------------------


def test_the_preflight_precedes_the_first_uv_stage(tmp_path: Path) -> None:
    """The control: the same fixture with ``.worktrees/`` ignored.

    Two jobs. It floors Run A — a recorder that never sees a ``uv`` line makes
    Run A's absence assertion constant-true — and it states AC-5 positively, so
    an implementation that ran the preflight *after* the expensive stages fails
    here.

    The exit code is deliberately unasserted: this fixture's ``uv`` shim cannot
    satisfy every stage of a real gate, and the property under test is the order
    of the launches, not the gate's verdict.
    """
    root = _fixture(tmp_path)
    (root / ".gitignore").write_text(".worktrees/\n")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "ignore worktrees")
    nested = root / ".worktrees" / "agent"
    _git(root, "worktree", "add", "-q", "-b", "task/agent", str(nested))
    bindir, log = _recorders(tmp_path)

    _run_gate(root, bindir)

    lines = _lines(log)
    preflight = _index_of(lines, PREFLIGHT_LINE)
    first_uv = next(
        (index for index, line in enumerate(lines) if line.startswith("uv ")), -1
    )

    assert preflight != -1, f"no preflight invocation was recorded: {lines}"
    assert first_uv != -1, (
        "no `uv` stage ran at all, so Run A's absence assertion is an empty "
        f"corpus rather than an observation: {lines}"
    )
    assert preflight < first_uv, (
        "scripts/verify.sh launched a `uv` stage before the nested-worktree "
        f"preflight, so the check no longer guards the expensive half: {lines}"
    )
