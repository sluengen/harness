"""#377 — the agent-led build flow carries the assurance policy.

The harness ledger is paused, but its intended quality boundary must remain in
the distributed guidance.  These checks lock the operator-facing contract,
where a future install can rely on it without the harness runtime.
"""

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
BUILD = REPO_ROOT / "commands" / "build.md"
REVIEWER = REPO_ROOT / "agents" / "reviewer.md"
ARCHITECT = REPO_ROOT / "agents" / "architect.md"
CONTEXT_TEMPLATE = REPO_ROOT / "templates" / "CONTEXT.template.md"


def test_build_defines_the_three_assurance_levels_and_safe_default() -> None:
    """Unknown assurance remains reviewable rather than becoming trivial."""
    text = BUILD.read_text().lower()

    for level in ("trivial", "simple", "complex"):
        assert level in text
    assert "default to `simple`" in text
    assert "trivial" in text and "certif" in text
    assert "assurance.trivial_certify" in text
    assert "git add -a && git write-tree" in text
    assert "invalidates the certificate" in text
    assert "no user-facing or as-built-record surface" in text
    assert "trivial_certify" in CONTEXT_TEMPLATE.read_text()


def test_build_isolates_design_and_review_from_implementation() -> None:
    """Complex design and every non-trivial review get a fresh agent context."""
    text = " ".join(BUILD.read_text().lower().split())

    assert "design sub-agent" in text
    assert "reviewer sub-agent" in text
    assert "do not pass the implementer's conversation" in text
    assert "inline review" not in text


def test_build_requires_visual_evidence_for_user_facing_changes() -> None:
    """A UI pass renders real state and supplies its final captures to review."""
    text = " ".join(BUILD.read_text().lower().split())

    for phrase in (
        "realistic seeded state",
        "screenshot",
        "either side of every breakpoint",
        "reference or the applicable design archetype",
        "visual evidence",
    ):
        assert phrase in text


def test_design_and_reviewer_roles_receive_the_agent_led_contract() -> None:
    """The dispatched roles know the required isolation and visual inputs."""
    assert "fresh context" in ARCHITECT.read_text().lower()
    reviewer_text = REVIEWER.read_text().lower()
    assert "visual evidence" in reviewer_text
    assert "screenshot" in reviewer_text
