"""#213 — document the four-verb lifecycle across the guidance surfaces.

*Source:* ``specs/proposals/design-verb.md`` (accepted 2026-07-25), policy
record ``specs/decisions/0007-design-verb.md``; breakdown item 4 of 4. Items
1–3 shipped the ``design`` engine protocol (#210), the verb itself (#211), and
``review``'s ``no_design`` enforcement + design context (#212). The guidance
the orchestrating session actually follows still described the three-verb loop,
so every unattended run's first contact with the mandatory stage would have
been a mid-loop ``no_design`` refusal.

These guards pin that the documentation landed and stays consistent:

* the loop in ``commands/harness.md`` names the ``design`` step, its
  degrade-and-record posture, and the ``no_design`` refusal;
* one **canonical lifecycle string** appears in both ``commands/harness.md``
  and ``CONTEXT.md``, asserted against a single shared constant so the two
  surfaces cannot drift a second wording;
* ``spec-authoring`` records that the design stage is unconditional and
  verb-owned;
* the version stamps moved in **every** registry-tracked place — the standing
  trap: a header bumped without its ``registry.yaml`` entry, and
  ``registry.yaml``'s own third-order self-version left behind.

``CONTEXT.md`` is deliberately absent from the stamp assertions: it is not
registry-tracked (only ``templates/CONTEXT.template.md`` is), and its
``template-context`` header records the template it was seeded from rather
than its own content version.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from tests.unit.test_cli_surface_locked import _AUDITED_VERBS, _FENCE, _INVOCATION

REPO_ROOT = Path(__file__).parent.parent.parent
COMMAND_DOC = REPO_ROOT / "commands" / "harness.md"
CONTEXT = REPO_ROOT / "CONTEXT.md"
README = REPO_ROOT / "README.md"
SPEC_AUTHORING = REPO_ROOT / "skills" / "spec-authoring" / "SKILL.md"
CHANGELOG = REPO_ROOT / "CHANGELOG.md"
REGISTRY = REPO_ROOT / "registry.yaml"

#: The one wording of the lifecycle, taken verbatim from ADR 0007. Both
#: in-scope surfaces must carry *this* string — not a paraphrase of it.
CANONICAL_LIFECYCLE = "start → design → implement → review → (fix → review)* → close"


def _unescaped(path: Path) -> str:
    """File text with markdown's ``\\*`` escape normalised to ``*``.

    ``commands/harness.md`` writes the lifecycle inside bold markup, where a
    bare ``*`` would start emphasis, so it escapes it; ``CONTEXT.md`` writes it
    in a YAML comment where no escape is needed. Normalising lets one constant
    pin both without either file carrying a wrong-for-its-context rendering.
    """
    return path.read_text().replace("\\*", "*")


def _registry_entry(path: str) -> str:
    pattern = re.escape(path) + r":\s*\{[^}]*\}"
    m = re.search(pattern, REGISTRY.read_text())
    assert m, f"registry.yaml must have an entry for {path}"
    return m.group(0)


def _header_version(path: Path) -> str:
    m = re.search(r"guidance:[a-z0-9-]+@(\d+\.\d+\.\d+)", path.read_text())
    assert m, f"{path.name} must carry a guidance version header"
    return m.group(1)


# --- AC-1: the loop documents the design step -------------------------------


def test_loop_documents_the_design_verb() -> None:
    text = COMMAND_DOC.read_text()
    assert "harness design --run-id" in text, (
        "commands/harness.md's loop must show the `harness design --run-id "
        "<run_id>` invocation, between `start` and implement (#213 AC-1)."
    )
    assert re.search(r"\*\*Step 1\.5 — .?`?design", text), (
        "commands/harness.md must carry a design step between Step 1 (`start`) "
        "and Step 2 (implement) (#213 AC-1)."
    )


def test_loop_documents_degrade_and_record_posture() -> None:
    """ADR 0007 D4: a design-engine failure records a `failed` event and the
    build proceeds. The docs must not imply an infra flake wedges the run."""
    text = COMMAND_DOC.read_text()
    assert "degrade" in text.lower() and "no_design" in text, (
        "commands/harness.md must document the degrade-and-record posture and "
        "the `no_design` refusal together (#213 AC-1)."
    )
    assert re.search(r"failed.{0,120}satisfies|satisfies.{0,120}failed", text, re.S), (
        "commands/harness.md must state that a *failed* design attempt still "
        "satisfies `review`'s enforcement — otherwise a reader concludes a "
        "flake blocks the run (#213 AC-1)."
    )


def test_loop_documents_the_adopt_path_posting_no_comment() -> None:
    """#258: on a successful adopt, two of Step 1.5's three recording places apply.

    The step tells the reader the verb records the design "in three places", the
    first being the ticket comment. ADR 0008's adopt path posts **none** — the
    design is already on the ticket, which is where it was recovered from. An
    operator who goes looking for a design comment against a resumed run's
    `run_id` will not find one, and that is the surprise worth documenting.

    Asserted on the two facts, not on a wording: that the step names inheritance
    at all, and that it says no comment is posted. The engine-runs description
    is left alone deliberately — it is correct for every run that *does* run the
    engine, which is every clean start and every resumed run whose adoption
    declines (including one whose predecessor's own design failed).
    """
    text = COMMAND_DOC.read_text()
    assert "inherited_from" in text, (
        "commands/harness.md Step 1.5 must name the adopt path's ledger marker "
        "(`inherited_from`), so a reader can tell an adopted design from a "
        "designed one in `harness events` (#258, ADR 0008 D1)."
    )
    assert re.search(r"adopt.{0,400}no (new )?comment", text, re.S | re.I), (
        "commands/harness.md Step 1.5 must state that the adopt path posts no "
        "comment — otherwise the documented 'records it in three places' reads "
        "as unconditional and an operator hunts for a comment that is absent "
        "(#258)."
    )


def test_lifecycle_summary_matches_across_surfaces() -> None:
    """One canonical string, two surfaces — the drift this test exists to catch."""
    for path in (COMMAND_DOC, CONTEXT):
        assert CANONICAL_LIFECYCLE in _unescaped(path), (
            f"{path.name} must carry the canonical lifecycle string "
            f"{CANONICAL_LIFECYCLE!r} verbatim (#213 AC-1/AC-2)."
        )


# --- AC-2: CONTEXT.md reflects the four-verb lifecycle ----------------------


def test_context_commands_run_names_design() -> None:
    m = re.search(r"^\s*run:\s*\"([^\"]*)\"", CONTEXT.read_text(), re.M)
    assert m, "CONTEXT.md must keep a commands.run entry"
    assert "design" in m.group(1), (
        "CONTEXT.md `commands.run` must name the design verb: "
        f"got {m.group(1)!r} (#213 AC-2)."
    )


def test_context_architecture_lists_four_verbs() -> None:
    text = CONTEXT.read_text()
    assert "Four verbs, one ledger, one gate" in text, (
        "CONTEXT.md's Architecture section must read 'Four verbs, one ledger, "
        "one gate' — the ledger and the gate are unchanged (#213 AC-2)."
    )
    assert "Three verbs" not in text, (
        "CONTEXT.md must not still claim three verbs (#213 AC-2)."
    )
    assert re.search(r"^- \*\*`design`\*\*", text, re.M), (
        "CONTEXT.md's Architecture verb list must carry a `design` bullet "
        "(#213 AC-2)."
    )


# --- #249: README.md's remaining three-verb framing -------------------------
# CODE-1 (2026-07-29 assess pass). The 2026-07-26 fix corrected exactly the
# four README locations its own "Where" list named, leaving six other live
# occurrences of the same three-verb framing untouched. `test_cli_surface_
# locked.py`'s subset-enumeration guard (widened to README in the same change)
# catches the backtick-slash-list locations (`:16`, `:29`); the four guards
# below catch the shapes that guard does not scan for — an arrow diagram, a
# fenced invocation loop, a bullet enumeration, and a bare cardinality claim.


def _readme_live_text(text: str | None = None) -> str:
    """README text up to the ``## Changelog`` heading.

    The dated entries below it (e.g. "calling three deterministic verbs")
    record the three-verb era faithfully as of when they were written and are
    correct history, not drift — the same exclusion the #249 assessment drew.

    *text* defaults to the real README and is overridable so a regression test
    can doctor a copy **in memory** and still travel the guards' own scan path.
    A test that re-implemented the scan could go green while the guard's path
    stayed narrow — the same reasoning ``_subset_enumeration_offenders`` records.
    """
    text = README.read_text() if text is None else text
    cut = text.find("\n## Changelog")
    return text if cut == -1 else text[:cut]


#: A word token not introduced by ``/``, so the agent-led ``/start → /review →
#: /ship`` sequence (live in CLAUDE.md) is never read as a harness verb chain.
_INVOCATION_TOKEN = re.compile(r"(?<!/)\b(\w+)\b")


def _arrow_lifecycle_offenders(text: str, audited: set[str]) -> list[list[str]]:
    """Every line that *draws* the lifecycle (contains an arrow) yet names a
    proper subset of the audited verbs. Line-scoped, not match-scoped: a chain
    broken by ``(fix → review)*`` is still one drawing of one lifecycle."""
    out = []
    for line in text.splitlines():
        if "→" not in line:
            continue
        named = set(_INVOCATION_TOKEN.findall(line)) & audited
        if len(named) >= 2 and named != audited:
            out.append(sorted(named))
    return out


def _loop_fence_offenders(text: str, audited: set[str]) -> list[list[str]]:
    """Every fenced block that invokes two or more audited verbs, yet not all."""
    out = []
    for block in _FENCE.findall(text):
        named = set(_INVOCATION.findall(block)) & audited
        if len(named) >= 2 and named != audited:
            out.append(sorted(named))
    return out


#: A number word or digit followed by an optional single adjective and then
#: "verb(s)"/"command(s)" — the ``:45``/``:94`` idiom ("three verbs", "three
#: commands"). Requires the leading numeral so "read commands" and "two
#: triggers" (no verb/command noun, or no leading count) are left alone.
_COUNT_CLAIM = re.compile(
    r"\b(one|two|three|four|five|six|\d+)\s+(?:\w+\s+)?(verbs?|commands?)\b",
    re.I,
)

#: Word-form numbers the claim above may spell out, normalised to int so a
#: claim can be compared against ``len(_AUDITED_VERBS)`` without hardcoding
#: today's cardinality as a literal — a fifth audited verb re-arms the check
#: with no edit here.
_NUMBER_WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6}


def _stale_count_claims(text: str, expected: int) -> list[str]:
    """Every ``_COUNT_CLAIM`` hit in *text* whose number does not equal
    *expected*. An unmapped word is ignored, not raised on — ``_COUNT_CLAIM``'s
    closed word set already keeps the regex from matching arbitrary prose, so
    this stays defensive rather than relying on that exclusively."""
    out = []
    for m in _COUNT_CLAIM.finditer(text):
        tok = m.group(1).lower()
        n = int(tok) if tok.isdigit() else _NUMBER_WORDS.get(tok)
        if n is not None and n != expected:
            out.append(m.group(0))
    return out


def _missing_verb_bullets(text: str, audited: set[str]) -> list[str]:
    """Audited verbs with no bullet of their own in ``## What it does``.

    The ``^- \\*\\*`` anchor under ``re.M`` is load-bearing: a ``design``
    *mention* inside another verb's bullet must not satisfy the rule — the same
    *documented as a verb, not merely mentioned* bar the verb-model guard sets.
    """
    section = text[text.index("## What it does") : text.index("## The model:")]
    return sorted(
        verb
        for verb in audited
        if not re.search(rf"^- \*\*`{verb}`\*\*", section, re.M)
    )


def test_readme_what_it_does_bullets_every_audited_verb() -> None:
    """README's ``## What it does`` section documents every audited verb as its
    own bullet, not merely mentions it (the ``:47-49`` defect: `design` had no
    bullet at all)."""
    missing = _missing_verb_bullets(_readme_live_text(), _AUDITED_VERBS)
    assert not missing, (
        f"README.md's '## What it does' section has no `- **`<verb>`**` bullet "
        f"for {missing} — every audited verb needs its own bullet (#249)."
    )


def test_readme_lifecycle_arrows_name_every_audited_verb() -> None:
    """README's arrow-drawn lifecycle diagrams name the full audited set (the
    ``:69`` defect: the inner diagram line omitted `design`)."""
    offenders = _arrow_lifecycle_offenders(_readme_live_text(), _AUDITED_VERBS)
    assert not offenders, (
        f"README.md draws the lifecycle naming a proper subset of the audited "
        f"verbs: {offenders}. Name the full set {sorted(_AUDITED_VERBS)} (#249)."
    )


def test_readme_loop_fences_invoke_every_audited_verb() -> None:
    """README's fenced ``harness <verb>`` loops invoke the full audited set
    (the ``:94`` and ``:153-160`` defects: both fences skipped `design`)."""
    offenders = _loop_fence_offenders(_readme_live_text(), _AUDITED_VERBS)
    assert not offenders, (
        f"README.md has a fenced loop invoking a proper subset of the audited "
        f"verbs: {offenders}. Name the full set {sorted(_AUDITED_VERBS)} (#249)."
    )


def test_readme_states_no_stale_verb_cardinality() -> None:
    """README states no stale verb/command count (the ``:45``/``:94`` defect:
    "three verbs" / "three commands" after `design` joined the lifecycle)."""
    stale = _stale_count_claims(_readme_live_text(), len(_AUDITED_VERBS))
    assert not stale, (
        f"README.md states a stale verb/command count: {stale}. The lifecycle "
        f"now has {len(_AUDITED_VERBS)} verbs (#249)."
    )


# --- #249 detector precision -------------------------------------------------
# The four guards above read the *live* README, which this change already
# corrected — so on their own they asserted only that today's text is clean and
# would have stayed green if the detector logic itself regressed (line-scoping
# vs match-scoping, the `(?<!/)` exemption, the count regex's adjective slot).
# The tables below pin each detector against fixed input, independently of
# README's current text, exactly as the design's Test strategy specified.


@pytest.mark.parametrize(
    "line, flagged",
    [
        # The `:69` diagram defect — the exact shape this ticket fixed.
        ("start → [implement] → review → (fix → review)* → close", True),
        # The fix. Also why the rule is *line*-scoped: a match-scoped rule would
        # see `(fix → review)*` as its own chain and flag this line falsely.
        ("start → design → [implement] → review → (fix → review)* → close", False),
        # The agent-led sequence live in CLAUDE.md — the `(?<!/)` exemption.
        ("/start → /review → /ship", False),
        # An arrow line naming no audited verb at all.
        ("# gate → commit / merge / push → ticket Done", False),
        # One audited verb beside prose is a reference, not a lifecycle drawing.
        ("the run opens at start → then you implement", False),
        # No arrow: not a drawing of the lifecycle, whatever it names.
        ("start, review and close are the audited verbs", False),
    ],
)
def test_arrow_lifecycle_detection(line: str, flagged: bool) -> None:
    assert bool(_arrow_lifecycle_offenders(line, _AUDITED_VERBS)) is flagged


@pytest.mark.parametrize(
    "block, flagged",
    [
        # Both README loop fences (`:94`, `:156`) had this shape.
        ("```bash\nharness start X\nharness review --run-id r\nharness close X\n```", True),
        # The corrected fence.
        (
            "```bash\nharness start X\nharness design --run-id r\n"
            "harness review --run-id r\nharness close X\n```",
            False,
        ),
        # A single verb is a reference, not a loop.
        ("```bash\nharness start CAL-42\n```", False),
        # No audited verb invoked.
        ("```bash\nuv sync --extra dev\nuv run pytest\n```", False),
        # The repository-layout fence: `harness/` is followed by `/`, not a
        # space, so `_INVOCATION` cannot match it. Pins the exemption that lets
        # that fence stay unmodified.
        ("```\nharness/start.py\nharness/review.py\nharness/close.py\n```", False),
    ],
)
def test_loop_fence_detection(block: str, flagged: bool) -> None:
    assert bool(_loop_fence_offenders(block, _AUDITED_VERBS)) is flagged


@pytest.mark.parametrize(
    "text, expected, flagged",
    [
        # The `:45` / `:94` defects.
        ("three verbs over a SQLite ledger", 4, True),
        ("end to end, is three commands", 4, True),
        # The adjective slot.
        ("calling three deterministic verbs", 4, True),
        # The corrected claims.
        ("four verbs over a SQLite ledger", 4, False),
        ("end to end, is four commands", 4, False),
        # Digits, not only words.
        ("3 verbs", 4, True),
        # No leading numeral, or not the guarded noun — left alone.
        ("read commands", 4, False),
        ("two triggers", 4, False),
        ("Three paths", 4, False),
    ],
)
def test_stale_count_claim_detection(text: str, expected: int, flagged: bool) -> None:
    assert bool(_stale_count_claims(text, expected)) is flagged


def test_stale_count_claim_rearms_when_a_fifth_verb_joins() -> None:
    """A 5th audited verb makes today's *correct* "four verbs" stale — and the
    guard must say so with no edit here.

    This is the regression test for the defect review caught mid-#249: the guard
    originally carried a hardcoded ``!= "four"`` fallback beside the derived
    ``len(_AUDITED_VERBS)`` check, so a fifth verb would have left every "four
    commands" claim in README undetected. Passing *5* is the whole point — it
    simulates that future without waiting for it, and it fails loudly if the
    literal is ever reintroduced.
    """
    assert _stale_count_claims("four verbs over a SQLite ledger", 5) == ["four verbs"]
    assert not _stale_count_claims("five verbs over a SQLite ledger", 5)


def test_stale_count_claim_ignores_an_unmapped_number_word(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An unmapped numeral word is skipped, not raised on.

    ``_COUNT_CLAIM``'s closed word set makes this unreachable today, which is
    precisely why it needs a test: the defensive ``.get()`` contract is invisible
    to every other test and a future widening of the regex would turn a silent
    skip into a gate-crashing ``KeyError``. Widening the pattern here is what
    reaches the branch.
    """
    monkeypatch.setattr(
        "tests.unit.test_design_verb_lifecycle_documented._COUNT_CLAIM",
        re.compile(r"\b(\w+)\s+(?:\w+\s+)?(verbs?|commands?)\b", re.I),
    )
    assert _stale_count_claims("a dozen commands", 4) == []


