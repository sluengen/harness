"""Repo-owned guard — ``/harness run`` stays out of the installed surface (CAL-650).

The "merge the guidance repo into the harness" decision (``specs/architecture-
principles.md``, "App vs. installed surface" and D1/D6) records one deliberate
exception to the otherwise-simple "files under a surface directory are surface"
rule: ``commands/harness.md`` — the ``/harness run`` command that drives the
harness's *own* pipeline — lives in the surface directory ``commands/`` but is
**deliberately kept out of** ``registry.yaml``'s ``files:`` block, so it is
never installed into a target repo. CAL-624 ("distribute ``/harness run`` via
the agents-repo channel") is subsumed by this: the harness owns the channel and
chooses not to distribute its own pipeline command.

The footprint guard (``test_guidance_footprint.py``, CAL-648) mechanically holds
the boundary for app *directories* (``harness/ docker/ bin/ scripts/ specs/
tests/``). It cannot hold *this* line, because ``commands/`` *is* a surface
directory — ``commands/harness.md`` is excluded by intent, not by location. So
the decision lived in prose only until this guard: a future edit could add
``commands/harness.md`` to the registry and silently begin distributing the
harness's own pipeline command into every consuming repo.

This guard pins the intent: ``commands/harness.md`` is present in the source
tree but absent from the installed surface.

*Source:* ``specs/architecture-principles.md`` (the "App vs. installed surface"
principle — ``commands/harness.md`` is "a repo-owned command kept *out* of the
registry" — and the "Merge the guidance repo into the harness" decision, which
subsumes CAL-624 into CAL-650).
"""

from __future__ import annotations

import posixpath
import re
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent.parent
REGISTRY = REPO_ROOT / "registry.yaml"

#: The harness's own pipeline command — repo-owned, never installed surface.
HARNESS_COMMAND = "commands/harness.md"

#: A mapping-entry line: leading indent, an optionally quoted key, then a colon.
#: Identical in spirit to ``test_guidance_footprint._KEY_RE`` — read the key from
#: the ``path: {...}``, quoted ``"path": {...}``, and block ``path:`` forms alike,
#: so a quoted ``"commands/harness.md": {...}`` entry cannot slip past the guard.
_KEY_RE = re.compile(r"""\s+(?P<q>["']?)(?P<key>[^"'\s:]+)(?P=q)\s*:""")


def _normalize(path: str) -> str:
    """Lexically normalize a registry key the way the installer's copy target
    would resolve it, collapsing ``.`` and ``..`` segments — so a non-canonical
    spelling (``commands/./harness.md``, ``commands/x/../harness.md``) that
    *resolves* to the excluded command is judged on its real destination, not
    its raw text. Mirrors ``test_guidance_footprint._normalize`` (codex P2,
    CAL-650)."""
    return posixpath.normpath(path)


def _registry_file_keys(text: str) -> list[str]:
    """The path keys of a registry text's ``files:`` block.

    Slices to the ``files:`` section (between the ``files:`` and ``meta:``
    headers) exactly as ``test_guidance_footprint`` does, then reads each
    entry's key. Takes the registry *text* (not a fixed path) so the teeth test
    can exercise the parser against a synthetic registry without touching disk.
    A line regex avoids coupling to a ``yaml`` import (PyYAML is not a declared
    dependency).
    """
    start = text.index("\nfiles:")
    end = text.index("\nmeta:", start)
    keys: list[str] = []
    for line in text[start:end].splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or stripped == "files:":
            continue
        m = _KEY_RE.match(line)
        if m:
            keys.append(m.group("key"))
    return keys


def test_harness_command_present_in_source_tree() -> None:
    """``commands/harness.md`` exists in the source tree.

    Half the invariant: the command must be *present* (it drives the harness's
    own pipeline) — it is excluded from the surface, not deleted. Without this
    anchor the exclusion guard would pass vacuously if the file were removed.
    """
    assert (REPO_ROOT / HARNESS_COMMAND).is_file(), (
        f"{HARNESS_COMMAND} is missing from the source tree — it is the "
        "/harness run command that drives the harness's own pipeline. It must "
        "exist (repo-owned), just not be installed into target repos."
    )


def test_registry_lists_other_commands() -> None:
    """Guard the parser: the registry must list *some* ``commands/`` entry.

    If the parser returned nothing, ``test_harness_command_excluded_from_registry``
    would pass vacuously. Anchor on a known-distributed command so a broken
    parser fails loudly here instead.
    """
    keys = _registry_file_keys(REGISTRY.read_text())
    assert any(k.startswith("commands/") for k in keys), (
        "registry.yaml's files: block parsed to no commands/ entries — the "
        "parser or the copy-list is broken; the repo-owned guard would pass "
        "vacuously."
    )


