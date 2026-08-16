"""#454 — the published guidance surface is mechanically well-formed.

Four defects shipped into the installed surface at once, and each is a *mechanical*
property of the bytes — no regex has to read meaning to see any of them, so they sit
squarely on the tests' side of ADR 0016's line (structure and negative space are the
guard's; whether the prose says the right thing is the reviewer's).

The occurrences these guards cite (`code-quality` Part C → *A new guard cites the
occurrence it prevents*), all found by the full-system review of 2026-08-16 and all
live on ``dev`` @ ``2408d7a``:

* **AC-1** — ``skills/tracker/SKILL.md:87``: a paragraph interposed between a table's
  header block and its last two rows, so ``| **Todo** |`` and ``| **Backlog** |``
  rendered as literal pipes in every consuming repo.
* **AC-2** — ``skills/code-quality/references/specialized-verification.md:12``: a
  heading with no body at all, whose content lives in the parent skill.
* **AC-3** — ``skills/review-discipline/references/diff-shape-checks.md:23`` and
  ``skills/tracker/SKILL.md:15``: template-brace syntax shipped to consumers
  unexpanded.
* **AC-4** — ``README.md:61``: "roughly 1,300 tests" against a gate that collects
  nothing like that number — 1,709 on the tree this module ships in, measured at
  review. (The ticket's own grounding said ~1,850, which was true of no tree on this
  branch; that is the class one level up, and the reason the fix removes the claim
  rather than refreshing it.) The false-MEASURED-claim class
  ``specs/features/guidance-system.md`` documents about itself.

Every sweep here derives its subject set from ``registry.yaml``'s ``files:`` block
rather than naming files (`code-quality` references →
*A guard derives its subjects; it does not list them*), and none of them carries an
allowlist or an exemption token — an exemption inside a sweep needs its own placement
guard or the sweep is opt-out prose (#449, recurred in #453), so each of the two AC-3
sites was reworded to remove the ambiguity at the subject instead.

**Fenced code is excluded by a line-state toggle, not by a span regex.** These are
line-oriented structural guards — a violation is reported *at a line number* — so the
fence filter has to answer "is this line inside a fence" directly. The toggle fires
only on a line whose first non-whitespace characters are the fence marker, which is
the anchoring `craft.md` → *A paired delimiter can be counterfeited by prose that
mentions it* prescribes: a sentence naming a fence mid-clause must not open one and
swallow the prose after it. :func:`test_fence_filter_is_line_anchored` is that control.
"""

from __future__ import annotations

import re
from pathlib import Path

# ``tests/unit/test_*.py`` → ``parents[2]`` is the repo (or worktree) root.
_REPO_ROOT = Path(__file__).resolve().parents[2]
_REGISTRY = _REPO_ROOT / "registry.yaml"

#: A member of ``registry.yaml``'s ``files:`` block — a two-space-indented mapping key
#: naming a markdown path. The same shape ``hooks/guidance-freshness.js`` calls
#: ``registryMember``.
_FILES_ENTRY = re.compile(r"^\s{2}(\S+\.md):\s*\{", re.M)

#: A markdown table separator: a row of nothing but pipes, dashes, colons and spaces,
#: carrying at least one dash.
_SEPARATOR_ROW = re.compile(r"^\s*\|[-:|\s]*-[-:|\s]*\|\s*$")

#: An ATX heading below the document title — ``##`` through ``######``.
_HEADING = re.compile(r"^(#{2,6})\s+(\S.*?)\s*$")

#: A template placeholder: a brace pair with no nested brace and no line break.
_PLACEHOLDER = re.compile(r"\{[^{}\n]*\}")

#: A digit group adjacent to the word "test"/"tests", in either order. The gap is
#: non-word characters only, so an intervening word breaks the adjacency.
_COUNT_BESIDE_TESTS = re.compile(r"\btests?\b\W{0,4}\d[\d,]*|\d[\d,]*\W{0,4}\btests?\b", re.I)


