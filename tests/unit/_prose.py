"""Shared prose-reading helpers for the guard suite, and the repository root.

Almost every guard in ``tests/unit/`` reads prose out of the tree and asserts
something structural about it, so almost every one of them needs the same two
things: where the repository is, and a way to cut a document down to the unit
the assertion is actually about. Before #467 both were per-module. **135**
modules bound their own root — under three names (``_REPO_ROOT`` ×80,
``REPO_ROOT`` ×52, ``ROOT`` ×3) and two expressions — and 30 modules imported
slicers out of
whichever sibling ``test_*`` module had defined one first — which made those
siblings libraries, and a library cannot be deleted, renamed or converted
without an importer audit. The ADR 0016 triage hit exactly that, annotating one
module "Must keep exporting ``_sentences``" in the middle of a pass whose whole
purpose was deciding what to delete.

This is the neutral home for the helpers that are genuinely shared, beside
:mod:`tests._gitutil` for git and :mod:`tests.unit._hooks` for captured host
payloads. It is deliberately **not** a home for every helper: a slicer whose
semantics are local to one guard stays in that guard. Twenty modules defined a
``_section`` under seven incompatible signatures at the time of the move (the
ticket enumerated five of them), and unifying them was
explicitly not the goal — the three with importers came here under names that
say what each actually does (:func:`section`, :func:`section_by_title`,
:func:`update_guidance_between`), and the local ones stayed local. Two sentence splitters
likewise: :func:`sentences` and :func:`sentences_on_break` disagree about what
ends a sentence, and both disagreements are load-bearing where they are used.

``REPO_ROOT`` is the **resolved** form. Seventeen modules bound the unresolved
``Path(__file__).parent.parent.parent``, which is the frame-mismatch hazard the
craft reference names: compared against a git-printed path, an unresolved root
is a latent constant-true or constant-false on any checkout reached through a
symlink, and nothing at the comparison says which.
"""

from __future__ import annotations

import re
from pathlib import Path

from tests._gitutil import tracked_files_under

#: ``tests/unit/_prose.py`` → ``parents[2]`` is the repo (or worktree) root.
REPO_ROOT = Path(__file__).resolve().parents[2]

REGISTRY = REPO_ROOT / "registry.yaml"
CODE_QUALITY = REPO_ROOT / "skills" / "code-quality" / "SKILL.md"
REVIEW_DISCIPLINE = REPO_ROOT / "skills" / "review-discipline" / "SKILL.md"
DIFF_SHAPE_CHECKS = (
    REPO_ROOT / "skills" / "review-discipline" / "references" / "diff-shape-checks.md"
)
ASSESS = REPO_ROOT / "commands" / "assess.md"
UPDATE_GUIDANCE = REPO_ROOT / "commands" / "update-guidance.md"


def read(rel: str) -> str:
    """A repo-relative file's text."""
    return (REPO_ROOT / rel).read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# The distributed surface — what a consumer actually receives
# ---------------------------------------------------------------------------

#: The universal-prose directories — the hook's ``PROSE`` set. Leaks are
#: leak-checked only inside these (``hooks`` / ``settings`` are distributed but
#: not prose).
PROSE_DIRS = ("skills", "agents", "commands", "process", "templates")


def registered_surface() -> list[Path]:
    """Every prose file ``registry.yaml`` distributes, as repo-relative paths.

    The same scope rule ``test_distributed_prose_no_repo_ids`` applies: what the
    registry lists under ``files:`` is what a consumer actually receives.
    """
    entries = re.findall(r"^\s{2}([\w./-]+\.(?:md|json)):\s*\{", REGISTRY.read_text(), re.M)
    return [Path(e) for e in entries if e.endswith(".md")]


def registered_markdown() -> list[str]:
    """Every registered `.md` file, as repo-relative posix paths."""
    return [p.as_posix() for p in registered_surface()]


def is_registered(rel_path: str, registry_src: str) -> bool:
    """Whether ``rel_path`` is a member of ``registry.yaml``'s files block.

    Mirrors the hook's ``registryMember`` rule (a ``<path>: {`` mapping key)
    rather than re-deriving it, so source and guard agree on what "distributed"
    means.
    """
    pattern = r"(^|\n)\s*" + re.escape(rel_path) + r":\s*\{"
    return re.search(pattern, registry_src) is not None


