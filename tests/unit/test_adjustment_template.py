"""#199 — the shared capture template for `/bug` and `/tweak`.

*Source:* ``specs/proposals/bug-and-tweak-capture-commands.md`` (accepted
2026-07-24), breakdown item 1. The proposal's crisp boundary: capture is a
**capture-optimized change spec** — same destination as ``templates/change.md``
(the tracker issue body), pre-framed for the moment of noticing rather than the
moment of building, and extended by ``/start`` with Grounding and Design at
build time. It is an on-ramp to the change spec, not a competing artifact.

**What this module asserts (#459).** Structure and negative space only: the
file exists, its header version matches its ``registry.yaml`` entry, its
frontmatter declares the two capture kinds, and the four body sections are
present. Two anchored tripwires stand in for the sentence-pins this module
used to carry — one per rule-home, each reading only its own slice:

* ``## As-built (observed)`` — the per-kind framing, with the polarity that
  makes it a rule rather than a list: the *tweak* arm **negates** the repro the
  *bug* arm demands. A co-occurrence of ``repro`` and the two kinds has no
  direction and stays green if the two arms are swapped, which is the class
  ``craft.md`` → *Mutate the rule into its opposite, not only out of
  existence* names.
* the preamble between ``# {title}`` and the first section heading — the
  on-ramp framing, whose polarity is the ``not a competing artifact`` clause
  bound to the same sentence as ``on-ramp``.

Whether either paragraph says the *right* thing beyond that is the review
gate's, per ``code-quality`` Part C → *A guard over prose owns structure and
negative space, never meaning* (ADR 0016).
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent.parent
TEMPLATE = REPO_ROOT / "templates" / "adjustment.md"
REGISTRY = REPO_ROOT / "registry.yaml"

#: The tokens an English clause carries a negation on. Asserted *bound to a
#: term* (same sentence / same bullet), never loose over a paragraph — a bare
#: ``"not" in block`` is satisfied by almost any prose and is decoration.
_NEGATION = re.compile(
    r"\b(never|not|no|nothing|none|neither|nor|cannot|can't|don't|doesn't)\b",
    re.IGNORECASE,
)


def _sentences(block: str) -> list[str]:
    """*block* flattened to one line and split into sentences.

    The terminator may be followed by markdown emphasis or a closing bracket
    (``skill.**``, ``(…).``) — consuming those is load-bearing, not cosmetic:
    a bolded lead-in that ends ``.**`` otherwise glues its sentence to the
    next one and widens every negation window that reads this (``craft.md`` →
    *The text unit is part of the predicate*). A dry run of the #459 mutation
    tables surfaced exactly that: an inverted clause survived on a negation
    belonging to the sentence after it.
    """
    flat = " ".join(block.split())
    return [s for s in re.split(r"(?<=[.!?])[*_`\"')\]]*\s+", flat) if s.strip()]


def _bullets(block: str) -> list[str]:
    """The top-level ``-`` list items in *block*, each joined to one line."""
    items: list[str] = []
    current: list[str] | None = None
    for line in block.splitlines():
        if re.match(r"\s*-\s+\S", line):
            if current is not None:
                items.append(" ".join(current))
            current = [line.strip()]
        elif current is not None:
            if not line.strip():
                items.append(" ".join(current))
                current = None
            else:
                current.append(line.strip())
    if current is not None:
        items.append(" ".join(current))
    return items


def _as_built_section() -> str:
    """The body of ``## As-built (observed)``, up to the next ``##`` heading."""
    text = TEMPLATE.read_text()
    start = text.index("## As-built (observed)")
    end = text.index("\n## ", start + 1)
    return text[start:end]


def _preamble() -> str:
    """The framing paragraph between ``# {title}`` and the first section.

    Anchored on the title line rather than on a byte offset, so a correct
    insertion above or below it does not invalidate the window (``craft.md`` →
    *An ordinal reference into an enumeration is invalidated by a correct
    insertion*).
    """
    text = TEMPLATE.read_text()
    start = text.index("# {title}") + len("# {title}")
    rest = text[start:]
    ends = [i for i in (rest.find("\n## "), rest.find("\n---")) if i != -1]
    return rest[: min(ends)] if ends else rest


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


def test_as_built_section_frames_the_two_kinds() -> None:
    """Tripwire — the As-built section splits the two capture kinds, and the
    tweak arm negates the repro the bug arm demands.

    Terms: ``repro`` plus both ``kind:`` values. Polarity: the *tweak* bullet
    carries a negation token, which is what distinguishes this rule from a
    two-item list of kinds and what an inversion of the two arms breaks.
    """
    section = _as_built_section()
    lowered = section.lower()
    for term in ("repro", "kind: bug", "kind: tweak"):
        assert term in lowered, (
            f"the As-built section must frame the capture kinds by naming {term!r} "
            "(#199)."
        )
    tweak_bullets = [b for b in _bullets(section) if "kind: tweak" in b.lower()]
    assert tweak_bullets, "no `kind: tweak` bullet inside the As-built section (#199)."
    assert any(_NEGATION.search(b) for b in tweak_bullets), (
        "the `kind: tweak` arm must negate the repro the `kind: bug` arm demands "
        "— without a negation the two arms are interchangeable and this guard "
        "would stay green if they were swapped (#199)."
    )


def test_the_form_declares_itself_an_on_ramp_to_the_change_spec() -> None:
    """Tripwire — the preamble routes to ``templates/change.md`` as an on-ramp.

    Terms: ``templates/change.md`` and ``on-ramp``. Polarity: the sentence
    naming the on-ramp also carries the negation (*not a competing artifact*),
    so a preamble that recast this form as a rival to the change spec fails
    here rather than passing on the two terms alone.
    """
    preamble = _preamble()
    assert "templates/change.md" in preamble, (
        "the capture form's framing must name templates/change.md as the "
        "artifact it feeds (#199)."
    )
    on_ramp = [s for s in _sentences(preamble) if re.search(r"on-ramp", s, re.I)]
    assert on_ramp, (
        "the framing paragraph must state that this form is an on-ramp (#199)."
    )
    assert any(_NEGATION.search(s) for s in on_ramp), (
        "the on-ramp sentence must carry its negation — this form is *not* a "
        "competing artifact to templates/change.md (#199)."
    )
