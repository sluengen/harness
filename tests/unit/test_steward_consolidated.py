"""Guard: one ``steward`` agent; ``/assess`` selects the scope; domains are skills (CAL-704).

``/assess`` dispatched one of *two* agents — ``agents/code-steward.md`` (code domain) and
``agents/system-steward.md`` (guidance domain) — that shared one methodology
(``skills/assessment-craft/SKILL.md``) and one procedure (``agents/tasks/steward.md``). The
*process* lived in two files; only the *domain standards* differed. B1 of the pre-launch
consolidation (``specs/proposals/pre-launch-consolidation.md``) adopts the layering —
**command = the scope; agent = the process; skills = the domain standards, pulled
just-in-time** — merging the two stewards into one ``agents/steward.md``.

AC-2 is *retired*: ``skills/guidance-coherence`` and the ``system`` scope went with the
runtime (ADR 0015 / #435), so the steward has two scopes, not three.

**What this module asserts, after #459.** Four negative-space / identity checks — both
old agent files are gone, the surviving agent is versioned and named, the registry lists
it and neither retired name, and no live installed-surface file mentions either — plus
**two tripwires**:

* the scope routing gates the ``design-system`` lens on its layer (``agents/steward.md``
  and ``commands/assess.md``, one rule across two surfaces);
* ``specs/architecture-principles.md`` records the layering that makes one steward
  possible (AC-6).

Four prose tests collapsed into those two under #459 (ADR 0016). One of them,
``assert "code" in lower and "architecture" in lower`` over the whole of
``commands/assess.md``, was **deleted outright rather than converted**: two extremely
common English words, unanchored, over a file about assessing code and architecture. It
could not fail while the file existed, and the routed-scope claim it gestured at is
already measured — with the retired ``system`` scope asserted absent — by
``test_assess_architecture_scope::test_code_and_architecture_scopes_remain_routed``.

Occurrence the layer-gate polarity cites (``code-quality`` Part C): the pre-#459 form was
``assert "design-system adherence" in text and "layer-gated" in text`` over the whole
command file. The two tokens sat in one table cell, but nothing said so — prose adding a
``design-system`` lens to an ungated scope, with ``layer-gated`` surviving in a sentence
about something else, passed unchanged. The ``craft.md`` class is *A guard over prose owns
structure and negative space, never meaning*.

*Source:* CAL-704, reshaped by #459.
"""

from __future__ import annotations

import re

from tests.unit._prose import REPO_ROOT

AGENTS_DIR = REPO_ROOT / "agents"
STEWARD = AGENTS_DIR / "steward.md"
CODE_STEWARD = AGENTS_DIR / "code-steward.md"
SYSTEM_STEWARD = AGENTS_DIR / "system-steward.md"
ASSESS = REPO_ROOT / "commands" / "assess.md"
REGISTRY = REPO_ROOT / "registry.yaml"
PRINCIPLES = REPO_ROOT / "specs" / "architecture-principles.md"

#: The live, installed surface — the files a consumer repo pulls. History (CHANGELOG),
#: specs/proposals + assessments (which record the change), and tests (this guard names the
#: retired agents as data) are deliberately excluded.
_SURFACE = [
    *sorted((REPO_ROOT / "commands").glob("*.md")),
    *sorted(AGENTS_DIR.glob("*.md")),
    *sorted((REPO_ROOT / "skills").glob("*/SKILL.md")),
    *sorted((REPO_ROOT / "templates").glob("*.md")),
    REPO_ROOT / "process" / "harness.md",
    REPO_ROOT / "AGENTS.md",
    REPO_ROOT / "CLAUDE.md",
    REPO_ROOT / "GEMINI.md",
    REGISTRY,
]


def _blocks(text: str) -> list[str]:
    return [block.strip() for block in text.split("\n\n") if block.strip()]


# --- AC-1: one steward replaces two -----------------------------------------


