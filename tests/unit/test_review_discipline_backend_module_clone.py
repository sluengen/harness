"""#209 — extend review-discipline's sibling-duplication check to backend
module files.

*Origin:* filed by ``/assess code`` in nano-erp (steward, 2026-07-24, systemic
insight CODE-INSIGHT-2; tracked as ``ERP-179`` in nano-erp's Linear).
``review-discipline``'s only mechanized check for the "new code copies a
sibling's helper instead of extracting it" shape was **Misplaced pure
helper** (CAL-796/CAL-823), scoped to frontend view/screen files under a
``lib/`` coverage ratchet — there was no equivalent instruction for a
reviewer looking at a new backend module (nano-erp's evidence: ``GetOrgConfig``
in ``inventory/acceptHook.ts`` mirroring ``quotes/service.ts``;
``asNullableString``/``requireName`` in ``procurement/input.ts`` duplicating
``customers/input.ts``). This adds a sibling Stage 2 bullet for backend
modules, alongside Misplaced pure helper, in the same style as its precedent
guards (``test_review_discipline_misplaced_helper.py``, CAL-823).

Acceptance criteria (#209):

* **AC-1** — ``review-discipline`` Stage 2 carries a rule that a new backend
  module's declared function/type names must be grepped against sibling
  modules; a name that already exists in a sibling with a matching signature
  is a clone that belongs in a shared home, not copied module-to-module.
  Proven by :func:`test_review_discipline_has_backend_module_clone_rule`.
* **AC-2** — the rule sits in Stage 2 quality, beside Misplaced pure helper,
  not buried elsewhere. Proven by
  :func:`test_backend_module_clone_rule_is_in_stage_two`.
* **AC-3** — ``review-discipline``'s ``guidance:`` header version and its
  ``registry.yaml`` entry are bumped consistently. Proven by
  :func:`test_review_discipline_header_matches_registry`.
"""

from __future__ import annotations

import re
from pathlib import Path

# ``tests/unit/test_*.py`` → ``parents[2]`` is the repo (or worktree) root.
_REPO_ROOT = Path(__file__).resolve().parents[2]
_SKILL = _REPO_ROOT / "skills" / "review-discipline" / "SKILL.md"
_REGISTRY = _REPO_ROOT / "registry.yaml"

_HEADER_RE = re.compile(r"<!--\s*guidance:[\w-]+@([\d.]+)\s*-->")


def _skill_text() -> str:
    return _SKILL.read_text(encoding="utf-8")


def _header_version(path: Path) -> str:
    m = _HEADER_RE.search(path.read_text())
    assert m, f"{path} must carry a guidance: header"
    return m.group(1)


def _registry_version(rel_path: str) -> str:
    text = _REGISTRY.read_text()
    m = re.search(
        rf"^\s*{re.escape(rel_path)}:.*?version:\s*([\d.]+)", text, re.MULTILINE
    )
    assert m, f"{rel_path} must have a registry.yaml files: entry"
    return m.group(1)


def _stage_two(text: str) -> str:
    """review-discipline's Stage 2 quality body (where structural checks live)."""
    start = text.index("### Stage 2")
    end = text.index("## Severity", start)
    return text[start:end]


def _backend_module_clone_bullet(text: str) -> str:
    """The Stage 2 bullet for the backend-module-clone rule.

    Find the ``- **...**`` bullet that follows "Misplaced pure helper" and
    slice to the next top-level bullet or heading, mirroring
    ``_misplaced_helper_bullet`` in ``test_review_discipline_misplaced_helper.py``.
    """
    stage_two = _stage_two(text)
    anchor = re.search(r"^- \*\*Misplaced pure helper\*\*", stage_two, re.MULTILINE)
    assert anchor, (
        "review-discipline Stage 2 must still carry the Misplaced-pure-helper "
        "bullet this rule sits beside (CAL-796/CAL-823)."
    )
    rest = stage_two[anchor.end() :]
    m = re.search(r"^- \*\*(?!Misplaced pure helper)", rest, re.MULTILINE)
    assert m, (
        "review-discipline Stage 2 has no bullet following Misplaced pure "
        "helper naming the backend-module-clone rule (#209 AC-1)."
    )
    nxt = re.search(r"^(?:- \*\*|#{2,3} )", rest[m.start() + 1 :], re.MULTILINE)
    end = m.start() + 1 + nxt.start() if nxt else len(rest)
    return rest[m.start() : end]


def test_review_discipline_has_backend_module_clone_rule() -> None:
    """The skill states the backend-module-clone rule (AC-1)."""
    bullet = _backend_module_clone_bullet(_skill_text()).lower()
    # It is about a new backend *module*...
    assert "module" in bullet, "the rule must name a new backend module"
    # ...whose declared names must be grepped against *sibling* modules...
    assert "sibling" in bullet, (
        "the rule must compare against sibling modules, the reuse signal"
    )
    assert "grep" in bullet, (
        "the rule must instruct grepping declared names against siblings, "
        "in the style of its precedent structural checks"
    )
    # ...where a match is a clone, not a coincidence...
    assert "clone" in bullet and "coincidence" in bullet, (
        "a name that already exists in a sibling module must be named a "
        "clone, not a coincidence"
    )
    # ...that belongs in a shared home, not copied module-to-module.
    assert "shared home" in bullet, (
        "the rule must send the clone to a shared home, not leave it copied"
    )
    assert "module-to-module" in bullet, (
        "the rule must reject copying the helper/type module-to-module"
    )


def test_backend_module_clone_rule_is_in_stage_two() -> None:
    """AC-2: the rule sits in Stage 2 quality, beside Misplaced pure helper."""
    text = _skill_text()
    stage_two_start = text.find("### Stage 2")
    assert stage_two_start != -1, "review-discipline must have a Stage 2 section"
    severity_start = text.find("## Severity")
    assert severity_start != -1, "review-discipline must have a Severity section"
    stage_two = text[stage_two_start:severity_start]
    misplaced_idx = stage_two.find("**Misplaced pure helper**")
    assert misplaced_idx != -1, (
        "Stage 2 must still carry the Misplaced-pure-helper bullet"
    )
    # the new bullet must appear, and after Misplaced pure helper (siblings)
    bullet = _backend_module_clone_bullet(text)
    assert bullet.strip(), "the backend-module-clone bullet must be non-empty"
    assert stage_two.index(bullet.strip()[:20]) > misplaced_idx, (
        "the backend-module-clone rule must sit after Misplaced pure helper, "
        "as its sibling structural check"
    )


def test_review_discipline_header_matches_registry() -> None:
    """AC-3: header + registry version parity."""
    assert _header_version(_SKILL) == _registry_version(
        "skills/review-discipline/SKILL.md"
    ), "review-discipline's guidance: header must match its registry.yaml version (#209 AC-3)."
