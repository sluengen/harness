"""The CONTEXT template's tracker fields match what the engine honours — CAL-1104, CAL-1164.

CAL-1104 advertised two fields that were not interchangeable: ``repo.linear`` (the
address) and ``layers.linear`` (the switch the engine read), a pairing a repo
could set inconsistently. CAL-1164 collapses the switch to a single ``tracker:``
field — the sole on/off-plus-backend fact — coupled to ``repo.linear`` so the two
cannot contradict.

These tests pin the template against the engine rather than against a copy of its
own words: each one feeds the template's own example to
:func:`harness.layers.tracker` / :func:`harness.layers.tracker_config_error`, so
the docs cannot drift from the reader.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from harness.layers import (
    github_settings,
    linear_enabled,
    tracker,
    tracker_config_error,
)

_TEMPLATE = Path(__file__).resolve().parents[2] / "templates" / "CONTEXT.template.md"


@pytest.fixture
def template_text() -> str:
    return _TEMPLATE.read_text()


def _uncomment_github_block(template_text: str) -> str:
    """Recover the ``github:`` block the template shows as a commented example.

    The template's default tracker is ``linear``, so the ``github:`` alternative
    lives commented (each line prefixed with ``# ``) — invisible to the reader
    (:data:`harness.layers._GITHUB_HEADER` matches only a column-0 ``github:``).
    This strips the comment prefix so the recovered block can be fed back to the
    reader, pinning the documented example against what actually parses rather
    than against a copy of its words.
    """
    lines = template_text.splitlines()
    start = next(
        i for i, ln in enumerate(lines) if ln.rstrip() == "# github:"
    )
    body = ["github:"]
    for ln in lines[start + 1 :]:
        if not ln.startswith("#   "):
            break  # the commented block ends at the first non-indented-comment line
        body.append(ln[2:])  # drop the "# " prefix, keeping the indent
    return "\n".join(body) + "\n"


def test_template_documents_tracker_as_the_engine_switch(template_text: str) -> None:
    """The ``tracker:`` line names the tracker-less behaviour ``none`` triggers."""
    line = next(
        ln for ln in template_text.splitlines() if ln.strip().startswith("tracker:")
    )
    assert "tracker-less" in line, (
        "the tracker: line must say what none does — it is the switch the engine "
        "reads, not documentation of a preference"
    )


def test_template_no_longer_advertises_layers_linear(template_text: str) -> None:
    """The ``layers.linear`` name collision is gone — no ``linear:`` under ``layers:``."""
    in_layers = False
    for line in template_text.splitlines():
        if line.startswith("layers:"):
            in_layers = True
            continue
        if in_layers:
            if line[:1].strip() and not line.startswith("#"):
                break  # a later top-level key ends the block
            assert not line.strip().startswith("linear:"), (
                "layers: must not carry a linear: switch anymore; tracker: is the "
                "single source of truth (CAL-1164)"
            )


def test_template_couples_repo_linear_none_to_the_tracker(template_text: str) -> None:
    """``repo.linear: none`` points at ``tracker: none``, so the two cannot be set apart."""
    line = next(
        ln for ln in template_text.splitlines() if ln.strip().startswith("linear: {")
    )
    assert "tracker: none" in line


def test_the_templates_tracker_less_example_reads_as_off(tmp_path: Path) -> None:
    """A repo filled in per the template's tracker-less guidance is read as off.

    The end-to-end check: what the template tells a reader to write (``tracker:
    none`` with ``repo.linear: none``) is what the reader reports as tracker-less,
    and the pairing is coherent.
    """
    (tmp_path / "CONTEXT.md").write_text(
        "repo:\n"
        "  name: some-repo\n"
        "  linear: none\n"
        "tracker: none\n"
        "layers:\n"
        "  design_system: false\n"
        "  feature_specs: true\n"
    )
    assert tracker(tmp_path) == "none"
    assert linear_enabled(tmp_path) is False
    assert tracker_config_error(tmp_path) is None


def test_the_templates_default_example_reads_as_on(tmp_path: Path) -> None:
    """The template's *default* (``tracker: linear``) leaves the tracker on and coherent."""
    (tmp_path / "CONTEXT.md").write_text(
        "repo:\n"
        "  name: some-repo\n"
        "  linear: ACME\n"
        "tracker: linear\n"
        "layers:\n"
        "  design_system: false\n"
        "  feature_specs: true\n"
    )
    assert tracker(tmp_path) == "linear"
    assert linear_enabled(tmp_path) is True
    assert tracker_config_error(tmp_path) is None


def test_template_documents_a_github_block_alongside_the_tracker(
    template_text: str,
) -> None:
    """A ``github:`` example sits by the tracker fields, naming its three keys (CAL-1105).

    A repo bootstrapping onto ``tracker: github`` needs the backend's own config
    block shown, the same way ``repo.linear`` is shown for the Linear backend.
    """
    assert "# github:" in template_text, (
        "the template must show a github: block for the tracker: github backend"
    )
    block = _uncomment_github_block(template_text)
    for key in ("repo:", "project:", "status_field:"):
        assert key in block, f"the github: example must document {key}"


def test_the_templates_github_example_reads_as_github(tmp_path: Path) -> None:
    """A repo filled in per the template's github guidance is read as ``github``.

    The end-to-end pin: the block the template documents, fed to the engine's own
    reader, resolves to a coherent ``tracker: github`` config — so the docs cannot
    drift from :func:`harness.layers.github_settings`.
    """
    block = _uncomment_github_block(_TEMPLATE.read_text())
    (tmp_path / "CONTEXT.md").write_text(
        "repo:\n"
        "  name: some-repo\n"
        "  linear: none\n"
        "tracker: github\n"
        f"{block}"
        "layers:\n"
        "  design_system: false\n"
        "  feature_specs: true\n"
    )
    assert tracker(tmp_path) == "github"
    assert linear_enabled(tmp_path) is False
    assert tracker_config_error(tmp_path) is None
    settings = github_settings(tmp_path)
    assert settings is not None
    assert "/" in settings.repo  # owner/name
    assert "/" in settings.project  # owner/number
    assert settings.status_field  # a non-empty status field (documented or defaulted)


def test_template_documents_github_token_under_env(template_text: str) -> None:
    """The env block names ``GITHUB_TOKEN`` — the github equivalent of ``linear_token``."""
    env_line = next(
        (ln for ln in template_text.splitlines() if "GITHUB_TOKEN" in ln),
        None,
    )
    assert env_line is not None, (
        "the env block must document GITHUB_TOKEN, the tracker: github credential"
    )
