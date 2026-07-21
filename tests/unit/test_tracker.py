"""The ``tracker:`` single source of truth — CAL-1164.

CAL-1104 gave the engine a switch, ``layers.linear``, read by
:func:`harness.layers.linear_enabled`. But ``linear:`` then appeared *twice* in a
real ``CONTEXT.md`` — ``repo.linear`` (the address) and ``layers.linear`` (the
switch) — a derivable coupling nothing enforced, so ``repo.linear: none`` with
``layers.linear: true`` was a representable-but-contradictory state.

This ticket collapses the switch to one field: ``tracker: linear | github |
none``, the sole on/off-plus-backend fact. These tests pin the generalized
reader (:func:`harness.layers.tracker`), the preserved ``linear_enabled``
derivation, the ``layers.linear`` back-compat fallback, and the coherence check
(:func:`harness.layers.tracker_config_error`) that rejects an address/switch that
contradict.
"""

from __future__ import annotations

from pathlib import Path

from harness.layers import (
    github_settings,
    linear_enabled,
    tracker,
    tracker_config_error,
)


def _write(tmp_path: Path, text: str) -> Path:
    (tmp_path / "CONTEXT.md").write_text(text)
    return tmp_path


# --- tracker() — the single source of truth ---------------------------------


def test_tracker_linear_is_the_linear_backend(tmp_path: Path) -> None:
    root = _write(tmp_path, "tracker: linear\n")
    assert tracker(root) == "linear"
    assert linear_enabled(root) is True


def test_tracker_none_is_tracker_less(tmp_path: Path) -> None:
    root = _write(tmp_path, "tracker: none\n")
    assert tracker(root) == "none"
    assert linear_enabled(root) is False


def test_tracker_github_is_a_non_linear_backend(tmp_path: Path) -> None:
    """``github`` is a recognised backend value; the Linear path is not active."""
    root = _write(tmp_path, "tracker: github\n")
    assert tracker(root) == "github"
    assert linear_enabled(root) is False


def test_tracker_trailing_comment_is_ignored(tmp_path: Path) -> None:
    root = _write(tmp_path, "tracker: none   # this repo has no tracker\n")
    assert tracker(root) == "none"


def test_unrecognised_tracker_value_defaults_to_linear(tmp_path: Path) -> None:
    """An unrecognised value is not an off switch — the default stays conservative."""
    root = _write(tmp_path, "tracker: maybe\n")
    assert tracker(root) == "linear"
    assert linear_enabled(root) is True


def test_tracker_wins_over_a_lingering_layers_linear(tmp_path: Path) -> None:
    """``tracker:`` is the single source of truth; a stale ``layers.linear`` is ignored."""
    root = _write(
        tmp_path,
        "tracker: none\nlayers:\n  linear: true\n",
    )
    assert tracker(root) == "none"
    assert linear_enabled(root) is False


# --- back-compat: layers.linear when no tracker: key ------------------------


def test_backcompat_layers_linear_false_reads_as_none(tmp_path: Path) -> None:
    """A repo not yet migrated: ``layers.linear: false`` still means tracker-less."""
    root = _write(tmp_path, "layers:\n  linear: false\n")
    assert tracker(root) == "none"
    assert linear_enabled(root) is False


def test_backcompat_layers_linear_true_reads_as_linear(tmp_path: Path) -> None:
    root = _write(tmp_path, "layers:\n  linear: true\n")
    assert tracker(root) == "linear"
    assert linear_enabled(root) is True


def test_backcompat_repo_linear_prefix_does_not_mask_the_switch(tmp_path: Path) -> None:
    """The CAL-1104 trap survives: ``repo.linear`` above the switch is not the switch."""
    root = _write(
        tmp_path,
        "repo:\n  linear: CAL\nlayers:\n  linear: false\n",
    )
    assert tracker(root) == "none"


def test_missing_everything_defaults_to_linear(tmp_path: Path) -> None:
    """No CONTEXT.md, no tracker key, no layers block → on, as today."""
    assert tracker(tmp_path) == "linear"
    assert linear_enabled(tmp_path) is True


def test_the_harness_own_context_is_the_linear_backend() -> None:
    """The repo under test migrated to ``tracker: linear``; the reader agrees."""
    root = Path(__file__).resolve().parents[2]
    assert tracker(root) == "linear"
    assert linear_enabled(root) is True


# --- tracker_config_error() — the coherence check ---------------------------


