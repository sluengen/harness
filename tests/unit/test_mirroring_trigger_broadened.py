"""#206 — broaden the mirroring self-admission trigger from helper to any duplicated unit.

From the form repo's `/assess code` steward pass (2026-07-24, CODE-INSIGHT-1;
originating Linear ticket CAL-1214). `code-quality`'s "Extract on the third
strike" admission-comment rule (CAL-800, pinned by
``test_mirrors_admission_third_strike.py``) is worded around "a helper
mirrors ... a sibling", which reads naturally as scoped to pure-logic
functions. The sibling ticket CAL-1213 (CODE-1, same assessment pass) is the
exact failure mode this framing invites: three UI components each carried a
doc comment admitting they mirror the previous one, yet the rule as worded
did not visibly apply to a component, so the trigger was never pulled across
three separate, individually-reasonable reviews.

The fix broadens the trigger's subject from "a helper" to "a helper,
component, or module", and states explicitly that the trigger applies to a
duplicated rendering/structural shell exactly as it applies to a duplicated
function — so a mirrored component or screen is caught by the same rule a
mirrored helper already was.

Acceptance criteria (this ticket):

* **AC-1** — the "Extract on the third strike" section names "component" and
  "module" as subjects of the mirrors/duplicates/kept-in-sync admission
  trigger, alongside "helper".
* **AC-2** — the section states the trigger applies to a duplicated
  rendering/structural shell exactly as it applies to a duplicated function.
"""

from __future__ import annotations

import re
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_CODE_QUALITY = _REPO_ROOT / "skills" / "code-quality" / "SKILL.md"


def _extract_section(text: str) -> str:
    """The 'Extract on the third strike' subsection of code-quality Part B."""
    m = re.search(r"^### Extract on the third strike\s*$", text, re.MULTILINE)
    assert m, "code-quality must have an '### Extract on the third strike' section"
    rest = text[m.end() :]
    end = re.search(r"^#{2,3} ", rest, re.MULTILINE)
    return rest[: end.start()] if end else rest


def test_admission_trigger_names_component_and_module() -> None:
    """The admission trigger's subject is broadened past "a helper" (AC-1)."""
    section = _extract_section(_CODE_QUALITY.read_text())
    low = section.lower()
    assert "component" in low and "module" in low, (
        "the admission trigger must name 'component' and 'module' alongside "
        f"'helper' as subjects that can mirror/duplicate a sibling (AC-1); got:\n{section}"
    )
    # The trigger phrase itself, not just an incidental mention elsewhere.
    trigger = re.search(
        r"a helper,\s*component,\s*or module\s+\*\*mirrors\*\*", section
    )
    assert trigger, (
        "the trigger phrase must read 'a helper, component, or module mirrors "
        f"...' (AC-1); got:\n{section}"
    )


def test_admission_trigger_covers_duplicated_rendering_shell() -> None:
    """The section states the trigger applies to a duplicated shell exactly as
    it applies to a duplicated function (AC-2)."""
    section = _extract_section(_CODE_QUALITY.read_text()).lower()
    assert "rendering" in section and "structural" in section, (
        "the section must call out a duplicated rendering/structural shell "
        f"as covered by the trigger (AC-2); got:\n{section}"
    )
    assert "exactly as it applies to a duplicated function" in section, (
        "the section must state the trigger applies to a duplicated shell "
        f"exactly as it applies to a duplicated function (AC-2); got:\n{section}"
    )
