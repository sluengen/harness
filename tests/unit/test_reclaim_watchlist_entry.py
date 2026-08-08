"""#281 — ``harness/cli/reclaim.py`` is on the repo's architecture watchlist.

Surfaced by the ``/assess code`` pass of 2026-08-01 (CODE-3). #276 added to
``review-discipline`` the obligation that a seam extraction confirm where the
extracted module's tests went — but every obligation in that bullet is gated on the
diff touching a file named in ``CONTEXT.md``'s ``architecture_watchlist.files``, and
that list held exactly two entries (``review.py``, ``close.py``). The reclaim family
is the evidence #276's own guard docstring cites, and it was not on the list: **the
clause written to prevent that recurrence could not fire on the module it was
written about.**

``reclaim.py`` is a gravity well by the same criteria that armed the other two:

* **Growth despite relief** — 291 → 685 lines between 2026-06-16 and 2026-07-31
  *despite* three seam extractions in that window pulling 711 lines into siblings.
* **Churn** — the 3rd-most-churned Python file in the repo since 2026-07-01 (14
  commits, against ``review.py`` 21 and ``close.py`` 20 — the two that *are*
  watchlisted).
* **Size** — larger than watchlisted ``close.py`` (531), and it carries an honest
  ``# size:`` justification at ``harness/cli/reclaim.py:117``.

#281 takes the same *minimal arm* CAL-1014 (``review.py``) and CAL-1139
(``close.py``) took: name the gravity well in ``CONTEXT.md`` so the shipped
mechanism fires on the next change touching it. Extracting further from
``reclaim.py`` is explicitly out of scope — this ticket makes the module *visible*
to the watchlist obligations; whether it needs another seam is a decision the next
change touching it will carry.

**What this module measures, and what it deliberately does not.** #272's
``test_watchlist_entry_currency.py`` already reads every watchlist note against the
tree — it derives the sibling set from the ``<stem>_*.py`` filename convention and
fails when a note *omits* one. That guard covers reclaim by construction the moment
the entry lands, and more strictly than a hand-written triple would, so re-asserting
the carved-out module names as literals here would be exactly the per-extraction
churn #272 removed. The two note guards below are the halves it does **not** cover:
the reverse direction (a name in the note that resolves to nothing) and #273's
entry-currency rule (state, not a line count).

**The derived sibling set is wider than the ticket assumed, and that is correct.**
``_sibling_modules`` matches tracked ``harness/**/reclaim_*.py`` package-wide, which
is **four** modules, not three: ``harness/reclaim_marker.py`` is the shared
reclaim/handoff comment contract (CAL-739, ``6cf1e1e``) that ``harness/linear.py``
reads too — deliberately at the package root to avoid an import cycle, and a sibling
by *filename convention* only, never carved out of the verb. #272 anticipated this
exact case and recorded it as an accepted cost with the remedy *"name it in the
note, one clause"*, which is what the entry does. Excluding it from the derived set
instead would edit a guard this ticket does not own to work around a false positive
its author already priced in.

The entry parser is **imported** from the guard that owns it rather than recopied:
#272 recorded that a fourth private copy could drift and produce a confident false
green, and the repo sanctions cross-module test imports for exactly this.
"""

from __future__ import annotations

import fnmatch
import re
from pathlib import Path

import pytest

from tests._gitutil import tracked_files_under
from tests.unit.test_close_watchlist_entry import _watchlist_entries

REPO_ROOT = Path(__file__).resolve().parents[2]
CONTEXT = REPO_ROOT / "CONTEXT.md"

#: The gravity well this ticket puts under the watchlist.
WATCHLISTED_FILE = "harness/cli/reclaim.py"

#: Module filenames named in a note, e.g. ``reclaim_undo.py``. Deliberately keyed on
#: the ``.py`` suffix: bare ``#254``-style ticket refs and prose words are not module
#: claims, and only a claim that a *file* exists is checkable against the tree.
_MODULE_REF = re.compile(r"\b([a-z_][a-z0-9_]*\.py)\b")

#: A line count quoted in prose — the thing #273's entry-currency rule forbids,
#: because a number dates the moment the next change lands while a description of
#: the decomposition stays true. ``~450``/``531``/``2,774`` forms all count; a bare
#: ticket ref (``#254``) or a module name carries digits without claiming a size.
_LINE_COUNT = re.compile(r"~?\d[\d,]*\s*lines?\b", re.IGNORECASE)

#: Phrasings that must arm the line-count check. The first two are the exact strings
#: that rotted in the ``close.py`` note and produced #272.
_COUNT_MATCH = [
    "All three retired the justification (now ~450 lines)",
    "588 lines, over the 500 hard limit",
    "grown from 520 lines",
    "their tests landed back in one 2,774 line module",
    "it is 685 Lines today",
]

#: Phrasings that must not arm it. Every one of these appears in, or is the shape of,
#: the entry this ticket writes — ticket refs and module names carry digits, and
#: describing the decomposition is what the note is *for*.
_COUNT_NO_MATCH = [
    "#254 split the three-clock liveness rule out to reclaim_liveness.py",
    "#255 the sweep's closable predicate to reclaim_closable.py",
    "it carries a `# size:` marker; read that marker for the current decomposition",
    "reclaim_marker.py at the package root is the shared comment contract",
    "test structure followed the seams in #274",
]


def _reclaim_notes() -> list[str]:
    """The note(s) on every watchlist entry whose glob covers ``reclaim.py``."""
    return [
        note
        for glob, note in _watchlist_entries(CONTEXT.read_text(encoding="utf-8"))
        if fnmatch.fnmatch(WATCHLISTED_FILE, glob)
    ]


