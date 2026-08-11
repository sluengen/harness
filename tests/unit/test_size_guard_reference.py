"""CAL-1156 — the distributed size-marker guard reference is real, runnable, and adoptable.

The size-marker rule (``code-quality`` Part C: a file over the 500-line hard
limit carries a ``# size: <reason>`` justification or the reviewer rejects it)
is enforced *in this repo* by
:mod:`tests.unit.test_source_file_size_justification` (CODE-1, from the
2026-06-15 assessment): it globs ``harness/**/*.py`` and fails any over-limit
file lacking a ``# size:`` marker. That guard is repo-local — it hardcodes this
repo's glob and limit and lives in ``tests/``, which the installer never copies.

The accepted proposal ``size-criterion-process.md`` (2026-07-17, item 2 +
decision "here, plus a distributed reference") asks for the same mechanical
check to travel to consuming repos: a ``~30-line walker installed per repo`` with
its own globs/limit/exemptions. This guard covers that distributed artifact —
``templates/size-guard.md`` — and, crucially, **executes the reference code the
template ships** so a consuming repo copies something that actually works rather
than dead prose.

Acceptance criteria (CAL-1156):

* **AC-1** — the reference walker flags an over-limit file with no marker (shown
  red first, before the template existed) and passes a marked one. Proven by
  :func:`test_reference_flags_unmarked_over_limit_file` and
  :func:`test_reference_passes_marked_over_limit_file`.
* **AC-2** — removing a file's ``# size:`` marker makes the walker flag it.
  Proven by :func:`test_reference_flags_when_marker_removed`.
* **AC-3** — ``registry.yaml`` distributes the reference implementation. Proven
  by :func:`test_reference_is_registered_and_header_matches`.

The walker keys on the explicit ``# size:`` marker, not an incidental ticket
cite — the same discriminator CODE-1 documents, so a long file that merely
mentions a ticket for unrelated provenance does not false-green
(:func:`test_reference_ignores_incidental_ticket_cite`). Config (globs, limit,
exemptions) is exercised by :func:`test_reference_respects_exemptions` and
:func:`test_reference_ignores_under_limit_file`.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

# ``tests/unit/test_*.py`` → ``parents[2]`` is the repo (or worktree) root.
_REPO_ROOT = Path(__file__).resolve().parents[2]
_TEMPLATE = _REPO_ROOT / "templates" / "size-guard.md"
_REGISTRY = _REPO_ROOT / "registry.yaml"

_HARD_LIMIT = 500


def _extract_reference() -> dict[str, Any]:
    """Execute the single ``python`` code block the template ships and return its
    namespace.

    Testing the *executed* reference (not a text-parse of it) is the point: the
    template's value is that a consuming repo can copy it and have a working
    guard, so a bug in the shipped code must fail this suite, not rot silently.
    """
    text = _TEMPLATE.read_text(encoding="utf-8")
    blocks = re.findall(r"```python\n(.*?)```", text, re.S)
    assert len(blocks) == 1, (
        f"templates/size-guard.md must ship exactly one ```python reference "
        f"block for the guard to execute; found {len(blocks)}."
    )
    namespace: dict[str, Any] = {}
    exec(compile(blocks[0], str(_TEMPLATE), "exec"), namespace)  # noqa: S102
    assert "find_offenders" in namespace, (
        "the reference block must define find_offenders(root, *, globs, limit, "
        "exemptions) -> list[str] so an adopter (and this test) can call it."
    )
    return namespace


@pytest.fixture()
def find_offenders() -> Callable[..., list[str]]:
    return _extract_reference()["find_offenders"]


@pytest.fixture()
def declarative_ceiling() -> int:
    return _extract_reference()["DECLARATIVE_CEILING"]


def _write_lines(path: Path, count: int, *, marker: str | None) -> None:
    """Write a ``.py`` file of ``count`` lines, optionally carrying a marker line."""
    path.parent.mkdir(parents=True, exist_ok=True)
    body = [f"x{i} = {i}" for i in range(count)]
    if marker is not None:
        body.insert(0, marker)
    path.write_text("\n".join(body) + "\n", encoding="utf-8")


def test_reference_flags_unmarked_over_limit_file(
    find_offenders: Callable[..., list[str]], tmp_path: Path
) -> None:
    """AC-1: an over-limit file with no ``# size:`` marker is flagged."""
    _write_lines(tmp_path / "big.py", _HARD_LIMIT + 1, marker=None)
    offenders = find_offenders(tmp_path, globs=("**/*.py",), limit=_HARD_LIMIT)
    assert offenders == ["big.py"], offenders


