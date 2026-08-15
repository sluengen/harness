"""#354 — every surface that files an issue delegates the level choice to the rubric.

The companion to :mod:`tests.unit.test_assurance_filing_rubric`, which owns the
rubric itself, its two rules' polarity, and the backend-neutral ``create``
contract. This module owns the **reach**: which files actually file an issue,
that each of them points at the one rubric instead of restating it, that both
provider recipes map the chosen label while keeping explicit Todo placement, and
that every registered file's version stamp and registry entry moved in step.

The two split at 750 lines rather than by taste, and the seam is the natural one:
predicates and the rules they measure on one side, the derived corpus and the
per-file sweeps on the other. Every predicate this module uses is **imported**
from the rubric module — a control or a sweep that re-implemented a predicate
would stop protecting the one the other file's assertions call (#179/#327).

**AC-4's subject set is derived, never listed.** ``registry.yaml``'s ``files:``
block is the source, because a hand-maintained list of filing surfaces is the
same rot this ticket removes. The ticket named five surfaces; the derivation
finds seven. ``commands/build.md`` — the DEFER path — is the one nobody
enumerated, and it is named in the membership floor precisely because it is the
evidence the derivation earns its keep over a hand-list.
"""

from __future__ import annotations

import re
from collections.abc import Callable

import pytest

from tests.unit.test_assurance_filing_rubric import (
    _ASSURANCE,
    _EXACTLY_ONE,
    _GITHUB_SKILL,
    _LINEAR_SKILL,
    _REGISTRY,
    _RUBRIC_HOME,
    _RUBRIC_SECTION_TITLE,
    _TRACKER_SKILL,
    ASSURANCE_LABEL_PREFIX,
    ASSURANCE_LEVELS,
    _delegates_the_level_choice,
    _read,
    _registered_markdown,
    _section,
    _sentences,
    _states_an_incomplete_filing,
)

# ---------------------------------------------------------------------------
# AC-4 — the filing-surface set is derived, not hand-listed
# ---------------------------------------------------------------------------

#: Prose that instructs an agent to *file an issue* — the three spellings the
#: tree actually uses, lifted from it rather than invented.
_FILES_AN_ISSUE = re.compile(
    r"`tracker\.create`"
    r"|(?:creat\w+|file[sd]?)\b[^.]{0,120}?through (?:the )?`tracker`"
    r"|`tracker` skill'?s `create`",
    re.IGNORECASE,
)


def _instruction_units(text: str) -> list[str]:
    """``text`` split into instruction units: paragraphs, list items, steps.

    The unit has to be **narrower than the file**. ``commands/propose.md`` names
    ``spec-authoring`` three times in prose that has nothing to do with filing,
    so a file-wide pointer check passes there without a pointer ever being
    written. It also has to be **wider than the line**: every filing instruction
    in the tree wraps, and ``commands/build.md``'s DEFER bullet carries its verb
    on one line and its object on the next.
    """
    units: list[list[str]] = []
    current: list[str] = []
    starts_a_unit = re.compile(r"\s*(?:[-*+]\s|\d+\.\s|#{1,6}\s)")
    for line in text.splitlines():
        if current and (not line.strip() or starts_a_unit.match(line)):
            units.append(current)
            current = []
        if line.strip():
            current.append(line)
    if current:
        units.append(current)
    return [" ".join(" ".join(unit).split()) for unit in units]


def _filing_units(text: str) -> list[str]:
    """The instruction units of ``text`` that tell an agent to file an issue."""
    return [unit for unit in _instruction_units(text) if _FILES_AN_ISSUE.search(unit)]


def _filing_surfaces() -> list[str]:
    """Registered prose that instructs an agent to file an issue.

    Derived from ``registry.yaml``'s ``files:`` block — what a consumer actually
    receives — because a hand-maintained list of filing surfaces is the same rot
    this ticket exists to remove. The ticket named five surfaces; the derivation
    finds seven.
    """
    return [rel for rel in _registered_markdown() if _filing_units(_read(rel))]