def _registered_markdown() -> list[str]:
    """Every markdown path the registry's ``files:`` block installs, repo-relative.

    Scoped to ``files:`` — the block whose members are copied into a consuming repo.
    ``meta:`` (``BOOTSTRAP.md``, the registry itself) is version-stamped but never
    installed, so it is not published prose.
    """
    src = _REGISTRY.read_text()
    start = src.index("\nfiles:\n")
    end = src.index("\nmeta:\n", start)
    return sorted(_FILES_ENTRY.findall(src[start:end]))


def _registered_skill_prose() -> list[str]:
    """Registered markdown under ``skills/`` — SKILL files and their references."""
    return [rel for rel in _registered_markdown() if rel.startswith("skills/")]


def _line_states(text: str) -> list[tuple[int, str, bool]]:
    """``(1-based line number, line, is-fenced)`` for every line of ``text``.

    A line whose first non-whitespace run is ``` toggles the fence state, and counts
    as fenced itself. Prose that merely mentions the marker mid-sentence never
    toggles, which is the whole point (see the module docstring).
    """
    states: list[tuple[int, str, bool]] = []
    fenced = False
    for number, line in enumerate(text.splitlines(), start=1):
        if line.lstrip().startswith("```"):
            fenced = not fenced
            states.append((number, line, True))
            continue
        states.append((number, line, fenced))
    return states


def _unfenced_lines(text: str) -> list[tuple[int, str]]:
    """``(1-based line number, line)`` for every line outside a fenced code block."""
    return [(number, line) for number, line, fenced in _line_states(text) if not fenced]


def _registered_reference_files() -> list[str]:
    """Registered ``skills/<skill>/references/<name>.md`` — the reference-file surface."""
    return [
        rel
        for rel in _registered_markdown()
        if re.fullmatch(r"skills/[^/]+/references/[^/]+\.md", rel)
    ]


def test_registry_derivation_is_live() -> None:
    """The subject source parses, and yields the real installed markdown surface.

    The non-vacuity floor for all three registry-derived sweeps below
    (`craft.md` → *The empty subject set*). Membership is pinned, never length: a
    hardcoded count is the very drift these guards exist to remove. Each anchor names
    a file whose defect this change repairs, so a rename announces itself here rather
    than silently emptying a sweep.
    """
    registered = _registered_markdown()
    assert "skills/tracker/SKILL.md" in registered
    assert "skills/code-quality/references/specialized-verification.md" in registered
    assert "skills/review-discipline/references/diff-shape-checks.md" in registered
    # ``meta:`` is stamped but not installed — it must not leak into the subject set.
    assert "BOOTSTRAP.md" not in registered

    prose = _registered_skill_prose()
    assert "skills/tracker/SKILL.md" in prose
    # A reference file is skill prose too, and this is the assertion that says so.
    # AC-3's second live leak sat in a reference file, so a subject set narrowed to
    # ``SKILL.md`` alone would still carry both anchors above, still hold the
    # all-under-``skills/`` invariant below, and still report green over the very
    # surface the sweep was written for. Review measured that narrowing as a live
    # survivor before this line existed.
    assert "skills/review-discipline/references/diff-shape-checks.md" in prose
    assert not [rel for rel in prose if not rel.startswith("skills/")]

    references = _registered_reference_files()
    assert "skills/code-quality/references/specialized-verification.md" in references
    assert "skills/review-discipline/references/craft.md" in references
    # A SKILL file is not a reference file — the narrower sweep must stay narrow.
    assert "skills/tracker/SKILL.md" not in references


def test_fence_filter_is_line_anchored() -> None:
    """A mid-sentence fence mention does not open a fence and swallow the prose.

    `craft.md` → *A paired delimiter can be counterfeited by prose that mentions it*:
    an unanchored opener eats every line through to the next real fence, so the sweep
    reports zero offenders over text it never read. The first case is that shape; the
    second and third prove the filter still removes a real fence, plain and indented.
    """
    mentioned = "the one ```python block below is the reference\nkept\n"
    assert [line for _, line in _unfenced_lines(mentioned)] == [
        "the one ```python block below is the reference",
        "kept",
    ]

    plain = "before\n```\nhidden\n```\nafter\n"
    assert [line for _, line in _unfenced_lines(plain)] == ["before", "after"]

    indented = "before\n  ```\n  hidden\n  ```\nafter\n"
    assert [line for _, line in _unfenced_lines(indented)] == ["before", "after"]

    # Line numbers survive the filter — a violation is reported at its real line.
    assert _unfenced_lines(plain)[-1][0] == 5


