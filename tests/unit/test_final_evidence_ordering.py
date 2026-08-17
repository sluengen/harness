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
  its own name, in the bullet that carries it. Proven by
  :func:`test_the_home_states_the_ordering_rule`.
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
  check for the certified tree, and the reviewer reports the tree it bound to.
  Proven by :func:`test_ship_checks_head_against_the_reviewed_tree`,
  :func:`test_reviewer_reports_the_reviewed_tree`, and
  :func:`test_build_checks_the_committed_tree_against_the_reviewed_tree`.
* **AC-5 (pointers resolve)** — each file that stopped stating the rule names its
  home *on the line where it stops*, with a topic cue. Whole-file containment
  would be vacuous here: four of the five already name ``review-discipline`` for
  unrelated reasons (``commands/review.md:6`` has since forever). Proven by
  :func:`test_each_former_copy_points_at_the_home`.

**#459 changed two things and nothing else.** The two AC-1 home tests — one
reading the rule's name, one reading the gate-before-verdict half — were one rule
pinned twice over the same section, so they merge into
:func:`test_the_home_states_the_ordering_rule`, which reads the *bullet* rather
than the whole section. Section-wide, ``gate``, ``before``, ``verdict`` and
``fail`` are all free: the four sibling obligations use every one of them, so the
pre-#459 pair could not tell the ordering rule from its neighbours. And the
section slicer is now **imported** from
``test_review_discipline_asbuilt_record_gate`` rather than copy-pasted, which is
what this module's own docstring already claimed in prose — the ``craft.md``
class *A positive control must exercise the predicate, not re-implement it*,
applied to a shared slicer. Everything else here is untouched: the retired-ordering
sweep with both of its controls, the positional offsets, the identity contracts,
and the line-scoped pointers with their control were already the shape ADR 0016
asks for.