#: The surfaces AC-4 names by hand, plus the ones the derivation adds. Named as a
#: **membership** floor, never as the subject set: the subject set is derived
#: above, and this list exists only so a narrowed derivation cannot read green.
#: `commands/build.md` is here because it is the surface the ticket's own author
#: did not know about — it is the evidence the derivation earns its keep, and
#: `commands/promote.md` is the same shape found later. The two
#: `commands/harness/*` members were dropped when #435 retired that namespace.
_KNOWN_FILING_SURFACES = (
    "commands/bug.md",
    "commands/tweak.md",
    "commands/propose.md",
    "commands/assess.md",
    "commands/promote.md",
    "commands/build.md",
)


def test_the_filing_surface_set_is_non_empty() -> None:
    """FLOOR 1. A derivation that narrowed to nothing passes every check below."""
    surfaces = _filing_surfaces()
    assert len(surfaces) >= 6, (
        f"only {len(surfaces)} filing surfaces derived from registry.yaml — the "
        f"per-surface pointer checks derive their subjects from this set, so a "
        f"broken derivation makes them all pass on an empty set (#354 AC-4)."
    )


@pytest.mark.parametrize("rel", _KNOWN_FILING_SURFACES, ids=lambda r: r)
def test_a_known_filing_surface_is_a_member(rel: str) -> None:
    """FLOOR 2. Membership, not cardinality — a swapped member keeps the count."""
    assert rel in _filing_surfaces(), (
        f"{rel} files an issue but is no longer found by the derived search — "
        f"the guard would silently stop covering it (#354 AC-4)."
    )


def test_the_contract_that_defines_create_is_not_a_filing_surface() -> None:
    """FLOOR 3. Discrimination: defining ``create`` is not filing an issue.

    Without this, a predicate matching every mention of ``tracker`` would look
    like a working derivation while collecting the protocol and both provider
    recipes — none of which files anything, and all of which would then be asked
    for a pointer they must not carry.
    """
    surfaces = _filing_surfaces()
    for rel in (_TRACKER_SKILL, _GITHUB_SKILL, _LINEAR_SKILL):
        assert rel not in surfaces, (
            f"{rel} was derived as a filing surface; it *defines* or *implements* "
            f"`create` rather than calling it (#354 AC-4)."
        )


def test_the_filing_predicate_discriminates() -> None:
    """FLOOR 4. The positive and negative controls, through the same predicate.

    The three positives are the real spellings, lifted verbatim from the tree
    before this change. The negative is ``agents/reviewer.md``'s *"create it"* —
    a create that is not a filing, and the shape a looser predicate swallows.
    """
    real_spellings = (
        "**Step 3 — file it.** Pass the title and UTF-8 body file to `tracker.create`, "
        "with any labels and mandatory initial Todo placement.",
        "- Create an issue per item in the breakdown through the `tracker` skill's "
        "`create` operation — which sets queue placement explicitly.",
        "- **DEFER:** create the out-of-scope follow-up through `tracker` with explicit\n"
        "  queue placement, then ship the independently reviewed tree.",
    )
    for sample in real_spellings:
        assert _filing_units(sample), (
            f"the filing predicate no longer matches a real spelling from the "
            f"tree: {sample[:70]!r} (#354 AC-4)."
        )

    not_a_filing = (
        "If the as-built record does not exist yet, create it. An explicit deferral must "
        "name the reason."
    )
    assert not _filing_units(not_a_filing), (
        "the filing predicate matches a `create` that files nothing — it would "
        "demand a rubric pointer from prose about writing a feature spec (#354)."
    )


