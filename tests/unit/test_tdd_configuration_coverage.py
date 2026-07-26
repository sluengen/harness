"""#221 — RED gains a rule: cover a new stage under every supported configuration.

Surfaced by an ``/assess code`` steward pass (2026-07-26, systemic insight
CODE-INSIGHT-2, report ``assessments/2026-07-26-code.md``): a new lifecycle
stage ships with a thorough unit suite of its own, while the suites that walk
the lifecycle *end to end under a configuration* — a layer switched off, a
tracker absent, a breaker tripped — are never extended. A whole supported
configuration then goes unproven, precisely when a new mandatory stage was
inserted into it.

The rule joins two siblings in RED that name the same failure shape in other
guises: "Cover the active loop, not just its exit" (the live-state path
untested behind a green suite) and "Cover each of a guard's conditions, not
just the one that trips first" (one trigger path untested behind a covered
guard). This one is the configuration axis: the stage is covered, the
configuration is not.

Acceptance criteria (this ticket):

* **AC-1** — the skill states the rule: on adding a stage to a documented
  lifecycle, grep for the suites exercising the sibling stages under a
  configuration or layer and add the new stage's case to each, naming those
  suites in the change spec; a stage's own unit suite proves the stage, not
  that the lifecycle still holds under every configuration the repo claims to
  support. Proven by
  :func:`test_skill_states_the_configuration_coverage_rule`.
* **AC-2** — the rule sits in the RED section, immediately after the
  guard-conditions bullet. Proven by
  :func:`test_rule_sits_after_the_guard_conditions_bullet`.
* **AC-3** — the skill's version header is bumped and matches its
  ``registry.yaml`` entry (registry two-place self-version: header +
  ``files:`` row). Proven by :func:`test_version_bumped_and_matches_registry`.

The placement test asserts an **ordinal over the bullet titles derived from
the file**, not a hardcoded neighbour pair — ``code-quality``'s "a guard
derives its subjects, it does not list them". A fifth RED bullet added after
this one leaves it green; a rename of an anchor fails a *named* existence
assertion rather than an opaque lookup error.
"""

from __future__ import annotations

import re
from pathlib import Path

# ``tests/unit/test_*.py`` → ``parents[2]`` is the repo (or worktree) root.
_REPO_ROOT = Path(__file__).resolve().parents[2]
_SKILL = _REPO_ROOT / "skills" / "test-driven-development" / "SKILL.md"
_REGISTRY = _REPO_ROOT / "registry.yaml"

_PRIOR_VERSION = "0.5.0"

_NEW_BULLET_TITLE_PREFIX = "Cover the new stage under every configuration"
_GUARD_BULLET_TITLE_PREFIX = "Cover each of a guard's"
_ACTIVE_LOOP_BULLET_TITLE_PREFIX = "Cover the active loop"
_REAL_INPUTS_BULLET_TITLE_PREFIX = "Use real inputs"

# Vocabulary that would leak this repo's stack into prose the installer copies
# verbatim into repos it does not control.
_STACK_VOCABULARY = (
    "pytest",
    "python",
    "typer",
    "sqlite",
    "linear",
    "harness",
    "docker",
)


def _skill_text() -> str:
    return _SKILL.read_text(encoding="utf-8")


def _red_section(text: str) -> str:
    """The RED body: between its heading and the "Verify RED" heading."""
    start = text.index("### RED")
    end = text.index("### Verify RED", start)
    return text[start:end]


def _red_bullet_titles(text: str) -> list[str]:
    """The RED bullets' bolded titles, in document order.

    The subject set is *derived* from the file rather than listed here, so the
    placement assertion below survives any later addition to RED.
    """
    return re.findall(r"^\*\*(.+?)\*\*", _red_section(text), re.MULTILINE)


def _bullet(text: str, title_prefix: str) -> str:
    """A RED bullet sliced to its own paragraph.

    Scoping matters: "condition", "green" and "untested" all already appear
    elsewhere in RED, so an unscoped search would pass against a bullet that
    was never written.
    """
    red = _red_section(text)
    m = re.search(rf"^\*\*{re.escape(title_prefix)}", red, re.MULTILINE)
    assert m, (
        f"test-driven-development RED has no bullet titled {title_prefix!r} "
        "(#221 AC-1)."
    )
    rest = red[m.start() :]
    nxt = re.search(r"\n\n", rest)
    return rest[: nxt.start()] if nxt else rest