def registered_prose_files() -> list[Path]:
    """Git-tracked, registry-member files under the universal-prose dirs."""
    registry_src = REGISTRY.read_text()
    found: list[Path] = []
    for prose_dir in PROSE_DIRS:
        for path in sorted(tracked_files_under(prose_dir)):
            rel = path.relative_to(REPO_ROOT).as_posix()
            if is_registered(rel, registry_src):
                found.append(path)
    return found


# ---------------------------------------------------------------------------
# Slicers — three, because they mean three different things
# ---------------------------------------------------------------------------


def section(text: str, header: str) -> str:
    """The body of ``header``, from the header line to the next heading of its level or above.

    ``header`` is the **whole heading line** including its ``#`` marks, so the
    level is read off it rather than searched for.
    """
    match = re.search(rf"^{re.escape(header)}\s*$", text, re.MULTILINE)
    assert match, f"missing section header {header!r}"
    level = len(header) - len(header.lstrip("#"))
    rest = text[match.end() :]
    end = re.search(rf"^#{{1,{level}}} ", rest, re.MULTILINE)
    return rest[: end.start()] if end else rest


def section_by_title(text: str, heading: str) -> str:
    """The body of a Markdown section, found by heading **text** at any level.

    From the line whose stripped heading text equals ``heading`` (at any ``#``
    level) up to the next heading of the same-or-higher level, a horizontal
    rule, or EOF. Used to scope an assertion to one subsection so a cross-ref in
    a *different* part of the file cannot satisfy it.

    Distinct from :func:`section` in two ways that matter to its callers: the
    caller does not have to know the level, and a ``---`` rule ends the body.
    """
    lines = text.splitlines()
    start: int | None = None
    level = 0
    for i, line in enumerate(lines):
        m = re.match(r"(#+)\s+(.*)$", line)
        if m and m.group(2).strip() == heading:
            start, level = i + 1, len(m.group(1))
            break
    assert start is not None, f"section heading not found: {heading!r}"
    body: list[str] = []
    for line in lines[start:]:
        m = re.match(r"(#+)\s+", line)
        if (m and len(m.group(1)) <= level) or line.strip() == "---":
            break
        body.append(line)
    return "\n".join(body)


def update_guidance_between(start: str, end: str) -> str:
    """``commands/update-guidance.md`` between two literal delimiters.

    Literal bounds rather than a heading level, because the two guards reading
    this document slice it by step marker (``"### 2."`` to ``"### 3."``).
    ``str.index`` raises rather than returning ``-1``, so a delimiter that stops
    resolving fails loudly instead of yielding a slice that silently satisfies
    everything read from it.
    """
    text = UPDATE_GUIDANCE.read_text(encoding="utf-8")
    return text[text.index(start) : text.index(end)]


# ---------------------------------------------------------------------------
# Sentence and instruction units — the unit is part of the predicate
# ---------------------------------------------------------------------------


def sentences(text: str) -> list[str]:
    """``text`` split into sentences, each with its internal wrapping normalized.

    Prose in this tree is hard-wrapped, so a rule routinely spans two source
    lines. Normalizing inside the sentence is what lets a predicate anchor on a
    phrase (*"a small estimated diff alone"*) rather than on a line break.

    **The closing emphasis is part of the boundary.** This tree bolds its
    load-bearing rules, so a sentence ends ``…diff alone.**`` — a ``*``, not a
    ``.``, before the space. A splitter looking one character back never fires
    there, and the rule merges with everything after it. That is not cosmetic:
    every polarity predicate over these units asks *"is there a negation in this
    unit"*, so a merged unit lends a rule's own ``Never`` to the sentence
    contradicting it. Closing ``*``, ``_``, backtick, ``)`` and ``]`` are
    therefore consumed first.
    """
    return [
        " ".join(s.split()) for s in re.split(r"(?<=[.!?])[*_`)\]]*\s+|\n\n", text) if s.strip()
    ]


#: Split on sentence boundaries, requiring the next sentence to open with a
#: capital, a backtick, or an emphasis marker. That keeps `CONTEXT.md`,
#: `architecture_watchlist.files` and `code-quality`-style references intact,
#: since each continues in lower case.
SENTENCE_BREAK = re.compile(r"(?<=[.!?])\s+(?=[A-Z`*(])")


