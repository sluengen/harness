"""Issues #175 and #176 — conditional, tracker-neutral project scoping.

*Source:* ``specs/proposals/optional-project-scope.md`` (Option B); issues #175/#176.

The build loop scoped all work selection to a single project (``CONTEXT.md`` →
``repo.project``) with pure-Linear wording ("Work off one Linear project"),
even though the harness now runs ``tracker: github``. Proposal Option B makes
``repo.project`` **optional**: when set, the loop scopes to that project; when
unset, it works the whole tracker queue — for ``tracker: linear`` the team named
in ``repo.linear``, for ``tracker: github`` the board (already the full queue).

The *guidance surface* half of that change — the ``work-discovery`` skill and the
``/harness routine build`` command wording (the seam/CLI is issue #174):

* **#175 AC-1** — the ``work-discovery`` skill states scope **conditionally**
  (set → scope to that project; unset → the whole tracker queue) and drops the
  Linear-only "one Linear project" wording, with the ranking triad unchanged.
* **#175 AC-2** — ``/harness routine build`` resolves scope from ``CONTEXT`` at
  runtime and documents the **unscoped** reclaim + pick path when ``repo.project``
  is absent, while keeping the scoped path intact.
* **#175 AC-3** — both ``guidance:`` stamps are bumped past their pre-change
  values and the ``registry.yaml`` rows agree (the surface-header parity guard
  enforces the pairing; this pins the direction of the bump).

The *CONTEXT schema doc* half — the last spec of the trilogy (issue #176):

* **#176 AC-1** — ``templates/CONTEXT.template.md`` marks ``repo.project``
  **optional** and documents both modes (set → scope to the project; omit → the
  whole tracker queue) and what "unscoped" means per backend (Linear team /
  GitHub board).
* **#176 AC-2** — the ``/harness routine quality`` idle arm documents where
  ``/assess`` findings file when unscoped: the tracker's default backlog, no
  project (proposal D4).
* **#176 AC-3** — the optional read path is exercised (a CONTEXT with no
  ``repo.project`` reads as ``None`` and stays coherent), and the
  ``template-context`` stamp is bumped past its pre-change value with the
  ``registry.yaml`` row agreeing.
"""

from __future__ import annotations

import re
from pathlib import Path

from harness.repo_config import repo_project

REPO_ROOT = Path(__file__).parent.parent.parent
SKILL = REPO_ROOT / "skills" / "work-discovery" / "SKILL.md"
HARNESS_COMMAND = REPO_ROOT / "commands" / "harness.md"
TEMPLATE = REPO_ROOT / "templates" / "CONTEXT.template.md"
REGISTRY = REPO_ROOT / "registry.yaml"