def test_reference_passes_marked_over_limit_file(
    find_offenders: Callable[..., list[str]], tmp_path: Path
) -> None:
    """AC-1: an over-limit file carrying a ``# size:`` justification is not flagged."""
    _write_lines(
        tmp_path / "big.py", _HARD_LIMIT + 1, marker="# size: one cohesive concern"
    )
    assert find_offenders(tmp_path, globs=("**/*.py",), limit=_HARD_LIMIT) == []


def test_reference_flags_when_marker_removed(
    find_offenders: Callable[..., list[str]], tmp_path: Path
) -> None:
    """AC-2: removing the ``# size:`` marker flips a passing file to an offender."""
    big = tmp_path / "big.py"
    _write_lines(big, _HARD_LIMIT + 1, marker="# size: one cohesive concern")
    assert find_offenders(tmp_path, globs=("**/*.py",), limit=_HARD_LIMIT) == []
    _write_lines(big, _HARD_LIMIT + 1, marker=None)  # marker removed
    assert find_offenders(tmp_path, globs=("**/*.py",), limit=_HARD_LIMIT) == ["big.py"]


def test_reference_ignores_under_limit_file(
    find_offenders: Callable[..., list[str]], tmp_path: Path
) -> None:
    """A file at or under the limit needs no marker."""
    _write_lines(tmp_path / "small.py", _HARD_LIMIT, marker=None)
    assert find_offenders(tmp_path, globs=("**/*.py",), limit=_HARD_LIMIT) == []


def test_reference_ignores_incidental_ticket_cite(
    find_offenders: Callable[..., list[str]], tmp_path: Path
) -> None:
    """A bare ticket cite is not a size decision — it must not satisfy the guard."""
    _write_lines(
        tmp_path / "big.py", _HARD_LIMIT + 1, marker="# see PROJ-42 for the design"
    )
    assert find_offenders(tmp_path, globs=("**/*.py",), limit=_HARD_LIMIT) == ["big.py"]


@pytest.mark.parametrize(
    ("suffix", "marker"),
    [
        ("js", "// size: one cohesive module"),
        ("css", "/* size: one cohesive sheet */"),
        ("html", "<!-- size: one cohesive document -->"),
    ],
)
def test_reference_recognizes_non_hash_comment_markers(
    find_offenders: Callable[..., list[str]], tmp_path: Path, suffix: str, marker: str
) -> None:
    """The default marker travels beyond ``#``: ``//``, ``/* */`` and ``<!-- -->``
    comment styles justify an over-limit file, so a JS/CSS/HTML adopter is not
    silently broken (the rule is language-agnostic; the default covers the common
    comment leaders and ``SIZE_MARKER`` is editable for the rest)."""
    name = f"big.{suffix}"
    _write_lines(tmp_path / name, _HARD_LIMIT + 1, marker=marker)
    assert find_offenders(tmp_path, globs=(f"**/*.{suffix}",), limit=_HARD_LIMIT) == []


def test_reference_respects_exemptions(
    find_offenders: Callable[..., list[str]], tmp_path: Path
) -> None:
    """A repo-relative path in the exemption list is skipped (config, per Part B)."""
    _write_lines(tmp_path / "generated" / "schema.py", _HARD_LIMIT + 1, marker=None)
    assert find_offenders(
        tmp_path,
        globs=("**/*.py",),
        limit=_HARD_LIMIT,
        exemptions=frozenset({"generated/schema.py"}),
    ) == []


def test_reference_raises_ceiling_for_declarative_glob_file(
    find_offenders: Callable[..., list[str]],
    declarative_ceiling: int,
    tmp_path: Path,
) -> None:
    """A declarative-glob file above the hard limit but under the raised ceiling
    passes — the raise is a tripwire relocation, not an exemption."""
    _write_lines(tmp_path / "schemas" / "tokens.py", _HARD_LIMIT + 100, marker=None)
    assert (
        find_offenders(
            tmp_path,
            globs=("**/*.py",),
            limit=_HARD_LIMIT,
            declarative_globs=("schemas/**/*.py",),
        )
        == []
    )


def test_reference_flags_declarative_glob_file_over_raised_ceiling(
    find_offenders: Callable[..., list[str]],
    declarative_ceiling: int,
    tmp_path: Path,
) -> None:
    """A declarative-glob file over the raised ceiling is still an offender — the
    raise moves the tripwire, it does not disable it."""
    _write_lines(
        tmp_path / "schemas" / "tokens.py", declarative_ceiling + 1, marker=None
    )
    assert find_offenders(
        tmp_path,
        globs=("**/*.py",),
        limit=_HARD_LIMIT,
        declarative_globs=("schemas/**/*.py",),
    ) == ["schemas/tokens.py"]


