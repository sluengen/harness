"""#321 — per-ticket model tiering is retired, in the code and in the prose.

ADR 0005 carried two ``<dimension>:<tier>`` GitHub labels. ``build:`` was
consumed by nothing and set on 0 of 25 open issues; ``review:`` was a real
control signal that every recorded review resolved past to the same fallback,
while costing a tracker ``fetch_issue`` round-trip and five degradation branches
on the review path. The mechanism is deleted and the model is one configured
value, ``CONTEXT.md`` ``loop.review_model``.

Two acceptance criteria live here, and they measure different failure modes:

* **AC-5** — no live document still *asserts* a per-ticket review tier. Derived
  by search over the tracked tree, never from a list of the places the claim was
  made: the enumerated form of exactly this guard failed review twice in #294 by
  omitting a surface, and a list of where a claim *was* made is not a check on
  where it *can* be made.
* **AC-6** — ``resolve_model_tier`` and ``ModelTier`` resolve nowhere in
  ``harness/`` or ``tests/``, judged over the *tracked* tree (CAL-619): a symbol
  gone from the index must read as gone even if stale bytecode lingers.

The hard part of AC-5 is that most surviving mentions are **correct**: an
as-built record has to say the mechanism was retired, and a decision record has
to describe what it decided. So the predicate does not ban the vocabulary — it
requires every live mention to sit in a sentence that marks the retirement.
``test_prose_that_records_the_retirement_stays_legal`` is the negative control
that pins the difference, because a guard that would "fix" a true sentence is
worse than no guard: the fix is to weaken the true claim rather than the false
one.
"""

from __future__ import annotations

import re
from pathlib import Path

from tests._gitutil import tracked_files_under
from tests.unit.test_review_discipline_watchlist_entry_currency import _sentences

_REPO_ROOT = Path(__file__).resolve().parents[2]

#: This module names every banned token in order to look for it, so it is its own
#: worst offender and must never be its own subject.
_SELF = "tests/unit/test_model_tiering_retired.py"

#: Paths whose text is a **historical record** and may describe the mechanism as
#: it was, in the present tense of its own day. Exempt by *category*, not by
#: filename, so a new proposal or a new assessment is covered the day it lands
#: rather than the day someone extends a list. ``specs/decisions/0005-`` is the
#: ADR itself: it *is* the record of what was believed, and its own dated
#: superseding note is guarded separately below, so the exemption cannot go
#: silent.
_HISTORICAL_PREFIXES = (
    "CHANGELOG.md",
    "CHANGELOG-archive/",
    "changelog.d/",
    "assessments/",
    "specs/proposals/",
    "specs/retired/",
    "specs/decisions/0005-",
    "LOG.md",
)

#: The vocabulary of the retired mechanism. Both label families, the deleted
#: resolver, and the two prose forms the labels were described by — the ticket's
#: own ``grep`` used only the first group and so missed three live surfaces,
#: which is why the placeholder and prose forms are here too.
_TIER_TOKENS = re.compile(
    r"review:<tier>|build:<tier>|review:opus|build:opus|review:sonnet|build:sonnet"
    r"|resolve_model_tier|ModelTier"
    r"|per-ticket (?:model )?tier|model tiering",
    re.IGNORECASE,
)

#: Words that mark a sentence as *recording* the retirement rather than asserting
#: the mechanism. A live document may — and the as-built records must — say the
#: tier existed and no longer does.
#:
#: ``inert`` / ``nothing reads`` earn their place empirically: the negative
#: control below failed on "a `review:opus` label is inert data — nothing reads
#: it", which is a true sentence stating the retirement in its consequence
#: rather than its history. That failure is the whole reason the control exists —
#: without it the predicate would have shipped able to flag a correct
#: explanation, and the cheapest fix would have been to delete the explanation.
#:
#: Every marker here states *the change*. Citing the ticket does not: ``#321`` was
#: in this set until re-introducing the retired claim into ``verb-model.md``
#: failed to trip the guard, because the rewritten paragraph cites #321 one
#: clause later and the mutation inherited the citation. A number next to a claim
#: says nothing about whether the claim is being made or retired, so it is not a
#: marker — the sentence has to say what happened.
_RETIREMENT_MARKERS = re.compile(
    r"\bretire\w*|\bsupersed\w*|\bno longer\b|\bwas\b|\bwere\b|\buntil\b"
    r"|\breplac\w*|\bdeleted\b|\bremoved\b|\bformerly\b|\binert\b|\bnothing reads\b"
    r"|\bpreviously\b",
    re.IGNORECASE,
)


def _tracked() -> list[str]:
    """Every tracked path, repo-relative and POSIX-shaped.

    ``tracked_files_under`` answers in absolute, resolved paths; every predicate
    here is keyed on a repo-relative prefix, so the projection happens once.
    """
    return sorted(
        str(path.relative_to(_REPO_ROOT))
        for path in tracked_files_under(".", repo_root=_REPO_ROOT)
    )


def _live_markdown() -> list[str]:
    """Every tracked Markdown file that can carry a *live* claim."""
    return [
        rel
        for rel in _tracked()
        if rel.endswith(".md") and not rel.startswith(_HISTORICAL_PREFIXES) and rel != _SELF
    ]


def _live_tier_claims(text: str) -> list[str]:
    """Sentences of ``text`` naming the retired mechanism without retiring it."""
    return [
        sentence
        for sentence in _sentences(text)
        if _TIER_TOKENS.search(sentence) and not _RETIREMENT_MARKERS.search(sentence)
    ]