def test_harness_command_excluded_from_registry() -> None:
    """AC-1: ``commands/harness.md`` is absent from the installed surface.

    The other half of the invariant and the load-bearing assertion: the
    ``/harness run`` command is repo-owned and must never ride the install into
    a consuming repo, even though it sits in the ``commands/`` surface directory.
    Keys are normalized first so a non-canonical entry that *resolves* to the
    command (``commands/x/../harness.md``) is caught, not just the literal
    spelling (codex P2).
    """
    keys = _registry_file_keys(REGISTRY.read_text())
    offenders = [k for k in keys if _normalize(k) == HARNESS_COMMAND]
    assert not offenders, (
        f"{offenders!r} resolve(s) to {HARNESS_COMMAND} in registry.yaml's "
        "files: block — it would "
        "be installed into every consuming repo. The /harness run command is "
        "repo-owned: it drives the harness's own pipeline and is deliberately "
        "kept out of the installed surface (specs/architecture-principles.md, "
        "'App vs. installed surface'; CAL-624 subsumed by CAL-650). Remove the "
        "entry, or — if distributing it is now intended — revisit the boundary "
        "decision first."
    )


def _excluded_offenders(text: str) -> list[str]:
    """Registry keys that resolve to the repo-owned command — the exact
    predicate ``test_harness_command_excluded_from_registry`` enforces."""
    return [k for k in _registry_file_keys(text) if _normalize(k) == HARNESS_COMMAND]


def test_guard_flags_registered_harness_command() -> None:
    """AC-1 (teeth): the guard catches ``commands/harness.md`` if it is added.

    A negative assertion proving the exclusion check has teeth. Feed the
    predicate a synthetic registry whose ``files:`` block lists
    ``commands/harness.md`` and confirm it is flagged — so the exclusion
    assertion above would fail. Without this, a future refactor of the parser
    could neuter the guard while it still passed on the (clean) live registry.
    """
    synthetic = (
        "registry_format: 1\n"
        "files:\n"
        "  commands/start.md: { id: start, version: 0.2.1 }\n"
        "  commands/harness.md: { id: harness, version: 0.1.0 }\n"
        "meta:\n"
        "  registry.yaml: { id: registry, version: 0.4.1 }\n"
    )
    assert _excluded_offenders(synthetic) == [HARNESS_COMMAND], (
        "the guard failed to flag commands/harness.md in a synthetic registry "
        "that lists it — the repo-owned guard has no teeth and would not catch "
        "the command being added to the installed surface."
    )


def test_guard_reads_quoted_harness_key() -> None:
    """AC-1 (teeth): a *quoted* ``commands/harness.md`` entry is still caught.

    A strict ``path: {...}`` regex would skip a quoted key, letting the command
    ride into the surface unflagged. Confirm the key-first match reads the
    quoted form too.
    """
    synthetic = (
        "registry_format: 1\n"
        "files:\n"
        '  "commands/harness.md": { id: harness, version: 0.1.0 }\n'
        "meta:\n"
        "  registry.yaml: { id: registry, version: 0.4.1 }\n"
    )
    assert _excluded_offenders(synthetic) == [HARNESS_COMMAND], (
        "the guard failed to read a quoted commands/harness.md key — a quoted "
        "entry could bypass the repo-owned guard."
    )


def test_guard_flags_non_canonical_harness_key() -> None:
    """AC-1 (teeth, normalization): a non-canonical key that *resolves* to the
    command is caught (codex P2, CAL-650).

    ``commands/x/../harness.md`` and ``commands/./harness.md`` both resolve to
    ``commands/harness.md`` when the installer copies them, so they would
    distribute ``/harness run`` — yet a raw-string ``== "commands/harness.md"``
    check would miss them. The guard must normalize keys before comparing, the
    way the footprint guard does.
    """
    for key in ("commands/x/../harness.md", "commands/./harness.md"):
        synthetic = (
            "registry_format: 1\n"
            "files:\n"
            f"  {key}: {{ id: harness, version: 0.1.0 }}\n"
            "meta:\n"
            "  registry.yaml: { id: registry, version: 0.4.1 }\n"
        )
        assert _excluded_offenders(synthetic) == [key], (
            f"{key!r} resolves to {HARNESS_COMMAND} but the guard did not flag "
            "it — a non-canonical registry entry could distribute /harness run "
            "while the exclusion check passed."
        )
