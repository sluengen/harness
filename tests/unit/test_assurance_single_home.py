"""#352 AC-7 — the required-stages mapping has exactly one home.

The ticket's watchlist trigger says `review.py` must keep only orchestration and
refusal mapping, with the decision extracted. A second copy would not fail any
behavioural test on the day it is written: it would agree with the first. It
fails months later, when one is updated. So the guard is structural — no module
under ``harness/`` other than :mod:`harness.assurance` may relate the levels to
each other — and it derives its vocabulary from ``ASSURANCE_LEVELS`` so a fourth
level is covered the day it is added.

The predicate is a named function that the assertion **and its control** call, so
a mutation to the predicate kills the control rather than passing unnoticed — the
#327/#179 rule. It also carries a non-vacuity floor on the derived corpus it
scans, because a parametrized guard over a derivation that narrowed to nothing
reads green.

**#352's AC-8 guard was retired here by #353, deliberately.** It banned any live
document from presenting the trivial fast path as available, on the stated
premise that "the certification path … is item 2 of the parent proposal and is
not built". #353 builds it. The premise is now false, so the guard would force
every honest sentence in the updated records to lie about a shipped feature and
would turn ``dev`` red on the first one written. A guard whose subject has
shipped is not weakened by deletion — it is answered. What replaces it is the
behaviour itself: ``tests/unit/test_certify_verb.py`` and
``tests/unit/test_certify_gate.py`` measure what the documents may now claim.
The AC-7 half is untouched, and is what this module is now about.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from harness.assurance import ASSURANCE_LEVELS
from tests._gitutil import tracked_files_under

_REPO_ROOT = Path(__file__).resolve().parents[2]

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