@pytest.mark.parametrize("rel", _filing_surfaces(), ids=lambda r: r)
def test_every_filing_surface_delegates_the_level_choice(rel: str) -> None:
    """AC-2: the surface points at the rubric inside the instruction that files.

    Scoped to the filing instruction rather than the file, because three of these
    files already name ``spec-authoring`` elsewhere. A surface that restates the
    selection rules instead of pointing is caught by the exclusivity assertion
    below, not here.
    """
    units = _filing_units(_read(rel))
    assert any(_delegates_the_level_choice(unit) for unit in units), (
        f"{rel} files an issue without naming `spec-authoring` → "
        f"*{_RUBRIC_SECTION_TITLE}* in the instruction that files it. Every "
        f"filing surface delegates the level choice to the one rubric (#354 AC-2). "
        f"Filing instruction(s) found: {[u[:120] for u in units]}"
    )


#: Two surfaces the derived search does **not** find, named by hand. This is a
#: **list**, and it says so: neither file calls `create`, so no derivation over
#: filing instructions can reach them. Both are places where a level is *chosen*
#: rather than *passed*, which is exactly what AC-2 is about, so leaving them out
#: would let the rubric be restated at the two moments a filer actually reads.
_NAMED_WIDENINGS: dict[str, str] = {
    "templates/change.md": (
        "the form where the filer types the value — its `## Assurance` block is the field itself"
    ),
    "commands/start.md": (
        "step 5 chooses the level for a ticket filed without one, and restated "
        "the selection rules with no pointer"
    ),
}


@pytest.mark.parametrize("rel", sorted(_NAMED_WIDENINGS), ids=lambda r: r)
def test_a_named_widening_points_at_the_rubric(rel: str) -> None:
    """AC-2, widened by hand to the two surfaces that *choose* without filing."""
    assert _NAMED_WIDENINGS[rel].strip(), f"the widening for {rel} must state a reason"
    assert _delegates_the_level_choice(" ".join(_read(rel).split())), (
        f"{rel} does not name `spec-authoring` → *{_RUBRIC_SECTION_TITLE}*. "
        f"It is in scope because {_NAMED_WIDENINGS[rel]} (#354 AC-2)."
    )


def test_the_named_widenings_are_not_already_covered_by_the_derivation() -> None:
    """The widening must stay a widening — otherwise it is a duplicate subject.

    If one of these ever starts filing through `tracker.create`, the derived
    sweep covers it and the hand-named entry becomes a second, weaker assertion
    on the same file. This fails when that happens, so the list shrinks rather
    than rotting.
    """
    overlap = sorted(set(_NAMED_WIDENINGS) & set(_filing_surfaces()))
    assert not overlap, (
        f"{overlap} are now derived filing surfaces — drop them from "
        f"_NAMED_WIDENINGS so the derived sweep is their only guard (#354)."
    )


# ---------------------------------------------------------------------------
# AC-3 — both provider recipes map the label and preserve Todo placement
# ---------------------------------------------------------------------------


def _fenced_blocks(text: str) -> list[str]:
    return re.findall(r"```[^\n]*\n(.*?)```", text, re.S)


#: The label flag, with the level left as a **placeholder**. The prefix is
#: imported, not typed.
_GH_ASSURANCE_FLAG = re.compile(rf"--label\s+{re.escape(ASSURANCE_LABEL_PREFIX)}<level>")
#: A recipe that shipped a *fixed* level would apply the same assurance to every
#: issue the repo ever files — green against a namespace-only check.
_GH_FIXED_LEVEL = re.compile(
    "|".join(
        rf"--label\s+{re.escape(ASSURANCE_LABEL_PREFIX)}{re.escape(level)}\b"
        for level in ASSURANCE_LEVELS
    )
)


