"""The nightly promotion's exported allowlist admits its own ``--repo`` argument (#390).

Its sibling ``tests/unit/test_nightly_promotion_workflow.py`` is a text guard: it
can show the workflow *says* something, never that the thing it says works. Every
verb resolves ``--repo`` through :mod:`harness.workspace`, which fails closed —
``HARNESS_WORKSPACE_ROOTS`` unset means *no* allowed roots, so every candidate is
refused and the CLI exits 2. On a developer's box the Docker wrapper
(``~/bin/harness``) pins that allowlist; an Actions runner has no wrapper, so the
workflow has to pin it itself.

So this module executes the workflow's own export line under ``bash``, in an
environment scrubbed of ``HARNESS_WORKSPACE_ROOTS``, and feeds the two values it
produces — the allowlist, and the expansion of the ``--repo`` argument — to the
production :func:`~harness.workspace.resolve_repo_root`. Restating the allowlist
rule in the test would assert nothing about the code that enforces it.

Only the ``export`` lines are executed, never the whole block: the rest of it
spawns real ``harness promote`` verbs against real branches. That is why *ordering*
— the export preceding the first verb call — belongs to the text guard, which can
see the whole block, and is not claimed here.
"""

import os
import subprocess
import textwrap
from pathlib import Path

import pytest

from harness.workspace import WORKSPACE_ROOTS_ENV, WorkspaceNotAllowed, resolve_repo_root

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "nightly-staging-promotion.yml"

#: The step whose ``run:`` block holds the export and every verb call.
_STEP = "- name: Promote the gated candidate"


def _promotion_run_block() -> list[str]:
    """The promotion step's ``run:`` block, dedented to the lines bash receives."""
    lines = WORKFLOW.read_text(encoding="utf-8").splitlines()
    step = next(i for i, line in enumerate(lines) if line.strip() == _STEP)
    run = next(i for i in range(step, len(lines)) if lines[i].strip() == "run: |")
    indent = len(lines[run]) - len(lines[run].lstrip())
    body: list[str] = []
    for line in lines[run + 1 :]:
        if line.strip() and len(line) - len(line.lstrip()) <= indent:
            break
        body.append(line)
    return textwrap.dedent("\n".join(body)).splitlines()


def _exported_allowlist_and_repo_argument(
    block: list[str], workspace: Path
) -> tuple[str, str]:
    """Run ``block``'s exports under bash and read back both values it decides.

    The environment is scrubbed of ``HARNESS_WORKSPACE_ROOTS`` so the value read
    back can only have come from the workflow, and ``GITHUB_WORKSPACE`` points at
    ``workspace`` the way the runner points it at the checkout.
    """
    exports = [line for line in block if line.startswith("export ")]
    repo_argument = next(
        parts[parts.index("--repo") + 1]
        for line in block
        if "--repo" in (parts := line.split())
    )
    script = "\n".join(
        [
            *exports,
            f'printf "%s\\n" "${{{WORKSPACE_ROOTS_ENV}-}}"',
            f'printf "%s\\n" {repo_argument}',
        ]
    )
    env = {**os.environ, "GITHUB_WORKSPACE": str(workspace)}
    env.pop(WORKSPACE_ROOTS_ENV, None)
    result = subprocess.run(
        ["bash", "-c", script], env=env, capture_output=True, text=True, check=True
    )
    roots, expanded = result.stdout.split("\n")[:2]
    return roots, expanded


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    """A stand-in for ``GITHUB_WORKSPACE``.

    ``is_git_top_level`` only stats for a ``.git`` entry (it must accept a linked
    worktree, whose ``.git`` is a file), so no real repository is needed.
    """
    root = tmp_path / "workspace"
    root.mkdir()
    (root / ".git").touch()
    return root


def test_the_exported_allowlist_admits_the_workflows_own_repo_argument(
    workspace: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The workflow's export makes its ``--repo`` argument resolve to the checkout."""
    block = _promotion_run_block()
    assert [line for line in block if line.startswith("export ")], (
        "the promotion step exports nothing, so there is no allowlist to test"
    )

    roots, expanded = _exported_allowlist_and_repo_argument(block, workspace)
    assert roots, f"the promotion step left {WORKSPACE_ROOTS_ENV} empty — the deny-all state"

    # Resolve from a directory that is *not* the workspace: the argument has to
    # name the allowlisted root outright, not inherit it from the process cwd.
    monkeypatch.chdir(tmp_path)
    assert resolve_repo_root(expanded, {WORKSPACE_ROOTS_ENV: roots}) == workspace.resolve()


def test_without_the_export_the_same_argument_is_refused(
    workspace: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Negative control: the allowlist, not the argument, is what admits the path."""
    full = _promotion_run_block()
    block = [line for line in full if not line.startswith("export ")]
    assert len(block) < len(full), "nothing was stripped, so this controls for nothing"

    roots, expanded = _exported_allowlist_and_repo_argument(block, workspace)
    assert roots == "", "the export was meant to be stripped from the control"

    monkeypatch.chdir(tmp_path)
    with pytest.raises(WorkspaceNotAllowed):
        resolve_repo_root(expanded, {WORKSPACE_ROOTS_ENV: roots})
