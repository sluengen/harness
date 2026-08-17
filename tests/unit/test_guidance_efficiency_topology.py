"""Issue #401 active-path budgets and one-level reference topology."""

from __future__ import annotations

import re

from tests.unit._prose import REPO_ROOT

REGISTRY = REPO_ROOT / "registry.yaml"

#: A root document and the conditional references it links one level down. The
#: ``commands/harness.md`` tree was the fourth entry until #435 retired the
#: ``/harness`` namespace; the two skill trees below are the whole set now.
REFERENCE_TREES = {
    "skills/code-quality/SKILL.md": (
        "skills/code-quality/references/untrusted-fetch.md",
        "skills/code-quality/references/specialized-verification.md",
    ),
    "skills/review-discipline/SKILL.md": (
        "skills/review-discipline/references/diff-shape-checks.md",
        "skills/review-discipline/references/craft.md",
        "skills/review-discipline/references/fail-stop-rule.md",
    ),
}


#: The fraction of every declared cap below that must stay unspent. A budget
#: enforced at exactly its cap surfaces its pressure only as a red gate, on
#: whichever unrelated change happens to write the sentence that crosses it —
#: and at that moment the cheapest repair wins over the right one (#461, from
#: the proposals ledger). Holding a tenth back moves the signal forward by a
#: tenth of each cap below — 700 estimated tokens (2,800 B) on the startup path,
#: 500 (2,000 B) on a hot core — which is a paragraph to think with rather than a
#: byte to trim.
#:
#: Nothing pins this fraction, and nothing can: a bound with slack cannot be
#: falsified by loosening it, so setting this to ``0.0`` leaves the suite green
#: (measured at #461's review). The reserve is a recorded decision, not a
#: mechanism that defends itself, and erasing it is the cheapest repair the next
#: budget failure will offer.
BUDGET_RESERVE = 0.10

#: The required startup path's cap. Raised 6,500 → 7,000 by #461, deliberately
#: and with its reason recorded rather than as a red-gate concession:
#: ``tests/unit/test_process_doc_hook_inventory.py`` obliges ``process/harness.md``
#: — byte-mirrored into ``AGENTS.md`` — to carry one row per tracked hook, in
#: both directions, so installing a hook *mandatorily* grows this path. The two
#: hook tables are 2,248 B of the pair today (the *Enforcement hooks* section
#: around them is 4,651 B, but that guard obliges the rows, not the prose), and
#: neither existed when 6,500 was set: the cap came from #401 at ``bd80c2d`` and
#: the tables from #436 at ``ab406ac``. A cap another guard forces its subject
#: past is misconfigured, not merely tight.
STARTUP_TOKEN_CAP = 7_000

#: The per-file cap on a hot skill core — a file read on every review or every
#: build, whose whole cost is paid before the work starts.
HOT_SKILL_CORE_TOKEN_CAP = 5_000


def _text(relative: str) -> str:
    return (REPO_ROOT / relative).read_text(encoding="utf-8")


def _assert_within_budget(subject: str, measured: float, cap: int) -> None:
    """The one bound both budgets below are enforced through.

    Folded into the enforcing assertion rather than added beside it: a bare
    ``measured <= cap`` left standing next to a stricter reserve check is
    subsumed by it, and a subsumed assertion is decoration that reads as a
    second measure.
    """
    limit = cap * (1 - BUDGET_RESERVE)
    assert measured <= limit, (
        f"{subject} is {measured:.1f} estimated tokens, past the {limit:.1f} "
        f"left by the {BUDGET_RESERVE:.0%} reserve on its declared cap of "
        f"{cap:,}. Relieve the subject, or raise the cap with its reason "
        f"recorded beside the constant."
    )


def _estimated_tokens(*relative_paths: str) -> float:
    return sum(len((REPO_ROOT / path).read_bytes()) for path in relative_paths) / 4


def _registry_entry(relative: str) -> re.Match[str] | None:
    return re.search(
        rf"^\s{{2}}{re.escape(relative)}:\s*\{{[^}}]+\}}$",
        REGISTRY.read_text(encoding="utf-8"),
        re.MULTILINE,
    )


def test_required_startup_path_fits_budget_and_keeps_hot_invariants() -> None:
    measured = _estimated_tokens("AGENTS.md", "CONTEXT.md")
    _assert_within_budget("required startup path", measured, STARTUP_TOKEN_CAP)

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
            assert (REPO_ROOT / reference).is_file(), f"missing required reference {reference}"
            assert reference in root_text, f"{root} does not directly link {reference}"


def test_every_conditional_reference_is_versioned_registered_and_non_orphaned() -> None:
    expected = {reference for references in REFERENCE_TREES.values() for reference in references}
    discovered = {
        path.relative_to(REPO_ROOT).as_posix()
        for pattern in (
            "skills/code-quality/references/*.md",
            "skills/review-discipline/references/*.md",
        )
        for path in REPO_ROOT.glob(pattern)
    }
    assert expected, "the conditional-reference set is empty — this sweep measures nothing"
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


# The activated-payload budget (``/harness`` router + one routed reference
# <= 5,000 estimated tokens) went with the router: #435 retired
# ``commands/harness.md`` and the four references it routed to, and that command
# was the only root the budget was ever set against. The two surviving reference
# trees are skills, whose cores are budgeted by
# ``test_hot_skill_cores_fit_budget`` below; re-pointing the router budget at
# them would not be re-homing a guard, it would be inventing a bound nothing has
# ever held them to (both exceed it today).


def test_hot_skill_cores_fit_budget() -> None:
    for core in ("skills/code-quality/SKILL.md", "skills/review-discipline/SKILL.md"):
        _assert_within_budget(core, _estimated_tokens(core), HOT_SKILL_CORE_TOKEN_CAP)


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