# --- #249 non-vacuity: each guard catches its own defect, injected in memory --
# Equality with the injected offender — not merely a non-empty result — is what
# keeps these non-vacuous: it proves the hit is the injection rather than a
# pre-existing one, and it fails loudly if the real README regresses. Mirrors
# `test_a_stale_audited_slash_list_in_a_live_section_is_caught`.

_CHANGELOG_HEADING = "\n## Changelog"
_STALE_ARROW_LINE = "   start → [implement] → review → (fix → review)* → close\n"
_STALE_LOOP_FENCE = (
    "```bash\nharness start CAL-42\nharness review --run-id <run_id>\n"
    "harness close CAL-42 --run-id <run_id>\n```\n"
)


def _inject_live(snippet: str) -> str:
    """Real README with *snippet* placed in the live region (just above the
    ``## Changelog`` heading)."""
    text = README.read_text()
    cut = text.index(_CHANGELOG_HEADING)
    return text[:cut] + "\n\n" + snippet + text[cut:]


def _inject_retained(snippet: str) -> str:
    """Real README with *snippet* placed *below* ``## Changelog`` — the scoping
    control: the dated entries there are correct history, not drift."""
    text = README.read_text()
    cut = text.index(_CHANGELOG_HEADING) + len(_CHANGELOG_HEADING)
    return text[:cut] + "\n\n" + snippet + text[cut:]


