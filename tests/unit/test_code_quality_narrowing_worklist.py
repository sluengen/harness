"""CAL-1100 — ``code-quality`` names a narrowing's worklist as the transitive
consumers of the field, not the callsites a grep for the coercion finds.

From the 2026-07-16 code assessment (CODE-INSIGHT-1). A batch deliberately
hunting a null-sentinel narrowed it at each render edge and left the coercion
operator as a greppable worklist for a follow-up. The follow-up cleared every
callsite the operator grep returned — and still missed two: one coercion was two
files upstream of the render it fed (grepping the operator finds the coercion,
not the render), and one documented exception was waved through while a new
consumer did arithmetic on the sentinel. Both were High findings that survived a
pass built to catch exactly this.

The fix is a Part C verification rule: when a change narrows a nullable at a
boundary, the worklist is every *transitive consumer* of that field, enumerated
by following the type to its readers — not the callsites a grep for the coercion
operator returns. It sits beside the sibling auditable-choice rules in the gate.

This guard binds that rule into the skill so a future re-edit cannot silently
drop it. It is a text-parse content guard in the style of
``test_code_quality_owning_layer_aggregate`` (CAL-1073) and
``test_code_quality_size_justification`` (CAL-666), whose Part C rules this one
sits beside.

Acceptance criteria (this ticket):

* **AC-1** — ``code-quality`` states that a narrowing's worklist is the transitive
  consumers of the field, found by following the type to its readers, not the
  callsites the coercion-operator grep returns. Proven by
  :func:`test_code_quality_has_narrowing_worklist_rule`.
* **AC-2** — the rule lives in the Part C verification gate, beside the sibling
  auditable-choice rules. Proven by
  :func:`test_narrowing_worklist_rule_is_in_verification_gate`.
* **AC-3** — the rule is phrased universally: it keys off the type / call graph
  every language has, and names no single consumer's stack, paths, or transport.
  Proven by :func:`test_narrowing_worklist_rule_is_universal`.
"""

from __future__ import annotations

from pathlib import Path

# ``tests/unit/test_*.py`` → ``parents[2]`` is the repo (or worktree) root.
_REPO_ROOT = Path(__file__).resolve().parents[2]
_SKILL = _REPO_ROOT / "skills" / "code-quality" / "SKILL.md"

_HEADING = "### Narrowing a nullable is a whole-call-graph change"


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
        "code-quality must carry the narrowing-worklist rule under the heading "
        f"{_HEADING!r} (CAL-1100 / CODE-INSIGHT-1)"
    )
    rest = text[start + len(_HEADING) :]
    end = rest.find("\n### ")
    return rest if end == -1 else rest[:end]


def test_code_quality_has_narrowing_worklist_rule() -> None:
    """The skill states the transitive-consumer worklist rule (AC-1)."""
    section = _section()
    lower = section.lower()

    # The rule names the worklist as the transitive consumers of the field...
    assert "worklist" in lower, (
        "the rule must name the change's *worklist* — the thing the enumeration "
        "produces — so an agent knows what set it is completing"
    )
    assert "transitive consumer" in lower, (
        "the worklist must be the *transitive consumers* of the narrowed field, "
        "not the local callsites — that transitivity is the whole point"
    )
    # ...found by following the type to its readers...
    assert "following the type" in lower, (
        "the rule must say the consumers are enumerated by *following the type* "
        "to its readers — the mechanism that catches the file the grep misses"
    )
    # ...and states the coercion-operator grep is not that worklist.
    assert "coercion" in lower and "grep" in lower, (
        "the rule must contrast the type-driven enumeration against a *grep for "
        "the coercion operator*, which finds the narrowing but not the reader"
    )


def test_narrowing_worklist_rule_is_in_verification_gate() -> None:
    """The rule sits in the Part C verification gate (AC-2)."""
    text = _skill_text()
    part_c_start = text.find("## Part C")
    assert part_c_start != -1, "code-quality must have a Part C verification section"
    assert _HEADING in text[part_c_start:], (
        "the narrowing-worklist rule must live in the Part C verification gate, "
        "beside the owning-layer aggregate and over-limit rules whose "
        "auditable-choice / completeness shape it shares (CAL-1100)"
    )


def test_narrowing_worklist_rule_is_universal() -> None:
    """The rule names no single consumer's stack (AC-3).

    The rule was filed from one consumer's defect, in that consumer's terms (a
    coercion in a mobile helper feeding a render two files away). The skill is
    distributed to every repo, so it keys off the type / call graph every
    language has instead — a repo with no mobile client still narrows nullables
    and still has readers to follow the type to. This guard pins that boundary,
    the standing rule for guidance edits born from a single repo.
    """
    section = _section()
    lower = section.lower()

    # Speaks in universal call-graph vocabulary, not a stack's.
    assert "consumer" in lower and "reader" in lower, (
        "the rule must speak in call-graph terms (consumers, readers) that hold "
        "in any language, not one stack's component vocabulary"
    )
    for leak in ("mobile", "react", "expo", "typescript", "http", "endpoint"):
        assert leak not in lower, (
            f"the rule must not name {leak!r}: code-quality is distributed to "
            "every consumer repo, and the originating defect's stack is not a "
            "universal one (the universal/repo boundary)"
        )
