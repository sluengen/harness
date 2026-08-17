"""CAL-972 — ``review-discipline`` gates the as-built record on a behaviour change.

From the 2026-07-03 full-review assessment (SYSTEM-INSIGHT-1 — a systemic
insight): shipped behaviour changes whose as-built records silently rot. The
per-change review updated the code but never the mapped feature spec / design
doc, so the canonical record drifted from what shipped — a class no single
per-change reviewer catches, because each reviewer looks at the code, not at
whether the record kept pace.

The accepted fix elevates the reviewer's *record reality on PASS* obligation into
a hard **as-built-record gate**: when the diff touches a user-facing surface, the
review must either fold the matching as-built-record update into the change or
record an explicit deferral naming the reason; a behaviour change with neither is
a FAIL. It is layer-aware — the record is ``specs/features/`` where
``feature_specs`` is on, otherwise the design doc / ``SPEC.md``.

**What this module asserts, after #459.** Two tripwires:

* **the gate** — the one ``## Reviewer obligations`` bullet that carries it names
  the trigger, both escapes, both layer forms, and the FAIL, with the consequence
  anchored to the ``neither … nor`` that earns it;
* **the pointers** — ``commands/review.md`` and ``agents/reviewer.md`` each name
  the record and its deferral **on one line**, so neither can state the record
  step without its escape.

:func:`tests.unit._prose.obligations_section` and
:func:`tests.unit._prose.obligation_bullets` are read from the neutral home by
this module and by ``test_final_evidence_ordering`` — #467 moved them out of here
— because the two guards read adjacent bullets of the same section and must not
disagree about where it is.

Five term co-occurrences collapsed into those two (ADR 0016), three of them
near-identical: the same four words asserted over the whole skill, over the
obligations section, and again for the layer forms. Occurrence the anchoring
cites (``code-quality`` Part C): read over the whole section, ``fail`` is free —
four other bullets and the section that follows use it — so the pre-#459 form
proved only that the words *as-built*, *user-facing surface*, *deferral* and
*fail* each appeared somewhere in a 5-bullet block. The ``craft.md`` class is *A
guard over prose owns structure and negative space, never meaning*.
"""

from __future__ import annotations

import re
from pathlib import Path

from tests.unit._prose import REPO_ROOT, obligation_bullets

_COMMAND = REPO_ROOT / "commands" / "review.md"
_AGENT = REPO_ROOT / "agents" / "reviewer.md"

#: The subject that selects the gate's bullet out of the obligations list.
_GATE_TERM = "as-built-record gate"

#: The consequence, **anchored to the condition that earns it**. ``FAIL`` read
#: anywhere in the obligations section is free — several bullets use it — so the
#: verdict has to be read next to the ``neither … nor`` that triggers it. This is
#: the whole content of a *gate*: without it the bullet describes an obligation
#: that nothing enforces, which is the state CAL-972 found.
_NEITHER_IS_A_FAIL = re.compile(
    r"\bneither\b(?:\W+\w+){0,12}?\W+FAIL\b", re.DOTALL
)


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _gate_bullets() -> list[str]:
    """Obligation bullets carrying the as-built-record gate."""
    return [b for b in obligation_bullets() if _GATE_TERM in b]


def test_the_asbuilt_record_gate_is_stated_where_the_reviewer_reads_it() -> None:
    """The one tripwire over the gate's bullet (AC-1).

    Four parts:

    * **anchor** — exactly one obligation bullet names the as-built-record gate.
      Cardinality, not containment: two bullets stating it is how the gate and the
      obligation it strengthens drift apart, and one is what the reviewer reaches.
    * **terms** — the trigger (``user-facing surface``), the escape
      (``deferral``), and both layer forms (``specs/features`` where
      ``feature_specs`` is on, the design doc / ``SPEC.md`` otherwise). A gate
      stated for only one layer is off in every repo on the other.
    * **polarity** — ``FAIL`` anchored to the ``neither … nor`` that earns it.
      Read section-wide, that token proves nothing.
    """
    bullets = _gate_bullets()
    assert len(bullets) == 1, (
        f"review-discipline's Reviewer obligations carry {len(bullets)} bullets "
        f"naming the {_GATE_TERM!r}; there must be exactly one. The gate belongs "
        "with the record obligation it strengthens — stated twice, the two copies "
        "agree the day the second is written and drift after (CAL-972)."
    )
    bullet = bullets[0]
    lowered = bullet.lower()

    assert "user-facing surface" in lowered, (
        "the as-built-record gate no longer names its trigger. Without 'the diff "
        "touches a user-facing surface' the gate has no condition and applies to "
        "everything or nothing (CAL-972)."
    )
    assert "deferral" in lowered, (
        "the as-built-record gate no longer offers an explicit deferral as the "
        "alternative to updating the record. A gate with no sanctioned escape is "
        "one every legitimately-blocked review has to route around (CAL-972)."
    )

    assert "specs/features" in lowered, (
        "the gate no longer names specs/features as the record where the "
        "feature_specs layer is on (CAL-972)."
    )
    assert "spec.md" in lowered or "design doc" in lowered, (
        "the gate no longer covers the feature_specs-off case (design doc / "
        "SPEC.md). Stated for one layer only, it is silently off in every repo on "
        "the other (CAL-972)."
    )

    assert _NEITHER_IS_A_FAIL.search(bullet), (
        "the gate no longer makes a behaviour change with *neither* a record "
        "update *nor* a recorded deferral a FAIL. Read over the whole obligations "
        "section the word FAIL is free — several bullets use it — so without the "
        "verdict anchored to the condition that earns it, this bullet can be "
        "softened back into the un-enforced obligation CAL-972 found rotting."
    )


def test_each_operating_surface_names_the_gate_and_its_escape() -> None:
    """The pointer tripwire: the command and the agent state the gate *in place*.

    **Line-scoped, and that is the whole point.** Both files name the as-built
    record for other reasons and both name a deferral for other reasons, so a
    whole-file check — which is what the two pre-#459 tests did — passes on a file
    that states the unconditional record obligation and drops its gate. Requiring
    the two on one line is what ties the escape to the obligation it qualifies.
    """
    missing = [
        str(path.relative_to(REPO_ROOT))
        for path in (_COMMAND, _AGENT)
        if not any(
            "as-built" in line.lower() and "deferral" in line.lower()
            for line in _text(path).splitlines()
        )
    ]
    assert not missing, (
        f"{missing} state the as-built record without its deferral escape on the "
        "same line. These are the surfaces that operate the gate, and either one "
        "can name both words for unrelated reasons — so the record step must "
        "carry the escape where a reader meets it, or the gate is only in the "
        "skill (CAL-972)."
    )