def _orphan_table_rows(text: str) -> list[int]:
    """Line numbers of ``|``-rows that open a table without being a header.

    A table row whose predecessor is not itself a row is the *first* row of a table,
    and the first row of a well-formed markdown table is its header — so the line
    after it must be the ``| --- | --- |`` separator. A row that opens a table and is
    not followed by a separator is severed from the header above it: the renderer
    prints it as literal pipes.

    **Adjacency is physical, not positional in the filtered list.** The neighbours are
    compared by *line number*, not by index into ``_unfenced_lines``. Taking the
    filtered neighbour instead makes the two halves of a table severed by a fenced
    code block adjacent — the fence lines are gone from the list — so the renderer
    breaks the table and the sweep sees a contiguous one. Review proved that gap by
    paired splice: a paragraph and a fenced block spliced at the same offset of
    ``skills/tracker/SKILL.md``, the paragraph flagged and the fence silently not.
    """
    lines = _unfenced_lines(text)
    row_numbers = {number for number, line in lines if line.lstrip().startswith("|")}
    violations: list[int] = []
    for index, (number, _line) in enumerate(lines):
        if number not in row_numbers:
            continue
        previous = lines[index - 1] if index > 0 else None
        if previous is not None and previous[0] == number - 1 and previous[0] in row_numbers:
            continue
        following = ""
        if index + 1 < len(lines) and lines[index + 1][0] == number + 1:
            following = lines[index + 1][1]
        if not _SEPARATOR_ROW.match(following):
            violations.append(number)
    return violations


def test_orphan_table_detector_reads_position_not_content() -> None:
    """The detector distinguishes a severed row from a well-formed table.

    Fed the pre-fix shape verbatim (a paragraph interposed between a table's header
    block and its remaining rows) it flags the row that lost its header; fed the same
    table intact it flags nothing. `craft.md` → *A positive control must exercise the
    predicate, not re-implement it*: the control feeds the production predicate, and
    the two samples differ only in where the paragraph sits.
    """
    severed = (
        "| Signal | Meaning |\n"
        "|---|---|\n"
        "| **Assignee** | held |\n"
        "\n"
        "There are exactly two hold labels.\n"
        "| **Todo** | confirmed work |\n"
        "| **Backlog** | triage |\n"
    )
    assert _orphan_table_rows(severed) == [6]

    intact = (
        "| Signal | Meaning |\n"
        "|---|---|\n"
        "| **Assignee** | held |\n"
        "| **Todo** | confirmed work |\n"
        "| **Backlog** | triage |\n"
        "\n"
        "There are exactly two hold labels.\n"
    )
    assert _orphan_table_rows(intact) == []

    # A fenced block severs a table exactly as a paragraph does, and it is the shape
    # the fence filter can hide: strip the fence lines and the two halves become
    # neighbours in the filtered list. Only physical adjacency separates this sample
    # from ``intact`` above.
    fence_severed = (
        "| Signal | Meaning |\n"
        "|---|---|\n"
        "| **Assignee** | held |\n"
        "```sh\n"
        "gh issue list\n"
        "```\n"
        "| **Todo** | confirmed work |\n"
        "| **Backlog** | triage |\n"
    )
    assert _orphan_table_rows(fence_severed) == [7]


def test_no_registered_skill_prose_has_an_orphan_table_row() -> None:
    """No installed skill prose severs a table row from its header (AC-1).

    Cites ``skills/tracker/SKILL.md:87`` — the Signal table's ``| **Todo** |`` and
    ``| **Backlog** |`` rows, cut off from the header block at 80–84 by an interposed
    paragraph, and therefore rendered as literal pipes in every repo the surface is
    installed into.
    """
    violations: list[str] = []
    for rel in _registered_skill_prose():
        for number in _orphan_table_rows((_REPO_ROOT / rel).read_text()):
            violations.append(f"{rel}:{number}")

    assert not violations, (
        "a table row opens a table without a `| --- |` separator beneath it — it is "
        "severed from its header and renders as literal pipes. Move the interposed "
        "prose out of the table (#454):\n  " + "\n  ".join(violations)
    )


