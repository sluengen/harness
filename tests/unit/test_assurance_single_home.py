"""#352 AC-7/AC-8 — one policy home, and no surface claiming the fast path shipped.

Two criteria that are easy to satisfy in prose and easy to lose silently, so
each gets a predicate that *measures* rather than a checklist that lists.

**AC-7 — one required-stages mapping.** The ticket's watchlist trigger says
`review.py` must keep only orchestration and refusal mapping, with the decision
extracted. A second copy would not fail any behavioural test on the day it is
written: it would agree with the first. It fails months later, when one is
updated. So the guard is structural — no module under ``harness/`` other than
:mod:`harness.assurance` may relate the levels to each other — and it derives its
vocabulary from ``ASSURANCE_LEVELS`` so a fourth level is covered the day it is
added.

**AC-8 — the trivial fast path has not shipped.** The level is in the vocabulary
and named all over the as-built records, which is exactly the condition under
which a sentence claiming it *works* is easy to write and impossible to spot.
Every live document may describe it as recognized-and-upgraded; none may present
it as available.

Both predicates are named functions that the assertions **and their controls**
call, so a mutation to a predicate kills the control rather than passing
unnoticed — the #327/#179 rule. Both also carry a non-vacuity floor on the
derived corpus they scan, because a parametrized guard over a derivation that
narrowed to nothing reads green.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from harness.assurance import ASSURANCE_LEVELS
from tests._gitutil import tracked_files_under

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SELF = str(Path(__file__).resolve().relative_to(_REPO_ROOT))

#: Where describing the past correctly is required, so a live-claim scan must not
#: reach: changelogs, decisions, proposals, retired specs, assessments, the log.
_HISTORICAL_PREFIXES = (
    "CHANGELOG.md",
    "CHANGELOG-archive/",
    "changelog.d/",
    "specs/decisions/",
    "specs/proposals/",
    "specs/retired/",
    "assessments/",
    "LOG.md",
)

#: The policy module — the one place the levels may be related to one another.
_POLICY_MODULE = "harness/assurance.py"


def _tracked() -> list[str]:
    return sorted(
        str(path.relative_to(_REPO_ROOT))
        for path in tracked_files_under(".", repo_root=_REPO_ROOT)
    )


# ---------------------------------------------------------------------------
# AC-7 — the required-stages mapping has exactly one home
# ---------------------------------------------------------------------------


def _harness_modules() -> list[str]:
    """Every tracked module of the app package except the policy itself."""
    return [
        rel
        for rel in _tracked()
        if rel.startswith("harness/") and rel.endswith(".py") and rel != _POLICY_MODULE
    ]


#: One level as a string literal, e.g. ``"complex"`` or ``\'simple\'``. Derived
#: from :data:`ASSURANCE_LEVELS`, so a fourth level is covered without editing
#: anything here.
_LEVEL_LITERAL = re.compile(
    "|".join(rf'["\']({re.escape(level)})["\']' for level in ASSURANCE_LEVELS)
)


def _blocks(source: str) -> list[str]:
    """``source`` split into blank-line-separated blocks.

    The unit has to be a **block**, not a line. The most likely shape of a second
    mapping is a multi-line dict — which is exactly how ``_REQUIRED_STAGES``
    itself is written — and a line-scoped scan sees only one level per line of
    it, so it would pass unflagged. A blank line separates unrelated code in
    Python, which makes it the right boundary: it is wide enough to hold a
    literal table and narrow enough that two unrelated mentions elsewhere in a
    module do not read as a relation.
    """
    return [block for block in re.split(r"\n\s*\n", source) if block.strip()]


def _relates_the_levels(source: str) -> list[str]:
    """Blocks of ``source`` naming **two or more distinct** assurance levels.

    The signature of a second mapping: a table, an ``if``-chain, or a set that
    decides one level's stages against another's. One level named alone is not —
    a module may legitimately mention ``"complex"`` in a docstring or seed a
    fixture with it — and neither is the *same* level twice, which is why the
    count is over distinct values rather than matches.
    """
    offenders = []
    for block in _blocks(source):
        named = {m.group(0).strip("\"\'") for m in _LEVEL_LITERAL.finditer(block)}
        if len(named) >= 2:
            offenders.append(block)
    return offenders


def test_the_module_corpus_reaches_the_verbs_it_claims_to() -> None:
    """Non-vacuity floor: the scan really covers the modules AC-7 is about.

    Membership, not cardinality. A derivation that narrowed — a changed prefix,
    a suffix typo — would leave the scan below green over an empty corpus, which
    is the shape that reads as "no second mapping exists" when it means "nothing
    was looked at".
    """
    modules = _harness_modules()
    for expected in ("harness/cli/review.py", "harness/cli/design.py", "harness/cli/start.py"):
        assert expected in modules, f"the AC-7 scan no longer reaches {expected}"
    assert _POLICY_MODULE not in modules, "the policy module must be excluded, not scanned"


@pytest.mark.parametrize("module", _harness_modules(), ids=lambda m: m)
def test_no_module_outside_the_policy_relates_the_assurance_levels(module: str) -> None:
    """AC-7: the level→stage relation exists in exactly one place.

    ``design`` and ``review`` consume it through :func:`required_stages` and
    :func:`design_precondition`; neither may re-derive it. A second copy passes
    every behavioural test the day it is written, because it agrees with the
    first — this is the only guard that can see it.
    """
    offenders = _relates_the_levels((_REPO_ROOT / module).read_text(encoding="utf-8"))
    assert not offenders, (
        f"{module} relates assurance levels to each other; the mapping belongs "
        f"in {_POLICY_MODULE} alone (#352 AC-7). Offending lines: {offenders}"
    )


def test_the_relation_predicate_finds_a_planted_second_mapping() -> None:
    """The positive control: the predicate must catch what it exists to catch.

    Without it the parametrized sweep above is an absence assertion with nothing
    proving the detector works — every module would pass a predicate that always
    returned ``[]``. The sample is a plausible second table, and the second
    assertion pins the *discrimination*: a lone level, which is legal, must not
    be flagged, so the guard cannot be satisfied by simply banning the word.
    """
    one_line = '_STAGES = {"simple": False, "complex": True}'
    assert _relates_the_levels(one_line) == [one_line]

    # The shape that matters, and the one a line-scoped predicate missed: a
    # multi-line dict, written exactly the way ``_REQUIRED_STAGES`` is. No line
    # of it names two levels, so this is the case that decides whether the guard
    # measures the mapping or only a compact spelling of it.
    multi_line = (
        "_STAGES = {\n"
        '    "simple": RequiredStages(design=False),\n'
        '    "complex": RequiredStages(design=True),\n'
        "}"
    )
    assert _relates_the_levels(multi_line) == [multi_line]

    # ...and the two shapes that must stay legal: one level alone, and the same
    # level twice. Neither relates anything.
    assert _relates_the_levels('DEFAULT = "simple"  # the safe level') == []
    assert _relates_the_levels('assert x == "simple"\nassert y == "simple"') == []


def test_the_policy_module_is_what_the_predicate_would_flag() -> None:
    """...and the excluded module is excluded because it *is* the mapping.

    An exemption with nothing proving it is still needed is how an allowlist
    grows into a hole (#327). If ``assurance.py`` ever stopped carrying the
    relation, this fails and the exclusion should go with it.
    """
    policy = (_REPO_ROOT / _POLICY_MODULE).read_text(encoding="utf-8")
    offenders = _relates_the_levels(policy)
    assert offenders, (
        f"{_POLICY_MODULE} no longer relates the levels, so excluding it from "
        f"the AC-7 scan proves nothing"
    )
    # Bound to the *mapping*, not merely to some block naming two levels. The
    # ``Assurance = Literal[...]`` alias also names all three, so a bare
    # non-empty assertion is satisfied by the type declaration and would keep
    # justifying the exclusion after the table it exists for had moved out.
    assert any("RequiredStages(" in block for block in offenders), (
        f"the block the exclusion is for — the required-stages table — is no "
        f"longer what {_POLICY_MODULE} relates the levels in"
    )


# ---------------------------------------------------------------------------
# AC-8 — no live document claims the trivial fast path has shipped
# ---------------------------------------------------------------------------

#: Sentences that would present the fast path as available. Each names ``trivial``
#: *and* a claim of current capability. Deliberately not a bare ``trivial`` scan:
#: every as-built record now names the level, and must, to say it is upgraded.
_SHIPPED_CLAIM = re.compile(
    r"\btrivial\b[^.]{0,120}?\b(?:skips?|bypass\w*|no LLM review|without a review)\b"
    r"|\b(?:skips?|bypass\w*)\b[^.]{0,120}?\breview\b[^.]{0,60}?\btrivial\b",
    re.IGNORECASE,
)

#: Words that mark such a sentence as describing the *decided policy* or the
#: unbuilt future rather than today's behaviour. The vocabulary must be
#: describable — the proposal's own table says `trivial` skips design and review —
#: so the ban is on presenting it as reachable, not on stating the mapping.
_NOT_YET = re.compile(
    r"\bnot built\b|\bunbuilt\b|\bnot (?:yet )?ship\w*\b|\bhas \*\*not\*\* shipped\b"
    r"|\bupgrad\w*\b|\brewrit\w*\b|\bunavailable\b|\bwould\b|\buntil\b|\bcannot\b"
    r"|\bnever returns\b|\bno run can\b|\blater increment\b|\bitem 2\b",
    re.IGNORECASE,
)


def _sentences(text: str) -> list[str]:
    return [s for s in re.split(r"(?<=[.!?])\s+|\n\n", text) if s.strip()]


def _live_fast_path_claims(text: str) -> list[str]:
    """Sentences presenting the trivial fast path as something that works."""
    return [
        sentence
        for sentence in _sentences(text)
        if _SHIPPED_CLAIM.search(sentence) and not _NOT_YET.search(sentence)
    ]


def _live_markdown() -> list[str]:
    return [
        rel
        for rel in _tracked()
        if rel.endswith(".md") and not rel.startswith(_HISTORICAL_PREFIXES) and rel != _SELF
    ]


def test_the_document_corpus_reaches_the_surfaces_ac8_names() -> None:
    """Non-vacuity floor on the AC-8 corpus, and on its exclusions.

    The criterion names four surfaces by hand; the scan is deliberately wider
    than that list, because a claim can appear in a file nobody thought to name.
    What the floor pins is that the surfaces the criterion *did* name are in it,
    and that the historical records it must not police are out.
    """
    docs = _live_markdown()
    for expected in (
        "commands/harness.md",
        "skills/spec-authoring/SKILL.md",
        "specs/features/verb-model.md",
        "specs/features/run-ledger.md",
    ):
        assert expected in docs, f"the AC-8 scan no longer reaches {expected}"
    assert not any(d.startswith(_HISTORICAL_PREFIXES) for d in docs)


@pytest.mark.parametrize("doc", _live_markdown(), ids=lambda d: d)
def test_no_live_document_claims_the_trivial_fast_path_works(doc: str) -> None:
    """AC-8: ``trivial`` is described as recognized and upgraded, never as available.

    A run that could skip the LLM review needs the deterministic certification
    path, which is item 2 of the parent proposal and is not built. A document
    saying otherwise would send an operator to label an issue in the belief that
    it buys something, and the harness would silently give them ``simple``.
    """
    claims = _live_fast_path_claims((_REPO_ROOT / doc).read_text(encoding="utf-8"))
    assert not claims, (
        f"{doc} presents the trivial fast path as shipped (#352 AC-8). It is "
        f"recognized and upgraded to `simple` until the certification path "
        f"lands. Offending sentences: {claims}"
    )


def test_the_fast_path_predicate_discriminates() -> None:
    """The control, through the same predicate — both directions.

    A ban is free against prose that never made the claim, so the sample that
    *does* make it has to be caught, and the sample that correctly describes the
    upgrade has to be let through. The second half is the one that matters: a
    predicate flagging every mention would pressure an author into deleting the
    sentence that tells the truth, which is how #330's guard nearly shipped.
    """
    shipped = "An issue labelled `assurance:trivial` skips the LLM review entirely."
    assert _live_fast_path_claims(shipped) == [shipped]

    honest = (
        "`trivial` skips design and the LLM review in the decided mapping, but "
        "no run can reach it: `start` upgrades it to `simple` until the "
        "certification path is built."
    )
    assert _live_fast_path_claims(honest) == []
