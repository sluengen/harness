"""CAL-974 — a removal must sweep for its dependents.

*Source:* ``assessments/2026-07-03-full-review.md`` (CODE-INSIGHT-2 — systemic
insight). One review pass surfaced several dead contracts left keyed to removed
things: an unreachable 409 guarding a constraint dropped in a migration, a
coverage floor no gate measured, ``tools/`` references three files deep, and a
prior pass's orphaned library helpers. The class of defect is "a removal that
leaves its dependents behind."

**Converted under #459** (ADR 0016, and ``code-quality`` Part C → *A guard over
prose owns structure and negative space, never meaning*). Exact-sentence pins —
``"removal is not complete"``, ``"grep for the removed name"`` — plus a
dependent-kind checklist and a placement re-check became the single tripwire
below. Those pins broke on any rewording that preserved the rule, and passed on
any rewrite that kept the bytes while reversing the advice.

**What this module now asserts.** One tripwire, one rule-home:

* **Anchor** — ``### A removal sweeps for its dependents`` resolves *from
  inside* ``## Part A — Scope``. The nesting carries the placement claim the
  dropped third test re-checked.
* **Term set** — ``removal``, ``grep``, ``removed name``, ``dependent``. The
  dependent-kind list (exception handler / config / doc) is *illustration*, not
  the rule, so it is no longer pinned: a rewrite that swaps the examples for
  better ones is exactly the edit the old guard punished.
* **Polarity** — the negation bound to what it governs: a removal *is **not**
  complete* until the sweep runs (``craft.md`` → *Mutate the rule into its
  opposite, not only out of existence*).

**What it does not prove.** That a sweep was performed on any change — the same
honest limit the extraction-sweep guard beside it states.
"""

from __future__ import annotations

import re

from tests.unit._prose import REPO_ROOT, section

_CODE_QUALITY = REPO_ROOT / "skills" / "code-quality" / "SKILL.md"

_PART_A = "## Part A — Scope"
_HEADING = "### A removal sweeps for its dependents"

#: The words the rule cannot be stated without, as whole-word patterns.
_TERMS = (
    r"\bremovals?\b",
    r"\bgrep\b",
    r"\bremoved name\b",
    r"\bdependents?\b",
)

#: The negation **bound to the completeness it denies** — see the sibling
#: extraction-sweep guard for why a bare ``not`` over a paragraph is decoration.
_IS_NOT_COMPLETE = re.compile(
    r"\b(?:not|never)\b(?:\W+\w+){0,2}?\W+complete\b", re.IGNORECASE
)


def _rule() -> str:
    """``### A removal sweeps for its dependents``, sliced from inside Part A."""
    text = _CODE_QUALITY.read_text(encoding="utf-8")
    return section(section(text, _PART_A), _HEADING)


def test_the_removal_sweep_rule_has_a_home() -> None:
    """One tripwire: the rule is in Part A, names its terms, keeps its polarity."""
    rule = _rule()
    assert rule.strip(), (
        f"{_HEADING!r} is empty — a heading with no rule under it states nothing "
        "(CAL-974)."
    )

    missing = [t for t in _TERMS if not re.search(t, rule, re.IGNORECASE)]
    assert not missing, (
        f"{_HEADING!r} no longer carries the terms the removal-sweep rule cannot be "
        f"stated without; missing {missing}. The sweep greps for the *removed name* "
        "and updates or deletes every dependent, so the diff of a removal includes "
        f"them (CAL-974). Section read:\n{rule}"
    )

    assert _IS_NOT_COMPLETE.search(rule), (
        "the rule has lost its polarity: a removal must be stated as *not complete* "
        "until its dependents are swept. Without the negation bound to `complete`, a "
        "paragraph about removals and greps that says the opposite carries every "
        f"term above and passes (CAL-974). Section read:\n{rule}"
    )
