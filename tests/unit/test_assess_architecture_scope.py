"""CAL-816 — `/assess architecture --deep`, a holistic architecture-review scope.

Raised from the Slate architecture-review follow-up (2026-06-19): `/assess code
--deep` carries architecture as one lens, but its output contract is a *finding
engine* — only issues that clear the future-ticket bar survive, so the holistic
question ("is the system shape still right for the product, and what should we
preserve, change, or watch?") gets squeezed out. This change adds a distinct
`architecture` scope to the *same* steward process: the scope changes the domain
standards (the architecture skill's assessment rubric) and the report contract
(a holistic judgement that may file zero tickets while still recording a verdict
and a watchlist), not the agent.

**What this module asserts, after #459.** Four identity/exclusivity checks —
header⇄registry parity for every surface this ticket edited, the rubric's single
canonical home, the routed scope set with the retired `system` scope asserted
absent, and the global scope-ID enumeration naming `ARCH-` — plus **two
tripwires**, one per rule-home:

* ``skills/architecture/SKILL.md`` § ``## Architecture assessment`` carries the
  eight lenses and names positive bets to preserve;
* ``commands/assess.md`` § step 2 states that the architecture scope files only
  actionable risks, with the negation that excludes positive observations.

Seven prose pins collapsed into those two under #459 (ADR 0016), and both
``test_smoke_*`` cases went with their ``_file_only_actionable`` fixture: the
"executable spec" they exercised was a three-line dict filter **defined in this
test file**, asserted against samples also defined here. It could not fail for any
edit to the guidance it claimed to be the smoke test of — the ``craft.md`` class
*Exercise the production path, not merely a production constant*, in its worst
form, since there is no production path at all (the mechanism is agent-followed
prose).

Occurrence the surviving polarity cites (``code-quality`` Part C): the pre-#459
filing check was ``assert "only" in low and "actionable" in low`` over the whole
of ``commands/assess.md``. Both words occur in the file for unrelated reasons,
and neither reads the exclusion — so prose instructing the steward to file
positive observations as tickets passed it. The ``craft.md`` class is *A guard
over prose owns structure and negative space, never meaning*.
"""

from __future__ import annotations

import re
from pathlib import Path

from tests.unit._prose import REPO_ROOT, assess_step_two

ASSESS = REPO_ROOT / "commands" / "assess.md"
STEWARD = REPO_ROOT / "agents" / "steward.md"
ARCHITECTURE = REPO_ROOT / "skills" / "architecture" / "SKILL.md"
ASSESSMENT_CRAFT = REPO_ROOT / "skills" / "assessment-craft" / "SKILL.md"
ASSESSMENT_TEMPLATE = REPO_ROOT / "templates" / "assessment.md"
REGISTRY = REPO_ROOT / "registry.yaml"

#: The canonical rubric's section header — it lives in exactly one skill.
RUBRIC_SECTION = "## Architecture assessment"

#: The eight holistic lenses the rubric must carry (AC-3).
LENSES = (
    "purpose fit",
    "boundary integrity",
    "domain-model coherence",
    "change ergonomics",
    "operational",
    "verification architecture",
    "spec-record",
    "watchlist recommendations",
)


def _section(text: str, header: str) -> str:
    """The body of a ``## ``-level markdown section, header to next ``## ``."""
    m = re.search(rf"^{re.escape(header)}\b.*$", text, re.MULTILINE)
    assert m, f"missing section header {header!r}"
    rest = text[m.end() :]
    end = re.search(r"^## ", rest, re.MULTILINE)
    return rest[: end.start()] if end else rest


def _registry_version(path_fragment: str) -> str:
    m = re.search(
        rf"{re.escape(path_fragment)}:\s*\{{[^}}]*version:\s*([\d.]+)",
        REGISTRY.read_text(),
    )
    assert m, f"no registry entry for {path_fragment!r}"
    return m.group(1)


def _header_version(path: Path) -> str:
    m = re.search(r"<!-- guidance:[\w-]+@([\d.]+) -->", path.read_text())
    assert m, f"no guidance header in {path}"
    return m.group(1)


# --- AC-3: the architecture skill carries a holistic assessment rubric --------


def test_the_architecture_rubric_carries_its_lenses() -> None:
    """The rubric's lens set, read from its own section (AC-3).

    **This rule has no polarity, and that is stated rather than faked.** It is an
    enumeration: eight lenses plus the instruction to name positive bets to
    preserve. There is no negation the rule cannot be stated without, and a bare
    ``"not" in block`` over a section this long is decoration — almost any English
    section satisfies it. What the tripwire owns is membership, read from the
    anchored section rather than the file, so a lens deleted from the rubric fails
    here even if the word survives in the surrounding prose.

    Whether the eight lenses *say* the right thing is the review gate's job
    (ADR 0016).
    """
    block = _section(ARCHITECTURE.read_text(), RUBRIC_SECTION).lower()
    missing = [lens for lens in LENSES if lens not in block]
    assert not missing, (
        f"the {RUBRIC_SECTION!r} rubric no longer carries the {missing} lens(es) "
        "(AC-3). The scope is the lens set — dropping one narrows what a holistic "
        "pass looks at, silently."
    )
    assert "preserve" in block, (
        "the rubric no longer names positive bets to preserve as first-class "
        "output. Without it the architecture scope degrades into the finding "
        "engine the `code` scope already is, which is the gap CAL-816 opened it "
        "to close (AC-3)."
    )