def test_a_stale_lifecycle_arrow_injected_into_live_readme_is_caught() -> None:
    offenders = _arrow_lifecycle_offenders(
        _readme_live_text(_inject_live(_STALE_ARROW_LINE)), _AUDITED_VERBS
    )
    assert offenders == [["close", "review", "start"]]


def test_a_stale_lifecycle_arrow_below_the_changelog_is_not_scanned() -> None:
    assert not _arrow_lifecycle_offenders(
        _readme_live_text(_inject_retained(_STALE_ARROW_LINE)), _AUDITED_VERBS
    )


def test_a_stale_loop_fence_injected_into_live_readme_is_caught() -> None:
    offenders = _loop_fence_offenders(
        _readme_live_text(_inject_live(_STALE_LOOP_FENCE)), _AUDITED_VERBS
    )
    assert offenders == [["close", "review", "start"]]


def test_a_stale_loop_fence_below_the_changelog_is_not_scanned() -> None:
    assert not _loop_fence_offenders(
        _readme_live_text(_inject_retained(_STALE_LOOP_FENCE)), _AUDITED_VERBS
    )


def test_a_stale_count_claim_injected_into_live_readme_is_caught() -> None:
    stale = _stale_count_claims(
        _readme_live_text(_inject_live("A verb loop is three commands.\n")),
        len(_AUDITED_VERBS),
    )
    assert stale == ["three commands"]


