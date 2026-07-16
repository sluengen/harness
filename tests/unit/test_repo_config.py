"""``harness.repo_config`` — read the ``repo:`` identity keys from CONTEXT.md.

The escalation path (CAL-1118) resolves its Linear team + project from
``CONTEXT.md`` so an orchestrator need not thread them by hand. This locks the two
readers, including the block-scoping that keeps the ``layers.linear`` *switch*
from being misread as the ``repo.linear`` *team key* (the same ambiguity
``test_layers.py`` guards from the other side).
"""

from __future__ import annotations

from pathlib import Path

from harness.repo_config import repo_linear_team, repo_project

# A CONTEXT.md where ``linear:`` appears twice — the team key under ``repo:`` and
# the on/off switch under ``layers:`` — and ``project:`` carries an internal space
# and a trailing comment.
_CONTEXT = """\
# How work happens here

repo:
  name: harness
  linear: CAL   # team prefix — Calibrate-coffee (CAL)
  project: Harness v3   # the project the routines pull from
layers:
  linear: true

tools:
  verify: "bash scripts/verify.sh"
"""


def _write(tmp_path: Path, text: str) -> Path:
    (tmp_path / "CONTEXT.md").write_text(text)
    return tmp_path


def test_reads_the_team_key(tmp_path: Path) -> None:
    """``repo.linear`` yields the team key, stripped of its trailing comment."""
    assert repo_linear_team(_write(tmp_path, _CONTEXT)) == "CAL"


def test_reads_a_project_name_with_spaces(tmp_path: Path) -> None:
    """``repo.project`` keeps an internal space (a bare ``\\S+`` grab would truncate)."""
    assert repo_project(_write(tmp_path, _CONTEXT)) == "Harness v3"


def test_layers_switch_is_not_read_as_the_team_key(tmp_path: Path) -> None:
    """The ``linear: true`` under ``layers:`` must not leak in as the team key —
    block scoping resolves the ``repo:`` block first (the load-bearing case)."""
    assert repo_linear_team(_write(tmp_path, _CONTEXT)) == "CAL"


def test_missing_context_md_returns_none(tmp_path: Path) -> None:
    """No CONTEXT.md → both readers degrade to ``None`` (never raise)."""
    assert repo_linear_team(tmp_path) is None
    assert repo_project(tmp_path) is None


def test_absent_key_returns_none(tmp_path: Path) -> None:
    """A ``repo:`` block without the key returns ``None`` for that key."""
    text = "repo:\n  name: harness\n"
    assert repo_linear_team(_write(tmp_path, text)) is None
    assert repo_project(_write(tmp_path, text)) is None


def test_quoted_value_is_unwrapped(tmp_path: Path) -> None:
    """A quoted value has its surrounding quotes stripped."""
    text = 'repo:\n  project: "Harness v3"\n'
    assert repo_project(_write(tmp_path, text)) == "Harness v3"
