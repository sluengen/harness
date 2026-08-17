"""No private surface leaks into the tree — workspace URLs and personal paths.

The repo is public (2026-07-06 open-sourcing decision, CAL-1027). Two private
surfaces must never appear in a tracked file:

* the **workspace URL** — the Linear host plus this workspace's slug — which
  points a reader straight at the author's private tracker; and
* the **personal home path** — an absolute ``/Users/<name>`` path from the
  author's machine — which leaks a username and is meaningless to any reader.

A workspace **rename** does not retire the old slug (CAL-1029). The workspace was
``calibrate-coffee`` before it became ``form-coffee``, and the CAL-1027 scrub was
written against the then-current slug only — so it stripped the ``form-coffee``
URLs and left 24 ``calibrate-coffee`` ones standing in ``specs/``, invisible to
this guard for being spelled with yesterday's name. A stale URL leaks the same
two things a live one does (the private org's identity and a map of ticket ids);
that it now 404s is not redaction. Every slug this workspace has ever answered
to is forbidden, so the tuple below grows on a rename rather than being swapped.

Bare ``CAL-xxx`` ticket ids are deliberately **kept** (opaque to outsiders and
load-bearing in the run ledger); this guard targets only the two surfaces above.

Regression vector this closes: an ``/assess`` report or a proposal routinely
pastes a full Linear URL or an absolute path, silently re-leaking a surface the
CAL-1027 scrub removed. The guard is git-aware (it judges the **committed** tree
via ``tracked_files_under``, so a local scratch file on an author's disk does not
trip it) and self-clean: it builds each forbidden literal from split fragments so
this file itself contains neither contiguous string. Do **not** "tidy" the
concatenations back together — that would make this guard its own false positive.
"""

from __future__ import annotations

from tests._gitutil import tracked_files_under
from tests.unit._prose import REPO_ROOT

# Built from fragments on purpose — see the module docstring. Joined at runtime
# these equal the forbidden literals; split in source, this file stays clean
# and is still scanned like every other tracked file (no self-exclusion carve-out
# that could hide a real leak in this very file).
_WORKSPACE_URL = "linear.app/" + "form-coffee"
#: The pre-rename slug. Kept forbidden forever — see the module docstring.
_WORKSPACE_URL_LEGACY = "linear.app/" + "calibrate-coffee"
_PERSONAL_PATH = "/Users/" + "scottluengen"
_FORBIDDEN = (_WORKSPACE_URL, _WORKSPACE_URL_LEGACY, _PERSONAL_PATH)


def _offenders() -> list[str]:
    """``<relpath>:<lineno>: <literal>`` for every private-surface leak."""
    hits: list[str] = []
    for path in tracked_files_under("."):
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue  # a binary / unreadable file cannot carry a text surface
        rel = path.relative_to(REPO_ROOT)
        for lineno, line in enumerate(text.splitlines(), start=1):
            for needle in _FORBIDDEN:
                if needle in line:
                    hits.append(f"{rel}:{lineno}: {needle}")
    return sorted(hits)


def test_no_private_surface_in_tracked_files() -> None:
    """No tracked file names the workspace URL or a personal home path."""
    offenders = _offenders()
    assert not offenders, (
        "Private surfaces leaked into the public tree (redact the URL to a bare "
        "CAL-xxx id, and the path to a ~/ or <repo-root>-relative form):\n"
        + "\n".join(offenders)
    )