# ---------------------------------------------------------------------------
# AC-5 — no live document asserts a per-ticket review tier.
# ---------------------------------------------------------------------------


def test_no_live_document_still_claims_a_per_ticket_model_tier() -> None:
    """The retired mechanism survives only as a recorded retirement (AC-5)."""
    offenders: list[str] = []
    recorded = 0
    for relpath in _live_markdown():
        text = (_REPO_ROOT / relpath).read_text(encoding="utf-8", errors="replace")
        for sentence in _sentences(text):
            if not _TIER_TOKENS.search(sentence):
                continue
            if _RETIREMENT_MARKERS.search(sentence):
                recorded += 1
            else:
                offenders.append(f"{relpath}: {' '.join(sentence.split())[:160]}")

    assert not offenders, (
        "per-ticket model tiering is retired (#321): the claude review engine's "
        "model is CONTEXT.md's `loop.review_model`, and no `review:<tier>` / "
        "`build:<tier>` label is read by anything. These live sentences still "
        "present the mechanism as current:\n  " + "\n  ".join(offenders)
    )
    assert recorded >= 3, (
        f"only {recorded} live sentences mention the retired tier mechanism at "
        "all — the as-built records are supposed to *record* the retirement, so "
        "this few means the token set has stopped recognising the vocabulary and "
        "the check above is passing over nothing"
    )


def test_the_predicate_catches_the_claim_it_forbids() -> None:
    """The negative control: prove the detector fires on the retired wording.

    Without it the assertion above is satisfiable by a token set that matches
    nothing, and the ``recorded`` floor would not save it — a floor counts
    *compliant* sentences, so a predicate that stopped matching would drive both
    counts to zero and only one of them is asserted upward.
    """
    live = (
        "The claude engine's model is resolved per-ticket from a review:<tier> "
        "label; a review:opus label resolves opus."
    )
    assert _live_tier_claims(live) == _sentences(live)


def test_prose_that_records_the_retirement_stays_legal() -> None:
    """A true sentence about the retired mechanism must not be a violation.

    This is the discrimination the guard exists to make. Every as-built record
    updated by this change has to *name* what was retired to say it is gone, and
    ``specs/decisions/0007``'s amendment names the deleted resolver directly. A
    predicate keyed on the bare vocabulary would flag all of them, and the fix
    for that failure would be to delete a correct explanation.
    """
    for sentence in (
        "The per-ticket model tier ADR 0005 established was retired by #321.",
        "`resolve_model_tier` no longer exists; the model is one configured value.",
        "A `review:opus` label on an issue is inert data — nothing reads it.",
        "Previously the verb resolved a review:<tier> label; it now reads "
        "CONTEXT.md's loop.review_model.",
    ):
        assert not _live_tier_claims(sentence), sentence


def test_the_exempt_decision_record_carries_its_superseding_note() -> None:
    """ADR 0005 is exempt from the sweep, so it must say it was superseded.

    The exemption is what lets the ADR keep describing the mechanism in the
    present tense of its own day. Without this the exemption is a hole: the one
    document most likely to be read as the current design would be the one
    document nothing checks.
    """
    adr = (_REPO_ROOT / "specs" / "decisions" / "0005-per-ticket-model-tiering.md").read_text(
        encoding="utf-8"
    )

    assert re.search(r"\bretired\b|\bsuperseded\b", adr, re.IGNORECASE), (
        "ADR 0005 must record that its mechanism was retired (#321) — it is "
        "exempt from the live-prose sweep precisely because it is the record"
    )
    assert re.search(r"20\d\d-\d\d-\d\d", adr), (
        "the superseding note must be dated (`spec-authoring`: previously X; "
        "changed to Y because Z)"
    )
    assert "#321" in adr, "the note must cite the change that retired the mechanism"


# ---------------------------------------------------------------------------
# AC-6 — the symbols resolve nowhere in the tracked Python tree.
# ---------------------------------------------------------------------------

#: The deleted symbols. ``review:opus`` as a *string literal* is deliberately not
#: here: ``test_github.py`` and ``test_cli_start.py`` use it as an arbitrary label
#: in label-passthrough tests, where it is sample data and not a live mechanism.
_DELETED_SYMBOLS = ("resolve_model_tier", "ModelTier")


def test_the_tier_resolver_resolves_nowhere_in_the_tracked_python_tree() -> None:
    """Neither symbol survives in ``harness/`` or ``tests/`` (AC-6)."""
    offenders: list[str] = []
    scanned = 0
    for relpath in _tracked():
        if not relpath.endswith(".py") or relpath == _SELF:
            continue
        if not relpath.startswith(("harness/", "tests/")):
            continue
        scanned += 1
        text = (_REPO_ROOT / relpath).read_text(encoding="utf-8", errors="replace")
        offenders += [f"{relpath}: {name}" for name in _DELETED_SYMBOLS if name in text]

    assert scanned > 50, (
        f"only {scanned} tracked Python sources were scanned — the projection "
        "has stopped finding the tree, so this guard is measuring almost nothing"
    )
    assert not offenders, (
        "#321 deleted `resolve_model_tier` and `ModelTier`; these files still "
        "name them:\n  " + "\n  ".join(offenders)
    )


def test_the_deleted_test_module_is_gone_from_the_index() -> None:
    """The resolver's dedicated suite went with the resolver it covered."""
    assert "tests/unit/test_review_model_tier.py" not in _tracked()
