"""#331 — the as-built record lands inside the tree the verdict certifies.

Every surface that operated the as-built-record gate told the reviewer to write
the record **after** the verdict: ``agents/reviewer.md`` said "as the last commit
on the branch before merge", ``commands/review.md`` and ``commands/ship.md`` said
the same in their own words, and ``commands/build.md`` put the record paragraph
in *§3 Ship*, after the PASS. So the commit that actually merged was never the
commit that was reviewed, and never the commit the verify gate ran over.

That is not a documentation nicety. Documentation is delivered tree content: a
record edit can trip a link, generated-doc, or drift guard, and under the old
order it did so *after* the gate that was supposed to catch it. On the harness
path it is worse than untested — ``harness close`` binds a pass to a SHA, so a
post-verdict record commit is exactly what ``stale_review`` refuses. The prose
instructed the agent to produce a state the gate rejects.

The fix names the rule and gives it one home: the **final-evidence ordering
rule** in ``skills/review-discipline/SKILL.md``'s *Reviewer obligations*, beside
the as-built-record gate it strengthens. Every other surface points at it and
carries no competing statement — the #329 shape, for the same reason: two
statements of one policy is how the policy came to contradict itself.

Four properties, each measured separately:

* **AC-1 (single home)** — ``review-discipline`` states the ordering rule under
  its own name. Proven by :func:`test_review_discipline_states_the_ordering_rule`.
* **AC-2 (no competing statement)** — the retired ordering survives in no
  registered prose file, template, or entry-doc mirror. Derived from the tracked,
  registered tree rather than hand-listed, so a file nobody thought to list is in
  scope the day it lands (#329's lesson). Proven by
  :func:`test_the_retired_ordering_is_gone_everywhere`.
* **AC-3 (ordering, positionally)** — in the two files with an ordered narrative,
  the record step precedes the verdict step by *offset*, which is the thing the
  ticket is actually about and which no keyword test can see. Proven by
  :func:`test_reviewer_records_before_it_decides` and
  :func:`test_build_records_before_it_ships`.
* **AC-4 (the checkable contracts)** — ``/ship`` and ``/build`` gain an identity
  check for the certified tree, and the reviewer reports the SHA it bound to.
  Proven by :func:`test_ship_checks_head_against_the_reviewed_sha`,
  :func:`test_reviewer_reports_the_reviewed_sha`, and
  :func:`test_build_checks_the_committed_tree_against_the_reviewed_tree`.
* **AC-5 (pointers resolve)** — each file that stopped stating the rule names its
  home *on the line where it stops*, with a topic cue. Whole-file containment
  would be vacuous here: four of the five already name ``review-discipline`` for
  unrelated reasons (``commands/review.md:6`` has since forever). Proven by
  :func:`test_each_former_copy_points_at_the_home`.
"""

from __future__ import annotations

import re
from pathlib import Path

from tests._gitutil import tracked_files_under

# ``tests/unit/test_*.py`` → ``parents[2]`` is the repo (or worktree) root.
_REPO_ROOT = Path(__file__).resolve().parents[2]
_REGISTRY = _REPO_ROOT / "registry.yaml"

#: The universal-prose directories, as ``test_distributed_prose_no_repo_ids``
#: scopes them, plus ``templates/`` — unlike #329's literal ban, nothing here is
#: a number a template legitimately owns, and ``templates/feature.md`` carried
#: the retired ordering in its own editing rule.
_PROSE_DIRS = ("skills", "agents", "commands", "process", "templates")

#: The entry process doc and its byte-identical mirrors. Root files, so the
#: ``_PROSE_DIRS`` sweep cannot reach them, and the mirrors are what a session
#: actually reads.
_ENTRY_DOCS = ("CLAUDE.md", "AGENTS.md", "GEMINI.md")

#: The one file that owns the rule.
_HOME = "skills/review-discipline/SKILL.md"

#: The rule's name — greppable on purpose, so the home states it and the
#: pointers can name it without restating it.
_RULE_NAME = "final-evidence ordering"

#: The retired ordering. Anchored on the two clauses that place the record
#: *after* the reviewed tree. Deliberately NOT a bare "last commit":
#: ``templates/feature.md:5`` documents a frontmatter field as "the day of the
#: last commit that changed this file", and ``tests/_gitutil`` prose speaks of
#: "the last commit touching that path" — both unrelated, both must stay legal.
_RETIRED_ORDERING = re.compile(
    r"last commit\s+(?:on the branch|before merge)",
    re.IGNORECASE,
)

