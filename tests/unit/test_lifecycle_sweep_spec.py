"""CAL-973 — require a lifecycle sweep in change-spec design sections.

*Source:* ``assessments/2026-07-03-full-review.md`` (CODE-INSIGHT-1, Medium —
systemic insight). One review pass surfaced three separate write/delete paths
that shipped their primary mutation but missed a *derived* artifact of the same
entity: a brew POST that never invalidated its cache, a deletion that never
revoked the entity's share token, and an anonymisation that filtered some
``use_count`` aggregates but not others. The class of defect is "a state change
that forgets its derived artifacts."

The fix is a guidance rule in ``spec-authoring``: a change spec's design section
must, for any state-changing operation, enumerate the derived artifacts of the
affected entity and say per artifact what happens to it — so the sweep happens
at spec time (where it is cheapest), not after review finds the gap.

This guard pins the *presence* of that rule in the surface. It cannot prove the
sweep was genuinely performed on any ticket (the same honest limit the grounding
guard states) — only that the rule the reviewer checks against is on record.

Acceptance criteria (CAL-973):

* **AC-1** — the upstream skill carries the exact rule wording.
  :func:`test_spec_authoring_has_lifecycle_sweep_rule`,
  :func:`test_lifecycle_sweep_names_derived_artifact_kinds`,
  :func:`test_lifecycle_sweep_unaffected_clause`.
* **AC-1 (placement)** — the rule lives in the change-spec design guidance, not
  some unrelated section. :func:`test_lifecycle_sweep_in_change_spec_section`.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent.parent
SPEC_AUTHORING = REPO_ROOT / "skills" / "spec-authoring" / "SKILL.md"


def _spec_authoring_text() -> str:
    return SPEC_AUTHORING.read_text()


def test_spec_authoring_has_lifecycle_sweep_rule() -> None:
    """AC-1: the skill states the rule — for any state-changing operation,
    enumerate the *derived artifacts* of the affected entity."""
    low = _spec_authoring_text().lower()
    assert "state-changing operation" in low, (
        "spec-authoring must scope the sweep to any 'state-changing operation' "
        "(CAL-973 AC-1)."
    )
    assert "derived artifact" in low, (
        "spec-authoring must require enumerating the 'derived artifacts' of the "
        "affected entity (CAL-973 AC-1)."
    )
    assert re.search(r"enumerate the .{0,40}derived artifact", low), (
        "the rule must say to *enumerate* the derived artifacts, not merely "
        "mention them (CAL-973 AC-1)."
    )


def test_lifecycle_sweep_names_derived_artifact_kinds() -> None:
    """AC-1: the rule names the concrete artifact kinds the class covers — caches /
    query keys, share tokens, counts / aggregates, sessions — so the checklist is
    actionable, not abstract. Each probe word is absent from the skill before this
    rule (``aggregate`` is used rather than ``count``, whose substring pre-exists in
    "accounts"), so the check is non-vacuous — drop the rule and it fails."""
    low = _spec_authoring_text().lower()
    kinds = ("cache", "share token", "aggregate", "session")
    missing = [k for k in kinds if k not in low]
    assert not missing, (
        "the lifecycle-sweep rule must name every derived-artifact kind "
        f"(caches/query keys, share tokens, counts/aggregates, sessions); "
        f"missing {missing} (CAL-973 AC-1)."
    )


def test_lifecycle_sweep_unaffected_clause() -> None:
    """AC-1: the rule closes the silence gap — 'Unaffected' is an acceptable answer,
    but saying nothing is not. This clause is what makes an omission a spec defect
    rather than an oversight."""
    low = _spec_authoring_text().lower()
    assert "unaffected" in low, (
        "the rule must allow 'Unaffected' as an explicit per-artifact answer "
        "(CAL-973 AC-1)."
    )
    assert "silence is not" in low, (
        "the rule must state that silence is not an acceptable answer "
        "(CAL-973 AC-1)."
    )


def test_lifecycle_sweep_in_change_spec_section() -> None:
    """AC-1 (placement): the rule sits inside the change-spec design guidance — the
    ``## Change spec`` section — not an unrelated part of the skill."""
    text = _spec_authoring_text()
    m = re.search(r"^##\s+Change spec\b", text, re.MULTILINE)
    assert m, "spec-authoring must have a '## Change spec' section."
    # bound the section to the next top-level heading
    rest = text[m.end():]
    nxt = re.search(r"^##\s+", rest, re.MULTILINE)
    section = rest[: nxt.start()] if nxt else rest
    assert "derived artifact" in section.lower(), (
        "the lifecycle-sweep rule must live in the '## Change spec' design "
        "guidance (CAL-973 AC-1 placement)."
    )