def _tracked_module_names() -> set[str]:
    """Every tracked ``*.py`` filename in the repo, basename only.

    Derived from the tracked tree so a note naming a module deleted by a later merge
    goes red without this guard needing an edit. Basename rather than path because
    the notes name modules the way the repo's prose does — ``reclaim_undo.py``, not
    ``harness/cli/reclaim_undo.py``.

    Repo-wide rather than ``harness/``-only on purpose: #276's clause is about where
    an extraction's *tests* went, so a note recording that seam names test modules
    too, and a typo there is exactly as misleading as one in a source module name.
    """
    return {path.name for path in tracked_files_under(".") if path.suffix == ".py"}


def test_reclaim_py_is_on_the_architecture_watchlist() -> None:
    """``CONTEXT.md`` opts ``reclaim.py`` into the watchlist, and the mechanism's
    trigger rule fires on it (#281 AC-1, minimal arm).

    This is the whole point of the ticket: until the glob is there, #276's tests
    clause and #273's entry-currency clause cannot reach the reclaim family at all.
    """
    globs = [glob for glob, _ in _watchlist_entries(CONTEXT.read_text(encoding="utf-8"))]
    assert globs, (
        "CONTEXT.md must define a non-empty `architecture_watchlist.files` so the "
        "gravity-well tripwire is armed (#281)."
    )
    assert any(fnmatch.fnmatch(WATCHLISTED_FILE, pat) for pat in globs), (
        f"`{WATCHLISTED_FILE}` must be covered by a glob in "
        f"`architecture_watchlist.files` so the watchlist mechanism — and with it "
        f"#276's extracted-tests clause — fires on the next change that touches the "
        f"reclaim family; current globs: {globs} (#281 AC-1)."
    )


def test_reclaim_entry_names_modules_that_all_exist() -> None:
    """AC-3 — every module the note names resolves to a tracked file.

    The reverse direction from #272's sibling guard, which fails when a note *omits*
    a module that exists. This one fails when a note *names* one that does not — a
    typo, or a module a later merge deleted. Together they pin the note to the tree
    in both directions; neither alone does.
    """
    notes = _reclaim_notes()
    assert notes and notes[0], (
        f"the `{WATCHLISTED_FILE}` watchlist entry must carry a `#` note saying why "
        f"it is a gravity well and what has been carved out of it, as the "
        f"`review.py` and `close.py` entries do. An entry reflowed onto two lines "
        f"parses as an empty note — keep it on one physical line (#281 AC-1)."
    )
    named = sorted({m for note in notes for m in _MODULE_REF.findall(note)})
    assert named, (
        f"the `{WATCHLISTED_FILE}` note names no module at all — it must record the "
        f"decomposition sitting beside the gravity well, or this guard passes by "
        f"measuring nothing (#281 AC-3)."
    )
    tracked = _tracked_module_names()
    missing = [name for name in named if name not in tracked]
    assert not missing, (
        f"the `{WATCHLISTED_FILE}` watchlist note names {missing}, which no tracked "
        f"module under `harness/` provides. The note is the record read at the *next* "
        f"touch, so a name that resolves to nothing mis-primes every later session. "
        f"Fix the note, not the tree (#281 AC-3)."
    )


def test_reclaim_entry_describes_state_not_a_line_count() -> None:
    """AC-2 — the note describes the decomposition *state* and quotes no line count.

    #273's entry-currency rule, and the concrete lesson of #272: the ``close.py``
    note's ``(now ~450 lines)`` was false within one ticket, while a description of
    which concerns were split out where stays true until the next split — at which
    point #272's derived guard fails and forces the refresh. A number dates; a
    description does not.

    Scoped to the reclaim entry rather than all three: widening it passes today and
    is a one-line change later, but binding this ticket's failure surface to this
    ticket's prose is the smaller step.
    """
    notes = _reclaim_notes()
    assert notes and notes[0], (
        f"the `{WATCHLISTED_FILE}` entry must carry a note for this guard to measure "
        f"(#281 AC-2)."
    )
    for note in notes:
        count = _LINE_COUNT.search(note)
        assert count is None, (
            f"the `{WATCHLISTED_FILE}` watchlist note quotes a line count "
            f"({count.group(0)!r}), which #273's entry-currency rule "
            f"forbids: the number is stale the next time the file changes, and #272 "
            f"shipped because exactly such a number went stale. Describe the "
            f"decomposition state instead, and point at the `# size:` marker for the "
            f"current one (#281 AC-2)."
        )
        assert "size:" in note, (
            f"the `{WATCHLISTED_FILE}` note must point at the file's `# size:` marker "
            f"as the live record of its decomposition — that pointer is what replaces "
            f"the line count this guard forbids, mirroring the `review.py` and "
            f"`close.py` entries (#281 AC-2)."
        )


@pytest.mark.parametrize("sample", _COUNT_MATCH)
def test_line_count_regex_accepts_real_counts(sample: str) -> None:
    """The pinned examples are the readable specification of the heuristic — without
    them the next editor cannot tell which phrasings are caught."""
    assert _LINE_COUNT.search(sample), (
        f"{sample!r} quotes a line count and must arm the check (#281 AC-2)."
    )


@pytest.mark.parametrize("sample", _COUNT_NO_MATCH)
def test_line_count_regex_rejects_ticket_refs_and_module_names(sample: str) -> None:
    """Ticket refs and module names carry digits without claiming a size; arming on
    those would make the entry unwritable."""
    assert not _LINE_COUNT.search(sample), (
        f"{sample!r} quotes no line count and must not arm the check (#281 AC-2)."
    )