#: The files that carried a copy of the ordering before this ticket, and must
#: now point at the home. Hand-named on purpose: this is the *historical* claim,
#: and a file that never carried one owes no pointer. The derived sweep in AC-2
#: is what covers files nobody thought to list.
_POINTERS = (
    "agents/reviewer.md",
    "commands/review.md",
    "commands/build.md",
    "commands/ship.md",
    "commands/harness/run.md",
)

#: A topic cue that must sit on the *same line* as the pointer. Without this the
#: check is vacuous — see the module docstring's AC-5 note.
_POINTER_TOPIC = re.compile(
    r"final-evidence|ordering|reviewed[_ ]sha|certif|before the verdict|record",
    re.IGNORECASE,
)


def _is_registered(rel: str, registry_src: str) -> bool:
    """Whether ``rel`` appears as a key in ``registry.yaml``'s ``files:`` block."""
    return (
        re.search(rf"^\s*{re.escape(rel)}:\s*\{{", registry_src, re.MULTILINE)
        is not None
    )


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


def _swept_files() -> list[Path]:
    """The AC-2 subject set: registered prose plus the entry-doc mirrors."""
    files = _registered_prose_files()
    files.extend(
        _REPO_ROOT / name for name in _ENTRY_DOCS if (_REPO_ROOT / name).is_file()
    )
    return files


def _rel(path: Path) -> str:
    return path.relative_to(_REPO_ROOT).as_posix()


def _text(rel: str) -> str:
    return (_REPO_ROOT / rel).read_text(encoding="utf-8")


def _obligations_section() -> str:
    """``review-discipline``'s *Reviewer obligations* section.

    Parsed exactly as ``test_review_discipline_asbuilt_record_gate`` parses it,
    so the two guards cannot disagree about where the gate lives.
    """
    text = _text(_HOME)
    start = text.find("## Reviewer obligations")
    assert start != -1, "review-discipline must have a Reviewer obligations section"
    end = text.find("## On a FAIL", start)
    assert end != -1, "review-discipline must have an 'On a FAIL' section after it"
    return text[start:end]


# ---------------------------------------------------------------------------
# Non-vacuity floors — every derived set this guard consumes is non-empty
# ---------------------------------------------------------------------------


def test_the_sweep_finds_the_prose_it_governs() -> None:
    """Floor: the derived subject set is non-empty and holds the known files.

    A rename of ``registry.yaml``'s block, a change to ``tracked_files_under``,
    or a move of the prose dirs would silently empty this set and leave AC-2
    passing over nothing at all — the empty-subject shape that has gone
    vacuously green here before.
    """
    rels = {_rel(p) for p in _swept_files()}

    assert rels, "no registered universal prose found — the sweep is scanning nothing"
    assert _HOME in rels, f"{_HOME} must be in scope — it is the rule's home"
    for pointer in _POINTERS:
        assert pointer in rels, f"{pointer} must be in scope"
    assert "templates/feature.md" in rels, (
        "templates/feature.md must be in scope — it carried the retired ordering "
        "in its own editing rule"
    )
    for mirror in _ENTRY_DOCS:
        assert mirror in rels, f"{mirror} must be in scope — it is what a session reads"


def test_the_retired_ordering_predicate_can_fail() -> None:
    """Positive control: the exact pre-#331 sentences are caught.

    Each sample is a real sentence from the tree this ticket changed. Without
    this, a predicate that had stopped matching would leave AC-2 green over
    prose still carrying the retired rule.
    """
    pre_331 = [
        "to reflect what the diff actually does, as the last commit on the branch"
        " before merge",
        "the reviewer records what shipped to the as-built record ... as the last"
        " commit on the branch",
        "The reviewer has recorded the shipped behaviour to `specs/features/` (the"
        " last commit on the branch).",
        "The reviewer recorded what shipped to `specs/features/` on PASS (the last"
        " commit before merge).",
        "written from what the diff actually does as the last commit before merge",
        "The reviewer updates `specs/features/<feature>.md` to match what shipped,"
        " as the last commit before merge.",
        "based on what the diff actually does, as the last commit before merge",
    ]
    unmatched = [s for s in pre_331 if not _RETIRED_ORDERING.search(s)]
    assert not unmatched, (
        f"the predicate no longer catches the pre-#331 wording: {unmatched}"
    )


