"""Issue #401 tracker ownership and active-backend guidance guards."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _read(relative: str) -> str:
    return (ROOT / relative).read_text()


def test_tracker_create_is_the_single_filing_contract() -> None:
    text = _read("skills/tracker/SKILL.md")
    assert "deliberate exception" not in text
    for required in (
        "UTF-8 body file",
        "mandatory initial Todo placement",
        "canonical identifier and URL",
        "partial creation",
        "Never create a duplicate",
    ):
        assert required in text, f"tracker.create is missing {required!r}"


def test_active_repo_guidance_does_not_direct_agents_to_linear() -> None:
    # The repo-active surface: what this GitHub-tracked repo's own agents read.
    # ``commands/harness.md`` was a member until #435 retired it.
    corpus = (
        "CONTEXT.md",
        "commands/promote.md",
        "commands/routine.md",
        "settings/harness.json",
        ".claude/settings.json",
    )
    assert len(corpus) >= 5, "the sweep's corpus was emptied — it now measures nothing"
    active = {relative: _read(relative) for relative in corpus}
    forbidden = (
        "LINEAR_API_KEY",
        "Linear ticket",
        "Linear mutation",
        "Linear credentials",
        "repo.linear",
        "linear_cli",
        "linear_token",
        "Linear",
    )
    offenders = {
        relative: [token for token in forbidden if token in text]
        for relative, text in active.items()
        if any(token in text for token in forbidden)
    }
    assert not offenders, f"active GitHub guidance still directs agents to Linear: {offenders}"
