"""#194 — review-discipline catches partial adoption of a shared hook/utility.

Surfaced by nano-erp's ``/assess code`` pass (2026-07-23, insight
CODE-INSIGHT-1, tracked as ERP-157). A call site imports a hook built to
replace a hand-rolled pattern — e.g. ``useResource`` replacing a hand-rolled
write-refusal/pending pattern — but destructures only part of its return
value and reimplements the rest by hand, silently reopening the defect the
unused part existed to close. Nothing catches this today: the file compiles
(unused fields just aren't destructured) and tests pass (nothing exercises
the missing state). Direct evidence: ``OrgFeatureFlagsPage.tsx`` imports
``useResource`` but only destructures part of its contract, while its
sibling ``AdminFeatureFlagsPage.tsx`` calls the identical hook one line apart
and uses the full contract — only a side-by-side read of the two siblings
surfaces the gap.

Unlike its sibling Stage-2 structural classes, this rule shipped with no
content guard until now. Every other concrete structural class has a
text-parse guard pinning it into the skill —
``test_review_discipline_port_orphan`` (CAL-665),
``test_over_engineering_lens`` (CAL-711),
``test_mirrors_admission_third_strike`` (CAL-800),
``test_review_discipline_misplaced_helper`` (CAL-823) — so a future re-edit
cannot silently drop the rule. This is that guard for **Partial hook/utility
adoption**, in the same style.

Acceptance criteria (this ticket):

* **AC-1** — ``review-discipline`` carries a rule that, for a call site
  importing a shared hook/utility built to replace a hand-rolled pattern,
  the reviewer confirms every field of its return value the concern needs is
  actually used, not reimplemented beside it — checking sibling call sites
  for the same hook to see which fields they use that this one does not.
  Proven by :func:`test_review_discipline_has_partial_hook_adoption_rule`.
* **AC-2** — the rule lives in the Stage 2 quality checks, immediately after
  the "Mirrors/duplicates" admission-comment bullet and before the
  Architecture watchlist bullet. Proven by
  :func:`test_partial_hook_adoption_rule_is_in_stage_two` and
  :func:`test_partial_hook_adoption_rule_sits_between_mirrors_and_watchlist`.

#208 — renews ERP-157 (nano-erp ``/assess code``, CODE-INSIGHT-1). The rule
above only fires once a reviewer notices the shared hook *is* imported and
checks its destructuring. Twice in one range (``QuoteShoppingPage.tsx``
skipping ``useResource`` entirely, ``WorkingPanel.tsx`` skipping
``useRefusal`` entirely) the call site never imported the hook at all and
hand-rolled the whole contract beside it — a screen that imports nothing has
nothing to destructure, so the existing trigger ("a call site imports the
hook...") never fires. The rule must trigger on the **shape of the diff**
(a data-fetching or write-then-refetch flow, or a hand-rolled
``useState``-based load/save/refusal/pending sequence) rather than only on
an existing import, so it also catches the no-import case.

* **AC-3** — the rule states it applies whether or not the shared hook is
  imported at all, triggered by the shape of what the diff adds (a
  data-fetching or write-then-refetch flow) rather than only by an existing
  import. Proven by
  :func:`test_partial_hook_adoption_rule_covers_full_non_adoption`.
"""

from __future__ import annotations

import re
from pathlib import Path

# ``tests/unit/test_*.py`` → ``parents[2]`` is the repo (or worktree) root.
_REPO_ROOT = Path(__file__).resolve().parents[2]
_SKILL = _REPO_ROOT / "skills" / "review-discipline" / "SKILL.md"


def _skill_text() -> str:
    return _SKILL.read_text(encoding="utf-8")


def _stage_two(text: str) -> str:
    """review-discipline's Stage 2 quality body (where structural checks live).

    Slice between the ``### Stage 2`` heading and the ``## Severity`` section
    so the assertions see only the quality rules, not the neighbouring
    sections.
    """
    start = text.index("### Stage 2")
    end = text.index("## Severity", start)
    return text[start:end]


