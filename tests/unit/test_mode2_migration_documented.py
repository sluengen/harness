"""Superseding pre-merge guidance is a re-bootstrap, not an ``/update-guidance``.

*Source:* ``assessments/2026-06-15-system-and-code.md`` SYSTEM-6 (deployment
risk); doc-only half split per the 2026-06-16 decision.

Superseding *pre-merge* guidance — a repo whose installed skills were
renamed/folded by the merge (``scope-discipline`` / ``verification-before-completion``
/ ``code-structure`` → ``code-quality``; the ``spec.md`` template → ``feature.md``)
— must be done by **re-bootstrap** (re-running ``BOOTSTRAP.md``), *not* by
``/update-guidance``. The fold knowledge lives only in ``BOOTSTRAP.md``'s
legacy-artifact handling; ``/update-guidance`` would treat an old skill as a
generic "removed" file and the new one as "added", losing the fold relationship
and any local edits. ``/update-guidance`` applies only to a repo **already on a
harness lock**.

**#435 removed the third doc.** ADR 0015 deletes ``ONBOARDING.md``, which carried
the consolidated migration checklist. The migrator-facing surface is the two
documents below, and the deleted checklist is **not** re-asserted here: a guard
kept pointing at content that no longer exists is the failure mode this module
was written to prevent.

**What this module asserts, after #459.** Under ADR 0016 (*tests own structure
and negative space; the reviewer owns meaning*) five exact-phrase pins across the
two docs collapse to one tripwire per rule-home:

* **``BOOTSTRAP.md`` step 2**, sliced from its own numbered step to the next, so
  the assertion reads the legacy-artifact handling rather than the installer at
  large. Terms: the supersede case, ``re-bootstrap``, and the two-tier deletion
  rule (``in bulk`` for a prior install's own folded files, ``per-file
  confirmation`` for files the repo owns). Polarity yes and anchored — the step
  says the supersede is done by re-running the installer, *not* by
  ``/update-guidance``; without that clause the step names both tools and
  chooses neither.
* **``commands/update-guidance.md``**'s **preamble** — everything above the first
  ``## `` heading — because a wrong-tool guard buried in step 4 is read after the
  command has already run. Terms ``already on a harness lock`` and
  ``re-bootstrap``, with the same anchored refusal. The command has to decline
  the case, not merely mention it.

Occurrence they cite (``code-quality`` Part C, *A new guard cites the occurrence
it prevents*): ``test_both_docs_name_rebootstrap`` asserted the token
``re-bootstrap`` appears in both files — satisfied by either doc *recommending*
``/update-guidance`` for the supersede case and mentioning re-bootstrap in
passing, which is the exact confusion the two docs exist to settle. The
``MERGE_FOLD_TOKENS`` pin went with it: a two-element literal list of skill names
inside the installer's prose is content, not structure.

The docs are worded "pre-merge guidance" rather than "agents-repo" so the live
operational docs respect the one-repo-source invariant enforced by
``test_docs_consistency``; this module's own prose keeps the assessment's framing
for traceability (test files are not scanned by that guard).
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
BOOTSTRAP = REPO_ROOT / "BOOTSTRAP.md"
UPDATE_GUIDANCE = REPO_ROOT / "commands" / "update-guidance.md"

#: The canonical phrase naming the supersede case, so a migrator searching either
#: doc lands on the same answer. Worded "pre-merge guidance" (not "agents-repo")
#: to respect the one-repo-source guard ``test_docs_consistency`` enforces.
SUPERSEDE_PHRASE = "superseding pre-merge guidance"
#: The phrase scoping ``/update-guidance`` to the non-supersede case.
LOCK_PHRASE = "already on a harness lock"

#: The refusal, **anchored to the tool it declines**. A doc carrying a negation
#: somewhere and naming ``/update-guidance`` somewhere states nothing — both docs
#: name the command repeatedly. The claim is that this command is *not* it.
_NOT_UPDATE_GUIDANCE = re.compile(
    r"\b(?:not|never|no)\b(?:\W+\w+){0,2}?\W+/?update-guidance\b", re.IGNORECASE
)


def _bootstrap_step_two() -> str:
    """``BOOTSTRAP.md``'s step 2 — the copy-in step that handles legacy artifacts.

    Sliced between its own numbered step heading and the next one, so a rule
    asserted here is asserted where a migrator would read it, not merely
    somewhere in a hundred-line installer.
    """
    text = BOOTSTRAP.read_text()
    steps = list(re.finditer(r"^> \*\*(\d+)\. ", text, re.MULTILINE))
    assert steps, "BOOTSTRAP.md must carry numbered installer steps"
    starts = {m.group(1): m.start() for m in steps}
    assert "2" in starts, (
        "BOOTSTRAP.md must carry a step 2 — the copy-in step whose legacy-artifact "
        "handling is the only home of the fold knowledge"
    )
    after = [m.start() for m in steps if m.start() > starts["2"]]
    end = min(after) if after else len(text)
    section = text[starts["2"] : end]
    assert section.strip(), "BOOTSTRAP.md's step 2 is empty"
    return section


def test_the_installer_owns_the_supersede_path() -> None:
    """One tripwire for BOOTSTRAP.md: step 2, its terms, and the refusal (#459)."""
    step = _bootstrap_step_two()
    lower = step.lower()

    assert SUPERSEDE_PHRASE in lower, (
        f"BOOTSTRAP.md step 2 must name the supersede case — {SUPERSEDE_PHRASE!r} "
        "— so a migrator searching for it lands in the legacy-artifact handling"
    )
    assert "re-bootstrap" in lower, (
        "BOOTSTRAP.md step 2 must name re-bootstrap (re-running this installer) as "
        "the tool for superseding pre-merge guidance"
    )
    assert "in bulk" in lower and "per-file confirmation" in lower, (
        "BOOTSTRAP.md's no-auto-delete rule must distinguish superseding a prior "
        "install's own renamed/folded files (confirm once, in bulk) from deleting "
        "files the repo itself owns (per-file confirmation) — a faithful "
        "re-bootstrap removes many superseded files at once"
    )
    assert _NOT_UPDATE_GUIDANCE.search(lower), (
        "BOOTSTRAP.md step 2 must state the supersede is *not* an "
        "`/update-guidance`, with the refusal anchored to the command it "
        "declines. A step that names both tools and chooses neither leaves the "
        "migrator with the one that loses the fold relationship"
    )


def _update_guidance_preamble() -> str:
    """Everything in ``commands/update-guidance.md`` above its first ``## `` heading.

    The wrong-tool guard is only a guard where it is read *before* the command
    runs. Sliced to the preamble rather than searched file-wide: the same three
    tokens appear throughout the steps, so a whole-file assertion stays green
    with the scoping clause relocated into the middle of the procedure it is
    supposed to prevent.
    """
    text = UPDATE_GUIDANCE.read_text()
    m = re.search(r"^## ", text, re.MULTILINE)
    assert m, "commands/update-guidance.md must carry a '## ' section heading"
    preamble = text[: m.start()]
    assert preamble.strip(), "commands/update-guidance.md has an empty preamble"
    return preamble


def test_update_guidance_declines_the_supersede_case() -> None:
    """One tripwire for the command: its scope, its pointer, and the refusal (#459)."""
    lower = _update_guidance_preamble().lower()

    assert LOCK_PHRASE in lower, (
        "commands/update-guidance.md's preamble must state it applies to a repo "
        f"{LOCK_PHRASE!r} — the scope that distinguishes it from a re-bootstrap"
    )
    assert "re-bootstrap" in lower, (
        "commands/update-guidance.md's preamble must point a pre-merge supersede "
        "at re-bootstrap (re-running BOOTSTRAP.md) rather than at this command"
    )
    assert _NOT_UPDATE_GUIDANCE.search(lower), (
        "commands/update-guidance.md's preamble must *refuse* the supersede case, "
        "with the refusal anchored to itself. Mentioning re-bootstrap as an "
        "alternative is not the wrong-tool guard: the command has to say this is "
        "not the tool, or a migrator reading it top-to-bottom runs it anyway"
    )