def test_the_retired_ordering_predicate_admits_unrelated_last_commits() -> None:
    """Negative control: "last commit" in an unrelated sense stays legal.

    ``templates/feature.md``'s frontmatter documents ``last_updated`` as the day
    of the last commit that changed the file, and the currency guards speak of
    the last commit touching a path. A predicate keyed on the bare phrase would
    flag both and force unrelated prose to be reworded to satisfy a rule that
    has nothing to say about it.
    """
    unrelated = [
        "last_updated: YYYY-MM-DD    # day of the last commit that changed this"
        " file — bump it on every content edit",
        "asked git for the last commit touching a path and returned the graft"
        " boundary",
        "`last_updated` must be no older than the author date of the last commit"
        " touching that path.",
    ]
    flagged = [s for s in unrelated if _RETIRED_ORDERING.search(s)]
    assert not flagged, f"the predicate flags unrelated prose it must admit: {flagged}"


# ---------------------------------------------------------------------------
# AC-1 — the rule has a home
# ---------------------------------------------------------------------------


def test_review_discipline_states_the_ordering_rule() -> None:
    """The home names the rule and states what it forbids (AC-1)."""
    section = _obligations_section()
    lowered = section.lower()

    assert _RULE_NAME in lowered, (
        f"{_HOME}'s Reviewer obligations must name the {_RULE_NAME} rule — it is "
        "the home every other surface points at"
    )
    assert "as-built" in lowered, (
        "the ordering rule must sit with the as-built-record gate it strengthens"
    )
    assert "verdict" in lowered, (
        "the rule is about what the verdict covers — it must say so"
    )
    assert "fail" in lowered, (
        "a pass issued over a tree that is not the merged tree is a FAIL, not a "
        "style note"
    )


def test_the_home_states_the_gate_runs_over_the_record() -> None:
    """The certifying gate runs over the tree that already holds the record (AC-1).

    This is the half that makes the rule load-bearing rather than tidy: a record
    edit is tree content a link, generated-doc, or drift guard may reject, and
    the whole point is that it is rejected *before* a verdict exists.
    """
    lowered = _obligations_section().lower()
    assert "gate" in lowered, "the rule must name the verify gate"
    assert "before" in lowered, (
        "the rule must state the ordering — the record lands before the "
        "certifying gate and the verdict, not after"
    )


# ---------------------------------------------------------------------------
# AC-2 — nothing else states the retired ordering
# ---------------------------------------------------------------------------


def test_the_retired_ordering_is_gone_everywhere() -> None:
    """No swept file places the record after the reviewed tree (AC-2).

    Scoped over the derived set rather than the files this ticket happened to
    name: ``skills/spec-driven-development/SKILL.md`` and
    ``templates/feature.md`` both carried the retired clause and appear in no
    line of the ticket's *Where*.
    """
    violations: list[str] = []
    for path in _swept_files():
        body = path.read_text(encoding="utf-8")
        for match in _RETIRED_ORDERING.finditer(body):
            violations.append(f"{_rel(path)}: {match.group(0)!r}")

    assert not violations, (
        "guidance still places the as-built record after the tree the verdict "
        f"binds to — the {_RULE_NAME} rule is single-homed in {_HOME} and the "
        "record goes into the candidate before the certifying gate (#331):\n  "
        + "\n  ".join(violations)
    )


# ---------------------------------------------------------------------------
# AC-3 — the ordering, measured positionally
# ---------------------------------------------------------------------------


def test_reviewer_records_before_it_decides() -> None:
    """``agents/reviewer.md`` records reality before it issues a verdict (AC-3).

    Measured by offset, not by keyword: the defect was never a missing word, it
    was a correct instruction in the wrong place. Before #331 the record section
    sat *after* the ``Decide`` step.
    """
    text = _text("agents/reviewer.md")

    record_at = text.lower().find("record reality")
    assert record_at != -1, "agents/reviewer.md must keep its record-reality step"
    decide_at = text.find("**Decide.**")
    assert decide_at != -1, (
        "agents/reviewer.md must keep a **Decide.** step — it is the verdict this "
        "ordering is measured against"
    )

    assert record_at < decide_at, (
        "agents/reviewer.md issues its verdict before it records reality — the "
        "record must be in the tree the verdict covers, so the record step comes "
        f"first (#331; record at {record_at}, decide at {decide_at})"
    )