def _partial_adoption_bullet(text: str) -> str:
    """The Stage 2 bullet for the Partial-hook/utility-adoption rule.

    The rule is its own ``- **Partial hook/utility adoption**`` bullet
    alongside the other concrete structural checks (Mirrors-admission /
    Architecture watchlist); find that bullet and slice to the next
    top-level bullet or heading so the assertions see only this rule.
    """
    stage_two = _stage_two(text)
    m = re.search(r"^- \*\*Partial hook/utility adoption\*\*", stage_two, re.MULTILINE)
    assert m, (
        "review-discipline Stage 2 has no bullet naming the Partial-hook/"
        "utility-adoption rule (#194 AC-1)."
    )
    rest = stage_two[m.start() :]
    nxt = re.search(r"^(?:- \*\*|#{2,3} )", rest[1:], re.MULTILINE)
    return rest[: nxt.start() + 1] if nxt else rest


def test_review_discipline_has_partial_hook_adoption_rule() -> None:
    """The skill states the partial-hook/utility-adoption rule (AC-1)."""
    bullet = _partial_adoption_bullet(_skill_text()).lower()
    # It is about a call site importing a shared hook/utility built to
    # replace a hand-rolled pattern...
    assert "hook" in bullet and "hand-rolled" in bullet, (
        "the rule must name a shared hook/utility built to replace a "
        "hand-rolled pattern"
    )
    # ...that destructures only part of its return value / contract...
    assert "destructures" in bullet or "contract" in bullet, (
        "the rule must call out destructuring only part of the hook's "
        "return value / contract"
    )
    assert "reimplement" in bullet, (
        "the rule must call out reimplementing the rest by hand beside the "
        "hook"
    )
    # ...and the fix is to check sibling call sites for the same hook.
    assert "sibling" in bullet, (
        "the rule must direct checking sibling call sites for the same "
        "hook to see which fields they use that this one does not"
    )


def test_partial_hook_adoption_rule_is_in_stage_two() -> None:
    """The rule sits in Stage 2 quality, beside the sibling structural rules (AC-2)."""
    text = _skill_text()
    stage_two_start = text.find("### Stage 2")
    assert stage_two_start != -1, "review-discipline must have a Stage 2 section"
    severity_start = text.find("## Severity")
    assert severity_start != -1, "review-discipline must have a Severity section"
    stage_two = text[stage_two_start:severity_start]
    assert "**Partial hook/utility adoption**" in stage_two, (
        "the partial-hook-adoption rule must live in the Stage 2 quality "
        "checks, alongside the other structural rules"
    )


def test_partial_hook_adoption_rule_sits_between_mirrors_and_watchlist() -> None:
    """The rule sits immediately after Mirrors/duplicates, before Architecture watchlist (AC-2)."""
    stage_two = _stage_two(_skill_text())
    mirrors_idx = stage_two.index('- **"Mirrors/duplicates" admission comment**')
    partial_idx = stage_two.index("- **Partial hook/utility adoption**")
    watchlist_idx = stage_two.index("- **Architecture watchlist**")
    assert mirrors_idx < partial_idx < watchlist_idx, (
        "the Partial-hook/utility-adoption bullet must sit immediately after "
        "the Mirrors/duplicates admission-comment bullet and before the "
        "Architecture watchlist bullet"
    )


def test_partial_hook_adoption_rule_covers_full_non_adoption() -> None:
    """The rule also catches a call site that skips the hook entirely (#208 AC-3).

    A screen that never imports the shared hook has nothing to destructure,
    so a trigger scoped to "a call site imports the hook..." never fires for
    it. The rule must instead trigger on the shape of what the diff adds —
    a data-fetching or write-then-refetch flow — so it catches both the
    partial-adoption case (imports, uses part) and the no-adoption case
    (never imports, hand-rolls the whole thing beside it).
    """
    bullet = _partial_adoption_bullet(_skill_text()).lower()
    assert "whether or not" in bullet and "imported" in bullet, (
        "the rule must state it applies whether or not the shared hook is "
        "imported at all, not only when a call site already imports it"
    )
    assert "data-fetching" in bullet or "write-then-refetch" in bullet, (
        "the rule must trigger on the shape of what the diff adds (a "
        "data-fetching or write-then-refetch flow), not only on an "
        "existing import"
    )