def _headings(text: str) -> list[tuple[int, int, int, str]]:
    """``(index into line states, line number, level, title)`` for each ``##``–``######``.

    Headings are read from unfenced lines only — a ``#`` comment inside a shell block
    is not a section.
    """
    found: list[tuple[int, int, int, str]] = []
    for index, (number, line, fenced) in enumerate(_line_states(text)):
        if fenced:
            continue
        match = _HEADING.match(line)
        if match:
            found.append((index, number, len(match.group(1)), match.group(2)))
    return found


def _empty_leaf_sections(text: str) -> list[tuple[int, str]]:
    """``(line number, title)`` for each heading that is a leaf with no content.

    A **leaf** is a heading whose next heading is at the same or a shallower level, or
    which has no next heading at all. A heading followed by a *deeper* one is a
    container: the subsections below it are its content, and flagging it would fail
    every legitimately nested document (``## Part C — Specialized verification``, and
    each of ``craft.md``'s six ``##`` families).

    Body emptiness is measured over **every** line between the two headings, fenced
    lines included — a section whose entire body is a code block has content.
    """
    states = _line_states(text)
    headings = _headings(text)
    violations: list[tuple[int, str]] = []
    for position, (index, number, level, title) in enumerate(headings):
        following = headings[position + 1] if position + 1 < len(headings) else None
        stop = following[0] if following else len(states)
        if any(states[j][1].strip() for j in range(index + 1, stop)):
            continue
        if following is not None and following[2] > level:
            continue
        violations.append((number, title))
    return violations


def test_empty_leaf_detector_spares_containers() -> None:
    """The detector separates a bodiless *container* from a bodiless *leaf*.

    The level comparison is the whole predicate, so it gets both directions. A
    heading immediately followed by a deeper heading is the normal shape of a nested
    document and must stay silent; the same heading followed by a *sibling* is the
    defect. The third case pins the tail: a bodiless heading at the end of a file has
    no next heading and is still a leaf.
    """
    container = "## Family\n### Entry\n\nBody.\n"
    assert _empty_leaf_sections(container) == []

    leaf = "## Family\n\n### First\n### Second\n\nBody.\n"
    assert _empty_leaf_sections(leaf) == [(3, "First")]

    trailing = "## Family\n\nBody.\n\n### Dangling\n"
    assert _empty_leaf_sections(trailing) == [(5, "Dangling")]

    # A body made entirely of fenced code is content, not emptiness.
    fenced_body = "### Recipe\n\n```sh\nls\n```\n\n### Next\n\nBody.\n"
    assert _empty_leaf_sections(fenced_body) == []


def test_no_registered_reference_file_has_an_empty_leaf_section() -> None:
    """No installed reference file carries a heading with nothing under it (AC-2).

    Cites ``skills/code-quality/references/specialized-verification.md:12`` —
    ``### A green suite is only evidence if its inputs are real``, which shipped with
    zero body and a sibling ``###`` directly beneath it. Its content lives in
    ``skills/code-quality/SKILL.md``; the heading was a stub that promised a section
    the file does not have.

    **Scoped to reference files, and the exclusion has one live subject.** Widening
    this sweep to every registered ``skills/`` file today fails on exactly one
    heading — ``skills/test-driven-development/SKILL.md`` →
    ``### REPEAT for the next criterion.``, where the heading *is* the content and a
    body would say the same words twice. That is the whole reason for the narrowing,
    and naming it here is what makes it a decision rather than a shrug; the scope is
    pinned in both directions by :func:`test_registry_derivation_is_live`, which
    asserts a ``SKILL.md`` is *not* a reference file.
    """
    violations: list[str] = []
    for rel in _registered_reference_files():
        for number, title in _empty_leaf_sections((_REPO_ROOT / rel).read_text()):
            violations.append(f"{rel}:{number} — {title}")

    assert not violations, (
        "a reference file carries a heading with no body and no subsections — it "
        "promises a section that is not there. Write the section or delete the "
        "heading (#454):\n  " + "\n  ".join(violations)
    )