def _section(text: str, heading_substr: str) -> str:
    """Body of the heading line containing ``heading_substr`` up to the next
    heading of the same-or-higher level (mirrors ``test_routine_commands``)."""
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
    """AC-1: the unset branch is tracker-neutral — it names the Linear team and
    the GitHub board as the two backends' natural full scope, and no longer says
    'one Linear project'."""
    body = _section(SKILL.read_text(), "The queue")
    low = body.lower()
    assert "one linear project" not in low, (
        "the queue section must drop the 'one Linear project' wording (#175 AC-1)."
    )
    assert "team" in low and "board" in low, (
        "the unset branch must name both the Linear team and the GitHub board as "
        "the per-backend full queue (#175 AC-1)."
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


def test_build_routine_documents_unscoped_path() -> None:
    """AC-2: the Build routine resolves scope from ``CONTEXT`` and documents the
    unscoped path — a ``harness reclaim --stale`` with no ``--project`` and a
    whole-queue pick — when ``repo.project`` is absent."""
    body = _section(HARNESS_COMMAND.read_text(), "/harness routine build")
    low = body.lower()
    assert "repo.project" in body, (
        "the Build routine must name `repo.project` as the runtime scope lever "
        "(#175 AC-2)."
    )
    assert re.search(r"unset|absent", low), (
        "the Build routine must document the `repo.project` unset/absent branch "
        "(#175 AC-2)."
    )
    assert re.search(r"whole|full", low), (
        "the unset branch must widen the pick to the whole/full tracker queue "
        "(#175 AC-2)."
    )
    # the unscoped reclaim: a `harness reclaim --stale` command line whose
    # command portion (before any inline `#` comment) carries no `--project`.
    reclaim_cmds = [
        ln.split("#", 1)[0]
        for ln in body.splitlines()
        if "harness reclaim --stale" in ln.split("#", 1)[0]
    ]
    assert any("--project" not in c for c in reclaim_cmds), (
        "the Build routine must show a `harness reclaim --stale` command with no "
        "`--project` for the unscoped path (#175 AC-2)."
    )


def test_build_routine_keeps_scoped_path() -> None:
    """AC-2 boundary: the scoped path is preserved — the reclaim pre-flight still
    shows ``--project`` for the ``repo.project``-set case (the existing reclaim
    guard depends on it)."""
    body = _section(HARNESS_COMMAND.read_text(), "/harness routine build")
    assert "reclaim --stale --project" in body, (
        "the Build routine must retain the scoped `reclaim --stale --project` for "
        "the `repo.project`-set case (#175 AC-2)."
    )


def test_scope_note_is_tracker_neutral() -> None:
    """AC-2: the routine's scope note drops 'one Linear project' and the stale
    'Harness v3' project name."""
    text = HARNESS_COMMAND.read_text()
    assert "one Linear project" not in text, (
        "the routine scope note must drop 'one Linear project' (#175 AC-2)."
    )
    assert "Harness v3" not in text, (
        "the scope note must not carry the stale `Harness v3` project name — this "
        "repo's project is `Harness` since the GitHub cutover (#175 AC-2)."
    )


# --- AC-3: both guidance stamps bumped, registry rows agree ------------------


def test_guidance_stamps_bumped() -> None:
    """AC-3: ``work-discovery`` is stamped past 0.3.0 and ``harness`` past 0.2.1,
    with the ``registry.yaml`` rows agreeing (the surface-parity guard enforces
    the pairing; this pins the bump direction)."""
    skill = SKILL.read_text()
    ms = re.search(r"guidance:work-discovery@(\d+)\.(\d+)\.(\d+)", skill)
    assert ms, "the work-discovery skill must carry a guidance stamp."
    sk_ver = tuple(int(g) for g in ms.groups())
    assert sk_ver > (0, 3, 0), (
        f"work-discovery must be bumped past 0.3.0, got {ms.group(0)} (#175 AC-3)."
    )

    cmd = HARNESS_COMMAND.read_text()
    mc = re.search(r"guidance:harness@(\d+)\.(\d+)\.(\d+)", cmd)
    assert mc, "commands/harness.md must carry a guidance stamp."
    cmd_ver = tuple(int(g) for g in mc.groups())
    assert cmd_ver > (0, 2, 1), (
        f"harness command must be bumped past 0.2.1, got {mc.group(0)} (#175 AC-3)."
    )

    reg = REGISTRY.read_text()
    sk_str = ".".join(str(n) for n in sk_ver)
    cmd_str = ".".join(str(n) for n in cmd_ver)
    assert re.search(
        r"skills/work-discovery/SKILL\.md:\s*\{[^}]*version:\s*"
        + re.escape(sk_str)
        + r"[^}]*\}",
        reg,
    ), f"registry row for work-discovery must be version {sk_str} (#175 AC-3)."
    assert re.search(
        r"commands/harness\.md:\s*\{[^}]*version:\s*"
        + re.escape(cmd_str)
        + r"[^}]*\}",
        reg,
    ), f"registry row for harness command must be version {cmd_str} (#175 AC-3)."


# ============================================================================
# Issue #176 — CONTEXT schema/template + idle-arm filing doc
# ============================================================================


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
    assert "optional" in doc.lower(), (
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
    assert "optional" in doc and re.search(r"whole|full", doc), (
        "the project field must positively document optionality and the "
        "whole-queue mode, not just say 'omit otherwise' (#176 AC-1)."
    )


# --- #176 AC-2: idle-arm filing when unscoped (routine quality) ---------------


def test_quality_routine_documents_unscoped_idle_arm_filing() -> None:
    """#176 AC-2: the ``/harness routine quality`` idle arm states where
    ``/assess`` findings file when unscoped — the tracker's default backlog with
    no project (proposal D4)."""
    body = _section(HARNESS_COMMAND.read_text(), "/harness routine quality")
    assert body, "commands/harness.md must carry a '/harness routine quality' section."
    low = body.lower()
    assert re.search(r"idle arm|idle-arm", low), (
        "the quality routine must describe its idle arm (#176 AC-2)."
    )
    assert re.search(r"default backlog|team backlog", low), (
        "the idle arm must state the unscoped findings file to the tracker's "
        "default/team backlog (#176 AC-2)."
    )
    assert re.search(r"no project|without a project|unset|absent", low), (
        "the unscoped filing must be qualified as no-project (#176 AC-2)."
    )


# --- #176 AC-3: optional read path + template-context stamp bump --------------


def test_repo_project_optional_read_path(tmp_path: Path) -> None:
    """#176 AC-3: the optional path — a CONTEXT.md with no ``repo.project`` reads
    as ``None`` and does not raise; a scoped one still reads its project. This is
    the schema no longer requiring the field."""
    (tmp_path / "CONTEXT.md").write_text(
        "repo:\n  name: some-repo\n  linear: ACME\ntracker: linear\n"
    )
    assert repo_project(tmp_path) is None, (
        "a CONTEXT with no repo.project must read as None, not raise — the field "
        "is optional (#176 AC-3)."
    )

    (tmp_path / "CONTEXT.md").write_text(
        "repo:\n  name: some-repo\n  linear: ACME\n  project: Widgets\ntracker: linear\n"
    )
    assert repo_project(tmp_path) == "Widgets", (
        "a CONTEXT with repo.project set must still read that project (#176 AC-3)."
    )


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
