"""The Design section vocabulary: what a design is asked for, and what counts as one.

One list, read from both ends of the design round trip. Going out, the section
names and their briefs are rendered into the engine prompt; coming back,
:func:`carries_design_sections` recognizes those same names in what the engine
returned. Splitting the two halves across modules is how they drift, and a
recognizer blind to a section the prompt asks for is a silent one.

Homed apart from ``design_protocol`` because that module is the *wire* contract
— the command, the channels, the parsers — while this is the vocabulary the wire
carries. ``design_protocol`` re-exports both public names, so the split is
internal and no caller had to move with it.
"""

from __future__ import annotations

import re

__all__ = [
    "DESIGN_SECTIONS",
    "carries_design_sections",
    "render_section_briefs",
]

# The sections a design must carry, in order. Three come from
# ``templates/change.md``'s Design block — the artifact is that block, not a
# new artifact class (ADR 0007) — and Security and Test strategy from the
# ``architecture`` skill's "what a design produces". Single-sourced here and
# rendered into the prompt, so the list cannot drift from what is asked for.
DESIGN_SECTIONS: tuple[str, ...] = (
    "Data model",
    "Interface / contract",
    "Scenarios",
    "Security",
    "Test strategy",
)

_SECTION_BRIEFS: dict[str, str] = {
    "Data model": (
        "Entities, fields, relationships, and invariants that change. Note any "
        "migration."
    ),
    "Interface / contract": (
        "Endpoints, commands, or component contracts: request/response shapes, "
        "status and error cases, auth rules."
    ),
    "Scenarios": (
        "Behaviour in scenarios where it is non-obvious or edge cases are easy "
        "to forget, as GIVEN {precondition} WHEN {action} THEN {outcome}."
    ),
    "Security": (
        "The trust boundaries this change touches, the validation at each, and "
        "what data is exposed to whom."
    ),
    "Test strategy": (
        "What to test, the key edge cases, and the integration points — enough "
        "that an implementer can write the first failing test from it."
    ),
}


def render_section_briefs() -> str:
    """The section list as the prompt shows it: each name as a heading, then its brief."""
    return "\n\n".join(
        f"### {section}\n{_SECTION_BRIEFS[section]}" for section in DESIGN_SECTIONS
    )


#: A line that is *only* a heading: an ATX heading (``### Data model``) or the
#: bold-line form models emit about as often (``**Data model**``). Anchored to
#: the whole line in both branches, which is the narrowing that matters — a
#: refusal saying "tell me what the data model should be" mentions a section
#: name in running prose and must not read as one.
_SECTION_HEADING_RE = re.compile(
    r"^[ \t]{0,3}(?:#{1,6}[ \t]+(?P<atx>.+?)|\*\*(?P<bold>.+?)\*\*)[ \t]*:?[ \t]*$",
    re.MULTILINE,
)

_SECTION_NAMES: frozenset[str] = frozenset(name.casefold() for name in DESIGN_SECTIONS)


def carries_design_sections(text: str) -> bool:
    """Whether ``text`` is shaped like a design at all.

    The structural floor for the **Codex** channel, and the reason it exists is
    an asymmetry between the two engines rather than a general quality bar.
    Claude's design file exists only because the model used the one write grant
    it was given, at a nonce'd path only that invocation knows — the file
    existing *is* the evidence a design was produced. Codex is read-only and its
    CLI writes ``--output-last-message`` on every completed turn, so a refusal, a
    clarifying question, or a summary lands in exactly the file a design would.
    Without a floor, any final message at all was hashed, posted to the ticket as
    the Design section, and recorded ``status="ok"``.

    The floor is **one** recognized heading, not all five. A real design may
    legitimately omit a section — the prompt asks for five, and asking is not
    guaranteeing — so requiring the full set would reject good designs to catch
    prose that carries none. One heading separates the two populations; more
    would start rejecting the first population too.

    Section names come from :data:`DESIGN_SECTIONS`, the same list the prompt is
    rendered from, so a sixth section cannot be asked for without being
    recognized. Matching is case-insensitive; the heading level is free.
    """
    for match in _SECTION_HEADING_RE.finditer(text):
        heading = match.group("atx") or match.group("bold") or ""
        # ``### Data model ###`` is a legal closed ATX heading.
        if heading.strip().rstrip("#").strip().casefold() in _SECTION_NAMES:
            return True
    return False
