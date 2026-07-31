"""CAL-1010 — the retired deterministic-engine sections are extracted from SPEC.md.

`SPEC.md` was ~two-thirds retired content: §3, §5–§10, §12–§14 described the
retired deterministic workflow engine, kept inline behind supersede banners
while only §1–2, §4, §11 (and the tail meta sections) are live. #271 extended
the same treatment to §15 / §17 / §18 — the engine's migration plan, open
questions and acceptance criteria — which the original banner named as neither
live nor retired, leaving them reading as current guidance. Retired specs
elsewhere were re-homed under ``specs/retired/`` (CAL-661/693); SPEC.md's own
retired sections were not, so every agent that opened the file paid the context
tax of scrolling past a deleted engine.

These tests are the executable form of the acceptance criteria:

* **AC-1** — the retired sections' *bodies* no longer live in SPEC.md: each
  retired top-level section survives only as a **stub** that points at the
  re-homed doc, and SPEC.md is lean (a fraction of its former size).
* **AC-2** — the moved bodies live in ``specs/retired/spec-engine.md``, a
  git-tracked doc carrying a dated supersede banner and **not** titled
  ``(live)`` (so the ``test_hermes_retired`` retired-spec conventions hold).
* **AC-3** — the live sections (§1–2, §4, §11) survive intact in SPEC.md, so the
  guards that scan them (``test_cli_surface_locked`` / ``test_module_home_spec_cites``)
  keep their source of truth.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from tests._gitutil import tracked_files_under

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SPEC = _REPO_ROOT / "SPEC.md"
_ENGINE = _REPO_ROOT / "specs" / "retired" / "spec-engine.md"

#: The retired top-level sections, per SPEC.md's status banner (§3, §5–§10,
#: §12–§14 describe the retired deterministic workflow engine; §15, §17 and §18
#: plan, question and grade that same engine, and were re-homed after it —
#: §15's migration was abandoned mid-plan when CAL-574 deleted the engine, not
#: completed, so it is preserved as design history rather than dropped).
_RETIRED_SECTIONS = (3, 5, 6, 7, 8, 9, 10, 12, 13, 14, 15, 17, 18)

#: The sections that must remain live and intact in SPEC.md. §16 (Non-Goals) is
#: here because #271 retired the sections either side of it: it is standing
#: policy README.md and CONTEXT.md lean on, and it carries the "*Resolved:
#: external*" boundary the retired §17.4 stated, so it is the one live section
#: bracketed by stubs — the shape most at risk from a sloppy multi-line delete.
_LIVE_SECTIONS = (1, 2, 4, 11, 16)

#: A distinctive body sentence from each retired block — present in SPEC.md
#: today; after the move each must live in ``spec-engine.md`` and be gone from
#: SPEC.md (each verified unique when the test was authored).
_RETIRED_BODY_SENTINELS = {
    3: "← Python package",
    5: "A workflow is **pure YAML**. No Python state classes",
    6: "**State is not declared. State is derived.**",
    7: "the merge is **type-driven**, not configured per-write",
    8: "A single ULID (or short UUID) is generated at workflow start",
    9: "Worktree handling is a node type, not an engine feature",
    10: "Steps execute in declared order.",
    12: "Single database per project",
    13: "# docker/Dockerfile",
    14: "name: steward",
    15: "Cut order: **stewards → bugfix → feature.**",
    17: "These are deliberately unresolved. Pick before code lands.",
    18: "The 10-minute workflow test.",
}

#: The same dated-supersede-banner recognition ``test_docs_consistency`` uses.
_BANNER_RE = re.compile(r"^>\s*\*\*Superseded\s+\d{4}-\d{2}-\d{2}")

#: The re-homed doc, cited by every stub pointer.
_ENGINE_REL = "specs/retired/spec-engine.md"

#: The opening of the stub paragraph a retired section is reduced to. A live
#: section never carries it (mentioning the re-homed doc in signage is fine —
#: e.g. the §3 status banner that sits inside §2's span — but only a stub is
#: *reduced to* this marker).
_STUB_MARKER = "**Retired — deterministic workflow engine.** Moved to"


def _section_body(num: int, full: str) -> str:
    """Body of the ``## <num>. …`` section up to the next ``## `` heading.

    Terminates on *any* top-level heading, not only a numbered one: the last
    numbered section is followed by the unnumbered ``## Appendix A``, and a
    numbered-only terminator would run it to EOF and count the appendix's lines
    as that section's body.
    """
    start = re.search(rf"^## {num}\. ", full, re.M)
    assert start is not None, f"SPEC.md is missing the '## {num}.' section header"
    rest = full[start.end() :]
    nxt = re.search(r"^## ", rest, re.M)
    return rest[: nxt.start()] if nxt else rest


# ---------------------------------------------------------------------------
# The section-splitting helper itself — a retired section at the tail of the
# numbered run is bounded by the unnumbered section that follows it.
# ---------------------------------------------------------------------------


def test_section_body_is_bounded_by_an_unnumbered_heading() -> None:
    """A ``## <word>`` heading terminates a section, not only a ``## <n>.`` one.

    The helper originally terminated on ``^## \\d+\\. `` alone, so the *last*
    numbered section ran to EOF and swallowed everything after it. That makes
    the stub guard below unsatisfiable for that section: even a correct
    three-line stub fails the ``<= 6`` non-blank bound, because the trailing
    unnumbered section's lines are counted as the stub's body.
    """
    doc = "\n".join(
        [
            "## 18. Success Criteria",
            "",
            "> **Retired.** Moved to the re-homed doc.",
            "",
            "## Appendix A — Inspirations and design ancestry",
            "",
            "- an inspiration",
            "- another inspiration",
        ]
    )
    body = _section_body(18, doc)
    assert "Retired." in body, "the section's own body must survive the split"
    assert "Appendix A" not in body, (
        "an unnumbered '## ' heading must bound the preceding numbered section"
    )
    assert "an inspiration" not in body, (
        "the unnumbered section's body must not be attributed to §18"
    )
    # The heading's own tail ("Success Criteria") is the first body line, since
    # the split starts after the "## 18. " marker; the stub paragraph is the
    # second. Nothing from the appendix is counted.
    assert [ln for ln in body.splitlines() if ln.strip()] == [
        "Success Criteria",
        "> **Retired.** Moved to the re-homed doc.",
    ]


def test_spec_md_ends_with_an_unnumbered_section() -> None:
    """SPEC.md really does exhibit the shape the guard above defends against.

    Without a trailing unnumbered section the helper's numbered-only terminator
    would be harmless, and the fix above would assert nothing about this repo.
    """
    headings = re.findall(r"^## .*", _SPEC.read_text(encoding="utf-8"), re.M)
    numbered = [h for h in headings if re.match(r"^## \d+\. ", h)]
    assert headings.index(numbered[-1]) < len(headings) - 1, (
        "SPEC.md's last numbered section is also its last section — the "
        "unnumbered-heading terminator is no longer load-bearing here."
    )


# ---------------------------------------------------------------------------
# AC-1 — SPEC.md keeps only stubs for the retired sections, and is lean.
# ---------------------------------------------------------------------------


#: Headroom above the count at the extraction (was 1,227 lines, cut to ~470).
#: The bound catches a retired-engine section growing a body back; it is not a
#: freeze on the live surface, which grows a line per command registered — #265
#: added ``stats`` and landed on 481 against a bound of 480, so it was raised to
#: 500 with the reason stated rather than nudged by one, since a bound that
#: ratchets to whatever the last change needed has stopped measuring anything.
#: Re-homing §15 / §17 / §18 (#271) then shed 59 lines to 427, so the bound
#: **falls** to keep measuring: a bound left at 500 over a 427-line file would
#: have absorbed the whole cut and stopped catching a regrowing section. The
#: retired-bulk teeth are the per-section stub tests below, which assert each
#: retired section is *reduced to* a pointer — those cannot be satisfied by a
#: section that regrew, whatever the total.
_LEAN_LINE_BOUND = 440


def test_spec_md_is_lean() -> None:
    """SPEC.md shed its retired-engine bulk (was 1,227 lines; live is a fraction)."""
    line_count = len(_SPEC.read_text(encoding="utf-8").splitlines())
    assert line_count <= _LEAN_LINE_BOUND, (
        f"SPEC.md is {line_count} lines — the retired engine sections (§3, §5–§10, "
        f"§12–§14) should be re-homed to {_ENGINE_REL}, leaving only live sections."
    )


@pytest.mark.parametrize("num", _RETIRED_SECTIONS)
def test_retired_section_is_a_stub_pointing_at_the_rehomed_doc(num: int) -> None:
    """Each retired top-level section survives in SPEC.md only as a short stub."""
    body = _section_body(num, _SPEC.read_text(encoding="utf-8"))
    assert _STUB_MARKER in body and _ENGINE_REL in body, (
        f"SPEC §{num} must be a stub pointing at {_ENGINE_REL}; its body does not "
        "carry the retired-section stub marker."
    )
    # A stub is a pointer, not the moved content — a handful of lines at most.
    non_blank = [ln for ln in body.splitlines() if ln.strip()]
    assert len(non_blank) <= 6, (
        f"SPEC §{num} still carries {len(non_blank)} non-blank lines — the body "
        f"should be re-homed to {_ENGINE_REL}, leaving only a pointer stub."
    )


@pytest.mark.parametrize("num", _RETIRED_SECTIONS)
def test_retired_body_is_gone_from_spec_md(num: int) -> None:
    """The distinctive body of each retired section no longer lives in SPEC.md."""
    sentinel = _RETIRED_BODY_SENTINELS[num]
    assert sentinel not in _SPEC.read_text(encoding="utf-8"), (
        f"SPEC.md still contains retired §{num} body text ({sentinel!r}); it must "
        f"move to {_ENGINE_REL}."
    )


# ---------------------------------------------------------------------------
# The currency map — SPEC.md's status banner and the re-homed doc's H1 both
# enumerate the retired set, and must agree with the set the guards enforce.
# ---------------------------------------------------------------------------


#: A run of section cites: ``§3``, ``§5–§10`` (en dash, em dash or hyphen), with
#: or without a second ``§``. Expanded to the full set so a range and its
#: spelled-out equivalent are the same claim — ``§12–§15`` and
#: ``§12, §13, §14, §15`` must not be able to disagree.
_SECTION_RUN_RE = re.compile(r"§\s*(\d+)\s*(?:[–—-]\s*§?\s*(\d+))?")


def _enumerated_sections(text: str) -> set[int]:
    """Every section number a cite run names, ranges expanded."""
    found: set[int] = set()
    for low, high in _SECTION_RUN_RE.findall(text):
        found.update(range(int(low), int(high or low) + 1))
    return found


def test_spec_status_banner_enumerates_exactly_the_retired_set() -> None:
    """SPEC.md's own banner names the same retired sections the guards enforce.

    The map is duplicated across the banner, the §3 banner, the spec-index row
    and the re-homed doc's H1; a change that moves one and not the others leaves
    the file contradicting itself, which is the defect #271 existed to fix.
    """
    status = next(
        ln
        for ln in _SPEC.read_text(encoding="utf-8").splitlines()
        if ln.startswith("**Status:**")
    )
    run = re.search(r"((?:§\s*\d+\s*(?:[–—-]\s*§?\s*\d+)?[,\s]*(?:and\s+)?)+)described", status)
    assert run is not None, (
        "SPEC.md's **Status:** line must enumerate the retired sections "
        "immediately before the word 'described'."
    )
    assert _enumerated_sections(run.group(1)) == set(_RETIRED_SECTIONS), (
        "SPEC.md's status banner and _RETIRED_SECTIONS disagree about which "
        "sections are retired — the banner is what a reader trusts."
    )


def test_rehomed_doc_h1_enumerates_exactly_the_retired_set() -> None:
    """The re-homed doc's H1 names every section whose body it carries."""
    h1 = next(
        ln
        for ln in _ENGINE.read_text(encoding="utf-8").splitlines()
        if ln.startswith("# ")
    )
    assert _enumerated_sections(h1) == set(_RETIRED_SECTIONS), (
        f"{_ENGINE_REL}'s H1 must enumerate exactly the sections it carries; it "
        "is the first thing a reader arriving from a stub pointer sees."
    )


