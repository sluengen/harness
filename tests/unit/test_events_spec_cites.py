"""CAL-635 — the ``harness/events/`` docstrings cite the right SPEC section.

The event-log writer and its canonical event types live in SPEC **§4.7**
(``harness.events.emitter`` — "Event types live in ``harness.events.schema``").
Four live docstrings instead cited **§4.9**, which is a *current* section but
documents ``harness.launcher`` / ``harness.workspace`` / ``harness.trigger`` —
nothing about events. A cross-reference that resolves to the wrong section is
worse than none: a reader following §4.9 lands on launcher/workspace/trigger and
finds no event-type contract.

This is a distinct class from the retired-§ cluster (CAL-633): §4.9 is a *live*
section, so a retired-§ grep-guard would not catch it. This guard is the
executable form of the fix — the events module source must cite §4.7 for the
event surface and must not cite §4.9 at all.

It also locks the **§4.4** class (originally deferred by the CAL-635 fix):
``schema.py`` once cited §4.4 for the retired ``decision_violation`` event type,
but the verb-model rewrite made §4.4 ``harness.cli.close`` (the close gate) —
which documents nothing about contract violations. ``decision_violation`` is an
engine-era type emitted by no live code (live verbs emit only ``review`` /
``close``); it is kept in the Literal so historical rows validate, and its
comment is now a retired-engine label citing no live section. The guard asserts
the events source carries no §4.4 cite so the wrong pointer cannot return.
"""

from __future__ import annotations

from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]

#: The events module source files whose docstrings cite the event-type section.
_EVENTS_SOURCES = [
    "harness/events/emitter.py",
    "harness/events/schema.py",
]


@pytest.mark.parametrize("relpath", _EVENTS_SOURCES)
def test_events_source_does_not_cite_wrong_section(relpath: str) -> None:
    """No events module source cites §4.9 — that section is launcher/workspace."""
    text = (_REPO_ROOT / relpath).read_text()
    assert "§4.9" not in text, (
        f"{relpath} cites SPEC §4.9, which documents harness.launcher / "
        "harness.workspace / harness.trigger — not events. The event-log writer "
        "and its event types live in §4.7; cite that instead."
    )


@pytest.mark.parametrize("relpath", _EVENTS_SOURCES)
def test_events_source_does_not_cite_close_section(relpath: str) -> None:
    """No events module source cites §4.4 — that section is harness.cli.close.

    ``decision_violation`` is a retired engine-era type emitted by no live code;
    its comment must label it as such, not point at the close-verb section.
    """
    text = (_REPO_ROOT / relpath).read_text()
    assert "§4.4" not in text, (
        f"{relpath} cites SPEC §4.4, which documents harness.cli.close (the "
        "close gate) — not contract violations or any event type. The retired "
        "decision_violation type cites no live section; relabel it instead."
    )


@pytest.mark.parametrize("relpath", _EVENTS_SOURCES)
def test_events_source_cites_canonical_section(relpath: str) -> None:
    """Each events module source cites §4.7 — the home of the event surface."""
    text = (_REPO_ROOT / relpath).read_text()
    assert "§4.7" in text, (
        f"{relpath} must cite SPEC §4.7 (harness.events.emitter) for the "
        "event-log writer / event types — that is their canonical home."
    )