def test_specialized_verification_lost_exactly_the_stub_heading() -> None:
    """AC-2's deletion removed one heading and nothing else.

    The did-not-delete-too-much floor `craft.md` requires beside any absence claim: a
    pure absence assertion passes just as happily on an emptied file. Membership is
    pinned, never a count — a count is satisfied forever by deleting one section and
    adding another (`craft.md` → *Floors decay into decoration*).

    The removed heading appears in the negative half; the six survivors are the file's
    heading list as it stood before #454, minus exactly that one. The section's real
    home is ``skills/code-quality/SKILL.md``, which the second assertion pins so the
    content cannot vanish from the tree along with the stub.
    """
    reference = _REPO_ROOT / "skills" / "code-quality" / "references"
    source = (reference / "specialized-verification.md").read_text()
    titles = [title for _, _, _, title in _headings(source)]

    assert titles == [
        "Part C — Specialized verification",
        "A security-contract test asserts the predicate, not the name",
        "A file over the hard limit is an auditable choice, not silent drift",
        "A guard derives its subjects; it does not list them",
        "Re-deriving what another layer owns is an auditable choice, not a default",
        "Narrowing a nullable is a whole-call-graph change, not a grep-and-replace",
    ]

    home = (_REPO_ROOT / "skills" / "code-quality" / "SKILL.md").read_text()
    assert "### A green suite is only evidence if its inputs are real" in home, (
        "the stub heading was deleted from the reference file on the grounds that its "
        "content lives in the core skill — if that home goes, the deletion becomes a "
        "content loss (#454)"
    )


def _placeholder_tokens(text: str) -> list[tuple[int, str]]:
    """``(line number, token)`` for every ``{…}`` brace token outside fenced code.

    **Inline code spans are deliberately not excluded.** Both live leaks sat inside
    backticks — ``` `{e.g. RELEASING.md}` ``` and ``` `github: { repo, project,
    status_field? }` ``` — so an inline-code exemption would have hidden the very
    defect this sweep exists to find. Fenced *blocks* are excluded because a fenced
    block in a skill is a code sample, where braces are the sample's own syntax.
    """
    found: list[tuple[int, str]] = []
    for number, line in _unfenced_lines(text):
        found.extend((number, token) for token in _PLACEHOLDER.findall(line))
    return found


def test_placeholder_detector_reads_inline_code_and_skips_fenced_blocks() -> None:
    """The detector sees a braced token inside backticks and ignores a fenced block.

    The first assertion is the one that matters: sparing inline code would have made
    this sweep vacuous against both real leaks, and an exemption inside a sweep needs
    its own placement guard or the sweep is opt-out prose (#449, recurred in #453).
    The samples are the pre-fix wordings verbatim (`craft.md` → *A positive control
    must exercise the predicate, not re-implement it*). The last case shows the fenced
    exclusion is a block exclusion, not a brace-anywhere exclusion.
    """
    assert _placeholder_tokens("this repo's is `{e.g. RELEASING.md}`") == [
        (1, "{e.g. RELEASING.md}")
    ]
    assert _placeholder_tokens("| `github: { repo, project, status_field? }` |") == [
        (1, "{ repo, project, status_field? }")
    ]
    assert _placeholder_tokens('```json\n{ "a": 1 }\n```\n') == []
    assert _placeholder_tokens('{ "a": 1 }\n') == [(1, '{ "a": 1 }')]


def test_no_registered_skill_prose_carries_a_template_placeholder() -> None:
    """No installed skill prose ships an unexpanded ``{…}`` placeholder (AC-3).

    Cites ``skills/review-discipline/references/diff-shape-checks.md:23``
    (``{e.g. RELEASING.md}``) and ``skills/tracker/SKILL.md:15``
    (``{ repo, project, status_field? }``) — template-brace syntax that reached
    consuming repos verbatim, where it reads as an instruction to substitute.

    Scoped to ``skills/`` on purpose. ``templates/`` uses exactly this syntax
    deliberately — ``templates/CONTEXT.template.md`` writes
    ``language: {e.g. Python 3.11 / TypeScript}`` — and that is the convention that
    leaked, so the sweep must not be widened onto the surface it came from.
    """
    violations: list[str] = []
    for rel in _registered_skill_prose():
        for number, token in _placeholder_tokens((_REPO_ROOT / rel).read_text()):
            violations.append(f"{rel}:{number} — {token}")

    assert not violations, (
        "installed skill prose carries template-brace syntax; a consuming repo reads "
        "it as a placeholder to substitute. Write it as real prose (#454):\n  "
        + "\n  ".join(violations)
    )


