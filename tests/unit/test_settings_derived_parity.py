"""The distributable settings file and the repo's derived copy must not diverge.

``.claude/settings.json`` is a *derived copy* of ``settings/harness.json``
(``BOOTSTRAP.md`` step 3; ``commands/update-guidance.md`` step 3) — the same
relationship ``AGENTS.md`` / ``CLAUDE.md`` / ``GEMINI.md`` have with the process
doc, which step 3 already guards with a byte-identical check.

Nothing mechanical enforced the settings half, so it drifted: harness ran an
``autoMode`` block, six extra force-push denies, dev-push allows, and
``WebFetch`` allows that ``settings/harness.json`` never shipped. Consumers
could not obtain that posture through any sanctioned route (CAL-1081, reported
from a nano-erp session 2026-07-15).

Two guards, because they fail for different reasons:

* **AC-1/AC-3 — the derivation holds.** The two files are byte-identical, so a
  posture added to one is added to both. :func:`test_derived_copy_is_byte_identical`.
  This is what makes the ``/update-guidance`` step-3 clobber trap harmless here:
  a clean derivation has no local content to lose. Repo-local permissions belong
  in the gitignored ``.claude/settings.local.json``, which is never derived.
* **AC-1/AC-2/AC-4 — the posture is actually present.** Byte-identity alone would
  survive deleting the posture from *both* files, so the promoted content is
  pinned directly against the distributable.

CAL-1087 extends the ``autoMode`` half. The routine's versioned guidance
instructs three tracker writes — a deferral comment plus the ``decision`` label
(``work-discovery``, ``/harness routine build`` step 2) and a Linear issue per
finding (``/assess`` step 2) — and the loop's own ``harness close`` transitions
the ticket it built. None was sanctioned, so an unattended run had them refused
with *"the scheduled task explicitly limits write actions to those the task file
requests"*. That is a **configuration** gap, not a property of unattended runs:
the same guidance writes to Linear fine wherever the posture names the action.
The fix belongs here, where the posture is versioned and distributed, rather
than in guidance degraded to match one under-configured trigger.

Each clause must carry the **bound** that makes it safe, because the clause text
is what the classifier reads. These tests pin the bound, not merely the
permission — an allowance that lost its rationale would be a wider grant wearing
the same name.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DISTRIBUTABLE = _REPO_ROOT / "settings" / "harness.json"
_DERIVED = _REPO_ROOT / ".claude" / "settings.json"

#: Force-push spellings the base globs miss — the `+refspec` bypass and the
#: `-C` reordering — plus the `main`-merge denies. Promoted from the repo's own
#: config, where they were live but unshipped.
_PROMOTED_DENIES = [
    "Bash(git -C * push * --force *)",
    "Bash(git push * +*)",
    "Bash(git push origin +*)",
    "Bash(git -C * push * +*)",
    "Bash(git merge * main)",
    "Bash(git merge * main *)",
]

#: Pushing an already-reviewed commit to the `dev` integration branch. Profile-general:
#: every repo on this profile integrates on `dev` with the agent-led review as the
#: merge gate, so a direct push of reviewed work does not bypass review.
_PROMOTED_DEV_PUSH_ALLOWS = [
    "Bash(git push origin dev)",
    "Bash(git push origin HEAD:dev)",
    "Bash(git push origin *:dev)",
]

#: Generic enough for any repo on this profile.
_PROMOTED_WEBFETCH_ALLOWS = [
    "WebFetch(domain:github.com)",
    "WebFetch(domain:docs.anthropic.com)",
]

#: Harness's own Python-stack docs. These must stay out of a universal profile —
#: they belong in the consuming repo's gitignored settings.local.json.
_STACK_SPECIFIC_WEBFETCH = [
    "WebFetch(domain:docs.pydantic.dev)",
    "WebFetch(domain:typer.tiangolo.com)",
    "WebFetch(domain:docs.astral.sh)",
]


def _distributable() -> dict[str, Any]:
    return json.loads(_DISTRIBUTABLE.read_text())


def test_derived_copy_is_byte_identical() -> None:
    """AC-1/AC-3: `.claude/settings.json` is a pure derivation of the distributable.

    Anything harness needs but does not ship belongs in `.claude/settings.local.json`
    (gitignored, never derived), not merged into the derived copy.
    """
    distributable = _DISTRIBUTABLE.read_text()
    derived = _DERIVED.read_text()
    if distributable != derived:
        raise AssertionError(
            f"{_DERIVED.relative_to(_REPO_ROOT)} has drifted from its source "
            f"{_DISTRIBUTABLE.relative_to(_REPO_ROOT)}. It is a derived copy: promote "
            f"the difference into the source, or move repo-local content to "
            f".claude/settings.local.json."
        )


def test_distributable_carries_the_automode_dev_push_clause() -> None:
    """AC-1: the unattended-run posture ships, rather than living only here."""
    auto_mode = _distributable().get("autoMode", {})
    allow = auto_mode.get("allow", [])
    assert "$defaults" in allow, "autoMode.allow must extend the defaults"
    assert any("dev" in clause for clause in allow if clause != "$defaults"), (
        "autoMode.allow must carry the dev-push policy statement"
    )


@pytest.mark.parametrize("rule", _PROMOTED_DENIES)
def test_distributable_denies_the_force_push_forms_the_base_globs_miss(rule: str) -> None:
    """AC-1: the `+refspec` / `-C`-reordered bypasses are denied for consumers too."""
    assert rule in _distributable()["permissions"]["deny"], (
        f"{rule} is missing from the distributable's deny list"
    )


@pytest.mark.parametrize("rule", _PROMOTED_DEV_PUSH_ALLOWS + _PROMOTED_WEBFETCH_ALLOWS)
def test_distributable_carries_the_promoted_allows(rule: str) -> None:
    """AC-1: dev-push and generic WebFetch allows ship."""
    assert rule in _distributable()["permissions"]["allow"], (
        f"{rule} is missing from the distributable's allow list"
    )


@pytest.mark.parametrize("rule", _STACK_SPECIFIC_WEBFETCH)
def test_distributable_omits_stack_specific_webfetch_domains(rule: str) -> None:
    """AC-4: a universal profile must not ship one repo's stack docs."""
    assert rule not in _distributable()["permissions"]["allow"], (
        f"{rule} is Python-stack-specific and must not ship to every repo; "
        f"it belongs in .claude/settings.local.json"
    )


