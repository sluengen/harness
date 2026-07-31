"""CAL-636 — a module's docstring *home* cite resolves to the §4.x section that documents it.

CAL-633 guards the **retired-§** class (a docstring citing a permanently
superseded section) and CAL-635 (``test_events_spec_cites.py``) guards one
instance of the adjacent **wrong-current-§** class (the events writer cited the
*live* §4.9 — workspace — instead of its home §4.7). A
retired-§ grep cannot catch the wrong-current-§ class: §4.9 is a current
section, so its mere existence is not the fault — the fault is that it documents
a *different* module than the one citing it.

This guard generalises CAL-635 from "the events module specifically" to the
whole SPEC §4 module-design block. §4's subsections document a fixed set of
modules, named in the header and (for a few) the body::

    ### 4.5 `harness.worktree`
    ### 4.6 `harness.state.store`
    ### 4.7 `harness.events.emitter`     (body also: `harness.events.schema`)
    ### 4.8 `harness.linear`, `harness.identity`
    ### 4.9 `harness.workspace`

so each module's *home* section is mechanically derivable from §4's text. The
contract: **if a module's module-level docstring cites a §4.x section, that
section must document the module.**

Two narrowings eliminate false positives:

* **Home cites only.** Only the §4.x cites in the *module-level docstring*
  (``ast.get_docstring``) are checked. A module legitimately cross-refers other
  current sections from inline comments / function docstrings — e.g.
  ``events/emitter.py`` cites its own §4.7 from a method docstring. Those are
  not home declarations and are left alone.
* **Presence-optional.** The guard does not force every module to carry a home
  cite (``harness.linear`` / ``harness.workspace`` carry none today). It only
  requires that a home cite, *if present*, resolves correctly — the CODE-2 class
  is a *wrong* cite, not a *missing* one.

The home map is explicit, not a package-parent heuristic: a module homes at a
section iff the section's **header** names it, **or** the section's text names it
and it is named by no other section's header. The second clause admits
``harness.events.schema`` (named only in §4.7's body) while *rejecting* a body
cross-reference to a module that homes elsewhere — §4.2's body mentions
``harness.worktree``, but ``worktree`` is §4.5's header name, so §4.2 is not a
home for it. A header-parent heuristic was rejected (it let a dotted submodule
resolve to a sibling section via the shared top-level ``harness`` package, and
``harness.cli._git`` — as the module was then named, before #269 re-homed it to
``harness._git`` — to any of §4.2–§4.4 via its ``harness.cli`` parent).

Acceptance criteria:

* **AC-1** — a structural guard fails when a module's docstring home cite names a
  §4.x section that does not document that module. Proven by
  :func:`test_home_resolution_rule` (the synthetic contract, including the CODE-2
  ``events.emitter``→§4.9 case) and
  :func:`test_no_module_docstring_cites_a_foreign_home_section` (the live sweep,
  which would fail were any home cite foreign).
* **AC-2** — the rule admits a body-documented home (``harness.events.schema``→§4.7)
  without admitting a body *cross-reference* (``harness.worktree``→§4.2) or a
  distinct sibling section (``harness.cli.start``→§4.3). Proven by
  :func:`test_home_resolution_rule` and :func:`test_home_map_matches_spec`.
"""

from __future__ import annotations

import ast
import re
from collections import defaultdict
from pathlib import Path

import pytest

from tests._gitutil import tracked_files_under

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SPEC = _REPO_ROOT / "SPEC.md"

# A markdown header line and the §4.x subsection id it may open.
_HEADER_RE = re.compile(r"^(#{2,6})\s+(.*)$")
_SUBSECTION_RE = re.compile(r"^(4\.\d+)\b")
_MODULE_TOKEN_RE = re.compile(r"harness\.[A-Za-z_][\w.]*")

# A §4.x cite in prose: ``§4.7``, ``§ 4.7`` (the retired-cite guard keys on the
# same ``§`` glyph). §4 has only single-digit subsections.
_CITE_RE = re.compile(r"§\s*(4\.\d+)")


def _parse_section_modules(spec_text: str) -> tuple[dict[str, set[str]], dict[str, set[str]]]:
    """Return ``(header_modules, section_modules)`` for the §4 block.

    ``header_modules[s]`` — modules named on §s's header line.
    ``section_modules[s]`` — every ``harness.<dotted>`` token in §s's full text
    (header + body), accumulated until the next markdown header.
    """
    header_modules: dict[str, set[str]] = {}
    section_modules: dict[str, set[str]] = defaultdict(set)
    current: str | None = None
    for line in spec_text.splitlines():
        header = _HEADER_RE.match(line)
        if header:
            sub = _SUBSECTION_RE.match(header.group(2))
            if sub:
                current = sub.group(1)
                names = set(_MODULE_TOKEN_RE.findall(header.group(2)))
                header_modules[current] = names
                section_modules[current] |= names
            else:
                current = None  # any non-§4.x header ends the current section
            continue
        if current is not None:
            section_modules[current] |= set(_MODULE_TOKEN_RE.findall(line))
    return header_modules, dict(section_modules)


