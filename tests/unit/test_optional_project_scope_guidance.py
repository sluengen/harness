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


def test_work_discovery_queue_states_scope_conditionally() -> None:
    """AC-1: the 'The queue' section names ``repo.project`` as the optional scope
    lever and states both branches — set → scope to that project; unset → the
    whole tracker queue."""
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


def test_work_discovery_ranking_unchanged() -> None:
    """AC-1: the ranking triad (dependencies, priority, decision-skip) stays
    single-homed in the skill — the scoping change does not disturb it."""
    low = SKILL.read_text().lower()
    assert all(t in low for t in ("dependencies", "priority", "decision")), (
        "the ranking/actionability logic must be unchanged by the scoping edit "
        "(#175 AC-1)."
    )


# --- AC-2: the Build routine resolves scope from CONTEXT, documents unscoped --


# --- AC-3: both guidance stamps bumped, registry rows agree ------------------


def test_guidance_stamps_bumped() -> None:
    """AC-3: ``work-discovery`` is stamped past 0.3.0, with the ``registry.yaml``
    row agreeing (the surface-parity guard enforces the pairing; this pins the
    bump direction).

    The companion half pinned the routine-build command doc past 0.1.0; #435
    retired that command, and the scope resolution it restated is now
    single-homed in the skill above — which is what the AC-1 guards cover.
    """
    skill = SKILL.read_text()
    ms = re.search(r"guidance:work-discovery@(\d+)\.(\d+)\.(\d+)", skill)
    assert ms, "the work-discovery skill must carry a guidance stamp."
    sk_ver = tuple(int(g) for g in ms.groups())
    assert sk_ver > (0, 3, 0), (
        f"work-discovery must be bumped past 0.3.0, got {ms.group(0)} (#175 AC-3)."
    )

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


def test_template_marks_repo_project_optional() -> None:
    """#176 AC-1: the CONTEXT template documents ``repo.project`` as optional."""
    doc = _repo_project_doc(TEMPLATE.read_text())
    assert doc.strip().startswith("project:"), (
        "the template must carry a `project:` field under `repo:` (#176 AC-1)."
    )
    assert _states_optionality(doc), (
        "repo.project must be documented as optional, not required (#176 AC-1)."
    )


def test_template_documents_both_project_scope_modes() -> None:
    """#176 AC-1: both modes are documented — set → scope to the project;
    omit/unset → the whole tracker queue."""
    low = _repo_project_doc(TEMPLATE.read_text()).lower()
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


def test_template_names_per_backend_unscoped_meaning() -> None:
    """#176 AC-1: "unscoped" is defined per backend — the Linear team and the
    GitHub board as each backend's natural full queue."""
    low = _repo_project_doc(TEMPLATE.read_text()).lower()
    assert "team" in low and "board" in low, (
        "the unset mode must name both the Linear team and the GitHub board as "
        "the per-backend meaning of 'unscoped' (#176 AC-1)."
    )
    assert "repo.linear" in low, (
        "the Linear unscoped meaning must name `repo.linear` as the team it "
        "widens to (#176 AC-1)."
    )


def test_template_repo_project_drops_required_only_wording() -> None:
    """#176 AC-1 boundary: the old required-only framing ('only needed if this
    repo self-hosts … omit otherwise') no longer stands alone as the sole word on
    scope — the field must positively state optionality and both modes."""
    doc = _repo_project_doc(TEMPLATE.read_text()).lower()
    # the field must not read as merely "omit otherwise" with no mode explanation:
    # both an explicit "optional" and the whole-queue mode must be present.
    assert _states_optionality(doc) and re.search(r"whole|full", doc), (
        "the project field must positively document optionality and the "
        "whole-queue mode, not just say 'omit otherwise' (#176 AC-1)."
    )


# --- #176 AC-2: idle-arm filing when unscoped (routine quality) ---------------


# --- #176 AC-3: optional read path + template-context stamp bump --------------


def test_template_context_stamp_bumped() -> None:
    """#176 AC-3: the ``template-context`` stamp is bumped past 0.1.11 and the
    ``registry.yaml`` row agrees (the surface-parity guard enforces the pairing;
    this pins the bump direction)."""
    tpl = TEMPLATE.read_text()
    m = re.search(r"guidance:template-context@(\d+)\.(\d+)\.(\d+)", tpl)
    assert m, "the CONTEXT template must carry a guidance stamp."
    ver = tuple(int(g) for g in m.groups())
    assert ver > (0, 1, 11), (
        f"template-context must be bumped past 0.1.11, got {m.group(0)} (#176 AC-3)."
    )
    ver_str = ".".join(str(n) for n in ver)
    reg = REGISTRY.read_text()
    assert re.search(
        r"templates/CONTEXT\.template\.md:\s*\{[^}]*version:\s*"
        + re.escape(ver_str)
        + r"[^}]*\}",
        reg,
    ), f"registry row for template-context must be version {ver_str} (#176 AC-3)."
