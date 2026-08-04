"""#283 — edited as-built records must refresh their currency stamp.

The Stage-2 ``CONTEXT.md currency`` check already identifies diff shapes that
can stale repository configuration.  An as-built record has a separate,
equally local stale-data shape: editing its content while leaving its
``last_updated`` frontmatter unchanged.  This guard keeps that reviewer check
on the existing currency bullet, rather than turning it into a second,
unanchored file-wide requirement.
"""

from __future__ import annotations

from tests.unit.test_review_discipline_context_currency import (
    _context_currency_bullet,
    _skill_text,
)


def test_context_currency_rule_requires_an_edited_asbuilt_record_stamp() -> None:
    """The existing Stage-2 bullet covers all supported as-built record shapes."""
    bullet = _context_currency_bullet(_skill_text()).lower()

    for record in ("as-built record", "feature spec", "`spec.md`", "design-system layer"):
        assert record in bullet, (
            "the CONTEXT.md currency rule must name every as-built record "
            f"shape that needs a refreshed stamp; missing {record!r} (#283)"
        )

    assert "last_updated" in bullet, (
        "an edited as-built record must require its `last_updated` frontmatter "
        "stamp to move (#283)"
    )
    assert "same **medium** finding" in bullet, (
        "a stale as-built record stamp must fold into the existing Medium "
        "currency finding (#283)"
    )