def test_reference_raised_ceiling_is_scoped_to_declarative_globs(
    find_offenders: Callable[..., list[str]], tmp_path: Path
) -> None:
    """The raised ceiling applies only to files matched by ``declarative_globs`` —
    a same-length non-declarative file is still measured against the hard limit."""
    length = _HARD_LIMIT + 100
    _write_lines(tmp_path / "schemas" / "tokens.py", length, marker=None)
    _write_lines(tmp_path / "app" / "service.py", length, marker=None)
    assert find_offenders(
        tmp_path,
        globs=("**/*.py",),
        limit=_HARD_LIMIT,
        declarative_globs=("schemas/**/*.py",),
    ) == ["app/service.py"]


def test_reference_marker_passes_above_raised_ceiling(
    find_offenders: Callable[..., list[str]],
    declarative_ceiling: int,
    tmp_path: Path,
) -> None:
    """A ``# size:`` marker still justifies a declarative file above the raised
    ceiling — marker semantics are unchanged, only the ceiling moved."""
    _write_lines(
        tmp_path / "schemas" / "tokens.py",
        declarative_ceiling + 1,
        marker="# size: generated field list",
    )
    assert (
        find_offenders(
            tmp_path,
            globs=("**/*.py",),
            limit=_HARD_LIMIT,
            declarative_globs=("schemas/**/*.py",),
        )
        == []
    )


def test_reference_declarative_default_is_inert(
    find_offenders: Callable[..., list[str]], tmp_path: Path
) -> None:
    """The shipped ``DECLARATIVE_GLOBS`` default is empty, so an adopter who has
    not opted in sees identical behaviour to before this change."""
    _write_lines(tmp_path / "schemas" / "tokens.py", _HARD_LIMIT + 1, marker=None)
    assert find_offenders(tmp_path, globs=("**/*.py",), limit=_HARD_LIMIT) == [
        "schemas/tokens.py"
    ]


def test_reference_declarative_ceiling_constant_defaults_to_1_5x_hard_limit() -> None:
    """AC-1/AC-3: the constant exists, is distinct from ``EXEMPTIONS``, and
    defaults to 1.5x the hard limit, not a value someone typed once."""
    ns = _extract_reference()
    assert ns["DECLARATIVE_GLOBS"] == ()
    assert ns["DECLARATIVE_CEILING"] == ns["HARD_LIMIT"] * 3 // 2
    assert isinstance(ns["EXEMPTIONS"], frozenset)


def test_reference_exemption_wins_over_declarative_ceiling(
    find_offenders: Callable[..., list[str]],
    declarative_ceiling: int,
    tmp_path: Path,
) -> None:
    """A path in both ``EXEMPTIONS`` and a declarative glob is skipped — exemption
    is checked first and wins, pinning the precedence order."""
    _write_lines(
        tmp_path / "schemas" / "tokens.py", declarative_ceiling + 100, marker=None
    )
    assert (
        find_offenders(
            tmp_path,
            globs=("**/*.py",),
            limit=_HARD_LIMIT,
            exemptions=frozenset({"schemas/tokens.py"}),
            declarative_globs=("schemas/**/*.py",),
        )
        == []
    )


def test_reference_declarative_glob_matching_directory_is_not_a_file(
    find_offenders: Callable[..., list[str]], tmp_path: Path
) -> None:
    """A declarative glob matching a directory entry contributes nothing to the
    declarative set — only files carry the raised ceiling."""
    _write_lines(tmp_path / "schemas" / "tokens.py", _HARD_LIMIT + 100, marker=None)
    # "schemas" itself (the directory) matches "schemas*" but must be filtered by
    # is_file(); the file inside still needs its own glob to be scanned at all.
    assert find_offenders(
        tmp_path,
        globs=("**/*.py",),
        limit=_HARD_LIMIT,
        declarative_globs=("schemas*", "schemas/**/*.py"),
    ) == []


def test_reference_declarative_glob_outside_source_globs_is_never_scanned(
    find_offenders: Callable[..., list[str]], tmp_path: Path
) -> None:
    """``declarative_globs`` narrows a ceiling within the scanned set — it does
    not widen the scan to files ``globs`` never selects."""
    _write_lines(tmp_path / "schemas" / "tokens.txt", _HARD_LIMIT + 100, marker=None)
    assert (
        find_offenders(
            tmp_path,
            globs=("**/*.py",),
            limit=_HARD_LIMIT,
            declarative_globs=("schemas/**/*.txt",),
        )
        == []
    )


