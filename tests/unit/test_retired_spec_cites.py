"""CAL-633 — no live ``harness/`` source cites a *retired* SPEC section.

SPEC.md is current only for §1–2 (the verb model), §4 (core module design),
and §11 (CLI design); **§3, §5–§10, and §12–§14 describe the retired
deterministic workflow engine and are permanently superseded** (see the banner
at [SPEC.md:4](../../SPEC.md) / the §3 banner). A docstring or comment that
cross-refers a reader into one of those sections sends them to retired prose:
worse than no cite at all.

This had been surfacing one module at a time — CAL-629 (`_time.py`→§12),
CAL-632 (`worktree.py`→§9, `identity.py`→§8) — each a manual find→file→fix
cycle. This guard turns that recurring cycle into ONE structural check: it
greps every git-tracked ``harness/**/*.py`` for a cite to a retired section and
fails, so the existing cluster is swept once and new code can't reintroduce
the class.

Scope (the narrow retired-§ class only): it catches a cite to a *retired*
section. It does NOT catch a cite to the *wrong current* section (e.g. an
events docstring citing §4.9 instead of §4.7) — that adjacent class is guarded
separately by ``test_events_spec_cites.py`` and is the subject of the
broaden-later follow-up CAL-636.

Acceptance criteria (this ticket):

* **AC-1** — a structural guard fails when any live ``harness/`` source cites a
  retired SPEC section. Proven by :func:`test_no_live_harness_source_cites_a_retired_spec_section`
  (it would fail were the sweep below incomplete).
* **AC-2** — the existing retired-§ cluster (§6/§7 in ``state/schema.py``; §12
  in ``state/store.py``, ``events/emitter.py``, and the ``cli/query*`` family)
  is swept — repointed to ``specs/state-store.md``, the current schema
  reference named by the SPEC §3 banner. Proven by the same test passing now.
"""

from __future__ import annotations

import re

import pytest

from tests._gitutil import tracked_files_under

# A cite is keyed on the ``§`` section glyph and the retired section number —
# NOT on a literal ``SPEC `` prefix, so every prefix form is caught equally:
# ``SPEC §12``, ``SPEC.md §12``, ```SPEC.md`` §12``, ``SPEC  §12`` (any spacing),
# and a bare ``§12``. ``§`` is the section-cite marker throughout this codebase,
# so no separate prefix is needed and there is no non-SPEC ``§<digit>`` use to
# false-match. ``\s*`` after the glyph also catches the spaced form ``§ 12``
# (including a non-breaking space, which Unicode ``\s`` matches).
#
# Current sections (§1, §2, §4 and its §4.x subsections, §11) are deliberately
# absent from the alternatives, so a current-section cite never matches
# regardless of trailing subsection digits — ``§4.7`` cannot match because ``4``
# is not an alternative. The ``(?!\d)`` lookahead is the only boundary needed:
# it stops ``§1`` matching inside ``§11`` and ``§12`` inside ``§120``, while
# still matching a sentence-ending cite (``§6.``, ``§12.``) and — deliberately —
# a retired *subsection* cite (``§12.1``, ``§6.2``), since every subsection
# beneath a retired top-level section is itself retired.
_RETIRED_CITE = re.compile(r"§\s*(?:3|5|6|7|8|9|10|12|13|14)(?!\d)")


def _retired_cites_in(text: str) -> list[tuple[int, str]]:
    """Return ``(line_number, line)`` for each line citing a retired section."""
    return [
        (n, line)
        for n, line in enumerate(text.splitlines(), start=1)
        if _RETIRED_CITE.search(line)
    ]


# The regex boundary contract, pinned by example. ``match`` cases are retired
# cites the guard MUST catch; ``no-match`` cases are current-section cites (and
# non-cites) it must NOT flag. Retired *subsections* (``§12.1``, ``§6.2``) are
# in scope: every subsection beneath a retired top-level section is retired.
_MATCH = [
    "see SPEC §6.",            # retired, sentence-terminated
    "SPEC §12 documents",      # retired, mid-sentence
    "SPEC §10 ",               # retired, two-digit
    "SPEC §12.1 row shape",    # retired subsection
    "SPEC §6.2",               # retired subsection
    "SPEC §7 notes",           # retired
    "SPEC.md §12",             # ``.md`` prefix form
    "`SPEC.md` §13",           # backticked prefix form
    "SPEC  §9",                # extra whitespace between prefix and glyph
    "see §14 for the row",     # bare ``§`` with no SPEC prefix
    "SPEC § 12 row",       # ordinary space after the glyph
    "SPEC §\u00a013 row",  # § glyph + non-breaking space (\u00a0) before number
]
_NO_MATCH = [
    "SPEC §11 names",          # current
    "SPEC §4.7 emitter",       # current subsection — 4 is not an alternative
    "see SPEC §1 ",            # current
    "SPEC §1.",                # current, sentence-terminated
    "§4.4",                    # current subsection
    "SPEC §120",               # not a real section; 12 followed by a digit
    "specs/state-store.md",    # the repointed target — no §, must not self-flag
    "see §Observability",      # non-numeric section label (hermes spec)
]


@pytest.mark.parametrize("sample", _MATCH)
def test_retired_cite_regex_matches_retired_sections_and_subsections(sample: str) -> None:
    assert _RETIRED_CITE.search(sample), f"{sample!r} should be flagged as a retired-§ cite"


@pytest.mark.parametrize("sample", _NO_MATCH)
def test_retired_cite_regex_ignores_current_sections(sample: str) -> None:
    assert not _RETIRED_CITE.search(sample), f"{sample!r} must not be flagged"


def test_no_live_harness_source_cites_a_retired_spec_section() -> None:
    """No git-tracked ``harness/**/*.py`` cites a retired SPEC section.

    Retired sections (§3, §5–§10, §12–§14) describe the deleted deterministic
    engine; the current schema reference is ``specs/state-store.md`` and the
    current command/module homes are §4 / §11. A cite into a retired section
    must be repointed, not introduced.
    """
    violations: list[str] = []
    for path in sorted(tracked_files_under("harness")):
        if path.suffix != ".py":
            continue
        for line_no, line in _retired_cites_in(path.read_text()):
            violations.append(f"{path.name}:{line_no}: {line.strip()}")

    assert not violations, (
        "live harness/ source cites a retired SPEC section (§3, §5–§10, "
        "§12–§14 are superseded — the current schema reference is "
        "specs/state-store.md):\n  " + "\n  ".join(violations)
    )
