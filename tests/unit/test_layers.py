"""The ``layers:`` reader — CAL-1104.

``CONTEXT.md`` advertises ``layers.linear: false`` for a repo not wired to a
tracker. These tests pin the reader that honours it, and above all the one thing
a naive regex gets wrong: **``linear:`` appears twice** in a real CONTEXT.md —
once under ``repo:`` as the team prefix (``linear: CAL``) and once under
``layers:`` as the switch. An unscoped match reads the team prefix and silently
ignores the switch, so every case below that mixes the two is load-bearing.
"""

from __future__ import annotations

from pathlib import Path

from harness.layers import linear_enabled

# The shape of a real CONTEXT.md: ``repo.linear`` (team prefix) sits *above*
# ``layers.linear`` (the switch), so an unscoped ``linear:`` search hits the
# prefix first. This is the harness's own file, trimmed.
_BOTH_KEYS = """\
repo:
  name: harness
  linear: CAL   # team prefix
  project: Harness v3
layers:
  linear: {switch}
  design_system: false
stack:
  language: Python 3.11+
"""


def _write(tmp_path: Path, text: str) -> Path:
    (tmp_path / "CONTEXT.md").write_text(text)
    return tmp_path


def test_layers_linear_false_disables_the_tracker(tmp_path: Path) -> None:
    """An explicit ``layers.linear: false`` turns the layer off."""
    root = _write(tmp_path, "layers:\n  linear: false\n")
    assert linear_enabled(root) is False


def test_layers_linear_true_keeps_the_tracker_on(tmp_path: Path) -> None:
    root = _write(tmp_path, "layers:\n  linear: true\n")
    assert linear_enabled(root) is True


def test_repo_linear_prefix_does_not_mask_the_layers_switch(tmp_path: Path) -> None:
    """The trap: ``repo.linear: CAL`` precedes ``layers.linear: false``.

    An unscoped ``^\\s*linear:`` search matches the team prefix ``CAL`` — which is
    not ``false`` — and reports the layer *on* while CONTEXT.md plainly turns it
    off. The reader must scope to the ``layers:`` block.
    """
    root = _write(tmp_path, _BOTH_KEYS.format(switch="false"))
    assert linear_enabled(root) is False


def test_repo_linear_none_does_not_disable_a_layer_that_is_on(tmp_path: Path) -> None:
    """The mirror trap: ``repo.linear: none`` must not turn off an on layer.

    ``layers.linear`` is the single switch the engine reads; the team-prefix
    field is not a second source of truth.
    """
    root = _write(
        tmp_path,
        "repo:\n  linear: none\nlayers:\n  linear: true\n",
    )
    assert linear_enabled(root) is True


def test_missing_context_file_defaults_to_on(tmp_path: Path) -> None:
    """No CONTEXT.md → the layer is on, so an unconfigured repo behaves as today."""
    assert linear_enabled(tmp_path) is True


def test_missing_layers_block_defaults_to_on(tmp_path: Path) -> None:
    root = _write(tmp_path, "repo:\n  name: harness\n  linear: CAL\n")
    assert linear_enabled(root) is True


def test_layers_block_without_a_linear_key_defaults_to_on(tmp_path: Path) -> None:
    root = _write(tmp_path, "layers:\n  design_system: false\n")
    assert linear_enabled(root) is True


def test_trailing_comment_is_ignored(tmp_path: Path) -> None:
    """The harness's own CONTEXT.md comments its layer keys."""
    root = _write(
        tmp_path,
        "layers:\n  linear: false   # this repo is not on a tracker\n",
    )
    assert linear_enabled(root) is False


def test_a_later_top_level_key_ends_the_layers_block(tmp_path: Path) -> None:
    """A ``linear:`` under a *later* top-level block is not the layers switch."""
    root = _write(
        tmp_path,
        "layers:\n  design_system: false\ntools:\n  linear: false\n",
    )
    assert linear_enabled(root) is True


def test_only_an_explicit_false_turns_the_layer_off(tmp_path: Path) -> None:
    """An unrecognised value is not an off switch — the default is conservative."""
    root = _write(tmp_path, "layers:\n  linear: maybe\n")
    assert linear_enabled(root) is True


def test_the_harness_own_context_reports_the_layer_on() -> None:
    """The repo under test is on Linear; the reader agrees with its CONTEXT.md."""
    assert linear_enabled(Path(__file__).resolve().parents[2]) is True
