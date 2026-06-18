"""Distributed-surface guard — ``/harness run`` ships as a registry-tracked unit (CAL-764).

CAL-650 originally kept ``commands/harness.md`` deliberately **out of**
``registry.yaml``: the command drives the harness's *own* pipeline, so it was
treated as repo-owned and never installed into a consuming repo. Onboarding real
self-hosting repos (``slate``; ``coffee-standards/brewspec``) showed that
boundary cost more than it saved — every such repo had to **hand-copy** the file
and **hand-edit** its ``/harness routine`` project reference, the exact untracked
drift the version-stamped registry exists to prevent.

CAL-764 inverts that boundary case (approach A — lean / ungated): ``commands/
harness.md`` becomes a normal **distributed surface unit**. It carries a
``guidance:`` header, gains a ``registry.yaml`` ``files:`` entry under the
``harness`` profile, and is therefore copied by the installer like any other
command and tracked by ``/update-guidance``. The cost approach A accepts — the
command sits *inert* in a repo that does not host the harness tool — is bounded:
the command documents its ``~/bin/harness`` prerequisite and errors clearly
where the tool is absent.

This guard **replaces** ``test_harness_command_repo_owned.py`` (which asserted
the now-reversed exclusion) and pins the new contract with teeth:

* the command is **present** in the source tree (it still drives the pipeline);
* it is **registered** in the ``files:`` block (AC-1);
* it is registered under the ``harness`` profile, so a fresh bootstrap installs
  it **everywhere** — approach A (AC-3);
* it carries a ``guidance:`` header (AC-1) — the per-unit version
  ``/update-guidance`` and the freshness hook key off (the header *value* is held
  equal to the registry by ``test_guidance_source.test_surface_headers_match_registry``).

*Source:* CAL-764; ``specs/architecture-principles.md`` ("App vs. installed
surface" — already anticipated "``/harness run`` once distributed, CAL-650").
"""

from __future__ import annotations

import posixpath
import re
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent.parent
REGISTRY = REPO_ROOT / "registry.yaml"

#: The harness's own pipeline command — now a distributed surface unit.
HARNESS_COMMAND = "commands/harness.md"

#: A mapping-entry line: leading indent, an optionally quoted key, then a colon.
#: Mirrors ``test_guidance_footprint._KEY_RE`` so a quoted ``"commands/harness.md"``
#: entry is read the same as the bare form. PyYAML is not a declared dependency.
_KEY_RE = re.compile(r"""\s+(?P<q>["']?)(?P<key>[^"'\s:]+)(?P=q)\s*:""")


def _normalize(path: str) -> str:
    """Lexically normalize a registry key the way the installer's copy target
    resolves it, collapsing ``.``/``..`` segments — so a non-canonical spelling
    (``commands/./harness.md``) is judged on its real destination. Mirrors
    ``test_guidance_footprint._normalize``."""
    return posixpath.normpath(path)


def _registry_file_keys(text: str) -> list[str]:
    """The path keys of a registry text's ``files:`` block.

    Slices to the ``files:`` section (between the ``files:`` and ``meta:``
    headers) exactly as ``test_guidance_footprint`` does, then reads each entry's
    key. Takes the registry *text* (not a fixed path) so the teeth test can
    exercise the parser against a synthetic registry without touching disk.
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


def _is_registered(text: str) -> bool:
    """Whether some ``files:`` key resolves to ``commands/harness.md`` — the
    predicate ``test_harness_command_registered`` enforces, factored out so the
    teeth test can drive it against a synthetic registry."""
    return any(_normalize(k) == HARNESS_COMMAND for k in _registry_file_keys(text))


def _harness_entry_line(text: str) -> str:
    """The full ``files:`` entry line for ``commands/harness.md`` (its ``{...}``
    mapping value), so a test can assert on the entry's profile membership."""
    start = text.index("\nfiles:")
    end = text.index("\nmeta:", start)
    for line in text[start:end].splitlines():
        m = _KEY_RE.match(line)
        if m and _normalize(m.group("key")) == HARNESS_COMMAND:
            return line
    return ""


def test_harness_command_present_in_source_tree() -> None:
    """``commands/harness.md`` exists in the source tree.

    It still drives the harness's own pipeline — distributing it does not delete
    it. Without this anchor the registration guard could pass against a registry
    entry for a file that no longer exists.
    """
    assert (REPO_ROOT / HARNESS_COMMAND).is_file(), (
        f"{HARNESS_COMMAND} is missing from the source tree — it is the "
        "/harness run command that drives the harness's own pipeline."
    )


def test_registry_lists_other_commands() -> None:
    """Guard the parser: the registry lists *some* ``commands/`` entry.

    If the parser returned nothing, ``test_harness_command_registered`` would
    pass vacuously. Anchor on a known-distributed command so a broken parser
    fails loudly here instead.
    """
    keys = _registry_file_keys(REGISTRY.read_text())
    assert any(k.startswith("commands/") for k in keys), (
        "registry.yaml's files: block parsed to no commands/ entries — the "
        "parser or the copy-list is broken; the registration guard would pass "
        "vacuously."
    )