def test_the_github_create_recipe_carries_the_level_as_a_placeholder() -> None:
    """AC-3: the GitHub recipe maps the chosen level, and does not pick one."""
    create_fences = [
        block for block in _fenced_blocks(_github_create_recipe()) if "gh issue create" in block
    ]
    assert create_fences, f"{_GITHUB_SKILL} no longer documents `gh issue create` (#354 AC-3)."
    assert any(_GH_ASSURANCE_FLAG.search(block) for block in create_fences), (
        f"{_GITHUB_SKILL}'s create step does not apply "
        f"`--label {ASSURANCE_LABEL_PREFIX}<level>`. The protocol makes the label "
        f"a postcondition; the provider is what actually applies it (#354 AC-3)."
    )
    fixed = [block for block in create_fences if _GH_FIXED_LEVEL.search(block)]
    assert not fixed, (
        f"{_GITHUB_SKILL}'s create step hard-codes an assurance level rather than "
        f"passing the chosen one: {fixed}. The recipe maps a value; it never "
        f"selects one (#354 AC-3)."
    )


def test_the_github_create_recipe_keeps_todo_placement_alongside_the_label() -> None:
    """AC-3 is a conjunction: exactly one label **and** explicit Todo placement.

    The item-add-no-status trap (tick #90) is the half that has already been lost
    once. Asserting both in one test binds them: a rewrite that adds the label
    while collapsing the three-step sequence fails here rather than passing two
    tests that each saw half the recipe.
    """
    text = _read(_GITHUB_SKILL)
    for fragment in (
        "gh issue create",
        "gh project item-add",
        "gh project item-edit",
        "single-select-option-id",
    ):
        assert fragment in text, (
            f"{_GITHUB_SKILL} must keep `{fragment}` — an item added without an "
            f"explicit Status is invisible to the Todo-scoped queue read (#354 AC-3)."
        )
    assert _GH_ASSURANCE_FLAG.search(text), (
        f"{_GITHUB_SKILL} must apply the assurance label alongside the placement "
        f"steps — AC-3 requires both, not either (#354 AC-3)."
    )


def _github_create_recipe() -> str:
    """The GitHub ``create`` recipe — from its heading to the next one.

    Section-scoped, and this is load-bearing rather than tidy: the ``open``
    recipe two headings above already reads an issue's labels back, so a
    file-wide check for a label read-back is satisfied by prose that predates
    this ticket.
    """
    text = _read(_GITHUB_SKILL)
    match = re.search(r"^### `create`[^\n]*$", text, re.MULTILINE)
    assert match, f"{_GITHUB_SKILL} has no `create` recipe heading"
    rest = text[match.end() :]
    end = re.search(r"^#{2,3} ", rest, re.MULTILINE)
    return rest[: end.start()] if end else rest


#: A read-back of the created issue's labels, in whichever form a provider
#: expresses it — a command in GitHub's fence, a sentence in Linear's prose.
#: Defined here rather than in the rubric module, with its controls below and the
#: two recipes it reads: it is a provider-recipe predicate, and nothing in the
#: rubric module calls it.
_READS_BACK = re.compile(r"\bre-read\w*\b|\bread(?:s|ing)?\b[^.;]{0,60}?\bback\b", re.IGNORECASE)
_LABEL = re.compile(r"\blabels?\b", re.IGNORECASE)


def _reads_the_label_back(text: str) -> list[str]:
    """Units of ``text`` that re-read the created issue's **labels** after writing.

    A write that was refused, or landed twice, is indistinguishable from a
    successful one until the issue is read again: neither ``gh``'s exit status
    nor Linear's ``success`` field says the label is *on* the issue, only that
    the call ran.

    One predicate for both providers, deliberately — they express the rule in
    different media (a command in a fence, a sentence in prose), and a predicate
    per provider is how this ended up guarded on one side and unguarded on the
    other. Both conjuncts must land in the *same* unit: naming the read-back and
    naming labels in separate breaths is satisfied by the ``open`` recipe, which
    read labels back long before this ticket.
    """
    return [unit for unit in _sentences(text) if _READS_BACK.search(unit) and _LABEL.search(unit)]


