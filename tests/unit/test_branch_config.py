"""``harness.branch_config`` — read the repo's branch model from CONTEXT.md.

CAL-1106 stops the engine hardcoding this repo's ``dev``/``main``/``master`` into
what should be a generic scaffold. The base a run builds off, and the base a
merged worktree is reclaimed against, both read ``branches.integration`` from the
target repo's CONTEXT.md instead. This locks the reader, including the block
scoping that keeps a same-named key in another block from leaking in.
"""

from __future__ import annotations

from pathlib import Path

from harness.branch_config import integration_branch

# A CONTEXT.md whose ``branches:`` block sets a non-default integration branch,
# with a same-named ``integration:`` decoy nested under an unrelated block to
# prove block scoping resolves ``branches:`` first.
_CONTEXT = """\
# How work happens here

repo:
  name: acme
branches:
  integration: trunk    # feature branches base from here
  staging: staging
  release: main
policy:
  integration: everything   # decoy — must not be read as the branch
"""


def _write(tmp_path: Path, text: str) -> Path:
    (tmp_path / "CONTEXT.md").write_text(text)
    return tmp_path


def test_reads_the_integration_branch(tmp_path: Path) -> None:
    """``branches.integration`` yields the branch, stripped of its comment."""
    assert integration_branch(_write(tmp_path, _CONTEXT)) == "trunk"


def test_decoy_in_another_block_is_not_read(tmp_path: Path) -> None:
    """An ``integration:`` under a different top-level block must not leak in —
    block scoping resolves the ``branches:`` block first (the load-bearing case)."""
    assert integration_branch(_write(tmp_path, _CONTEXT)) == "trunk"


def test_missing_context_md_returns_none(tmp_path: Path) -> None:
    """No CONTEXT.md → the reader degrades to ``None`` (never raises)."""
    assert integration_branch(tmp_path) is None


def test_absent_key_returns_none(tmp_path: Path) -> None:
    """A ``branches:`` block without ``integration:`` returns ``None``."""
    text = "branches:\n  release: main\n"
    assert integration_branch(_write(tmp_path, text)) is None


def test_no_branches_block_returns_none(tmp_path: Path) -> None:
    """A CONTEXT.md with no ``branches:`` block at all returns ``None``."""
    text = "repo:\n  name: acme\n"
    assert integration_branch(_write(tmp_path, text)) is None


def test_quoted_value_is_unwrapped(tmp_path: Path) -> None:
    """A quoted value has its surrounding quotes stripped."""
    text = 'branches:\n  integration: "develop"\n'
    assert integration_branch(_write(tmp_path, text)) == "develop"
