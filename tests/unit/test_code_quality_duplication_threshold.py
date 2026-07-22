"""#180 — scope discipline needs a numeric duplication threshold.

*Source:* nano-erp assessment ``assessments/2026-07-22-code.md``, systemic
insight CODE-INSIGHT-1 (nano-erp ERP-137). Per-ticket review sees only its own
diff, so it cannot notice that the Nth screen re-implemented a concern the
previous N-1 already implemented — "consider extracting" is what let five
copies land in nano-erp. A numeric threshold, checked before the helper is
even written, is what makes the duplication checkable at review time.

This guard pins the *presence* of that rule in the surface (the same honest
limit the removal-sweep and mirrors-admission guards state — it evidences the
rule, not that a grep was performed on any change).

Acceptance criteria (#180):

* **AC-1** — code-quality's scope-discipline section (Part A) tells builders
  to grep sibling modules for the concern a new helper would handle *before*
  writing it. Proven by :func:`test_code_quality_has_pre_write_grep_rule` and
  :func:`test_duplication_rule_in_scope_section`.
* **AC-2** — the rule states the numeric threshold: one existing near-identical
  copy must be named and justified in the change spec; two existing copies
  means extract now — the third copy is not a judgement call. Proven by
  :func:`test_duplication_rule_states_one_copy_case` and
  :func:`test_duplication_rule_states_two_copy_case`.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent.parent
CODE_QUALITY = REPO_ROOT / "skills" / "code-quality" / "SKILL.md"


def _code_quality_text() -> str:
    return CODE_QUALITY.read_text()


def _scope_section() -> str:
    text = _code_quality_text()
    m = re.search(r"^##\s+Part A\b.*Scope", text, re.MULTILINE)
    assert m, "code-quality must have a 'Part A — Scope' section."
    rest = text[m.end() :]
    nxt = re.search(r"^##\s+Part B\b", rest, re.MULTILINE)
    return rest[: nxt.start()] if nxt else rest


def test_code_quality_has_pre_write_grep_rule() -> None:
    """AC-1: the rule tells builders to grep sibling modules before writing a
    helper for the concern it would handle."""
    low = _scope_section().lower()
    assert "before writing a helper" in low, (
        "code-quality must tell builders to check for duplication 'before "
        "writing a helper' (#180 AC-1)."
    )
    assert "grep" in low and "sibling" in low, (
        "the rule must say to grep the sibling modules for the concern the "
        "new helper would handle (#180 AC-1)."
    )


def test_duplication_rule_in_scope_section() -> None:
    """AC-1 (placement): the rule sits inside 'Part A — Scope' discipline —
    checking for duplication before writing code is a scope-discipline concern,
    not a Part B structural cleanup."""
    section = _scope_section().lower()
    assert "before writing a helper" in section, (
        "the pre-write duplication-grep rule must live in the 'Part A — Scope' "
        "discipline (#180 AC-1 placement)."
    )


def test_duplication_rule_states_one_copy_case() -> None:
    """AC-2: a single near-identical existing copy must be named and justified
    in the change spec, not silently duplicated."""
    low = _scope_section().lower()
    assert "one other place" in low, (
        "the rule must state the one-copy case: a near-identical helper "
        "existing in one other place (#180 AC-2)."
    )
    assert "change spec" in low and "justified" in low, (
        "the one-copy case must require naming the existing helper in the "
        "change spec and saying why the copy is justified (#180 AC-2)."
    )


def test_duplication_rule_states_two_copy_case() -> None:
    """AC-2: two existing copies means extract now — the numeric threshold
    that makes the rule checkable, not a judgement call."""
    low = _scope_section().lower()
    assert "if it exists in two" in low or "exists in two" in low, (
        "the rule must state the two-copy case explicitly (#180 AC-2)."
    )
    assert "extract it" in low, (
        "the two-copy case must require extracting the helper (#180 AC-2)."
    )
    assert "third copy" in low and "not a judgement call" in low, (
        "the rule must state that a third copy is not a judgement call — the "
        "numeric threshold is the point (#180 AC-2)."
    )
