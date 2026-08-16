"""CAL-815 / #459 — the architecture watchlist mechanism and its review trigger.

Raised from the architecture-review follow-up (2026-06-19): an opportunistic
"refactor when you touch a gravity well" instruction is unreliable in a fully
agentic system when the trigger lives only in conversational memory. The change
made an optional, repo-local ``architecture_watchlist`` first-class: when the
planned or actual touched files intersect it, the change spec and the review must
carry a ``Watchlist trigger`` section that either includes a small
behavior-preserving seam extraction or records why extraction is deferred.

The mechanism has ONE canonical home — ``skills/architecture/SKILL.md`` — and the
CONTEXT shape (``templates/CONTEXT.template.md``), the builder (``spec-authoring``
+ ``templates/change.md``), the reviewer (``review-discipline``), and the steward
(``agents/steward.md``) reference it rather than re-stating it.

**What this module asserts, after #459.** Two tripwires — one per rule-home —
alongside the exclusivity, correspondence and negative-space guards that were
already the target shape (ADR 0016, ``code-quality`` Part C → *A guard over prose
owns structure and negative space, never meaning*):

* **The mechanism**, in ``skills/architecture/SKILL.md`` § *Architecture
  watchlist*. Term set: the repo-local key, the section a triggered change
  carries, and the two outcomes (``seam`` / ``defer``), plus ``no-op`` for the
  repo that never opts in. Polarity: *an unrecorded one is not* — the clause
  that makes recording mandatory. Both outcomes being valid is the whole rule's
  permissiveness, and without the refusal that follows it the section reads as
  "extract or defer, or neither", which is the pre-mechanism status quo.
* **The review trigger**, in ``review-discipline``'s Stage-2
  ``- **Architecture watchlist**`` bullet. Term set: the key, the ``diff``
  comparison, and the two outcomes. Polarity: *with **neither** recorded is a
  **Medium** structural finding* — the negation anchored to what is recorded,
  which is what turns the reviewer's read into a finding rather than a note.

What went: six section term pins over one home (the mechanism, the second-seam
rule, the diff/fallback pair, the design-stage carrier, the no-op/preservation
pair, and the steward routing) collapse into the first tripwire; the whole-file
co-occurrence that stood for steward routing goes with them. The three
``test_smoke_*`` cases and their ``_watchlist_triggers`` fixture go outright:
the fixture is an ``fnmatch`` demo defined in this file and asserted against
itself, so it exercises no production path and can only fail if its own three
lines are edited — ``craft.md`` → *Exercise the production path, not merely a
production constant*.

**This module exports ``_review_watchlist_bullet``**, imported by
``test_review_discipline_watchlist_entry_currency`` and
``test_review_discipline_extraction_test_home``, which read two later clauses of
the same bullet.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
ARCHITECTURE = REPO_ROOT / "skills" / "architecture" / "SKILL.md"
SPEC_AUTHORING = REPO_ROOT / "skills" / "spec-authoring" / "SKILL.md"
REVIEW_DISCIPLINE = (
    REPO_ROOT
    / "skills"
    / "review-discipline"
    / "references"
    / "diff-shape-checks.md"
)
CONTEXT_TEMPLATE = REPO_ROOT / "templates" / "CONTEXT.template.md"
CHANGE_TEMPLATE = REPO_ROOT / "templates" / "change.md"
STEWARD = REPO_ROOT / "agents" / "steward.md"
UPDATE_GUIDANCE = REPO_ROOT / "commands" / "update-guidance.md"

#: The canonical mechanism's section header — it lives in exactly one skill.
WATCHLIST_SECTION = "## Architecture watchlist"

#: The named section the change spec and the review must carry when a watchlisted
#: file is touched. Stable across the builder, reviewer, and template homes.
TRIGGER_SECTION = "Watchlist trigger"

#: The repo-local CONTEXT key carrying the gravity-well file list.
WATCHLIST_KEY = "architecture_watchlist"

#: The mechanism's term set: the repo-local key, the section a triggered change
#: carries, the two outcomes, and the opt-out that makes the whole thing
#: optional.
_MECHANISM_TERMS = (WATCHLIST_KEY, TRIGGER_SECTION.lower(), "seam", "defer", "no-op")

#: The mechanism's polarity, with the negation **anchored to what it governs**.
#: A bare negation token would be satisfied anywhere in a 30-line section; this
#: only matches while an unrecorded outcome is still refused.
_UNRECORDED_IS_NOT = re.compile(r"\bunrecorded\b(?:\W+\w+){0,3}?\W+not\b", re.IGNORECASE)

#: The review trigger's term set: what it keys off, what it compares, and the
#: two outcomes it accepts.
_REVIEW_TRIGGER_TERMS = (WATCHLIST_KEY, "diff", "seam", "defer")

#: The review trigger's polarity, with the negation **anchored to the recording
#: it governs**. This is what makes an unhandled watchlisted file a finding
#: rather than an observation, and it is the half an edit drops while keeping
#: every term above.
_NEITHER_RECORDED = re.compile(
    r"\bneither\b(?:\W+\w+){0,2}?\W+recorded\b", re.IGNORECASE
)


def _section(text: str, header: str) -> str:
    """The body of a ``## ``-level markdown section, header to next ``## ``."""
    m = re.search(rf"^{re.escape(header)}\b.*$", text, re.MULTILINE)
    assert m, f"missing section header {header!r}"
    rest = text[m.end() :]
    end = re.search(r"^## ", rest, re.MULTILINE)
    return rest[: end.start()] if end else rest