def test_live_and_retired_sections_partition_spec_md() -> None:
    """Every numbered section is declared exactly once — live or retired.

    §15 / §17 / §18 sat in *neither* list before #271, which is precisely how
    three sections of retired design went on reading as live guidance.
    """
    numbered = {
        int(m)
        for m in re.findall(r"^## (\d+)\. ", _SPEC.read_text(encoding="utf-8"), re.M)
    }
    declared = set(_RETIRED_SECTIONS) | set(_LIVE_SECTIONS)
    assert numbered == declared, (
        f"sections declared by neither list: {sorted(numbered - declared)}; "
        f"declared but absent from SPEC.md: {sorted(declared - numbered)}"
    )
    assert not set(_RETIRED_SECTIONS) & set(_LIVE_SECTIONS), (
        "a section cannot be both live and retired"
    )


# ---------------------------------------------------------------------------
# AC-2 — the re-homed doc carries the moved bodies, tracked and bannered.
# ---------------------------------------------------------------------------


def test_spec_engine_doc_is_tracked() -> None:
    """``specs/retired/spec-engine.md`` is a committed file (git-aware guard)."""
    assert _ENGINE.resolve() in tracked_files_under(_ENGINE_REL), (
        f"{_ENGINE_REL} must be a git-tracked file — the SPEC.md stubs point at it."
    )


