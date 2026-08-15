"""The repo is dual-licensed along the boundary ``registry.yaml`` already draws.

The repo shipped MIT, which permits exactly what it intends to prevent: a fork
taken proprietary and sold with nothing returned. A single copyleft licence over
the whole tree is the wrong instrument, because the repo holds two artifacts with
different distribution models:

* **The engine** (``harness/`` ``scripts/``) — a CLI the user
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
the correct side automatically. ``GUIDANCE-MIT.md`` declares its scope as path
prefixes; these tests hold that declaration and the registry in correspondence.

**Why the guidance licence is not named ``LICENSE-GUIDANCE`` (CAL-1198).** GitHub
detects a repo's licence with ``licensee``, which resolves the whole repo to a
*single* SPDX id only when exactly one licence is present, or all matched licence
files agree. Two *different* licences at the root — even each a 100% match — make
it return ``NOASSERTION`` and the sidebar reads "Other". Measured directly: with
``LICENSE`` at 100% AGPL-3.0 and ``LICENSE-GUIDANCE`` at 100% MIT, the repo verdict
was still ``NOASSERTION``. ``licensee`` treats any root file whose name carries a
``licen[sc]e``/``copying`` stem as a licence candidate, so the carve-out file is
named ``GUIDANCE-MIT.md`` — invisible to the candidate glob — leaving ``LICENSE``
as the only detected licence and the badge as "AGPL-3.0".

Acceptance criteria (executable form):

* **AC-1** — ``LICENSE`` is the canonical AGPL-3.0 text **verbatim, with nothing
  prepended** (:func:`test_license_is_verbatim_agpl`, a byte-exact pin against the
  gnu.org text — the earlier scope note is gone, since prepended prose dropped
  licensee's score below its 98% threshold), and it is the **only** root file
  licensee reads as a licence (:func:`test_license_is_the_only_detectable_licence`,
  the measuring test for the "AGPL-3.0" badge). ``GUIDANCE-MIT.md`` carries MIT's
  operative text (:func:`test_guidance_licence_is_mit`).
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
outlived it are kept here rather than dropped: both licence files must be
**git-tracked** (:func:`test_both_licences_are_tracked`), since a public reader
sees only the committed tree and never the author's disk, and the copyright holder
must be recorded (:func:`test_copyright_holder_is_recorded`) — in the MIT file and
package metadata, since a verbatim AGPL ``LICENSE`` cannot name them without
breaking detection.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

from tests._gitutil import tracked_files_under

# ``tests/unit/test_*.py`` → ``parents[2]`` is the repo (or worktree) root.
_REPO_ROOT = Path(__file__).resolve().parents[2]
_LICENSE = _REPO_ROOT / "LICENSE"
_GUIDANCE_MIT = _REPO_ROOT / "GUIDANCE-MIT.md"
_REGISTRY = _REPO_ROOT / "registry.yaml"
_PYPROJECT = _REPO_ROOT / "pyproject.toml"
_README = _REPO_ROOT / "README.md"
_CONTRIBUTING = _REPO_ROOT / "CONTRIBUTING.md"
_BOOTSTRAP = _REPO_ROOT / "BOOTSTRAP.md"

#: First line of the canonical AGPL-3.0 body. ``LICENSE`` is now the licence
#: verbatim, so the file *begins* with this line — nothing is prepended.
_AGPL_BODY_START = "                    GNU AFFERO GENERAL PUBLIC LICENSE"

#: SHA-256 of the canonical AGPL-3.0 text as published at
#: https://www.gnu.org/licenses/agpl-3.0.txt — verified word-for-word against
#: the SPDX license-list copy (5,535 words, identical) when this landed. The
#: licence is frozen (2007), so pinning its bytes is the executable form of
#: "verbatim": any edit to the text fails here.
_AGPL_BODY_SHA256 = "0d96a4ff68ad6d4b6f1f30f713b18d5184912ba8dd389f86aa7710db079abcb0"

#: A root filename ``licensee`` treats as a licence candidate: a ``licen[sc]e``
#: or ``copying``/``copyright`` or ``unlicense``/``ofl`` stem. Any second such
#: file at the root — even a perfect match — collapses GitHub's repo verdict to
#: ``NOASSERTION`` ("Other"), so the carve-out file must not match this.
_LICENSE_CANDIDATE = re.compile(r"(?i)(un)?licen[sc]e|copy(ing|right)|\bofl\b")

#: Engine roots — never MIT. ``scripts/`` is the load-bearing one since #435
#: (the gate and the mutation instrument a third party would fork); ``harness/``
#: was, until ADR 0015 deleted the package. ``tests/`` is named so the scope
#: cannot creep into the guard suite.
_ENGINE_PREFIXES = ("tests/", "scripts/")


def _mit_scope_prefixes(text: str) -> tuple[str, ...]:
    """The path prefixes ``GUIDANCE-MIT.md`` declares as MIT-covered.

    The scope is declared as an indented block of ``<dir>/`` lines under a
    ``Scope`` marker, so it is machine-checkable rather than prose a reader has
    to interpret — these tests hold it against the registry in both directions.
    """
    block = re.search(r"^Scope\b.*?$\n(?P<body>(?:\n|[ \t]+\S.*$\n)+)", text, re.M)
    assert block, "could not find the Scope block in GUIDANCE-MIT.md"
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


def test_license_is_verbatim_agpl() -> None:
    """``LICENSE`` is the canonical AGPL-3.0 text verbatim, nothing prepended (AC-1).

    GitHub's ``licensee`` reads ``LICENSE`` and needs a 98% match to report a
    licence rather than "Other". A verbatim file is a 100% (exact-hash) match; any
    prepended prose — the reason the repo previously read as "Other" — dilutes the
    score. So the requirement is stronger than "the body is unmodified": the file
    must *begin* with the licence, carrying no scope note above it.
    """
    text = _LICENSE.read_text()
    assert text.startswith(_AGPL_BODY_START), (
        "LICENSE must begin with the AGPL-3.0 text — nothing may be prepended, or "
        "licensee scores it below 98% and GitHub reports 'Other'. Put any "
        "repo-specific wording in README.md / CONTRIBUTING.md / GUIDANCE-MIT.md."
    )
    assert hashlib.sha256(text.encode()).hexdigest() == _AGPL_BODY_SHA256, (
        "LICENSE is not the canonical AGPL-3.0 text byte-for-byte — it must be verbatim"
    )


def test_license_is_the_only_detectable_licence() -> None:
    """``LICENSE`` is the sole root file ``licensee`` reads as a licence (AC-1).

    The measuring test for the "AGPL-3.0" badge. ``licensee`` resolves a repo to a
    single SPDX id only when one licence is present or all matched files agree;
    two *different* root licences return ``NOASSERTION`` ("Other") even at 100%
    each (measured: verbatim ``LICENSE`` AGPL + verbatim ``LICENSE-GUIDANCE`` MIT
    still gave ``NOASSERTION``). It treats any root ``licen[sc]e``/``copying`` stem
    as a candidate, so the carve-out must be named to *not* match — hence
    ``GUIDANCE-MIT.md``. This guards against a second candidate creeping back in.
    """
    root_candidates = sorted(
        p.name
        for p in tracked_files_under(".")
        if p.parent == _REPO_ROOT and _LICENSE_CANDIDATE.search(p.name)
    )
    assert root_candidates == ["LICENSE"], (
        f"licensee would treat these root files as licence candidates: {root_candidates}. "
        "Exactly one ('LICENSE') may match, or GitHub returns 'Other' for the whole repo. "
        "Name any additional licence file off the licen[sc]e/copying stem (e.g. GUIDANCE-MIT.md)."
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
    assert _GUIDANCE_MIT.resolve() in tracked_files_under("GUIDANCE-MIT.md"), (
        "No tracked GUIDANCE-MIT.md — the MIT carve-out would be invisible to a reader."
    )


def test_copyright_holder_is_recorded() -> None:
    """The copyright holder is named where it can be (AC-1).

    Inherited from the superseded CAL-1025 guard, but redirected: a verbatim AGPL
    ``LICENSE`` cannot name the holder without foreign words that break detection,
    so the holder is recorded in ``GUIDANCE-MIT.md`` (MIT's grant is meaningless
    without the notice) and in ``pyproject.toml`` (the engine's package metadata).
    """
    assert "Scott Luengen" in _GUIDANCE_MIT.read_text(), (
        "GUIDANCE-MIT.md must name the copyright holder — MIT requires the notice"
    )
    assert re.search(r'name\s*=\s*"Scott Luengen"', _PYPROJECT.read_text()), (
        "pyproject.toml must name the copyright holder for the AGPL engine"
    )


def test_guidance_licence_is_mit() -> None:
    """``GUIDANCE-MIT.md`` carries MIT's operative text (AC-1)."""
    text = _GUIDANCE_MIT.read_text()
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
    prefixes = _mit_scope_prefixes(_GUIDANCE_MIT.read_text())
    escaped = [p for p in _registry_files(_REGISTRY.read_text()) if not _is_mit_scoped(p, prefixes)]
    assert not escaped, (
        f"registry.yaml distributes {escaped} but GUIDANCE-MIT.md does not cover them — "
        f"they would ship AGPL into a third-party repo. Declared scope: {list(prefixes)}"
    )


def test_mit_scope_excludes_the_engine() -> None:
    """The MIT scope never reaches the engine (AC-3).

    The engine is the thing copyleft is *for*. A scope prefix that swallowed
    ``scripts/`` would silently relicense the gate and the mutation instrument
    permissively and void the whole point of the change.
    """
    prefixes = _mit_scope_prefixes(_GUIDANCE_MIT.read_text())
    for engine in _ENGINE_PREFIXES:
        assert not _is_mit_scoped(engine, prefixes), (
            f"GUIDANCE-MIT.md scope covers engine path {engine!r} — the engine must stay AGPL"
        )


def test_the_document_names_the_engine_trees_that_actually_exist() -> None:
    """``GUIDANCE-MIT.md``'s illustration of the AGPL side names live trees (#435).

    The operative boundary is *everything outside the Scope block*, and the two
    tests above hold that against the registry. This pins the sentence that
    **illustrates** it, which nothing did: after ADR 0015 the document still
    named "the CLI in ``harness/``, its tests, and its build and container
    tooling" as the AGPL side, none of which exists. The boundary had not moved,
    but a licence document whose only concrete description of the copyleft side
    names three deleted directories is one a reader cannot act on — and
    :data:`_ENGINE_PREFIXES` had already been updated to ``tests/``/``scripts/``,
    so the guard and the document it guards disagreed with nobody watching.
    """
    text = _GUIDANCE_MIT.read_text()
    boundary = text.split("MIT License", 1)[0]
    for engine in _ENGINE_PREFIXES:
        assert f"`{engine.rstrip('/')}/`" in boundary, (
            f"GUIDANCE-MIT.md does not name {engine!r} when describing what stays "
            f"AGPL, though _ENGINE_PREFIXES says it is exactly that."
        )
    for retired in ("`harness/`", "container tooling", "the CLI in"):
        assert retired not in boundary, (
            f"GUIDANCE-MIT.md still describes the AGPL side as {retired!r}, which "
            f"ADR 0015 deleted. The boundary is unchanged; the description is not."
        )


def test_mit_scope_has_no_dead_prefix() -> None:
    """Every declared prefix actually holds distributed files (AC-3).

    Guards the over-claiming direction: a prefix naming a directory the registry
    does not distribute would hand out an MIT grant over engine code that merely
    happens to live there.
    """
    registry_files = _registry_files(_REGISTRY.read_text())
    for prefix in _mit_scope_prefixes(_GUIDANCE_MIT.read_text()):
        assert any(f.startswith(prefix) for f in registry_files), (
            f"GUIDANCE-MIT.md claims {prefix!r} but registry.yaml distributes nothing under it — "
            "the MIT grant would over-reach"
        )


def test_mit_scope_covers_only_tracked_guidance() -> None:
    """Each declared prefix resolves to real, git-tracked files (AC-3).

    A scope prefix pointing at nothing on disk is a licence grant over a phantom;
    it also means the registry and the tree have drifted.
    """
    for prefix in _mit_scope_prefixes(_GUIDANCE_MIT.read_text()):
        assert tracked_files_under(prefix.rstrip("/")), (
            f"GUIDANCE-MIT.md scope names {prefix!r}, which tracks no files"
        )


def test_boundary_check_catches_an_escaped_path() -> None:
    """The correspondence check is non-vacuous (AC-3).

    Without this, a scope-parse that silently returned everything — or a registry
    parse that returned nothing — would make the guards above pass by accident.
    """
    prefixes = _mit_scope_prefixes(_GUIDANCE_MIT.read_text())
    assert _is_mit_scoped("skills/code-quality/SKILL.md", prefixes), "a distributed file must scope"
    assert not _is_mit_scoped("scripts/mutate.py", prefixes), "an engine file must not scope"
    # The registry parse must find the real distributed set, not an empty one.
    files = _registry_files(_REGISTRY.read_text())
    assert "skills/code-quality/SKILL.md" in files, "registry files: parse missed a known entry"
    assert "BOOTSTRAP.md" not in files, "the meta: block must stay out of the distributed set"


def test_readme_states_the_split() -> None:
    """``README.md`` tells a reader which licence applies to what (AC-4)."""
    text = _README.read_text()
    assert "AGPL-3.0" in text, "README must name the engine licence"
    assert "GUIDANCE-MIT.md" in text, "README must point at the guidance licence"


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


def test_contributing_states_patent_grant() -> None:
    """The inbound grant reaches patents, not just copyright (CAL-1080).

    The CAL-1078 grant covered copyright alone, which leaves a contributor free
    to contribute code reading on their own patent and later assert it against
    the project or its users — a copyright licence does not reach patent claims.
    The wording is Apache ICLA §3 plus Apache-2.0 §3's defensive termination
    rather than bespoke drafting; standard text has survived adversarial use in a
    way freshly-written prose has not.
    """
    text = _CONTRIBUTING.read_text().lower()
    assert "patent" in text, "the inbound grant must include a patent grant"
    for clause in ("make, have made, use", "royalty-free"):
        assert clause in text, f"the patent grant is missing standard wording: {clause!r}"
    assert "litigation" in text, (
        "the patent grant must terminate for an entity that institutes patent litigation "
        "(Apache-2.0 §3 defensive termination) — without it the grant is one-way"
    )


def test_contributing_states_right_to_submit() -> None:
    """A contributor affirms the code is theirs to give (CAL-1080).

    The DCO's entire purpose. Without it someone can contribute code they do not
    own — an employer's, or copied from an incompatible source — and the project
    has no recorded basis for having believed otherwise. Bound to the same
    opening-a-PR assent as the rest of the grant rather than a per-commit
    ``Signed-off-by``: one mechanism, deliberately, for a contributor base of zero.
    """
    text = _CONTRIBUTING.read_text().lower()
    assert "right to submit" in text, "the contributor must affirm a right to submit"
    assert "original" in text, "the representation must cover original creation"
    assert "employer" in text, (
        "the representation must address employer-owned IP — the most common way a "
        "contributor lacks the right to grant"
    )
    assert "third-party" in text or "third party" in text, (
        "the representation must address third-party material and its licence"
    )


def test_bootstrap_installs_the_guidance_licence() -> None:
    """The installer carries the MIT notice into the target repo (AC-5).

    Without this the carve-out is invisible where it matters: the receiving repo
    holds unmarked markdown cloned from an AGPL source, and a compliance scanner
    assumes the worst — which is the adoption blocker the split exists to avoid.
    """
    assert "GUIDANCE-MIT.md" in _BOOTSTRAP.read_text(), (
        "BOOTSTRAP.md must install GUIDANCE-MIT.md alongside the guidance it copies"
    )
