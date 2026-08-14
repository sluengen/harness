"""How the installed client is deployed, and what ``doctor`` says about it (#312).

Two things live here, because they are two halves of one report:

* :mod:`harness.hostenv.deployment` — the classification that used to be
  ``_wrapper_status()`` in ``docker/harness-wrapper.sh``. **AC-4 is satisfied as
  "preserved"**: same environment variable, same four verdicts, same ``doctor``
  mapping, plus a fifth (``image``) for the deployment this ticket adds. What
  changed is where it lives, for two reasons worth recording — the shim is at a
  line-count ratchet with no headroom, and bash is the one place in this repo a
  branch cannot be unit-tested.
* ``check_wrapper``'s mapping of a verdict onto PASS / WARN / FAIL, extended with
  the version now in effect.

**AC-1 is "the version in effect is reportable without inspecting a symlink
target".** The value comes from a forwarded stamp, never from the shape of a
link — which is what the third test below measures, by giving the *same* stamped
client both shapes and requiring the same answer.

Not in ``tests/unit/test_cli_doctor.py``: that module is at 749 of the 750-line
``tests/`` ceiling.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from harness.cli.doctor import check_wrapper
from harness.hostenv import deployment

_STAMP = "0.2.1+20260815T171500Z"


def _versioned_checkout(tmp_path: Path, *, body: str = "#!/usr/bin/env bash\ntrue\n") -> Path:
    """A directory shaped like a checkout: it carries the versioned shim at the
    path the classification compares against."""
    root = tmp_path / "checkout"
    (root / "docker").mkdir(parents=True, exist_ok=True)
    (root / "docker" / "harness-wrapper.sh").write_text(body)
    return root


# --- The four preserved verdicts (AC-4) -------------------------------------


def test_no_client_path_is_no_verdict(tmp_path: Path) -> None:
    """Nothing mediated the invocation, so there is nothing to classify.

    This is the native install and the pre-#312 shim alike; ``check_wrapper``'s
    own container-presence fallback tells those two apart, unchanged.
    """
    result = deployment.classify(client_path="", source_root=str(tmp_path), client_version="")
    assert result.status == ""
    assert result.version == ""


def test_a_client_outside_any_checkout_is_detached(tmp_path: Path) -> None:
    """No versioned shim under the resolved source root: nothing to track."""
    client = tmp_path / "bin" / "harness"
    client.parent.mkdir(parents=True)
    client.write_text("#!/usr/bin/env bash\n")
    result = deployment.classify(
        client_path=str(client), source_root=str(tmp_path), client_version=""
    )
    assert result.status == "detached"


def test_a_symlink_into_the_checkout_is_a_symlink(tmp_path: Path) -> None:
    root = _versioned_checkout(tmp_path)
    client = tmp_path / "bin" / "harness"
    client.parent.mkdir(parents=True)
    client.symlink_to(root / "docker" / "harness-wrapper.sh")
    result = deployment.classify(
        client_path=str(client), source_root=str(root), client_version=""
    )
    assert result.status == "symlink"


def test_a_byte_identical_copy_is_a_copy(tmp_path: Path) -> None:
    root = _versioned_checkout(tmp_path)
    client = tmp_path / "bin" / "harness"
    client.parent.mkdir(parents=True)
    client.write_bytes((root / "docker" / "harness-wrapper.sh").read_bytes())
    result = deployment.classify(
        client_path=str(client), source_root=str(root), client_version=""
    )
    assert result.status == "copy"


def test_a_copy_that_has_fallen_behind_is_drifted(tmp_path: Path) -> None:
    root = _versioned_checkout(tmp_path)
    client = tmp_path / "bin" / "harness"
    client.parent.mkdir(parents=True)
    client.write_text("#!/usr/bin/env bash\n# an older release\n")
    result = deployment.classify(
        client_path=str(client), source_root=str(root), client_version=""
    )
    assert result.status == "drifted"


def test_a_drift_of_the_same_size_and_age_is_still_drift(tmp_path: Path) -> None:
    """The bash this replaced used ``cmp -s``, which compares content. So must this.

    A stat-signature comparison (``shallow=True``) calls two files identical when
    their mode, size and mtime agree — and a copy edited in place can keep its
    size while a freshly-cloned sibling can carry the same mtime. ``doctor`` would
    then report ``copy`` for a client that has genuinely diverged, which is the
    exact silence CAL-1149 exists to break.

    This case exists because the mutation ``shallow=False`` → ``shallow=True``
    **survived** every other test in this module: they all happen to differ in
    length, so the cheap comparison reaches the right answer for the wrong reason.
    """
    root = _versioned_checkout(tmp_path, body="#!/usr/bin/env bash\nAAA\n")
    versioned = root / "docker" / "harness-wrapper.sh"
    client = tmp_path / "harness"
    client.write_text("#!/usr/bin/env bash\nBBB\n")
    one_instant = (1_784_268_000, 1_784_268_000)
    os.utime(client, one_instant)
    os.utime(versioned, one_instant)
    assert client.stat().st_size == versioned.stat().st_size, (
        "the fixture must make size and mtime agree, or it is not exercising the "
        "comparison at all"
    )

    result = deployment.classify(
        client_path=str(client), source_root=str(root), client_version=""
    )
    assert result.status == "drifted", (
        "a same-size, same-mtime divergence was read as an identical copy — the "
        "comparison is looking at the stat signature, not the bytes"
    )


# --- The fifth verdict, and why it is checked first (AC-1) -------------------


def test_classify_reports_image_without_reading_the_link_shape(tmp_path: Path) -> None:
    """AC-1's load-bearing property: the verdict comes from the forwarded stamp,
    not from the shape of the thing on PATH.

    The *same* stamped client is given both shapes — a real symlink and a real
    file — and must classify identically. A classifier consulting ``is_symlink``
    before the stamp makes the two disagree, and the report then depends on a
    link target after all.
    """
    root = _versioned_checkout(tmp_path)
    plain = tmp_path / "plain-harness"
    plain.write_text("#!/usr/bin/env bash\n")
    linked = tmp_path / "linked-harness"
    linked.symlink_to(root / "docker" / "harness-wrapper.sh")

    verdicts = {
        deployment.classify(
            client_path=str(path), source_root=str(root), client_version=_STAMP
        ).status
        for path in (plain, linked)
    }
    assert verdicts == {"image"}, (
        f"a stamped client classified differently by link shape: {verdicts}"
    )


@pytest.mark.parametrize("shape", ["symlink", "copy", "drifted", "detached"])
def test_the_image_verdict_precedes_every_other_branch(
    tmp_path: Path, shape: str
) -> None:
    """The ordering is the whole of R-3, and it is not cosmetic.

    A stamped client is given, in turn, each of the four shapes an *unstamped*
    client can have, and must classify ``image`` in all four. Every one is
    reachable in practice — an install placed inside a checkout is a plain file
    differing from the versioned shim (it carries the preamble), and an install
    at ``~/bin/harness`` is outside any checkout entirely.

    Parametrising over all four is deliberate, and it was measured: an earlier
    version of this test used only the *drifted* shape, and a mutation demoting
    the stamp check to just above the ``drifted`` return **passed it**. One shape
    pins one placement; four pin the precedence.
    """
    root = _versioned_checkout(tmp_path)
    versioned = root / "docker" / "harness-wrapper.sh"
    client = tmp_path / "bin" / "harness"
    client.parent.mkdir(parents=True)

    source_root = str(root)
    if shape == "symlink":
        client.symlink_to(versioned)
    elif shape == "copy":
        client.write_bytes(versioned.read_bytes())
    elif shape == "drifted":
        client.write_text(
            f"#!/usr/bin/env bash\n_harness_baked_client_version='{_STAMP}'\n"
            + versioned.read_text()
        )
    else:
        client.write_text("#!/usr/bin/env bash\n")
        source_root = str(tmp_path / "not-a-checkout")

    result = deployment.classify(
        client_path=str(client), source_root=source_root, client_version=_STAMP
    )
    assert result.status == "image", (
        f"a stamped client with the {shape!r} shape was classified {result.status!r}"
        " — a correct install then reports as something doctor complains about"
    )
    assert result.version == _STAMP


def test_an_unstamped_deployment_carries_no_version(tmp_path: Path) -> None:
    """A symlink install has no pinned version, and the honest report of that is
    an empty string rather than a plausible-looking one."""
    root = _versioned_checkout(tmp_path)
    client = tmp_path / "harness"
    client.symlink_to(root / "docker" / "harness-wrapper.sh")
    assert (
        deployment.classify(
            client_path=str(client), source_root=str(root), client_version=""
        ).version
        == ""
    )


# --- doctor's report (AC-1, AC-3) -------------------------------------------


def test_an_image_installed_client_reports_its_stamped_version() -> None:
    """AC-1: the version actually in effect is readable off ``doctor``'s line."""
    status, message = check_wrapper(
        env={"HARNESS_WRAPPER_STATUS": "image", "HARNESS_CLIENT_VERSION": _STAMP},
        in_container=True,
    )
    assert status == "PASS", message
    assert _STAMP in message, message


