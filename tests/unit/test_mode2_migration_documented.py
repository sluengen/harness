"""CAL-733 — document the Mode-2 (supersede agents-repo) migration path.

Source: ``assessments/2026-06-15-system-and-code.md`` SYSTEM-6 (Medium,
deployment risk); doc-only half split from **CAL-717** per the decision
(Option 3, 2026-06-16).

Superseding *old agents-repo* guidance — a repo whose installed skills were
renamed/folded by the merge (``scope-discipline`` / ``verification-before-completion``
/ ``code-structure`` -> ``code-quality``; the ``spec.md`` template -> ``feature.md``)
— must be done by **re-bootstrap** (re-running ``BOOTSTRAP.md``), *not* by
``/update-guidance``. The fold knowledge (which old skill folds into which new
file) lives only in ``BOOTSTRAP.md``'s legacy-artifact handling; ``/update-guidance``
would treat an old skill as a generic "removed" file and the new one as "added",
losing the fold relationship and any local edits. ``/update-guidance`` applies
only to a repo **already on a harness lock**.

That distinction was stated nowhere. These guards pin it into the three docs a
migrator would read:

* **AC-1** — ``BOOTSTRAP.md`` states the supersede path explicitly: superseding
  old agents-repo guidance is a re-bootstrap.
* **AC-2** — ``commands/update-guidance.md`` carries the wrong-tool guard: it is
  for a repo already on a harness lock; an agents-repo supersede is a re-bootstrap.

**#435 removed the third doc.** ADR 0015 deletes ``ONBOARDING.md``, which carried
AC-3's consolidated "Migrating off pre-merge guidance" checklist and a second
statement of AC-1. The migrator-facing surface is now the two documents below,
both of which ADR 0015 keeps — the copy-in installer and its update command are
the delivery mechanism the decision explicitly retains. AC-3's checklist has no
surviving home and is **not** re-asserted here: a guard kept pointing at content
that no longer exists is the failure mode this module was written to prevent.

The docs are worded "pre-merge guidance" rather than "agents-repo" so the live
operational docs respect the one-repo-source invariant enforced by the CAL-651
``test_docs_consistency`` guard; this module's own prose keeps the assessment's
"agents-repo" framing for traceability (test files are not scanned by that guard).
"""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
BOOTSTRAP = REPO_ROOT / "BOOTSTRAP.md"
UPDATE_GUIDANCE = REPO_ROOT / "commands" / "update-guidance.md"

#: The canonical phrase naming the supersede case, used so a migrator searching
#: any of the three docs lands on the same answer. Worded "pre-merge guidance"
#: (not "agents-repo") to respect the one-repo-source guard the CAL-651 docs-
#: consistency test enforces on the live operational docs (``test_docs_consistency``).
SUPERSEDE_PHRASE = "superseding pre-merge guidance"
#: The phrase scoping ``/update-guidance`` to the non-supersede case.
LOCK_PHRASE = "already on a harness lock"

#: Folds the *merge into the harness* performs, beyond the pre-merge-era set
#: (``scope-discipline``/… -> ``code-quality``, ``spec.md`` -> ``feature.md``).
#: CAL-750: the brewspec dry-run found BOOTSTRAP.md named only the pre-merge folds,
#: so a literal reading would leave ~18 orphans (it migrated by agent judgment).
#: ``linear-sync`` and ``harness-steward`` are absent from BOOTSTRAP.md until the
#: merge fold-set is named, so they discriminate the fix from the old text.
MERGE_FOLD_TOKENS = ("linear-sync", "harness-steward")


# --- AC-1: BOOTSTRAP.md + ONBOARDING.md state the supersede path ----------------


def test_installer_states_supersede_is_rebootstrap() -> None:
    """``BOOTSTRAP.md`` names re-bootstrap as the supersede-agents-repo tool (AC-1)."""
    text = BOOTSTRAP.read_text()
    assert SUPERSEDE_PHRASE in text, (
        "BOOTSTRAP.md must state the supersede path explicitly — the phrase "
        f"{SUPERSEDE_PHRASE!r} — so the legacy-artifact section names the case "
        "(CAL-733 AC-1)."
    )
    assert "re-bootstrap" in text, (
        "BOOTSTRAP.md must name re-bootstrap (re-running this installer) as the "
        "tool for superseding old agents-repo guidance (CAL-733 AC-1)."
    )


# --- AC-2: /update-guidance carries the wrong-tool guard -----------------------


def test_update_guidance_carries_wrong_tool_guard() -> None:
    """``/update-guidance`` scopes itself to a locked repo, points elsewhere (AC-2)."""
    text = UPDATE_GUIDANCE.read_text()
    assert LOCK_PHRASE in text, (
        "commands/update-guidance.md must state it applies to a repo "
        f"{LOCK_PHRASE!r} — distinguishing it from a re-bootstrap (CAL-733 AC-2)."
    )
    assert "re-bootstrap" in text, (
        "commands/update-guidance.md must point an agents-repo supersede at "
        "re-bootstrap (re-running BOOTSTRAP.md) rather than this command "
        "(CAL-733 AC-2)."
    )


# --- CAL-750: BOOTSTRAP.md's legacy handling is complete for the merge ------------


def test_installer_names_the_merge_fold_set() -> None:
    """BOOTSTRAP.md step 2 names the folds the merge performs, not just pre-merge ones."""
    text = BOOTSTRAP.read_text()
    missing = [tok for tok in MERGE_FOLD_TOKENS if tok not in text]
    assert not missing, (
        f"BOOTSTRAP.md does not name these merge folds: {missing}. Step 2 lists "
        "only the pre-merge folds (scope-discipline/... -> code-quality, "
        "spec.md -> feature.md); a Mode-2 re-bootstrap also folds linear-sync -> "
        "linear, code-steward + harness-steward -> steward, etc. Naming them stops "
        "an agent following the doc literally from leaving orphans (CAL-750)."
    )


def test_installer_distinguishes_bulk_supersede_from_foreign_deletion() -> None:
    """BOOTSTRAP.md separates bulk supersede-cleanup from per-file foreign deletion."""
    text = BOOTSTRAP.read_text()
    assert "in bulk" in text and "per-file confirmation" in text, (
        "BOOTSTRAP.md's no-auto-delete rule must distinguish superseding a prior "
        "install's own renamed/folded files (confirm once, in bulk) from deleting "
        "files the repo itself owns (per-file confirmation) — a faithful Mode-2 "
        "re-bootstrap removes ~18 superseded files (CAL-750)."
    )


# --- cross-file: both name re-bootstrap as the supersede tool -----------------


def test_both_docs_name_rebootstrap() -> None:
    """The supersede answer is consistent across both surviving migrator docs."""
    missing = [
        p.name
        for p in (BOOTSTRAP, UPDATE_GUIDANCE)
        if "re-bootstrap" not in p.read_text()
    ]
    assert not missing, (
        f"these docs do not name re-bootstrap: {missing} — a migrator reading "
        "either must learn that an agents-repo supersede is a re-bootstrap (CAL-733)."
    )