**#456 turned one identity contract around rather than deleting it.** The AC-4
assertions used to require the literal ``reviewed_sha`` in ``agents/reviewer.md``
and ``commands/ship.md``, and ``/ship`` to read a bare ``git rev-parse HEAD``.
The verdict now binds to the **git tree object**, which is what the gate's own
marker is named after and what ``/build`` already compared, so the pins move to
``reviewed_tree`` and to the tree form of the command — the same property, over
the identity the enforcement hooks actually read. The retired spelling is not
merely unpinned but **swept out**: :func:`test_the_commit_sha_identity_is_retired`
asserts it survives in no registered prose, because a surviving copy in a file
nobody re-pinned is exactly how the two identities came to disagree. The
distinction the sweep respects is the one AC-2 draws — a report may still *name*
a commit sha for a human; what may not survive is `reviewed_sha` as the thing
shipping is gated on.
"""

from __future__ import annotations

import re
from pathlib import Path

from tests._gitutil import tracked_files_under
from tests.unit._prose import REPO_ROOT, obligation_bullets

_REGISTRY = REPO_ROOT / "registry.yaml"

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

#: The identity a verdict binds to (#456): the git **tree** object, which is
#: what the verify gate's marker is named after and what ``/build`` already
#: compared. ``/ship`` reads it with the tree form of ``git rev-parse``.
_REVIEWED_TREE = "reviewed_tree"
_TREE_OF_HEAD = "git rev-parse HEAD^{tree}"

#: The retired identity. A commit sha is both weaker (an amend that rewrites no
#: bytes fails it) and different from the object the enforcement hooks read.
_RETIRED_IDENTITY = "reviewed_sha"

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
            rel = path.relative_to(REPO_ROOT).as_posix()
            if _is_registered(rel, registry_src):
                found.append(path)
    return found


def _swept_files() -> list[Path]:
    """The AC-2 subject set: registered prose plus the entry-doc mirrors."""
    files = _registered_prose_files()
    files.extend(
        REPO_ROOT / name for name in _ENTRY_DOCS if (REPO_ROOT / name).is_file()
    )
    return files


def _rel(path: Path) -> str:
    return path.relative_to(REPO_ROOT).as_posix()


def _text(rel: str) -> str:
    return (REPO_ROOT / rel).read_text(encoding="utf-8")


#: The ordering rule's own clause: nothing lands after the certifying gate. The
#: negation is **anchored to what it governs** — a bare negation in a bullet this
#: long is decoration, and ``before`` on its own is satisfied by prose putting the
#: record before anything at all.
_NOTHING_LANDS_AFTER = re.compile(
    r"\b(?:nothing|never|not|no)\b(?:\W+\w+){0,3}?\W+(?:after|later)\b", re.IGNORECASE
)


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


def _ordering_bullets() -> list[str]:
    """Reviewer-obligation bullets naming the final-evidence ordering rule."""
    return [b for b in obligation_bullets() if _RULE_NAME in b.lower()]


def test_the_home_states_the_ordering_rule() -> None:
    """The home names the rule, in the bullet that carries it (AC-1).

    One tripwire where #459 found two, and read from the *bullet* rather than the
    ``## Reviewer obligations`` section: section-wide, every term below is free.
    The gate obligation beside it names ``as-built`` and ``FAIL``; the twin sweep
    names ``branch`` and ``deferral``; the report contract names ``verdict``,
    ``gate`` and ``fail``. So a pair of section-scoped term checks proved only
    that four common words appeared somewhere in five bullets.

    * **anchor** — exactly one obligation names :data:`_RULE_NAME`. That name is
      greppable on purpose, because every other surface points at it by name;
      stated twice, the pointers stop having one referent.
    * **terms** — ``as-built`` (the gate it strengthens), ``gate`` and ``verdict``
      (the two things the record has to precede).
    * **polarity** — :data:`_NOTHING_LANDS_AFTER`. The ordering is a claim about
      what may *not* follow the certified tree, and it is the half a later edit
      drops while keeping the rest: "record before the gate" reads as advice
      without it, and a documentation commit after the verdict is exactly the
      state the rule exists to refuse.
    """
    bullets = _ordering_bullets()
    assert len(bullets) == 1, (
        f"{_HOME}'s Reviewer obligations carry {len(bullets)} bullets naming the "
        f"{_RULE_NAME} rule; there must be exactly one. It is the home every other "
        "surface points at by name, and two homes is how the policy came to "
        "contradict itself (#331)."
    )
    bullet = bullets[0]
    lowered = bullet.lower()

    missing = [term for term in ("as-built", "gate", "verdict") if term not in lowered]
    assert not missing, (
        f"the {_RULE_NAME} rule no longer states {missing}. It sits with the "
        "as-built-record gate it strengthens, and it is about the tree the verify "
        "gate and the verdict both cover."
    )
    assert _NOTHING_LANDS_AFTER.search(bullet), (
        f"the {_RULE_NAME} rule no longer refuses anything landing after the "
        "certified tree. Without that clause the bullet reads as a preference "
        "about ordering: a record commit added after the verdict is uncertified "
        "tree content, and it is what made the merged commit a commit nobody had "
        "reviewed (#331)."
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


def test_reviewer_reports_the_reviewed_tree() -> None:
    """The reviewer names the tree its verdict binds to (AC-4).

    The agent-led flow has no ledger, so the identity of the certified tree has
    to travel in the report — it is what ``/ship`` checks the branch against.
    #456 moved that identity from the commit sha to the git tree object; the
    property is unchanged and the pin follows the identity rather than the
    spelling.
    """
    text = _text("agents/reviewer.md")
    assert _REVIEWED_TREE in text, (
        f"agents/reviewer.md must report the {_REVIEWED_TREE} — without an "
        "identity for the certified tree, /ship has nothing to compare against "
        "(#331, re-based on the tree oid by #456)"
    )


def test_ship_checks_head_against_the_reviewed_tree() -> None:
    """``/ship`` refuses a branch whose tree is not the certified one (AC-4).

    A third assertion required ``commands/ship.md`` to name the harness engine's
    ``stale_review`` refusal, so the agent-led rule and the audited one read as
    one rule. #435 retires the engine, so there is no second path left to be
    recognisable as; requiring the name would only pin a pointer to something
    deleted. The two assertions that carry the property — the identity it
    compares against, and the command that reads it — are the ones that fail if
    the check is dropped.

    Both moved to the tree form under #456. A bare ``git rev-parse HEAD`` would
    now satisfy neither: it prints the commit, and a commit that rewrites no
    bytes is a mismatch the tree comparison correctly ignores.
    """
    text = _text("commands/ship.md")
    assert _REVIEWED_TREE in text, (
        f"commands/ship.md must name the {_REVIEWED_TREE} it checks the branch "
        "against"
    )
    assert _TREE_OF_HEAD in text, (
        "commands/ship.md must show the check in its tree form, not merely "
        "assert the precondition — a precondition nobody runs is how the old "
        "ordering survived (#331), and a commit-sha comparison is not the "
        "identity the gate's own evidence is named after (#456)"
    )


def test_the_commit_sha_identity_is_retired() -> None:
    """No registered prose gates shipping on the commit sha any more (AC-2).

    The turned-around half of the two pins above. Deleting them and pinning the
    new spelling would have left the retired identity alive in every file this
    ticket did not happen to open — the shape that let ``/build``'s tree
    comparison and ``/ship``'s sha comparison disagree for four releases. Scoped
    over the same derived corpus as AC-2's sweep, so a file nobody listed is
    covered.

    Absence of the **identifier**, not of the word *sha*: AC-2 permits a report
    to name a commit sha for a human reader, and forbids only that the shipping
    equality be stated over one.
    """
    violations: list[str] = []
    for path in _swept_files():
        body = path.read_text(encoding="utf-8")
        if _RETIRED_IDENTITY in body:
            violations.append(_rel(path))

    assert not violations, (
        f"guidance still names {_RETIRED_IDENTITY!r} as the identity a verdict "
        f"binds to. The shipping equality is tree to tree ({_REVIEWED_TREE}), "
        f"single-homed in {_HOME}'s {_RULE_NAME} rule, and matching the object "
        "the verify gate's own evidence is named after (#456): "
        + ", ".join(sorted(violations))
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
