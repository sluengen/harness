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


def _promotion_run_block(lines: list[str]) -> list[str]:
    """The promotion step's ``run:`` block, dedented to the lines bash receives.

    Both lookups assert rather than ``next(...)`` bare: a renamed step used to
    raise ``StopIteration`` naming nothing, leaving whoever renamed it to work
    out from scratch what this module had been looking for (#391).
    """
    steps = [i for i, line in enumerate(lines) if line.strip() == _STEP]
    assert steps, f"the workflow has no step whose name is {_STEP!r} — renamed or removed?"
    step = steps[0]
    runs = [i for i in range(step, len(lines)) if lines[i].strip() == "run: |"]
    assert runs, f"the step {_STEP!r} has no `run: |` block to read the export out of"
    run = runs[0]
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
    # The bound check is not defensive padding: `--repo` may legally be the last
    # token on a line, its argument folded onto the next one (#391). This helper
    # only ever needs one argument to expand, so it takes an unwrapped one and
    # says so plainly rather than raising IndexError from inside a comprehension.
    repo_arguments = [
        parts[index + 1]
        for line in block
        if "--repo" in (parts := line.split()) and (index := parts.index("--repo")) + 1 < len(parts)
    ]
    assert repo_arguments, "no line in the promotion block passes --repo an argument to expand"
    repo_argument = repo_arguments[0]
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
    block = _promotion_run_block(WORKFLOW.read_text(encoding="utf-8").splitlines())
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
    full = _promotion_run_block(WORKFLOW.read_text(encoding="utf-8").splitlines())
    block = [line for line in full if not line.startswith("export ")]
    assert len(block) < len(full), "nothing was stripped, so this controls for nothing"

    roots, expanded = _exported_allowlist_and_repo_argument(block, workspace)
    assert roots == "", "the export was meant to be stripped from the control"

    monkeypatch.chdir(tmp_path)
    with pytest.raises(WorkspaceNotAllowed):
        resolve_repo_root(expanded, {WORKSPACE_ROOTS_ENV: roots})


# --- The locators say what they were looking for (#391) -----------------------
#
# These read no real workflow. They pin that the two lookups above fail with a
# message naming their target, so renaming the step in the workflow costs the
# next author a sentence rather than a bare `StopIteration` traceback.


def test_a_missing_promotion_step_names_the_step_it_looked_for() -> None:
    """AC-4: a renamed or removed step is named, not reported as StopIteration."""
    with pytest.raises(AssertionError) as refused:
        _promotion_run_block(
            ["      - name: Promote something else", "        run: |", "          true"]
        )

    assert _STEP in str(refused.value)


def test_a_promotion_step_with_no_run_block_names_what_was_missing() -> None:
    """AC-4: the second lookup explains itself the same way the first does."""
    with pytest.raises(AssertionError) as refused:
        _promotion_run_block([f"      {_STEP}", "        uses: actions/checkout@v4"])

    assert "run: |" in str(refused.value)


def test_a_block_whose_repo_argument_is_wrapped_says_so(workspace: Path) -> None:
    """A `--repo` folded onto the next line leaves nothing to expand, and says which."""
    with pytest.raises(AssertionError) as refused:
        _exported_allowlist_and_repo_argument(
            [
                'export HARNESS_WORKSPACE_ROOTS="$GITHUB_WORKSPACE"',
                "uv run harness promote pr --repo",
            ],
            workspace,
        )

    assert "--repo" in str(refused.value)
