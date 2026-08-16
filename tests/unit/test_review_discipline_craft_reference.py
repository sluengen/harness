"""The review-craft reference: its structure, its named patterns, its two roots.

What this module pins:

* the family headings (``## ``) are derived from the file and equal the recorded
  set — a renamed or dropped family fails here rather than quietly re-homing its
  patterns;
* the pattern set (``### ``) is derived from the file, not hand-listed, is
  non-empty, and sits above a floor set just under the measured count — the two
  conditions kept in separate tests so neither hides the other from mutation;
* the named anchors the change spec requires are present **by membership**, so a
  rename names itself instead of shrinking the set behind a count that still
  passes;
* every pattern body clears a character floor;
* both citing roots name the reference by its repo-relative path.

What this module does **not** prove:

* **That a pattern carries a falsifying example.** The body assertion measures
  *length*. A long body with nothing concrete in it passes. No predicate short
  of reading the entry distinguishes an example from a restatement, and a
  keyword sweep for one would be exactly the fail-open blacklist the reference
  itself warns about. The floor catches the class it can catch: a pattern
  degraded to its one-line statement, which is the shape a distillation rots
  into.
* That the patterns are correct, mutually exclusive, or free of restatement of
  what the core skill already owns. Those are review judgments over prose, not
  properties of the tracked tree.
* That any reader loads the file. A root naming the path is necessary, not
  sufficient.
* That a root names the path in every place it should. The build command cites
  it at both the implementation and the review brief; this asserts only that the
  path is *somewhere* in the file, so deleting one of the two cites survives.
  Measured, and left deliberately: a count is the cardinality floor the reference
  itself warns against, and it would rot the first time a third brief is added.

Registration, versioning and the one-level nesting rule are owned by the
guidance-topology guard; the app-cite and repo-id sweeps own this file's prose
constraints. None of that is re-asserted here.
"""

from __future__ import annotations

import re
from pathlib import Path

# ``tests/unit/test_*.py`` → ``parents[2]`` is the repo (or worktree) root.
_REPO_ROOT = Path(__file__).resolve().parents[2]

_CRAFT_REL = "skills/review-discipline/references/craft.md"
_CRAFT = _REPO_ROOT / _CRAFT_REL

#: The roots that must brief a reader on the reference, each by path.
_CITING_ROOTS = ("skills/review-discipline/SKILL.md", "commands/build.md")

#: The families the reference is organised into, in order. Pinned as an
#: equality, so both a lost family and an unrecorded new one go red.
_FAMILIES = (
    "Vacuity — the test that cannot fail",
    "Prose predicates and text guards",
    "Deletion, retirement, and re-homing",
    "Mutation discipline",
    "The ticket and its criteria",
    "Unmeasured claims — prose asserting what nothing checks",
)

#: Named patterns pinned by membership — one per family at minimum, covering the
#: lesson classes the change spec names. A rename shows up here as a missing
#: name rather than as a set that silently lost an entry.
_REQUIRED_PATTERNS = (
    "Exercise the production path, not merely a production constant",
    "The empty comparison set",
    "A blacklist inversion sweep fails open on an appended grant",
    "The negation window assumes a false converse",
    "The text unit is part of the predicate",
    "A deletion pass that moves a definition must move its killer",
    "The wiring-field survivor",
    "Never re-run the builder's table as verification",
    "A ticket's grounding is its least reliable part",
    "A declined action is not a prevented one",
)

#: Measured at 40 patterns. The floor sits just under that: a slack floor set
#: far below the real count swallows whole families without going red.
_PATTERN_FLOOR = 38

#: Measured shortest body is 357 characters. The floor sits just under it. A
#: pattern stripped back to its one-line statement — the rule with the
#: falsifying example dropped — lands around 120 and trips this.
_BODY_FLOOR = 320

_HEADING = re.compile(r"^(#{2,3}) (.+)$", re.MULTILINE)


def _craft_text() -> str:
    return _CRAFT.read_text(encoding="utf-8")


def _sections() -> list[tuple[int, str, str]]:
    """``(level, heading, body)`` for every ``##``/``###`` section, in order.

    A section's body ends at the next heading of *either* level, so a pattern
    that happens to sit last under a family does not absorb the family heading
    that follows it.
    """
    text = _craft_text()
    marks = list(_HEADING.finditer(text))
    sections: list[tuple[int, str, str]] = []
    for index, mark in enumerate(marks):
        end = marks[index + 1].start() if index + 1 < len(marks) else len(text)
        sections.append((len(mark.group(1)), mark.group(2).strip(), text[mark.end() : end].strip()))
    return sections


def _families() -> list[str]:
    return [heading for level, heading, _ in _sections() if level == 2]


def _patterns() -> dict[str, str]:
    return {heading: body for level, heading, body in _sections() if level == 3}


def test_families_are_the_recorded_set() -> None:
    """The derived family set equals the recorded one, in both directions."""
    derived = _families()
    assert derived == list(_FAMILIES), f"family headings drifted: {derived}"


def test_pattern_derivation_is_non_vacuous() -> None:
    """The derivation found patterns at all.

    Kept apart from the floor below so each has its own killer. A heading-shape
    change that makes ``_patterns()`` derive to ``{}`` leaves the body sweep
    iterating over nothing — passing while measuring nothing — and this is the
    assertion that catches it.
    """
    assert _patterns(), "no ### patterns derived — the parser or the file's shape changed"


def test_pattern_count_is_above_its_floor() -> None:
    """Enough patterns survive, measured against a floor set just under the count."""
    patterns = _patterns()
    assert len(patterns) >= _PATTERN_FLOOR, (
        f"the reference carries {len(patterns)} patterns, under the floor of {_PATTERN_FLOOR}"
    )


def test_required_patterns_are_present_by_name() -> None:
    """The lesson classes the change spec names are present, pinned by membership."""
    derived = set(_patterns())
    missing = [name for name in _REQUIRED_PATTERNS if name not in derived]
    assert not missing, f"the reference lost required pattern(s): {missing}"


def test_every_pattern_body_clears_the_floor() -> None:
    """No pattern is reduced to its one-line statement.

    This measures length, not the presence of a falsifying example — see the
    module docstring. It catches the degradation a distillation actually
    suffers: an entry trimmed to its rule with the concrete case dropped.
    """
    thin = {name: len(body) for name, body in _patterns().items() if len(body) < _BODY_FLOOR}
    assert not thin, (
        f"pattern bodies under {_BODY_FLOOR} chars (statement with no example?): {thin}"
    )


def test_both_citing_roots_name_the_reference() -> None:
    """`review-discipline` and the build command each link the file by path."""
    for root in _CITING_ROOTS:
        text = (_REPO_ROOT / root).read_text(encoding="utf-8")
        assert _CRAFT_REL in text, f"{root} does not name {_CRAFT_REL}"


def test_version_header_is_the_first_line() -> None:
    """The guidance stamp leads the file, where the freshness hook reads it."""
    first = _craft_text().splitlines()[0]
    assert re.fullmatch(r"<!-- guidance:review-discipline-craft@\d+\.\d+\.\d+ -->", first), (
        f"first line is not the guidance stamp: {first!r}"
    )
