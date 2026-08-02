"""#294 — the design engine is not read-only, and no live surface may say it is.

Giving the design engine a file as its output channel replaced
``--permission-mode plan`` with a scoped write grant. Eight independent
surfaces described the engine as "read-only", and every one went silently false
at that moment: the module docstring, the ``--help`` text, an event-schema
comment, README, SPEC, CONTEXT, and two feature specs. None was caught by a
test — they were caught by two rounds of human-facing review, which is the
defect class the ticket itself was filed against ("it is not the sandbox the
docstring implies").

Split out of ``test_design_verb_lifecycle_documented.py``: that module's
subject is #213's *lifecycle documentation* — which verbs exist, in what order,
stamped in which registry places. This one's subject is a single **capability
claim** and whether any live surface still asserts it. Sharing a file made the
older module's own docstring false about half its contents, and pushed it past
the line ceiling.

What this guard is for, beyond the claim itself: it is **derived, not
enumerated**. The enumerated first draft failed review twice — once by omitting
``CONTEXT.md`` (the surface loaded into every agent session), once by listing
``commands/harness.md`` and still not recognising the claim inside it. A list of
where a claim *was* made is not a check on where it *can* be made.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent.parent


#: Paths whose text is a **historical record** and may therefore describe the
#: engine as it was. An ADR states the decision of its day (0007's own amendment
#: says "it is no longer read-only", which a token sweep would flag), a released
#: changelog entry is immutable, a proposal records what was proposed, and
#: ``specs/retired/`` is retired by definition.
_HISTORICAL_PREFIXES = (
    "CHANGELOG.md",
    "changelog.d/",
    "specs/decisions/",
    "specs/proposals/",
    "specs/retired/",
    "assessments/",
    "LOG.md",
)

#: Where a live description of the design engine can live. Derived from the
#: tracked tree rather than enumerated: an enumerated list is what failed this
#: guard's own review twice — first by omitting ``CONTEXT.md``, the surface
#: loaded into every agent session, then by listing ``commands/harness.md`` and
#: still missing the claim inside it.
_LIVE_SUFFIXES = (".md", ".py")


def _live_surface_paths() -> list[str]:
    tracked = subprocess.run(
        ["git", "ls-files"],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.split()
    return [
        rel
        for rel in tracked
        if rel.endswith(_LIVE_SUFFIXES)
        and not rel.startswith(_HISTORICAL_PREFIXES)
        and rel != "tests/unit/test_design_engine_capability_claim.py"
    ]


#: The unit of selection is a **paragraph** for prose. Sentence scope was the
#: third thing to defeat this guard: ``commands/harness.md`` opened a paragraph
#: "A read-only **Opus** engine studies the worktree…" and only named the design
#: stage two clauses later, so the sentence carrying the claim did not itself
#: look like it was about design.
_PARAGRAPH_BREAK = re.compile(r"\n\s*\n")

#: …but only for prose. In Python a blank line separates unrelated *code*, so a
#: "paragraph" there spans a whole block of unrelated command registrations and
#: reads a claim about one verb as a claim about another. Python prose lives in
#: docstrings, which do have sentences, so ``.py`` is split by sentence.
_SENTENCE_BREAK = re.compile(r"(?<=[.;:!?])\s+|\n\s*\n")

#: A passage is about the design engine when it names the engine and the design
#: stage close together, in **either** order. Direction is the second thing that
#: defeated the enumerated version: the same file reads "…Opus engine … produces
#: the change spec's Design section", where the engine comes first.
_ABOUT_DESIGN_ENGINE = re.compile(
    r"\bdesign engine\b|\bharness design\b"
    r"|\bdesign\b.{0,80}\bengine\b|\bengine\b.{0,80}\bdesign\b",
    re.IGNORECASE | re.DOTALL,
)

#: The claim itself, plus the mechanism that used to enforce it — a surface still
#: naming plan mode for this engine is making the same false statement in
#: implementation terms.
_READ_ONLY_CLAIM = re.compile(r"read-only|plan mode", re.IGNORECASE)

#: A passage may *mention* the retired claim in order to deny it — "it is no
#: longer read-only" — and those state the change correctly. Only an **asserted**
#: claim is a defect, so a negation in the run-up to the token disqualifies it.
_NEGATION = re.compile(
    r"\b(no longer|not|never|stopped|ceased|unlike|rather than|instead of|was|used to)\b",
    re.IGNORECASE,
)
_NEGATION_WINDOW = 60


def _asserts_the_claim(passage: str) -> bool:
    """True when the passage claims the engine is read-only, rather than denying it."""
    for match in _READ_ONLY_CLAIM.finditer(passage):
        run_up = passage[max(0, match.start() - _NEGATION_WINDOW) : match.start()]
        if not _NEGATION.search(run_up):
            return True
    return False


def _design_engine_sentences(text: str, *, prose: bool = True) -> list[str]:
    """The passages of ``text`` that are about the design engine specifically."""
    breaker = _PARAGRAPH_BREAK if prose else _SENTENCE_BREAK
    return [s for s in breaker.split(text) if _ABOUT_DESIGN_ENGINE.search(s)]


def test_no_live_surface_calls_the_design_engine_read_only() -> None:
    """The engine holds one scoped write grant; every live surface must agree (#294).

    Derived, not enumerated. The claim is checked wherever it can be made rather
    than in a list of the places it was made — the distinction that matters,
    since every failure of this guard has been a surface missing from a list
    rather than a claim the check could not recognise.
    """
    offenders: list[str] = []
    examined = 0
    for relpath in _live_surface_paths():
        text = (REPO_ROOT / relpath).read_text(encoding="utf-8", errors="replace")
        if "design" not in text.lower():
            continue
        for passage in _design_engine_sentences(text, prose=relpath.endswith(".md")):
            examined += 1
            if _asserts_the_claim(passage):
                offenders.append(f"{relpath}: {' '.join(passage.split())[:150]}")
    assert examined > 10, (
        f"only {examined} passages about the design engine were found across the "
        "tracked tree — the selector has stopped recognising the concept, so this "
        "guard is measuring almost nothing"
    )
    assert not offenders, (
        "the design engine holds write capability for its output file since "
        "#294, so no live surface may describe it as read-only or plan mode:\n  "
        + "\n  ".join(offenders)
    )


def test_a_negated_mention_is_not_a_claim() -> None:
    """Saying the engine is *no longer* read-only is the correct statement."""
    assert not _asserts_the_claim("The design engine is no longer read-only.")
    assert not _asserts_the_claim("The design engine command is no longer plan mode.")


def test_the_negation_window_does_not_excuse_a_later_claim() -> None:
    """A negation earlier in a passage must not license a claim further along.

    Without the bounded run-up window this would be an escape hatch: one "not"
    anywhere in a long paragraph would silence every claim after it.
    """
    passage = (
        "The review engine is not the design engine. " + "x" * 200
        + " The design engine is a read-only subprocess."
    )
    assert _asserts_the_claim(passage)


def test_the_guard_would_catch_the_claim_it_forbids() -> None:
    """The negative control: prove the detector fires on the retired wording.

    Without this, a change to ``_design_engine_sentences`` that stopped matching
    anything would leave the test above green *and* vacuous — and its
    non-vacuity assert only proves some sentence was examined, not that a
    violating one would be recognised.
    """
    retired = "`harness design` runs a read-only Opus engine over the worktree."
    sentences = _design_engine_sentences(retired)
    assert sentences, "the sentence selector no longer recognises a design-engine claim"
    assert any(re.search(r"read-only", s, re.IGNORECASE) for s in sentences)


def test_the_review_engine_may_still_be_called_read_only() -> None:
    """Scope check: the sibling engine genuinely is read-only, and must stay sayable.

    A guard keyed on the bare token anywhere in these files would forbid a true
    statement about ``review`` (`claude -p --permission-mode plan`) sitting in
    the same document — and the fix for that failure would be to weaken the
    true claim, not the false one.
    """
    verb_model = (REPO_ROOT / "specs" / "features" / "verb-model.md").read_text(
        encoding="utf-8"
    )
    assert re.search(r"read-only[^\n]*review engine|review engine[^\n]*read-only", verb_model), (
        "verb-model.md no longer states the review engine is read-only; if that "
        "changed, this guard's scoping rationale needs revisiting"
    )
