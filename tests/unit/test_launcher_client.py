"""Unit tests for :mod:`harness.launcher_client` — the agent-side socket client.

The agent runtime routes every verb through the launcher control socket
(decision #1): ``harness <verb> …`` becomes one ``{"op", "params"}`` request.
These tests cover the argv → request mapping in isolation; the socket round-trip
against a real :class:`~harness.launcher.ControlServer` lives in
``tests/integration/test_launcher_client.py``.
"""

from __future__ import annotations

import pytest

from harness.launcher import OPERATIONS
from harness.launcher_client import UnsupportedVerb, verb_argv_to_request

REPO = "/work/repo"


def test_start_maps_to_start_op_with_ticket_and_base() -> None:
    req = verb_argv_to_request(["start", "CAL-1", "--base", "dev"], repo=REPO)
    assert req == {"op": "start", "params": {"repo": REPO, "ticket": "CAL-1", "base": "dev"}}


def test_start_without_base() -> None:
    req = verb_argv_to_request(["start", "CAL-1"], repo=REPO)
    assert req == {"op": "start", "params": {"repo": REPO, "ticket": "CAL-1"}}


def test_review_maps_to_review_op_with_run_id() -> None:
    req = verb_argv_to_request(["review", "--run-id", "R1"], repo=REPO)
    assert req == {"op": "review", "params": {"repo": REPO, "run_id": "R1"}}


def test_close_maps_to_close_op_with_ticket_and_run_id() -> None:
    req = verb_argv_to_request(["close", "CAL-1", "--run-id", "R1"], repo=REPO)
    assert req == {"op": "close", "params": {"repo": REPO, "run_id": "R1", "ticket": "CAL-1"}}


@pytest.mark.parametrize("verb", ["status", "events", "cancel"])
def test_run_id_positional_ops(verb: str) -> None:
    req = verb_argv_to_request([verb, "R1", "--json"], repo=REPO)
    assert req == {"op": verb, "params": {"repo": REPO, "run_id": "R1"}}


def test_decision_maps_to_decision_op() -> None:
    req = verb_argv_to_request(["decision", "R1", "approve"], repo=REPO)
    assert req == {"op": "decision", "params": {"repo": REPO, "run_id": "R1", "value": "approve"}}


def test_repo_and_db_flags_are_dropped_in_favour_of_the_mount() -> None:
    # The agent's CWD is the mounted workspace; a --repo/--db the loop passes is
    # ignored — the launcher sets the repo/ledger path server-side.
    req = verb_argv_to_request(
        ["review", "--run-id", "R1", "--repo", "/somewhere/else", "--db", "/x.db"], repo=REPO
    )
    assert req["params"]["repo"] == REPO


def test_every_mapped_op_is_a_real_launcher_operation() -> None:
    # The client never invents an op the server does not expose.
    for argv in (
        ["start", "CAL-1"],
        ["review", "--run-id", "R1"],
        ["close", "CAL-1", "--run-id", "R1"],
        ["status", "R1"],
        ["events", "R1"],
        ["cancel", "R1"],
        ["decision", "R1", "approve"],
    ):
        assert verb_argv_to_request(argv, repo=REPO)["op"] in OPERATIONS


@pytest.mark.parametrize("argv", [[], ["run", "build"], ["doctor"], ["serve", "--local"]])
def test_unsupported_verb_is_rejected(argv: list[str]) -> None:
    with pytest.raises(UnsupportedVerb):
        verb_argv_to_request(argv, repo=REPO)


def test_missing_required_argument_is_rejected() -> None:
    with pytest.raises(UnsupportedVerb):
        verb_argv_to_request(["start"], repo=REPO)  # no ticket
    with pytest.raises(UnsupportedVerb):
        verb_argv_to_request(["review"], repo=REPO)  # no --run-id
