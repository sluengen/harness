"""CAL-1014 — ``harness/cli/review.py`` is on the repo's architecture watchlist.

``review.py`` is the codebase's gravity well: verb orchestration, the prompt, the
SUBMIT parser, per-engine command building, three empirically-derived
engine-failure detectors, and the fallback policy all accrete there, and every
new engine quirk lands another detector in the CLI layer. The repo shipped the
``architecture_watchlist`` mechanism (CAL-815, ``test_architecture_watchlist.py``)
for exactly this pattern: naming a gravity well in ``CONTEXT.md`` makes the next
change touching it carry a ``Watchlist trigger`` section (a seam extraction or a
recorded deferral) instead of silently bolting on more.

CAL-1014 takes the *minimal* arm the ticket offers — add ``review.py`` to
``CONTEXT.md``'s ``architecture_watchlist`` so the shipped mechanism fires on it —
rather than the fuller ``review_engine.py`` extraction, which stays its own
ticket (a large refactor of the untrusted-diff review verb is not a P4 hygiene
change). This guard pins the entry so the tripwire cannot be silently dropped: it
parses ``CONTEXT.md`` and applies the same ``fnmatch`` trigger rule the mechanism
specifies (``test_architecture_watchlist._watchlist_triggers``) to confirm
``review.py`` is actually covered.
"""

from __future__ import annotations

import fnmatch
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
CONTEXT = REPO_ROOT / "CONTEXT.md"

#: The gravity well this ticket puts under the watchlist.
WATCHLISTED_FILE = "harness/cli/review.py"


def _watchlist_files(context_text: str) -> list[str]:
    """The globs under ``architecture_watchlist.files`` in ``CONTEXT.md``.

    Text-parsed, not YAML-loaded, to match the repo's no-YAML-dependency
    convention for reading ``CONTEXT.md`` (see ``harness/loop_budget.py``). The
    ``architecture_watchlist:`` key sits at column 0 of the ``CONTEXT.md`` YAML
    block; the section runs to the next column-0 key, and every ``- <path>`` list
    item within it is a watchlist glob. An absent block yields an empty list.
    """
    start = re.search(r"^architecture_watchlist:.*$", context_text, re.MULTILINE)
    if start is None:
        return []
    rest = context_text[start.end() :]
    nxt = re.search(r"^\w[\w-]*:", rest, re.MULTILINE)
    section = rest[: nxt.start()] if nxt else rest
    return re.findall(r"^\s*-\s*(\S+)", section, re.MULTILINE)


def test_review_py_is_on_the_architecture_watchlist() -> None:
    """``CONTEXT.md`` opts ``review.py`` into the watchlist, and the mechanism's
    trigger rule fires on it (CAL-1014 acceptance criterion, minimal arm)."""
    files = _watchlist_files(CONTEXT.read_text())
    assert files, (
        "CONTEXT.md must define a non-empty `architecture_watchlist.files` so the "
        "gravity-well tripwire is armed (CAL-1014)."
    )
    assert any(fnmatch.fnmatch(WATCHLISTED_FILE, pat) for pat in files), (
        f"`{WATCHLISTED_FILE}` must be covered by a glob in "
        f"`architecture_watchlist.files` so the watchlist mechanism fires on the "
        f"next change that touches it; current globs: {files} (CAL-1014)."
    )
