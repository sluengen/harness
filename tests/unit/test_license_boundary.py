"""The repo is dual-licensed along the boundary ``registry.yaml`` already draws.

The repo shipped MIT, which permits exactly what it intends to prevent: a fork
taken proprietary and sold with nothing returned. A single copyleft licence over
the whole tree is the wrong instrument, because the repo holds two artifacts with
different distribution models:

* **The engine** (``harness/`` ``bin/`` ``docker/`` ``scripts/``) — a CLI the user
  runs, and the thing a third party would fork and productize. Copyleft here does
  the intended work, so it is **AGPL-3.0-only**.
* **The installed guidance** — the files the installer physically copies into a
  third-party repo and commits there (the copy-in model, ``BOOTSTRAP.md``).
  Copyleft here would block adoption of the very thing the harness exists to
  spread while protecting nothing, since a licence covers expression and not
  method. So it is **MIT**.

The boundary is not a hand-maintained directory list: ``registry.yaml``'s
``files:`` block *is* the set copied into someone else's repo, so it is the
authoritative definition of "distributed", and a newly registered file inherits
the correct side automatically. ``LICENSE-GUIDANCE`` declares its scope as path
prefixes; these tests hold that declaration and the registry in correspondence.

Acceptance criteria (executable form):

* **AC-1** — ``LICENSE`` carries the AGPL-3.0 text with its operative body
  unmodified (:func:`test_license_body_is_verbatim_agpl`, a byte-exact pin
  against the canonical gnu.org text); ``LICENSE-GUIDANCE`` carries MIT's
  (:func:`test_guidance_licence_is_mit`).
* **AC-2** — ``pyproject.toml`` declares the SPDX identifier
  (:func:`test_pyproject_declares_agpl`).
* **AC-3** — the registry-to-licence-scope correspondence holds in **both**
  directions: no distributed file escapes the MIT scope
  (:func:`test_every_distributed_file_is_mit_scoped`) and the scope never reaches
  the engine or over-claims (:func:`test_mit_scope_excludes_the_engine`,
  :func:`test_mit_scope_has_no_dead_prefix`). Non-vacuity is anchored by
  :func:`test_boundary_check_catches_an_escaped_path`.
* **AC-4** — ``README.md`` and ``CONTRIBUTING.md`` state the split, and
  ``CONTRIBUTING.md`` states the inbound relicensing grant that keeps
  dual-licensing available (:func:`test_readme_states_the_split`,
  :func:`test_contributing_states_inbound_grant`).
* **AC-5** — the installer carries the MIT notice into the target repo, or the
  carve-out is invisible where it matters (:func:`test_bootstrap_installs_the_guidance_licence`).

Supersedes ``tests/unit/test_license.py`` (the CAL-1025 MIT guard), whose premise
— "the repo ships an MIT license" — this change falsifies. Its two contracts that
outlived it are kept here rather than dropped: both licences must be **git-tracked**
(:func:`test_both_licences_are_tracked`), since a public reader sees only the
committed tree and never the author's disk, and both must name the copyright holder
(:func:`test_both_licences_name_the_copyright_holder`).
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

from tests._gitutil import tracked_files_under

# ``tests/unit/test_*.py`` → ``parents[2]`` is the repo (or worktree) root.
_REPO_ROOT = Path(__file__).resolve().parents[2]
_LICENSE = _REPO_ROOT / "LICENSE"
_LICENSE_GUIDANCE = _REPO_ROOT / "LICENSE-GUIDANCE"
_REGISTRY = _REPO_ROOT / "registry.yaml"
_PYPROJECT = _REPO_ROOT / "pyproject.toml"
_README = _REPO_ROOT / "README.md"
_CONTRIBUTING = _REPO_ROOT / "CONTRIBUTING.md"
_BOOTSTRAP = _REPO_ROOT / "BOOTSTRAP.md"

#: First line of the AGPL-3.0 body. The scope note is *prepended* above this
#: line; the licence body itself is never edited, so the body starts here.
_AGPL_BODY_START = "                    GNU AFFERO GENERAL PUBLIC LICENSE"

#: SHA-256 of the canonical AGPL-3.0 text as published at
#: https://www.gnu.org/licenses/agpl-3.0.txt — verified word-for-word against
#: the SPDX license-list copy (5,535 words, identical) when this landed. The
#: licence is frozen (2007), so pinning its bytes is the executable form of
#: "verbatim": any edit to the operative text fails here.
_AGPL_BODY_SHA256 = "0d96a4ff68ad6d4b6f1f30f713b18d5184912ba8dd389f86aa7710db079abcb0"

#: Engine roots — never MIT. ``harness/`` is the load-bearing one (the CLI a
#: third party would fork); the rest are named so the scope cannot creep.
_ENGINE_PREFIXES = ("harness/", "tests/", "scripts/", "docker/", "bin/")


def _mit_scope_prefixes(text: str) -> tuple[str, ...]:
    """The path prefixes ``LICENSE-GUIDANCE`` declares as MIT-covered.

    The scope is declared as an indented block of ``<dir>/`` lines under a
    ``Scope`` marker, so it is machine-checkable rather than prose a reader has
    to interpret — these tests hold it against the registry in both directions.
    """
    block = re.search(r"^Scope\b.*?$\n(?P<body>(?:\n|[ \t]+\S.*$\n)+)", text, re.M)
    assert block, "could not find the Scope block in LICENSE-GUIDANCE"
    return tuple(re.findall(r"^\s+([A-Za-z0-9_./-]+/)\s*$", block.group("body"), re.M))


def _registry_files(registry_src: str) -> tuple[str, ...]:
    """Every path in ``registry.yaml``'s ``files:`` block.

    Mirrors the membership rule the freshness hook uses (a ``<path>: {`` mapping
    key), scoped to the ``files:`` block so the ``meta:`` block — version-stamped
    but *not* installed into a repo — stays out.
    """
    files_block = re.search(r"^files:\s*$\n(?P<body>.*?)(?=^meta:\s*$)", registry_src, re.M | re.S)
    assert files_block, "could not find the files: block in registry.yaml"
    return tuple(re.findall(r"^\s{2}(\S+):\s*\{", files_block.group("body"), re.M))


def _is_mit_scoped(rel_path: str, prefixes: tuple[str, ...]) -> bool:
    return any(rel_path.startswith(p) for p in prefixes)


def test_license_body_is_verbatim_agpl() -> None:
    """``LICENSE`` carries the AGPL-3.0 body byte-for-byte (AC-1).

    GitHub's licence detector reads ``LICENSE``, and a licence whose operative
    text has drifted is not the licence it claims to be. The scope note is
    prepended above the body; everything from the title line down must hash to
    the canonical text.
    """
    text = _LICENSE.read_text()
    assert _AGPL_BODY_START in text, "LICENSE does not carry the AGPL-3.0 body"
    body = text[text.index(_AGPL_BODY_START) :]
    assert hashlib.sha256(body.encode()).hexdigest() == _AGPL_BODY_SHA256, (
        "the AGPL-3.0 body in LICENSE is not the canonical text — it must be "
        "verbatim; put any repo-specific wording in the prepended scope note"
    )


def test_license_scope_note_names_the_carve_out() -> None:
    """The AGPL file itself points at the MIT carve-out (AC-1).

    A bare AGPL ``LICENSE`` would read as covering the whole tree, which is the
    opposite of the intent for the installed guidance.
    """
    note = _LICENSE.read_text().split(_AGPL_BODY_START)[0]
    assert "SPDX-License-Identifier: AGPL-3.0-only" in note
    assert "LICENSE-GUIDANCE" in note, "the scope note must point at the MIT carve-out"
    assert "registry.yaml" in note, "the scope note must name the authoritative boundary"


def test_scope_note_stays_within_licence_detection_margin() -> None:
    """The scope note stays short enough that GitHub still detects AGPL-3.0 (AC-1).

    The measuring test for the requirement the note puts at risk. GitHub detects
    a licence with ``licensee``, which scores the file against each known licence
    text by Dice coefficient and needs **98%** to report a match rather than
    "Other". Prepended prose is foreign content: it dilutes the score, and the
    sidebar badge is the single most visible signal that this repo is copyleft --
    the whole point of the change. An earlier 157-word note scored ~98.6%, which
    is a 0.6-point margin on an estimate, so the note was cut to a terse pointer
    with the rationale left to README and LICENSE-GUIDANCE.

    The bound is derived, not guessed. With ``b`` body words and ``n`` note
    words, Dice is ``2b / ((n + b) + b)``; holding that at >= 99% against the
    AGPL's 5,535 words allows ``n <= 111``. The assertion sits at 100 for
    headroom, since this approximates licensee's tokenisation rather than
    reproducing it -- it is a canary for a note that grew, not a precise oracle.
    """
    text = _LICENSE.read_text()
    note, body = text.split(_AGPL_BODY_START)[0], _AGPL_BODY_START + text.split(_AGPL_BODY_START)[1]
    note_words, body_words = len(note.split()), len(body.split())
    dice = 2 * body_words / ((note_words + body_words) + body_words)
    assert note_words <= 100, (
        f"the LICENSE scope note is {note_words} words (max 100): it dilutes licence "
        f"detection to ~{dice * 100:.1f}% and risks GitHub reporting 'Other' instead of "
        "AGPL-3.0. Put the explanation in README.md or LICENSE-GUIDANCE, not here."
    )


def test_both_licences_are_tracked() -> None:
    """Both licence files are committed, not just present on disk (AC-1).

    Inherited from the superseded CAL-1025 guard: a public reader sees only the
    committed tree, so a licence that exists solely on an author's disk grants
    nobody anything. Git-aware by construction.
    """
    assert _LICENSE.resolve() in tracked_files_under("LICENSE"), (
        "No tracked LICENSE at the repo root — a public reader looks for it there."
    )
    assert _LICENSE_GUIDANCE.resolve() in tracked_files_under("LICENSE-GUIDANCE"), (
        "No tracked LICENSE-GUIDANCE — the MIT carve-out would be invisible to a reader."
    )


def test_both_licences_name_the_copyright_holder() -> None:
    """Both licences carry the copyright line (AC-1).

    Inherited from the superseded CAL-1025 guard. The AGPL's own "how to apply"
    appendix expects the notice, and MIT's grant is meaningless without one.
    """
    assert "Scott Luengen" in _LICENSE.read_text(), "LICENSE must name the copyright holder"
    assert "Scott Luengen" in _LICENSE_GUIDANCE.read_text(), (
        "LICENSE-GUIDANCE must name the copyright holder"
    )


def test_guidance_licence_is_mit() -> None:
    """``LICENSE-GUIDANCE`` carries MIT's operative text (AC-1)."""
    text = _LICENSE_GUIDANCE.read_text()
    assert "SPDX-License-Identifier: MIT" in text
    for clause in (
        "Permission is hereby granted, free of charge",
        "without restriction, including without limitation the rights",
        "THE SOFTWARE IS PROVIDED \"AS IS\", WITHOUT WARRANTY OF ANY KIND",
    ):
        assert clause in text, f"MIT text is missing its operative clause: {clause!r}"


def test_pyproject_declares_agpl() -> None:
    """The package metadata declares the engine's licence (AC-2)."""
    assert re.search(
        r'^license\s*=\s*"AGPL-3\.0-only"\s*$', _PYPROJECT.read_text(), re.M
    ), "pyproject.toml must declare license = \"AGPL-3.0-only\""


def test_every_distributed_file_is_mit_scoped() -> None:
    """Nothing the installer copies out escapes the MIT scope (AC-3).

    This is the load-bearing direction. A distributed file outside the MIT scope
    is AGPL by default, so it would land committed inside a third-party repo and
    encumber it — the exact failure the split exists to prevent. A newly
    registered file in an unscoped directory fails here.
    """
    prefixes = _mit_scope_prefixes(_LICENSE_GUIDANCE.read_text())
    escaped = [p for p in _registry_files(_REGISTRY.read_text()) if not _is_mit_scoped(p, prefixes)]
    assert not escaped, (
        f"registry.yaml distributes {escaped} but LICENSE-GUIDANCE does not cover them — "
        f"they would ship AGPL into a third-party repo. Declared scope: {list(prefixes)}"
    )


def test_mit_scope_excludes_the_engine() -> None:
    """The MIT scope never reaches the engine (AC-3).

    The engine is the thing copyleft is *for*. A scope prefix that swallowed
    ``harness/`` would silently relicense the CLI permissively and void the whole
    point of the change.
    """
    prefixes = _mit_scope_prefixes(_LICENSE_GUIDANCE.read_text())
    for engine in _ENGINE_PREFIXES:
        assert not _is_mit_scoped(engine, prefixes), (
            f"LICENSE-GUIDANCE scope covers engine path {engine!r} — the engine must stay AGPL"
        )


def test_mit_scope_has_no_dead_prefix() -> None:
    """Every declared prefix actually holds distributed files (AC-3).

    Guards the over-claiming direction: a prefix naming a directory the registry
    does not distribute would hand out an MIT grant over engine code that merely
    happens to live there.
    """
    registry_files = _registry_files(_REGISTRY.read_text())
    for prefix in _mit_scope_prefixes(_LICENSE_GUIDANCE.read_text()):
        assert any(f.startswith(prefix) for f in registry_files), (
            f"LICENSE-GUIDANCE claims {prefix!r} but registry.yaml distributes nothing under it — "
            "the MIT grant would over-reach"
        )


def test_mit_scope_covers_only_tracked_guidance() -> None:
    """Each declared prefix resolves to real, git-tracked files (AC-3).

    A scope prefix pointing at nothing on disk is a licence grant over a phantom;
    it also means the registry and the tree have drifted.
    """
    for prefix in _mit_scope_prefixes(_LICENSE_GUIDANCE.read_text()):
        assert tracked_files_under(prefix.rstrip("/")), (
            f"LICENSE-GUIDANCE scope names {prefix!r}, which tracks no files"
        )


def test_boundary_check_catches_an_escaped_path() -> None:
    """The correspondence check is non-vacuous (AC-3).

    Without this, a scope-parse that silently returned everything — or a registry
    parse that returned nothing — would make the guards above pass by accident.
    """
    prefixes = _mit_scope_prefixes(_LICENSE_GUIDANCE.read_text())
    assert _is_mit_scoped("skills/code-quality/SKILL.md", prefixes), "a distributed file must scope"
    assert not _is_mit_scoped("harness/cli/close.py", prefixes), "an engine file must not scope"
    # The registry parse must find the real distributed set, not an empty one.
    files = _registry_files(_REGISTRY.read_text())
    assert "skills/code-quality/SKILL.md" in files, "registry files: parse missed a known entry"
    assert "BOOTSTRAP.md" not in files, "the meta: block must stay out of the distributed set"


def test_readme_states_the_split() -> None:
    """``README.md`` tells a reader which licence applies to what (AC-4)."""
    text = _README.read_text()
    assert "AGPL-3.0" in text, "README must name the engine licence"
    assert "LICENSE-GUIDANCE" in text, "README must point at the guidance licence"


def test_contributing_states_inbound_grant() -> None:
    """``CONTRIBUTING.md`` states the inbound relicensing grant (AC-4).

    Under inbound-equals-outbound, one accepted outside PR would permanently
    remove the ability to relicense, because the maintainer would no longer hold
    all copyright. The grant is what keeps that option open, so its absence is a
    silent, irreversible loss — worth pinning.
    """
    text = _CONTRIBUTING.read_text()
    assert "Inbound licensing" in text, "CONTRIBUTING must carry an Inbound licensing section"
    assert "relicense" in text.lower(), "the inbound grant must state the relicensing right"
    assert "AGPL-3.0" in text and "MIT" in text, "the inbound section must name both licences"


def test_bootstrap_installs_the_guidance_licence() -> None:
    """The installer carries the MIT notice into the target repo (AC-5).

    Without this the carve-out is invisible where it matters: the receiving repo
    holds unmarked markdown cloned from an AGPL source, and a compliance scanner
    assumes the worst — which is the adoption blocker the split exists to avoid.
    """
    assert "LICENSE-GUIDANCE" in _BOOTSTRAP.read_text(), (
        "BOOTSTRAP.md must install LICENSE-GUIDANCE alongside the guidance it copies"
    )
