"""CAL-1171 — the feature template's Interface surface demands a production call site.

Steward insight CODE-INSIGHT-2 (nano-erp): a framework layer can ship
*provable but unconsumed* — an exported entry green against a fixture test yet
called by nothing in production — and the reviewer recording the as-built spec
is uniquely placed to catch it. ``templates/feature.md`` must therefore make the
reviewer name a real caller for each exported entry, and route an entry with no
production consumer to Known limitations rather than list it as delivered API.

**What this module asserts (#459).** One tripwire over one rule-home. The five
literal phrase pins this module carried (``"a test is not a consumer"``,
``"no consumer yet"``, ``"never listed as delivered api"``…) were brittle and
vacuous at once: any benign rewording broke them, while an edit that kept the
bytes and inverted the rule in the next sentence passed. What replaces them is
the ``## Interface surface`` slice, the three words the rule cannot be stated
without, and the **negation bound to ``consumer``** — the direction that a
term co-occurrence has no way to see (``craft.md`` → *Mutate the rule into its
opposite, not only out of existence*; ``code-quality`` Part C → *A guard over
prose owns structure and negative space, never meaning*).
"""

from __future__ import annotations

import re

from tests.unit._prose import REPO_ROOT

FEATURE_TEMPLATE = REPO_ROOT / "templates" / "feature.md"

_NEGATION = re.compile(
    r"\b(never|not|no|nothing|none|neither|nor|cannot|can't)\b", re.IGNORECASE
)


def _interface_surface_section() -> str:
    """Return the body of the ``## Interface surface`` section of the template."""
    text = FEATURE_TEMPLATE.read_text()
    start = text.index("## Interface surface")
    end = text.index("\n## ", start + 1)
    return text[start:end]


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


def test_interface_surface_binds_each_entry_to_a_production_consumer() -> None:
    """Tripwire — the section names the call-site obligation and its escape.

    Terms: ``call site`` (the obligation), ``consumer`` (what a caller has to
    be), ``known limitations`` (where an unconsumed entry goes instead).
    Polarity: a sentence naming ``consumer`` also carries a negation token —
    the template's *a test is not a consumer* / *never listed as delivered
    API* direction. Without that binding the guard reads the same green on a
    section that told the reviewer a test **is** a consumer.
    """
    section = _interface_surface_section()
    lowered = section.lower()
    for term in ("call site", "consumer", "known limitations"):
        assert term in lowered, (
            f"the Interface surface section must state the call-site rule in terms "
            f"of {term!r} (CAL-1171)."
        )
    consumer_sentences = [s for s in _sentences(lowered) if "consumer" in s]
    assert consumer_sentences, "no sentence names a consumer in Interface surface."
    assert any(_NEGATION.search(s) for s in consumer_sentences), (
        "the consumer rule must carry its negation inside the Interface surface "
        "section — a test is *not* a consumer, and an unconsumed entry is "
        "*never* listed as delivered API. Term co-occurrence alone stays green "
        "on the inverted rule (CAL-1171)."
    )
