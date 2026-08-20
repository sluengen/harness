"""#494 — the nested-worktree check runs before expensive gate stages."""

from __future__ import annotations

import os
import shlex
import subprocess
import sys
from pathlib import Path

from tests._gitutil import indexed_text


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=repo, check=True, capture_output=True, text=True
    ).stdout.strip()


def test_visible_registered_nested_worktree_is_unrunnable_before_expensive_stages(
    tmp_path: Path,
) -> None:
    """The live verify script maps this infrastructure failure to exit 97."""
    root = tmp_path / "repo"
    (root / "scripts").mkdir(parents=True)
    (root / "scripts" / "verify.sh").write_text(
        indexed_text("scripts/verify.sh"), encoding="utf-8"
    )
    (root / "scripts" / "gate_marker.py").write_text(
        indexed_text("scripts/gate_marker.py"), encoding="utf-8"
    )
    _git(root, "init", "-q", "--initial-branch=dev")
    _git(root, "config", "user.email", "t@example.com")
    _git(root, "config", "user.name", "t")
    (root / "a.txt").write_text("one\n")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "base")
    nested = root / ".worktrees" / "agent"
    _git(root, "worktree", "add", "-q", "-b", "task/agent", str(nested))

    bindir = tmp_path / "bin"
    bindir.mkdir()
    invocations = tmp_path / "uv-invocations"
    uv = bindir / "uv"
    uv.write_text(
        "#!/bin/sh\n"
        f"printf '%s\\n' \"$*\" >> {shlex.quote(str(invocations))}\n"
        "shift 4\n"
        f'exec {shlex.quote(sys.executable)} "$@"\n'
    )
    uv.chmod(0o755)

    proc = subprocess.run(
        ["/bin/bash", "scripts/verify.sh"],
        cwd=root,
        env={**os.environ, "PATH": f"{bindir}{os.pathsep}{os.environ['PATH']}"},
        capture_output=True,
        text=True,
        timeout=60,
    )

    assert proc.returncode == 97
    assert str(nested) in proc.stderr
    assert invocations.read_text().splitlines() == [
        "run --extra dev python scripts/gate_marker.py preflight"
    ]
    common = Path(_git(root, "rev-parse", "--path-format=absolute", "--git-common-dir"))
    assert not (common / "harness" / "gate").exists()
