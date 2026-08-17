"""#209 / #459 — the Stage-2 **Cloned backend module helper** rule, as one tripwire.

*Origin:* filed by ``/assess code`` in nano-erp (steward, 2026-07-24).
``review-discipline``'s only mechanized check for the "new code copies a
sibling's helper instead of extracting it" shape was **Misplaced pure helper**,
scoped to frontend view/screen files under a ``lib/`` coverage ratchet — there
was no equivalent instruction for a reviewer looking at a new backend module.
This bullet is that sibling: grep the function and type names a new module
declares against the equivalent files in the modules beside it.

**What this module asserts, after #459.** One tripwire over one rule-home, plus
the version parity that is structural correspondence and stays (ADR 0016,
``code-quality`` Part C → *A guard over prose owns structure and negative space,
never meaning*):

1. **Anchor** — the ``- **Cloned backend module helper**`` bullet exists inside
   ``### Stage 2``, and the assertion reads only that slice. The pre-conversion
   slicer found the bullet *positionally*, as "the first bullet after Misplaced
   pure helper", which a correct insertion between them silently redirects —
   ``craft.md`` → *An ordinal reference into an enumeration is invalidated by a
   correct insertion*. It now anchors on the bullet's own title.
2. **Term set** — ``sibling``, ``grep``, ``shared home``: the comparison set,
   the mechanism, and the destination.
3. **Polarity** — ``a clone, not a coincidence``, with the negation anchored to
   the noun it governs. That is the rule's whole judgement call, resolved: a
   matching name in a sibling module is not to be explained away. An edit
   keeping every term above while allowing the coincidence reading inverts the
   rule and nothing else in the tree would notice.

What went: ``module``, ``clone``, ``coincidence`` and ``module-to-module`` as
separate literal pins, and ``test_backend_module_clone_rule_is_in_stage_two``,
which re-checked the placement the slicer enforces by construction *and* pinned
the ordinal described above.
"""

from __future__ import annotations

import re
from pathlib import Path

from tests.unit._prose import REPO_ROOT, diff_shape_checks_text, stage_two_bullet

_SKILL = REPO_ROOT / "skills" / "review-discipline" / "references" / "diff-shape-checks.md"
_REGISTRY = REPO_ROOT / "registry.yaml"

_HEADER_RE = re.compile(r"<!--\s*guidance:[\w-]+@([\d.]+)\s*-->")

_BULLET_TITLE = "Cloned backend module helper"

#: The comparison set, the mechanism, and the destination.
_TERMS = ("sibling", "grep", "shared home")

#: The judgement, with the negation **anchored to the noun it governs**. A bare
#: negation token would be satisfied by the grep recipe's own exclusion
#: (``| grep -v <this-module>``); this only matches while the bullet still
#: refuses to read a matching sibling name as coincidence.
_NOT_A_COINCIDENCE = re.compile(
    r"\bnot\b(?:\W+\w+){0,2}?\W+coincidence\b", re.IGNORECASE
)


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


def _bullet() -> str:
    return stage_two_bullet(diff_shape_checks_text(), _BULLET_TITLE)


def test_the_backend_clone_rule_sends_a_matching_sibling_name_to_a_shared_home() -> None:
    """A declared name that already exists in a sibling module is a clone, not a coincidence."""
    bullet = _bullet().lower()

    missing = [t for t in _TERMS if t not in bullet]
    assert not missing, (
        f"the Cloned backend module helper bullet no longer states {missing}. "
        f"Without the sibling comparison set the rule has nothing to grep "
        f"against, and without the shared home it names the defect and no fix "
        f"(#209)."
    )
    assert _NOT_A_COINCIDENCE.search(bullet), (
        "the bullet no longer calls a matching sibling name a clone rather than "
        "a coincidence. That refusal is the rule: each ticket introduces one "
        "module, so no single reviewer ever sees the third strike, and a "
        "reviewer permitted to read the match as coincidence never extracts "
        "anything (#209, #459)."
    )


def test_review_discipline_header_matches_registry() -> None:
    """AC-3: header + registry version parity."""
    assert _header_version(_SKILL) == _registry_version(
        "skills/review-discipline/references/diff-shape-checks.md"
    ), "review-discipline's guidance: header must match its registry.yaml version (#209 AC-3)."
