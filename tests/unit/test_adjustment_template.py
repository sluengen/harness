"""#199 — the shared capture template for `/bug` and `/tweak`.

*Source:* ``specs/proposals/bug-and-tweak-capture-commands.md`` (accepted
2026-07-24), breakdown item 1. The proposal's crisp boundary: capture is a
**capture-optimized change spec** — same destination as ``templates/change.md``
(the tracker issue body), pre-framed for the moment of noticing rather than the
moment of building, and extended by ``/start`` with Grounding and Design at
build time. It is an on-ramp to the change spec, not a competing artifact.

This guard pins the template's shape so ``commands/bug.md`` (#200) and
``commands/tweak.md`` (#201) — both depend on this ticket — have a stable
contract to fill: the ``kind``/``area`` frontmatter, the four body sections,
and the per-kind framing notes (a bug's observed is the wrong behaviour + a
repro; a tweak's is the current behaviour + the friction).
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent.parent
TEMPLATE = REPO_ROOT / "templates" / "adjustment.md"
REGISTRY = REPO_ROOT / "registry.yaml"


def test_template_exists_with_version_header() -> None:
    assert TEMPLATE.exists(), "templates/adjustment.md must exist (#199)."
    text = TEMPLATE.read_text()
    assert re.search(r"guidance:template-adjustment@[\d.]+", text), (
        "templates/adjustment.md must carry a `guidance:template-adjustment@x.y.z` "
        "version header."
    )


def test_registered_in_harness_profile_with_matching_version() -> None:
    """The footprint/parity guards require every surface file to be registered
    with a matching header version (mirrors the researcher-agent precedent in
    test_grounding_step.py::test_researcher_registered)."""
    header_version = re.search(
        r"guidance:template-adjustment@([\d.]+)", TEMPLATE.read_text()
    ).group(1)
    entry = re.search(
        r"templates/adjustment\.md:\s*\{[^}]*id:\s*template-adjustment[^}]*\}",
        REGISTRY.read_text(),
    )
    assert entry, (
        "registry.yaml files: must list templates/adjustment.md with "
        "id: template-adjustment (#199)."
    )
    assert "harness" in entry.group(0), "the entry must be in the `harness` profile."
    registry_version = re.search(r"version:\s*([\d.]+)", entry.group(0)).group(1)
    assert registry_version == header_version, (
        f"templates/adjustment.md header version {header_version!r} must match "
        f"registry.yaml's {registry_version!r}."
    )


def test_frontmatter_declares_kind_and_area() -> None:
    text = TEMPLATE.read_text()
    assert re.search(r"^kind:\s*bug\s", text, re.MULTILINE), (
        "the frontmatter must declare `kind: bug | tweak` (#199)."
    )
    assert "tweak" in text, "the frontmatter's kind must offer `tweak` as well as `bug`."
    assert re.search(r"^area:\s*", text, re.MULTILINE), (
        "the frontmatter must declare an `area:` field (#199)."
    )


def test_body_has_the_four_capture_sections() -> None:
    text = TEMPLATE.read_text()
    for heading in (
        "As-built (observed)",
        "Desired",
        "From actual use",
        "Acceptance criteria",
    ):
        assert re.search(rf"^#+\s*{re.escape(heading)}\s*$", text, re.MULTILINE), (
            f"templates/adjustment.md must have a `## {heading}` section (#199)."
        )


def test_as_built_section_frames_bug_and_tweak_differently() -> None:
    """A bug's observed is the wrong behaviour + repro; a tweak's is the current
    (correct) behaviour + the friction — the one axis the proposal says the two
    kinds differ on."""
    text = TEMPLATE.read_text()
    section = text.split("## As-built (observed)", 1)[1].split("## Desired", 1)[0]
    assert "repro" in section.lower(), (
        "the As-built section must frame the bug case with a repro (#199)."
    )
    assert "kind: bug" in section and "kind: tweak" in section, (
        "the As-built section must give per-kind framing notes for both `bug` "
        "and `tweak` (#199)."
    )


def test_states_it_is_an_on_ramp_not_a_competing_artifact() -> None:
    """The proposal is explicit: this is a capture-optimized change spec that
    `/start` extends — not a competitor to templates/change.md."""
    text = TEMPLATE.read_text()
    assert "templates/change.md" in text, (
        "templates/adjustment.md must reference templates/change.md as the "
        "artifact it is an on-ramp to (#199)."
    )
    assert re.search(r"on-ramp", text, re.IGNORECASE), (
        "templates/adjustment.md must state it is an on-ramp, not a competing "
        "artifact (#199)."
    )