def test_a_stale_count_claim_below_the_changelog_is_not_scanned() -> None:
    assert not _stale_count_claims(
        _readme_live_text(_inject_retained("A verb loop is three commands.\n")),
        len(_AUDITED_VERBS),
    )


def test_a_dropped_verb_bullet_is_caught() -> None:
    """Deleting `design`'s bullet — the ``:47-49`` defect — is caught."""
    doctored = re.sub(
        r"^- \*\*`design`\*\*.*$", "", README.read_text(), count=1, flags=re.M
    )
    assert _missing_verb_bullets(_readme_live_text(doctored), _AUDITED_VERBS) == [
        "design"
    ]


def test_a_verb_mentioned_inside_another_bullet_does_not_count_as_documented() -> None:
    """The ``^- \\*\\*`` anchor's reason for being: folding `design` into the
    `start` bullet as prose leaves it undocumented, and the guard must say so."""
    doctored = re.sub(
        r"^- \*\*`design`\*\*.*$",
        "  Then `design` runs against the worktree.",
        README.read_text(),
        count=1,
        flags=re.M,
    )
    assert _missing_verb_bullets(_readme_live_text(doctored), _AUDITED_VERBS) == [
        "design"
    ]


def test_readme_live_text_tolerates_a_missing_changelog_heading() -> None:
    """``find`` returns -1 and the whole text is scanned — no silent truncation
    to the empty string, which would make every guard above vacuously green."""
    assert _readme_live_text("# README\n\nNo changelog here.\n") == (
        "# README\n\nNo changelog here.\n"
    )