def test_linear_backend_with_an_address_is_coherent(tmp_path: Path) -> None:
    root = _write(tmp_path, "repo:\n  linear: CAL\ntracker: linear\n")
    assert tracker_config_error(root) is None


def test_linear_backend_without_an_address_is_rejected(tmp_path: Path) -> None:
    """``tracker: linear`` needs a ``repo.linear`` address to talk to."""
    root = _write(tmp_path, "repo:\n  linear: none\ntracker: linear\n")
    err = tracker_config_error(root)
    assert err is not None
    assert "repo.linear" in err


def test_linear_backend_with_a_missing_address_is_rejected(tmp_path: Path) -> None:
    root = _write(tmp_path, "repo:\n  name: acme\ntracker: linear\n")
    err = tracker_config_error(root)
    assert err is not None
    assert "repo.linear" in err


def test_tracker_none_with_a_dangling_address_is_rejected(tmp_path: Path) -> None:
    """``tracker: none`` but a real ``repo.linear`` address still set is contradictory."""
    root = _write(tmp_path, "repo:\n  linear: CAL\ntracker: none\n")
    err = tracker_config_error(root)
    assert err is not None
    assert "repo.linear" in err


def test_tracker_none_with_no_address_is_coherent(tmp_path: Path) -> None:
    root = _write(tmp_path, "repo:\n  linear: none\ntracker: none\n")
    assert tracker_config_error(root) is None


def test_a_lingering_contradictory_layers_linear_is_rejected(tmp_path: Path) -> None:
    """A second derivable boolean that contradicts ``tracker:`` is the exact state
    this ticket removes — the coherence check flags it (AC-1/AC-3)."""
    root = _write(
        tmp_path,
        "repo:\n  linear: none\ntracker: none\nlayers:\n  linear: true\n",
    )
    err = tracker_config_error(root)
    assert err is not None
    assert "layers.linear" in err


def test_backcompat_coherent_on_config_passes(tmp_path: Path) -> None:
    """A pre-migration repo (no ``tracker:`` key) with a consistent on switch is
    coherent — the check must not force migration."""
    root = _write(tmp_path, "repo:\n  linear: CAL\nlayers:\n  linear: true\n")
    assert tracker_config_error(root) is None


def test_backcompat_coherent_off_config_passes(tmp_path: Path) -> None:
    root = _write(tmp_path, "repo:\n  linear: none\nlayers:\n  linear: false\n")
    assert tracker_config_error(root) is None


def test_the_harness_own_context_is_coherent() -> None:
    root = Path(__file__).resolve().parents[2]
    assert tracker_config_error(root) is None


# --- github backend config (CAL-1105) ---------------------------------------


def test_github_with_a_complete_block_is_coherent(tmp_path: Path) -> None:
    root = _write(tmp_path, "tracker: github\ngithub:\n  repo: acme/widgets\n  project: acme/7\n")
    assert tracker_config_error(root) is None


def test_github_without_a_block_is_rejected(tmp_path: Path) -> None:
    """``tracker: github`` needs a ``github:`` block — an absent one fails fast."""
    root = _write(tmp_path, "tracker: github\n")
    err = tracker_config_error(root)
    assert err is not None
    assert "github:" in err


def test_github_with_an_incomplete_block_is_rejected(tmp_path: Path) -> None:
    root = _write(tmp_path, "tracker: github\ngithub:\n  repo: acme/widgets\n")
    err = tracker_config_error(root)
    assert err is not None
    assert "github:" in err


def test_github_settings_parses_repo_project_and_default_status_field(tmp_path: Path) -> None:
    root = _write(tmp_path, "tracker: github\ngithub:\n  repo: acme/widgets\n  project: acme/7\n")
    settings = github_settings(root)
    assert settings is not None
    assert settings.repo == "acme/widgets"
    assert settings.project == "acme/7"
    assert settings.status_field == "Status"  # default


def test_github_settings_reads_a_custom_status_field(tmp_path: Path) -> None:
    root = _write(
        tmp_path,
        'tracker: github\ngithub:\n  repo: acme/widgets\n  project: acme/7\n'
        '  status_field: "Harness Status"\n',
    )
    settings = github_settings(root)
    assert settings is not None
    assert settings.status_field == "Harness Status"


def test_github_settings_none_without_a_block(tmp_path: Path) -> None:
    root = _write(tmp_path, "tracker: github\n")
    assert github_settings(root) is None
