"""CAL-1109 — no distributed prose cites an *app-only* path a consumer lacks.

``test_distributed_skill_cites.py`` (CAL-654) guards the adjacent class: a
``skills/<id>/SKILL.md`` cite that resolves to **nothing**. This guard covers
the inverse failure: a cite that resolves fine *in the harness* but points at a
path that never installs into a consuming repo — the harness **app**
(``harness/ docker/ bin/ scripts/ specs/ tests/``) or a repo-root operational
doc (``RUNBOOK.md``) that is not part of the installed surface. A consumer that
self-hosts the surface reads that prose and is sent to a path it does not have.

The class rode in through ``commands/harness.md``: its ``/harness routine``
section cited ``RUNBOOK.md`` and ``specs/decisions/0001-...``; a whole-file sweep
also found the same defect in ``agents/steward.md``, ``agents/reviewer.md`` and
``commands/assess.md`` (the harness's own design docs cited as reader
pointers). The precedent guarded only *skill* cites, so nothing pinned the wider
class.

The boundary is not re-typed here — it is **parsed from the recorded source**
(AC-2):

* the **App** side from ``specs/architecture-principles.md``'s "App vs. installed
  surface" enumeration (``**App** — `harness/ docker/ bin/ scripts/ specs/
  tests/```);
* the **registered** side from ``registry.yaml`` itself — every ``files:`` and
  ``meta:`` entry. A file with *zero* entries in ``registry.yaml`` is the
  discriminator the ticket names for ``RUNBOOK.md`` ("zero entries in
  registry.yaml"); a ``files:`` file installs into the consumer, and a ``meta:``
  file (``BOOTSTRAP.md``, ``registry.yaml``) is the guidance's own documented,
  version-stamped machinery a consumer legitimately follows to install/update —
  so neither is app-only, while an unregistered ``harness/``/``specs/``/root doc
  is.

So a renumber or a boundary edit moves the guard with it; the guard cannot drift
from the boundary it enforces.

Scope discriminators (why the guard does not flap on legitimate prose):

* **Resolution** — a cite is only judged if it resolves to a git-tracked harness
  file. A bare convention directory (``specs/features/``, ``specs/proposals/`` —
  which a consumer *generates* under the ``feature_specs`` layer / ``/propose``)
  is not a file, so it never matches; a template ``{e.g. specs/architecture.md}``
  names no real harness file, so it never matches.
* **Template placeholders** — ``{...}`` segments (the ``CONTEXT.template.md``
  ``{e.g. …}`` syntax) are stripped before scanning; they are examples a consumer
  fills in its own tree, not cites.
* **Home-path install locations** — ``~/bin/harness`` (the wrapper's documented
  install path under ``$HOME``) is not a repo cite: a path segment preceded by
  ``/``, ``~`` or ``.`` is inside a longer path and is not re-matched, so the
  ``bin/harness`` *inside* ``~/bin/harness`` never fires.
* **Registered + consumer-present** — a cite to any ``registry.yaml`` entry
  (installed surface ``templates/feature.md``; documented ``meta:`` machinery
  ``BOOTSTRAP.md``) or a file every repo carries (``CLAUDE.md``, ``README.md``,
  ``CONTEXT.md``) is resolvable/known in the consumer, so it is not a defect.

Acceptance criteria (CAL-1109):

* **AC-1** — the guard fails when distributed prose cites an app-only path.
  Proven live by :func:`test_detector_flags_an_app_only_cite` (a synthetic line
  citing ``harness/cli/close.py`` is flagged) and enforced across the tree by
  :func:`test_no_distributed_prose_cites_an_app_only_path`.
* **AC-2** — the app/surface split is parsed from the recorded boundary, not a
  hand-typed list. Proven by :func:`test_app_prefixes_come_from_the_boundary_doc`
  and :func:`test_registered_files_come_from_the_registry`.
"""

from __future__ import annotations

import re
from pathlib import Path

from tests._gitutil import tracked_files_under

# ``tests/unit/test_*.py`` → ``parents[2]`` is the repo (or worktree) root.
_REPO_ROOT = Path(__file__).resolve().parents[2]
_REGISTRY = _REPO_ROOT / "registry.yaml"
_PRINCIPLES = _REPO_ROOT / "specs" / "architecture-principles.md"

# Files a consuming repo resolves though they are not ``registry.yaml`` ``files:``
# entries: the installer-derived artifacts (architecture-principles.md, "App vs.
# installed surface": AGENTS/CLAUDE/GEMINI.md) and the repo-owned root docs every
# repo carries. A cite to one of these is not app-only.
_CONSUMER_PRESENT = frozenset(
    {"AGENTS.md", "CLAUDE.md", "GEMINI.md", "README.md", "CONTEXT.md", "SPEC.md"}
)