# --- AC-3: spec-authoring records the unconditional, verb-owned stage -------


def test_spec_authoring_notes_the_design_stage() -> None:
    text = SPEC_AUTHORING.read_text()
    assert "harness design" in text, (
        "spec-authoring must name the `harness design` verb as the owner of "
        "the design stage (#213 AC-3)."
    )
    assert re.search(r"unconditional", text), (
        "spec-authoring must record that the design stage is unconditional — "
        "it runs for every ticket, unlike the tier labels (#213 AC-3)."
    )
    assert "`build`" in text and "`review`" in text, (
        "spec-authoring must keep the build/review tier-label semantics, which "
        "this change does not touch (#213 AC-3)."
    )


# --- AC-4: the CHANGELOG entry ---------------------------------------------


def test_changelog_records_the_lifecycle_change() -> None:
    """An entry *heading*, not a mention. #211 and #212's bodies both name #213
    as their out-of-scope follow-on, so a bare substring search passes before
    this ticket ships anything."""
    heading = re.search(r"^### .*\(#213\).*$", CHANGELOG.read_text(), re.M)
    assert heading, (
        "CHANGELOG.md must carry its own `### ` entry heading for #213 — a "
        "mention inside a sibling entry is not one (#213 AC-4)."
    )
    assert "design" in heading.group(0).lower() or "verb" in heading.group(0).lower(), (
        "the #213 CHANGELOG heading must name the design verb / four-verb "
        "lifecycle (#213 AC-4)."
    )


