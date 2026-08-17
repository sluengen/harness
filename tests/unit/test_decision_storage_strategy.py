"""#330 — decision storage is repo-configurable, embedded-first.

*Source:* SYSTEM-3 in ``assessments/2026-08-04-system.md``, plus the operator
``## Resolution`` block on the issue, which is the spec this guard pins.

Universal ``spec-authoring`` stated a flat prohibition — "There is no separate
``decisions/`` folder and no standalone ADRs" — while this repo declares
``paths.decisions`` and keeps a growing numbered ADR set there. An agent applying
the universal rule here was instructed to dismantle the repo's canonical decision
record. The resolution keeps **embedded as the default** and makes the *optional*
``CONTEXT.md`` ``paths.decisions`` key the **only** switch: declare it and the
directory holds decisions that are cross-cutting, consequential and expensive to
reverse; omit it and every decision is embedded in the spec it governs.

What is pinned, and why each check has the shape it has:

* **The rule's home stays ``spec-authoring``.** ``test_skill_boundary_dedup.py``
  owns that ownership claim and stays green — the heading and its pinned tokens
  survive the rewrite, which is why this module asserts the *content* of the rule
  and never re-asserts who owns it.
* **The prohibition sweep is line-scoped with a same-line qualifier**, not
  whole-file containment. Five registered files legitimately keep a prohibition
  phrase *inside* a conditional ("no ``decisions/`` folder **unless** the repo
  configures one"), so a file-level ban would forbid the very sentences that fix
  the finding. :func:`_unconditional_ban` is the single named predicate; the
  sweep, the positive control and the negative control all call it, so degrading
  it is visible (a control carrying its own copy of a predicate is a silent
  survivor — #327).
* **Universal prose names ``paths.decisions``, never a concrete directory.**
  Leaking this repo's ``specs/decisions/`` into installed prose is the same
  universal/repo boundary violation in the opposite direction.
* **The repo side is derived from ``CONTEXT.md``**, not hardcoded, so the guard
  cannot rot if the repo moves or drops the directory.
"""

from __future__ import annotations

import re
from pathlib import Path

from tests.unit.test_distributed_prose_no_repo_ids import _registered_prose_files
from tests.unit.test_skill_boundary_dedup import _section

# ``tests/unit/test_*.py`` → ``parents[2]`` is the repo (or worktree) root.
_REPO_ROOT = Path(__file__).resolve().parents[2]
_SPEC_AUTHORING = _REPO_ROOT / "skills" / "spec-authoring" / "SKILL.md"
_CONTEXT = _REPO_ROOT / "CONTEXT.md"
_DECISION_SECTION = "Decisions live in the spec they govern"

#: Phrases that state the storage prohibition. A line carrying one is making a
#: claim about where decisions may live.
_PROHIBITION = (
    r"standalone ADRs?",
    r"`decisions/` folder",
    r"standalone files?",
    # Supersession-shaped: a record filed in a configured directory is superseded
    # by the repo's own convention, so universal prose may not rule out a new
    # file *there* either. Both phrases are deliberately narrow — a bare
    # ``separate file`` would flag ``templates/change.md``'s unrelated (and
    # correct) "the change spec is the tracker issue — there is no separate
    # file", which is the negative control below.
    r"new numbered file",
    r"chain of separate files",
)

#: Tokens that make such a line *conditional* on the repo's own configuration.
_QUALIFIER = r"paths\.decisions|unless|configur|declar"

#: The five files edited by #330 that keep a prohibition phrase inside a
#: conditional — the sweep must actually see them, or it is measuring nothing.
_CONDITIONAL_FILES = (
    "skills/spec-authoring/SKILL.md",
    "skills/architecture/SKILL.md",
    "agents/architect.md",
    "templates/decision.md",
    "templates/architecture.md",
)


def _states_prohibition(line: str) -> bool:
    """Whether the line makes a claim about standalone decision storage."""
    return any(re.search(p, line, re.I) for p in _PROHIBITION)