def test_the_read_back_predicate_discriminates() -> None:
    """FLOOR for the parametrized read-back sweep, through the same function.

    Both real spellings — GitHub's fenced command with its comment, Linear's
    prose sentence — and the shape that must **not** count: naming labels while
    trusting what the write itself reported, which is the exact failure AC-6
    names and the one a looser predicate would accept.
    """
    assert _reads_the_label_back(
        "verify the postcondition by re-reading the issue, not by exit status\n"
        "gh issue view <number> --repo <owner>/<name> --json labels"
    )
    assert _reads_the_label_back(
        "Read the created issue's labels back before reporting; the mutation's "
        "`success` field says the call ran, not that the postcondition holds."
    )
    assert not _reads_the_label_back(
        "`labelIds` must include the resolved id of the `assurance:<level>` label the "
        "filer chose, and the mutation reports whether it succeeded."
    ), (
        "the read-back predicate counts a sentence that merely names labels — it "
        "would report the postcondition guarded while nothing re-reads the issue."
    )
    assert not _reads_the_label_back("Read the tracker skill first, and come back to this file."), (
        "the read-back predicate matches a `read`/`back` pair that has nothing to "
        "do with an issue's labels."
    )


def _linear_create_recipe() -> str:
    """The Linear ``create`` recipe — the ``issueCreate`` paragraph and its fence.

    Region-scoped for the same reason the GitHub recipe is: the Labels table
    higher up the file names ``assurance`` three times, so a file-wide check that
    Linear "mentions assurance" is satisfied by the taxonomy row while the recipe
    itself says nothing about carrying the id.
    """
    text = _read(_LINEAR_SKILL)
    start = text.index("**Create an issue**")
    end = text.index("**Comment**", start)
    return text[start:end]


def test_the_linear_create_recipe_carries_the_resolved_label_id() -> None:
    """AC-3, Linear side: ``issueCreate`` passes the resolved assurance label id."""
    recipe = _linear_create_recipe()
    create_fences = [block for block in _fenced_blocks(recipe) if "issueCreate" in block]
    assert create_fences, f"{_LINEAR_SKILL} no longer documents `issueCreate` (#354 AC-3)."
    assert any("labelIds" in block for block in create_fences), (
        f"{_LINEAR_SKILL}'s `issueCreate` recipe carries no `labelIds` — the "
        f"assurance label has no way onto the issue (#354 AC-3)."
    )
    assert _ASSURANCE.search(recipe), (
        f"{_LINEAR_SKILL}'s create recipe must state that `labelIds` includes the "
        f"resolved `{ASSURANCE_LABEL_PREFIX}<level>` id (#354 AC-3)."
    )


@pytest.mark.parametrize(
    ("skill", "recipe"),
    [(_GITHUB_SKILL, _github_create_recipe), (_LINEAR_SKILL, _linear_create_recipe)],
    ids=[_GITHUB_SKILL, _LINEAR_SKILL],
)
def test_each_provider_recipe_states_the_incomplete_filing_outcome(
    skill: str, recipe: Callable[[], str]
) -> None:
    """AC-6 reaches the provider, not only the protocol.

    The `tracker` contract can define the failure shape; the recipe is what an
    agent actually follows. Both backends must say, in the create recipe itself,
    that a label they cannot apply makes the filing incomplete — with the
    identifier, the URL, and a stop.
    """
    stated = _states_an_incomplete_filing(recipe())
    assert stated, (
        f"{skill}'s create recipe never names the incomplete-filing outcome. A "
        f"provider that cannot apply exactly one assurance label must report the "
        f"filing incomplete and stop, not return a queue-ready identifier "
        f"(#354 AC-6)."
    )


