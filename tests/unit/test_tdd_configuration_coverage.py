"""RED carries a rule: cover a new stage under every supported configuration.

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

**What this module asserts, after #459.**

* **One tripwire** over one rule-home: the ``**Cover the new stage under every
  configuration…`` bullet of ``skills/test-driven-development/SKILL.md`` →
  ``### RED``, sliced to its own paragraph and read for a small term set the
  rule cannot be stated without.
* **A derived ordinal** placing that bullet immediately after the
  guard-conditions bullet, over titles derived from the file rather than a
  hardcoded neighbour pair (``code-quality`` → *A guard derives its subjects; it
  does not list them*). A fifth RED bullet added after this one leaves it green;
  a rename of an anchor fails a *named* existence assertion rather than an
  opaque lookup error.
* **Structural correspondence**: the header version and its ``registry.yaml``
  row agree.
* **Negative space**: the bullet leaks no stack vocabulary into prose the
  installer copies verbatim into repos on other stacks.

The rule is an obligation — grep the sibling suites, extend each, name them in
the change spec — so most of it has no polarity to read. Its one directional
clause is the reason it exists (*a stage's own unit suite does* **not** *prove
the lifecycle holds under every configuration*), and that negation is asserted
anchored to the verb it governs. The eight exact-phrase containments this
replaced carried no direction at all: a bullet inverting the rule while reusing
its vocabulary passed every one of them (ADR 0016; ``code-quality`` Part C → *A
guard over prose owns structure and negative space, never meaning*).
"""

from __future__ import annotations

import re

from tests.unit._prose import REPO_ROOT

_SKILL = REPO_ROOT / "skills" / "test-driven-development" / "SKILL.md"
_REGISTRY = REPO_ROOT / "registry.yaml"

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


def test_the_configuration_coverage_rule_has_a_home() -> None:
    """RED's configuration-coverage bullet states the rule, with its direction.

    Four conjuncts and a negation, all inside the bullet's own paragraph — the
    scoping matters, since ``lifecycle``, ``grep`` and ``change spec`` all have
    neighbours in RED that could supply them.

    ``lifecycle`` is the trigger's subject; ``grep`` and ``sibling`` are the
    action, and without them the rule says "test more" and names no move;
    ``layers:`` is where a repo declares the configurations that make the set of
    suites finite; and ``change spec`` is what makes the extension reviewable
    rather than a private intention. The negation is the reason clause: a
    stage's own suite does **not** prove the lifecycle still holds, which is the
    one place this bullet has a direction to lose.
    """
    bullet = _bullet(_skill_text(), _NEW_BULLET_TITLE_PREFIX).lower()

    for term, why in (
        ("lifecycle", "the rule is triggered by a stage added to a documented "
                      "lifecycle; unscoped, it is advice about testing"),
        ("grep", "the rule must name the move — grep for the suites that "
                 "already exercise the sibling stages"),
        ("sibling", "the subject is the sibling stages' suites, not the new "
                    "stage's own"),
        ("layers:", "the rule must point at where a repo declares the "
                    "configurations, or the set of suites to extend is unbounded"),
        ("change spec", "the extended suites are named in the change spec, "
                        "which is what makes the obligation reviewable"),
    ):
        assert term in bullet, (
            f"RED's configuration-coverage bullet no longer names {term!r} — {why}"
        )

    assert re.search(r"\b(?:not|never|no)\b(?:\W+\w+){0,3}?\W+prov\w+", bullet), (
        "the bullet no longer states that a stage's own unit suite does *not* "
        "prove the lifecycle holds under every configuration. That clause is "
        "the rule's whole direction: without it a bullet asserting the opposite "
        "— that the stage's own suite is sufficient — reuses every term above "
        "and reads the same to this guard."
    )


def test_rule_sits_after_the_guard_conditions_bullet() -> None:
    """The rule sits immediately after the guard-conditions bullet."""
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


def test_version_matches_registry() -> None:
    """The skill's stamp and its registry row move together.

    #459 dropped the ``header != "0.5.0"`` half. A frozen prior version is a
    museum assertion: it was live for exactly one commit, and every version the
    tree can now hold satisfies it, so it can no longer fail for any edit. What
    is durable is the **agreement** — a stamp that drifts from its registry
    entry is how a consuming repo pulls a file whose version says it already has
    it.
    """
    text = _skill_text()
    header_m = re.search(
        r"^<!-- guidance:test-driven-development@([\d.]+) -->", text, re.MULTILINE
    )
    assert header_m, "test-driven-development/SKILL.md must carry its version header"
    header_version = header_m.group(1)

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
