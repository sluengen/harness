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


def _readme_live_text() -> str:
    """README text up to the ``## Changelog`` heading.

    The dated entries below it (e.g. "calling three deterministic verbs")
    record the three-verb era faithfully as of when they were written and are
    correct history, not drift — the same exclusion the #249 assessment drew.
    """
    text = README.read_text()
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


def _claimed_count(word: str) -> int:
    return int(word) if word.isdigit() else _NUMBER_WORDS[word.lower()]


def test_readme_what_it_does_bullets_every_audited_verb() -> None:
    """README's ``## What it does`` section documents every audited verb as its
    own bullet, not merely mentions it (the ``:47-49`` defect: `design` had no
    bullet at all)."""
    text = _readme_live_text()
    section = text[text.index("## What it does") : text.index("## The model:")]
    missing = {
        verb
        for verb in _AUDITED_VERBS
        if not re.search(rf"^- \*\*`{verb}`\*\*", section, re.M)
    }
    assert not missing, (
        f"README.md's '## What it does' section has no `- **`<verb>`**` bullet "
        f"for {sorted(missing)} — every audited verb needs its own bullet (#249)."
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
    text = _readme_live_text()
    stale = [
        m.group(0)
        for m in _COUNT_CLAIM.finditer(text)
        if _claimed_count(m.group(1)) != len(_AUDITED_VERBS)
    ]
    assert not stale, (
        f"README.md states a stale verb/command count: {stale}. The lifecycle "
        f"now has {len(_AUDITED_VERBS)} verbs (#249)."
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
