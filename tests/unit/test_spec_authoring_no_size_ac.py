"""CAL-1155 — ``spec-authoring``: file size is never an AC; renegotiation lives on the ticket.

From proposal ``size-criterion-process`` (accepted 2026-07-17). A prior ticket
shipped Done against the criterion "review.py under 500 lines" while the file
stood at 759: a raw line count landed as an acceptance criterion with no
measuring test, and the builder's correct renegotiation lived only in a commit
body where the tracker could not see it.

The proposal's rule, stated from the change-spec author's vantage: a change spec
states the *structural outcome* a size target is a proxy for, never a raw line
count; and a builder who finds a criterion wrong mid-build renegotiates it *on
the ticket* (comment with the evidence, amend the criterion there, then build to
the amended spec) before any Done claim — not silently in a commit body.

This guard is a text-parse content check in the style of
``test_code_quality_size_justification`` (CAL-666): it reads the as-built
guidance and asserts the rule is present in the change-spec section, so a future
re-edit cannot silently drop it.

Acceptance criteria (this ticket):

* **AC-1** — ``spec-authoring`` states file size is never an acceptance
  criterion, naming the structural-outcome alternative. Proven by
  :func:`test_size_is_never_an_acceptance_criterion`.
* **AC-2** — the renegotiation protocol lives in the change-spec section:
  renegotiate on the Linear issue before any Done claim; a commit-body-only
  amendment is not the record. Proven by
  :func:`test_renegotiation_lives_on_the_ticket`.
"""

from __future__ import annotations

from pathlib import Path

# ``tests/unit/test_*.py`` → ``parents[2]`` is the repo (or worktree) root.
_REPO_ROOT = Path(__file__).resolve().parents[2]
_SKILL = _REPO_ROOT / "skills" / "spec-authoring" / "SKILL.md"


def _skill_text() -> str:
    return _SKILL.read_text(encoding="utf-8")


def _change_spec_section() -> str:
    """The '## Change spec' section — up to the next '## Feature spec' heading."""
    text = _skill_text()
    start = text.find("## Change spec")
    assert start != -1, "spec-authoring must have a '## Change spec' section"
    end = text.find("## Feature spec", start)
    assert end != -1, "spec-authoring must have a '## Feature spec' heading after it"
    return text[start:end]


def test_size_is_never_an_acceptance_criterion() -> None:
    """The change-spec section forbids a raw size AC, naming the alternative (AC-1)."""
    section = _change_spec_section()
    lower = section.lower()
    assert "file size is never an acceptance criterion" in lower, (
        "spec-authoring's change-spec section must state that file size is never "
        "an acceptance criterion (proposal size-criterion-process)"
    )
    # The sanctioned alternative is the structural outcome the size was a proxy for.
    assert "structural outcome" in lower, (
        "the rule must name the structural-outcome alternative to a raw line count"
    )


def test_renegotiation_lives_on_the_ticket() -> None:
    """A mid-build criterion change is renegotiated on the ticket, not a commit (AC-2)."""
    section = _change_spec_section()
    lower = section.lower()
    # The move has a name and a home (the Linear issue / ticket).
    assert "renegotiat" in lower, (
        "the change-spec section must name the renegotiation move for a criterion "
        "found wrong mid-build"
    )
    assert "linear" in lower or "ticket" in lower, (
        "renegotiation must be recorded on the Linear issue / ticket"
    )
    # It happens before any Done claim...
    assert "done" in lower, (
        "renegotiation must precede any Done claim, so the canonical record is right"
    )
    # ...and a commit-body-only argument is explicitly not the record.
    assert "commit body" in lower, (
        "the rule must call out that a commit-body-only argument leaves the "
        "tracker's criterion wrong"
    )
