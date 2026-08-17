"""#206 — the mirroring admission trigger covers a duplicated shell, not just a
duplicated function.

From the form repo's ``/assess code`` steward pass (2026-07-24, CODE-INSIGHT-1;
originating Linear ticket CAL-1214). ``code-quality``'s "Extract on the third
strike" admission-comment rule (CAL-800) was worded around "a helper mirrors …
a sibling", which reads naturally as scoped to pure-logic functions. The sibling
ticket CAL-1213 is the exact failure mode that framing invites: three UI
components each carried a doc comment admitting they mirrored the previous one,
yet the rule as worded did not visibly apply to a component, so the trigger was
never pulled across three separate, individually-reasonable reviews.

**Converted under #459** (ADR 0016, and ``code-quality`` Part C → *A guard over
prose owns structure and negative space, never meaning*). Two tests carrying two
literal-phrase regexes — ``a helper,\\s*component,\\s*or module\\s+\\*\\*mirrors\\*\\*``
and ``"exactly as it applies to a duplicated function"`` — became the single
tripwire below, and **half of this module's subject moved next door**: #206's
AC-1 claim (the trigger's subjects are ``helper``, ``component`` *and*
``module``) now lives in
:func:`tests.unit.test_mirrors_admission_third_strike.test_the_builder_home_states_the_admission_trigger`'s
term set, because that tripwire already reads the same paragraph and one
rule-home takes one tripwire. Moving it rather than dropping it is what keeps the
claim measured (``craft.md`` → *A deletion pass that moves a definition must move
its killer*); the sibling module's mutation table carries the entry that proves
the killer arrived.

**What this module now asserts.** #206's other half — the **coverage-parity**
claim, which nothing else in the tree measures: a duplicated rendering or
structural shell is covered exactly as a duplicated function is.

* **Anchor** — the admission paragraph of ``### Extract on the third strike``.
  The slicer is **imported** from :mod:`tests.unit._prose` rather than
  re-spelled, so
  both tripwires read the same window and a fork cannot open between them
  (``craft.md`` → *A positive control must exercise the predicate, not
  re-implement it*). The window is the paragraph, not the section: the
  rule-of-three paragraph beside it already says "shared UI in a component".
* **Term set** — ``rendering``, ``structural``, ``function``.
* **Polarity — none exists.** The claim is a *breadth* claim: it widens what the
  trigger already covers. There is no direction to invert, so no negation token
  is asserted; a bare ``not`` over the paragraph would be decoration, and the
  paragraph's own negation belongs to the sibling tripwire's polarity, not this
  one's.

**What it does not prove.** That the parity is stated the right way round — a
sentence naming a rendering shell, a structural shell and a function while
*excluding* them from the trigger carries all three terms. Breadth claims have
no cheap mechanical inversion, and this one is the reviewer's.
"""

from __future__ import annotations

import re

from tests.unit._prose import admission_paragraph

#: The words the coverage-parity claim cannot be stated without.
_TERMS = (r"\brendering\b", r"\bstructural\b", r"\bfunction\b")


def test_the_trigger_covers_a_duplicated_shell_like_a_duplicated_function() -> None:
    """AC-2: the admission trigger reaches a rendering/structural shell."""
    para = admission_paragraph()
    missing = [t for t in _TERMS if not re.search(t, para, re.IGNORECASE)]
    assert not missing, (
        "the admission paragraph no longer states that the trigger covers a "
        f"duplicated rendering/structural shell as it covers a duplicated function; "
        f"missing {missing}. Without it the rule reads as scoped to pure-logic "
        "helpers, which is the framing that let three mirrored components through "
        f"three reviews (#206 AC-2). Paragraph read:\n{para}"
    )