def test_spec_engine_doc_has_dated_supersede_banner() -> None:
    """The re-homed doc carries a dated supersede banner near the top."""
    head = _ENGINE.read_text(encoding="utf-8").splitlines()[:12]
    assert any(_BANNER_RE.match(line) for line in head), (
        f"{_ENGINE_REL} needs a dated supersede banner of the form "
        "'> **Superseded YYYY-MM-DD** …' near the top (see hermes-control-model.md)."
    )


def test_spec_engine_doc_is_not_titled_live() -> None:
    """The re-homed doc's H1 must not wear the ``(live)`` badge (test_hermes_retired)."""
    for line in _ENGINE.read_text(encoding="utf-8").splitlines():
        if line.startswith("# "):
            assert "(live)" not in line.lower(), (
                f"{_ENGINE_REL} is retired design history; its H1 must not be '(live)'."
            )
            break


@pytest.mark.parametrize("num", _RETIRED_SECTIONS)
def test_retired_body_lives_in_spec_engine_doc(num: int) -> None:
    """Each retired section's header and distinctive body live in the re-homed doc."""
    text = _ENGINE.read_text(encoding="utf-8")
    assert re.search(rf"^## {num}\. ", text, re.M), (
        f"{_ENGINE_REL} is missing the '## {num}.' section header."
    )
    sentinel = _RETIRED_BODY_SENTINELS[num]
    assert sentinel in text, (
        f"{_ENGINE_REL} is missing retired §{num} body text ({sentinel!r})."
    )