def test_reference_declarative_set_dedups_across_overlapping_globs(
    find_offenders: Callable[..., list[str]],
    declarative_ceiling: int,
    tmp_path: Path,
) -> None:
    """A file matched by two overlapping ``declarative_globs`` entries is not
    double-counted — it is flagged at most once when over the raised ceiling."""
    _write_lines(
        tmp_path / "schemas" / "tokens.py", declarative_ceiling + 1, marker=None
    )
    assert find_offenders(
        tmp_path,
        globs=("**/*.py",),
        limit=_HARD_LIMIT,
        declarative_globs=("schemas/**/*.py", "schemas/**"),
    ) == ["schemas/tokens.py"]


def test_code_quality_declarative_ceiling_claim_matches_the_shipped_constant() -> None:
    """AC-3: `code-quality` Part C's claim that the walker's config carries 'the
    higher declarative-file ceiling from Part B' is true only if the shipped
    reference actually defines that constant — asserting both halves is the
    point, since either alone can drift back into the gap this ticket closes."""
    path = (
        _REPO_ROOT
        / "skills"
        / "code-quality"
        / "references"
        / "specialized-verification.md"
    )
    skill = path.read_text(encoding="utf-8")
    assert "the higher declarative-file ceiling from Part B" in skill
    ns = _extract_reference()
    assert "DECLARATIVE_CEILING" in ns


def test_reference_is_registered_and_header_matches() -> None:
    """AC-3: the registry distributes the reference and its header matches."""
    assert _TEMPLATE.exists(), "templates/size-guard.md must exist"
    registry = _REGISTRY.read_text(encoding="utf-8")
    row = re.search(
        r"templates/size-guard\.md:\s*\{[^}]*id:\s*template-size-guard[^}]*"
        r"version:\s*(?P<v>[\d.]+)[^}]*\}",
        registry,
    )
    assert row, (
        "registry.yaml must list "
        "'templates/size-guard.md: { id: template-size-guard, version: ... }'"
    )
    header = re.search(
        r"guidance:template-size-guard@([\d.]+)", _TEMPLATE.read_text(encoding="utf-8")
    )
    assert header, "templates/size-guard.md must carry a guidance:template-size-guard@<v> header"
    assert header.group(1) == row.group("v"), (
        f"header {header.group(1)} != registry {row.group('v')} — bump both together."
    )


def test_template_scopes_the_test_tree_at_the_declarative_ceiling() -> None:
    """#275 — the adopt guidance names the test tree and the ceiling it gets.

    The repo's own guard scoped to production for over a year and deferred
    ``tests/`` in prose; by the time the deferral was revisited the test tree
    held 14 files past the declarative ceiling with no recorded decision. The
    template shipped every consuming repo the same blind spot: its
    ``SOURCE_GLOBS`` example names one production tree and nothing told an
    adopter their test tree is source too.

    The fix is guidance, not a defaults change. ``DECLARATIVE_GLOBS`` ships
    empty on purpose (:func:`test_reference_declarative_default_is_inert`,
    #234), so this asserts the *prose* carries the scope advice and the
    ``tests/`` example, leaving the inert-default contract intact.

    Each token below was confirmed absent from the pre-change template, so this
    measures the new guidance rather than passing on text that was already
    there.
    """
    text = _TEMPLATE.read_text(encoding="utf-8")
    required = {
        "the scope heading": "Scope every source tree",
        "the raised ceiling for tests": "declarative ceiling",
        "the tests/ DECLARATIVE_GLOBS example": 'DECLARATIVE_GLOBS: tuple[str, ...] = ("tests',
        "the tests/ SOURCE_GLOBS example": '"tests/**/*.py"',
        "the green-because-unchecked warning": "reads green",
        "the auditable-choice framing": "auditable choice",
    }
    missing = [name for name, token in required.items() if token not in text]
    assert not missing, (
        "templates/size-guard.md's adopt guidance must tell an adopter to scope "
        "their test tree at the declarative ceiling (#275); missing: "
        f"{missing}"
    )


def test_template_still_ships_exactly_one_executable_reference() -> None:
    """The scope guidance's config excerpt must not become a second reference.

    :func:`_extract_reference` requires exactly one ```python block so what a
    consuming repo executes is unambiguous. The #275 guidance adds a config
    excerpt, which is deliberately fenced *without* the ``python`` tag for that
    reason — this pins the distinction so a later edit that promotes the excerpt
    to a python block fails here with the reason rather than inside the
    extractor's assert.
    """
    text = _TEMPLATE.read_text(encoding="utf-8")
    assert len(re.findall(r"```python\n", text)) == 1
    assert 'SOURCE_GLOBS: tuple[str, ...] = ("src/**/*.py"' in text, (
        "the config excerpt must stay in the template as a non-python fence"
    )