def test_the_reported_version_is_the_forwarded_one_not_a_constant() -> None:
    """Two installs of one package version must be distinguishable.

    A report built on ``harness.__version__`` would be identical for both — a
    vacuous equality that reads like a version report, which is precisely the
    failure ``HARNESS_CLIENT_VERSION`` exists to avoid.
    """
    older = check_wrapper(
        env={"HARNESS_WRAPPER_STATUS": "image", "HARNESS_CLIENT_VERSION": "0.2.1+20260101T000000Z"},
        in_container=True,
    )[1]
    newer = check_wrapper(
        env={"HARNESS_WRAPPER_STATUS": "image", "HARNESS_CLIENT_VERSION": "0.2.1+20260815T171500Z"},
        in_container=True,
    )[1]
    assert older != newer, f"both installs reported the same version: {older!r}"


def test_a_symlink_deployment_still_passes_and_says_its_version_is_unpinned() -> None:
    """AC-3: the existing deployment keeps working, and its report is honest.

    A symlink's version follows the checkout, so there is no version to pin —
    saying so is the accurate report of the defect this ticket names, and it is
    reached without reading the link target.
    """
    status, message = check_wrapper(
        env={"HARNESS_WRAPPER_STATUS": "symlink"}, in_container=True
    )
    assert status == "PASS", message
    assert "unpinned" in message, message


