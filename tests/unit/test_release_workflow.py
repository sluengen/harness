"""GHCR publish slice guard — Dockerfile source LABEL + tag-gated release CI (CAL-623).

The cross-repo-readiness decision (CAL-623, recorded 2026-06-14) lands the
**code-only** slice of publishing the runtime image to GitHub Container Registry:

1. ``docker/Dockerfile`` carries
   ``LABEL org.opencontainers.image.source=https://github.com/sluengen/harness``
   so GHCR auto-links the published package to the repo (the link that lets a
   human enable "Inherit access from repository" after the first push).
2. A release workflow (``.github/workflows/release.yml``) builds and pushes
   ``ghcr.io/sluengen/harness:<tag>`` **gated behind a version-tag push** — inert
   until a human cuts the first tagged release (``RELEASING.md`` → Tagging). It
   authenticates with the built-in ``GITHUB_TOKEN`` (``packages: write``), never
   a PAT, so the package stays owned by / linked to the repo.

The manual, environment-bound steps — the one-time GitHub-UI "Inherit access"
toggle, the first ``docker login`` + ``docker pull`` access check, and flipping
the ``~/bin/harness`` wrapper default ``HARNESS_IMAGE`` — are **deferred to a
human runbook after the first verified publish** and are out of scope here. This
guard pins only what lands in-repo now.

The workflow is parsed as text (PyYAML is not a project dependency); the
assertions are substring-level so they survive action-version bumps but still
catch a regression that would silently un-gate the publish or drop the auth /
permission contract.

*Source:* CAL-623 (cross-repo readiness — GHCR publish), decision recorded
2026-06-14; same source-repo / access boundary as CAL-653.
"""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent.parent
DOCKERFILE = REPO_ROOT / "docker" / "Dockerfile"
RELEASE_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "release.yml"

#: The authoritative registry / source repo for both the image and the guidance
#: pull source (CAL-623 + CAL-653). A fork-or-org change must update both.
SOURCE_LABEL = "org.opencontainers.image.source=https://github.com/sluengen/harness"
IMAGE_REF = "ghcr.io/sluengen/harness"


def test_dockerfile_declares_ghcr_source_label() -> None:
    """The Dockerfile links the image to the repo so GHCR can inherit its access."""
    dockerfile = DOCKERFILE.read_text()
    assert f"LABEL {SOURCE_LABEL}" in dockerfile, (
        "docker/Dockerfile must LABEL org.opencontainers.image.source so GHCR "
        "links the package to sluengen/harness"
    )


def test_release_workflow_exists() -> None:
    assert (
        RELEASE_WORKFLOW.is_file()
    ), "the GHCR publish workflow .github/workflows/release.yml must exist (CAL-623)"


def test_release_workflow_is_tag_gated_and_inert_on_branches() -> None:
    """The publish triggers only on a version-tag push — inert until a release is cut."""
    wf = RELEASE_WORKFLOW.read_text()
    assert "tags:" in wf, "release workflow must trigger on a tag push"
    assert "v*" in wf, "release workflow must gate on a version-tag pattern (v*)"
    # No branch / PR trigger: pushing to dev or main must not publish an image.
    assert (
        "branches:" not in wf
    ), "release workflow must not trigger on branch pushes (inert until a tag is cut)"
    assert (
        "pull_request" not in wf
    ), "release workflow must not trigger on pull requests"


def test_release_workflow_pushes_to_ghcr_with_github_token() -> None:
    """Publish targets ghcr.io/sluengen/harness and authenticates with GITHUB_TOKEN."""
    wf = RELEASE_WORKFLOW.read_text()
    assert IMAGE_REF in wf, f"release workflow must push to {IMAGE_REF}"
    assert (
        "packages: write" in wf
    ), "release workflow must grant packages: write so GITHUB_TOKEN can push to GHCR"
    assert (
        "secrets.GITHUB_TOKEN" in wf
    ), "release workflow must authenticate with the built-in GITHUB_TOKEN, not a PAT"


def test_release_workflow_builds_the_repo_dockerfile() -> None:
    """The published image is the repo's runtime image, not an ad-hoc build."""
    wf = RELEASE_WORKFLOW.read_text()
    assert (
        "docker/Dockerfile" in wf
    ), "release workflow must build from docker/Dockerfile"


def test_release_workflow_guards_tag_against_packaged_version() -> None:
    """The registry tag must agree with the static pyproject / __version__.

    The tag is derived from the git ref while the image bakes in
    ``harness.__version__``; without a guard a ``v0.2.0`` tag could publish an
    image that reports ``harness 0.1.0``. The workflow must fail fast on drift
    before any push.
    """
    wf = RELEASE_WORKFLOW.read_text()
    assert "GITHUB_REF_NAME" in wf, "version guard must read the pushed tag"
    assert (
        "pyproject.toml" in wf and "__version__" in wf
    ), "version guard must compare the tag against both pyproject and harness.__version__"
    assert "exit 1" in wf, "version guard must fail the job on a tag/version mismatch"


def test_release_workflow_runs_the_verification_gate_before_publishing() -> None:
    """A failing commit must not become an immutable release image.

    The publish job depends on a verification job that runs ``scripts/verify.sh``
    on the tagged commit before any build/push.
    """
    wf = RELEASE_WORKFLOW.read_text()
    assert (
        "scripts/verify.sh" in wf
    ), "release workflow must run the verification gate on the tagged commit"
    assert (
        "needs: verify" in wf
    ), "the publish job must depend on the verification gate passing"


def test_release_workflow_enforces_the_main_release_boundary() -> None:
    """A `v*` tag on an unmerged commit must not publish (dev → main boundary, D7)."""
    wf = RELEASE_WORKFLOW.read_text()
    assert (
        "origin/main" in wf and "is-ancestor" in wf
    ), "release workflow must refuse to publish a tag not contained in origin/main"