# A path-shaped cite: a slash-joined path (``harness/cli/close.py``,
# ``specs/decisions/0001-x.md``) or a bare SHOUTING root doc (``RUNBOOK.md``).
# The uppercase anchor on the bare-doc branch keeps it from matching ordinary
# lowercase ``foo.md`` prose while still catching ``RUNBOOK.md`` / ``ONBOARDING.md``.
# The ``(?<![\w./~])`` lookbehind on the slash branch stops a segment *inside* a
# longer path from re-matching — so ``bin/harness`` inside ``~/bin/harness`` (the
# documented home-dir install path) never fires.
_PATH_CITE = re.compile(
    r"(?<![\w./~])[\w.-]+(?:/[\w.-]+)+|(?<![\w/])[A-Z][A-Z0-9_]+\.md\b"
)

# Template placeholder syntax (``{e.g. …}``) — stripped before scanning.
_PLACEHOLDER = re.compile(r"\{[^}]*\}")


def _app_prefixes() -> tuple[str, ...]:
    """Parse the **App** enumeration from the recorded boundary (AC-2).

    The boundary line reads ``- **App** — `harness/ docker/ bin/ scripts/ specs/
    tests/`. …``. The app side of the split is exactly those trailing-slash
    prefixes; re-typing them here would let the guard drift from the boundary.
    """
    for line in _PRINCIPLES.read_text().splitlines():
        match = re.search(r"\*\*App\*\*\s*—\s*`([^`]+)`", line)
        if match:
            prefixes = tuple(
                sorted(tok for tok in match.group(1).split() if tok.endswith("/"))
            )
            if prefixes:
                return prefixes
    raise AssertionError(
        "architecture-principles.md must record the **App** boundary enumeration"
    )


def _registry_entries(block: str) -> set[str]:
    """The path keys under a top-level ``registry.yaml`` block (``files:``/``meta:``)."""
    members: set[str] = set()
    in_block = False
    for line in _REGISTRY.read_text().splitlines():
        if line.startswith(f"{block}:"):
            in_block = True
            continue
        if in_block:
            # the block ends at the next top-level key (column 0, not a comment)
            if line and not line[0].isspace() and not line.lstrip().startswith("#"):
                break
            entry = re.match(r"\s{2}(\S+?):\s*\{", line)
            if entry:
                members.add(entry.group(1))
    return members


def _surface_members() -> set[str]:
    """The ``registry.yaml`` ``files:`` membership — the installed surface (AC-2)."""
    return _registry_entries("files")


def _registered_files() -> set[str]:
    """Every path registered in ``registry.yaml`` — ``files:`` (installed) plus
    ``meta:`` (the guidance's documented machinery). A cite to any of these is
    resolvable or known in a consumer; a file with *zero* entries is app-only."""
    return _surface_members() | _registry_entries("meta")


def _resolve(cite: str, rel_dir: str, tracked: set[Path]) -> str | None:
    """The repo-relative path a cite resolves to, or ``None`` if it names no
    tracked file. A cite is resolved both as a **repo-root** path (how prose
    names ``harness/cli/start.py``) and as a **file-relative** markdown link (how
    ``[0002](../specs/decisions/0002-...)`` names it, relative to the citing
    file's directory) — the first that lands on a tracked file wins."""
    for base in ((_REPO_ROOT / cite), (_REPO_ROOT / rel_dir / cite)):
        resolved = base.resolve()
        try:
            rel = resolved.relative_to(_REPO_ROOT).as_posix()
        except ValueError:
            continue  # a leading ``../`` walked outside the repo — not this cite
        if resolved in tracked:
            return rel
    return None


def _scan_text(text: str, rel_dir: str = ".") -> list[tuple[int, str]]:
    """Return ``(line_number, cite)`` for each app-only path cite in ``text``.

    A cite is app-only when it resolves to a git-tracked harness file that is
    neither registered in ``registry.yaml`` nor a consumer-present root doc, and
    it lives under an App prefix or is a bare unregistered root doc. ``rel_dir``
    is the citing file's directory (repo-relative), so file-relative markdown
    links resolve correctly.
    """
    tracked = tracked_files_under(".")
    prefixes = _app_prefixes()
    registered = _registered_files()
    hits: list[tuple[int, str]] = []
    for line_no, line in enumerate(text.splitlines(), start=1):
        scrubbed = _PLACEHOLDER.sub("", line)
        for match in _PATH_CITE.finditer(scrubbed):
            cite = match.group(0).rstrip(".,;:)")
            resolved = _resolve(cite, rel_dir, tracked)
            if resolved is None:
                continue  # not a real harness file — the non-resolution class
            if resolved in registered or resolved in _CONSUMER_PRESENT:
                continue  # installed / documented machinery / present in consumer
            under_app = any(resolved.startswith(prefix) for prefix in prefixes)
            is_root_doc = "/" not in resolved
            if under_app or is_root_doc:
                hits.append((line_no, cite))
    return hits


