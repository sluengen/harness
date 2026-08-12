"""#329 — one canonical review→fix stop policy, single-homed in review-discipline.

The policy had **two** contradictory statements living in distributed guidance at
once. ``agents/reviewer.md``, ``commands/build.md`` and ``commands/harness.md``
said cycles 1–3 run unconditionally with a hard stop at the sixth; ``skills/
review-discipline/SKILL.md`` and ``commands/review.md`` said a *second
consecutive FAIL* stops the loop — four cycles earlier. An executor following the
skill stopped long before the agent and the harness contract expected; one
following the agent violated the skill that supposedly owns the review standard.
Which behaviour you got depended on which entry point you came in through, on a
load-bearing spend breaker.

``test_loop_stop_rule_coherence`` already existed and did not catch it, for a
reason worth stating rather than repeating: it banned the retired phrase in
exactly **two** hand-named files, and the two files still carrying that phrase
were not among them. A guard over a hand-written file list cannot notice the file
nobody added to it. So this one **derives** its subject set from the tracked,
registered tree — the same scope rule ``test_distributed_prose_no_repo_ids`` uses
— and a new command that restates the policy is in scope the day it lands.

Three properties, each a separate measure:

1. **Single home** — ``review-discipline`` states the policy and names the
   ``CONTEXT.md`` keys the numbers live in.
2. **No competing statement** — no other registered prose file states a rule of
   its own: no cycle-count literal bound to a cycle noun, and no survival of the
   retired consecutive-FAIL rule anywhere, including the two files the old guard
   never looked at.
3. **Pointers resolve** — each file that *used* to carry a copy now names
   ``review-discipline`` in the region where it stops.

The numbers themselves are not asserted here. They live in ``CONTEXT.md`` and are
measured by ``test_loop_budget`` / ``test_context_template_loop_block``; a prose
guard that also pinned them would be the third copy of the thing this ticket
exists to reduce to one.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from tests._gitutil import tracked_files_under

# ``tests/unit/test_*.py`` → ``parents[2]`` is the repo (or worktree) root.
_REPO_ROOT = Path(__file__).resolve().parents[2]
_REGISTRY = _REPO_ROOT / "registry.yaml"

#: The universal-prose directories, as ``test_distributed_prose_no_repo_ids``
#: scopes them. ``templates/`` is deliberately excluded here where that guard
#: includes it: ``templates/CONTEXT.template.md`` *is* the numbers' home, so the
#: literal ban below would flag the one file that is supposed to carry them.
_PROSE_DIRS = ("skills", "agents", "commands", "process")

#: The one file that owns the policy.
_HOME = "skills/review-discipline/SKILL.md"

#: The files that carried a competing copy before this ticket, and must now
#: point at the home instead. Hand-named on purpose — this is the *historical*
#: claim, and a file that never had a copy owes no pointer. The derived sweep
#: below is what covers files nobody thought to list.
_POINTERS = (
    "agents/reviewer.md",
    "commands/build.md",
    "commands/review.md",
    "commands/harness/run.md",
)

#: The CONTEXT keys the home must name, so a reader of the policy can find the
#: numbers without the policy restating them.
_CONFIG_KEYS = ("loop.max_review_cycles", "loop.unconditional_review_cycles")

#: The retired rule. Matched case-insensitively, and in either of the two
#: phrasings the tree used.
_RETIRED_RULE = re.compile(r"(second|two|2nd) consecutive fail", re.IGNORECASE)

#: A cycle-count literal: a bare or ordinal number bound to a cycle/iteration
#: noun. This is the shape a competing policy statement takes — "the 6th
#: review→fix cycle", "cycles 1–3", "the first 3 iterations". Prose that names a
#: *field* or a *reason tag* carries no numeral and is unaffected, which is what
#: lets the verb mechanics stay in ``commands/harness.md`` while the policy does
#: not.
_CYCLE_NOUN = r"(?:review→fix |review/fix |fix→review )?(?:cycle|iteration)s?"
_COUNT_LITERAL = re.compile(
    rf"(?:"
    rf"\b(?:first|last|maximum of|max(?:imum)?|total of)\s+\d+\s+{_CYCLE_NOUN}"
    rf"|\b\d+(?:st|nd|rd|th)\s+{_CYCLE_NOUN}"
    rf"|\b(?:sixth|fifth|fourth|third|second)\s+{_CYCLE_NOUN}"
    rf"|\b{_CYCLE_NOUN}\s+\d+\s*[–-]\s*\d+"
    rf"|\b{_CYCLE_NOUN}\s+\d+\b"
    # The ordinal can follow the noun as well as precede it — "every iteration
    # past the 3rd" states the window boundary just as plainly as "cycles 1–3".
    rf"|\b{_CYCLE_NOUN}\s+(?:past|after|beyond|through|up to)\s+(?:the\s+)?"
    rf"\d+(?:st|nd|rd|th)?\b"
    rf")",
    re.IGNORECASE,
)


def _is_registered(rel: str, registry_src: str) -> bool:
    """Whether ``rel`` appears as a key in ``registry.yaml``'s ``files:`` block."""
    return re.search(rf"^\s*{re.escape(rel)}:\s*\{{", registry_src, re.MULTILINE) is not None