def test_harness_command_registered() -> None:
    """AC-1: ``commands/harness.md`` is present in the installed surface.

    The load-bearing assertion and the inverse of the retired CAL-650 guard: the
    ``/harness run`` command is now a distributed surface unit, so a ``files:``
    entry must resolve to it — otherwise the installer would not copy it and
    ``/update-guidance`` would not track it (the manual-copy drift CAL-764 fixes).
    """
    assert _is_registered(REGISTRY.read_text()), (
        f"{HARNESS_COMMAND} has no entry in registry.yaml's files: block — the "
        "/harness run command must be a tracked surface unit (CAL-764, approach "
        "A). Add it like any other command so the installer copies it and "
        "/update-guidance detects drift; do not revert to hand-copying it."
    )


def test_harness_command_registered_under_harness_profile() -> None:
    """AC-3: the entry carries the ``harness`` profile, so a fresh bootstrap
    installs ``/harness run`` **everywhere** (approach A — ungated).

    The installer copies every file whose ``profiles`` lists the selected profile
    (the only profile is ``harness``). Asserting profile membership is the
    deterministic, in-gate proof that a fresh bootstrap brings ``/harness run``
    automatically — the end-to-end behaviour AC-3 requires.
    """
    line = _harness_entry_line(REGISTRY.read_text())
    assert line, f"no files: entry for {HARNESS_COMMAND} (see test_harness_command_registered)."
    assert re.search(r"profiles:\s*\[[^\]]*\bharness\b", line), (
        f"the registry entry for {HARNESS_COMMAND} must list the `harness` "
        f"profile so the installer distributes it everywhere (CAL-764 AC-3): {line!r}"
    )


def test_harness_command_carries_guidance_header() -> None:
    """AC-1: ``commands/harness.md`` carries a ``guidance:`` version header.

    A registered surface file is version-tracked by its ``guidance:<id>@<ver>``
    header; the freshness hook and ``/update-guidance`` key drift off it. (The
    header value is held equal to the registry version by
    ``test_guidance_source.test_surface_headers_match_registry``; here we pin only
    that the header *exists*, the precondition that turns the command into a
    tracked unit rather than an untracked copy.)
    """
    text = (REPO_ROOT / HARNESS_COMMAND).read_text()
    assert re.search(r"guidance:[\w-]+@[\d.]+", text), (
        f"{HARNESS_COMMAND} carries no `guidance:<id>@<version>` header — a "
        "distributed surface unit must be version-stamped so /update-guidance "
        "and the freshness hook can track it (CAL-764 AC-1)."
    )


def test_guard_flags_unregistered_harness_command() -> None:
    """AC-1 (teeth): the guard catches a registry that *drops* the command.

    The inverse of the retired guard's teeth. Feed the predicate a synthetic
    registry whose ``files:`` block omits ``commands/harness.md`` and confirm it
    reports *not registered* — so ``test_harness_command_registered`` would fail
    if a refactor silently removed the entry and reverted to manual copying.
    """
    without = (
        "registry_format: 1\n"
        "files:\n"
        "  commands/start.md: { id: start, version: 0.2.1, profiles: [harness] }\n"
        "meta:\n"
        "  registry.yaml: { id: registry, version: 0.4.1 }\n"
    )
    assert not _is_registered(without), (
        "the predicate reported commands/harness.md as registered in a synthetic "
        "registry that omits it — the registration guard has no teeth."
    )
    with_it = (
        "registry_format: 1\n"
        "files:\n"
        "  commands/harness.md: { id: harness, version: 0.1.0, profiles: [harness] }\n"
        "meta:\n"
        "  registry.yaml: { id: registry, version: 0.4.1 }\n"
    )
    assert _is_registered(with_it), (
        "the predicate failed to detect a registered commands/harness.md entry — "
        "the registration guard would pass vacuously."
    )


def test_guard_reads_quoted_and_non_canonical_keys() -> None:
    """AC-1 (teeth): a quoted or non-canonical key that *resolves* to the command
    counts as registered.

    The installer would copy ``commands/./harness.md`` to ``commands/harness.md``
    all the same, so the registration check normalizes keys before comparing —
    the same normalization the footprint and retired guards use.
    """
    for key in ('"commands/harness.md"', "commands/./harness.md", "commands/x/../harness.md"):
        synthetic = (
            "registry_format: 1\n"
            "files:\n"
            f"  {key}: {{ id: harness, version: 0.1.0, profiles: [harness] }}\n"
            "meta:\n"
            "  registry.yaml: { id: registry, version: 0.4.1 }\n"
        )
        assert _is_registered(synthetic), (
            f"{key!r} resolves to {HARNESS_COMMAND} but the guard did not count "
            "it as registered."
        )
