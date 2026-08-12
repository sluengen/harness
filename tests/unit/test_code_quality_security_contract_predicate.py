"""#183 — a security-contract test asserts the predicate, not the name.

*Source:* nano-erp assessment ``assessments/2026-07-22-code.md``, systemic
insight CODE-INSIGHT-1 (nano-erp ERP-150). The tenancy gate the whole repo
leans on (``test/catalog_security.test.ts``) verified a policy *called*
``tenant_fence`` exists — it never read ``qual``/``with_check``, so
``tenant_fence ... using (true)`` passed. Asserting a control exists by name
proves only that someone typed the right string; the predicate it evaluates
to is what a defect actually changes.

This guard pins the *presence* of that rule in the surface (the same honest
limit the sibling structural-rule guards state — it evidences the rule, not
that any given test in this repo follows it).

Acceptance criteria (#183):

* **AC-1** — code-quality's Part C — Verification states that a
  security-contract test must assert what the control *evaluates to*
  (a policy's ``USING``/``WITH CHECK`` expression, a guard's refusal, a
  directive's value), not merely that it exists by name or presence in a
  list. Proven by :func:`test_security_contract_rule_present` and
  :func:`test_security_contract_rule_names_predicate_not_presence`.
* **AC-2** — the rule requires pairing the assertion with a negative fixture
  whose control is present but wrong, and watching the test fail. Proven by
  :func:`test_security_contract_rule_requires_negative_fixture`.
* **AC-3** (placement) — the subsection sits in Part C — Verification,
  beside "A measurable criterion needs a measuring test". Proven by
  :func:`test_security_contract_rule_in_part_c`.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent.parent
CODE_QUALITY = REPO_ROOT / "skills" / "code-quality" / "references" / "specialized-verification.md"


def _code_quality_text() -> str:
    return CODE_QUALITY.read_text()


def _part_c_section() -> str:
    text = _code_quality_text()
    m = re.search(r"^##\s+Part C\b", text, re.MULTILINE)
    assert m, "code-quality must have a 'Part C — Verification' section."
    rest = text[m.end() :]
    nxt = re.search(r"^##\s+Part D\b", rest, re.MULTILINE)
    return rest[: nxt.start()] if nxt else rest


def test_security_contract_rule_present() -> None:
    """AC-1: the rule is present and named for what it is."""
    low = _part_c_section().lower()
    assert "security-contract test asserts the predicate, not the name" in low, (
        "code-quality must state that a security-contract test asserts the "
        "predicate, not the name (#183 AC-1)."
    )


def test_security_contract_rule_names_predicate_not_presence() -> None:
    """AC-1: the rule says to assert what the control evaluates to, not
    merely that it exists by name or presence in a list."""
    low = _part_c_section().lower()
    assert "exists" in low and "by name" in low, (
        "the rule must call out that asserting a control exists 'by name' "
        "proves only that someone typed the right string (#183 AC-1)."
    )
    assert "using" in low and "with check" in low, (
        "the rule must name the concrete predicate a security-contract test "
        "should assert, e.g. an RLS policy's USING/WITH CHECK expression "
        "(#183 AC-1)."
    )


def test_security_contract_rule_requires_negative_fixture() -> None:
    """AC-2: the rule requires a negative fixture whose control is present
    but wrong, and watching the test fail."""
    low = _part_c_section().lower()
    assert "negative fixture" in low, (
        "the rule must require pairing the assertion with a negative "
        "fixture (#183 AC-2)."
    )
    assert "present but" in low and "wrong" in low, (
        "the negative fixture must have a control that is present but "
        "wrong (#183 AC-2)."
    )


def test_security_contract_rule_in_specialized_part_c() -> None:
    """AC-3 (placement): the subsection sits in the conditional Part C reference."""
    section = _part_c_section().lower()
    assert "security-contract test asserts the predicate, not the name" in section, (
        "the security-contract-predicate rule must live in 'Part C — "
        "Verification' (#183 AC-3 placement)."
    )
    core = (REPO_ROOT / "skills" / "code-quality" / "SKILL.md").read_text()
    assert "references/specialized-verification.md" in core, (
        "the hot code-quality skill must link the conditional verification reference"
    )
