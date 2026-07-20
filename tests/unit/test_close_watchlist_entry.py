"""CAL-1139 — ``harness/cli/close.py`` is on the repo's architecture watchlist.

Surfaced by the read-only ``/assess code`` idle-arm pass (2026-07-17). The
watchlist armed exactly one file — ``review.py`` (CAL-1014) — while ``close.py``
had grown into a gravity well by the same criteria and was not armed, so the next
change there did not trip the ``Watchlist trigger``:

* **Churn** — 19 commits, tied with ``review.py`` for the most in the package.
* **Size** — 588 lines, over the 500 hard limit, grown from 520 (it carried an
  honest ``# size:`` justification).
* **Concern mix** — the close *gate* (``_evaluate_gate``, ``_has_gate_evidence``),
  *ledger* finalization (``_mark_run_closed``), and *git* integrate/merge/push
  all accreted in one module.

CAL-1139 took the same *minimal arm* CAL-1014 took: name the gravity well in
``CONTEXT.md`` so the shipped mechanism fires on the next change touching it. That
change was **CAL-1154**, which tripped the trigger and cut the seam — the git
integrate/merge/push concern moved to :mod:`harness.close_merge` (the
throwaway-worktree merge), dropping ``close.py`` back under the 500-line limit and
retiring its ``# size:`` justification. ``close.py`` stays on the watchlist (its
churn and the remaining gate/ledger cohabitation keep it a gravity well), and its
entry note now records the split — mirroring how ``review.py``'s entry records the
``review_protocol.py`` extraction (CAL-1107).

This guard pins the entry so the tripwire cannot be silently dropped, and pins the
deliberate ``linear.py`` *exclusion* so a later well-meaning pass does not arm a
file whose size is guard-mandated cohesion. It mirrors the CAL-1014 guard's
text-parse approach (``test_review_watchlist_entry.py``); each watchlist entry
keeps its own guard documenting why that file is a gravity well.
"""

from __future__ import annotations

import fnmatch
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
CONTEXT = REPO_ROOT / "CONTEXT.md"

#: The gravity well this ticket puts under the watchlist.
WATCHLISTED_FILE = "harness/cli/close.py"

#: Deliberately NOT armed: ``linear.py``'s size is guard-mandated cohesion — the
#: CAL-731 embed guard forces every Linear GraphQL call into the one client (its
#: ``# size:`` justification), so the surface grows one query-method at a time and
#: a trigger there would fire on changes with no decision to make. No line count is
#: quoted here on purpose: the file grows by design, so a number would date.
EXCLUDED_FILE = "harness/linear.py"


def _watchlist_entries(context_text: str) -> list[tuple[str, str]]:
    """The ``(glob, note)`` pairs under ``architecture_watchlist.files``.

    Text-parsed, not YAML-loaded, to match the repo's no-YAML-dependency
    convention for reading ``CONTEXT.md`` (see ``harness/loop_budget.py``). The
    ``architecture_watchlist:`` key sits at column 0 of the ``CONTEXT.md`` YAML
    block; the section runs to the next column-0 key, and every ``- <path>`` list
    item within it is a watchlist glob whose trailing ``#`` comment is its note.
    An absent block yields an empty list.
    """
    start = re.search(r"^architecture_watchlist:.*$", context_text, re.MULTILINE)
    if start is None:
        return []
    rest = context_text[start.end() :]
    nxt = re.search(r"^\w[\w-]*:", rest, re.MULTILINE)
    section = rest[: nxt.start()] if nxt else rest
    return [
        (m.group(1), (m.group(2) or "").strip())
        for m in re.finditer(r"^\s*-\s*(\S+)[ \t]*(?:#(.*))?$", section, re.MULTILINE)
    ]


def test_close_py_is_on_the_architecture_watchlist() -> None:
    """``CONTEXT.md`` opts ``close.py`` into the watchlist, and the mechanism's
    trigger rule fires on it (CAL-1139 AC-1, minimal arm)."""
    globs = [glob for glob, _ in _watchlist_entries(CONTEXT.read_text())]
    assert globs, (
        "CONTEXT.md must define a non-empty `architecture_watchlist.files` so the "
        "gravity-well tripwire is armed (CAL-1139)."
    )
    assert any(fnmatch.fnmatch(WATCHLISTED_FILE, pat) for pat in globs), (
        f"`{WATCHLISTED_FILE}` must be covered by a glob in "
        f"`architecture_watchlist.files` so the watchlist mechanism fires on the "
        f"next change that touches it; current globs: {globs} (CAL-1139)."
    )


def test_close_entry_names_its_concern_mix() -> None:
    """The entry carries a note naming the gate/ledger/git mix that makes it a
    gravity well, mirroring the ``review.py`` entry (CAL-1139 AC-1)."""
    notes = [
        note
        for glob, note in _watchlist_entries(CONTEXT.read_text())
        if fnmatch.fnmatch(WATCHLISTED_FILE, glob)
    ]
    assert notes and notes[0], (
        f"the `{WATCHLISTED_FILE}` watchlist entry must carry a short `#` note "
        "saying why it is a gravity well, as the `review.py` entry does "
        "(CAL-1139)."
    )
    note = notes[0].lower()
    missing = [term for term in ("gate", "ledger", "git") if term not in note]
    assert not missing, (
        f"the `{WATCHLISTED_FILE}` note must name its separable concerns — the "
        f"close gate, ledger finalization, and git integrate/merge/push — so a "
        f"reader knows what the trigger is for; missing {missing} in {notes[0]!r} "
        "(CAL-1139)."
    )


def test_linear_py_is_deliberately_not_on_the_watchlist() -> None:
    """``linear.py`` stays off the watchlist: its size is guard-mandated cohesion,
    so a trigger there would fire on changes with no decision to make.

    A tripwire, not a wish — if a later pass arms ``linear.py``, this fails and
    forces the reasoning above to be re-litigated rather than silently reversed
    (CAL-1139 AC-2).
    """
    globs = [glob for glob, _ in _watchlist_entries(CONTEXT.read_text())]
    covering = [pat for pat in globs if fnmatch.fnmatch(EXCLUDED_FILE, pat)]
    assert not covering, (
        f"`{EXCLUDED_FILE}` must NOT be armed on the architecture watchlist — its "
        "size is guard-mandated cohesion (the CAL-731 embed guard forces every "
        "Linear GraphQL call into the one client, per its `# size:` justification), "
        f"so the trigger would fire with no decision to make; covered by {covering} "
        "(CAL-1139 AC-2)."
    )