# --- AC-1/AC-3: the version stamps moved in every tracked place -------------


def test_guidance_stamps_bumped_everywhere() -> None:
    """The standing trap: a header bumped without its registry entry (or with
    `registry.yaml`'s own self-version left behind, which is itself recorded in
    two places — its header and its `meta:` entry)."""
    for rel, doc in (
        ("commands/harness.md", COMMAND_DOC),
        ("skills/spec-authoring/SKILL.md", SPEC_AUTHORING),
    ):
        version = _header_version(doc)
        assert f"version: {version}" in _registry_entry(rel), (
            f"{rel} header is @{version} but its registry.yaml entry disagrees "
            "— bump both (#213)."
        )

    registry_header = re.search(r"# guidance:registry@(\d+\.\d+\.\d+)", REGISTRY.read_text())
    assert registry_header, "registry.yaml must carry its own guidance header"
    assert f"version: {registry_header.group(1)}" in _registry_entry("registry.yaml"), (
        "registry.yaml's header self-version and its `meta:` entry must agree "
        "— the third place the stamp lives (#213)."
    )


# ---------------------------------------------------------------------------
# #294 — the design engine is no longer read-only, and no surface may say it is
#
# The change that gave the engine a file as its output channel replaced
# ``--permission-mode plan`` with a scoped write grant. Six independent
# surfaces described the engine as "read-only", and every one of them went
# silently false at that moment — the module docstring, the ``--help`` text,
# README, SPEC, and two feature specs. Five were caught in review rather than
# by anything that measures, which is the defect class the ticket itself was
# filed against ("it is not the sandbox the docstring implies").
#
# So the claim is derived and checked rather than fixed in six places and
# trusted: any *live* surface describing the design engine must not call it
# read-only. Scoped to sentences that are about the design engine, because
# "read-only" is correct and load-bearing elsewhere in these same files — the
# review engine genuinely is read-only, ``harness stats`` opens the ledger
# ``mode=ro``, and a retired spec describes read-only ledger observability.
# ---------------------------------------------------------------------------

