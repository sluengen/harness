"""#363 — the reviewer's mutation budget, decided purely.

`harness review`'s probe stage gives the reviewer an independent counterparty
role on the mutation table: it *proposes* entries in #360's format, the verb runs
them through that harness against a throwaway tree at the reviewed SHA, and a
survivor comes back for a second engine pass. This module holds every rule that
can be decided without spawning anything — the screen, the TOML rendering, the
report reading, the second-pass brief, and the verdict combination — on the
`review_protocol` precedent that a pure layer is provable on its own.

The two claims that carry this ticket are both here, because both are about
*judgment*, not plumbing:

* **AC-2, in both directions.** An entry that kills nothing and an entry that
  breaks collection are each a failure of **the entry**, never a survivor and
  never a finding. That is what stops the vacuity this whole repo pays for from
  simply relocating into review: a reviewer that runs something and reads green
  has produced a feeling, not evidence.
* **The proposal is untrusted input.** It originates in an engine reading a diff
  and a ticket, both injectable. The screen is the boundary, and the TOML
  renderer is the sharper half of it — a table is a structured document, so a
  proposal that can spell a delimiter can write entries nobody proposed.

`kills` is #360 AC-1's contract and is required, not optional: an entry that
declares no prediction cannot be judged, and an unjudged probe is exactly the
"ran a suite, saw green, concluded verified" shape.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from harness.cli.review_probe import (
    PROBE_SELECT,
    ProbeOutcome,
    build_probe_feedback,
    combine_issues,
    combine_verdict,
    demonstrated_ids,
    read_probe_report,
    render_probe_table,
    screen_proposals,
    survivors,
)

_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT / "scripts"))

import mutate  # noqa: E402

_ADD = "tests/test_calc.py::test_add"


def _tree(tmp_path: Path) -> Path:
    """A minimal probe tree: one target file, one sentinel, one test path."""
    tree = tmp_path / "probe"
    (tree / "pkg").mkdir(parents=True)
    (tree / "pkg" / "calc.py").write_text("def add(a, b):\n    return a + b\n", encoding="utf-8")
    (tree / ".harness-probe").write_text("run-1 abc123\n", encoding="utf-8")
    return tree


def _proposal(**over: object) -> dict[str, object]:
    base: dict[str, object] = {
        "id": "e1",
        "file": "pkg/calc.py",
        "old": "return a + b",
        "new": "return a - b",
        "kills": [_ADD],
        "note": "the guard must notice addition becoming subtraction",
    }
    base.update(over)
    return base


# ---------------------------------------------------------------------------
# The screen — the boundary the untrusted proposal crosses.
# ---------------------------------------------------------------------------


def test_a_well_formed_proposal_is_kept(tmp_path: Path) -> None:
    screened = screen_proposals([_proposal()], tree=_tree(tmp_path), cap=3)

    assert screened.proposed == 1
    assert [p.id for p in screened.kept] == ["e1"]
    assert screened.dropped == ()


@pytest.mark.parametrize(
    ("override", "reason"),
    [
        ({"id": ""}, "missing_id"),
        ({"kills": []}, "no_kills"),
        ({"new": "return a + b"}, "identical"),
        ({"file": "pkg/absent.py"}, "file_missing"),
        ({"file": "../outside.py"}, "file_outside_tree"),
        ({"old": "return a * b"}, "old_absent"),
        ({"old": "a"}, "old_ambiguous"),
    ],
    ids=[
        "missing-id",
        "no-kills",
        "identical",
        "file-missing",
        "file-outside-tree",
        "old-absent",
        "old-ambiguous",
    ],
)
def test_each_rejection_class_drops_that_entry_with_its_own_reason(
    tmp_path: Path, override: dict[str, object], reason: str
) -> None:
    """Every drop is named. A silent screen is a budget spent on nothing.

    Each of these is a rule ``mutate`` applies **authoritatively** — and applies
    to the *whole table*. Without the pre-screen one bad entry voids the entire
    budget, which is why the screen duplicates them rather than deferring.
    """
    screened = screen_proposals([_proposal(**override)], tree=_tree(tmp_path), cap=3)

    assert screened.kept == ()
    assert [r for _, r in screened.dropped] == [reason]


def test_a_duplicate_id_drops_only_the_second(tmp_path: Path) -> None:
    """``id`` is what the second pass cites by, so it has to be a handle."""
    screened = screen_proposals(
        [_proposal(), _proposal(new="return a * b")], tree=_tree(tmp_path), cap=3
    )

    assert [p.new for p in screened.kept] == ["return a - b"]
    assert [r for _, r in screened.dropped] == ["duplicate_id"]


def test_a_value_that_is_not_a_proposal_is_dropped_not_raised(tmp_path: Path) -> None:
    """A malformed ``probes`` value never costs a verdict (it is an addition to
    the SUBMIT contract, not a new way to fail it)."""
    screened = screen_proposals(
        ["not-an-object", {"id": "e2"}, _proposal()], tree=_tree(tmp_path), cap=3
    )

    assert [p.id for p in screened.kept] == ["e1"]
    assert [r for _, r in screened.dropped] == ["malformed", "malformed"]


def test_a_probes_value_that_is_not_a_list_yields_nothing_proposed(tmp_path: Path) -> None:
    screened = screen_proposals({"id": "e1"}, tree=_tree(tmp_path), cap=3)

    assert screened.proposed == 0
    assert screened.kept == ()


def test_the_count_cap_is_enforced_and_the_cut_entries_are_named(tmp_path: Path) -> None:
    """AC-4's count half. Truncation is reported, never silent (#350's rule)."""
    proposals = [_proposal(id=f"e{n}", new=f"return a - b  # {n}") for n in range(7)]

    screened = screen_proposals(proposals, tree=_tree(tmp_path), cap=3)

    assert [p.id for p in screened.kept] == ["e0", "e1", "e2"]
    assert [(i, r) for i, r in screened.dropped] == [
        ("e3", "over_cap"),
        ("e4", "over_cap"),
        ("e5", "over_cap"),
        ("e6", "over_cap"),
    ]


def test_a_cap_of_zero_keeps_nothing(tmp_path: Path) -> None:
    """The disable switch is the cap itself, on ``untracked_file_limit``'s
    convention — one knob, not a knob plus a flag that can disagree with it."""
    screened = screen_proposals([_proposal()], tree=_tree(tmp_path), cap=0)

    assert screened.kept == ()
    assert [r for _, r in screened.dropped] == ["over_cap"]


# ---------------------------------------------------------------------------
# The table renderer — a structured document written from untrusted strings.
# ---------------------------------------------------------------------------


def test_the_rendered_table_loads_through_mutates_own_parser(tmp_path: Path) -> None:
    """The contract under test is ``mutate.load_table``, so use it.

    A second TOML parser here would prove the renderer emits *some* valid TOML,
    which is not the claim — the claim is that the harness this feeds accepts it.
    """
    tree = _tree(tmp_path)
    screened = screen_proposals(
        [_proposal(observe=["-c", "import pkg.calc; print(pkg.calc.add(1, 2))"])],
        tree=tree,
        cap=3,
    )
    table_path = tmp_path / "probe.toml"
    table_path.write_text(
        render_probe_table(
            screened.kept, sentinel_file=".harness-probe", sentinel_text="run-1 abc123"
        ),
        encoding="utf-8",
    )

    table = mutate.load_table(table_path)

    assert table.select == PROBE_SELECT
    (entry,) = table.mutations
    assert entry.id == "e1"
    assert entry.old == "return a + b"
    assert entry.kills == frozenset({_ADD})
    assert entry.observe == ("-c", "import pkg.calc; print(pkg.calc.add(1, 2))")
    # Containment is certified against *this run's* probe tree, which is what
    # makes running a reviewer's table against the run worktree impossible.
    assert table.sentinel_file == ".harness-probe"


def test_a_proposal_cannot_forge_a_second_entry_through_the_table(tmp_path: Path) -> None:
    """The sharp half of "the proposal is untrusted".

    A table is a structured document. A renderer using TOML's ``'''literal'''``
    delimiters — the spelling a human tick writes by hand — lets any proposal
    containing that delimiter close the string and open a ``[[mutation]]`` of its
    own, escaping the count cap, the screen and the verb-owned ``select`` in one
    step. Quoting every value instead makes the injection unrepresentable rather
    than filtered, which is the difference between a boundary and a blocklist.
    """
    tree = _tree(tmp_path)
    injected = "\n'''\nselect = [\"tests\"]\n[[mutation]]\nid = \"forged\"\n"
    screened = screen_proposals(
        [_proposal(note=injected, kills=[_ADD])], tree=tree, cap=3
    )
    table_path = tmp_path / "probe.toml"
    table_path.write_text(
        render_probe_table(
            screened.kept, sentinel_file=".harness-probe", sentinel_text="run-1 abc123"
        ),
        encoding="utf-8",
    )

    table = mutate.load_table(table_path)

    assert [m.id for m in table.mutations] == ["e1"]
    assert table.select == PROBE_SELECT
    # The injection really was carried through the screen — without this the
    # assertion above passes against a renderer that simply dropped `note`.
    assert table.mutations[0].note == injected


# ---------------------------------------------------------------------------
# Reading the report — AC-2, both directions.
# ---------------------------------------------------------------------------


def _row(ident: str, outcome: str, **over: object) -> dict[str, object]:
    row: dict[str, object] = {
        "id": ident,
        "outcome": outcome,
        "predicted": [_ADD],
        "observed": [_ADD] if outcome == "killed" else [],
        "missing": [],
        "unexpected": [],
        "collected": 2,
        "duration_s": 1.5,
        "detail": "",
        "pristine_digest": "",
        "mutated_digest": "",
    }
    row.update(over)
    return row


def test_a_live_survivor_is_demonstrated(tmp_path: Path) -> None:
    outcomes = read_probe_report(
        {"results": [_row("weak", "survived", pristine_digest="aaa", mutated_digest="bbb")]}
    )

    (outcome,) = outcomes
    assert outcome.live is True
    assert outcome.citable is True
    assert demonstrated_ids(outcomes) == ("weak",)
    assert survivors(outcomes) == outcomes


def test_a_survivor_with_no_observable_is_a_lead_not_a_demonstration() -> None:
    """#365's ``SURVIVED (UNPROVEN)``, carried across the boundary intact.

    It still reaches the second pass — it is a real lead — but it is absent from
    ``probe_demonstrated``, because nothing has shown the mutation was live and
    four of #336's twenty entries looked exactly like this.
    """
    outcomes = read_probe_report({"results": [_row("unproven", "survived")]})

    (outcome,) = outcomes
    assert outcome.live is False
    assert outcome.citable is True
    assert demonstrated_ids(outcomes) == ()
    assert survivors(outcomes) == outcomes


def test_an_entry_that_kills_nothing_and_moves_nothing_is_a_failure_of_the_entry() -> None:
    """AC-2, direction one. ``inert`` is not a survivor and is cited nowhere."""
    outcomes = read_probe_report(
        {"results": [_row("noop", "inert", pristine_digest="ccc", mutated_digest="ccc")]}
    )

    (outcome,) = outcomes
    assert outcome.outcome == "inert"
    assert outcome.citable is False
    assert demonstrated_ids(outcomes) == ()
    assert survivors(outcomes) == ()


def test_an_entry_that_breaks_collection_is_a_failure_of_the_entry() -> None:
    """AC-2, direction two. Over-kill fails the same set equality the no-op does."""
    outcomes = read_probe_report(
        {
            "results": [
                _row(
                    "breaker",
                    "mispredicted",
                    observed=[_ADD, "tests/test_calc.py::test_sub"],
                    unexpected=["tests/test_calc.py::test_sub"],
                )
            ]
        }
    )

    (outcome,) = outcomes
    assert outcome.outcome == "mispredicted"
    assert outcome.citable is False
    assert outcome.observed == 2
    assert survivors(outcomes) == ()


def test_a_killed_entry_is_the_guard_working_and_is_not_a_finding() -> None:
    outcomes = read_probe_report({"results": [_row("good", "killed")]})

    assert outcomes[0].citable is False
    assert survivors(outcomes) == ()


def test_an_unreadable_report_yields_no_outcomes_rather_than_raising() -> None:
    """The probe stage degrades on every path; it never wedges a review."""
    assert read_probe_report({"results": "nonsense"}) == ()
    assert read_probe_report([]) == ()
    assert read_probe_report({"results": [{"id": "x"}]}) == ()


# ---------------------------------------------------------------------------
# The second-pass brief.
# ---------------------------------------------------------------------------


def test_the_brief_separates_a_demonstration_from_a_lead_and_from_a_defect() -> None:
    """The rules, stated to the engine rather than the raw report handed over.

    A reviewer given a table of outcomes will read every non-``killed`` row as a
    hole. The distinction between the three is the whole content of #365, and it
    is not recoverable from the row alone.
    """
    outcomes = read_probe_report(
        {
            "results": [
                _row("live-one", "survived", pristine_digest="aaa", mutated_digest="bbb"),
                _row("unproven-one", "survived"),
                _row("inert-one", "inert", pristine_digest="c", mutated_digest="c"),
                _row("broke-one", "mispredicted", observed=[_ADD, "x::y"]),
            ]
        }
    )

    brief = build_probe_feedback(outcomes)

    assert "live-one" in brief
    assert "unproven-one" in brief
    # A failure of the entry may not be cited at all, so it is not named as an
    # available finding — naming it invites the reviewer to raise it anyway.
    assert "inert-one" not in brief
    assert "broke-one" not in brief
    assert "[probe:" in brief


# ---------------------------------------------------------------------------
# Combination — computed, never trusted to the second pass.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("first", "second", "expected"),
    [
        ("pass", "pass", "pass"),
        ("pass", "fail", "fail"),
        ("fail", "pass", "fail"),
        ("fail", "defer", "fail"),
        ("defer", "pass", "defer"),
        ("pass", "defer", "defer"),
        ("defer", "fail", "fail"),
    ],
    ids=[
        "pass-pass",
        "pass-fail",
        "fail-pass",
        "fail-defer",
        "defer-pass",
        "pass-defer",
        "defer-fail",
    ],
)
def test_the_combined_verdict_is_monotone_in_severity(
    first: str, second: str, expected: str
) -> None:
    """Probing adds evidence; it can never retract a finding the first pass made.

    ``fail-pass`` is the load-bearing row: a second pass that saw the probe
    outcomes and said "pass" must not overturn the first pass's rejection of the
    diff, because it was asked about the probes, not re-asked about the diff.
    """
    assert combine_verdict(first, second) == expected


def test_the_issue_union_keeps_the_first_passs_findings_and_adds_the_seconds() -> None:
    combined = combine_issues(["a real finding", "another"], ["another", "[probe:x] a gap"])

    assert combined == ["a real finding", "another", "[probe:x] a gap"]


def test_a_second_pass_that_says_nothing_loses_no_finding() -> None:
    assert combine_issues(["a real finding"], []) == ["a real finding"]
    assert combine_verdict("fail", None) == "fail"
    assert combine_issues(["a real finding"], None) == ["a real finding"]


def test_outcome_construction_is_bounded_to_counts_and_ids() -> None:
    """Nothing that reaches the ledger carries source text or captured output."""
    outcome = ProbeOutcome(
        id="e1", outcome="survived", live=True, predicted=1, observed=0, duration_ms=1500
    )

    assert set(outcome.as_payload()) == {
        "id",
        "outcome",
        "live",
        "predicted",
        "observed",
        "duration_ms",
    }
