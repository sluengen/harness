"""The CONTEXT template's tracker fields match what the engine honours — CAL-1104 AC-4.

The template advertises two tracker fields and they are not interchangeable:
``repo.linear`` names the workspace/team, while **``layers.linear`` is the switch
the engine actually reads**. A repo that sets ``repo.linear: none`` but leaves
``layers.linear: true`` reads as tracker-less to a human and still makes the
verbs demand a ``LINEAR_API_KEY`` — the exact mismatch this ticket closes.

These tests pin the template against the engine rather than against a copy of
its own words: each one feeds the template's own example to
:func:`harness.layers.linear_enabled`, so the docs cannot drift from the reader.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from harness.layers import linear_enabled

_TEMPLATE = Path(__file__).resolve().parents[2] / "templates" / "CONTEXT.template.md"


@pytest.fixture
def template_text() -> str:
    return _TEMPLATE.read_text()


def test_template_documents_layers_linear_as_the_engine_switch(
    template_text: str,
) -> None:
    """The ``layers.linear`` line names the tracker-less behaviour it triggers."""
    line = next(
        ln for ln in template_text.splitlines() if ln.strip().startswith("linear: true")
    )
    assert "tracker-less" in line, (
        "the layers.linear line must say what false does — it is the switch the "
        "engine reads, not documentation of a preference"
    )


def test_template_couples_repo_linear_none_to_the_layer(template_text: str) -> None:
    """``repo.linear: none`` points at the layer, so the two cannot be set apart."""
    line = next(
        ln for ln in template_text.splitlines() if ln.strip().startswith("linear: {")
    )
    assert "layers.linear: false" in line


def test_the_templates_tracker_less_example_reads_as_off(tmp_path: Path) -> None:
    """A repo filled in per the template's tracker-less guidance is read as off.

    The end-to-end check on AC-4: what the template tells a reader to write is
    what :func:`linear_enabled` reports as tracker-less.
    """
    (tmp_path / "CONTEXT.md").write_text(
        "repo:\n"
        "  name: some-repo\n"
        "  linear: none\n"
        "layers:\n"
        "  linear: false\n"
        "  design_system: false\n"
        "  feature_specs: true\n"
    )
    assert linear_enabled(tmp_path) is False


def test_the_templates_default_example_reads_as_on(tmp_path: Path) -> None:
    """The template's *default* (``linear: true``) leaves the tracker on."""
    (tmp_path / "CONTEXT.md").write_text(
        "repo:\n"
        "  name: some-repo\n"
        "  linear: ACME\n"
        "layers:\n"
        "  linear: true\n"
        "  design_system: false\n"
        "  feature_specs: true\n"
    )
    assert linear_enabled(tmp_path) is True
