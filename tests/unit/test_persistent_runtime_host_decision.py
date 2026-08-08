"""#304 — SPEC §16 records the persistent-runtime-host carve-out (ADR 0012).

§16 lists "long-running daemon / server" and "built-in scheduling" as explicit
non-goals. ADR 0012 decides to build a persistent host-side process that owns
credentials, image freshness, container construction, and periodic maintenance.
Until §16 records the carve-out, every ticket in the #305–#313 chain is built
against a spec that forbids it.

The amendment **keeps both entries** and annotates each. That is the whole
point: the intent they encode — the CLI runs, completes, exits; state persists
in SQLite — still binds every verb, and it is precisely what *bounds* the
carve-out. Deleting an entry would remove the bound and leave the exception
unbounded, so this guard treats the headline and the intent as load-bearing,
not as prose the amendment may tidy away.

The bound itself is the **no-run-state** constraint: the host process is a
credential broker, a spawner, and a scheduler; anything that outlives a request
and describes a run has exceeded the carve-out. It is a safety property, not
documentation hygiene — the close gate's guarantee holds only because the
ledger is a run's sole memory (ADR 0012, decision D2), so a host process
holding run state would break it while appearing to work. Stating it in §16
makes an over-reaching future design reviewable against the spec, not only
against the ADR.

Acceptance criteria:

* **AC-1** — §16 retains both non-goal entries, each carrying an exception
  clause resolving to ``specs/decisions/0012-persistent-runtime-host.md``.
  Proven by :func:`test_both_amended_entries_retain_headline_and_intent` and
  :func:`test_section_16_cites_the_persistent_runtime_host_adr`.
* **AC-2** — whenever the ADR exists, §16 references it, so removing the
  pointer fails the gate rather than silently leaving §16 contradicting a live
  decision. Proven by :func:`test_section_16_cites_the_persistent_runtime_host_adr`
  (conditional, per the AC) with :func:`test_the_adr_is_present` as its
  non-vacuity floor and :func:`test_the_cited_adr_path_resolves` proving the
  cited path is live rather than merely present as a string.
* **AC-3** — the no-run-state bound is stated in §16 itself, not only in the
  ADR. Proven by :func:`test_section_16_states_the_no_run_state_bound`, floored
  by :func:`test_the_adr_states_the_no_run_state_bound`.

**Design departure, recorded deliberately.** The design specified a local
title-keyed section slicer ("find the heading containing ``Non-Goals``") so a
renumbered §16 stays findable. This module instead **imports**
:func:`tests.unit.test_spec_engine_extraction._section_body` and asks for
section 16. The reason is that §16's number is already pinned repo-wide — that
module's ``_LIVE_SECTIONS`` contains 16 and asserts the section survives — so a
renumber already fails loudly there, and a second slicer here would be a
re-derivation of an already-established fact (the failure mode recorded at
#249/#252). The imported helper asserts its own header lookup, so a renumber
surfaces here as a stated assertion failure, never as a silent empty slice —
which is the property the design's scenario actually asked for.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from tests.unit.test_spec_engine_extraction import _section_body

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SPEC = _REPO_ROOT / "SPEC.md"
_DECISIONS = _REPO_ROOT / "specs" / "decisions"

#: The ADR is resolved by **slug**, not by number: ``0011`` was already taken by
#: ``0011-attended-run-spend-scope.md`` when this decision was written, so the
#: series has collided once and can again. A renumber must leave the ADR
#: findable, so that the fault reported is §16's stale link — the real defect —
#: rather than this guard's own missing constant.
_ADR_GLOB = "*-persistent-runtime-host.md"

#: §16's non-goal list is a flat bullet list; a bullet's continuation lines are
#: indented and do not open with ``- ``.
_BULLET_RE = re.compile(r"^- ", re.MULTILINE)


def _adr() -> Path | None:
    """The persistent-runtime-host ADR, or ``None`` when it is not recorded.

    Two matches means a rename left both files behind — an ambiguous state that
    fails explicitly rather than being silently exempted by a skip.
    """
    hits = sorted(_DECISIONS.glob(_ADR_GLOB))
    assert len(hits) <= 1, (
        f"{len(hits)} files match specs/decisions/{_ADR_GLOB} "
        f"({[h.name for h in hits]}) — a rename left both behind; §16 cannot "
        "cite an ambiguous decision."
    )
    return hits[0] if hits else None


def _non_goals() -> str:
    """§16's body, sliced by the repo's one section slicer (see the departure note)."""
    return _section_body(16, _SPEC.read_text(encoding="utf-8"))


def _entries(section: str) -> list[str]:
    """The section's bullets, each with its indented continuation lines attached.

    The amended entries wrap onto continuation lines, so a line-scoped reader
    would not see an exception clause that sits on a bullet's second line.
    """
    starts = [m.start() for m in _BULLET_RE.finditer(section)]
    bounds = starts + [len(section)]
    return [section[bounds[i] : bounds[i + 1]].strip() for i in range(len(starts))]


def _entry(section: str, keyword: str) -> str:
    """The single §16 bullet naming ``keyword``."""
    hits = [e for e in _entries(section) if keyword in e.lower()]
    assert len(hits) == 1, (
        f"expected exactly one SPEC §16 non-goal mentioning {keyword!r}, "
        f"found {len(hits)}. §16 must retain the entry — the intent it encodes "
        "is what bounds the ADR 0012 carve-out."
    )
    return hits[0]


# --- Non-vacuity floors ------------------------------------------------------
# Every assertion below reads a set derived at runtime (the ADR file, the §16
# slice, its bullets). Each derivation gets a floor, because a derived guard's
# failure mode in this repo is going green while measuring nothing.


def test_the_adr_is_present() -> None:
    """Floor for AC-2's conditional cite test, which *skips* when the ADR is absent.

    AC-2 is deliberately conditional — a retired decision leaves §16 free to
    stand unamended. But a conditional guard whose condition silently stops
    holding is the empty-subject vacuous pass: the cite test would skip and the
    run would stay green. This asserts the condition is live today, so removing
    the ADR is a deliberate, visible edit here rather than a quiet loss of
    coverage.
    """
    assert _adr() is not None, (
        f"no specs/decisions/{_ADR_GLOB} — ADR 0012 records the carve-out SPEC "
        "§16 is amended for. If the decision was genuinely retired, retire this "
        "guard in the same change rather than letting the cite test skip."
    )


def test_the_non_goals_section_parses_into_its_entries() -> None:
    """Floor for every §16 assertion: the slice is real and holds its bullets.

    A structural break must report as a structural break here, rather than as a
    confusing downstream miss in a cite assertion reading an empty string.
    """
    section = _non_goals()
    assert section.strip(), "SPEC §16 sliced to an empty body"
    entries = _entries(section)
    assert len(entries) >= 8, (
        f"SPEC §16 parsed to {len(entries)} bullets, expected at least 8 — the "
        "non-goal list lost entries, or the bullet parse broke."
    )


def test_the_adr_states_the_no_run_state_bound() -> None:
    """Floor for AC-3: the bound §16 must carry is the one the ADR records.

    AC-3 asserts §16 states the bound. If the ADR's own wording of it ever
    disappeared, §16's copy would be pinned against nothing — so the source is
    anchored before the copy is required.
    """
    adr = _adr()
    assert adr is not None, "guarded by test_the_adr_is_present"
    text = adr.read_text(encoding="utf-8").lower()
    assert "run state" in text, (
        "ADR 0012 must state the no-run-state constraint — it is the bound the "
        "SPEC §16 carve-out is measured against."
    )
    assert re.search(r"\b(no|never|holds no)\b[^.]{0,80}run state", text), (
        "ADR 0012 mentions 'run state' but not as a prohibition; the carve-out's "
        "bound is that the host process holds *no* run state."
    )


# --- AC-1: both entries survive, headline and intent intact ------------------


def test_both_amended_entries_retain_headline_and_intent() -> None:
    """AC-1: the amendment annotates the two non-goals; it does not replace them.

    The intent clauses are asserted specifically, because "keep the entry" is
    satisfiable by a stub reading "Long-running daemon — see ADR 0012", and that
    stub is the regression: it deletes the bound while looking like a citation.
    """
    section = _non_goals()

    daemon = _entry(section, "daemon")
    assert re.search(r"runs,\s*completes,\s*exits", daemon, re.IGNORECASE), (
        "SPEC §16's daemon non-goal lost its intent ('The CLI runs, completes, "
        "exits'). That sentence is what bounds the ADR 0012 carve-out — the "
        "exception is that a *host* persists, not that a verb does."
    )

    scheduling = _entry(section, "scheduling")
    assert re.search(r"cron|launchd|systemd", scheduling, re.IGNORECASE), (
        "SPEC §16's built-in-scheduling non-goal lost its intent (cron / launchd "
        "/ systemd trigger the harness). The carve-out lets the host run the "
        "harness's own maintenance; it does not make the harness a scheduler."
    )


# --- AC-1 / AC-2: each amended entry resolves to the ADR ---------------------


def test_section_16_cites_the_persistent_runtime_host_adr() -> None:
    """AC-1/AC-2: both amended entries carry a pointer to the live decision.

    Asserted on the path *string*, so a markdown link, a backticked path and a
    bare path all pass — the contract is that the pointer resolves, not which
    markup carries it.
    """
    adr = _adr()
    if adr is None:  # pragma: no cover - floored by test_the_adr_is_present
        pytest.skip(f"no specs/decisions/{_ADR_GLOB}; §16 need not cite it")

    rel = adr.relative_to(_REPO_ROOT).as_posix()
    section = _non_goals()
    for keyword in ("daemon", "scheduling"):
        entry = _entry(section, keyword)
        assert rel in entry, (
            f"SPEC §16's {keyword!r} non-goal must cite {rel}. ADR 0012 is live "
            "and carves an exception out of this entry; without the pointer, §16 "
            "reads as forbidding what the harness is being built to do."
        )


def test_the_cited_adr_path_resolves() -> None:
    """AC-2: the path §16 cites is a file that exists — not a stale link.

    Read back out of §16 rather than re-using :func:`_adr`'s answer, so a
    renumber that updates the file but not the spec fails here.
    """
    section = _non_goals()
    cited = set(re.findall(r"specs/decisions/[\w./-]+\.md", section))
    assert cited, "SPEC §16 cites no specs/decisions/ path at all"
    for path in sorted(cited):
        assert (_REPO_ROOT / path).is_file(), (
            f"SPEC §16 cites {path}, which does not exist. A renumbered or "
            "renamed ADR must be followed here — a dead pointer is the failure "
            "this guard exists to catch."
        )


# --- AC-3: the bound is legible from §16 alone -------------------------------


def test_section_16_states_the_no_run_state_bound() -> None:
    """AC-3: a reader of §16 alone can tell what the exception does not permit.

    The bound is asserted as a *prohibition* bound to 'run state' within one
    sentence, not as the bare presence of the phrase: §16 mentioning run state
    approvingly would satisfy a substring check while inverting the meaning.
    """
    section = _non_goals()
    assert re.search(
        r"\b(no|never|holds no|not)\b[^.]{0,80}run state", section, re.IGNORECASE
    ), (
        "SPEC §16 must state the carve-out's bound — the host process holds no "
        "run state — so a reader of §16 alone can tell what ADR 0012 does not "
        "permit. Stating it only in the ADR leaves an over-reaching design "
        "reviewable against the ADR but not against the spec."
    )
