"""#273 — a seam extraction must refresh the watchlist entry it invalidates.

Two adjacent Stage-2 bullets in ``review-discipline`` check different things
about the same touch, and neither covered the space between them. **Architecture
watchlist** checks that a *decision* was recorded (a seam extraction, or a
deferral with a reason). **CONTEXT.md currency** checks the ``stack`` /
``commands`` / ``layers`` blocks, on a trigger list — a test runner, a gate
step, a workspace, a top-level path — that is deliberately narrow and does not
reach the ``architecture_watchlist`` block at all.

So a change could record its ``Watchlist trigger`` correctly, pass both bullets,
and leave the watchlist entry describing a decomposition and a size state that
the extraction had just replaced. That happened three times running in this repo
(#262, #263, #270) and produced #272 — including an entry that ended up stating
the *opposite* of the truth, claiming a file had retired its ``# size:``
justification when the intervening change had re-added it.

The fix is one clause on the **Architecture watchlist** bullet, not a fifth
trigger on **CONTEXT.md currency**: that bullet's narrowness is load-bearing and
says so in its own text ("it is not 'read ``CONTEXT.md`` every time'"). The
watchlist bullet already has the changed file set in hand from its own
``git diff --name-only`` comparison, so the confirmation costs nothing extra to
run, and a stale entry folds into the Medium finding the bullet already grades.

This guard is the universal half; the local mechanization it once sat beside
(#272) is gone — but no consuming repo was ever assumed to have such a guard,
and the checklist clause is what covers them. Mechanizing it further is
explicitly out of scope: the watchlist discipline is reviewer judgement by
design.

Acceptance criteria (this ticket):

* **AC-1** — the clause lives on the **Architecture watchlist** bullet and the
  guidance version stamp is bumped. The stamp half needs no new test: the
  durable, base-independent invariant is header ↔ registry parity, already
  asserted by
  ``test_review_discipline_backend_module_clone::test_review_discipline_header_matches_registry``
  and the tree-wide sweep in ``test_guidance_source``, so a stamp edited without
  its registry entry (or vice versa) goes red there. The clause half is proven
  by :func:`test_watchlist_bullet_requires_refreshing_the_context_entry`.
* **AC-2** — the assertion is *anchored to that bullet*, not a bare substring
  match over the file. Proven by
  :func:`test_the_clause_lives_inside_the_watchlist_bullet` and
  :func:`test_the_refresh_obligation_is_bound_to_the_extraction_outcome`.
* **AC-3** — the verify gate is green (the gate, not a test).

Why the tokens below and not the obvious ones: the pre-change bullet already
contains ``CONTEXT.md``, ``architecture_watchlist.files``, ``seam extraction``,
``diff``, ``deferral`` and ``Medium``. A guard keyed on any of those is green
against the *unmodified* file and measures nothing. Each token asserted here was
confirmed absent from the bullet before the clause was written.
"""

from __future__ import annotations

import re
from pathlib import Path

# Reuse the slicer rather than declaring a fourth private copy: a copy can drift
# from the anchor it slices on and produce a confident false green — the exact
# argument #272's guard recorded. This one carries its own CAL-815 assertion, so
# a renamed or deleted bullet fires there instead of silently measuring nothing.
from tests.unit.test_architecture_watchlist import _review_watchlist_bullet

# ``tests/unit/test_*.py`` → ``parents[2]`` is the repo (or worktree) root.
_REPO_ROOT = Path(__file__).resolve().parents[2]
_SKILL = _REPO_ROOT / "skills" / "review-discipline" / "references" / "diff-shape-checks.md"

# The neighbouring bullet. Its title must never appear inside our slice — if it
# does, the slicer over-ran and every token below could be satisfied by *that*
# bullet's prose instead of ours.
_NEIGHBOUR_TITLE = "**CONTEXT.md currency**"

# Split on sentence boundaries, requiring the next sentence to open with a
# capital, a backtick, or an emphasis marker. That keeps `CONTEXT.md`,
# `architecture_watchlist.files` and `code-quality`-style references intact,
# since each continues in lower case.
_SENTENCE_BREAK = re.compile(r"(?<=[.!?])\s+(?=[A-Z`*(])")


def _bullet() -> str:
    return _review_watchlist_bullet(_SKILL.read_text(encoding="utf-8"))


def _sentences(text: str) -> list[str]:
    return [s.strip() for s in _SENTENCE_BREAK.split(text.strip()) if s.strip()]


