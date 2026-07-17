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