def sentences_on_break(text: str) -> list[str]:
    """``text`` split on :data:`SENTENCE_BREAK`, stripped, empties dropped.

    The stricter of the two splitters here: it will not break before a lower-case
    continuation, which is what keeps a back-ticked path from ending a sentence.
    Its callers assert over units that routinely contain such references.
    """
    return [s.strip() for s in SENTENCE_BREAK.split(text.strip()) if s.strip()]


def units(text: str) -> str:
    """``text`` re-joined one :func:`sentences` unit per paragraph.

    Loss-free for every predicate that runs over ``sentences`` units, because
    ``sentences`` already normalizes whitespace inside a unit. What it buys is
    **wrap-insensitivity**: a control anchored on a hard-wrapped phrase stops
    landing the moment the paragraph is re-wrapped at another column width, and
    a re-wrap must not read as a finding. Call it on a section body, never on the
    whole file — :func:`section` needs its headers on lines of their own.
    """
    return "\n\n".join(sentences(text))


def instruction_units(text: str) -> list[str]:
    """``text`` split into instruction units: paragraphs, list items, steps.

    The unit has to be **narrower than the file**. ``commands/propose.md`` names
    ``spec-authoring`` three times in prose that has nothing to do with filing,
    so a file-wide pointer check passes there without a pointer ever being
    written. It also has to be **wider than the line**: every filing instruction
    in the tree wraps, and ``commands/build.md``'s DEFER bullet carries its verb
    on one line and its object on the next.
    """
    collected: list[list[str]] = []
    current: list[str] = []
    starts_a_unit = re.compile(r"\s*(?:[-*+]\s|\d+\.\s|#{1,6}\s)")
    for line in text.splitlines():
        if current and (not line.strip() or starts_a_unit.match(line)):
            collected.append(current)
            current = []
        if line.strip():
            current.append(line)
    if current:
        collected.append(current)
    return [" ".join(" ".join(unit).split()) for unit in collected]


# ---------------------------------------------------------------------------
# Emphasis and negation — what an anchored predicate has to reach across
# ---------------------------------------------------------------------------

#: Emphasis, stripped before any *anchored* predicate runs: this tree bolds its
#: rules, so ``**stops**`` puts a ``*`` between the verb and the words that
#: release it, and a "verb, then up to N words" anchor never crosses it.
#: **Asterisks only** — ``_`` emphasis is unused here and ``certified_tree`` is
#: not, and splitting one identifier into two tokens spends two of an anchor's
#: gap allowance on a single word. Both halves measured: the first let
#: ``**stops** only when the operator asks`` read as unconditional, the second
#: let ``Comparing `HEAD^{tree}` to `certified_tree` is optional`` escape.
EMPHASIS = re.compile(r"\*+")

#: Verbs that **block** whatever follows them. A negation landing on one of
#: these states the *opposite* of the rule it appears to state: *"does not
#: preclude proceeding"*, *"does not block integration"* and *"does not forbid
#: writing"* each read to a negation-then-verb anchor as the prohibition intact,
#: while granting exactly what the prohibition forbids. Measured, one sentence at
#: a time, against the real file: each of those three left the whole module at
#: **25 passed**. So the gap a negation may reach across excludes them — a
#: negation whose object is a blocking verb governs the blocking, not the verb
#: beyond it, and the predicate must decline to treat the occurrence as covered.
#:
#: ``fail`` and ``hesitat`` are here for the double negation (*"never fails to
#: proceed"*), which is the same false converse reached by a different idiom.
#: Prefixes, not whole words: ``preclud`` covers *precludes/precluding*, ``rul``
#: covers *rule out/rules out*.
BLOCKING_VERBS = (
    r"preclud|prevent|block|forbid|prohibit|bar|stop|halt|refus|restrict|"
    r"impede|hinder|obstruct|disallow|deter|rul|fail|hesitat"
)