def test_watchlist_bullet_requires_refreshing_the_context_entry() -> None:
    """The bullet obliges a check of the watchlist entry's own prose (AC-1)."""
    bullet = _bullet().lower()

    # What is refreshed is the *entry's* descriptive comment, not `CONTEXT.md`
    # generally — that distinction is what keeps this off `:48`'s trigger list.
    assert "entry" in bullet, (
        "the Architecture watchlist bullet must name the "
        "`architecture_watchlist.files` *entry* as the thing to confirm — "
        "refreshing `CONTEXT.md` generally is the neighbouring bullet's job, "
        "and its narrowness is deliberate (#273)"
    )
    # The two facts an extraction invalidates, and the two #272 got wrong.
    assert "decomposition" in bullet, (
        "the bullet must require confirming the entry still names the file's "
        "current *decomposition* — the modules carved out of it (#273)"
    )
    assert "size" in bullet, (
        "the bullet must require confirming the entry still names the file's "
        "current *size state*: #272's entry claimed a `size:` justification had "
        "been retired while the file still carried one (#273)"
    )
    # Folded into the finding the bullet already grades — one finding, not a
    # second checklist item with its own severity.
    assert "medium" in bullet, (
        "a stale watchlist entry must fold into the bullet's existing Medium "
        "structural finding, not introduce a new severity (#273)"
    )


def test_the_refresh_obligation_is_bound_to_the_extraction_outcome() -> None:
    """The refresh is owed on an *extraction*, not on every watchlist touch (AC-2).

    A deferral carves nothing out, so the entry's description of the
    decomposition is still whatever it was. A clause demanding the refresh on
    every touch would satisfy the token test above and fail here — and it should,
    because that is the drift toward "read `CONTEXT.md` every time" that the
    neighbouring bullet rules out in its own text.
    """
    bearing = [s for s in _sentences(_bullet()) if "decomposition" in s.lower()]
    assert bearing, (
        "no sentence in the Architecture watchlist bullet names the entry's "
        "decomposition — the obligation this ticket adds is missing (#273)"
    )
    for sentence in bearing:
        assert "extraction" in sentence.lower(), (
            "the refresh obligation must be bound to the seam-extraction "
            "outcome in the sentence that states it, not merely co-present in "
            "the bullet; an unbound clause reads as 'refresh on every watchlist "
            f"touch' (#273). Offending sentence: {sentence!r}"
        )


def test_the_clause_lives_inside_the_watchlist_bullet() -> None:
    """The claim is anchored to `:47`, not matched anywhere in the file (AC-2)."""
    text = _SKILL.read_text(encoding="utf-8")
    bullet = _bullet()

    assert bullet.strip(), (
        "the Architecture watchlist slice is empty — the guard would assert "
        "nothing (#273)"
    )
    assert len(bullet) < len(text), (
        "the Architecture watchlist slice spans the whole skill file, so every "
        "assertion above degenerates into a file-wide substring match (#273)"
    )
    assert _NEIGHBOUR_TITLE not in bullet, (
        f"the slice ran past the bullet into {_NEIGHBOUR_TITLE} — that bullet's "
        "own `CONTEXT.md` and stale-entry prose would satisfy the tokens above "
        "without the clause existing at all (#273)"
    )
    # And the neighbour is genuinely a separate bullet in the file, so the
    # exclusion above is a real boundary rather than a vacuous one.
    assert _NEIGHBOUR_TITLE in text, (
        f"{_NEIGHBOUR_TITLE} is no longer a Stage-2 bullet, so excluding it "
        "from the slice proves nothing — re-anchor this guard (#273)"
    )


def test_the_bullet_still_ends_with_its_no_op_scope_statement() -> None:
    """The opt-out sentence stays terminal, so it governs the new clause too.

    The bullet's scope statement — a repo with no `architecture_watchlist` skips
    the check — is stated last and therefore covers everything above it. The one
    structural way this edit could go wrong is stranding the clause *after* it,
    which would read as obliging a repo that has no watchlist at all.
    """
    sentences = _sentences(_bullet())
    assert sentences, "the Architecture watchlist bullet is empty (#273)"
    last = sentences[-1].lower()
    assert "skips this check" in last and "no-op" in last, (
        "the bullet's no-op scope statement must stay its final sentence so it "
        "governs the new clause; a clause appended after it reads as binding on "
        f"a repo with no `architecture_watchlist` (#273). Final sentence: "
        f"{sentences[-1]!r}"
    )
