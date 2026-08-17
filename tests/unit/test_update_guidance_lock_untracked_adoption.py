"""#173 — ``/update-guidance`` adopts a registry-listed, on-disk, lock-untracked file.

A file that graduates from repo-owned/hand-copied to a registry-tracked
distributable (the exact transition ``commands/harness.md`` made in CAL-764)
falls through step 2's classification table: it isn't "new" (source-added,
absent on disk — it IS on disk) and it isn't any lock-keyed state (it isn't in
the lock at all). A consumer installed before the graduation stays silently
stranded on a stale copy of a file the registry now owns, as happened to the
``form`` repo (issue #173).

**What this module asserts, after #459.** One tripwire over one rule-home: the
run of step-2 blocks that classify a **registry-listed / on-disk / lock-untracked**
file. It reads that window for the case's three-part name, its two outcomes
(adopt, or a CONFLICT-shaped reconcile), the negation that forbids a third, and
the two downstream steps the outcome has to reach.

Six prose pins collapsed into it, four of them exact-phrase regexes
(``"CONFLICT-shaped reconcile"``, ``adopt.{0,80}silently``, the
``registry-listed.{0,40}on-disk.{0,40}lock-untracked`` gap pattern, and the
``never leave`` sentence template). Each read the **whole file**, so nothing tied
the case's name to its outcomes; and each broke on a benign rewording of prose
that a migrator doc has every reason to keep editing.

Occurrence the tripwire's polarity cites (``code-quality`` Part C): the pre-#459
form pinned ``never leave … un-adopted … ignored`` as a sentence template, which
means the negation was verified as *bytes* rather than as a negation attached to
the case. Anchoring it to ``lock-untracked`` inside the window is what makes the
inversion — a step that names the case, describes adoption, and then permits
leaving the file alone — go red. The ``craft.md`` class is *A guard over prose
owns structure and negative space, never meaning*.

**Coordinated with ``test_update_guidance_same_version_drift``**, which owns the
SOURCE DRIFT rule in the same step. Two tripwires, two rule-homes, one file; the
section slicer both read, :func:`tests.unit._prose.update_guidance_between`,
lives in the neutral home since #467 rather than in either guard, so the two
cannot disagree about where a step begins.
"""

from __future__ import annotations

import re

from tests.unit._prose import update_guidance_between

#: The three-part name the case is classified under. All three are conjuncts:
#: dropping any one turns the rule into a claim about a different, already-handled
#: state (a lock-tracked file, an absent file, or a file the registry does not own).
_CASE_TERMS = ("registry-listed", "on-disk", "lock-untracked")

#: The two sanctioned outcomes. ``adopt`` is the silent path when the on-disk copy
#: is already correct; ``CONFLICT`` is the reconcile when it is not.
_OUTCOME_TERMS = ("adopt", "CONFLICT")

#: The negation **anchored to the outcome it forbids**. The claim is that a file
#: in this shape is never left *ignored* — that third outcome is the #173 defect.
#:
#: Anchored to ``ignored`` rather than to ``lock-untracked``, and the difference
#: was measured. The case's own definition opens *"exists on disk but is **not**
#: in the lock at all — a **registry-listed / on-disk / lock-untracked** file"*:
#: a negation ten words ahead of ``lock-untracked``, in a sentence that only
#: *names* the case. Anchored there, the predicate matched the definition, and an
#: inverted refusal — "a file may be left lock-untracked and ignored" — stayed
#: green. ``ignored`` appears once in the window, in the refusal itself, so it is
#: the token that cannot be borrowed from a neighbour. Found while authoring this
#: conversion's mutation table (#459), before the table was run.
_NEVER_LEFT_UNRESOLVED = re.compile(
    r"\b(?:never|not|no)\b(?:\W+\w+){0,12}?\W+ignored?\b", re.IGNORECASE
)


