"""#353 — the trivial-diff classifier and the allowlist it reads.

Two properties carry the whole safety argument of the fast path, and each is
easy to satisfy in a way that measures nothing:

**Order.** A restricted path must be refused *before* the allowlist is
consulted. A table whose rows all use an allowlist that does not match the path
would pass against a classifier with the checks in either order, so every row
that matters here supplies an allowlist that **does** match — ``specs/**`` for a
feature spec, ``CONTEXT.md`` for the config, ``harness/**`` for a source file.

**Coverage.** The table is hand-written, and a hand-written tuple loses a member
silently. Two floors sit outside the parametrization: one deriving the covered
surfaces from :data:`~harness.trivial_diff.RESTRICTED_PATTERNS` and asserting
they are exactly :data:`~harness.trivial_diff.RESTRICTED_SURFACES`, and one
sweeping *every* production pattern through the same predicate. An empty
parametrize set reports ``1 skipped`` rather than a failure, so the floors are
not optional decoration.

Everything drives :func:`~harness.trivial_diff.path_ineligibility` — the same
function :func:`~harness.trivial_diff.classify_paths` calls. There is no second
implementation of the predicate in this file.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from harness.trivial_diff import (
    RESTRICTED_PATTERNS,
    RESTRICTED_SURFACES,
    AllowlistConfig,
    classify_paths,
    ineligible,
    load_trivial_allowlist,
    matches,
    path_ineligibility,
    validate_pattern,
)

# ---------------------------------------------------------------------------
# Pattern matching
# ---------------------------------------------------------------------------

_MATCH_CASES: list[tuple[str, str, str, bool]] = [
    ("dir-rule-child", "docs/guide.md", "docs/**", True),
    ("dir-rule-deep", "docs/a/b/c.md", "docs/**", True),
    ("dir-rule-self", "docs", "docs/**", True),
    ("dir-rule-sibling-prefix", "docsx/guide.md", "docs/**", False),
    ("dir-rule-elsewhere", "other/guide.md", "docs/**", False),
    ("ext-rule-root", "setup.py", "*.py", True),
    ("ext-rule-nested", "harness/cli/close.py", "*.py", True),
    ("ext-rule-miss", "notes.md", "*.py", False),
    ("ext-rule-not-a-prefix-match", "spy.python", "*.py", False),
    ("exact-hit", "CONTEXT.md", "CONTEXT.md", True),
    ("exact-nested-is-not-a-hit", "sub/CONTEXT.md", "CONTEXT.md", False),
    ("star-does-not-cross-a-slash", "docs/a/b.md", "docs/*", False),
]


@pytest.mark.parametrize(
    ("path", "pattern", "expected"),
    [(p, pat, e) for _, p, pat, e in _MATCH_CASES],
    ids=[name for name, _, _, _ in _MATCH_CASES],
)
def test_pattern_matching_table(path: str, pattern: str, expected: bool) -> None:
    """The three forms, and the two a glob library would have decided for us."""
    assert matches(path, pattern) is expected


def test_the_matching_table_covers_all_three_forms() -> None:
    """Floor outside the parametrization: an emptied table reads as skipped."""
    patterns = {pat for _, _, pat, _ in _MATCH_CASES}
    assert any(p.endswith("/**") for p in patterns), "no directory rule exercised"
    assert any(p.startswith("*.") for p in patterns), "no extension rule exercised"
    assert any(
        "*" not in p for p in patterns
    ), "no exact rule exercised"


# ---------------------------------------------------------------------------
# Pattern validation
# ---------------------------------------------------------------------------

_VALIDATION_CASES: list[tuple[str, str, str | None]] = [
    ("well-formed-dir", "docs/**", None),
    ("well-formed-ext", "*.md", None),
    ("well-formed-exact", "CHANGELOG.md", None),
    ("empty", "", "empty"),
    ("everything", "**", "empty_prefix"),
    ("absolute-everything", "/**", "absolute"),
    ("star-prefix-everything", "*/**", "bad_glob"),
    ("absolute", "/etc/passwd", "absolute"),
    ("traversal", "../etc/passwd", "traversal"),
    ("traversal-mid", "docs/../harness/**", "traversal"),
    ("backslash", "docs\\**", "forbidden_char"),
    ("hash", "docs#**", "forbidden_char"),
    ("nul", "docs\0", "forbidden_char"),
    ("whitespace", "docs /**", "whitespace"),
    ("interior-star", "docs/*/x.md", "bad_glob"),
    ("bare-star", "*", "bad_glob"),
    ("ext-with-slash", "*.md/x", "bad_glob"),
]


@pytest.mark.parametrize(
    ("pattern", "tag"),
    [(p, t) for _, p, t in _VALIDATION_CASES],
    ids=[name for name, _, _ in _VALIDATION_CASES],
)
def test_pattern_validation_table(pattern: str, tag: str | None) -> None:
    assert validate_pattern(pattern) == tag


def test_no_pattern_that_would_match_everything_is_expressible() -> None:
    """Floor outside the parametrization, on the one rejection that is load-bearing.

    A pattern matching every path is what a run would add to its own CONTEXT.md
    to certify itself. Asserted here as a property over candidate spellings
    rather than as three table rows, so a spelling nobody listed still has to be
    rejected by the validator or caught by the sweep below.
    """
    for spelling in ("**", "/**", "*/**", ".**", "*"):
        assert validate_pattern(spelling) is not None, (
            f"{spelling!r} is accepted as a pattern; if it also matches an "
            f"arbitrary path it opens the gate to everything"
        )


def test_no_accepted_pattern_matches_an_unrelated_path() -> None:
    """The property behind the validator, measured rather than assumed.

    ``validate_pattern`` rejecting a spelling only helps if the spellings it
    *accepts* cannot match everything. This drives both functions together: for
    each accepted candidate, a path that shares nothing with it must not match.
    """
    accepted = [
        p
        for p in (
            "docs/**",
            "*.md",
            "CHANGELOG.md",
            "a/b/**",
            "./**",  # accepted, and it must still match nothing outside "./"
            "**",
            "/**",
            "*/**",
            "*",
        )
        if validate_pattern(p) is None
    ]
    assert accepted, "the candidate set must contain something acceptable"
    for pattern in accepted:
        assert not matches("harness/cli/close.py", pattern), (
            f"the accepted pattern {pattern!r} matches an unrelated source file"
        )


# ---------------------------------------------------------------------------
# Path eligibility — the ordering property
# ---------------------------------------------------------------------------

#: ``(id, path, allowlist, expected_reason)``. Every restricted row deliberately
#: supplies an allowlist that **matches the path**: a row whose allowlist misses
#: would answer ``restricted_path`` under either check order and would therefore
#: prove nothing about the ordering this table exists to pin.
_ELIGIBILITY_CASES: list[tuple[str, str, list[str], str | None]] = [
    ("source-under-a-matching-rule", "harness/x.py", ["harness/**"], "restricted_path"),
    ("feature-spec-under-a-matching-rule", "specs/features/run-ledger.md", ["specs/**"], "restricted_path"),  # noqa: E501
    ("decision-under-a-matching-rule", "specs/decisions/0007-design-verb.md", ["specs/**"], "restricted_path"),  # noqa: E501
    ("config-under-an-exact-rule", "CONTEXT.md", ["CONTEXT.md"], "restricted_path"),
    ("security-under-a-matching-rule", "SECURITY.md", ["SECURITY.md"], "restricted_path"),
    ("persistence-under-a-matching-rule", "db/schema.sql", ["db/**"], "restricted_path"),
    ("guidance-under-a-matching-rule", "skills/x/SKILL.md", ["skills/**"], "restricted_path"),
    ("public-contract-under-a-matching-rule", "scripts/verify.sh", ["scripts/**"], "restricted_path"),  # noqa: E501
    ("allowlisted-doc", "docs/notes.md", ["docs/**"], None),
    ("allowlisted-exact", "CHANGELOG.md", ["CHANGELOG.md"], None),
    ("unknown-path", "tools/thing.md", ["docs/**"], "unlisted_path"),
    ("unknown-path-empty-allowlist", "docs/notes.md", [], "unlisted_path"),
]


@pytest.mark.parametrize(
    ("path", "allowlist", "expected"),
    [(p, a, e) for _, p, a, e in _ELIGIBILITY_CASES],
    ids=[name for name, _, _, _ in _ELIGIBILITY_CASES],
)
def test_path_eligibility_table(
    path: str, allowlist: list[str], expected: str | None
) -> None:
    """Every path must be allowlisted, and a restricted one is refused regardless."""
    assert path_ineligibility(path, allowlist) == expected


def test_the_eligibility_table_covers_every_restricted_surface() -> None:
    """Floor outside the parametrization, derived from the production table.

    An emptied or thinned parametrize set reads as ``skipped``, not as a
    failure, so the sweep's breadth needs its own assertion. The surfaces are
    derived from ``RESTRICTED_PATTERNS`` rather than listed again here, so a new
    surface added to the production table without a row fails this test.
    """
    covered = {
        surface
        for _, path, allow, expected in _ELIGIBILITY_CASES
        if expected == "restricted_path"
        for pattern, surface in RESTRICTED_PATTERNS
        if matches(path, pattern)
    }
    assert covered == RESTRICTED_SURFACES, (
        f"the eligibility table does not exercise every restricted surface: "
        f"missing {sorted(RESTRICTED_SURFACES - covered)}"
    )


def test_every_restricted_pattern_is_reachable_through_the_predicate() -> None:
    """The second floor: every production pattern, through the same function.

    Derived from ``RESTRICTED_PATTERNS`` itself, so a pattern added without a
    hand-written row is still swept. Each synthesised path is offered with an
    allowlist that matches it exactly, so a pattern that had somehow stopped
    vetoing would answer ``None`` here rather than ``restricted_path``.
    """
    unreachable = []
    for pattern, _surface in RESTRICTED_PATTERNS:
        path = _synthesise(pattern)
        assert matches(path, pattern), f"bad synthesis for {pattern!r}: {path!r}"
        if path_ineligibility(path, [path]) != "restricted_path":
            unreachable.append((pattern, path))
    assert not unreachable, f"restricted patterns that no longer veto: {unreachable}"


def test_the_restricted_table_names_no_surface_outside_the_declared_set() -> None:
    """Both directions of the derivation, so neither side can drift alone."""
    assert {surface for _, surface in RESTRICTED_PATTERNS} == RESTRICTED_SURFACES


def _synthesise(pattern: str) -> str:
    """A path that matches ``pattern`` — the inverse the sweep above needs."""
    if pattern.endswith("/**"):
        return pattern[: -len("/**")] + "/probe.txt"
    if pattern.startswith("*."):
        return "probe" + pattern[1:]
    return pattern


# ---------------------------------------------------------------------------
# Whole-diff classification
# ---------------------------------------------------------------------------

_VALID = AllowlistConfig(("docs/**", "CHANGELOG.md"), True, None)


def test_a_wholly_allowlisted_diff_is_eligible() -> None:
    result = classify_paths(["docs/a.md", "CHANGELOG.md"], _VALID)
    assert result.eligible
    assert result.reason is None
    assert result.eligible_paths == ("CHANGELOG.md", "docs/a.md")
    assert result.allowlist == ("docs/**", "CHANGELOG.md")


def test_one_restricted_path_among_many_makes_the_whole_diff_ineligible() -> None:
    """The *whole* diff is judged, not a sample of it.

    The restricted path is deliberately last in sort order, so a classifier that
    inspected only the first changed path would report this diff eligible.
    """
    result = classify_paths(["docs/a.md", "harness/cli/close.py"], _VALID)
    assert not result.eligible
    assert result.reason == "restricted_path"
    assert result.offending_paths == ("harness/cli/close.py",)
    assert result.eligible_paths == ()


def test_one_unlisted_path_among_many_makes_the_whole_diff_ineligible() -> None:
    result = classify_paths(["docs/a.md", "tools/x.md"], _VALID)
    assert not result.eligible
    assert result.reason == "unlisted_path"
    assert result.offending_paths == ("tools/x.md",)


def test_an_invalid_allowlist_refuses_before_any_path_is_read() -> None:
    """Without a policy nothing is trivial, whatever the diff says."""
    result = classify_paths(["docs/a.md"], AllowlistConfig((), False, "no_block"))
    assert result.reason == "no_allowlist"
    assert result.offending_paths == ()


def test_a_diff_that_changed_nothing_is_not_certifiable() -> None:
    assert classify_paths([], _VALID).reason == "empty_diff"


def test_offending_paths_are_bounded() -> None:
    """A thousand-file refusal reaches a tracker comment; it must not be one."""
    result = classify_paths([f"tools/f{i:04d}.md" for i in range(60)], _VALID)
    assert result.reason == "unlisted_path"
    assert len(result.offending_paths) == 20


def test_the_verb_side_reasons_share_one_shape() -> None:
    """``gate_not_configured`` / ``no_base_sha`` / ``diff_unreadable`` are the
    verb's to produce, and they come back as the same dataclass every other
    refusal does — so a consumer reads one type."""
    for reason in ("gate_not_configured", "no_base_sha", "diff_unreadable"):
        result = ineligible(reason)  # type: ignore[arg-type]
        assert not result.eligible
        assert result.reason == reason
        assert result.eligible_paths == ()


# ---------------------------------------------------------------------------
# The configuration surface
# ---------------------------------------------------------------------------


def _context(tmp_path: Path, body: str | None) -> Path:
    root = tmp_path / "repo"
    root.mkdir(exist_ok=True)
    if body is not None:
        (root / "CONTEXT.md").write_text(body)
    return root


_WELL_FORMED = """\
```yaml
tracker: github
assurance:
  trivial_paths:            # every changed path must match
    - CHANGELOG.md          # restricted surfaces are vetoed regardless
    - docs/**
```