#: The gap between a negation and the verb it governs: up to two words, none of
#: them a blocking verb. Two is #354's measured bound — every legitimate spelling
#: here keeps them adjacent or within two words (*"never proceeds"*, *"No one
#: writes"*, *"never integrate"*, *"refusal to integrate"*), and a negation
#: further off governs something else.
#:
#: **What this does not catch, measured rather than assumed.** Eighteen further
#: grant-shaped wordings were spliced into the real file one at a time, and the
#: line falls in a describable place:
#:
#: *Caught.* A grant whose blocking word is a noun or an idiom wider than the gap
#: — *"is no bar to proceeding"*, *"does not stand in the way of proceeding"*,
#: *"Nothing here prevents proceeding"*, *"is not a reason to withhold
#: proceeding"* — matches **no** negation at all, so the occurrence stays
#: uncovered and the sweep flags it. That is the fail-closed side, and it is why
#: the exclusion only has to rescue the cases where a negation *does* match.
#:
#: *Escapes.* **An outer negation over a well-formed inner prohibition** — *"It
#: is not true that no one writes an as-built record on a `trivial` run"*,
#: *"There is no rule that a mismatch must not be integrated"*, *"A thin design
#: is not a reason the run cannot proceed"*. The inner clause is exactly the rule
#: these predicates look for, spelled correctly, with a clean gap; the grant
#: lives in the matrix clause, which no token-window anchor can reach. All three
#: were measured escaping all three predicates. It is a different class from the
#: one fixed there — sentential negation scope, not a verb inside a gap — and it
#: is **not** closed. Closing it needs clause structure, not a wider window, so
#: it is recorded here at its measured size rather than papered over.
NEGATION_GAP = rf"(?:\s+(?!(?:{BLOCKING_VERBS})\w*\b)\w+){{0,2}}"


# ---------------------------------------------------------------------------
# The filing rubric — its home, and the pointer that delegates to it
# ---------------------------------------------------------------------------

#: The assurance vocabulary — its one remaining home. Imported from
#: ``harness.assurance`` until #435 deleted the package; ADR 0015 keeps the
#: levels and the namespace, which are tracker labels a filer applies rather
#: than runtime machinery.
ASSURANCE_LEVELS = ("trivial", "simple", "complex")
ASSURANCE_LABEL_PREFIX = "assurance:"

#: The one home of the filing-time rubric.
RUBRIC_HOME = "skills/spec-authoring/SKILL.md"
#: The rubric's subsection title — what a pointer has to name to be a pointer.
RUBRIC_SECTION_TITLE = "Choosing assurance"
#: The backend-neutral contract that carries assurance as input and postcondition.
TRACKER_SKILL = "skills/tracker/SKILL.md"
GITHUB_SKILL = "skills/github-issues/SKILL.md"
LINEAR_SKILL = "skills/linear/SKILL.md"

ASSURANCE = re.compile(r"\bassurance\b", re.IGNORECASE)
#: The quantifier, **anchored to the noun it governs**. A bare `exactly one`
#: check would be satisfied by any of the four unrelated "exactly one"s already
#: in the tree; a sentence-wide conjunction with `assurance` would be satisfied
#: by a sentence that pins the count of something else entirely.
EXACTLY_ONE = re.compile(
    r"\bexactly one\b[^.]{0,40}?\bassurance\b|\bassurance\b[^.]{0,80}?\bexactly one\b",
    re.IGNORECASE,
)

#: A pointer names **both** the rubric's home skill and its subsection. Naming
#: the skill alone is not enough: `commands/start.md` and `commands/propose.md`
#: both already name `spec-authoring` in prose that says nothing about choosing
#: a level, so a bare-skill check passes on the pre-change tree.
POINTS_AT_THE_RUBRIC = re.compile(
    rf"`spec-authoring`[^.]{{0,120}}?{RUBRIC_SECTION_TITLE}"
    rf"|{RUBRIC_SECTION_TITLE}[^.]{{0,120}}?`spec-authoring`",
    re.IGNORECASE,
)


def delegates_the_level_choice(unit: str) -> bool:
    """Does this instruction delegate the level choice to the rubric's one home?"""
    return bool(POINTS_AT_THE_RUBRIC.search(unit))


#: Prose that instructs an agent to *file an issue* — the three spellings the
#: tree actually uses, lifted from it rather than invented.
FILES_AN_ISSUE = re.compile(
    r"`tracker\.create`"
    r"|(?:creat\w+|file[sd]?)\b[^.]{0,120}?through (?:the )?`tracker`"
    r"|`tracker` skill'?s `create`",
    re.IGNORECASE,
)


