"""CAL-1073 — ``code-quality`` makes re-deriving an owned aggregate auditable.

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

This guard binds that rule into the skill so a future re-edit cannot silently
drop it. It is a text-parse content guard in the style of
``test_code_quality_size_justification`` (CAL-666), whose Part C
"auditable choice, not silent drift" section this rule mirrors, and
``test_fetch_untrusted_urls_checklist``.

Acceptance criteria (this ticket):

* **AC-1** — ``code-quality`` requires a change that re-derives an aggregate the
  owning layer already returns to name why, with the reviewer rejecting one that
  does not. Proven by :func:`test_code_quality_has_owning_layer_aggregate_rule`.
* **AC-2** — the rule lives in the Part C verification gate, beside the sibling
  auditable-choice rule it mirrors. Proven by
  :func:`test_owning_layer_aggregate_rule_is_in_verification_gate`.
* **AC-3** — the rule is phrased universally: it keys off the layers the
  consumer's ``CONTEXT.md`` declares, and names no single consumer's stack,
  paths, or transport. Proven by
  :func:`test_owning_layer_aggregate_rule_is_universal`.
"""

from __future__ import annotations

from pathlib import Path

# ``tests/unit/test_*.py`` → ``parents[2]`` is the repo (or worktree) root.
_REPO_ROOT = Path(__file__).resolve().parents[2]
_SKILL = _REPO_ROOT / "skills" / "code-quality" / "references" / "specialized-verification.md"

_HEADING = "### Re-deriving what another layer owns is an auditable choice"


def _skill_text() -> str:
    return _SKILL.read_text(encoding="utf-8")


def _section() -> str:
    """The rule's own section body, sliced to the next heading.

    Scoped deliberately: an assertion run against the whole file would pass on
    wording that lives in some other section, so it would not prove *this* rule
    is present. The slice is what makes each assertion below bite on the rule
    it names.
    """
    text = _skill_text()
    start = text.find(_HEADING)
    assert start != -1, (
        "code-quality must carry the owning-layer aggregate rule under the "
        f"heading {_HEADING!r} (CAL-1073 / CODE-INSIGHT-1)"
    )
    rest = text[start + len(_HEADING) :]
    end = rest.find("\n### ")
    return rest if end == -1 else rest[:end]


def test_code_quality_has_owning_layer_aggregate_rule() -> None:
    """The skill states the re-derivation justification rule (AC-1)."""
    section = _section()
    lower = section.lower()

    # The rule names the aggregating operations it triggers on...
    for op in ("average", "sum", "count", "group"):
        assert op in lower, (
            f"the rule must name {op!r} among the aggregating operations that "
            "trigger it — an agent matches on the operation in front of them"
        )
    # ...routes the justification to the change spec...
    assert "change spec" in lower, (
        "the rule must require the justification in the change spec — spec time "
        "is the only point where one person is looking at both layers"
    )
    # ...and states the reviewer rejects an unjustified re-derivation.
    assert "reject" in lower, (
        "the rule must state the reviewer rejects a re-derivation that names "
        "neither a reason nor a ticket, matching the sibling size rule's bar"
    )


def test_owning_layer_aggregate_rule_is_in_verification_gate() -> None:
    """The rule sits in the Part C verification gate (AC-2)."""
    text = _skill_text()
    part_c_start = text.find("## Part C")
    assert part_c_start != -1, "code-quality must have a Part C verification section"
    assert _HEADING in text[part_c_start:], (
        "the owning-layer aggregate rule must live in the Part C verification "
        "gate, beside the over-limit rule whose auditable-choice shape it "
        "mirrors (CAL-1073)"
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
