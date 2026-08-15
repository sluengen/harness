"""Footprint guard — the installed surface excludes every app path (CAL-648).

The harness repo holds two things that must never bleed into each other: the
harness *app* (``scripts/ specs/ tests/`` — never
installed into a target repo) and the *surface* it installs (``commands/
skills/ agents/ templates/ hooks/ process/ settings/``, enumerated by
``registry.yaml``'s ``files:`` block). After the guidance merge the boundary is
a convention inside one tree rather than a repo wall, so it needs structural
enforcement: an app file must not be able to ride the install into a target
repo by being added to a registry ``files:`` entry.

This guard asserts ``registry.yaml``'s ``files:`` paths exclude every app path,
*eliminating* — not merely mitigating — the version-entanglement risk between
the app's release line and the surface's per-unit ``guidance:<id>@x.y.z``
versions.

*Source:* ``specs/architecture-principles.md`` (the "App vs. installed surface"
principle and the "Merge the guidance repo into the harness" decision, D5).
"""

from __future__ import annotations

import posixpath
import re
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent.parent
REGISTRY = REPO_ROOT / "registry.yaml"

#: Top-level directories that are the harness *app* — never the installed
#: surface (``specs/architecture-principles.md``, "App vs. installed surface";
#: merge decision D5). A registry ``files:`` entry under any of these would
#: entangle the app's release line with the installed surface.
APP_PREFIXES = ("scripts/", "specs/", "tests/")

#: The directories that *are* the installed surface, enumerated verbatim from the
#: "App vs. installed surface" principle. The installer copies a registry entry
#: to the same path in the target tree, so a path is only legitimately surface
#: when it resolves within one of these. Asserting membership here (not merely
#: "not under an app dir") catches an entry that escapes via ``..`` traversal —
#: e.g. ``skills/../scripts/mutate.py`` resolves to an app file but would clear a
#: bare app-prefix denylist.
SURFACE_PREFIXES = (
    "commands/",
    "skills/",
    "agents/",
    "templates/",
    "hooks/",
    "process/",
    "settings/",
)


def _normalize(path: str) -> str:
    """Lexically normalize a registry path the way the installer's copy target
    would resolve it, collapsing ``..`` traversal (``skills/../scripts/x`` →
    ``scripts/x``) so the prefix checks see the real destination."""
    return posixpath.normpath(path)


#: A mapping-entry line: leading indent, an optionally quoted key, then a colon.
#: Permissive on purpose — it reads the key from ``path: {...}``, the quoted
#: ``"path": {...}``, and block ``path:`` forms alike. A *strict* "path: {...}"
#: regex would silently skip a quoted or block-style entry, letting an app path
#: ride into the surface unflagged while the parser still looked healthy (the
#: bypass codex flagged on CAL-648); a key-first match closes that hole.
_KEY_RE = re.compile(r"""\s+(?P<q>["']?)(?P<key>[^"'\s:]+)(?P=q)\s*:""")

#: A *plain literal* path: word chars, ``/``, ``.``, ``-`` only — the shape every
#: real registry key has. A key outside this set (a backslash escape such as
#: ``skills/\x2e\x2e/scripts/mutate.py``, which YAML decodes to ``skills/../...``,
#: or any other non-literal spelling) cannot be reasoned about by the lexical
#: prefix checks, which see the *raw* text, not YAML's decoded value. The guard
#: therefore accepts only plain literals and rejects everything else loudly —
#: closing the raw-vs-decoded bypass class, since a plain literal decodes to
#: itself (codex P2, CAL-648).
_PLAIN_PATH_RE = re.compile(r"[\w./-]+\Z")


def _files_entry_lines() -> list[str]:
    """The non-comment, non-blank lines of ``registry.yaml``'s ``files:`` block.

    The ``profiles:`` and ``meta:`` blocks are excluded by slicing to the
    ``files:`` section (between the ``files:`` and ``meta:`` headers), exactly as
    ``test_guidance_source._registry_files`` does. A line regex avoids coupling
    the test to a transitive ``yaml`` import — PyYAML is not a declared
    dependency.
    """
    text = REGISTRY.read_text()
    start = text.index("\nfiles:")
    end = text.index("\nmeta:", start)
    lines: list[str] = []
    for line in text[start:end].splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or stripped == "files:":
            continue
        lines.append(line)
    return lines


def _registry_file_paths() -> list[str]:
    """The path keys of ``registry.yaml``'s ``files:`` block, quoted or not."""
    paths: list[str] = []
    for line in _files_entry_lines():
        m = _KEY_RE.match(line)
        if m:
            paths.append(m.group("key"))
    return paths