def filing_units(text: str) -> list[str]:
    """The instruction units of ``text`` that tell an agent to file an issue."""
    return [unit for unit in instruction_units(text) if FILES_AN_ISSUE.search(unit)]


def states_an_incomplete_filing(text: str) -> list[str]:
    """Sentences naming the incomplete-filing outcome and what to do with it.

    AC-6's failure shape has to reach the **provider**, not only the protocol.
    The protocol can say a filing is incomplete all it likes; the recipe an agent
    actually follows is where the behaviour either happens or does not. Both
    provider skills are checked with this one predicate rather than one re-spelled
    per backend.
    """
    return [
        sentence
        for sentence in sentences(text)
        if re.search(r"\bincomplete\b", sentence, re.IGNORECASE)
        and re.search(r"\bstop\b|\bidentifier\b|\bURL\b", sentence, re.IGNORECASE)
    ]


# ---------------------------------------------------------------------------
# Anchored readers over particular documents, shared by more than one guard
# ---------------------------------------------------------------------------

PROPOSAL_STATUS = re.compile(r"^status:\s*(?P<status>[a-z][a-z-]*)\s*(?:#.*)?$", re.MULTILINE)


def proposal_status(text: str) -> str:
    """The ``status:`` a proposal's frontmatter declares.

    Raises on a proposal with no parseable status: a proposal that declares
    nothing must not read as a proposal that declares something valid.
    """
    match = PROPOSAL_STATUS.search(text)
    if match is None:
        raise AssertionError("no parseable 'status:' line in this proposal's frontmatter")
    return match.group("status")


#: The step of `/assess` that files findings — two guards read different
#: paragraphs of it.
ASSESS_STEP_HEADER = "### 2. File the findings"


def assess_step_two() -> str:
    """The body of the ``### 2. File the findings`` step, header to next ``### ``.

    One slicer, so the guards reading different paragraphs of the step cannot
    disagree about where the step ends.
    """
    text = ASSESS.read_text()
    m = re.search(rf"^{re.escape(ASSESS_STEP_HEADER)}\b.*$", text, re.MULTILINE)
    assert m, f"missing step header {ASSESS_STEP_HEADER!r}"
    rest = text[m.end() :]
    end = re.search(r"^#{2,3} ", rest, re.MULTILINE)
    return rest[: end.start()] if end else rest


def obligations_section() -> str:
    """``review-discipline``'s ``## Reviewer obligations`` section.

    One slicer, so the guards reading the record gate and the ordering bullet
    cannot disagree about where the obligations begin and end.
    """
    text = REVIEW_DISCIPLINE.read_text(encoding="utf-8")
    start = text.find("## Reviewer obligations")
    assert start != -1, "review-discipline must have a Reviewer obligations section"
    end = text.find("## On a FAIL", start)
    assert end != -1, "review-discipline must have an 'On a FAIL' section after obligations"
    return text[start:end]


def obligation_bullets() -> list[str]:
    """The section's top-level ``- **`` bullets, one string each.

    The text unit is part of the predicate: the obligations are separate rules,
    and a predicate read over the whole section lets a term from one bullet
    satisfy a claim about another.
    """
    bullets: list[str] = []
    current: list[str] = []
    for line in obligations_section().splitlines():
        if line.startswith("- **"):
            if current:
                bullets.append("\n".join(current).strip())
            current = [line]
        elif current:
            current.append(line)
    if current:
        bullets.append("\n".join(current).strip())
    return bullets


def diff_shape_checks_text() -> str:
    return DIFF_SHAPE_CHECKS.read_text(encoding="utf-8")


