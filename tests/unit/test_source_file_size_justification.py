"""CODE-1 / CODE-INSIGHT-1 (2026-06-15 code assessment) — the 500-line size rule
is enforced on production source, not just asserted in the skill text.

``code-quality`` Part C requires any file over the 500-line hard limit to carry,
at its top, a language-native ``size: <reason>`` justification comment (or
reference an open tracking ticket); the reviewer **rejects** an over-limit file
with neither. But the existing guard ``test_code_quality_size_justification``
only checks that the *skill* states the rule — nothing scans the source. So
``harness/launcher.py`` grew to 525 lines during CAL-675 with no justification
and slipped through undetected: the rule was enforced by human attention alone,
which is exactly the silent drift it was written to prevent (CAL-666).

This guard turns the rule into a suite gate for the production package. It globs
the git-tracked ``harness/**/*.py`` and fails for any file past the hard limit
that does not carry a ``size:`` justification comment — the same
text-structural form as ``test_retired_spec_cites`` (CAL-633) and
``test_guidance_footprint`` (CAL-648): a recurring manual find→fix cycle turned
into one structural check.

Scope and discriminator:

* **Production source only** (``harness/``). Production drift is the steward's
  recurring pain — an unjustified production module crossing the limit is what
  CAL-666 was written to stop — so this guard scopes to ``harness/`` as a
  deliberate boundary. ``tests/`` is left to reviewer judgment for now (several
  test files are over the limit; whether an over-limit test file is a field-list
  case table or genuinely inlined logic is a separate decision, not assumed
  here).
* **Keys on the explicit ``size:`` marker**, the concrete form the rule names —
  not on an incidental ticket cite. ``launcher.py`` already references CAL-579
  as *design provenance*, which is not a size decision and must not satisfy the
  guard. The prose's "or a ticket" alternative stays a reviewer-judgment path;
  the structural gate enforces the strong, unambiguous form so no incidental
  cite anywhere in a long file produces a false green.
* **Requires a reason.** ``# size:`` with nothing after it does not justify
  anything, so the marker must be followed by non-whitespace.

Acceptance criteria (this ticket):

* **AC-1** — a production ``harness/`` file over the 500-line hard limit with no
  ``size:`` justification fails the guard. Proven by
  :func:`test_over_limit_source_files_carry_a_size_justification` (it failed on
  ``launcher.py`` before this change; the marker regex contract below pins what
  counts as a justification so an incidental cite cannot satisfy it).
* **AC-2** — ``harness/launcher.py`` carries a ``# size:`` justification, so the
  guard passes on the current tree.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from tests._gitutil import tracked_files_under

# ``tests/unit/test_*.py`` → ``parents[2]`` is the repo (or worktree) root.
_REPO_ROOT = Path(__file__).resolve().parents[2]

# Part B / Part C of ``code-quality``: the hard limit for a module/file.
_HARD_LIMIT = 500

# A size justification is a Python comment containing the ``size:`` marker
# followed by a non-empty reason. Harness source is pure Python, so the marker is
# a ``#`` comment. The pattern deliberately does NOT accept a bare ticket cite:
# an incidental ``CAL-579`` provenance reference is not a size decision, and an
# empty ``# size:`` records no reason.
_SIZE_JUSTIFICATION = re.compile(r"#.*\bsize:\s*\S")


def _line_count(path: Path) -> int:
    return len(path.read_text(encoding="utf-8").splitlines())


def _has_size_justification(path: Path) -> bool:
    return bool(_SIZE_JUSTIFICATION.search(path.read_text(encoding="utf-8")))


# The marker contract, pinned by example. ``match`` cases are real size
# justifications the guard MUST accept; ``no-match`` cases are comments (and
# code) it must NOT accept as a justification — most importantly an incidental
# ticket cite, which is what would otherwise let ``launcher.py`` pass untouched.
_MARKER_MATCH = [
    "# size: cohesive launcher concern, kept together",
    "    # size: single concern — split would scatter the gate",
    "x = 1  # size: inline trailing form is fine",
]
_MARKER_NO_MATCH = [
    "# see CAL-579 for the launch decision",  # incidental ticket cite, not a size decision
    "# resize the ring buffer before write",  # 'size' substring, no marker colon
    "size = len(items)",  # code, not a comment marker
    "# size:",  # marker with no reason recorded
    "# size: ",  # marker, trailing whitespace only — still no reason
]


@pytest.mark.parametrize("sample", _MARKER_MATCH)
def test_size_marker_regex_accepts_real_justifications(sample: str) -> None:
    assert _SIZE_JUSTIFICATION.search(sample), f"{sample!r} should count as a size justification"


@pytest.mark.parametrize("sample", _MARKER_NO_MATCH)
def test_size_marker_regex_rejects_non_justifications(sample: str) -> None:
    assert not _SIZE_JUSTIFICATION.search(sample), f"{sample!r} must not count as a justification"


def test_over_limit_source_files_carry_a_size_justification() -> None:
    """Every over-limit ``harness/`` source file records a size decision (AC-1, AC-2)."""
    offenders = [
        path
        for path in sorted(tracked_files_under("harness"))
        if path.suffix == ".py"
        and _line_count(path) > _HARD_LIMIT
        and not _has_size_justification(path)
    ]
    assert not offenders, (
        f"these production source files are over the {_HARD_LIMIT}-line hard "
        "limit with no `# size: <reason>` justification (code-quality Part C) — "
        "add a one-line `# size:` comment recording why the file may exceed the "
        "limit, or split it:\n"
        + "\n".join(
            f"  - {p.relative_to(_REPO_ROOT)}: {_line_count(p)} lines" for p in offenders
        )
    )