#: The surfaces that describe the design engine to a human or an agent. Paths,
#: not a glob, because the claim is about *documentation of this engine* — a
#: file that never mentions the design engine has nothing to get wrong.
_DESIGN_ENGINE_SURFACES = (
    "harness/cli/design.py",
    "harness/cli/design_protocol.py",
    "harness/cli/__init__.py",
    "README.md",
    "SPEC.md",
    "specs/features/verb-model.md",
    "specs/features/cli-surface.md",
    "commands/harness.md",
)

_SENTENCE_BREAK = re.compile(r"(?<=[.;:!?])\s+|\n\n+")


def _design_engine_sentences(text: str) -> list[str]:
    """Sentences that are about the design engine specifically."""
    # Case-insensitive deliberately. The ``--help`` string reads "Design section
    # with a ... engine" and a case-sensitive selector skipped it — the exact
    # surface the review caught, missed by the guard written to catch it.
    return [
        sentence
        for sentence in _SENTENCE_BREAK.split(text)
        if re.search(
            r"\bdesign engine\b|\bharness design\b|`design`|\bdesign\b.{0,40}\bengine\b",
            sentence,
            re.IGNORECASE,
        )
    ]


def test_no_live_surface_calls_the_design_engine_read_only() -> None:
    """The engine holds one scoped write grant; every surface must agree (#294)."""
    offenders: list[str] = []
    examined = 0
    for relpath in _DESIGN_ENGINE_SURFACES:
        text = (REPO_ROOT / relpath).read_text(encoding="utf-8")
        for sentence in _design_engine_sentences(text):
            examined += 1
            if re.search(r"read-only", sentence, re.IGNORECASE):
                offenders.append(f"{relpath}: {' '.join(sentence.split())[:160]}")
    assert examined, (
        "no sentence about the design engine was found in any listed surface — "
        "the guard is measuring nothing, so a renamed concept has slipped past it"
    )
    assert not offenders, (
        "the design engine holds write capability for its output file since "
        "#294, so no live surface may describe it as read-only:\n  "
        + "\n  ".join(offenders)
    )


def test_the_guard_would_catch_the_claim_it_forbids() -> None:
    """The negative control: prove the detector fires on the retired wording.

    Without this, a change to ``_design_engine_sentences`` that stopped matching
    anything would leave the test above green *and* vacuous — and its
    non-vacuity assert only proves some sentence was examined, not that a
    violating one would be recognised.
    """
    retired = "`harness design` runs a read-only Opus engine over the worktree."
    sentences = _design_engine_sentences(retired)
    assert sentences, "the sentence selector no longer recognises a design-engine claim"
    assert any(re.search(r"read-only", s, re.IGNORECASE) for s in sentences)


def test_the_review_engine_may_still_be_called_read_only() -> None:
    """Scope check: the sibling engine genuinely is read-only, and must stay sayable.

    A guard keyed on the bare token anywhere in these files would forbid a true
    statement about ``review`` (`claude -p --permission-mode plan`) sitting in
    the same document — and the fix for that failure would be to weaken the
    true claim, not the false one.
    """
    verb_model = (REPO_ROOT / "specs" / "features" / "verb-model.md").read_text(
        encoding="utf-8"
    )
    assert re.search(r"read-only[^\n]*review engine|review engine[^\n]*read-only", verb_model), (
        "verb-model.md no longer states the review engine is read-only; if that "
        "changed, this guard's scoping rationale needs revisiting"
    )
