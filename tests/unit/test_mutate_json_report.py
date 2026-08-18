"""#363 — ``scripts/mutate.py --json``: the report as data, for a machine consumer.

#360 dropped the optional JSON dump with a stated reason: *"Nothing consumes it,
and the rendered report is the contract a tick reads."* That reason expires here.
``harness review``'s probe stage runs the harness as a subprocess and has to
decide, per entry, whether the mutation *survived*, whether an observable showed
it *live*, and whether the entry was a failure of the entry rather than a finding
— and it has to do that without a human in the loop.

The rejected alternative is parsing :func:`mutate.render`. That is textually the
defect #207 *is* — deriving a verdict from a human summary — and mutate's own
docstring forbids it ("Parsing ``N passed`` *is* #207"). So the producer grows a
machine channel rather than the consumer growing a scraper.

Two claims, and the second is the one that can rot:

* the documented shape is present and carries the node-id **sets** a consumer
  needs (``observed`` a strict superset of ``predicted`` is what makes a
  collection-breaker legible as ``mispredicted``);
* **no source text and no captured output reaches the dump.** A report row is
  read into a ledger event and pasted into a ticket. ``old``/``new`` are exact
  source substrings of the tree under review; they must not travel. That claim is
  measured by planting a distinctive literal in the mutation's ``old``/``new`` and
  asserting the serialized dump does not contain it — so adding ``"old": m.old``
  to the payload fails here rather than leaking in production.

The consumer this channel was built for — ``harness review``'s probe stage —
was retired with the runtime (ADR 0015), and the end-to-end module that proved
the wiring against that real subprocess went with it. What remains proven here
is the producer's contract: the shape, the node-id sets, and the
no-source-text guarantee of :func:`mutate.json_report` itself. ``--json`` stays
because it is mutate's machine interface for whatever next consumes a run —
the same reason the flag was added.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from tests.unit._prose import REPO_ROOT

sys.path.insert(0, str(REPO_ROOT / "scripts"))

import mutate  # noqa: E402

#: Planted in ``old``/``new`` so the no-leak claim is measured rather than
#: asserted. Deliberately not a plausible identifier: a substring search for it
#: cannot succeed by accident.
_SOURCE_SECRET = "zz-probe-source-text-must-not-travel-zz"

_ADD = "tests/test_calc.py::test_add"
_SUB = "tests/test_calc.py::test_sub"


def _mutation(ident: str = "e1", *, observe: tuple[str, ...] = ()) -> mutate.Mutation:
    return mutate.Mutation(
        id=ident,
        file="pkg/calc.py",
        old=f"return a + b  # {_SOURCE_SECRET}",
        new=f"return a - b  # {_SOURCE_SECRET}",
        kills=frozenset({_ADD}),
        note="the guard must notice addition becoming subtraction",
        observe=observe,
    )


def _result(
    mutation: mutate.Mutation,
    *,
    outcome: str,
    observed: frozenset[str],
    pristine_digest: str = "",
    mutated_digest: str = "",
) -> mutate.EntryResult:
    predicted = mutation.kills
    return mutate.EntryResult(
        mutation=mutation,
        outcome=outcome,
        observed=observed,
        missing=predicted - observed,
        unexpected=observed - predicted,
        collected=2,
        duration_s=1.25,
        detail="",
        pristine_digest=pristine_digest,
        mutated_digest=mutated_digest,
    )


def _report(*results: mutate.EntryResult) -> mutate.Report:
    return mutate.Report(
        baseline=mutate.Baseline(passed=frozenset({_ADD, _SUB}), collected=2, duration_s=0.5),
        results=results,
        work_dir=Path("/tmp/work"),
        select=("-m", "unit or guard"),
    )


def test_the_dump_carries_the_documented_top_level_shape() -> None:
    """``select`` + ``baseline`` + ``results``, and nothing else."""
    report = _report(_result(_mutation(), outcome="killed", observed=frozenset({_ADD})))

    payload = mutate.json_report(report)

    assert set(payload) == {"select", "baseline", "results"}
    assert payload["select"] == ["-m", "unit or guard"]
    assert payload["baseline"] == {"passed": 2, "collected": 2, "duration_s": 0.5}


def test_an_entry_carries_the_node_id_sets_a_consumer_classifies_on() -> None:
    """A collection-breaker is legible as an over-kill, not as a kill.

    ``observed`` a strict superset of ``predicted`` is exactly what separates
    ``mispredicted`` from ``killed``, and a consumer that saw only counts could
    not tell an over-kill from a differently-shaped equal-sized set.
    """
    over_kill = frozenset({_ADD, _SUB})
    report = _report(_result(_mutation(), outcome="mispredicted", observed=over_kill))

    (entry,) = mutate.json_report(report)["results"]

    assert entry["id"] == "e1"
    assert entry["outcome"] == "mispredicted"
    assert entry["predicted"] == [_ADD]
    assert entry["observed"] == sorted(over_kill)
    assert entry["unexpected"] == [_SUB]
    assert entry["missing"] == []
    assert entry["collected"] == 2
    assert entry["duration_s"] == 1.25


def test_a_liveness_fork_is_readable_from_the_two_digests() -> None:
    """#365's fork travels: equal digests are ``inert``, differing ones are live."""
    live = _result(
        _mutation("live", observe=("-c", "print(1)")),
        outcome="survived",
        observed=frozenset(),
        pristine_digest="aaa",
        mutated_digest="bbb",
    )
    inert = _result(
        _mutation("inert", observe=("-c", "print(1)")),
        outcome="inert",
        observed=frozenset(),
        pristine_digest="ccc",
        mutated_digest="ccc",
    )
    unproven = _result(_mutation("unproven"), outcome="survived", observed=frozenset())

    results = {e["id"]: e for e in mutate.json_report(_report(live, inert, unproven))["results"]}

    assert results["live"]["pristine_digest"] != results["live"]["mutated_digest"]
    assert results["inert"]["pristine_digest"] == results["inert"]["mutated_digest"]
    assert results["unproven"]["pristine_digest"] == ""
    assert results["unproven"]["mutated_digest"] == ""


def test_no_source_text_from_the_mutated_tree_reaches_the_dump() -> None:
    """The no-leak rule, measured on a planted literal rather than asserted.

    ``old``/``new`` are exact substrings of the tree under review and a dump row
    is read into a ledger event. Serializing the whole payload and searching it
    is the check that survives someone adding a field: it does not enumerate the
    keys that are allowed, it enumerates the value that is not.
    """
    report = _report(
        _result(_mutation(), outcome="survived", observed=frozenset()),
        _result(_mutation("e2"), outcome="mispredicted", observed=frozenset({_SUB})),
    )

    serialized = json.dumps(mutate.json_report(report))

    # The literal really is on the mutations being dumped — without this the
    # absence assertion above is free.
    assert _SOURCE_SECRET in report.results[0].mutation.old
    assert _SOURCE_SECRET not in serialized


def test_the_dump_is_json_serializable_as_written() -> None:
    """No ``frozenset``, no ``Path`` — the producer, not the caller, flattens."""
    report = _report(_result(_mutation(), outcome="killed", observed=frozenset({_ADD})))

    round_tripped = json.loads(json.dumps(mutate.json_report(report)))

    assert round_tripped == mutate.json_report(report)
