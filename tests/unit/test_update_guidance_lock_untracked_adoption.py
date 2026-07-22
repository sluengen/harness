"""#173 — ``/update-guidance`` step 2 adopts a registry-listed, on-disk,
lock-untracked file instead of silently ignoring it.

A file that graduates from repo-owned/hand-copied to a registry-tracked
distributable (the exact transition ``commands/harness.md`` made in CAL-764)
falls through step 2's classification table: it isn't "new" (source-added,
absent on disk — it IS on disk) and it isn't any lock-keyed state (it isn't in
the lock at all). A consumer installed before the graduation stays silently
stranded on a stale copy of a file the registry now owns, as happened to the
``form`` repo (issue #173).

These tests pin the fix: step 2 explicitly classifies a **registry-listed /
on-disk / lock-untracked** file two ways —

* **hash matches the source** — adopt it into the lock silently, no
  confirmation (it is already correct).
* **hash differs** — treat it as a CONFLICT-shaped reconcile (show a diff, ask
  before overwriting) — a 2-way diff, since there is no locked version to serve
  as a 3-way base.

— and states the file must never be left lock-untracked-and-ignored.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
UPDATE_GUIDANCE = REPO_ROOT / "commands" / "update-guidance.md"


def _text() -> str:
    return UPDATE_GUIDANCE.read_text(encoding="utf-8")


def test_step2_names_the_registry_listed_on_disk_lock_untracked_case() -> None:
    """Step 2 explicitly names the case a file in this shape falls into."""
    text = _text()
    assert re.search(r"registry-listed.{0,40}on-disk.{0,40}lock-untracked", text), (
        "commands/update-guidance.md step 2 must explicitly name the "
        "registry-listed / on-disk / lock-untracked case (#173) — the gap that "
        "let a graduated file (e.g. commands/harness.md, CAL-764) stay silently "
        "stranded on a stale copy in a consumer repo."
    )


def test_step2_adopts_silently_when_hash_matches_source() -> None:
    """A lock-untracked file whose on-disk content already equals the source is
    adopted into the lock silently — no confirmation needed."""
    text = _text()
    assert re.search(r"adopt.{0,80}silently", text, re.IGNORECASE), (
        "step 2 must adopt a lock-untracked file into the lock silently when its "
        "on-disk hash already matches the source (#173) — it is already correct, "
        "so no confirmation is needed."
    )


def test_step2_conflict_reconciles_when_hash_differs() -> None:
    """A lock-untracked file whose on-disk content differs from the source is
    treated as a CONFLICT-shaped reconcile, not silently overwritten or ignored."""
    text = _text()
    assert re.search(r"CONFLICT-shaped reconcile", text), (
        "step 2 must treat a lock-untracked file that differs from the source as "
        "a CONFLICT-shaped reconcile (show a diff, ask) rather than silently "
        "overwriting or ignoring it (#173)."
    )


def test_step2_states_never_leave_it_unresolved() -> None:
    """The doc states the file must never be left lock-untracked and ignored."""
    text = _text()
    assert re.search(
        r"never leave.{0,60}(lock-untracked|un-?adopted).{0,60}(ignored|unresolved)",
        text,
        re.IGNORECASE,
    ), (
        "step 2 must state a registry-listed/on-disk/lock-untracked file must "
        "never be left un-adopted and unflagged — the gap #173 closes."
    )


def test_step4_lock_rewrite_covers_adopted_files() -> None:
    """Step 4 (rewrite the lock) covers newly-adopted files, not just PULLs."""
    text = _text()
    step4 = text[text.index("### 4."):text.index("### 5.")]
    assert re.search(r"adopt", step4, re.IGNORECASE), (
        "step 4 must state that a newly-adopted lock-untracked file gets a fresh "
        "lock entry, the same as a first-time PULL (#173)."
    )


def test_step6_report_names_adopted_count() -> None:
    """Step 6's reported counts include adopted files, not just pulled/local/conflict."""
    text = _text()
    step6 = text[text.index("### 6."):]
    assert "adopted" in step6, (
        "step 6 must report a count of adopted (previously lock-untracked) files "
        "alongside pulled/local/conflict/current (#173)."
    )
