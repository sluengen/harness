"""#231 — a sync-critical pattern extracts on the second copy, not the third.

``code-quality`` Part B's rule-of-three tells the builder to extract on the
*third* strike. The steward's cross-file-duplication lens already applies a
stricter bar — *two or more* — when the duplicated pattern is a security check,
an auth gate, or a domain rule that must stay in sync, since two copies that can
drift are already a latent bug. That gap let a duplicated authorization predicate
accumulate hand-written copies through separate merge reviews without a
build-time rule ever naming it: at copy two, the rule-of-three's own wording says
"twice is a coincidence."

Filed via a downstream repo's steward assessment, routed upstream per this repo's
own guidance-fix-routing rule (`CLAUDE.md`).

**Converted under #459** (ADR 0016, and ``code-quality`` Part C → *A guard over
prose owns structure and negative space, never meaning*). Five functions over one
paragraph became the single tripwire below. Three went for cause:

* the **paragraph-index ordering** test (``rot_idx < second_copy_idx <
  mirrors_idx``) encoded no rule — paragraph order inside a subsection is
  editorial, and a correct insertion invalidates the ordinal (``craft.md`` → *An
  ordinal reference into an enumeration is invalidated by a correct insertion*);
* the **proper-subset selector control** re-asserted what the content-based
  selector already guarantees by construction;
* the **duplicate vocabulary** test asserted a strict subset of the term set.

**One acceptance criterion is retired, not moved.** AC-3 claimed the sync-critical
vocabulary is not orphaned from the steward's lens that already applies the
two-copy bar, and named ``test_subject_vocabulary_still_present_in_steward_lens``
as its proof. No such function existed: the module's actual
``test_subject_vocabulary_stays_in_code_quality`` read the *code-quality*
paragraph, so the cross-surface claim was never measured — ``craft.md`` → *A
docstring claiming coverage the code lacks*. Restoring it would mean adding a
positive-meaning pin over ``agents/steward.md`` prose, which is the shape ADR
0016 removes. The claim is therefore retired here and left to the reviewer, and
this paragraph is the record of that call.

**What this module now asserts.** One tripwire, one rule-home:

* **Anchor** — the second-copy paragraph inside ``### Extract on the third
  strike``, sliced from inside ``## Part B — Structure``. The window is the
  paragraph because the rule-of-three paragraph beside it already contains the
  phrase "a permission check" as an example pattern, so a section-scoped
  assertion would be green before this rule was ever written.
* **Term set** — ``second``, ``permission check``, ``auth gate``, ``domain
  rule``, ``coincidence``.
* **Polarity** — the negation bound to what it governs: the coincidence
  allowance *does **not** apply* to these subjects (``craft.md`` → *Mutate the
  rule into its opposite, not only out of existence*).
"""

from __future__ import annotations

import re
from pathlib import Path

from tests.unit.test_assurance_filing_rubric import _section

# ``tests/unit/test_*.py`` → ``parents[2]`` is the repo (or worktree) root.
_REPO_ROOT = Path(__file__).resolve().parents[2]
_CODE_QUALITY = _REPO_ROOT / "skills" / "code-quality" / "SKILL.md"

_PART_B = "## Part B — Structure"
_HEADING = "### Extract on the third strike"

#: The words the rule cannot be stated without.
_TERMS = (
    r"\bsecond\b",
    r"\bpermission check\b",
    r"\bauth gate\b",
    r"\bdomain rule\b",
    r"\bcoincidence\b",
)

#: The negation **bound to the allowance it withdraws**. A bare ``not`` over the
#: paragraph would be decoration; within a few words of ``apply`` it is the
#: clause that inverts with the rule.
_DOES_NOT_APPLY = re.compile(
    r"\b(?:not|never)\b(?:\W+\w+){0,3}?\W+appl(?:y|ies)\b", re.IGNORECASE
)


def _second_copy_paragraph() -> str:
    """The sync-critical paragraph, selected by content — never by index.

    ``_section`` is imported rather than re-spelled, and the two calls are
    nested so Part B membership lives in the anchor instead of a second test.
    """
    text = _CODE_QUALITY.read_text(encoding="utf-8")
    section = _section(_section(text, _PART_B), _HEADING)
    paragraphs = [block.strip() for block in section.split("\n\n") if block.strip()]
    hits = [p for p in paragraphs if re.search(r"\bsecond\b", p, re.IGNORECASE)]
    assert hits, (
        f"no paragraph in {_HEADING!r} states a second-copy threshold — the "
        "sync-critical exception (permission check / auth gate / domain rule that "
        "must stay in sync) is missing (#231 AC-1)."
    )
    assert len(hits) == 1, (
        f"{_HEADING!r} states a second-copy threshold in {len(hits)} paragraphs; "
        "this guard's window can no longer tell which one it is pinning."
    )
    return hits[0]


def test_the_sync_critical_second_copy_rule_has_a_home() -> None:
    """One tripwire: the paragraph is in Part B, names its subjects, keeps polarity."""
    para = _second_copy_paragraph()

    missing = [t for t in _TERMS if not re.search(t, para, re.IGNORECASE)]
    assert not missing, (
        "the second-copy paragraph no longer carries the terms the rule cannot be "
        f"stated without; missing {missing}. A permission check, an auth gate or a "
        "domain rule that must stay in sync extracts on the second copy, because two "
        f"copies that can drift are already a latent bug (#231 AC-1). Paragraph "
        f"read:\n{para}"
    )

    assert _DOES_NOT_APPLY.search(para), (
        "the rule has lost its polarity: the coincidence allowance must be stated as "
        "*not applying* to these subjects. Without the negation bound to `apply`, a "
        "paragraph naming all three subjects while granting them the same "
        f"twice-is-a-coincidence latitude passes (#231 AC-1). Paragraph read:\n{para}"
    )