Prose after the block.
"""

#: ``(id, body, valid, patterns, invalid_reason)``. The **reason** is asserted,
#: not merely the validity: every negative row answers ``valid=False``, so a
#: validity-only table cannot tell one refusal from another and would keep
#: passing while ``**`` stopped being recognised as the everything-rule. The
#: mutation run that showed this is why the column exists.
_ALLOWLIST_CASES: list[tuple[str, str | None, bool, tuple[str, ...], str | None]] = [
    ("well-formed", _WELL_FORMED, True, ("CHANGELOG.md", "docs/**"), None),
    ("no-file", None, False, (), "no_block"),
    ("no-assurance-block", "```yaml\ntracker: github\n```\n", False, (), "no_block"),
    ("no-trivial-paths-key", "```yaml\nassurance:\n  other: 1\n```\n", False, (), "no_key"),
    ("empty-list", "```yaml\nassurance:\n  trivial_paths:\n```\n", False, (), "empty"),
    (
        "everything-quoted",
        "```yaml\nassurance:\n  trivial_paths:\n    - '**'\n```\n",
        False,
        (),
        "bad_pattern:**:empty_prefix",
    ),
    (
        "bare-star",
        "```yaml\nassurance:\n  trivial_paths:\n    - **\n```\n",
        False,
        (),
        "bad_pattern:**:empty_prefix",
    ),
    (
        "traversal",
        "```yaml\nassurance:\n  trivial_paths:\n    - ../etc/passwd\n```\n",
        False,
        (),
        "bad_pattern:../etc/passwd:traversal",
    ),
    (
        "one-bad-among-good",
        "```yaml\nassurance:\n  trivial_paths:\n    - docs/**\n    - /**\n```\n",
        False,
        (),
        "bad_pattern:/**:absolute",
    ),
    (
        "empty-item",
        "```yaml\nassurance:\n  trivial_paths:\n    - docs/**\n    -\n```\n",
        False,
        (),
        "bad_pattern::empty",
    ),
    (
        "value-with-whitespace",
        "```yaml\nassurance:\n  trivial_paths:\n    - docs /**\n```\n",
        False,
        (),
        "bad_pattern:docs /**:whitespace",
    ),
    (
        # ``context_block`` keeps a blank line inside a block rather than ending
        # it, so the item scan has to skip one — a body an operator writes
        # without thinking about it, and the one line of this reader no other
        # row reaches.
        "blank-line-inside-the-list",
        "```yaml\nassurance:\n  trivial_paths:\n    - docs/**\n\n    - CHANGELOG.md\n```\n",
        True,
        ("docs/**", "CHANGELOG.md"),
        None,
    ),
    (
        "quoted-pattern-is-usable",
        "```yaml\nassurance:\n  trivial_paths:\n    - 'docs/**'\n```\n",
        True,
        ("docs/**",),
        None,
    ),
]


@pytest.mark.parametrize(
    ("body", "valid", "patterns", "reason"),
    [(b, v, p, r) for _, b, v, p, r in _ALLOWLIST_CASES],
    ids=[name for name, _, _, _, _ in _ALLOWLIST_CASES],
)
def test_allowlist_configuration_table(
    tmp_path: Path,
    body: str | None,
    valid: bool,
    patterns: tuple[str, ...],
    reason: str | None,
) -> None:
    """Absent or invalid configuration means no diff is trivial, and says why."""
    config = load_trivial_allowlist(_context(tmp_path, body))
    assert config.valid is valid
    assert config.patterns == patterns
    assert config.invalid_reason == reason


def test_a_valid_allowlist_is_representable(tmp_path: Path) -> None:
    """Floor outside the parametrization.

    Every negative row would still pass against a reader that returned
    ``valid=False`` unconditionally, which is why the positive case is asserted
    here as well as inside the table.
    """
    config = load_trivial_allowlist(_context(tmp_path, _WELL_FORMED))
    assert config.valid
    assert config.patterns == ("CHANGELOG.md", "docs/**")


def test_one_bad_pattern_invalidates_the_whole_list_rather_than_being_dropped(
    tmp_path: Path,
) -> None:
    """The named alternative, measured.

    Dropping the bad entry would leave ``docs/**`` in force and change which
    paths are eligible with nothing failing. The reason names the rejected
    pattern so the operator can fix it.
    """
    root = _context(
        tmp_path, "```yaml\nassurance:\n  trivial_paths:\n    - docs/**\n    - /**\n```\n"
    )
    config = load_trivial_allowlist(root)
    assert config.patterns == ()
    assert config.invalid_reason == "bad_pattern:/**:absolute"


def test_a_later_top_level_key_ends_the_assurance_block(tmp_path: Path) -> None:
    """The block reader's boundary, exercised through the real config path."""
    root = _context(
        tmp_path,
        "```yaml\nassurance:\n  trivial_paths:\n    - docs/**\npaths:\n  - not-a-pattern\n```\n",
    )
    assert load_trivial_allowlist(root).patterns == ("docs/**",)


def test_a_sibling_key_after_the_list_ends_it(tmp_path: Path) -> None:
    root = _context(
        tmp_path,
        "```yaml\nassurance:\n  trivial_paths:\n    - docs/**\n  other: 1\n```\n",
    )
    assert load_trivial_allowlist(root).patterns == ("docs/**",)


def test_this_repos_own_allowlist_is_valid() -> None:
    """The repo dogfoods its own configuration surface.

    A pure-fixture suite would stay green against a reader that could not parse
    the one CONTEXT.md that actually ships.
    """
    config = load_trivial_allowlist(Path(__file__).resolve().parents[2])
    assert config.valid, f"this repo's own allowlist is unusable: {config.invalid_reason}"
    assert config.patterns
