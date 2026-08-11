"""The nightly promotion's exported allowlist admits its own ``--repo`` argument (#390).

Every verb resolves ``--repo`` through :mod:`harness.workspace`, which fails
closed — ``HARNESS_WORKSPACE_ROOTS`` unset means *no* allowed roots, so every
candidate is refused and the CLI exits 2. On a developer's box the Docker wrapper
(``~/bin/harness``) pins that allowlist; an Actions runner has no wrapper, so the
promotion has to pin it itself.

So this module executes the promotion's own export line under ``bash``, in an
environment scrubbed of ``HARNESS_WORKSPACE_ROOTS``, and feeds the two values it
produces — the allowlist, and the expansion of the ``--repo`` argument — to the
production :func:`~harness.workspace.resolve_repo_root`. Restating the allowlist
rule in the test would assert nothing about the code that enforces it.

Only the ``export`` lines are executed, never the whole file: the rest of it
spawns real ``harness promote`` verbs against real branches. The whole file *is*
executed, against stubbed verbs, by
``tests/integration/test_promotion_step_script.py`` (#396) — which is also where
ordering is now claimed, because recording the allowlist each verb actually saw
makes "the export precedes the first call" an executed property rather than a
textual one.

Its source moved in #396 and nothing else did: the promotion's shell now lives in
``scripts/promotion-step.sh`` rather than in a workflow ``run:`` block, so the
locator is a file read instead of a YAML walk.
"""

import os
import subprocess
from pathlib import Path

import pytest

from harness.workspace import WORKSPACE_ROOTS_ENV, WorkspaceNotAllowed, resolve_repo_root

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "promotion-step.sh"


def _promotion_step_lines() -> list[str]:
    """The promotion's shell, as the lines bash receives them.

    A file read rather than the YAML walk this was until #396: no step lookup, no
    ``run: |`` lookup, no dedent. The floor that used to be those lookups' error
    messages is now :func:`test_the_promotion_step_script_is_where_the_shell_lives`.
    """
    return SCRIPT.read_text(encoding="utf-8").splitlines()


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
    """The promotion's export makes its ``--repo`` argument resolve to the checkout."""
    block = _promotion_step_lines()
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
    full = _promotion_step_lines()
    block = [line for line in full if not line.startswith("export ")]
    assert len(block) < len(full), "nothing was stripped, so this controls for nothing"

    roots, expanded = _exported_allowlist_and_repo_argument(block, workspace)
    assert roots == "", "the export was meant to be stripped from the control"

    monkeypatch.chdir(tmp_path)
    with pytest.raises(WorkspaceNotAllowed):
        resolve_repo_root(expanded, {WORKSPACE_ROOTS_ENV: roots})


# --- The locator's floor (#396) -----------------------------------------------
#
# The YAML walk this module used to do asserted its own two lookups, so a renamed
# step failed by name. A file read has one way to go wrong, and this is it: name
# the path, so a rename costs the next author a sentence rather than an
# unexplained `FileNotFoundError` from inside a helper.


def test_the_promotion_step_script_is_where_the_shell_lives() -> None:
    """The source every test above reads exists and is not empty.

    Without this, moving or emptying the script would fail the two tests above
    from inside a helper, naming nothing — and an *empty* file would fail their
    export floor as though the export had been deleted, which is a different
    defect calling for different work.
    """
    assert SCRIPT.is_file(), (
        f"{SCRIPT.relative_to(REPO_ROOT)} is where the nightly promotion's shell lives "
        "(#396); if it moved, move this locator with it"
    )
    assert SCRIPT.read_text(encoding="utf-8").strip(), (
        f"{SCRIPT.relative_to(REPO_ROOT)} is empty, so every assertion in this module "
        "would be measuring nothing"
    )


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