# ---------------------------------------------------------------------------
# AC-3 — the live sections survive intact in SPEC.md.
# ---------------------------------------------------------------------------


def test_non_goals_still_carries_the_boundary_retired_17_deferred_to_it() -> None:
    """§16 keeps the boundary that justified retiring §17 (#271).

    §17.4 asked whether an external trigger source belongs in the harness and
    answered "*Resolved: external*". Retiring §17 loses nothing **only because**
    §16 states the same boundary as standing policy — no daemon, no built-in
    scheduling, not a general-purpose agent framework. If that content ever left
    §16, retiring §17 would have quietly dropped a live resolution, so the
    justification is pinned here rather than left as prose in a changelog.
    """
    body = _section_body(16, _SPEC.read_text(encoding="utf-8"))
    for claim, pattern in (
        ("no long-running daemon", r"daemon"),
        ("no built-in scheduling", r"[Bb]uilt-in scheduling"),
        ("not a general-purpose agent framework", r"[Gg]eneral-purpose agent framework"),
    ):
        assert re.search(pattern, body), (
            f"SPEC §16 no longer states '{claim}' — retired §17.4 deferred its "
            "'Resolved: external' boundary to §16, so §16 must keep carrying it."
        )


@pytest.mark.parametrize("num", _LIVE_SECTIONS)
def test_live_section_survives_in_spec_md(num: int) -> None:
    """A live section keeps a real body in SPEC.md (not reduced to a stub)."""
    body = _section_body(num, _SPEC.read_text(encoding="utf-8"))
    assert _STUB_MARKER not in body, (
        f"SPEC §{num} is a *live* section — it must not be reduced to a "
        f"retired-section stub pointing at {_ENGINE_REL}."
    )
    non_blank = [ln for ln in body.splitlines() if ln.strip()]
    assert len(non_blank) > 6, (
        f"SPEC §{num} is a live section but has only {len(non_blank)} non-blank "
        "lines — its content must survive intact."
    )