def _app_paths(paths: list[str]) -> list[str]:
    """The subset of ``paths`` that resolve under an app directory.

    Normalizes first so a ``..``-traversal entry that resolves into an app dir
    is caught, not just one written with a literal app prefix.
    """
    return [p for p in paths if _normalize(p).startswith(APP_PREFIXES)]


def _non_surface_paths(paths: list[str]) -> list[str]:
    """The subset of ``paths`` that do *not* resolve within a surface dir."""
    return [p for p in paths if not _normalize(p).startswith(SURFACE_PREFIXES)]


def _symlink_escapes(root: Path, paths: list[str]) -> list[str]:
    """Registry ``paths`` whose *real* on-disk target escapes the surface.

    Lexical normalization sees only the registry string, so a surface-looking
    entry (``skills/internal.md``) that is a **symlink** to app code
    (``../scripts/mutate.py``) would clear the lexical checks yet install app code
    when dereferenced. Resolve each materialized path against ``root`` and flag
    any whose real target leaves ``root`` or lands outside a surface directory.
    Paths not yet on disk are skipped — the lexical checks already cover them.
    """
    root = root.resolve()
    bad: list[str] = []
    for p in paths:
        target = root / p
        if not target.exists() and not target.is_symlink():
            continue
        try:
            rel = target.resolve().relative_to(root).as_posix()
        except ValueError:
            bad.append(p)  # resolves outside the repo entirely
            continue
        if not (rel + "/").startswith(SURFACE_PREFIXES) or _normalize(rel).startswith(
            APP_PREFIXES
        ):
            bad.append(p)
    return bad


def test_registry_lists_surface_files() -> None:
    """Guard the parser: the registry must list surface entries to check.

    A parser that silently returned nothing would make the exclusion test pass
    vacuously, so anchor on a known-present surface prefix first.
    """
    paths = _registry_file_paths()
    assert any(p.startswith("skills/") for p in paths), (
        "registry.yaml's files: block parsed to no skills/ entries — the parser "
        "or the copy-list is broken; the footprint guard would pass vacuously."
    )


def test_registry_excludes_app_paths() -> None:
    """AC-2: no ``registry.yaml`` ``files:`` entry is under an app directory."""
    offenders = _app_paths(_registry_file_paths())
    assert not offenders, (
        f"registry.yaml's files: block lists app path(s) {offenders!r}. App code "
        f"({', '.join(APP_PREFIXES)}) must never be installed into a target repo "
        "— it would entangle the app's release line with the installed surface. "
        "Remove the entry, or, if it is genuinely surface, reconsider the "
        "boundary (specs/architecture-principles.md, 'App vs. installed surface')."
    )


def test_registry_paths_are_within_a_surface_dir() -> None:
    """AC-2 (positive form): every ``files:`` entry resolves within a surface dir.

    The allowlist complement of the app-path exclusion: an entry must land under
    one of the enumerated surface directories. This catches not only app paths
    but also a ``..``-traversal entry (``skills/../scripts/x``) that resolves out
    of the surface, which a bare app-prefix denylist would miss.
    """
    offenders = _non_surface_paths(_registry_file_paths())
    assert not offenders, (
        f"registry.yaml's files: block lists path(s) {offenders!r} that do not "
        f"resolve within a surface directory ({', '.join(SURFACE_PREFIXES)}). "
        "Only surface files are installed into target repos "
        "(specs/architecture-principles.md, 'App vs. installed surface')."
    )


def test_registry_paths_resolve_within_surface() -> None:
    """AC-2 (symlink form): every materialized ``files:`` entry's real on-disk
    target stays within a surface dir — a registry path that symlinks into an
    app dir installs app code even though its string looks like surface (codex
    P2, CAL-648)."""
    escapes = _symlink_escapes(REPO_ROOT, _registry_file_paths())
    assert not escapes, (
        f"registry.yaml's files: block lists path(s) {escapes!r} whose real "
        "target (after resolving symlinks) leaves the surface. A surface entry "
        "must not dereference to app code "
        "(specs/architecture-principles.md, 'App vs. installed surface')."
    )


def test_registry_keys_are_plain_literal_paths() -> None:
    """AC-2 (encoding form): every ``files:`` key is a plain literal path.

    The lexical prefix checks compare the *raw* key text, so a YAML-escaped key
    such as ``"skills/\\x2e\\x2e/scripts/mutate.py"`` (which decodes to
    ``skills/../scripts/mutate.py``) would clear them while the installer copies app
    code. Rejecting any non-literal key closes that raw-vs-decoded gap: a plain
    literal decodes to itself, so what the checks see is what gets installed
    (codex P2, CAL-648).
    """
    exotic = [p for p in _registry_file_paths() if not _PLAIN_PATH_RE.fullmatch(p)]
    assert not exotic, (
        f"registry.yaml's files: block has non-literal key(s) {exotic!r}. Keys "
        "must be plain literal paths ([\\w./-]); an escaped or quoted-with-escapes "
        "key can decode to an app path the prefix checks cannot see. Write the "
        "path plainly."
    )