def _unconditional_ban(line: str) -> bool:
    """Whether the line bans standalone decision storage with no repo condition.

    The single home of the predicate. Every assertion below — the sweep and both
    controls — calls this function rather than restating the regexes, so a
    mutation to it is visible in more than one test.
    """
    return _states_prohibition(line) and not re.search(_QUALIFIER, line, re.I)


def _prohibition_lines() -> list[tuple[str, str]]:
    """``(relpath, line)`` for every registered-prose line stating a prohibition."""
    found: list[tuple[str, str]] = []
    for path in _registered_prose_files():
        rel = path.relative_to(_REPO_ROOT).as_posix()
        for line in path.read_text().splitlines():
            if _states_prohibition(line):
                found.append((rel, line))
    return found


def _decision_section() -> str:
    return _section(_SPEC_AUTHORING.read_text(), _DECISION_SECTION)


def _context_paths_block() -> str:
    """The ``paths:`` mapping out of this repo's ``CONTEXT.md`` yaml block."""
    text = _CONTEXT.read_text()
    m = re.search(r"\npaths:\n(?P<body>(?:[ \t]+\S.*\n)+)", text)
    assert m, "CONTEXT.md declares no paths: block"
    return m.group("body")


# --- the rule itself ------------------------------------------------------


def test_spec_authoring_conditionalises_adr_storage() -> None:
    """The owner states the switch instead of banning the directory outright."""
    section = _decision_section()
    offenders = [ln for ln in section.splitlines() if _unconditional_ban(ln)]
    assert not offenders, (
        "spec-authoring still bans standalone decision storage unconditionally; "
        f"the repo's configured directory is denied by: {offenders}"
    )
    assert "paths.decisions" in section, (
        "spec-authoring must name `paths.decisions` as the switch that selects "
        "the ADR-directory strategy (#330 resolution)."
    )


def test_spec_authoring_states_the_threshold_and_its_negative_case() -> None:
    """Both halves of the bar: what qualifies, and what explicitly does not.

    The bar is a **conjunction** of three properties, and the conjunction is
    what is asserted — the three terms must co-occur in **one paragraph**, not
    merely somewhere in the section. That narrowing is load-bearing rather than
    tidy: ``cross-cutting`` and ``consequential`` each appear in the section's
    *unchanged* bullets, in different paragraphs, so a section-wide check of the
    three tokens would pass against prose stating only one third of the bar.

    #459 replaced the exact-phrase regex that used to carry this
    (``cross-cutting, consequential, and expensive to reverse``, comma placement
    included) with the paragraph-scoped conjunction. The regex was the class ADR
    0016 names — brittle to a benign reordering of the three properties, while
    verifying bytes rather than the rule — and the paragraph window keeps the
    non-vacuity the regex was actually buying (``craft.md`` → *The text unit is
    part of the predicate*).
    """
    section = _decision_section().lower()
    bar = ("cross-cutting", "consequential", "expensive to reverse")
    assert [p for p in section.split("\n\n") if all(t in p for t in bar)], (
        "no single paragraph of the decision-storage section states the bar as "
        f"the conjunction of all three properties {bar}; spread across "
        "paragraphs, the terms are satisfied by prose that predates the rule"
    )
    assert "several files" in section, (
        "the negative case must be stated — a decision that merely touches "
        "several files does not clear the bar (#330 resolution)."
    )
    assert re.search(r"one canonical|single canonical", section), (
        "a qualifying decision has one canonical record; affected specs link "
        "to it rather than duplicating its reasoning."
    )


def test_spec_authoring_defers_placement_to_the_repo_architecture_index() -> None:
    """Universal guidance defers, and names no concrete decision directory."""
    section = _decision_section()
    assert "architecture index" in section.lower(), (
        "placement, numbering and supersession inside a configured directory "
        "are the repo's business — defer to its architecture index."
    )
    leaked = re.findall(r"\b\w+/decisions/", section)
    assert not leaked, (
        f"universal prose names a concrete decision directory {leaked}; it may "
        "name only the `paths.decisions` key."
    )


