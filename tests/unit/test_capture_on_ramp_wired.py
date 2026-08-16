"""#202 — wire `/bug` and `/tweak` into the process docs + command table.

*Source:* ``specs/proposals/bug-and-tweak-capture-commands.md`` (accepted
2026-07-24), breakdown item 4. Depends on items 1-3 (``templates/adjustment.md``
#199, ``commands/bug.md`` #200, ``commands/tweak.md`` #201 — all shipped and
already registered in ``registry.yaml``). This ticket's remaining scope is
documentation only:

* name the capture on-ramp in ``spec-driven-development`` / ``spec-authoring``
  (where change specs are introduced), and
* add ``/bug`` / ``/tweak`` to the ``process/harness.md`` command table (whose
  byte-identical mirrors are ``CLAUDE.md`` / ``AGENTS.md`` / ``GEMINI.md``),
  with the crisp three-way boundary written explicitly: capture the
  confirmed-small (``/bug``, ``/tweak``) vs decide the unconfirmed
  (``/propose``) vs pick up the filed (``/start``) — the defense named against
  a later steward lean/MECE finding (the proposal's own Risks section).

**What this module asserts (#459).** Only the claims that survive here and
nowhere else.

*One tripwire* — ``process/harness.md`` § ``## Commands``: the two capture
commands appear as **table rows** (structure, not prose), and the same section
states the three-way boundary that keeps them distinct from ``/propose`` and
``/start``. Polarity: a sentence naming ``/propose`` carries a negation — a
confirmed bug or small tweak does **not** go through it. The whole-file version
this replaces asserted four command names and two words co-occurring anywhere
in the document, which the document satisfies for reasons unrelated to the
boundary being stated (``code-quality`` Part C → *A guard over prose owns
structure and negative space, never meaning*; ADR 0016).

*Two pointer tripwires* — ``spec-driven-development`` and ``spec-authoring``
each name the two commands and the shared capture form. These are artifact
names, not meaning; they fail when the on-ramp is unwired from either skill.

*Five re-checks removed.* Byte-identity of the mirrors is owned by
``test_process_doc_mirrors``; the three per-file header⇄registry checks and
the ``registry.yaml`` self-version check are subsumed by the tree-wide parity
sweeps (``test_guidance_source.py::test_surface_headers_match_registry`` and
``test_registered_file_version_matches_its_registry_entry``). A second copy of
a correspondence check is not a second guard — it is one guard with two homes
to keep in step.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent.parent
PROCESS_DOC = REPO_ROOT / "process" / "harness.md"
SPEC_DRIVEN = REPO_ROOT / "skills" / "spec-driven-development" / "SKILL.md"
SPEC_AUTHORING = REPO_ROOT / "skills" / "spec-authoring" / "SKILL.md"

def _commands_section() -> str:
    """The body of ``## Commands`` in the process doc, up to the next ``##``.

    Anchored on the heading text, so an inserted section above it does not move
    the window (``craft.md`` → *An ordinal reference into an enumeration is
    invalidated by a correct insertion*).
    """
    text = PROCESS_DOC.read_text()
    start = text.index("\n## Commands\n")
    end = text.index("\n## ", start + 1)
    return text[start:end]


# --- AC-1: the command table lists /bug and /tweak, with the boundary stated -


def test_command_table_lists_the_capture_commands_with_the_boundary() -> None:
    """Tripwire — both capture commands are table rows in ``## Commands``, and
    the section states the three-way boundary between the front doors.

    The row check is structural: a ``| `/bug…` |`` cell is what makes the
    command discoverable to an agent reading the table, and a mention in a
    paragraph is not the same claim. The boundary check adds the three sibling
    front doors plus the two words the distinction is drawn in
    (``confirmed-small`` / ``unconfirmed``).

    **No negation is asserted, and none is faked.** The section is a command
    table, and a markdown table carries no sentence terminators, so any
    negation window over it is wide enough to be satisfied by an unrelated
    row — ``/bug``'s own cell says *no escape hatch*, and the boundary
    paragraph opens *deliberate, not incidental*. A negation token bound to
    ``/propose`` would therefore stay green if the prohibition itself were
    deleted, which is decoration rather than polarity (``craft.md`` → *The
    text unit is part of the predicate*; ADR 0016). Whether the boundary still
    points the right way is the review gate's.
    """
    section = _commands_section()
    for command in ("/bug", "/tweak"):
        assert re.search(rf"\|\s*`{re.escape(command)}[^`]*`\s*\|", section), (
            f"process/harness.md's Commands table must list `{command}` as a row "
            "(#202 AC-1)."
        )
    for command in ("/propose", "/start"):
        assert command in section, (
            f"the Commands section must name {command} alongside the capture "
            "commands so the three-way boundary is legible (#202 AC-1)."
        )
    lowered = section.lower()
    for term in ("confirmed-small", "unconfirmed"):
        assert term in lowered, (
            "the Commands section must state the three-way boundary explicitly — "
            f"missing {term!r} (#202 AC-1, defending against a steward lean/MECE "
            "finding)."
        )


# --- AC-2: the mirrors stay byte-identical -----------------------------------
#
# Nothing is asserted here, deliberately. Byte-identity between
# ``process/harness.md`` and its three mirrors is owned by
# ``tests/unit/test_process_doc_mirrors.py``, which compares the whole files;
# re-comparing them here added no failure mode that guard does not already
# carry, and the version this replaced said so in its own comment (#459).
# A second copy of an identity check is not a second guard — it is one guard
# with two homes to keep in step.


# --- AC-3: spec-driven-development / spec-authoring name the on-ramp ---------


def test_spec_driven_development_names_the_capture_on_ramp() -> None:
    text = SPEC_DRIVEN.read_text()
    assert "/bug" in text and "/tweak" in text, (
        "spec-driven-development must name the /bug / /tweak capture on-ramp "
        "where change specs are introduced (#202 AC-3)."
    )
    assert "templates/adjustment.md" in text, (
        "spec-driven-development must name templates/adjustment.md as the "
        "capture form /bug and /tweak file (#202 AC-3)."
    )


def test_spec_authoring_names_the_capture_on_ramp() -> None:
    text = SPEC_AUTHORING.read_text()
    assert "/bug" in text and "/tweak" in text, (
        "spec-authoring must name the /bug / /tweak capture on-ramp in its "
        "Change spec section (#202 AC-3)."
    )
    assert "templates/adjustment.md" in text, (
        "spec-authoring must name templates/adjustment.md as the capture form "
        "/bug and /tweak file, ahead of the full change-spec form (#202 AC-3)."
    )
