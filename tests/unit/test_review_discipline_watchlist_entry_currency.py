"""#273 / #459 — a seam extraction must refresh the watchlist entry it invalidates.

Two adjacent Stage-2 bullets in ``review-discipline`` check different things
about the same touch, and neither covered the space between them. **Architecture
watchlist** checks that a *decision* was recorded (a seam extraction, or a
deferral with a reason). **CONTEXT.md currency** checks the ``stack`` /
``commands`` / ``layers`` blocks, on a trigger list that is deliberately narrow
and does not reach the ``architecture_watchlist`` block at all.

So a change could record its ``Watchlist trigger`` correctly, pass both bullets,
and leave the watchlist entry describing a decomposition the extraction had just
replaced. That happened three times running in this repo (#262, #263, #270) —
including an entry that ended up stating the *opposite* of the truth. The fix is
one clause on the **Architecture watchlist** bullet, folded into the Medium
finding that bullet already grades.

**What this module asserts, after #459.** One tripwire over one clause-home
(ADR 0016, ``code-quality`` Part C → *A guard over prose owns structure and
negative space, never meaning*), plus the slicer-boundary controls that were
already the target shape:

1. **Anchor** — the ``- **Architecture watchlist**`` bullet, sliced by
   :func:`~tests.unit._prose.review_watchlist_bullet`, and
   narrowed again to the *sentences* naming the decomposition. The narrowing is
   load-bearing: the bullet is nearly two thousand characters and holds four
   separate obligations, so a bullet-wide term set is the over-wide unit
   ``craft.md`` → *The text unit is part of the predicate* names.
2. **Term set** — ``decomposition`` selects the clause; ``entry`` is what is
   refreshed, and it is the word that keeps this off the neighbouring bullet's
   territory (refreshing ``CONTEXT.md`` generally is that bullet's job, and its
   narrowness is deliberate).
3. **Polarity — there is none, and none is faked.** The clause is an obligation
   with no negation token: it says an extraction *also* confirms the entry. What
   carries direction instead is the **binding**, asserted as a relation rather
   than as co-presence — every sentence naming the decomposition must also name
   the extraction, so a clause demanding the refresh on *every* watchlist touch
   goes red. That is the drift toward "read `CONTEXT.md` every time" the
   neighbouring bullet rules out in its own text, and mutating a relation means
   mutating the relation, not the relata.

What went: the four-term bullet-wide pin (``entry`` / ``decomposition`` /
``size`` / ``medium``). ``medium`` is still measured over this same bullet by
``test_review_discipline_extraction_test_home``'s severity sweep, which asserts
the other three grades absent; the rest were positive-meaning pins.

**``sentences_on_break`` lives in :mod:`tests.unit._prose`** since #467, read
from there by this module, by ``test_review_discipline_extraction_test_home`` and
by ``test_v4_records_only_what_remains``.
"""

from __future__ import annotations

from tests.unit._prose import REPO_ROOT, review_watchlist_bullet, sentences_on_break

_SKILL = REPO_ROOT / "skills" / "review-discipline" / "references" / "diff-shape-checks.md"

# The neighbouring bullet. Its title must never appear inside our slice — if it
# does, the slicer over-ran and every token below could be satisfied by *that*
# bullet's prose instead of ours.
_NEIGHBOUR_TITLE = "**CONTEXT.md currency**"


def _bullet() -> str:
    return review_watchlist_bullet(_SKILL.read_text(encoding="utf-8"))


def test_the_entry_refresh_is_owed_on_a_seam_extraction() -> None:
    """The refresh is owed on an *extraction*, and what is refreshed is the entry.

    A deferral carves nothing out, so the entry's description of the
    decomposition is still whatever it was. The assertion is therefore a
    relation, not a co-occurrence: every sentence that names the decomposition
    must bind the obligation to the extraction outcome in that same sentence. A
    clause demanding the refresh on every watchlist touch satisfies any
    bullet-wide term set and fails here — and it should, because that is the
    drift toward "read `CONTEXT.md` every time" the neighbouring bullet rules
    out in its own text.
    """
    bearing = [s for s in sentences_on_break(_bullet()) if "decomposition" in s.lower()]
    assert bearing, (
        "no sentence in the Architecture watchlist bullet names the entry's "
        "decomposition — the obligation this clause adds is missing (#273)"
    )
    for sentence in bearing:
        assert "extraction" in sentence.lower(), (
            "the refresh obligation must be bound to the seam-extraction "
            "outcome in the sentence that states it, not merely co-present in "
            "the bullet; an unbound clause reads as 'refresh on every watchlist "
            f"touch' (#273). Offending sentence: {sentence!r}"
        )
    assert any("entry" in s.lower() for s in bearing), (
        "the sentences stating the refresh do not name the "
        "`architecture_watchlist.files` *entry* as the thing to confirm. "
        "Refreshing `CONTEXT.md` generally is the neighbouring bullet's job and "
        "its narrowness is deliberate, so an unqualified clause lands the "
        "obligation on the wrong rule (#273)"
    )


def test_the_clause_lives_inside_the_watchlist_bullet() -> None:
    """The claim is anchored to the bullet, not matched anywhere in the file (AC-2)."""
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
    sentences = sentences_on_break(_bullet())
    assert sentences, "the Architecture watchlist bullet is empty (#273)"
    last = sentences[-1].lower()
    assert "skips this check" in last and "no-op" in last, (
        "the bullet's no-op scope statement must stay its final sentence so it "
        "governs the new clause; a clause appended after it reads as binding on "
        f"a repo with no `architecture_watchlist` (#273). Final sentence: "
        f"{sentences[-1]!r}"
    )
