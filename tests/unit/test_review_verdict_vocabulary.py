"""#456 AC-1 — one verdict vocabulary, owned by ``review-discipline``.

``DEFER`` was orphaned vocabulary. ``commands/build.md`` parsed its reviewer's
``SUBMIT:`` result as ``PASS`` / ``FAIL`` / ``DEFER`` and carried a full DEFER
branch, while the skill that owns the review method specified a report ending in
"a final PASS / FAIL", ``agents/reviewer.md`` never named DEFER, and attended
``/review`` had two branches. A reviewer following its own guidance could not
emit the verdict the unattended driver was written to handle.

**Structural correspondence, not a sentence pin (ADR 0016).** The verdict set is
**derived from the owner's own list** — the bullets under
``## The verdict vocabulary`` in ``skills/review-discipline/SKILL.md`` — and the
consumers are then required to name no verdict outside it. A hardcoded tuple of
three strings in this module would be the change agreeing with itself: the
owner could drop a verdict and this guard would still enumerate it.

The consumer side is **positional**, so nothing here has to judge meaning. A
verdict appears in this corpus in exactly two shapes, and both are structure:

* an **enumeration** — a run of shouting tokens joined by ``/``, a comma, ``or``
  or ``and`` (``PASS / FAIL``, ``as `PASS`, `FAIL`, or `DEFER```);
* a **bullet lead-in** — a bolded shouting token opening a list item
  (``- **DEFER:** …``).

A group is only judged when it **intersects the owner's set**, which is what
keeps the sweep off ``RED, GREEN, REFACTOR`` in ``agents/dev.md`` and
``CONFLICT`` / ``DRIFT`` / ``LOCAL`` in ``commands/update-guidance.md`` without
a hand-kept exemption anywhere. An exemption list inside a sweep is opt-out
prose; self-scoping by intersection earns the exclusion from the subject.

What this module does **not** prove: that DEFER is *defined well*, that the hold
it prescribes is the right one, or that ``/review``'s third branch does the
right thing. Those are meaning, and the review gate owns them.
"""

from __future__ import annotations

import re
from pathlib import Path

from tests.unit._prose import REPO_ROOT, registered_prose_files

#: The one file that owns the vocabulary.
_HOME = "skills/review-discipline/SKILL.md"

#: The heading whose bullets *are* the verdict set.
_HOME_HEADING = "## The verdict vocabulary"

#: A shouting token, optionally wrapped in markdown emphasis or code ticks.
_TOKEN = r"[`*_]{0,3}\b[A-Z]{3,}\b[`*_]{0,3}"

#: What joins two members of an enumeration.
_SEP = r"(?:\s*/\s*|\s*,\s*(?:or\s+|and\s+)?|\s+or\s+|\s+and\s+)"

#: Two or more shouting tokens in a row, joined by a separator.
_ENUM = re.compile(rf"{_TOKEN}(?:{_SEP}{_TOKEN})+")

#: A bolded shouting token opening a list item, with or without its colon.
_BULLET = re.compile(r"^[ \t]*[-*][ \t]+\*\*`?([A-Z]{3,})`?:?\*\*", re.MULTILINE)

#: Shouting tokens inside a matched span.
_SHOUT = re.compile(r"\b[A-Z]{3,}\b")


def _rel(path: Path) -> str:
    return path.relative_to(REPO_ROOT).as_posix()


def _home_section() -> str:
    """The body under :data:`_HOME_HEADING`, or ``""`` when the heading is gone.

    Returning empty on a rename is deliberate: the floor below rejects an empty
    set by name, so a renamed heading fails as *the owner moved* rather than
    leaving every assertion here comparing against nothing.
    """
    text = (REPO_ROOT / _HOME).read_text(encoding="utf-8")
    start = text.find(_HOME_HEADING)
    if start == -1:
        return ""
    rest = text[start + len(_HOME_HEADING) :]
    following = re.search(r"^## ", rest, re.MULTILINE)
    return (rest[: following.start()] if following else rest).strip()


def _verdicts() -> set[str]:
    """The verdict set, derived from the owner's own bullet list."""
    return set(_BULLET.findall(_home_section()))


def _enum_groups(text: str) -> list[list[str]]:
    """Every enumeration of shouting tokens in *text*, as token lists."""
    return [_SHOUT.findall(m.group(0)) for m in _ENUM.finditer(text)]


def _bullet_group(text: str) -> list[str]:
    """Every bolded shouting bullet lead-in in *text*, as one group.

    One group per file rather than per contiguous run: a verdict branch is a
    list item whose body carries paragraphs, fences and blank lines, so line
    adjacency is not what makes two branches siblings — being the shouting
    lead-ins of the same document is.
    """
    return _BULLET.findall(text)


def _verdict_groups(text: str, known: set[str]) -> list[list[str]]:
    """The groups in *text* that name at least one member of *known*.

    The intersection is the scoping rule. A group naming no verdict is not a
    verdict enumeration and is never judged, so ``RED, GREEN, REFACTOR`` needs
    no exemption to stay legal — it earns its exclusion from its own content.

    *known* is a parameter rather than a call to :func:`_verdicts` so the
    controls below can exercise this predicate against a set they supply. Read
    off the live tree, an empty owner section would make every group
    unjudgeable and leave the controls passing for the same reason the sweep
    was measuring nothing — one edit killing both halves.
    """
    groups = [*_enum_groups(text), _bullet_group(text)]
    return [g for g in groups if g and known.intersection(g)]