def test_architect_agent_permits_a_configured_decision_directory() -> None:
    """The role's prohibition is scoped to a directory the repo never declared."""
    text = (_REPO_ROOT / "agents" / "architect.md").read_text()
    offenders = [ln for ln in text.splitlines() if _unconditional_ban(ln)]
    assert not offenders, f"architect still bans a configured ADR outright: {offenders}"
    assert "paths.decisions" in text, (
        "the architect must know the configured-directory branch exists, or it "
        "will keep embedding a decision the repo files as an ADR."
    )


# --- the sweep, its predicate, and its floors -----------------------------


def test_no_universal_prose_bans_a_configured_decision_directory() -> None:
    """No registered line forbids standalone storage without a repo condition."""
    offenders = [
        f"{rel}: {line.strip()}"
        for rel, line in _prohibition_lines()
        if _unconditional_ban(line)
    ]
    assert not offenders, (
        "registered universal prose contradicts a repo that configures "
        "`paths.decisions`:\n" + "\n".join(offenders)
    )


def test_the_ban_predicate_discriminates() -> None:
    """Positive and negative controls, both through :func:`_unconditional_ban`.

    The positive control is the real pre-#330 prose, trimmed to the clause under
    test: each line must be judged an unconditional ban, or the sweep above would
    have passed against the exact defect. The negative control is the
    conditional form — it carries the
    *same* prohibition phrase, which is why a whole-file containment check would
    condemn the fix and this line-scoped one does not.
    """
    pre_change = (
        "**There is no separate `decisions/` folder and no standalone ADRs.** A "
        "consequential decision is recorded *in the spec it governs*.",
        "a decision is recorded **in the spec it governs**, never a standalone "
        "ADR or a `decisions/` folder, and is superseded **in place**.",
        "- Write standalone ADRs or a `decisions/` folder — decisions live in "
        "the spec they govern.",
        "A consequential decision is **not a standalone file**. Paste this block "
        "into the spec it governs.",
        "Decisions whose scope crosses features live here as Decision blocks, "
        "recorded in place rather than as standalone files.",
    )
    for line in pre_change:
        assert _states_prohibition(line), f"control sample states no prohibition: {line!r}"
        assert _unconditional_ban(line), f"predicate missed the real defect: {line!r}"

    post_change = (
        "A repo that declares no `paths.decisions` has no `decisions/` folder "
        "and no standalone ADRs — embedded, exclusively.",
        "never a standalone ADR or a `decisions/` folder unless the repo "
        "configures one (`paths.decisions`).",
        "Superseding an embedded decision means updating it in-place — not a "
        "new numbered file — and where a repo declares `paths.decisions`, its "
        "architecture index owns supersession for the records filed there.",
    )
    for line in post_change:
        assert _states_prohibition(line), (
            "the negative control must carry the prohibition phrase — that is "
            f"why containment alone would condemn it: {line!r}"
        )
        assert not _unconditional_ban(line), f"predicate flags the fix: {line!r}"

    # The phrase set must DISCRIMINATE as well as match. A bare ``separate
    # file`` would flag this real, unrelated and correct sentence from
    # ``templates/change.md``, which says nothing about decision storage.
    unrelated = (
        "This is the body of the **tracker issue** (`tracker`) — there is no "
        "separate file."
    )
    assert not _states_prohibition(unrelated), (
        "the prohibition set is too broad: it flags prose about where a change "
        f"spec lives, which is not a decision-storage claim: {unrelated!r}"
    )