@pytest.mark.parametrize("verdict", deployment.DEPLOYMENT_STATUSES)
def test_every_classifier_verdict_has_a_doctor_verdict(verdict: str) -> None:
    """Every verdict the classifier can produce is mapped by ``check_wrapper``.

    Without this, a sixth verdict added to the classifier would fall through to
    the "no verdict forwarded" branch and be reported as *a wrapper predating the
    drift check* — a confident, wrong diagnosis. The parametrisation derives from
    the classifier's own tuple; the floor below is what stops a derivation that
    died from passing as coverage.
    """
    status, message = check_wrapper(
        env={"HARNESS_WRAPPER_STATUS": verdict}, in_container=True
    )
    assert status in {"PASS", "WARN", "FAIL"}
    assert "predates the drift check" not in message, (
        f"{verdict!r} is unmapped and falls through to the stale-wrapper "
        f"diagnosis: {message}"
    )


def test_the_verdict_set_is_populated_and_names_the_image_install() -> None:
    """The floor under the parametrisation above: a dead derivation collects
    nothing and passes silently."""
    assert len(deployment.DEPLOYMENT_STATUSES) >= 5
    assert "image" in deployment.DEPLOYMENT_STATUSES
    assert "detached" in deployment.DEPLOYMENT_STATUSES