# ---------------------------------------------------------------------------
# Floors — both derived sets this guard consumes are non-empty
# ---------------------------------------------------------------------------


def test_the_owner_declares_a_verdict_set() -> None:
    """Floor on the comparison set: the owner's list resolves and is anchored.

    Membership, not cardinality (``craft.md`` → *Floors decay into
    decoration*): pinning "three verdicts" would rot the day a fourth is
    argued for, and pinning the whole set here would make this module the
    second home of the very thing it exists to single-home. ``PASS`` is the
    anchor — the one verdict every entry point in the tree already acts on, so
    a rename names itself here instead of emptying the set silently.
    """
    section = _home_section()
    assert section, (
        f"{_HOME} has no {_HOME_HEADING!r} section — the verdict set is derived "
        "from its bullets, so without it every consumer check below compares "
        "against nothing (#456)"
    )
    verdicts = _verdicts()
    assert verdicts, (
        f"{_HOME_HEADING} lists no bolded verdict — the set the consumers are "
        "measured against derived to empty (#456)"
    )
    assert "PASS" in verdicts, (
        f"{_HOME_HEADING} no longer names PASS. It is the anchor: every entry "
        "point in this tree acts on it, so its absence means the list moved "
        "rather than that the vocabulary shrank (#456)"
    )


def test_the_verdict_consumers_are_in_scope() -> None:
    """Floor on the subject set: the files that act on a verdict are swept.

    Anchored on the three consumers, because a sweep that stopped seeing them
    would pass over a corpus with no verdict in it at all — the empty-subject
    shape, which reports nothing and reads exactly like compliance.
    """
    swept = {_rel(p): p.read_text(encoding="utf-8") for p in registered_prose_files()}
    assert _HOME in swept, f"{_HOME} must be in the swept corpus"

    known = _verdicts()
    for consumer in ("commands/build.md", "commands/review.md", "agents/reviewer.md"):
        assert consumer in swept, f"{consumer} must be in the swept corpus (#456)"
        assert _verdict_groups(swept[consumer], known), (
            f"{consumer} names no verdict in any position this guard reads — "
            "either it stopped acting on a verdict, or the positional predicate "
            "stopped seeing the shape it is written in (#456)"
        )


def test_the_positional_predicate_discriminates() -> None:
    """Controls: the two shapes are caught, and a non-verdict run is admitted.

    The positive samples are the real pre-#456 spellings out of
    ``commands/build.md``. The negative samples are the real non-verdict
    shouting runs that share the *shape* — they are what a predicate without the
    intersection rule would flag, and the reason this sweep needs no exemption
    list to leave them alone.
    """
    supplied = {"PASS", "FAIL", "DEFER"}
    caught = {
        "enumeration": "Parse its `SUBMIT:` result as `PASS`, `FAIL`, or `DEFER`.",
        "bare enumeration": "the candidate when heading for PASS or DEFER, then",
        "bullet": "- **DEFER:** sort the deferred findings by class first",
    }
    for label, sample in caught.items():
        groups = _verdict_groups(sample, supplied)
        assert groups, f"the predicate no longer reads a verdict {label}: {sample!r}"
        assert "DEFER" in {t for g in groups for t in g}, (
            f"the predicate reads the {label} but drops DEFER out of it: {sample!r}"
        )

    admitted = (
        "3. **Build test-first.** RED, GREEN, REFACTOR, one acceptance criterion",
        "one acceptance criterion at a time: RED, GREEN, REFACTOR, under the",
        "Classify each as LOCAL, DRIFT, or CONFLICT before touching a file.",
        "Both `JSON` and `YAML` are structured data, not prose.",
    )
    for sample in admitted:
        assert _enum_groups(sample), (
            "the control must actually be a shouting enumeration — otherwise it "
            f"proves nothing about the intersection rule: {sample!r}"
        )
        assert not _verdict_groups(sample, supplied), (
            "a shouting run that names no verdict must not be judged as one; "
            "flagging it would force an exemption list, and an exemption inside "
            f"a sweep is opt-out prose: {sample!r}"
        )


# ---------------------------------------------------------------------------
# AC-1 — no consumer names a verdict the owner does not
# ---------------------------------------------------------------------------


def test_no_consumer_names_a_verdict_outside_the_owners_set() -> None:
    """Every verdict named anywhere in registered prose is one the owner declares.

    This is the correspondence the ticket is about, in the direction that fails
    on the as-built tree: ``DEFER`` sat in ``commands/build.md``'s parse
    instruction, its two tree-identity sentences and its ship branch, and in no
    other registered file — least of all the one that specifies what a review
    may return.
    """
    known = _verdicts()
    violations: list[str] = []
    for path in registered_prose_files():
        text = path.read_text(encoding="utf-8")
        for group in _verdict_groups(text, known):
            for token in group:
                if token not in known:
                    violations.append(f"{_rel(path)}: {token} (in {group})")

    assert not violations, (
        "guidance names a review verdict the owner does not declare. The "
        f"vocabulary is single-homed in {_HOME} → {_HOME_HEADING}; add it there "
        "or stop naming it, because a verdict no reviewer is told it may emit is "
        "a branch nothing can reach (#456):\n  " + "\n  ".join(sorted(set(violations)))
    )