@pytest.mark.parametrize(
    ("skill", "recipe"),
    [(_GITHUB_SKILL, _github_create_recipe), (_LINEAR_SKILL, _linear_create_recipe)],
    ids=[_GITHUB_SKILL, _LINEAR_SKILL],
)
def test_each_provider_recipe_reads_the_label_back_before_reporting(
    skill: str, recipe: Callable[[], str]
) -> None:
    """AC-6 at the provider: the postcondition is *read back*, not assumed.

    Parametrized over both backends through one predicate rather than checked
    per-provider, because the per-provider form is what let this land guarded on
    GitHub and unguarded on Linear — the same postcondition, one of the two
    deletable without a test noticing.
    """
    assert _reads_the_label_back(recipe()), (
        f"{skill}'s create recipe never re-reads the created issue's labels. "
        f"Neither an exit status nor a mutation's `success` field is evidence "
        f"that exactly one assurance label is on the issue (#354 AC-6)."
    )


def test_the_linear_labels_table_carries_the_assurance_group() -> None:
    """AC-3, Linear side: the taxonomy names the group and its quantifier."""
    rows = [
        row
        for row in _section(_read(_LINEAR_SKILL), "## Labels").splitlines()
        if row.startswith("|") and _ASSURANCE.search(row)
    ]
    assert rows, (
        f"{_LINEAR_SKILL}'s Labels table has no assurance row — the taxonomy that "
        f"tells a filer which labels exist omits the one that is mandatory "
        f"(#354 AC-3)."
    )
    assert any(_EXACTLY_ONE.search(row) for row in rows), (
        f"the assurance row states no quantifier: {rows}. The rule is exactly "
        f"one, always (#354 AC-3/AC-6)."
    )


# ---------------------------------------------------------------------------
# AC-9 — every registered file's header version matches its registry entry
# ---------------------------------------------------------------------------
#
# Derived over the whole registered surface rather than over this change's file
# list: a hand-written list of "the files this ticket touched" is stale the day
# after it lands, and a parity guard that only covers the files someone
# remembered is exactly the drift AC-9 is about. The registry's own
# self-version parity is already guarded by
# ``test_guidance_github_source::test_registry_header_matches_meta_self_version``
# and is deliberately not duplicated here.


def _registry_entry(rel: str) -> str:
    match = re.search(rf"^\s{{2}}{re.escape(rel)}:\s*\{{([^}}]*)\}}", _REGISTRY.read_text(), re.M)
    assert match, f"{rel} has no registry.yaml entry"
    return match.group(1)


def test_the_registered_surface_floor_for_version_parity() -> None:
    """FLOOR. A collapsed derivation would parametrize the parity check over nothing."""
    registered = _registered_markdown()
    assert len(registered) >= 40, (
        f"only {len(registered)} registered `.md` files parsed — the parity check "
        f"below derives its subjects from this set (#354 AC-9)."
    )
    for expected in (_RUBRIC_HOME, _TRACKER_SKILL, "templates/change.md"):
        assert expected in registered, f"the parity sweep no longer reaches {expected}"


@pytest.mark.parametrize("rel", _registered_markdown(), ids=lambda r: r)
def test_registered_file_version_matches_its_registry_entry(rel: str) -> None:
    """AC-9: the file's own stamp and the registry agree, for every registered file.

    ``/update-guidance`` and the freshness hook compare the registry's version to
    the consumer's; a file edited without its stamp bumped ships silently, and a
    stamp bumped in only one of the two places ships a version nobody has.
    """
    header = re.search(r"guidance:([\w-]+)@([\d.]+)", _read(rel))
    assert header, f"{rel} carries no `guidance:<id>@<version>` header (#354 AC-9)."
    entry = _registry_entry(rel)
    assert f"id: {header.group(1)}" in entry, (
        f"{rel} declares id `{header.group(1)}`; registry.yaml says {entry.strip()!r}"
    )
    assert f"version: {header.group(2)}" in entry, (
        f"{rel} is stamped {header.group(2)} but registry.yaml says "
        f"{entry.strip()!r} — bump both or neither (#354 AC-9)."
    )