def test_build_records_before_it_ships() -> None:
    """``commands/build.md`` records the as-built spec inside §2 (AC-3).

    Before #331 the record paragraph opened *§3 Ship*, after the verdict — so
    the commit that integrated was never the tree the review had judged.
    """
    text = _text("commands/build.md")

    record_at = text.find("Record the as-built spec")
    assert record_at != -1, "commands/build.md must keep its as-built record step"
    ship_at = text.find("## 3. Ship")
    assert ship_at != -1, "commands/build.md must keep its §3 Ship heading"

    assert record_at < ship_at, (
        "commands/build.md records the as-built spec in §3 Ship, after the "
        "verdict — it belongs in §2, before the verification and the review that "
        f"certify the tree (#331; record at {record_at}, §3 at {ship_at})"
    )


# ---------------------------------------------------------------------------
# AC-4 — the checkable contracts
# ---------------------------------------------------------------------------


def test_reviewer_reports_the_reviewed_sha() -> None:
    """The reviewer names the SHA its verdict binds to (AC-4).

    The agent-led flow has no ledger, so the identity of the certified tree has
    to travel in the report — it is what ``/ship`` checks HEAD against.
    """
    text = _text("agents/reviewer.md")
    assert "reviewed_sha" in text, (
        "agents/reviewer.md must report the reviewed_sha — without an identity "
        "for the certified tree, /ship has nothing to compare HEAD to (#331)"
    )


def test_ship_checks_head_against_the_reviewed_sha() -> None:
    """``/ship`` refuses a branch whose HEAD is not the certified tree (AC-4).

    The agent-led twin of the harness's ``stale_review`` refusal.
    """
    text = _text("commands/ship.md")
    assert "reviewed_sha" in text, (
        "commands/ship.md must name the reviewed_sha it checks HEAD against"
    )
    assert "git rev-parse HEAD" in text, (
        "commands/ship.md must show the check, not merely assert the "
        "precondition — a precondition nobody runs is how the old ordering "
        "survived (#331)"
    )
    lowered = text.lower()
    assert "stale_review" in lowered, (
        "commands/ship.md must name the harness refusal it mirrors, so the two "
        "paths are recognisably one rule"
    )


def test_build_checks_the_committed_tree_against_the_reviewed_tree() -> None:
    """``/build`` pins the committed tree to the reviewed one (AC-4).

    ``/build`` reviews a staged tree and commits after the verdict, so it has no
    pre-review SHA to bind to. The tree hash is the exact statement of the same
    property in that flow.
    """
    text = _text("commands/build.md")
    assert "write-tree" in text, (
        "commands/build.md must capture the reviewed tree hash before the review"
    )
    assert "HEAD^{tree}" in text, (
        "commands/build.md must compare the committed tree against the reviewed "
        "tree — in a flow with no pre-review commit that identity is the whole "
        "of the ordering rule (#331)"
    )


# ---------------------------------------------------------------------------
# AC-5 — pointers resolve
# ---------------------------------------------------------------------------


def test_each_former_copy_points_at_the_home() -> None:
    """Every file that stopped stating the rule names its home *in place* (AC-5).

    Line-scoped with a topic cue on purpose. Four of the five files already name
    ``review-discipline`` somewhere for unrelated reasons — ``commands/review.md``
    line 6 has said "Implements ``review-discipline``" since forever — so a
    whole-file containment check would pass on a file that had dropped its
    ordering pointer entirely.
    """
    missing: list[str] = []
    for rel in _POINTERS:
        lines = _text(rel).splitlines()
        if not any(
            "review-discipline" in line and _POINTER_TOPIC.search(line)
            for line in lines
        ):
            missing.append(rel)

    assert not missing, (
        "these files stopped stating the ordering rule without naming where it "
        f"now lives, on the same line: {missing}. Point at {_HOME} where the rule "
        "used to be (#331)"
    )


def test_the_pointer_predicate_is_not_satisfied_by_an_unrelated_mention() -> None:
    """Positive control: the cheaper whole-file predicate is distinguishable.

    Built from ``commands/review.md``'s real line 6, which names
    ``review-discipline`` and says nothing about ordering or the record. If the
    same-line topic cue were dropped, this line alone would satisfy AC-5 — so
    this control is what proves the *unit* of the check, not just its keyword.
    """
    unrelated = (
        "Runs the final gate before merge. Implements `review-discipline` via "
        "the `reviewer` agent."
    )
    assert "review-discipline" in unrelated
    assert not _POINTER_TOPIC.search(unrelated), (
        "the topic cue must not fire on a bare skill mention — otherwise AC-5 is "
        "satisfied by a line that predates this ticket entirely"
    )
