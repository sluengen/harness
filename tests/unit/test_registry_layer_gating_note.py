"""CAL-749 — the registry's layer-gating note states an accurate contract.

Source: ``assessments/2026-06-16-mode2-dryrun.md`` DRYRUN-2. The brewspec
Mode-2 dry-run omitted ``design-system`` + ``ux-design`` from the install on
the strength of the registry comment *"install-time layer gating is CAL-675"*
— but **CAL-675 is closed and is about ``/harness run`` universality, not
layer gating.** Install-time gating is unbuilt; the installer copies the whole
profile and the ``layers:`` block gates *engagement* at runtime, not install
membership. Omitting profile files drifts the consumer lock from the registry
(``/update-guidance`` would keep offering to re-add them).

**What this module asserts (#459).** Two halves, neither of them meaning.

*Negative space* — the stale CAL-675 cite must not reappear anywhere in
``registry.yaml``. Unchanged.

*One tripwire* — the note is read as a **slice anchored to the entry it
governs**: the run of ``#`` comment lines immediately above
``skills/design-system/SKILL.md``. That anchoring is the structural half of
the claim, because the note is only useful where an installer agent reading
that entry will see it; a note that drifted to the bottom of the file would
satisfy a whole-file phrase pin and mislead exactly as before. Inside that
window the guard asserts the words the rule cannot be stated without and the
**negation bound to ``install``** — the layer gates engagement, *not* install
membership. Two ``in REGISTRY.read_text()`` phrase pins had no anchor and no
direction: they read the same green on a note that said the layer *does* gate
install membership, which is the class ``craft.md`` → *Mutate the rule into
its opposite, not only out of existence* names (``code-quality`` Part C → *A
guard over prose owns structure and negative space, never meaning*; ADR 0016).
"""

from __future__ import annotations

import re

from tests.unit._prose import REPO_ROOT

REGISTRY = REPO_ROOT / "registry.yaml"

#: The stale claim the dry-run agent acted on — must not reappear.
STALE_GATING_CITE = "install-time layer gating is CAL-675"

#: The registry entry the product-skills note has to sit above to be read.
GATED_ENTRY = "skills/design-system/SKILL.md:"

_NEGATION = re.compile(
    r"\b(never|not|no|nothing|none|neither|nor|cannot|can't)\b", re.IGNORECASE
)


def _product_skills_note() -> str:
    """The contiguous ``#`` comment block directly above the design-system entry.

    Anchored on the entry rather than on a line number, so a correct insertion
    elsewhere in ``files:`` cannot invalidate the window (``craft.md`` → *An
    ordinal reference into an enumeration is invalidated by a correct
    insertion*).
    """
    lines = REGISTRY.read_text().splitlines()
    index = next(
        (i for i, line in enumerate(lines) if line.strip().startswith(GATED_ENTRY)),
        None,
    )
    assert index is not None, (
        f"registry.yaml must carry a files: entry for {GATED_ENTRY} — the note "
        "this guard reads is only useful directly above it (CAL-749)."
    )
    note: list[str] = []
    for line in reversed(lines[:index]):
        if not line.strip().startswith("#"):
            break
        note.append(line.strip().lstrip("#").strip())
    return " ".join(reversed(note))


def _sentences(block: str) -> list[str]:
    """*block* flattened to one line and split into sentences.

    The terminator may be followed by markdown emphasis or a closing bracket
    (``skill.**``, ``(…).``) — consuming those is load-bearing, not cosmetic:
    a bolded lead-in that ends ``.**`` otherwise glues its sentence to the
    next one and widens every negation window that reads this (``craft.md`` →
    *The text unit is part of the predicate*). A dry run of this module's #459
    mutation table surfaced exactly that: an inverted clause survived on a
    negation belonging to the sentence after it.
    """
    flat = " ".join(block.split())
    return [s for s in re.split(r"(?<=[.!?])[*_`\"')\]]*\s+", flat) if s.strip()]


def test_registry_drops_the_stale_cal675_gating_cite() -> None:
    """registry.yaml no longer cites the closed/unrelated CAL-675 as gating."""
    assert STALE_GATING_CITE not in REGISTRY.read_text(), (
        f"registry.yaml still claims {STALE_GATING_CITE!r} — CAL-675 is closed "
        "and is about /harness run universality, not layer gating (CAL-749)."
    )


def test_product_skills_note_states_the_layer_gates_engagement() -> None:
    """Tripwire — the note above the design-system entry says what the layer gates.

    Terms: ``install`` (the thing the layer does *not* gate), ``engagement``
    (the thing it does), ``ux-design`` (the skill that is outside the gate
    entirely). Polarity, twice over: a sentence naming ``install`` carries a
    negation, and so does one naming ``ux-design``. Both directions are the
    rule — an installer agent that reads this note wrongly omits profile files,
    which is precisely what happened once already.
    """
    note = _product_skills_note()
    assert note.strip(), (
        "no comment block sits above the design-system entry — the layer-gating "
        "note must be adjacent to the entry it governs (CAL-749)."
    )
    lowered = note.lower()
    for term in ("install", "engagement", "ux-design"):
        assert term in lowered, (
            f"the product-skills note must state the gating contract in terms of "
            f"{term!r} (CAL-749)."
        )
    sentences = _sentences(lowered)
    install = [s for s in sentences if "install" in s]
    assert any(_NEGATION.search(s) for s in install), (
        "the note must say the layers gate engagement, *not* install membership "
        "— without the negation it reads identically to the claim that started "
        "DRYRUN-2, that the layer decides what is installed (CAL-749)."
    )
    ux = [s for s in sentences if "ux-design" in s]
    assert any(_NEGATION.search(s) for s in ux), (
        "the note must keep ux-design outside the design_system gate — it "
        "applies to any user-facing surface and is never gated (CAL-749)."
    )
