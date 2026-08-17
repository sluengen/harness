"""#180 — the numeric duplication threshold has a home in ``code-quality`` Part A.

*Source:* nano-erp assessment ``assessments/2026-07-22-code.md``, systemic
insight CODE-INSIGHT-1 (nano-erp ERP-137). Per-ticket review sees only its own
diff, so it cannot notice that the Nth screen re-implemented a concern the
previous N-1 already implemented — "consider extracting" is what let five
copies land in nano-erp. A numeric threshold, checked before the helper is even
written, is what makes the duplication checkable at review time.

**Converted under #459** (ADR 0016, and ``code-quality`` Part C → *A guard over
prose owns structure and negative space, never meaning*). Four sentence-pins —
``"before writing a helper"``, ``"one other place"``, ``"if it exists in two"``,
``"not a judgement call"``, one of them a verbatim re-assertion of another —
became the single tripwire below. The pins were brittle and vacuous at once:
each broke on a benign rewording that preserved the rule exactly, while none of
them could see the rule inverted in the sentence beside it.

**What this module now asserts.** One tripwire, one rule-home:

* **Anchor** — ``### Grep before writing a helper`` resolves *from inside*
  ``## Part A — Scope``. The nesting is the placement claim: a subsection moved
  to Part B or Part C stops resolving, so there is no separate placement test
  (the dropped one was a strict subset of this slice — the class ``craft.md`` →
  *The text unit is part of the predicate* names).
* **Term set** — ``grep``, ``sibling``, ``change spec``, ``two``, ``extract``.
  The rule cannot be stated without them: drop ``two`` and the threshold stops
  being numeric, which is the whole point of the ticket.
* **Polarity** — the negation bound to what it governs: *the third copy is
  **not** a judgement call*. A bare ``not`` in the paragraph would be
  decoration; anchoring it to ``judgement`` is what makes the inversion ("the
  third copy is a judgement call") go red. ``craft.md`` → *Mutate the rule into
  its opposite, not only out of existence*.

**What it does not prove.** That the numbers are the right numbers, or that a
builder greps. A rewrite that keeps every term and reverses the advice around
them passes here and is the reviewer's to catch.
"""

from __future__ import annotations

import re

from tests.unit._prose import REPO_ROOT, section

_CODE_QUALITY = REPO_ROOT / "skills" / "code-quality" / "SKILL.md"

_PART_A = "## Part A — Scope"
_HEADING = "### Grep before writing a helper"

#: The words the rule cannot be stated without, as whole-word patterns.
_TERMS = (
    r"\bgrep\b",
    r"\bsiblings?\b",
    r"\bchange spec\b",
    r"\btwo\b",
    r"\bextract\w*\b",
)

#: The negation **bound to the thing it governs**. ``not`` alone is satisfied by
#: almost any English paragraph; ``not`` within a couple of words of
#: ``judgement`` is the clause that inverts with the rule.
_NOT_A_JUDGEMENT_CALL = re.compile(
    r"\b(?:not|never)\b(?:\W+\w+){0,2}?\W+judge?ment\b", re.IGNORECASE
)


def _rule() -> str:
    """``### Grep before writing a helper``, sliced from inside ``## Part A``.

    ``section`` is **imported**, not re-spelled: re-implementing the slicer
    forks it from the samples that measure it (``craft.md`` → *A positive
    control must exercise the predicate, not re-implement it*). Nesting the two
    calls is what folds the placement claim into the anchor.
    """
    text = _CODE_QUALITY.read_text(encoding="utf-8")
    return section(section(text, _PART_A), _HEADING)


def test_the_pre_write_duplication_threshold_has_a_home() -> None:
    """One tripwire: the rule is in Part A, names its terms, keeps its polarity."""
    rule = _rule()
    assert rule.strip(), (
        f"{_HEADING!r} is empty — a heading with no rule under it states nothing "
        "(#180)."
    )

    missing = [t for t in _TERMS if not re.search(t, rule, re.IGNORECASE)]
    assert not missing, (
        f"{_HEADING!r} no longer carries the terms the pre-write duplication rule "
        f"cannot be stated without; missing {missing}. The rule greps the sibling "
        "modules, names the one existing copy in the change spec, and extracts at "
        f"two (#180). Section read:\n{rule}"
    )

    assert _NOT_A_JUDGEMENT_CALL.search(rule), (
        "the threshold has lost its polarity: the third copy must be stated as "
        "*not a judgement call*. Without the negation bound to `judgement`, the "
        "inverted rule — the third copy is a judgement call — carries every term "
        f"above and passes (#180). Section read:\n{rule}"
    )