def _review_watchlist_bullet(text: str) -> str:
    """The Stage-2 ``- **Architecture watchlist**`` bullet, to the next bullet/heading."""
    m = re.search(r"^- \*\*Architecture watchlist\*\*", text, re.MULTILINE)
    assert m, (
        "review-discipline Stage 2 has no '- **Architecture watchlist**' check "
        "(CAL-815 AC-3)."
    )
    rest = text[m.end() :]
    end = re.search(r"^(?:- \*\*|## |### )", rest, re.MULTILINE)
    return rest[: end.start()] if end else rest


# --- AC-1: the mechanism is documented, with one canonical home ---------------


def test_the_watchlist_mechanism_refuses_an_unrecorded_outcome() -> None:
    """The mechanism names its key, its section, its two outcomes — and refuses neither.

    The section is deliberately permissive: a seam extraction and a recorded
    deferral are equally valid, and a repo that never opts in is untouched. All
    of that survives a rewrite that quietly drops the one sentence making the
    record mandatory, which is why the refusal is asserted rather than the
    permission (AC-1/AC-6).
    """
    block = _section(ARCHITECTURE.read_text(), WATCHLIST_SECTION).lower()

    missing = [t for t in _MECHANISM_TERMS if t not in block]
    assert not missing, (
        f"the Architecture watchlist section no longer states {missing}. The "
        f"repo-local key is what a repo opts in with, the `Watchlist trigger` "
        f"section is what a triggered change carries, the two outcomes are what "
        f"may go in it, and the no-op is what keeps the mechanism optional "
        f"(AC-1/AC-6)."
    )
    assert _UNRECORDED_IS_NOT.search(block), (
        "the section no longer refuses an *unrecorded* outcome. Either outcome "
        "being valid is the whole permissiveness of the rule; without the "
        "refusal that follows it, 'extract or defer' reads as optional and the "
        "mechanism is back to the conversational memory it replaced "
        "(CAL-815, #459)."
    )


def test_watchlist_section_lives_in_exactly_one_skill() -> None:
    """The mechanism has one canonical home — ``architecture`` — not many (lean/MECE)."""
    homes = sorted(
        str(p.relative_to(REPO_ROOT))
        for p in REPO_ROOT.glob("skills/*/SKILL.md")
        if WATCHLIST_SECTION in p.read_text()
    )
    assert homes == ["skills/architecture/SKILL.md"], (
        "the Architecture watchlist mechanism must have exactly one canonical "
        f"home (skills/architecture/SKILL.md); found in: {homes}."
    )


def test_the_watchlist_section_leaks_no_repo_source_paths() -> None:
    """Negative space: universal guidance names none of this repo's own paths (#251).

    The ban is on *this repo's own* paths appearing in universal guidance, and
    it is stated as a shape rather than as one literal: `harness/cli/` was the
    example when the rule was written, and #435 deleted that tree, which left
    the old single-literal assertion unfalsifiable. A repo-rooted source path is
    the shape — a leading `harness/`, `scripts/` or `tests/` segment inside a
    backticked token.
    """
    block = _section(ARCHITECTURE.read_text(), WATCHLIST_SECTION).lower()
    repo_paths = re.findall(r"`((?:harness|scripts|tests)/[^`]*)`", block)
    assert not repo_paths, (
        f"the section must stay capability-shaped — it names this repo's own "
        f"source paths {repo_paths} in universal guidance, which every consuming "
        f"repo receives and none of which has those files (#251)."
    )