def _surface_md_files() -> list[str]:
    """The ``.md`` surface units — the reader-facing distributed prose."""
    return sorted(f for f in _surface_members() if f.endswith(".md"))


# --- AC-2: the boundary is parsed, not re-typed ------------------------------


def test_app_prefixes_come_from_the_boundary_doc() -> None:
    prefixes = _app_prefixes()
    for expected in ("harness/", "docker/", "bin/", "scripts/", "specs/", "tests/"):
        assert expected in prefixes, (
            f"the App boundary enumeration must include {expected!r}"
        )


def test_registered_files_come_from_the_registry() -> None:
    registered = _registered_files()
    # non-vacuous anchor: known surface (files:) and machinery (meta:) units
    assert "commands/harness.md" in registered
    assert "agents/steward.md" in registered
    assert "templates/feature.md" in registered
    assert "BOOTSTRAP.md" in registered  # meta: — documented machinery, not app-only


# --- AC-1: the detector actually fires ---------------------------------------


def test_detector_flags_an_app_only_cite() -> None:
    """A synthetic line citing an app file is flagged (the mechanism is live)."""
    flagged = _scan_text("the verb lives in `harness/cli/close.py` today")
    assert flagged == [(1, "harness/cli/close.py")], flagged


def test_detector_flags_a_bare_app_root_doc() -> None:
    flagged = _scan_text("see RUNBOOK.md for the operator loop")
    assert flagged == [(1, "RUNBOOK.md")], flagged


def test_detector_flags_a_relative_markdown_link() -> None:
    """A ``../`` link resolves against the citing file's dir, not repo root — so
    ``[0002](../specs/decisions/0002-...)`` from ``commands/`` is caught, not
    silently walked outside the tree (the CAL-1109 review regression)."""
    line = "(ADR [`0002`](../specs/decisions/0002-in-container-review-engine.md))"
    flagged = _scan_text(line, rel_dir="commands")
    assert flagged == [(1, "../specs/decisions/0002-in-container-review-engine.md")], flagged


def test_detector_ignores_a_relative_link_to_registered_meta() -> None:
    """``[BOOTSTRAP.md](../BOOTSTRAP.md)`` resolves to registered machinery."""
    assert _scan_text("re-run [`BOOTSTRAP.md`](../BOOTSTRAP.md)", rel_dir="commands") == []


def test_detector_ignores_a_consumer_convention_dir() -> None:
    """A bare ``specs/features/`` directory (consumer-generated) is not a cite."""
    assert _scan_text("the reviewer records to specs/features/ on pass") == []


def test_detector_ignores_a_surface_cite() -> None:
    """A cite to an installed surface file resolves in the consumer."""
    assert _scan_text("use `templates/feature.md` for the record") == []


def test_detector_ignores_a_template_placeholder() -> None:
    """``{e.g. bash scripts/verify.sh}`` is a placeholder, not a cite."""
    assert _scan_text("verify: {the gate — e.g. bash scripts/verify.sh}") == []


def test_detector_ignores_a_registered_meta_doc() -> None:
    """``BOOTSTRAP.md`` is registered (meta:) machinery — not an app-only cite."""
    assert _scan_text("the other half of `BOOTSTRAP.md`: version stamps") == []


def test_detector_ignores_the_home_dir_install_path() -> None:
    """``~/bin/harness`` is the wrapper's install path, not a repo cite."""
    assert _scan_text("`harness` must be on PATH as `~/bin/harness` today") == []


# --- AC-1: the tree is clean -------------------------------------------------


def test_no_distributed_prose_cites_an_app_only_path() -> None:
    violations: list[str] = []
    for name in _surface_md_files():
        rel_dir = Path(name).parent.as_posix()
        for line_no, cite in _scan_text((_REPO_ROOT / name).read_text(), rel_dir):
            violations.append(f"{name}:{line_no}: {cite}")
    assert not violations, (
        "distributed prose cites an app-only path a consuming repo does not have "
        "(the harness app or an unregistered root doc — see CAL-1109):\n  "
        + "\n  ".join(violations)
    )
