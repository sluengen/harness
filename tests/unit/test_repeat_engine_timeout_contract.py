"""#347 — the contract around a *repeated* review-engine timeout.

The short-circuit itself (two attempts at one SHA, then refuse) is measured in
``tests/unit/test_review_breakers.py``, where the quantity the ticket is stated
in — the number of engine invocations — is asserted. What this file holds is the
contract around it, in three parts the ticket's ACs name separately:

* **AC-4, the corrected remediation text.** Each of run
  01KZ67FRV3HZRZ8CMAHBYBP4QT's four ``engine_timeout`` events carried a ``detail``
  reading "Raise ``engine_timeout_seconds`` … if the engine legitimately needs
  longer". Here the engine did not need longer — it hung, and the ceiling was the
  only thing that caught it. Following that advice would have spent *more* budget
  per dead attempt and brought the wall-clock breaker forward: the text steered
  the next reader toward the one change that makes this worse. The guard asserts
  the whole claim rather than a fragment of it — the hang case is named *before*
  the ceiling, the repeat refusal is named by its imported tag, and the ceiling is
  no longer offered as an unconditional imperative.
* **AC-5**, that the ceiling itself did not move.
* **The gate-width invariant**, which this ticket is the first to put under real
  pressure: the refusal shape now carries ``reviewed_sha``, the close gate's own
  binding key. A refusal must still be unable to certify a tree.
* **A doc guard**, so the orchestrator's actual retry site — guidance prose in
  ``commands/harness.md``, which tells the reader to treat ``engine_timeout``
  like the other infra walls and *just re-run* — states the bound.
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

from harness.cli import review as review_mod
from harness.cli._review_gate import certify_head
from harness.events.payloads import (
    REVIEW_REFUSAL_REASON_PATH,
    REVIEW_REVIEWED_SHA_PATH,
    ReviewRefusalEventData,
)
from harness.loop_budget import (
    DEFAULT_ENGINE_TIMEOUT_SECONDS,
    REPEAT_ENGINE_TIMEOUT_REASON,
    load_loop_budget,
)
from harness.state import store
from tests._asyncutil import run_sync

REPO_ROOT = Path(__file__).parent.parent.parent
HARNESS_COMMAND = REPO_ROOT / "commands" / "harness.md"
CLI_SURFACE_SPEC = REPO_ROOT / "specs" / "features" / "cli-surface.md"


def _timeout_message() -> str:
    """The message the verb actually raises on a hung engine.

    Driven through the real mechanism — a genuinely hanging child under a tiny
    ceiling — rather than read out of the source, so the guard holds the text a
    reader is served, not a string that happens to sit in a file.
    """
    hang = [sys.executable, "-c", "import time; time.sleep(30)"]

    async def _run() -> None:
        await review_mod._default_runner(
            cmd=hang, stdin="ignored", env=dict(os.environ), cwd=None, timeout=0.2
        )

    with pytest.raises(review_mod._ReviewError) as excinfo:
        asyncio.run(_run())
    return str(excinfo.value)


# ---------------------------------------------------------------------------
# AC-4 — the remediation text no longer leads with the ceiling
# ---------------------------------------------------------------------------


def test_the_timeout_message_names_the_hang_before_the_ceiling() -> None:
    """Ordering is the claim: the hang is the diagnosis, the ceiling a caveat.

    Asserted by string index rather than by presence, because the old text also
    mentioned both — what was wrong was which one it offered as the remedy.
    """
    message = _timeout_message()
    hang_at = message.index("hung engine")
    ceiling_at = message.index("engine_timeout_seconds")
    assert hang_at < ceiling_at, message


def test_the_timeout_message_conditions_the_ceiling_on_evidence() -> None:
    """The ceiling is a remedy only for an engine that *finishes* just past it.

    The retired wording — an unconditional "Raise engine_timeout_seconds … if the
    engine legitimately needs longer" — read as the default next step. The
    replacement names the observation that would justify it, so a reader who has
    not made that observation is not being told to raise anything.
    """
    message = _timeout_message()
    assert "Raise engine_timeout_seconds in CONTEXT.md's loop: block" not in message
    assert "finishing" in message


def test_the_timeout_message_names_the_repeat_refusal_by_tag() -> None:
    """A rename of the breaker tag must break this guard, not silently pass.

    The message is what tells an orchestrator its one re-run is bounded; if it
    named the refusal in prose only, the tag it actually receives on the second
    timeout could drift away from the tag the text promised.
    """
    assert REPEAT_ENGINE_TIMEOUT_REASON in _timeout_message()


def test_the_ceiling_is_not_what_this_fix_moves() -> None:
    """AC-5: this ticket bounds the *retry*; it does not buy a longer hang.

    Asserted as the lockstep invariant CONTEXT.md states — the configured ceiling
    equals :data:`~harness.loop_budget.DEFAULT_ENGINE_TIMEOUT_SECONDS`, so a repo
    carrying no ``loop:`` block runs the same number this one does — rather than
    by freezing the literal 720. The ceiling has legitimately moved once already,
    600 → 720, on measured evidence that the old bound sat inside the working
    distribution; a guard pinning today's value would forbid the next such
    decision while proving nothing about *this* change, whose diff leaves
    CONTEXT.md untouched.
    """
    assert load_loop_budget(REPO_ROOT).engine_timeout_seconds == DEFAULT_ENGINE_TIMEOUT_SECONDS


# ---------------------------------------------------------------------------
# The gate-width invariant, under new pressure
# ---------------------------------------------------------------------------


_RUN_ID = "01JRREPEATTIMEOUTXXXXXXX01"


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    _git(repo_root, "init", "-b", "dev")
    _git(repo_root, "config", "user.email", "test@example.com")
    _git(repo_root, "config", "user.name", "Test")
    (repo_root / "README.md").write_text("hello\n")
    _git(repo_root, "add", "README.md")
    _git(repo_root, "commit", "-m", "initial")
    return repo_root


def test_a_timeout_refusal_bound_to_head_still_cannot_certify_it(repo: Path) -> None:
    """The refusal now carries the gate's own binding key — and still cannot pass.

    Before #347 this invariant held trivially: a refusal had no ``reviewed_sha``
    at all, so it could not match a HEAD even in principle. Now it can, and the
    only thing standing between a recorded *failure* and a certified tree is the
    absent ``verdict`` key. That is enforcement by absence, so it is pinned here
    rather than left to inspection.
    """
    db_path = repo / ".harness" / "harness.db"
    head = _git(repo, "rev-parse", "HEAD").stdout.strip()

    async def _seed() -> None:
        await store.init_db(db_path)
        async with store.connect(db_path) as conn:
            await conn.execute(
                "INSERT INTO runs (run_id, workflow_name, workflow_version, status, "
                "state_json, inputs_json, base_branch, worktree_path, worktree_branch, "
                "ticket, started_at, pid) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    _RUN_ID,
                    "",
                    0,
                    "open",
                    "{}",
                    "{}",
                    "dev",
                    str(repo),
                    f"harness/{_RUN_ID}",
                    "347",
                    datetime.now(UTC).isoformat(),
                    1234,
                ),
            )
            for reason in ("engine_timeout", REPEAT_ENGINE_TIMEOUT_REASON):
                await conn.execute(
                    "INSERT INTO events (run_id, event_type, timestamp, data_json) "
                    "VALUES (?, 'review', ?, ?)",
                    (
                        _RUN_ID,
                        datetime.now(UTC).isoformat(),
                        json.dumps(
                            ReviewRefusalEventData(
                                run_id=_RUN_ID,
                                reason=reason,
                                detail="the engine hung",
                                created_at=datetime.now(UTC).isoformat(),
                                reviewed_sha=head,
                            ).model_dump(exclude_none=True)
                        ),
                    ),
                )
            await conn.commit()

    run_sync(_seed())

    certification = run_sync(certify_head(db_path, _RUN_ID, head))
    assert not certification.certified
    assert certification.verdict == "no_passing_review"


def test_a_pre_head_refusal_records_no_sha_at_all() -> None:
    """``exclude_none=True`` keeps the key out, so pre-#347 rows stay byte-identical.

    The guard counts by exact SHA match, so a refusal that invented a placeholder
    — an empty string, a literal ``"unknown"`` — would put rows into a bucket the
    count could one day collide with.
    """
    row = ReviewRefusalEventData(
        run_id=_RUN_ID,
        reason="no_gate_evidence",
        detail="the gate was never run",
        created_at=datetime.now(UTC).isoformat(),
    ).model_dump(exclude_none=True)
    assert "reviewed_sha" not in row
    assert "verdict" not in row


def test_the_two_review_shapes_name_the_sha_with_one_key() -> None:
    """The count reads one path across both shapes; a drift would read zero."""
    assert REVIEW_REVIEWED_SHA_PATH == "$.reviewed_sha"
    assert REVIEW_REFUSAL_REASON_PATH == "$.reason"


# ---------------------------------------------------------------------------
# Doc guard — the orchestrator's retry site states the bound
# ---------------------------------------------------------------------------


def _slice(doc: str, start_needle: str, end_needle: str) -> str:
    start = doc.index(start_needle)
    return doc[start : doc.index(end_needle, start)]


def test_the_infra_wall_paragraph_bounds_the_re_run() -> None:
    """``commands/harness.md`` says to just re-run an infra wall — with a bound.

    That instruction is the orchestrator's actual retry site: the harness verb is
    one-shot, so the loop #330 spent 48 minutes in was driven by this prose. It
    must now say the re-run is bounded and name the refusal that ends it, by tag,
    so a rename cannot leave the doc promising a tag nobody emits.

    The bound is asserted as the **claim** the paragraph makes, not as the bare
    token ``once``. That token was the original guard and it did not hold: a
    rewrite dropping the bound outright — "re-run it with care", followed by an
    ordinary "read the verdict once the engine returns" elsewhere in the region —
    still satisfied it, because ``once`` is common enough in running prose to
    reappear by accident. The negation is what carries the meaning: a doc telling
    the reader to re-run *until it works* is exactly the loop this ticket closes,
    so its explicit denial is the sentence worth pinning.
    """
    region = _slice(
        HARNESS_COMMAND.read_text(),
        "**A review that produced no verdict is not a `fail`.**",
        "Act on `verdict`:",
    )
    assert REPEAT_ENGINE_TIMEOUT_REASON in region
    assert "not until it works" in region


def test_the_exit_4_row_lists_the_third_breaker() -> None:
    """The as-built exit table must name every reason that lands on exit 4.

    An orchestrator branching on exit code alone would treat this as one of the
    two known breakers and take their recovery — cancel-and-resume, which opens a
    fresh budget window and walks straight back into the same hang.
    """
    exit_4_row = next(
        line for line in CLI_SURFACE_SPEC.read_text().splitlines() if line.startswith("| 4 |")
    )
    assert REPEAT_ENGINE_TIMEOUT_REASON in exit_4_row