def test_the_sweep_corpus_and_its_comparison_set_are_non_vacuous() -> None:
    """Floors on both derived sets: the corpus, and the lines it compares.

    A corpus that derives to nothing passes the sweep with a skip; a corpus that
    is fine while *no line states a prohibition* passes it silently, with no skip
    at all. Both are pinned, and the second is anchored on the four files that
    keep the phrase conditionally.
    """
    corpus = {p.relative_to(_REPO_ROOT).as_posix() for p in _registered_prose_files()}
    assert len(corpus) > 20, f"registered-prose corpus collapsed to {len(corpus)} files"
    assert "skills/spec-authoring/SKILL.md" in corpus

    seen = {rel for rel, _ in _prohibition_lines()}
    assert seen, "no registered line states a decision-storage prohibition at all"
    for rel in _CONDITIONAL_FILES:
        assert rel in seen, (
            f"{rel} no longer states the rule; the sweep cannot measure it, and "
            "the conditional form it carries is what the negative control pins."
        )


# --- the configuration surface -------------------------------------------


def test_context_template_declares_the_optional_decisions_path() -> None:
    """The installed template offers the switch, with the bar and the default."""
    text = (_REPO_ROOT / "templates" / "CONTEXT.template.md").read_text()
    m = re.search(r"\n[ \t]*decisions:.*", text)
    assert m, "templates/CONTEXT.template.md paths: carries no optional `decisions:` key"
    entry = m.group(0).lower()
    assert "omit" in entry, "the template must say what omitting the key means"
    assert "expensive to reverse" in entry, (
        "the key's comment must carry the threshold, or a repo declares it for "
        "decisions that belong embedded."
    )


def test_this_repo_configures_a_decisions_path_and_its_index_states_the_rules() -> None:
    """Repo-side coherence, derived from CONTEXT.md rather than hardcoded."""
    paths = _context_paths_block()
    m = re.search(r"^\s*decisions:\s*(?P<value>\S+)", paths, re.MULTILINE)
    if m is None:  # a repo may drop the directory; then there is nothing to check
        return
    directory = _REPO_ROOT / m.group("value")
    assert directory.is_dir(), f"paths.decisions names no directory: {directory}"
    assert list(directory.glob("*.md")), f"configured decision directory is empty: {directory}"

    index = _section(_CONTEXT.read_text(), "Decisions index").lower()
    for token in ("cross-cutting", "expensive to reverse"):
        assert token in index, (
            f"the decisions index must state the placement threshold ({token!r}) "
            "— universal guidance defers placement to it."
        )
    assert re.search(r"supersed", index), (
        "the decisions index must state how an ADR is superseded — universal "
        "guidance defers the mechanic to it."
    )


def test_architecture_principles_indexes_the_configured_decision_directory() -> None:
    """The repo's cross-cutting-decisions section names both homes and the bar.

    The ban sweep alone is too coarse here: the section is one long Markdown
    paragraph, so a *line*-scoped qualifier elsewhere in it would excuse a
    sentence that still denied the ADRs. What is asserted instead is the positive
    claim — the section is the index universal guidance defers to, so it must
    name the configured directory and the bar a record clears.
    """
    paths = _context_paths_block()
    m = re.search(r"^\s*decisions:\s*(?P<value>\S+)", paths, re.MULTILINE)
    if m is None:
        return
    spec = _REPO_ROOT / "specs" / "architecture-principles.md"
    section = _section(spec.read_text(), "Cross-cutting decisions")
    assert m.group("value") in section, (
        "the architecture index must name the configured decision directory "
        f"({m.group('value')}) — universal guidance defers placement to it."
    )
    assert "expensive to reverse" in section.lower(), (
        "the index must state the bar that separates an ADR from an inline "
        "Decision block, or both homes accept the same decision."
    )
    offenders = [ln for ln in section.splitlines() if _unconditional_ban(ln)]
    assert not offenders, (
        "the section claims decisions are never standalone files while this "
        f"repo files ADRs: {offenders}"
    )