def test_the_template_convention_this_sweep_excludes_is_still_live() -> None:
    """``templates/`` really does use ``{…}`` deliberately — the scope choice is real.

    The pair to the scoping decision above. If the template surface ever stopped
    using brace placeholders, the ``skills/``-only scope would be an unexamined
    narrowing rather than a justified one, and this sweep should widen. The anchor is
    the exact convention the two leaks copied, so a change of convention names itself
    here (`craft.md` → *The conditional guard whose skip reads as green*).
    """
    template = (_REPO_ROOT / "templates" / "CONTEXT.template.md").read_text()
    assert _placeholder_tokens(template), (
        "templates/CONTEXT.template.md no longer carries a {…} placeholder — the "
        "reason this sweep is scoped to skills/ may have expired (#454)"
    )


def _test_counts(text: str) -> list[tuple[int, str]]:
    """``(line number, phrase)`` for every digit group standing next to "test(s)".

    Either order — "1,300 tests" and "tests … 1,300" both count — because the claim
    is the adjacency, not the word order. The window is bounded to non-word
    characters, so ``tests/ — roughly 1,300`` is *not* a match on the ``tests/`` path
    (the words between them break the run) while ``roughly 1,300 tests`` is.
    """
    return [
        (number, match.group(0))
        for number, line in _unfenced_lines(text)
        for match in _COUNT_BESIDE_TESTS.finditer(line)
    ]


def test_count_detector_reads_adjacency_in_both_orders() -> None:
    """The detector catches a stated count and leaves an unquantified sentence alone.

    The first sample is ``README.md``'s pre-fix wording verbatim; the second is the
    same claim written the other way round, so a fix that merely reorders the sentence
    does not slip through. The negatives are the two shapes the README still needs:
    a bare ``tests/`` path near an unrelated number, and prose that names no count.

    The last assertion is the **widening** direction of the ``\\W{0,4}`` window, which
    the narrowing assertions above cannot see: the two operands sit in different table
    cells with an empty cell between them, which is not adjacency and must not read as
    a stated count. Without it the bound is pinned in one direction only — review
    measured a widened window as a live survivor.
    """
    assert _test_counts("under `tests/` — roughly 1,300 tests, most of which") == [
        (1, "1,300 tests")
    ]
    assert _test_counts("the suite counts tests: 1850 of them") == [(1, "tests: 1850")]
    assert _test_counts("Python 3.11 lives beside `tests/`") == []
    assert _test_counts("the guards, under `tests/`, read the tracked tree") == []
    assert _test_counts("| tests | | 1,300 |") == []


def test_readme_states_no_specific_test_count() -> None:
    """``README.md`` states no specific test count (AC-4).

    Cites ``README.md:61`` — "roughly 1,300 tests" against a gate whose real figure
    was neither that nor the ~1,850 the ticket asserted: 1,709 collected on the tree
    this module ships in. A number written into prose that nothing measures decays the
    day after it is written, and the ticket's own restatement of it decayed before the
    fix was built. So the fix is to stop stating one, not to state a fresher one, and
    this guard deliberately pins **no** count rather than pinning the README to what
    the gate collects (a pin would have to be re-measured on every ticket that adds a
    test, which is the same rot with more ceremony).
    """
    readme = _REPO_ROOT / "README.md"
    violations = [
        f"README.md:{number} — {phrase}"
        for number, phrase in _test_counts(readme.read_text())
    ]

    assert not violations, (
        "README.md states a specific test count. It is measured on the day it is "
        "written and wrong the day after — describe the suite without a number "
        "(#454):\n  " + "\n  ".join(violations)
    )
