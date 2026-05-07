"""Tests for harness.identity — see SPEC §8."""

from __future__ import annotations

import re
import time
from pathlib import Path

import pytest

from harness import identity

# ULID is 26 chars in Crockford base32: 0-9 + A-Z minus I, L, O, U
ULID_PATTERN = re.compile(r"^[0-9A-HJKMNP-TV-Z]{26}$")


# ---------------------------------------------------------------------------
# generate_run_id
# ---------------------------------------------------------------------------


def test_generate_run_id_is_26_characters() -> None:
    run_id = identity.generate_run_id()
    assert len(run_id) == 26


def test_generate_run_id_uses_crockford_alphabet() -> None:
    run_id = identity.generate_run_id()
    assert ULID_PATTERN.match(run_id), f"run_id {run_id!r} is not a valid ULID"


def test_generate_run_id_is_unique_across_calls() -> None:
    ids = {identity.generate_run_id() for _ in range(100)}
    assert len(ids) == 100


def test_generate_run_id_is_lexicographically_time_ordered() -> None:
    """Later calls produce IDs that sort after earlier ones (ULID property).

    ULIDs encode the timestamp at millisecond resolution; two calls within the
    same millisecond have only the random suffix to distinguish them, which is
    not guaranteed to be ordered. Sleep 2ms between calls so the timestamp
    prefix differs and the property is observable.
    """
    earlier = identity.generate_run_id()
    time.sleep(0.002)
    later = identity.generate_run_id()
    assert later > earlier


# ---------------------------------------------------------------------------
# worktree_dir
# ---------------------------------------------------------------------------


def test_worktree_dir_format() -> None:
    run_id = identity.generate_run_id()
    path = identity.worktree_dir(run_id)
    assert path == Path(".worktrees/harness") / run_id


def test_worktree_dir_returns_relative_path() -> None:
    path = identity.worktree_dir(identity.generate_run_id())
    assert not path.is_absolute()


# ---------------------------------------------------------------------------
# worktree_branch
# ---------------------------------------------------------------------------


def test_worktree_branch_format() -> None:
    run_id = identity.generate_run_id()
    branch = identity.worktree_branch(run_id)
    assert branch == f"harness/{run_id}"


# ---------------------------------------------------------------------------
# artifacts_dir
# ---------------------------------------------------------------------------


def test_artifacts_dir_format() -> None:
    run_id = identity.generate_run_id()
    path = identity.artifacts_dir(run_id)
    assert path == Path(".harness/artifacts") / run_id


def test_artifacts_dir_returns_relative_path() -> None:
    path = identity.artifacts_dir(identity.generate_run_id())
    assert not path.is_absolute()


# ---------------------------------------------------------------------------
# log_path
# ---------------------------------------------------------------------------


def test_log_path_format() -> None:
    run_id = identity.generate_run_id()
    path = identity.log_path(run_id)
    assert path == Path(".harness/logs") / f"{run_id}.log"


def test_log_path_returns_relative_path() -> None:
    path = identity.log_path(identity.generate_run_id())
    assert not path.is_absolute()


# ---------------------------------------------------------------------------
# Validation — every helper rejects invalid run_ids
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "bad_id",
    [
        "",
        "too-short",
        "X" * 26 + "extra",
        "01HZQK7M4VT2RY9Q5N3K8B6F0I",  # contains I — not in Crockford
        "01HZQK7M4VT2RY9Q5N3K8B6F0L",  # contains L
        "01HZQK7M4VT2RY9Q5N3K8B6F0U",  # contains U
        "01hzqk7m4vt2ry9q5n3k8b6f0z",  # lowercase rejected
    ],
)
def test_helpers_reject_invalid_run_id(bad_id: str) -> None:
    with pytest.raises(ValueError, match="run_id"):
        identity.worktree_dir(bad_id)
    with pytest.raises(ValueError, match="run_id"):
        identity.worktree_branch(bad_id)
    with pytest.raises(ValueError, match="run_id"):
        identity.artifacts_dir(bad_id)
    with pytest.raises(ValueError, match="run_id"):
        identity.log_path(bad_id)