def _registered_prose_files() -> list[Path]:
    """Git-tracked, registry-member files under the universal-prose dirs."""
    registry_src = _REGISTRY.read_text(encoding="utf-8")
    found: list[Path] = []
    for prose_dir in _PROSE_DIRS:
        for path in sorted(tracked_files_under(prose_dir)):
            rel = path.relative_to(_REPO_ROOT).as_posix()
            if _is_registered(rel, registry_src):
                found.append(path)
    return found


def _rel(path: Path) -> str:
    return path.relative_to(_REPO_ROOT).as_posix()


# ---------------------------------------------------------------------------
# Non-vacuity floors — every derived set this guard consumes is non-empty
# ---------------------------------------------------------------------------


def test_the_sweep_finds_the_prose_it_governs() -> None:
    """Floor: the derived subject set is non-empty and holds the known files.

    A rename of ``registry.yaml``'s block, a change to ``tracked_files_under``,
    or a move of the prose dirs would silently empty this set and leave the two
    rules below passing over nothing at all.
    """
    rels = {_rel(p) for p in _registered_prose_files()}

    assert rels, "no registered universal prose found — the sweep is scanning nothing"
    assert _HOME in rels, f"{_HOME} must be in scope — it is the policy's home"
    for pointer in _POINTERS:
        assert pointer in rels, f"{pointer} must be in scope"


def test_the_literal_predicate_can_fail() -> None:
    """Positive control: the shapes the pre-#329 tree actually used are caught.

    Each sample is a real sentence from the tree this ticket changed. Without
    this, a regex that had stopped matching anything would leave
    :func:`test_no_competing_policy_statement` green over prose full of competing
    rules — the failure mode that made the *previous* guard useless.
    """
    pre_329 = [
        "the run stops and escalates on reaching the 6th review→fix cycle regardless",
        "Cycles 1–3 run unconditionally.",
        "The first 3 iterations run unconditionally.",
        "assess convergence on each FAIL before every iteration past the 3rd",
    ]
    unmatched = [s for s in pre_329 if not _COUNT_LITERAL.search(s)]
    assert not unmatched, f"the predicate no longer catches the pre-#329 wording: {unmatched}"

    assert _RETIRED_RULE.search("A second consecutive FAIL is a stop: escalate")
    assert _RETIRED_RULE.search("A second consecutive FAIL stops the loop")


def test_the_literal_predicate_admits_the_verb_mechanics() -> None:
    """Negative control: naming the fields and tags is not stating a policy.

    ``commands/harness.md`` must keep describing the CLI contract — the exit
    code, the ``reason`` tag, the two advisory fields — and a predicate that
    flagged those would force the mechanics out of the only document that should
    hold them, which is not what single-homing the *policy* means.
    """
    mechanics = [
        "a fail that spent the last allowed cycle carries `cycles_exhausted: true`",
        "refused with `reason=review_cycle_ceiling` and exit 4",
        "the verb flags this with a `convergence_check_required` advisory",
        "This is the `(fix → review)*` loop; each new review binds to the new HEAD.",
    ]
    flagged = [s for s in mechanics if _COUNT_LITERAL.search(s)]
    assert not flagged, f"the predicate flags verb mechanics it must admit: {flagged}"