def _home_map(spec_text: str) -> dict[str, set[str]]:
    """Map each documented module to the §4.x section(s) that are its home.

    A module homes at section ``s`` iff ``s``'s header names it, or ``s``'s text
    names it and no section's header names it (a body-documented home). A body
    *cross-reference* to a module that homes elsewhere (it is some header's name)
    is excluded.
    """
    header_modules, section_modules = _parse_section_modules(spec_text)
    header_named = {m for names in header_modules.values() for m in names}
    homes: dict[str, set[str]] = defaultdict(set)
    for section, modules in section_modules.items():
        for module in modules:
            if module in header_modules.get(section, set()) or module not in header_named:
                homes[module].add(section)
    return dict(homes)


def _dotted_name(abs_path: Path) -> str:
    """``harness/events/emitter.py`` → ``harness.events.emitter``;
    ``harness/cli/__init__.py`` → ``harness.cli``."""
    rel = abs_path.relative_to(_REPO_ROOT).with_suffix("")
    parts = [p for p in rel.parts if p != "__init__"]
    return ".".join(parts)


def _home_cites(abs_path: Path) -> set[str]:
    """The §4.x sections cited in ``abs_path``'s **module-level** docstring."""
    try:
        docstring = ast.get_docstring(ast.parse(abs_path.read_text()))
    except (SyntaxError, ValueError):
        return set()
    if not docstring:
        return set()
    return set(_CITE_RE.findall(docstring))


# --- the home map and resolution rule, pinned by example ------------------
#: SPEC §4 as-built: module → its home section(s). Mirrors the headers, plus the
#: one body-documented home (``events.schema``→§4.7).
_EXPECTED_HOMES = {
    "harness.cli": {"4.1"},
    "harness.cli.start": {"4.2"},
    "harness.cli.review": {"4.3"},
    "harness.cli.close": {"4.4"},
    "harness.worktree": {"4.5"},
    "harness.state.store": {"4.6"},
    "harness.events.emitter": {"4.7"},
    "harness.events.schema": {"4.7"},
    "harness.linear": {"4.8"},
    "harness.identity": {"4.8"},
    "harness.workspace": {"4.9"},
}

# ``(module, section, expected)`` — is a home cite from ``module`` to ``section``
# valid?
_RULE_CASES = [
    # exact header homes — valid
    ("harness.worktree", "4.5", True),
    ("harness.state.store", "4.6", True),
    ("harness.events.emitter", "4.7", True),
    ("harness.identity", "4.8", True),
    ("harness.linear", "4.8", True),
    # body-documented home — valid (AC-2)
    ("harness.events.schema", "4.7", True),
    # the CODE-2 fault: events writer citing the workspace section — invalid (AC-1)
    ("harness.events.emitter", "4.9", False),
    # body cross-reference is not a home — invalid (AC-2: §4.2 mentions worktree)
    ("harness.worktree", "4.2", False),
    # a distinct sibling section must NOT be borrowed — invalid (AC-2)
    ("harness.cli.start", "4.3", False),
    ("harness.cli.review", "4.2", False),
    # the broad-fallback regression: a submodule must not resolve via the shared
    # top-level `harness` package — invalid
    ("harness.events.schema", "4.5", False),
    # a module §4 does not document has no home cite that resolves
    ("harness._git", "4.2", False),
]


@pytest.mark.parametrize("module, section, expected", _RULE_CASES)
def test_home_resolution_rule(module: str, section: str, expected: bool) -> None:
    homes = _EXPECTED_HOMES.get(module, set())
    assert (section in homes) is expected, (
        f"{module} citing §{section} should be {'valid' if expected else 'invalid'}"
    )


def test_home_map_matches_spec() -> None:
    """The home map parsed from SPEC equals the as-built mirror.

    Guards the parser against §4 drift: if a header is renamed or a module moves
    sections, this fails loudly instead of the home-cite sweep silently going
    permissive.
    """
    assert _home_map(_SPEC.read_text()) == _EXPECTED_HOMES


def test_no_module_docstring_cites_a_foreign_home_section() -> None:
    """Every §4.x home cite in a ``harness/`` module docstring resolves to a
    section that documents that module."""
    homes = _home_map(_SPEC.read_text())
    violations: list[str] = []
    for path in sorted(tracked_files_under("harness")):
        if path.suffix != ".py":
            continue
        module = _dotted_name(path)
        for section in sorted(_home_cites(path)):
            if section not in homes.get(module, set()):
                violations.append(
                    f"{path.name}: docstring home-cites §{section}, which does not "
                    f"document {module}"
                )

    assert not violations, (
        "a module docstring cites a §4.x section that documents a different "
        "module — cite the section that documents this module:\n  "
        + "\n  ".join(violations)
    )
