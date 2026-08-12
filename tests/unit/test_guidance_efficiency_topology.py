"""Issue #401 active-path budgets and one-level reference topology."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
REGISTRY = ROOT / "registry.yaml"

REFERENCE_TREES = {
    "commands/harness.md": (
        "commands/harness/run.md",
        "commands/harness/routine-build.md",
        "commands/harness/routine-quality.md",
        "commands/harness/ingest.md",
    ),
    "skills/code-quality/SKILL.md": (
        "skills/code-quality/references/untrusted-fetch.md",
        "skills/code-quality/references/specialized-verification.md",
    ),
    "skills/review-discipline/SKILL.md": (
        "skills/review-discipline/references/diff-shape-checks.md",
    ),
}


def _text(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def _estimated_tokens(*relative_paths: str) -> float:
    return sum(len((ROOT / path).read_bytes()) for path in relative_paths) / 4


def _registry_entry(relative: str) -> re.Match[str] | None:
    return re.search(
        rf"^\s{{2}}{re.escape(relative)}:\s*\{{[^}}]+\}}$",
        REGISTRY.read_text(encoding="utf-8"),
        re.MULTILINE,
    )


def test_required_startup_path_fits_budget_and_keeps_hot_invariants() -> None:
    measured = _estimated_tokens("AGENTS.md", "CONTEXT.md")
    assert measured <= 6_500, f"required startup path is {measured:.1f} estimated tokens"

    process = _text("AGENTS.md")
    for invariant in (
        "The tracker issue is the front door",
        "worktree",
        "Test-first",
        "measuring test",
        "independent review",
        "The builder writes the change spec",
        "reviewer records what shipped",
    ):
        assert invariant.lower() in process.lower(), f"hot root lost {invariant!r}"


def test_required_reference_roots_link_directly_to_every_conditional_file() -> None:
    for root, references in REFERENCE_TREES.items():
        root_text = _text(root)
        for reference in references:
            assert (ROOT / reference).is_file(), f"missing required reference {reference}"
            assert reference in root_text, f"{root} does not directly link {reference}"


def test_every_conditional_reference_is_versioned_registered_and_non_orphaned() -> None:
    expected = {reference for references in REFERENCE_TREES.values() for reference in references}
    discovered = {
        path.relative_to(ROOT).as_posix()
        for pattern in (
            "commands/harness/*.md",
            "skills/code-quality/references/*.md",
            "skills/review-discipline/references/*.md",
        )
        for path in ROOT.glob(pattern)
    }
    assert discovered == expected, (
        f"conditional reference set drifted: missing={expected - discovered}, "
        f"orphaned={discovered - expected}"
    )

    for root, references in REFERENCE_TREES.items():
        root_text = _text(root)
        for reference in references:
            text = _text(reference)
            header = re.search(r"guidance:([\w-]+)@([\d.]+)", text)
            assert header, f"{reference} has no guidance version header"
            entry = _registry_entry(reference)
            assert entry, f"{reference} is not registered"
            assert f"id: {header.group(1)}" in entry.group(0)
            assert f"version: {header.group(2)}" in entry.group(0)
            assert reference in root_text
            for nested in expected:
                assert nested not in text, f"{reference} nests conditional reference {nested}"


def test_each_activated_harness_command_payload_fits_budget() -> None:
    for reference in REFERENCE_TREES["commands/harness.md"]:
        measured = _estimated_tokens("commands/harness.md", reference)
        assert measured <= 5_000, (
            f"/harness router + {reference} is {measured:.1f} estimated tokens"
        )


def test_hot_skill_cores_fit_budget() -> None:
    for core in ("skills/code-quality/SKILL.md", "skills/review-discipline/SKILL.md"):
        measured = _estimated_tokens(core)
        assert measured <= 5_000, f"{core} is {measured:.1f} estimated tokens"


def test_reviewer_and_steward_role_bodies_are_concise() -> None:
    forbidden = {
        "agents/reviewer.md": ("Review engine", "bwrap", "wall_clock_budget_minutes"),
        "agents/steward.md": (
            "Lenses:",
            "Test-coverage quantity",
            "Architecture assessment rubric",
        ),
    }
    for relative, banned in forbidden.items():
        text = _text(relative)
        words = len(text.split())
        assert words <= 650, f"{relative} has {words} words"
        offenders = [token for token in banned if token in text]
        assert not offenders, f"{relative} duplicates owned detail: {offenders}"