def test_old_steward_agents_removed() -> None:
    """Both per-domain steward agent files are gone — folded into one ``steward``."""
    for old in (CODE_STEWARD, SYSTEM_STEWARD):
        assert not old.exists(), (
            f"{old.relative_to(REPO_ROOT)} must be removed — the two stewards merge into "
            "agents/steward.md (CAL-704)"
        )


def test_single_steward_agent_exists() -> None:
    """``agents/steward.md`` exists and is a valid, versioned, named agent."""
    assert STEWARD.exists(), "agents/steward.md must exist (the single process agent, CAL-704)"
    text = STEWARD.read_text()
    assert re.search(r"<!-- guidance:steward@\d+\.\d+\.\d+ -->", text), (
        "agents/steward.md must carry a 'guidance:steward@<version>' header"
    )
    assert re.search(r"^name:\s*steward\s*$", text, re.MULTILINE), (
        "agents/steward.md frontmatter must declare 'name: steward'"
    )


def test_registry_lists_steward_not_old_stewards() -> None:
    """The registry lists the new ``steward`` and drops both old steward entries."""
    text = REGISTRY.read_text()
    assert "code-steward" not in text and "system-steward" not in text, (
        "registry.yaml must not list code-steward/system-steward — remove their entries (CAL-704)"
    )
    assert re.search(r"agents/steward\.md:\s*\{\s*id:\s*steward,", text), (
        "registry.yaml must list 'agents/steward.md: { id: steward, ... }' (CAL-704)"
    )


def test_no_dangling_steward_reference_in_surface() -> None:
    """No live installed-surface file mentions the retired per-domain steward names (AC-1)."""
    offenders = [
        str(p.relative_to(REPO_ROOT))
        for p in _SURFACE
        if p.exists() and re.search(r"code-steward|system-steward", p.read_text())
    ]
    assert not offenders, (
        "the consolidated surface must carry no 'code-steward'/'system-steward' reference; "
        f"found in: {offenders} (CAL-704 AC-1)"
    )


# --- AC-3 / AC-4: the scope routing, and the gate on the design-system lens ---

#: The restrictor, **anchored to the condition it names**. This is the polarity of
#: the whole rule: the lens is pulled *only* when its layer is on. A routing block
#: naming ``design-system`` unconditionally reads as the rule to every term check.
_ONLY_WHEN_THE_LAYER = re.compile(
    r"\bonly\b(?:\W+\w+){0,4}?\W+layer\b", re.IGNORECASE
)

#: The domain standards the ``code`` scope pulls just-in-time.
_CODE_DOMAIN_SKILLS = (
    "code-quality",
    "test-driven-development",
    "architecture",
    "engineering-principles",
)


def _scope_routing_blocks() -> list[str]:
    """``agents/steward.md`` bullet blocks that route the ``code`` scope."""
    return [
        b for b in _blocks(STEWARD.read_text()) if b.startswith("- `") and "`code`" in b
    ]


def _design_system_lens_lines() -> list[str]:
    """``commands/assess.md`` lines naming the design-system adherence lens."""
    return [ln for ln in ASSESS.read_text().splitlines() if "design-system adherence" in ln]


