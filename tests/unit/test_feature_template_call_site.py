"""CAL-1171 — the feature template's Interface surface demands a production call site.

Steward insight CODE-INSIGHT-2 (nano-erp): a framework layer can ship
*provable but unconsumed* — an exported entry green against a fixture test yet
called by nothing in production — and the reviewer recording the as-built spec
is uniquely placed to catch it. ``templates/feature.md`` must therefore make the
reviewer name a real caller for each exported entry, and route an entry with no
production consumer to Known limitations rather than list it as delivered API.
"""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
FEATURE_TEMPLATE = REPO_ROOT / "templates" / "feature.md"


def _interface_surface_section() -> str:
    """Return the body of the ``## Interface surface`` section of the template."""
    text = FEATURE_TEMPLATE.read_text()
    start = text.index("## Interface surface")
    end = text.index("\n## ", start + 1)
    return text[start:end]


def test_interface_surface_requires_a_production_call_site() -> None:
    """Each exported entry must name its production caller; a test is not one."""
    section = _interface_surface_section()
    lowered = section.lower()
    assert "call site" in lowered, (
        "Interface surface must require naming the production call site per entry"
    )
    assert "a test is not a consumer" in lowered, (
        "Interface surface must state that a test does not count as a consumer"
    )


def test_unconsumed_entry_routes_to_known_limitations() -> None:
    """An entry with no production caller is recorded under Known limitations."""
    section = _interface_surface_section()
    lowered = section.lower()
    assert "known limitations" in lowered, (
        "an unconsumed entry must be routed to Known limitations"
    )
    assert "no consumer yet" in lowered, (
        "the Known-limitations wording ('no consumer yet: adopt or retire by "
        "{ticket}') must be present"
    )
    assert "never listed as delivered api" in lowered, (
        "an unconsumed entry must never be listed as delivered API"
    )