# ---------------------------------------------------------------------------
# 1. The policy has a home
# ---------------------------------------------------------------------------


def test_review_discipline_states_the_policy() -> None:
    """The home carries the whole rule, and points at the numbers' home."""
    body = (_REPO_ROOT / _HOME).read_text(encoding="utf-8")

    assert "## On a FAIL" in body, "review-discipline must keep its FAIL-handling section"
    for key in _CONFIG_KEYS:
        assert key in body, (
            f"{_HOME} must name `{key}` — the policy is written number-free and "
            "sends the reader to CONTEXT.md for the values"
        )
    assert "operator" in body.lower(), (
        f"{_HOME} must state that an exhausted ticket goes on operator hold — "
        "without it the unattended loop re-picks the work and starts a fresh budget"
    )


# ---------------------------------------------------------------------------
# 2. Nothing else states one
# ---------------------------------------------------------------------------


def test_no_competing_policy_statement() -> None:
    """No registered prose file outside the home states a stop rule of its own."""
    violations: list[str] = []
    for path in _registered_prose_files():
        rel = _rel(path)
        if rel == _HOME:
            continue
        body = path.read_text(encoding="utf-8")
        for match in _COUNT_LITERAL.finditer(body):
            violations.append(f"{rel}: {match.group(0)!r}")

    assert not violations, (
        "registered universal prose states a review→fix cycle count of its own — "
        f"the policy is single-homed in {_HOME} and the numbers in CONTEXT.md, so "
        "point at them instead of restating (#329):\n  " + "\n  ".join(violations)
    )


def test_the_retired_consecutive_fail_rule_is_gone_everywhere() -> None:
    """The contradicting rule survives in no registered prose file, home included.

    Scoped over the derived set rather than the two files the previous guard
    named — the two that actually carried it were the two it did not check.
    """
    violations = [
        _rel(path)
        for path in _registered_prose_files()
        if _RETIRED_RULE.search(path.read_text(encoding="utf-8"))
    ]

    assert not violations, (
        "the retired 'second consecutive FAIL' stop rule survives in: "
        + ", ".join(violations)
        + f" — it contradicts the canonical policy in {_HOME} (#329)"
    )


# ---------------------------------------------------------------------------
# 3. The pointers resolve
# ---------------------------------------------------------------------------


#: What makes a ``review-discipline`` mention a *stop-rule* pointer rather than
#: an unrelated one. ``commands/review.md`` already named the skill in its
#: opening line ("Implements `review-discipline` via the `reviewer` agent"), so
#: a whole-file containment test is satisfied by prose that says nothing about
#: stopping — the same weak-predicate shape as a guard whose subject set is
#: empty. The pointer and the topic must sit in one line.
_STOP_CUE = re.compile(r"stop rule|on a fail|cycle|abandon|budget", re.IGNORECASE)


def _pointer_lines(body: str) -> list[str]:
    """Lines naming the home *and* the thing it is being cited for."""
    return [
        line
        for line in body.splitlines()
        if "review-discipline" in line and _STOP_CUE.search(line)
    ]


def test_the_pointer_predicate_is_not_satisfied_by_an_unrelated_mention() -> None:
    """Positive control: naming the skill for some other reason is not a pointer.

    This is the exact line ``commands/review.md`` has carried since long before
    this ticket. If it counted, that file could drop its stop-rule pointer
    entirely and the parametrized test below would stay green.
    """
    unrelated = (
        "Runs the final gate before merge. "
        "Implements `review-discipline` via the `reviewer` agent."
    )
    assert "review-discipline" in unrelated
    assert not _pointer_lines(unrelated), (
        "an unrelated mention must not read as a stop-rule pointer"
    )


@pytest.mark.parametrize("rel", _POINTERS)
def test_each_former_copy_points_at_the_home(rel: str) -> None:
    """A file that dropped its copy must send the reader somewhere.

    Deleting a competing statement without leaving a pointer would satisfy the
    rule above while making the policy *less* reachable than the contradiction
    was — the reader would find nothing at all where the rule used to be.
    """
    body = (_REPO_ROOT / rel).read_text(encoding="utf-8")
    assert _pointer_lines(body), (
        f"{rel} dropped its copy of the stop rule but names no route to "
        f"{_HOME} where it stops, so a reader following it finds no policy (#329)"
    )
