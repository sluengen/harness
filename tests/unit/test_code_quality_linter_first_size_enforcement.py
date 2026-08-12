"""#185 — ``code-quality`` Part C: a linter enforces the file-size limit where it can.

The Part C size rule (CAL-666) requires an over-limit file to carry a ``size:``
justification, and the presence/substance amendment (CAL-1155) mechanized
*presence* as a tree-walking repo test. What neither said is which mechanism to
reach for first: where the repo's linter already implements a file-length rule
(``max-lines`` in ESLint or oxlint), turning that rule on beats writing a
bespoke walker — it runs with the rest of lint on every commit, and its
escape hatch (an inline disable carrying the ``size:`` reason) has a property
the walker cannot offer: an unused disable is itself reported, so a file that
shrinks back under the limit cannot silently keep its exemption.

In nano-erp a 725-line file (44% over the hard limit) passed both a review and
a green gate, and a repo-wide grep for the ``// size:`` marker returned zero
matches — the rule was enforced only by the weekly advisory pass. The steward
is the backstop where no linter and no walker can run, not the primary.

This guard is a text-parse content check in the style of
``test_code_quality_marker_presence_mechanized`` (CAL-1155): it reads the
as-built guidance and asserts the note is present in the Part C verification
gate, so a future re-edit cannot silently drop it.

Acceptance criteria (this ticket):

* **AC-1** — Part C states that where a linter can enforce the file-size limit,
  it should, naming the rule. Proven by :func:`test_linter_is_preferred_where_it_can_enforce`.
* **AC-2** — Part C states the escape hatch is an auditable inline disable
  carrying the ``size:`` reason, and that an unused disable is itself reported.
  Proven by :func:`test_escape_hatch_is_an_auditable_disable`.
* **AC-3** — Part C states the steward is the backstop only where the
  mechanical checks cannot run. Proven by :func:`test_steward_is_the_backstop_not_the_primary`.
"""

from __future__ import annotations

from pathlib import Path

# ``tests/unit/test_*.py`` → ``parents[2]`` is the repo (or worktree) root.
_REPO_ROOT = Path(__file__).resolve().parents[2]
_SKILL = _REPO_ROOT / "skills" / "code-quality" / "references" / "specialized-verification.md"


def _part_c() -> str:
    """The '## Part C' verification section — to end of file."""
    text = _SKILL.read_text(encoding="utf-8")
    start = text.find("## Part C")
    assert start != -1, "code-quality must have a '## Part C' verification section"
    return text[start:]


def test_linter_is_preferred_where_it_can_enforce() -> None:
    """Part C prefers a linter rule over a bespoke walker where one exists (AC-1)."""
    part_c = _part_c()
    lower = part_c.lower()
    assert "linter" in lower, (
        "Part C must name the linter as the mechanism that enforces the file-size "
        "limit where it can (#185)"
    )
    assert "max-lines" in lower, (
        "Part C must name the concrete rule (`max-lines`) so an adopting repo can "
        "turn it on without guessing"
    )


def test_escape_hatch_is_an_auditable_disable() -> None:
    """Part C states the disable carries the reason and an unused one is reported (AC-2)."""
    part_c = _part_c()
    lower = part_c.lower()
    assert "disable" in lower, (
        "Part C must state the linter escape hatch is an inline rule-disable, so an "
        "over-limit file is still an auditable choice"
    )
    assert "unused" in lower, (
        "Part C must state that an *unused* disable is itself reported — the property "
        "that stops a file which shrank back from silently keeping its exemption"
    )


def test_steward_is_the_backstop_not_the_primary() -> None:
    """Part C states the steward is the backstop where mechanization cannot run (AC-3)."""
    part_c = _part_c()
    lower = part_c.lower()
    assert "backstop" in lower, (
        "Part C must place the steward as the backstop for repos where no linter "
        "rule and no walker can enforce the limit — not as the primary enforcement"
    )
