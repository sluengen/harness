"""Issues #175 and #176 — conditional, tracker-neutral project scoping.

*Source:* ``specs/proposals/optional-project-scope.md`` (Option B); issues #175/#176.

The build loop scoped all work selection to a single project (``CONTEXT.md`` →
``repo.project``) with pure-Linear wording ("Work off one Linear project"),
even though the harness now runs ``tracker: github``. Proposal Option B makes
``repo.project`` **optional**: when set, the loop scopes to that project; when
unset, it works the whole tracker queue — for ``tracker: linear`` the team named
in ``repo.linear``, for ``tracker: github`` the board (already the full queue).

The *guidance surface* half of that change — the ``work-discovery`` skill and the
unattended routine's command wording (the seam/CLI was issue #174):

* **#175 AC-1** — the ``work-discovery`` skill states scope **conditionally**
  (set → scope to that project; unset → the whole tracker queue) and drops the
  Linear-only "one Linear project" wording, with the ranking triad unchanged.
* **#175 AC-2** — the unattended build command resolved scope from ``CONTEXT`` at
  runtime. ``/harness routine build`` was retired by ADR 0015 and the scope
  resolution it restated is single-homed in the skill, which AC-1 covers; there
  is nothing left here for a second guard to hold.
* **#175 AC-3** — both ``guidance:`` stamps are bumped past their pre-change
  values and the ``registry.yaml`` rows agree (the surface-header parity guard
  enforces the pairing; this pins the direction of the bump).

The *CONTEXT schema doc* half — the last spec of the trilogy (issue #176):

* **#176 AC-1** — ``templates/CONTEXT.template.md`` marks ``repo.project``
  **optional** and documents both modes (set → scope to the project; omit → the
  whole tracker queue) and what "unscoped" means per backend (Linear team /
  GitHub board).
* **#176 AC-2** — the idle quality arm documented where ``/assess`` findings file
  when unscoped: the tracker's default backlog, no project (proposal D4).
  ``/harness routine quality`` was retired by ADR 0015 with the same reasoning.
* **#176 AC-3** — the ``template-context`` stamp is bumped past its pre-change
  value with the ``registry.yaml`` row agreeing.

**What this module asserts (#459).** Two rule-homes, one tripwire each, plus
the negative space and the registry correspondence.

* ``skills/work-discovery/SKILL.md`` § *The queue* — the conditional scope
  rule, with the **negation bound to hardcoding**: the scope is resolved at
  runtime, never hardcoded. The provider-neutrality ban beside it stays as its
  own test: it is a zero-membership sweep (no backend name may appear in the
  active queue policy) and needs no judgement of meaning.
* ``templates/CONTEXT.template.md`` § the ``project:`` field — that the field
  is documented optional, in both modes, with the per-backend meaning of
  "unscoped". **This rule has no negation to bind to**, and none is faked: it
  is an affirmative claim about a config field. What carries discrimination
  instead is ``_states_optionality`` and its control, which proves the
  predicate is not satisfied by the proposal name the field cites.

Two guards went. ``test_work_discovery_ranking_unchanged`` was a whole-file
co-occurrence of three common words, satisfied by almost any version of the
skill; ``test_template_repo_project_drops_required_only_wording`` re-ran two
assertions already made above it. The two ``>`` version floors went with them:
a floor pinned to a shipped version only ever weakens as the version climbs,
while the registry-agreement half beside it is the assertion that actually
holds (``craft.md`` → *Floors decay into decoration*). Whether the prose still
means what it says is the review gate's (``code-quality`` Part C → *A guard
over prose owns structure and negative space, never meaning*; ADR 0016).

**#435 dropped one test and kept the rest.** ``test_repo_project_optional_read_path``
exercised ``harness.repo_config.repo_project`` — the reader that resolved the
field at runtime — and ADR 0015 deletes the package that read it. Nothing in the
surviving tree reads ``repo.project``: it is now a field an *agent* resolves from
``CONTEXT.md`` while following ``work-discovery``, so the guards that matter are
the prose ones below, and they all still have their subjects. The remaining
import was that one test's; every other assertion here reads the skill, the
template or the registry.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent.parent
SKILL = REPO_ROOT / "skills" / "work-discovery" / "SKILL.md"
TEMPLATE = REPO_ROOT / "templates" / "CONTEXT.template.md"
REGISTRY = REPO_ROOT / "registry.yaml"


def _section(text: str, heading_substr: str) -> str:
    """Body of the heading line containing ``heading_substr`` up to the next
    heading of the same-or-higher level."""
    lines = text.splitlines()
    start = None
    level = 0
    for i, line in enumerate(lines):
        if line.startswith("#") and heading_substr in line:
            start = i
            level = len(line) - len(line.lstrip("#"))
            break
    if start is None:
        return ""
    body = [lines[start]]
    for line in lines[start + 1 :]:
        if line.startswith("#") and len(line) - len(line.lstrip("#")) <= level:
            break
        body.append(line)
    return "\n".join(body)


# --- AC-1: work-discovery states scope conditionally, tracker-neutral --------


def _sentences(block: str) -> list[str]:
    """*block* flattened to one line and split into sentences.

    The terminator may be followed by markdown emphasis or a closing bracket
    (``skill.**``, ``(…).``) — consuming those is load-bearing, not cosmetic:
    a bolded lead-in that ends ``.**`` otherwise glues its sentence to the
    next one and widens every negation window that reads this (``craft.md`` →
    *The text unit is part of the predicate*). A dry run of this module's #459
    mutation table surfaced exactly that: an inverted clause survived on a
    negation belonging to the sentence after it.
    """
    flat = " ".join(block.split())
    return [s for s in re.split(r"(?<=[.!?])[*_`\"')\]]*\s+", flat) if s.strip()]


_NEGATION = re.compile(
    r"\b(never|not|no|nothing|none|neither|nor|cannot|can't)\b", re.IGNORECASE
)


def test_work_discovery_queue_states_scope_conditionally() -> None:
    """Tripwire — 'The queue' states the scope conditionally and resolves it late.

    Terms: ``repo.project`` (the lever), an optionality word, and a
    whole/full word (what the unset branch widens to). Polarity: the sentence
    naming ``repo.project`` carries a negation — resolve it at runtime, *never*
    hardcode it. Without that binding the term set reads identically on a
    section that told an agent to bake a project address into the guidance,
    which is the pre-change defect this rule closed (#175 AC-1).
    """
    body = _section(SKILL.read_text(), "The queue")
    assert body, "work-discovery must carry a 'The queue' section."
    low = body.lower()
    assert "repo.project" in body, (
        "the queue section must name `repo.project` as the scope lever (#175 AC-1)."
    )
    assert re.search(r"unset|absent|optional", low), (
        "the queue section must document the unset/optional branch (#175 AC-1)."
    )
    assert re.search(r"whole|full", low), (
        "the unset branch must widen to the whole/full tracker queue (#175 AC-1)."
    )
    lever = [s for s in _sentences(low) if "repo.project" in s]
    assert lever, "no sentence in the queue section names repo.project (#175 AC-1)."
    assert any(_NEGATION.search(s) for s in lever), (
        "the scope lever must carry its negation — resolved at runtime, never "
        "hardcoded. A scope named as a literal address is the drift this rule "
        "exists to prevent (#175 AC-1)."
    )


def test_work_discovery_queue_is_tracker_neutral() -> None:
    """AC-1: the unset branch delegates the provider's natural scope to tracker."""
    body = _section(SKILL.read_text(), "The queue")
    low = body.lower()
    assert "linear" not in low and "github" not in low, (
        "the active queue policy must not embed provider-specific scope (#401)."
    )
    assert "configured provider" in low and "tracker" in low, (
        "the unset branch must delegate natural full-scope resolution to tracker."
    )


# --- AC-2: the Build routine resolves scope from CONTEXT, documents unscoped --


# --- AC-3: the guidance stamp and its registry row agree ---------------------


def test_guidance_stamp_agrees_with_registry() -> None:
    """AC-3: the ``work-discovery`` header stamp and its ``registry.yaml`` row
    are the same version.

    The ``> (0, 3, 0)`` floor this carried is gone: a floor pinned to a shipped
    version can only ever weaken as the version climbs past it, and it never
    measured anything the correspondence below does not (``craft.md`` →
    *Floors decay into decoration*).
    """
    skill = SKILL.read_text()
    ms = re.search(r"guidance:work-discovery@(\d+)\.(\d+)\.(\d+)", skill)
    assert ms, "the work-discovery skill must carry a guidance stamp."
    sk_ver = tuple(int(g) for g in ms.groups())

    reg = REGISTRY.read_text()
    sk_str = ".".join(str(n) for n in sk_ver)
    assert re.search(
        r"skills/work-discovery/SKILL\.md:\s*\{[^}]*version:\s*"
        + re.escape(sk_str)
        + r"[^}]*\}",
        reg,
    ), f"registry row for work-discovery must be version {sk_str} (#175 AC-3)."


# ============================================================================
# Issue #176 — CONTEXT schema/template + idle-arm filing doc
# ============================================================================


#: ``optional`` as a standalone word. The bare substring is shielded by the
#: field's own comment, which cites the proposal ``optional-project-scope`` by
#: name — so a template that dropped every statement of optionality would still
#: satisfy ``"optional" in doc`` on the citation alone. Hyphen-bounded, because
#: the citation is the only shape that has to be excluded.
_OPTIONAL_WORD = re.compile(r"(?<![\w-])optional(?![\w-])", re.IGNORECASE)


def _states_optionality(doc: str) -> bool:
    """Does ``doc`` say the field is optional, in its own words?

    One predicate, called by both assertions below, so tightening it cannot
    leave one of them reading the loose form.
    """
    return bool(_OPTIONAL_WORD.search(doc))


def test_the_optionality_predicate_is_not_satisfied_by_the_proposal_name() -> None:
    """Control: the proposal citation alone does not count as stating the rule.

    The live template contains both, which is why the loose substring test read
    green against a field that had stopped saying it.
    """
    assert not _states_optionality(
        "# repo.project (proposal optional-project-scope, D3) — set it."
    ), "the citation `optional-project-scope` satisfies the predicate on its own"
    assert _states_optionality("project: {optional — the project the loop scopes to}")


def _repo_project_doc(text: str) -> str:
    """The ``repo.project`` field documentation from the CONTEXT template — the
    ``project:`` line plus any comment/blank lines that follow it, up to the next
    non-comment key. Captures whether the doc lives inline or in trailing
    ``#`` comment lines, so a test does not care which the author chose."""
    lines = text.splitlines()
    out: list[str] = []
    capturing = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("project:"):
            capturing = True
            out.append(line)
            continue
        if capturing:
            # a later non-comment, non-blank key (e.g. `tracker:`) ends the field doc
            if stripped and not stripped.startswith("#"):
                break
            out.append(line)
    return "\n".join(out)


# --- #176 AC-1: template marks repo.project optional, both modes, per-backend -


def test_template_documents_repo_project_as_optional_in_both_modes() -> None:
    """Tripwire — the ``project:`` field doc states optionality and both modes.

    Anchor: the ``project:`` line plus its trailing comment block, so a mention
    of "optional" against some other key cannot satisfy this. Terms: an
    optionality word (through ``_states_optionality``, whose control below
    proves the field's own proposal citation does not satisfy it), an
    omit/unset word, a whole/full word, and ``team`` + ``board`` + ``repo.linear``
    for the per-backend meaning of "unscoped".

    **No polarity is asserted, and none is faked.** "This field is optional" is
    an affirmative claim about a config schema; there is no clause in it whose
    inversion a negation token would catch. Discrimination comes from
    ``_states_optionality`` and its control instead (ADR 0016).
    """
    doc = _repo_project_doc(TEMPLATE.read_text())
    assert doc.strip().startswith("project:"), (
        "the template must carry a `project:` field under `repo:` (#176 AC-1)."
    )
    assert _states_optionality(doc), (
        "repo.project must be documented as optional, not required (#176 AC-1)."
    )
    low = doc.lower()
    assert re.search(r"\bset\b", low), (
        "the project field must document the `set` mode (scope to the project) "
        "(#176 AC-1)."
    )
    assert re.search(r"omit|unset|absent", low), (
        "the project field must document the omit/unset mode (#176 AC-1)."
    )
    assert re.search(r"whole|full", low), (
        "the unset mode must widen to the whole/full tracker queue (#176 AC-1)."
    )
    for term in ("team", "board", "repo.linear"):
        assert term in low, (
            "the unset mode must name the per-backend meaning of 'unscoped' — "
            f"missing {term!r} (#176 AC-1)."
        )


# --- #176 AC-2: idle-arm filing when unscoped (routine quality) ---------------


# --- #176 AC-3: optional read path + template-context stamp bump --------------


def test_template_context_stamp_agrees_with_registry() -> None:
    """#176 AC-3: the ``template-context`` header stamp and its ``registry.yaml``
    row are the same version.

    The ``> (0, 1, 11)`` floor is gone for the same reason as its sibling above:
    a floor pinned to a shipped version only weakens with time and measures
    nothing the correspondence does not.
    """
    tpl = TEMPLATE.read_text()
    m = re.search(r"guidance:template-context@(\d+)\.(\d+)\.(\d+)", tpl)
    assert m, "the CONTEXT template must carry a guidance stamp."
    ver = tuple(int(g) for g in m.groups())
    ver_str = ".".join(str(n) for n in ver)
    reg = REGISTRY.read_text()
    assert re.search(
        r"templates/CONTEXT\.template\.md:\s*\{[^}]*version:\s*"
        + re.escape(ver_str)
        + r"[^}]*\}",
        reg,
    ), f"registry row for template-context must be version {ver_str} (#176 AC-3)."
