"""``code-quality`` Part C: re-deriving an owned aggregate is an auditable choice.

From the 2026-07-15 code assessment (CODE-INSIGHT-1). A change added a client
aggregate (an average-rating-and-count re-derivation) while the API already
returned exactly those fields; the client copy averaged unrated entries as zero
and rendered a different number from its server-sourced sibling one toggle away
in the same tab.

Neither change's reviewer could have caught it: one shipped the client
aggregate, a later one shipped the server-sourced sibling beside it. The
contradiction existed only in the accumulation, which is why it took a steward
pass to find. The accepted fix routes the check to spec time — the one moment a
single person is looking at both layers — by making the re-derivation an
auditable choice: the change spec names why the owning layer does not own the
aggregate, or the reviewer rejects it.

**What this module asserts, after #459.** Under ADR 0016 (*tests own structure
and negative space; the reviewer owns meaning*) the term-set pin and the separate
placement pin over this one section collapse into a single tripwire:

* the section **exists inside Part C** — the slicer starts at ``## Part C``, so
  the placement claim is carried by where the anchor is looked for rather than by
  a second assertion;
* the terms the rule cannot be stated without (``aggregat``, ``change spec``);
* the **rejection anchored to what is missing** — *rejects a re-derivation that
  names neither*. That is the polarity: the rule's content is that an
  unjustified re-derivation is refused, and a window carrying ``reject`` and
  ``neither`` in unrelated sentences states nothing. Occurrence it cites
  (``code-quality`` Part C, *A new guard cites the occurrence it prevents*): the
  predecessor assertions were four bare substring checks, every one of which
  stays green if *accepts* replaces *rejects*.

:func:`test_owning_layer_aggregate_rule_is_universal` is unchanged — a
**negative-space** sweep, which ADR 0016 exempts and keeps byte-for-byte.
"""

from __future__ import annotations

import re

from tests.unit._prose import REPO_ROOT

_SKILL = REPO_ROOT / "skills" / "code-quality" / "references" / "specialized-verification.md"

_HEADING = "### Re-deriving what another layer owns is an auditable choice"

#: The rejection **anchored to the thing that is absent**. Six words is the gap
#: every legitimate spelling keeps ("rejects a re-derivation that names
#: neither"); further off, the rejection governs some other omission.
_REJECTS_WHEN_NEITHER = re.compile(
    r"\breject\w*\b(?:\W+\w+){0,6}?\W+neither\b"
    r"|\bneither\b(?:\W+\w+){0,6}?\W+reject\w*\b",
    re.IGNORECASE,
)


def _skill_text() -> str:
    return _SKILL.read_text(encoding="utf-8")


def _section() -> str:
    """The rule's own section body, sliced from Part C to the next heading.

    Scoped deliberately: an assertion run against the whole file would pass on
    wording that lives in some other section, so it would not prove *this* rule
    is present. Starting the search at ``## Part C`` is what makes the slice
    carry the placement claim as well — a copy of the rule outside the
    verification part leaves the anchor unresolved here.
    """
    text = _skill_text()
    part_c = text.find("## Part C")
    assert part_c != -1, "code-quality must have a Part C verification section"
    rest_of_part_c = text[part_c:]
    start = rest_of_part_c.find(_HEADING)
    assert start != -1, (
        "code-quality's Part C verification gate must carry the owning-layer "
        f"aggregate rule under the heading {_HEADING!r}"
    )
    rest = rest_of_part_c[start + len(_HEADING) :]
    end = rest.find("\n### ")
    return rest if end == -1 else rest[:end]


def test_the_owning_layer_aggregate_rule_is_stated_in_its_home() -> None:
    """One tripwire for one rule-home: anchor, term set, and the rejection (#459)."""
    lower = _section().lower()
    assert lower.strip(), f"the section {_HEADING!r} is empty"

    assert "aggregat" in lower, (
        "the rule must name the aggregating operation it triggers on — an agent "
        "matches on the operation in front of them"
    )
    assert "change spec" in lower, (
        "the rule must route the justification to the change spec — spec time is "
        "the only point where one person is looking at both layers"
    )
    assert _REJECTS_WHEN_NEITHER.search(lower), (
        "the rule must state that the reviewer *rejects* a re-derivation naming "
        "neither a reason nor a ticket, with the rejection anchored to the "
        "omission it answers. A section carrying `reject` and `neither` in "
        "unrelated sentences describes a review step and imposes no bar, and one "
        "that accepts the unjustified re-derivation reads identically to every "
        "substring check this replaced"
    )


def test_owning_layer_aggregate_rule_is_universal() -> None:
    """The rule names no single consumer's stack (AC-3).

    The rule was filed from one consumer's defect, in that consumer's terms (a
    mobile ``lib/`` function re-deriving what "the API" owned). The skill is
    distributed to every repo, so it has to key off the layers a consumer's
    ``CONTEXT.md`` declares instead — a repo with no mobile client and no HTTP
    API still has a layer that owns its domain. This guard pins that boundary,
    which is the standing rule for guidance edits born from a single repo.
    """
    section = _section()
    lower = section.lower()

    assert "context.md" in lower, (
        "the rule must key off the layers the consumer's CONTEXT.md declares, "
        "rather than assuming a particular architecture"
    )
    for leak in ("mobile", "react", "expo", "typescript", "http", "endpoint"):
        assert leak not in lower, (
            f"the rule must not name {leak!r}: code-quality is distributed to "
            "every consumer repo, and the originating defect's stack is not a "
            "universal one (the universal/repo boundary)"
        )