def test_skill_states_the_configuration_coverage_rule() -> None:
    """The skill states the configuration-coverage rule (AC-1)."""
    bullet = _bullet(_skill_text(), _NEW_BULLET_TITLE_PREFIX).lower()

    # The trigger: a change adds a stage to a documented lifecycle.
    assert "adds a stage" in bullet and "lifecycle" in bullet, (
        "the rule must name its trigger — a change adding a stage to a "
        "documented lifecycle"
    )
    # The action: grep for the suites exercising the sibling stages.
    assert "grep" in bullet and "sibling stages" in bullet, (
        "the rule must direct a grep for the suites exercising the sibling "
        "stages"
    )
    # Where to look: the configuration/layer declarations.
    assert "`context.md`" in bullet, (
        "the rule must point at CONTEXT.md as where a repo declares its "
        "configurations"
    )
    assert "`layers:`" in bullet and "`tracker:`" in bullet, (
        "the rule must name the layers: / tracker: keys as the places to look"
    )
    # The obligation: extend each suite...
    assert "add the new stage's case to each" in bullet, (
        "the rule must require adding the new stage's case to each such suite"
    )
    # ...and declare which ones, so a reviewer can check it.
    assert "name those suites in the change spec" in bullet, (
        "the rule must require naming those suites in the change spec"
    )
    # The reason: a stage's own suite proves the stage, not the lifecycle.
    # Anchored on the body's phrasing, not "every configuration" — that phrase
    # is in the bullet's own title, so it would satisfy the assertion even
    # with the reason deleted.
    assert "own unit suite" in bullet and "the repo claims to support" in bullet, (
        "the rule must state that a stage's own unit suite does not prove the "
        "lifecycle holds under every configuration the repo claims to support"
    )
    # The most expensive case: a stage other stages now refuse without.
    assert "refuse" in bullet, (
        "the rule must name the expensive case — a stage that other stages "
        "now refuse without"
    )


def test_rule_sits_after_the_guard_conditions_bullet() -> None:
    """The rule sits immediately after the guard-conditions bullet (AC-2)."""
    titles = _red_bullet_titles(_skill_text())

    def _index_of(prefix: str) -> int:
        matches = [i for i, t in enumerate(titles) if t.startswith(prefix)]
        assert matches, (
            f"RED must carry a bullet titled {prefix!r} — the placement "
            "assertion is anchored on it"
        )
        return matches[0]

    # Anti-vacuity: assert each anchor exists (with its own message) before
    # asserting an ordinal over them, so an upstream rename fails for the
    # reason it actually happened.
    real_inputs = _index_of(_REAL_INPUTS_BULLET_TITLE_PREFIX)
    active_loop = _index_of(_ACTIVE_LOOP_BULLET_TITLE_PREFIX)
    guard = _index_of(_GUARD_BULLET_TITLE_PREFIX)
    new_rule = _index_of(_NEW_BULLET_TITLE_PREFIX)

    assert real_inputs < active_loop < guard, (
        "RED's existing bullets must keep their order — real inputs, then the "
        "active loop, then a guard's conditions"
    )
    assert new_rule == guard + 1, (
        "the configuration-coverage rule must sit immediately after the "
        "guard-conditions bullet in RED"
    )


def test_version_bumped_and_matches_registry() -> None:
    """The header is bumped past 0.5.0 and matches the registry row (AC-3)."""
    text = _skill_text()
    header_m = re.search(
        r"^<!-- guidance:test-driven-development@([\d.]+) -->", text, re.MULTILINE
    )
    assert header_m, "test-driven-development/SKILL.md must carry its version header"
    header_version = header_m.group(1)
    assert header_version != _PRIOR_VERSION, (
        f"the header version must be bumped past {_PRIOR_VERSION} for this "
        "ticket's content addition"
    )

    registry_text = _REGISTRY.read_text(encoding="utf-8")
    row_m = re.search(
        r"skills/test-driven-development/SKILL\.md:\s*\{[^}]*version:\s*([\d.]+)",
        registry_text,
    )
    assert row_m, "registry.yaml must carry a test-driven-development row"
    assert row_m.group(1) == header_version, (
        "registry.yaml's test-driven-development version must match the "
        "SKILL.md header (registry two-place self-version)"
    )


def test_rule_is_universal() -> None:
    """The bullet carries no stack vocabulary (distributed-prose boundary)."""
    bullet = _bullet(_skill_text(), _NEW_BULLET_TITLE_PREFIX).lower()
    for term in _STACK_VOCABULARY:
        assert term not in bullet, (
            f"the rule is copied verbatim into repos on other stacks; it must "
            f"not name {term!r}"
        )
