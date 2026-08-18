"""A workflow that runs the verify gate checks out full history (#326).

``actions/checkout`` defaults to ``fetch-depth: 1``. The gate's feature-spec
currency guard (#280) asks git for the last commit touching each
``specs/features/*.md``, and in a depth-1 clone git answers with the graft
boundary for **every** path — a grafted commit has no known parents, so history
simplification reads it as introducing the whole tree. Every spec then reads as
touched at HEAD, and the run goes red on the specs that were not edited that day.
CI on ``dev`` was red this way from #280's merge until this fix.

Since #326 the helper *refuses* a boundary-derived answer rather than returning
it, so the failure is now named instead of misattributed to a spec's author. That
makes the truncation loud — it does not make the gate able to run. The checkout
depth is what lets the guard measure its real subject, and this guard pins it.

The subject set is **derived**: any workflow that runs ``scripts/verify.sh``,
directly or through a shell script it invokes. A workflow added later that runs
the gate is covered with no edit here. The workflows are parsed as text (PyYAML
is not a project dependency), matching ``test_ci_workflow_permissions.py``.

The one-hop resolution is not a refinement, it is the whole reach (#435). ADR
0015 retired ``release.yml`` — one of the two workflows that named the gate in
its own text — while the nightly promotion, which runs the same gate, names only
``scripts/promotion-step.sh``. A derivation that read workflow text alone would
have silently shrunk to a single subject and stopped covering the job whose
shallow clone the guard exists to prevent.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from tests.unit._prose import REPO_ROOT

_WORKFLOW_DIR = REPO_ROOT / ".github" / "workflows"

#: The gate invocation that makes a workflow a subject of this guard.
_GATE_INVOCATION = "scripts/verify.sh"

#: A checkout step — ``- uses: actions/checkout@v4`` at any indent/version.
_CHECKOUT_RE = re.compile(r"^(\s*)-\s*uses:\s*actions/checkout@\S+\s*$", re.M)

#: ``fetch-depth: 0`` — full history. Any other depth just moves the boundary.
_FULL_DEPTH_RE = re.compile(r"^\s*fetch-depth:\s*0\s*$", re.M)


#: A repo-relative shell script named in a workflow's text.
_SCRIPT_RE = re.compile(r"(?<![\w./-])(scripts/[\w./-]+\.sh)")


def _reachable_text(workflow: Path) -> str:
    """``workflow``'s text plus that of every ``scripts/*.sh`` it invokes.

    One hop, deliberately. It is the hop the tree actually uses — a workflow step
    running an extracted script (``specs/architecture-principles.md`` → *CI logic
    lives in a script, not in a `run:` block*) — and going deeper would trade a
    property the tree exhibits for one it does not.
    """
    text = workflow.read_text(encoding="utf-8")
    parts = [text]
    for relpath in dict.fromkeys(_SCRIPT_RE.findall(text)):
        script = REPO_ROOT / relpath
        if script.is_file():
            parts.append(script.read_text(encoding="utf-8"))
    return "\n".join(parts)


def _gate_workflows() -> list[Path]:
    """Every workflow that runs the verify gate, directly or one hop away."""
    return sorted(
        p for p in _WORKFLOW_DIR.glob("*.yml") if _GATE_INVOCATION in _reachable_text(p)
    )


def _checkout_blocks(text: str) -> list[str]:
    """Each ``actions/checkout`` step's text, up to the next step at its indent.

    The ``with:`` block belongs to the step it follows, so the depth assertion
    must read the step's own body rather than the whole file — a workflow with
    one full-history job and one shallow job would otherwise pass on the first.
    """
    blocks: list[str] = []
    for match in _CHECKOUT_RE.finditer(text):
        indent = len(match.group(1))
        rest = text[match.end() :]
        body: list[str] = []
        for line in rest.splitlines():
            stripped = line.strip()
            if stripped.startswith("- ") and len(line) - len(line.lstrip()) <= indent:
                break
            if stripped and not line.startswith(" " * (indent + 1)):
                break
            body.append(line)
        blocks.append("\n".join(body))
    return blocks


@pytest.mark.parametrize("workflow", _gate_workflows(), ids=lambda p: p.name)
def test_a_gate_workflow_checks_out_full_history(workflow: Path) -> None:
    """Every checkout in a gate-running workflow declares ``fetch-depth: 0``."""
    blocks = _checkout_blocks(workflow.read_text(encoding="utf-8"))
    assert blocks, f"{workflow.name} runs the gate but has no checkout step"
    shallow = [b for b in blocks if not _FULL_DEPTH_RE.search(b)]
    assert not shallow, (
        f"{workflow.name} runs {_GATE_INVOCATION} but {len(shallow)} of "
        f"{len(blocks)} actions/checkout step(s) do not declare `fetch-depth: 0`. "
        "The default depth is 1, and the feature-spec currency guard then reads "
        "the graft boundary as every spec's last commit (#280/#326)."
    )


def test_the_workflow_guard_finds_its_subjects() -> None:
    """The derivation is non-vacuous — subjects and checkout steps both found.

    A parametrized guard over an empty derived set *skips* and reads green, and
    a regex that silently matches no checkout step would pass every case without
    measuring one. Both floors are asserted, neither as a hardcoded total: the
    named workflows must be present, and every subject must yield a step.
    """
    subjects = {p.name for p in _gate_workflows()}
    assert {"ci.yml", "nightly-promotion.yml"} <= subjects, (
        f"expected the gate-running workflows among the derived subjects, got "
        f"{sorted(subjects)} — the {_GATE_INVOCATION!r} derivation is wrong"
    )
    # The floor above discriminates the one-hop resolution from a plain text
    # scan: the nightly names the gate nowhere in its own text, so it can only
    # be a subject if the script it invokes was followed.
    nightly = _WORKFLOW_DIR / "nightly-promotion.yml"
    assert _GATE_INVOCATION not in nightly.read_text(encoding="utf-8"), (
        "the nightly now names the gate directly, so its presence above no "
        "longer proves the script hop is followed — pick another subject that "
        "reaches the gate only through a script, or this floor is decorative"
    )
    for workflow in _gate_workflows():
        assert _checkout_blocks(workflow.read_text(encoding="utf-8")), (
            f"no actions/checkout step parsed out of {workflow.name} — the step "
            "regex matches nothing, so the depth assertion measures nothing"
        )