# --- CAL-1087: the writes the routine's own guidance instructs are sanctioned --


def _automode_allow() -> list[str]:
    return [c for c in _distributable()["autoMode"]["allow"] if c != "$defaults"]


def _clause_containing(*terms: str) -> str | None:
    """The single autoMode clause mentioning every one of *terms*, if any."""
    for clause in _automode_allow():
        if all(term in clause for term in terms):
            return clause
    return None


def test_automode_sanctions_the_routine_deferral_write() -> None:
    """CAL-1087: `work-discovery` tells the routine to comment on a ticket it
    judged not-yet-actionable and label it `decision`. The posture must permit
    the write the guidance instructs, bounded to the queue the routine pulls
    from — otherwise the deferral is refused and the ticket wedges the queue with
    the reason recorded nowhere a human looks."""
    clause = _clause_containing("`decision`")
    assert clause, (
        "autoMode.allow must sanction the deferral write `work-discovery` "
        "instructs — a comment plus the `decision` label (CAL-1087)."
    )
    assert "comment" in clause.lower(), (
        "the deferral clause must name the comment, not only the label — the "
        "comment is what tells the human why the ticket was deferred."
    )
    assert "queue" in clause.lower(), (
        "the deferral clause must state its bound: the queue the routine pulls "
        "from. An unbounded 'may write to Linear' is a wider grant (CAL-1087)."
    )


def test_automode_sanctions_assess_finding_filing() -> None:
    """CAL-1087: `/assess` step 2 files every finding and insight as an issue —
    the assessment's entire output. A finding it cannot file is lost."""
    clause = _clause_containing("/assess")
    assert clause, (
        "autoMode.allow must sanction filing an `/assess` pass's findings as "
        "issues — the step its own guidance instructs (CAL-1087)."
    )
    assert "queue" in clause.lower(), (
        "the filing clause must state its bound: findings land on the repo's "
        "Build queue for triage (CAL-1087)."
    )


def test_automode_sanctions_the_gated_close_verb() -> None:
    """CAL-1087: `harness close` is what lands a finished run — the Linear
    transition plus the merge. Unsanctioned, the loop can build and review its
    own work but never ship it.

    The clause must carry the bound that makes it safe: the verb refuses unless
    a passing review is bound to the current HEAD, so it cannot land unreviewed
    work. That is the same reviewed-work-only condition the dev-push clause
    rests on — the permission rides on the gate, not on trust."""
    clause = _clause_containing("harness close")
    assert clause, (
        "autoMode.allow must sanction `harness close` — without it the loop "
        "cannot land the work it built and reviewed (CAL-1087)."
    )
    for term in ("reviewed SHA", "HEAD"):
        assert term in clause, (
            f"the close clause must name its gate ({term!r}): the permission is "
            "safe only because the verb refuses a review that does not cover "
            "what would merge (CAL-1087)."
        )
    assert "stale_review" in clause, (
        "the close clause must name the refusal reasons that enforce the gate, "
        "so the bound is auditable rather than asserted (CAL-1087)."
    )