def _adoption_window() -> str:
    """Step 2's run of blocks classifying a lock-untracked file.

    From the first block naming ``lock-untracked`` to the last, inclusive — so
    the two outcome bullets update_guidance_between them are in scope even though neither repeats
    the case's name. Derived from the term the rule is *about* rather than from a
    heading or an ordinal, because the case is one classification among several
    inside one step and an ordinal into that step is invalidated by a correct
    insertion.
    """
    blocks = update_guidance_between("### 2.", "### 3.").split("\n\n")
    hits = [i for i, block in enumerate(blocks) if "lock-untracked" in block]
    if not hits:
        return ""
    return "\n\n".join(blocks[hits[0] : hits[-1] + 1])


def test_a_lock_untracked_file_is_adopted_or_reconciled() -> None:
    """The one tripwire: the case is named, resolved two ways, and never ignored.

    Four parts:

    * **anchor** — step 2 carries a run of blocks naming ``lock-untracked``. An
      empty window fails here rather than leaving containment checks scanning
      ``""``, which is what a whole-file search degrades into once the case is
      renamed.
    * **terms** — the case's three-part name and its two outcomes, read from the
      same window. Before #459 the name and the outcomes were pinned by separate
      whole-file regexes, so an ``adopt`` sentence about an unrelated state
      satisfied the outcome half.
    * **polarity** — the negation anchored to ``lock-untracked``: a file in this
      shape is never left un-adopted and ignored. That third outcome *is* #173.
    * **downstream** — the outcome has to reach the lock rewrite (step 4) and the
      report (step 6). An adoption the lock never records is a file re-adopted on
      every run; one the report never counts is invisible to the operator.
    """
    window = _adoption_window()
    assert window, (
        "commands/update-guidance.md step 2 no longer classifies a "
        "registry-listed / on-disk / lock-untracked file. That is the gap #173 "
        "closes: a file that graduated to a registry-tracked distributable after "
        "install matches no lock-keyed state and is silently skipped, stranding "
        "the consumer on a stale copy."
    )

    missing = [term for term in _CASE_TERMS if term not in window]
    assert not missing, (
        f"step 2's lock-untracked case no longer names {missing}. All three parts "
        "are what distinguish it from the states the table already handles."
    )

    missing_outcomes = [term for term in _OUTCOME_TERMS if term.lower() not in window.lower()]
    assert not missing_outcomes, (
        f"step 2's lock-untracked case no longer offers {missing_outcomes}. A "
        "matching hash is adopted into the lock silently; a differing one is a "
        "CONFLICT-shaped reconcile — 2-way, since there is no locked version to "
        "serve as a 3-way base."
    )

    assert _NEVER_LEFT_UNRESOLVED.search(window), (
        "step 2 describes the two outcomes but never forbids the third. Without "
        "the refusal anchored to the case, prose that names it, explains adoption, "
        "and then leaves the file alone satisfies every term above — which is the "
        "silent skip #173 is about."
    )

    assert re.search(r"adopt", update_guidance_between("### 4.", "### 5."), re.IGNORECASE), (
        "step 4 does not state that a newly-adopted lock-untracked file gets a "
        "fresh lock entry, the same as a first-time PULL. An adoption the lock "
        "never records is re-adopted on every subsequent run (#173)."
    )
    assert "adopted" in update_guidance_between("### 6.", "## Note"), (
        "step 6 does not report a count of adopted (previously lock-untracked) "
        "files alongside pulled/local/conflict/current. A resolution the operator "
        "never sees is indistinguishable from the skip it replaced (#173)."
    )


def test_the_adoption_window_is_narrower_than_the_step() -> None:
    """Control: the window is a slice of step 2, not the whole of it.

    The text unit is part of the predicate. If the block scan degraded into
    returning the entire step — or the entire file — every containment check
    above would silently widen to prose written for the classification table, the
    LOCAL-edit aside, and the new/removed-file paragraph, none of which this rule
    governs. Asserted as strict shortness against the step it is cut from, which
    is the one comparison a widened slicer cannot satisfy.
    """
    window = _adoption_window()
    step = update_guidance_between("### 2.", "### 3.")
    assert window, "no adoption window derived — see the tripwire above"
    assert len(window) < len(step), (
        "the adoption window is the whole of step 2, so the assertions above are "
        "reading the classification table and the new/removed-file paragraph as if "
        "they were the lock-untracked rule"
    )