def test_escape_encoded_app_key_is_rejected() -> None:
    """AC-1 (encoding form): a YAML-escaped key that decodes to an app path does
    not match the plain-literal rule, so the guard rejects it (codex P2)."""
    encoded = r"skills/\x2e\x2e/scripts/mutate.py"
    assert not _PLAIN_PATH_RE.fullmatch(encoded), (
        f"{encoded!r} contains escapes that decode to an app path but was "
        "accepted as a plain literal — the guard would not flag it."
    )


def test_every_files_entry_line_is_parsed() -> None:
    """No entry line is silently skipped (codex P2, CAL-648).

    A line the key extractor cannot read could hide an app path while
    ``test_registry_excludes_app_paths`` still passes vacuously, so every
    non-comment, non-blank line in the ``files:`` section must yield a key — an
    unrecognized entry fails loudly here rather than slipping through.
    """
    unparsed = [line for line in _files_entry_lines() if not _KEY_RE.match(line)]
    assert not unparsed, (
        "registry.yaml's files: block has line(s) the footprint parser cannot "
        f"read as a key: {unparsed!r}. An unparsed entry could hide an app path "
        "from the exclusion guard — fix the line's shape or broaden _KEY_RE."
    )


def test_parser_reads_quoted_and_unquoted_keys() -> None:
    """Regression for the codex P2 bypass: the key extractor must read quoted
    keys, or a quoted app entry like ``"scripts/foo.py": {...}`` would slip past
    the exclusion guard."""
    cases = {
        "  skills/foo.md: { id: foo }": "skills/foo.md",
        '  "scripts/foo.py": { id: x }': "scripts/foo.py",
        "  'tests/run.sh': { id: y }": "tests/run.sh",
    }
    for line, expected in cases.items():
        m = _KEY_RE.match(line)
        assert m and m.group("key") == expected, (
            f"_KEY_RE failed to read the key {expected!r} from {line!r} — a "
            "quoted app path could bypass the footprint guard."
        )


def test_guard_flags_an_app_path() -> None:
    """AC-1: the guard fails when an app path is added to a ``files:`` entry.

    A negative assertion proving the exclusion check has teeth: feed it a
    synthetic registry path under each app directory and confirm every one is
    flagged. Without this, a future refactor of the predicate could neuter the
    guard and ``test_registry_excludes_app_paths`` would still pass on the
    (clean) live registry.
    """
    synthetic = [f"{prefix}injected_app_file.py" for prefix in APP_PREFIXES]
    assert _app_paths(synthetic) == synthetic, (
        "the footprint predicate failed to flag a synthetic app path — the "
        "exclusion guard has no teeth and would not catch an app file added to "
        "registry.yaml's files: block."
    )


def test_guard_flags_a_traversal_app_path() -> None:
    """AC-1 (traversal form): an entry that escapes a surface dir via ``..`` and
    resolves into an app dir is still flagged — a lexical prefix check alone
    would be fooled by ``skills/../scripts/mutate.py`` (codex P2, CAL-648)."""
    traversal = "skills/../scripts/mutate.py"
    assert _app_paths([traversal]) == [traversal], (
        f"{traversal!r} resolves to an app file but was not flagged — the guard "
        "must normalize paths before the app-prefix check."
    )
    assert _non_surface_paths([traversal]) == [traversal], (
        f"{traversal!r} resolves outside every surface dir but the allowlist "
        "did not flag it."
    )


def test_guard_flags_a_symlinked_app_path(tmp_path: Path) -> None:
    """AC-1 (symlink form): a surface-named entry that is a symlink to app code
    is flagged once its real target is resolved (codex P2, CAL-648)."""
    (tmp_path / "harness").mkdir()
    (tmp_path / "harness" / "cli.py").write_text("# app code\n")
    (tmp_path / "skills").mkdir()
    link = tmp_path / "skills" / "internal.md"
    link.symlink_to(Path("..") / "harness" / "cli.py")

    assert _symlink_escapes(tmp_path, ["skills/internal.md"]) == ["skills/internal.md"], (
        "a surface-named entry symlinked to app code was not flagged — the guard "
        "must resolve symlinks before judging the boundary."
    )
