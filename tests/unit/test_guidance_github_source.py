"""CAL-653 — guidance is pulled from GitHub at a branch ref (dev dogfood → main release).

Breakdown item 8 of ``specs/proposals/merge-guidance-into-harness.md`` and the D7
sub-decision in ``specs/architecture-principles.md``. With the harness as the
guidance SOURCE (CAL-646), consumers must pull guidance from the harness GitHub
repo — not a local path — and releases ride the existing ``dev → main`` model:
the harness authors and dogfoods on ``dev``; external repos pull ``main``.

These guards are the as-built evidence that the GitHub-remote source mechanism is
documented, and stays documented:

* **AC-1** — ``/update-guidance`` pulls from a GitHub remote ref defined in the
  consumer lock's ``source: { repo, branch, ref }``.
* **AC-2** — ``bootstrap`` (``BOOTSTRAP.md``) installs from GitHub ``main``, and
  ``registry.yaml``'s ``source.repo`` is a concrete repo (not an ``<owner>``
  placeholder).
* **AC-3** — the dev-dogfood vs. main-release path and the release-coupling
  decision are recorded in ``specs/architecture-principles.md`` (the D7
  consequences no longer *defer* the coupling call to this ticket).
"""

from __future__ import annotations

import re

from tests.unit._prose import REPO_ROOT

REGISTRY = REPO_ROOT / "registry.yaml"
UPDATE_GUIDANCE = REPO_ROOT / "commands" / "update-guidance.md"
BOOTSTRAP = REPO_ROOT / "BOOTSTRAP.md"
PRINCIPLES = REPO_ROOT / "specs" / "architecture-principles.md"

SOURCE_REPO = "sluengen/harness"


# --- AC-2: registry names a concrete GitHub source repo -----------------------


def test_registry_source_repo_is_concrete() -> None:
    """``registry.yaml`` ``source:`` carries an uncommented, concrete ``repo``.

    The installer clones the guidance source from this repo, so it cannot stay a
    ``# repo: git@github.com:<owner>/harness.git`` placeholder — a fork/owner must
    be baked in (decided 2026-06-14: ``sluengen/harness``).
    """
    text = REGISTRY.read_text()
    # An active (non-comment) `repo:` line inside the source block.
    m = re.search(r"^\s*repo:\s*(\S+)", text, re.MULTILINE)
    assert m, "registry.yaml source: has no active `repo:` line (still a placeholder?)"
    repo = m.group(1)
    assert "<owner>" not in repo and SOURCE_REPO in repo, (
        f"registry.yaml source.repo must name the concrete guidance repo "
        f"({SOURCE_REPO}); got {repo!r}"
    )


def test_registry_source_branch_is_main() -> None:
    """``registry.yaml`` ``source:`` records ``branch: main`` — the released ref
    external repos pull (the harness dogfoods on ``dev``; D7)."""
    m = re.search(r"^\s*branch:\s*(\S+)", REGISTRY.read_text(), re.MULTILINE)
    assert m and m.group(1) == "main", (
        "registry.yaml source.branch must be `main` (external repos pull main; "
        f"the harness dogfoods on dev — D7); got {m.group(1) if m else None!r}"
    )


def test_registry_header_matches_meta_self_version() -> None:
    """The registry's own ``guidance:registry@`` header equals its ``meta:`` entry.

    The freshness hook keys meta-file drift on this; the two had drifted (header
    @0.4.1 vs meta 0.4.2). A registry edit must leave them reconciled.
    """
    text = REGISTRY.read_text()
    header = re.search(r"guidance:registry@([\d.]+)", text)
    meta = re.search(r"^\s*registry\.yaml:\s*\{[^}]*version:\s*([\d.]+)", text, re.MULTILINE)
    assert header and meta, "could not read registry header and/or meta self-version"
    assert header.group(1) == meta.group(1), (
        f"registry header ({header.group(1)}) must equal its meta self-version "
        f"({meta.group(1)})"
    )


# --- AC-1: /update-guidance pulls from a GitHub remote ref --------------------


def test_update_guidance_pulls_from_github_remote() -> None:
    """``commands/update-guidance.md`` step 1 fetches from a GitHub remote ref.

    The source must be the harness GitHub repo at a branch ref recorded in the
    consumer lock's ``source: { repo, branch, ref }`` — not an unspecified local
    path/remote.
    """
    text = UPDATE_GUIDANCE.read_text()
    assert re.search(r"git[Hh]ub", text), (
        "update-guidance.md must name GitHub as the concrete guidance source (AC-1)"
    )
    assert re.search(r"repo.*branch.*ref", text), (
        "update-guidance.md must reference the `source: { repo, branch, ref }` "
        "lock schema (AC-1)"
    )


# --- AC-1 / AC-2: the installer lock schema and GitHub-main install -----------


def test_installer_lock_schema_has_repo_branch_ref() -> None:
    """``BOOTSTRAP.md`` lock schema is ``source: { repo, branch, ref }`` (AC-1).

    The schema the installer writes is the consumer-side lock ``/update-guidance``
    later reads; it must carry the GitHub remote (``repo``/``branch``), not just a
    ``name``/``ref``.
    """
    text = BOOTSTRAP.read_text()
    m = re.search(r"source:\s*\{([^}]*)\}", text)
    assert m, "BOOTSTRAP.md has no `source: { ... }` lock schema example"
    body = m.group(1)
    for key in ("repo", "branch", "ref"):
        assert key in body, (
            f"BOOTSTRAP.md lock schema `source: {{ ... }}` must include `{key}` "
            f"(AC-1); got: {body.strip()!r}"
        )


def test_installer_installs_from_github_main() -> None:
    """``BOOTSTRAP.md`` installs the guidance from GitHub ``main`` (AC-2).

    External repos pull the released ``main`` ref, not in-flight ``dev``.
    """
    text = BOOTSTRAP.read_text()
    assert re.search(r"git[Hh]ub", text), (
        "BOOTSTRAP.md must name GitHub as the install source (AC-2)"
    )
    assert "main" in text, (
        "BOOTSTRAP.md must name `main` as the branch external repos install from "
        "(AC-2)"
    )


# --- AC-3: the coupling decision is recorded, no longer deferred ---------------


def test_d7_coupling_decision_recorded() -> None:
    """``architecture-principles.md`` records the coupling resolution (AC-3).

    The D7 consequences block deferred the release-coupling call to this ticket
    ("deferred to the D7 work, CAL-653"). With the decision closed (pull ``main``;
    no independent promotion path now), that deferral must be gone and the
    resolution recorded.
    """
    text = PRINCIPLES.read_text()
    assert "deferred to the D7 work, CAL-653" not in text, (
        "the D7 consequences must no longer DEFER the coupling call to CAL-653 — "
        "the decision is closed (AC-3)"
    )
    # The dev-dogfood vs. main-release path is documented.
    assert re.search(r"dogfood", text) and re.search(r"pull\s+`?main`?", text), (
        "architecture-principles.md must document the dev-dogfood vs. main-release "
        "path (external repos pull main) (AC-3)"
    )
