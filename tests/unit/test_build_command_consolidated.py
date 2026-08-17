"""Guard: ``/build`` is a single engine-arg command; ``/build-codex`` is retired (CAL-703).

``commands/build.md`` and ``commands/build-codex.md`` were ~95% identical — the only
real difference was the Review step (Claude inline vs ``codex exec``). A3 of the
pre-launch consolidation (``specs/proposals/pre-launch-consolidation.md``) collapses the
two into one ``commands/build.md`` whose review takes ``--engine codex`` (default Claude),
mirroring the engine-arg policy A1 set on the verb surface, and retires
``build-codex.md`` + its registry entry.

**What this module asserts, after #459.** Three negative-space sweeps — the retired
file is gone, the registry does not list it, and no live distributed surface names
it — plus **one tripwire** over the review-engine section: the Codex engine is
declared there, it runs read-only, and it runs from the worktree. Nothing here reads
whether the prose *says* the right thing about the engine; per ADR 0016 that is the
review gate's job.

The two assertions #459 removed, and why:

* the Codex→Claude fallback was pinned by bare term co-occurrence (``"fall" in text
  and "claude" in text``) — a predicate with no polarity, satisfied by prose saying
  the fallback is forbidden;
* the ``build.md`` header was pinned to a ``>= 1.3.0`` floor, a frozen bump that only
  ever needs hand-editing. Version identity is owned tree-wide by
  ``test_assurance_filing_surfaces::test_registered_file_version_matches_its_registry_entry``.

Occurrence this tripwire cites (``code-quality`` Part C, *A new guard cites the
occurrence it prevents*): the pre-#459 form read ``"--engine codex" in text`` over the
**whole file**, so the engine declaration and the sandbox flag could drift into two
unrelated sections — or into a retirement note — and still satisfy it. Scoping the
read to the ``### Independent review`` section is the fix; the ``craft.md`` class is
*A guard over prose owns structure and negative space, never meaning* (the anchored
window half).

*Source:* CAL-703, reshaped by #459.
"""

from __future__ import annotations

import re

from tests.unit._prose import REPO_ROOT

BUILD = REPO_ROOT / "commands" / "build.md"
BUILD_CODEX = REPO_ROOT / "commands" / "build-codex.md"
REGISTRY = REPO_ROOT / "registry.yaml"

#: The live, installed command/process surface — the files a consumer repo pulls.
#: History (CHANGELOG), specs/proposals, source, and tests are deliberately excluded:
#: they legitimately record the retirement and the long-gone ``build-codex.yaml``.
_SURFACE = [
    *sorted((REPO_ROOT / "commands").glob("*.md")),
    REPO_ROOT / "process" / "harness.md",
    REPO_ROOT / "AGENTS.md",
    REPO_ROOT / "CLAUDE.md",
    REPO_ROOT / "GEMINI.md",
    REGISTRY,
]

#: The heading the review engines are declared under. A ``### `` heading, so the
#: window runs to the next ``## `` (``^## `` cannot match ``### ``) and covers the
#: whole review block including *Record the as-built spec*, where the Codex
#: invocation sits.
_ENGINE_HEADING = "### Independent review"


def _review_engine_section() -> str:
    """``### Independent review`` through the next ``## `` heading.

    Returns ``""`` when the heading is absent, so a rename fails the tripwire
    loudly rather than leaving its containment checks scanning an empty string.
    """
    text = BUILD.read_text()
    start = re.search(rf"^{re.escape(_ENGINE_HEADING)}\s*$", text, re.MULTILINE)
    if start is None:
        return ""
    rest = text[start.end() :]
    following = re.search(r"^## ", rest, re.MULTILINE)
    return (rest[: following.start()] if following is not None else rest).strip()


# --- AC-1 / AC-2: the second file is gone and unlisted ----------------------


def test_build_codex_file_removed() -> None:
    """``commands/build-codex.md`` no longer exists — it folded into ``build.md``."""
    assert not BUILD_CODEX.exists(), (
        "commands/build-codex.md must be removed — its review step folds into "
        "commands/build.md behind '--engine codex' (CAL-703)"
    )


def test_registry_does_not_list_build_codex() -> None:
    """The registry must not list ``build-codex.md`` (its entry is removed)."""
    text = REGISTRY.read_text()
    assert "build-codex" not in text, (
        "registry.yaml still references build-codex — remove its files: entry (CAL-703)"
    )


# --- AC-3: no dangling reference in the live distributed surface -------------


def test_no_build_codex_in_distributed_surface() -> None:
    """No live command/process-surface file mentions ``build-codex`` (AC-3)."""
    offenders = [
        str(p.relative_to(REPO_ROOT))
        for p in _SURFACE
        if p.exists() and "build-codex" in p.read_text()
    ]
    assert not offenders, (
        "the consolidated surface must carry no 'build-codex' reference; found in: "
        f"{offenders} (CAL-703 AC-3)"
    )


# --- The tripwire: the engine is declared where it runs, and it runs safely ---


def test_the_codex_engine_runs_read_only_from_the_worktree() -> None:
    """The review-engine section declares the Codex engine and constrains it.

    One tripwire over one rule-home (#459). Three parts:

    * **anchor** — ``### Independent review`` resolves to prose, so a heading
      rename names itself here instead of emptying every check below;
    * **terms** — the opt-in flag, the invocation, and the sandbox flag are the
      three words the engine cannot be specified without;
    * **polarity** — ``--dangerously-bypass-approvals-and-sandbox`` is asserted
      **absent from this window**. The diff and the ticket are untrusted prompt
      content (CAL-659), so the unsandboxed flag reappearing next to the
      invocation is the inversion this guard exists to catch.

    The whole-file absence of that flag, and the tree-wide shell-invocation
    identity, stay in ``test_build_command_bodies`` — this window-scoped form is
    what keeps the flag from returning *in the section that runs the engine* while
    a retirement note elsewhere keeps the file-wide sweep green.
    """
    section = _review_engine_section()
    assert section, f"commands/build.md has no {_ENGINE_HEADING!r} section"

    missing = [
        term
        for term in ("--engine codex", "codex exec", "--sandbox read-only")
        if term not in section
    ]
    assert not missing, (
        f"the {_ENGINE_HEADING!r} section no longer specifies the Codex engine: "
        f"{missing} is absent. The engine opt-in, its invocation, and its sandbox "
        "must be stated where the review actually runs (CAL-703 / CAL-659)."
    )

    assert "--dangerously-bypass-approvals-and-sandbox" not in section, (
        "the review-engine section runs Codex with approvals and sandboxing "
        "disabled — the diff and the ticket are untrusted prompt content, so "
        "prompt injection could run arbitrary host commands (CAL-659)"
    )

    codex_lines = [ln for ln in section.splitlines() if "codex exec" in ln]
    assert codex_lines, "the review-engine section must invoke 'codex exec'"
    for ln in codex_lines:
        assert 'cd "$worktree_path" &&' in ln, (
            "the 'codex exec' invocation must 'cd \"$worktree_path\"' first so Codex "
            f"reads the implementation under review, not the base checkout — got: {ln!r}"
        )