def test_the_design_system_lens_is_gated_on_its_layer() -> None:
    """One rule across two surfaces: the lens is conditional, and both say so (AC-3/AC-4).

    Two anchored windows, because the rule is only true if both carry it — the
    agent decides what it loads, the command decides what the deep pass looks at:

    * **the steward's scope-routing block** — exactly one bullet block names the
      ``code`` scope; it must list the code-domain standards and carry the
      restrictor ``only … layer`` beside ``design-system``.
    * **the command's deep-pass row** — exactly one line of ``commands/assess.md``
      names ``design-system adherence``, and that same line must carry
      ``layer-gated`` and ``--deep``. Line-scoped on purpose: before #459 the two
      tokens were asserted independently over the whole file, so nothing tied the
      gate to the lens it gates.
    """
    routing = _scope_routing_blocks()
    assert len(routing) == 1, (
        f"agents/steward.md has {len(routing)} scope-routing bullet blocks naming the "
        "`code` scope; it must have exactly one. The routing is what makes a single "
        "steward possible — split across two blocks, the two scopes start drifting "
        "back into two agents (CAL-704 AC-3)."
    )
    block = routing[0]
    missing = [skill for skill in _CODE_DOMAIN_SKILLS if skill not in block]
    assert not missing, (
        f"the steward's `code` scope no longer pulls {missing} as domain standards "
        "(CAL-704 AC-3)."
    )
    assert "design-system" in block and _ONLY_WHEN_THE_LAYER.search(block), (
        "the steward's scope routing no longer gates `design-system` on its layer. "
        "Loaded unconditionally, a repo with no design system gets an assessment "
        "against standards it never adopted — and every term check here still passes "
        "(CAL-704 AC-4)."
    )

    lens_lines = _design_system_lens_lines()
    assert len(lens_lines) == 1, (
        f"commands/assess.md names the design-system adherence lens on "
        f"{len(lens_lines)} lines; it must name it on exactly one — the deep-pass row."
    )
    assert "layer-gated" in lens_lines[0] and "--deep" in lens_lines[0], (
        "the design-system adherence lens is listed without `layer-gated` on the same "
        f"deep-pass row: {lens_lines[0]!r}. Asserting the two tokens anywhere in the "
        "file is satisfied by an ungated lens beside an unrelated mention of gating "
        "(CAL-704 AC-4)."
    )


# --- AC-6: the layering principle is recorded -------------------------------

#: The negation **anchored to the alternative it rejects**. "One steward" is only
#: a decision because the obvious alternative — one steward per domain — is the
#: shape it replaced, and is what a later editor would re-derive.
_NOT_PER_DOMAIN = re.compile(
    r"\b(?:not|never|no)\b(?:\W+\w+){0,4}?\W+per domain\b", re.IGNORECASE
)


def _layering_principles() -> list[str]:
    """``specs/architecture-principles.md`` paragraphs recording a single steward."""
    return [
        " ".join(b.split())
        for b in _blocks(PRINCIPLES.read_text())
        if re.search(r"\b(?:single|one) steward\b", b, re.IGNORECASE)
    ]


def test_the_assessment_layering_is_recorded() -> None:
    """``architecture-principles.md`` records command=scope, agent=process, skills=standards (AC-6).

    One tripwire over one rule-home. **Anchor:** exactly one paragraph names a
    single steward. **Terms:** the three layers the principle assigns —
    ``scope``, ``process``, ``domain standard`` — plus ``just-in-time``, which is
    what makes the skills a *pull* rather than a fifth artifact. **Polarity:** the
    rejected alternative, one steward per domain, anchored to ``per domain``. The
    pre-#459 form asserted the four terms independently over the whole file, where
    all four occur for unrelated reasons.
    """
    paragraphs = _layering_principles()
    assert len(paragraphs) == 1, (
        f"specs/architecture-principles.md has {len(paragraphs)} paragraphs recording a "
        "single steward; it must have exactly one. Two statements of one principle is "
        "the duplication the principle itself rejects (CAL-704 AC-6)."
    )
    principle = paragraphs[0]
    lowered = principle.lower()

    missing = [
        term
        for term in ("scope", "process", "domain standard", "just-in-time")
        if term not in lowered
    ]
    assert not missing, (
        f"the assessment-layering principle no longer states {missing}. The layering is "
        "the whole reason one steward is enough: the command names the scope, the agent "
        "is the process, and the domain standards are skills pulled just-in-time "
        "(CAL-704 AC-6)."
    )
    assert _NOT_PER_DOMAIN.search(principle), (
        "the principle names a single steward but no longer rejects one per domain. "
        "Without the alternative it replaced, it reads as a description of today's "
        "tree rather than a decision — and the next domain added gets its own agent "
        "with nothing going red (CAL-704 AC-6)."
    )