def test_rubric_lives_in_exactly_one_skill() -> None:
    """The holistic rubric has one canonical home — `architecture` (lean/MECE)."""
    homes = sorted(
        str(p.relative_to(REPO_ROOT))
        for p in REPO_ROOT.glob("skills/*/SKILL.md")
        if RUBRIC_SECTION in p.read_text()
    )
    assert homes == ["skills/architecture/SKILL.md"], (
        "the Architecture assessment rubric must have exactly one canonical home "
        f"(skills/architecture/SKILL.md); found in: {homes}."
    )


# --- AC-7: the architecture scope's filing rule -------------------------------

#: The exclusion, **anchored to the object it excludes**. This is the whole rule:
#: narrative output stays in the report. A window that says "file only actionable
#: risks" without it is satisfied by a step that also files every positive
#: observation, since both are things an architecture pass produces.
_NOT_POSITIVE_OBSERVATIONS = re.compile(
    r"\b(?:not|never|no)\b(?:\W+\w+){0,6}?\W+positive observations?\b", re.IGNORECASE
)


def _architecture_filing_rules() -> list[str]:
    """Step-2 paragraphs stating the ``architecture`` scope's filing rule."""
    return [
        " ".join(block.split())
        for block in assess_step_two().split("\n\n")
        if "architecture" in block.lower() and block.strip()
    ]


def test_the_architecture_scope_files_only_actionable_risks() -> None:
    """Step 2's architecture-scope filing rule, read from its own unit (AC-7).

    Three parts:

    * **anchor** — the one paragraph of ``### 2. File the findings`` that names
      the ``architecture`` scope. The step slicer is imported from
      ``test_assess_filing_placement``, which owns the Todo-not-Backlog rule in
      the same step; two tripwires, two rule-homes, one slicer.
    * **terms** — ``only``, ``actionable``, and ``zero`` (a pass that files
      nothing is a valid outcome, not a failed run).
    * **polarity** — the negation anchored to ``positive observations``. Before
      #459 this rule was pinned by ``"only" in low and "actionable" in low`` over
      the whole command file, which reads neither the scope nor the exclusion.
    """
    candidates = _architecture_filing_rules()
    assert len(candidates) == 1, (
        f"step 2 has {len(candidates)} paragraphs naming the architecture scope; "
        "it must have exactly one. The scope's filing rule is what separates a "
        "holistic pass from the `code` scope's finding engine, and it is only "
        "readable where it is stated once (AC-7)."
    )
    rule = candidates[0]
    lowered = rule.lower()

    missing = [term for term in ("only", "actionable", "zero") if term not in lowered]
    assert not missing, (
        f"the architecture-scope filing rule no longer states {missing}. Only the "
        "actionable risks become tickets, and a useful pass may file zero of them "
        "while still recording a verdict and a watchlist (AC-7)."
    )
    assert _NOT_POSITIVE_OBSERVATIONS.search(rule), (
        "the architecture-scope filing rule no longer excludes positive "
        "observations from the tracker. An architecture report's value is largely "
        "narrative — the verdict, what is working, the trade-offs to preserve — "
        "and a rule that files only actionable risks *and* files the narrative has "
        "excluded nothing (AC-7)."
    )


# --- AC-8: the `code` scope's behavior is unchanged --------------------------


def test_code_and_architecture_scopes_remain_routed() -> None:
    """The concise role still routes both surviving assessment scopes (AC-8).

    The `system` scope was the third until ADR 0015 retired `guidance-coherence`,
    the domain skill that was its entire content; #435 removed it. `code` and
    `architecture` are the whole set now.
    """
    steward = STEWARD.read_text()
    for scope in ("`code`", "`architecture`"):
        assert scope in steward
    assert "`system`" not in steward, (
        "the `system` scope is retired with `guidance-coherence` (ADR 0015) — "
        "the steward must not route a scope whose domain skill is gone."
    )


def test_global_id_prefix_lists_name_arch() -> None:
    """Every *global* scope-ID-prefix enumeration names `ARCH-` beside `CODE-`,
    so the new scope stays coherent with the report convention (review nit).

    These are the lists that enumerate *all* scope prefixes together (the steward
    Output section, the assessment template, assessment-craft Output) — not the
    per-scope line that defines a single scope's own prefix."""
    # The steward Output section and the assessment template both phrase it as
    # "prefixed by scope — `CODE-` / …": ARCH- must sit in that list.
    for path in (ASSESSMENT_TEMPLATE,):
        text = path.read_text()
        m = re.search(r"prefixed by scope — (.+?) —|prefixed by scope — (.+?)\)", text)
        assert m, f"{path.name}: no 'prefixed by scope — …' enumeration found"
        enum = (m.group(1) or m.group(2))
        assert "ARCH-" in enum, (
            f"{path.name}: the global scope-ID enumeration must name `ARCH-` "
            f"(found: {enum!r})."
        )
    # assessment-craft lists them inline in its Output section.
    assert "ARCH-" in ASSESSMENT_CRAFT.read_text(), (
        "assessment-craft Output must name the `ARCH-` prefix."
    )


# --- version integrity: each edited header equals its registry entry ----------


def test_edited_versions_match_registry() -> None:
    """Every edited surface file's `guidance:@version` header equals its registry
    entry (the source's version-integrity invariant, test_guidance_source AC-2)."""
    for path, fragment in (
        (ASSESS, "commands/assess.md"),
        (STEWARD, "agents/steward.md"),
        (ARCHITECTURE, "skills/architecture/SKILL.md"),
        (ASSESSMENT_CRAFT, "skills/assessment-craft/SKILL.md"),
        (ASSESSMENT_TEMPLATE, "templates/assessment.md"),
    ):
        assert _header_version(path) == _registry_version(fragment), (
            f"{fragment}: header {_header_version(path)} != registry "
            f"{_registry_version(fragment)} — bump both together."
        )
