"""Ground every change spec in current reality, via a read-only research subagent.

*Source:* ``specs/proposals/ground-specs-and-context-rollover.md`` (accepted
2026-06-30), WS-A — delivery re-scoped to a research subagent (primary) with
inline self-grounding (fallback).

The spec-driven flow jumped straight from "open the issue" to "write the change
spec" with no step that grounds the spec in *current* code, so agents asserted
stale recalled facts — a moved file, a renamed flag, a superseded decision —
that reverted the ticket to blocked mid-build. The grounding contract is
verify-every-fact-that-names-a-file / function / flag / version / decision
against current code.

**What this module asserts, after #459.**

* **Structural identity, unchanged and untouched by the conversion:** the
  researcher agent file exists with its ``name:`` frontmatter and version
  header; its ``tools:`` list grants neither Edit nor Write, so read-only is a
  property of the declaration rather than of prose; it is a registered surface
  unit in ``registry.yaml``; and ``templates/change.md`` carries a ``Grounding``
  heading for the recorded brief. Each compares two things in the tree to each
  other, so none of them has to judge meaning.
* **One tripwire at the rule's canonical home** — the ``**Grounding`` paragraph
  of ``skills/spec-authoring/SKILL.md`` → ``## Change spec`` — reading the five
  fact kinds the contract is scoped to, the currency requirement, and the
  fallback that makes the step unconditional.
* **One pointer tripwire** on ``commands/start.md``: the command that runs the
  step dispatches the agent that performs it, asserted on one paragraph so the
  two words cannot satisfy it from opposite ends of the file.

**This rule has no polarity, and the docstring says so rather than faking one.**
Grounding is an obligation — verify, then record — with no negation a rewording
could not drop while keeping the rule intact. Asserting a bare ``"not"`` over
the paragraph would be decoration, because almost any English paragraph carries
one (ADR 0016).

Craft class this conversion answers (``code-quality`` Part C → *A guard over
prose owns structure and negative space, never meaning*): four of the deleted
functions were whole-file containment checks, and one of them read a **string
concatenation of three files** and asserted that ``inline`` and ``fallback``
appeared somewhere in the join — a window in which the two words need never
have been in the same document, let alone the same rule.

This guard pins the *presence* of the rule. It cannot, and does not claim to,
prove grounding was genuinely performed on any ticket — the honest limit the
proposal's own risks section states.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent.parent
RESEARCHER = REPO_ROOT / "agents" / "researcher.md"
SPEC_AUTHORING = REPO_ROOT / "skills" / "spec-authoring" / "SKILL.md"
CHANGE_TEMPLATE = REPO_ROOT / "templates" / "change.md"
START_COMMAND = REPO_ROOT / "commands" / "start.md"
REGISTRY = REPO_ROOT / "registry.yaml"

#: The concrete, checkable, staleness-prone fact kinds the grounding rule is
#: scoped to (proposal D2). All five co-occurring in one paragraph is the
#: signature of the rule: each on its own is a word the skill uses elsewhere.
_FACT_KINDS = ("file", "function", "flag", "version", "decision")


# --- structural identity: the read-only researcher agent -----------------------


def test_researcher_agent_present() -> None:
    """``agents/researcher.md`` exists with Agent frontmatter and a header."""
    assert RESEARCHER.exists(), (
        "agents/researcher.md must exist — the read-only grounding agent."
    )
    text = RESEARCHER.read_text()
    assert re.search(r"^name:\s*researcher\s*$", text, re.MULTILINE), (
        "agents/researcher.md must declare `name: researcher` in its frontmatter."
    )
    assert re.search(r"guidance:researcher@[\d.]+", text), (
        "agents/researcher.md must carry a `guidance:researcher@x.y.z` version header."
    )


def test_researcher_agent_is_read_only() -> None:
    """The researcher is Explore-style read-only — its ``tools:`` frontmatter
    grants neither Edit nor Write, so read-only enforcement is structural, not
    just prose."""
    text = RESEARCHER.read_text()
    m = re.search(r"^tools:\s*\[([^\]]*)\]", text, re.MULTILINE)
    assert m, "agents/researcher.md must declare a `tools: [...]` frontmatter list."
    tools = {t.strip() for t in m.group(1).split(",") if t.strip()}
    assert "Edit" not in tools and "Write" not in tools, (
        f"the researcher must be read-only (no Edit/Write); got tools={sorted(tools)}."
    )
    assert "Read" in tools, "the researcher needs Read to investigate."


def test_researcher_registered() -> None:
    """The researcher is a registered distributed surface unit under the
    ``harness`` profile (the footprint/parity guards require every surface file to
    be registered with a matching header)."""
    entry = re.search(
        r"agents/researcher\.md:\s*\{[^}]*id:\s*researcher[^}]*\}", REGISTRY.read_text()
    )
    assert entry, (
        "registry.yaml files: must list agents/researcher.md with id: researcher."
    )
    assert "harness" in entry.group(0), (
        "the researcher entry must be in the `harness` profile."
    )


def test_change_template_has_grounding_section() -> None:
    """``templates/change.md`` carries a recorded ``Grounding`` section — the
    brief is recorded there (mirroring the Watchlist-trigger precedent)."""
    text = CHANGE_TEMPLATE.read_text()
    assert re.search(r"^#+\s*Grounding\b", text, re.MULTILINE), (
        "templates/change.md must have a `## Grounding` section for the recorded brief."
    )


# --- the rule's canonical home, and the pointer to it --------------------------


def _grounding_paragraph() -> str:
    """The ``**Grounding`` paragraph inside ``spec-authoring``'s ``## Change spec``.

    The window is a paragraph inside the section, not the file: ``file``,
    ``version`` and ``decision`` are among the commonest words in a
    spec-authoring skill, so a file-wide conjunction of the five fact kinds is
    satisfied by a tree in which the grounding rule was deleted outright — the
    over-wide unit ``craft.md`` → *The text unit is part of the predicate* names,
    and the shape four of this module's deleted functions had.
    """
    text = SPEC_AUTHORING.read_text(encoding="utf-8")
    m = re.search(r"^##\s+Change spec\b", text, re.MULTILINE)
    assert m, "spec-authoring must have a '## Change spec' section."
    rest = text[m.end() :]
    nxt = re.search(r"^##\s+", rest, re.MULTILINE)
    section = rest[: nxt.start()] if nxt else rest

    marker = "**Grounding"
    start = section.find(marker)
    assert start != -1, (
        "spec-authoring's '## Change spec' section must carry the bolded "
        "`Grounding` rule — the craft home the flow skill and `/start` point at"
    )
    tail = section[start:]
    end = tail.find("\n\n")
    return (tail if end == -1 else tail[:end]).lower()


def test_the_grounding_craft_has_a_home() -> None:
    """spec-authoring carries the grounding contract, its scope and its fallback.

    Three conjuncts over one paragraph, and none of them is a polarity: the rule
    is an obligation, so what is read is the scope it cannot be stated without.
    ``current`` is the whole point — grounding against remembered code is the
    defect, not the fix. The five fact kinds are the rule's scope; a contract
    naming three of them silently stops covering the other two. And the inline
    fallback is what makes the step unconditional rather than a capability of
    hosts that happen to have sub-agents.
    """
    paragraph = _grounding_paragraph()
    assert re.search(r"\bcurrent\b", paragraph), (
        "the grounding rule must require verification against *current* code or "
        "reality; without it the rule says to write down what you recall"
    )
    missing = [k for k in _FACT_KINDS if k not in paragraph]
    assert not missing, (
        f"the grounding rule's scope no longer names every checkable fact kind; "
        f"missing {missing}. A contract naming a subset silently stops covering "
        f"the kinds it dropped, which is where the stale facts came from."
    )
    # Measured limit, recorded rather than papered over: this reads the five
    # kinds as *words present in the rule's paragraph*, not as the membership of
    # the enumeration itself. The paragraph names `version`, `flag` and
    # `decision` a second time when it describes the recorded brief, so a
    # narrowing of the enumeration alone — "names a **file or a function**" —
    # survives here. That narrowing is a change of meaning, and per ADR 0016 the
    # review gate owns meaning; what this refuses is the paragraph losing a kind
    # altogether.
    assert "inline" in paragraph, (
        "the rule must carry the inline self-grounding fallback for a host with "
        "no sub-agent mechanism, or grounding becomes conditional on the host"
    )


def test_start_dispatches_the_grounding_step() -> None:
    """`/start` runs the step: the command names the agent and what it is for.

    Asserted on one paragraph rather than on the file. ``researcher`` and
    ``ground`` both appear in ``commands/start.md`` for unrelated reasons — the
    command lists its agents, and "background" and "grounding" share a stem — so
    a file-wide co-occurrence passes on a command that dropped the step.
    """
    paragraphs = [
        p
        for p in START_COMMAND.read_text().split("\n\n")
        if "researcher" in p.lower() and re.search(r"\bground\w*\b", p, re.IGNORECASE)
    ]
    assert paragraphs, (
        "no paragraph of commands/start.md dispatches the `researcher` agent as "
        "its grounding step. The rule lives in `spec-authoring`; this is the "
        "pointer that gets it run, and a rule nothing invokes is documentation."
    )