def test_the_adr_index_names_exactly_the_records_on_disk() -> None:
    """The re-homed ADR index answers to the decision directory, both ways.

    #461 moved this index out of ``CONTEXT.md`` — one of
    ``test_v4_records_only_what_remains``'s six entry documents — and into
    ``specs/architecture-principles.md``, which is not one. The sixteen links
    went with it and left the only sweep that dangling-checked them: *a
    deletion pass that moves a definition must move its killer*
    (``skills/review-discipline/references/craft.md``). Measured at that
    ticket's review, with a paired splice: breaking one ADR link in the new home
    passed all 1,817 tests, while the same break spliced into ``CONTEXT.md``
    failed ``test_every_path_the_entry_documents_name_resolves``. The survival
    was a gap, not an unproven claim, because the control died first.

    This is that killer, re-homed beside the index. It is a correspondence
    rather than a count, so it fails in both directions and no number in it
    rots: an ADR filed without an index entry fails, and an index entry naming
    no file fails. Widening ``_ENTRY_DOCUMENTS`` to cover this spec was the
    alternative and was rejected — that module's subject is what an agent is
    *required* to read at startup, and this spec is a historical record whose
    Decision blocks cite retired machinery on purpose.
    """
    paths = _context_paths_block()
    m = re.search(r"^\s*decisions:\s*(?P<value>\S+)", paths, re.MULTILINE)
    if m is None:  # a repo may drop the directory; then there is no index to hold
        return
    on_disk = {path.name for path in (_REPO_ROOT / m.group("value")).glob("*.md")}
    assert on_disk, (
        f"no ADRs under {m.group('value')} — the correspondence below would hold "
        "over two empty sets and measure nothing"
    )

    spec = _REPO_ROOT / "specs" / "architecture-principles.md"
    # `_section` raises when the heading is gone, so re-titling the index fails
    # here rather than quietly reducing this guard to a pair of empty sets.
    index = _section(spec.read_text(), "The ADR index")
    targets = re.findall(r"\]\((?!\w+:)([^)\s#]+\.md)\)", index)
    unresolved = [target for target in targets if not (spec.parent / target).is_file()]
    assert not unresolved, (
        "the ADR index links paths resolving to no file, and since #461 nothing "
        f"else dangling-checks this document: {unresolved}"
    )

    linked = {Path(target).name for target in targets}
    assert linked == on_disk, (
        "the ADR index and the configured decision directory disagree. Absent "
        f"from the index: {sorted(on_disk - linked)}; indexed but not on disk: "
        f"{sorted(linked - on_disk)}"
    )


def test_no_feature_spec_duplicates_an_adr_decision() -> None:
    """One canonical home: a feature spec links to an ADR, never restates it."""
    paths = _context_paths_block()
    m = re.search(r"^\s*decisions:\s*(?P<value>\S+)", paths, re.MULTILINE)
    f = re.search(r"^\s*features:\s*(?P<value>\S+)", paths, re.MULTILINE)
    if m is None or f is None:
        return
    titles = {}
    for adr in sorted((_REPO_ROOT / m.group("value")).glob("*.md")):
        head = adr.read_text().splitlines()[0]
        # The strip must *fire*: ``re.sub`` returns the heading unchanged when it
        # misses, which leaves ``titles`` non-empty (so a bare emptiness floor
        # passes) while every key is unmatchable and the check measures nothing.
        parsed = re.match(r"^#\s*ADR\s*\d+\s*[—-]\s*(?P<title>.+)$", head)
        assert parsed, f"{adr.name}: unrecognised ADR heading {head!r}"
        titles[parsed.group("title").strip().lower()] = adr.name
    assert titles, "no ADR titles parsed; the duplication check would be vacuous"
    assert all(t and not t.startswith("#") for t in titles), (
        "a parsed ADR title is empty or still carries its heading markup, so no "
        f"Decision heading could ever match it: {sorted(titles)}"
    )

    duplicated: list[str] = []
    for spec in sorted((_REPO_ROOT / f.group("value")).glob("*.md")):
        for heading in re.findall(r"^#{2,4}\s*Decision:\s*(.+)$", spec.read_text(), re.M):
            if heading.strip().lower() in titles:
                duplicated.append(f"{spec.name}: {heading.strip()}")
    assert not duplicated, (
        "a feature spec restates an ADR as its own Decision block; it must link "
        f"to the canonical record instead: {duplicated}"
    )