def stage_two(text: str) -> str:
    """The ``### Stage 2`` body, to the next level-2 heading after it.

    The terminator was the literal ``## Severity`` until #455 retired the
    severity scale and renamed that section. Naming the *next* heading of the
    enclosing level rather than one particular title is what keeps six guards
    from breaking again the next time the section after Stage 2 is renamed —
    and it is not a widening: ``### Stage 2`` is a level-3 heading inside it, so
    the slice ends in exactly the same place. Both anchors still fail loudly
    when they resolve to nothing, which is the property that matters.
    """
    start = text.index("### Stage 2")
    # Past the heading's own line. ``^## `` cannot match ``### Stage 2`` at any
    # offset: the third character is a hash rather than a space, and ``^`` under
    # MULTILINE anchors only at a line start, so no interior offset is even a
    # candidate — measured, not assumed. Skipping the line is therefore a bound
    # on the *next* heading style rather than a repair of this one: it keeps the
    # search from ever being asked about the anchor line, so a level-2 anchor
    # would not resolve to offset zero and hand every assertion below an empty
    # slice, which reads as an absent bullet rather than as a broken slicer.
    after = text.index("\n", start) + 1
    end = re.search(r"^## ", text[after:], re.MULTILINE)
    assert end, (
        "`skills/review-discipline/references/diff-shape-checks.md` has no "
        "level-2 heading after `### Stage 2` — the slice every guard below "
        "reads would run to the end of the file"
    )
    return text[start : after + end.start()]


def stage_two_bullet(text: str, title: str) -> str:
    """The Stage-2 ``- **<title>**`` bullet, sliced to the next bullet or heading.

    The window is the predicate: a bullet-wide term set read over the whole
    ``### Stage 2`` body would be satisfied by any of the fourteen neighbouring
    rules, which is the over-wide unit ``craft.md`` → *The text unit is part of
    the predicate* names. Anchoring on the **title** rather than on a
    neighbour's position also keeps the slice correct when a bullet is inserted
    (``craft.md`` → *An ordinal reference into an enumeration is invalidated by
    a correct insertion*).
    """
    body = stage_two(text)
    m = re.search(rf"^- \*\*{re.escape(title)}\*\*", body, re.MULTILINE)
    assert m, (
        f"`skills/review-discipline/references/diff-shape-checks.md` Stage 2 has no "
        f"`- **{title}**` bullet — the anchor every assertion below reads is gone"
    )
    rest = body[m.start() :]
    nxt = re.search(r"^(?:- \*\*|#{2,3} )", rest[1:], re.MULTILINE)
    return rest[: nxt.start() + 1] if nxt else rest


def review_watchlist_bullet(text: str) -> str:
    """The Stage-2 ``- **Architecture watchlist**`` bullet, to the next bullet/heading."""
    m = re.search(r"^- \*\*Architecture watchlist\*\*", text, re.MULTILINE)
    assert m, (
        "review-discipline Stage 2 has no '- **Architecture watchlist**' check (CAL-815 AC-3)."
    )
    rest = text[m.end() :]
    end = re.search(r"^(?:- \*\*|## |### )", rest, re.MULTILINE)
    return rest[: end.start()] if end else rest


PART_B = "## Part B — Structure"
THIRD_STRIKE_HEADING = "### Extract on the third strike"


def third_strike_section() -> str:
    """``### Extract on the third strike``, sliced from inside ``## Part B``.

    The two calls are nested so Part B membership lives in the anchor instead of
    a second test.
    """
    text = CODE_QUALITY.read_text(encoding="utf-8")
    return section(section(text, PART_B), THIRD_STRIKE_HEADING)


def admission_paragraph() -> str:
    """The one paragraph in that section stating the admission trigger.

    Selected by content, never by index: an ordinal into the section is
    invalidated by a correct insertion (``craft.md`` → *An ordinal reference
    into an enumeration is invalidated by a correct insertion*), and the section
    has already grown a paragraph once (#231's second-copy rule).
    """
    paragraphs = [block.strip() for block in third_strike_section().split("\n\n") if block.strip()]
    hits = [p for p in paragraphs if re.search(r"\badmission\b", p, re.IGNORECASE)]
    assert hits, (
        f"no paragraph in {THIRD_STRIKE_HEADING!r} states the mirrors/duplicates/"
        "kept-in-sync comment as an explicit *admission* of duplication (CAL-800 AC-1)."
    )
    assert len(hits) == 1, (
        f"{THIRD_STRIKE_HEADING!r} states the admission trigger across {len(hits)} "
        "paragraphs; this guard's window can no longer tell which one it is pinning, "
        "and a term in one would satisfy an assertion about the other."
    )
    return hits[0]