def test_update_guidance_never_touches_context() -> None:
    """The preservation guarantee AC-6 rests on still holds in update-guidance."""
    text = UPDATE_GUIDANCE.read_text().lower()
    assert "never touch" in text and "context.md" in text, (
        "/update-guidance must still state it never touches CONTEXT.md — the "
        "guarantee that preserves repo-specific watchlist entries (AC-6)."
    )


# --- AC-1 shape: the CONTEXT template documents the optional block -------------


def test_context_template_documents_optional_watchlist_shape() -> None:
    """The CONTEXT template carries an optional `architecture_watchlist` block (AC-1)."""
    text = CONTEXT_TEMPLATE.read_text()
    assert WATCHLIST_KEY in text, (
        f"templates/CONTEXT.template.md must document the `{WATCHLIST_KEY}` shape "
        "(AC-1)."
    )
    # the block carries a `files:` list and is marked optional / no-op when absent.
    low = text.lower()
    assert "files" in low, "the watchlist block must show a `files:` list (AC-1)."
    assert "optional" in low or "no-op" in low, (
        "the watchlist block must be marked optional (omit it and the trigger is a "
        "no-op) (AC-1/AC-6)."
    )


# --- AC-2: the builder requires a Watchlist trigger section --------------------


def test_spec_authoring_requires_watchlist_trigger_section() -> None:
    """`spec-authoring` requires the change spec carry a Watchlist trigger section
    when the planned diff intersects the watchlist, and points at architecture (AC-2)."""
    text = SPEC_AUTHORING.read_text()
    assert TRIGGER_SECTION in text, (
        "spec-authoring must require a `Watchlist trigger` change-spec section "
        "(AC-2)."
    )
    assert WATCHLIST_KEY in text, (
        "spec-authoring must key the requirement off `architecture_watchlist` "
        "(AC-2)."
    )
    assert "architecture" in text, (
        "spec-authoring must reference the `architecture` mechanism rather than "
        "re-stating it (AC-2)."
    )


def test_change_template_has_watchlist_trigger_section() -> None:
    """`templates/change.md` makes the Watchlist trigger section first-class (AC-2)."""
    assert TRIGGER_SECTION in CHANGE_TEMPLATE.read_text(), (
        "templates/change.md must include a (conditional) `Watchlist trigger` "
        "section so the builder records the outcome (AC-2)."
    )


# --- AC-3: the reviewer flags an unhandled watchlisted file -------------------


def test_the_review_trigger_grades_an_unhandled_watchlisted_file() -> None:
    """The reviewer compares the actual diff against the watchlist, and neither is a finding.

    The bullet's term set says what to compare and what may be recorded. What
    makes it a *check* is the sentence grading the file that recorded neither —
    a co-occurrence of the same terms describes the mechanism just as well
    while obliging the reviewer to do nothing about it (AC-3).
    """
    block = _review_watchlist_bullet(REVIEW_DISCIPLINE.read_text()).lower()

    missing = [t for t in _REVIEW_TRIGGER_TERMS if t not in block]
    assert not missing, (
        f"the Stage-2 Architecture watchlist bullet no longer states {missing}. "
        f"Without the key it does not know which files are watchlisted, without "
        f"the diff it has no touched set, and without both outcomes it cannot "
        f"tell a handled touch from an unhandled one (AC-3)."
    )
    assert _NEITHER_RECORDED.search(block), (
        "the bullet no longer grades a watchlisted file that recorded *neither* "
        "outcome. That clause is the check: without it the reviewer reads the "
        "diff, observes the gravity well got heavier, and has no finding to "
        "raise (CAL-815 AC-3, #459)."
    )


# --- AC-4: changes are generic — no Slate-specific paths ----------------------

SURFACE = (
    ARCHITECTURE,
    SPEC_AUTHORING,
    REVIEW_DISCIPLINE,
    CONTEXT_TEMPLATE,
    CHANGE_TEMPLATE,
    STEWARD,
)
#: Slate-specific dogfood references that must not leak into universal guidance.
FORBIDDEN = ("slate", "passport", "0e5cd59", "mobile/lib")


def test_surface_changes_are_generic() -> None:
    """The command/skill/template changes name no Slate-specific paths (AC-4)."""
    for path in SURFACE:
        low = path.read_text().lower()
        leaked = [tok for tok in FORBIDDEN if tok in low]
        assert not leaked, (
            f"{path.relative_to(REPO_ROOT)} leaks Slate-specific reference(s) "
            f"{leaked} — the watchlist guidance must be generic (AC-4)."
        )
