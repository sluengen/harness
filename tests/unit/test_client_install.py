"""The image's ``install`` role emits the client (#312, AC-2).

``~/bin/harness`` is a symlink into a live working tree, so the wrapper text in
effect is whatever that tree currently holds — including for the fix whose whole
purpose is to advance the tree. #286 shipped the self-sync guard and the shipping
run still had to perform the fast-forward by hand. A script served from a working
tree cannot close that bootstrap case.

``docker/install-client.sh`` is the way out: **one producer**, shipped inside the
image, that emits a stamped, self-contained client on stdout. What is measurable
in this repo, exactly, is *the update act's dependency set* — and both halves of
it are executable measurements rather than structural assertions:

* it runs **no git** (proven with a ``git`` on ``PATH`` that logs every call);
* it reads **nothing at the destination** (proven by producing against an absent
  destination and against a hostile pre-existing one, and comparing the bytes).

What is *not* provable here, stated plainly rather than dressed up: that any
particular machine has migrated. ``doctor`` makes that state visible (AC-1); it
does not make it true. The first install is an act on the operator's machine,
performed once by hand from a checkout that already carries this change.

These tests execute the **real** producer. Synthetic templates appear only in the
negative controls, and the one positive control over a synthetic template exists
to show the version is read rather than hardcoded.
"""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
PRODUCER = PROJECT_ROOT / "docker" / "install-client.sh"
TEMPLATE = PROJECT_ROOT / "docker" / "harness-wrapper.sh"

#: ``<package version>+<UTC install instant>``. The instant is what distinguishes
#: two installs of one package version — the bare ``0.2.1`` changes only at
#: release, so a report built on it would be a vacuous equality most days.
_STAMP_RE = re.compile(rb"\d{8}T\d{6}Z")

#: A ``git`` that answers nothing and records everything. Exit 1 as well as the
#: log, so a producer that shells out to it *and* checks the status fails loudly
#: rather than silently taking a fallback branch.
_GIT_STUB = """#!/usr/bin/env bash
echo "git $*" >> "$STUB_GIT_LOG"
exit 1
"""


def _stub_git(tmp_path: Path) -> tuple[dict[str, str], Path]:
    """An environment whose ``git`` logs every call, and the log path."""
    stub_bin = tmp_path / "stubbin"
    stub_bin.mkdir(parents=True, exist_ok=True)
    git = stub_bin / "git"
    git.write_text(_GIT_STUB)
    git.chmod(0o755)

    log = tmp_path / "git-calls.log"
    log.write_text("")

    env = dict(os.environ)
    env["PATH"] = f"{stub_bin}{os.pathsep}{env['PATH']}"
    env["STUB_GIT_LOG"] = str(log)
    return env, log


def _produce(
    tmp_path: Path,
    *args: str,
    producer: Path | None = None,
    stdout_to: Path | None = None,
) -> subprocess.CompletedProcess[bytes]:
    """Run the real producer, returning its raw bytes."""
    env, _ = _stub_git(tmp_path)
    if stdout_to is not None:
        with stdout_to.open("wb") as sink:
            return subprocess.run(
                [str(producer or PRODUCER), *args],
                stdout=sink,
                stderr=subprocess.PIPE,
                env=env,
                check=False,
            )
    return subprocess.run(
        [str(producer or PRODUCER), *args],
        capture_output=True,
        env=env,
        check=False,
    )


def _normalised(emitted: bytes) -> bytes:
    """The emitted client with its install instant blanked.

    Two installs a second apart differ in exactly that field and in nothing else;
    blanking it is what lets *byte-identical* be asserted about everything else.
    """
    return _STAMP_RE.sub(b"<INSTANT>", emitted)


def _fake_image(tmp_path: Path, *, template: bytes, version: str = "9.9.9") -> Path:
    """A directory laid out the way the image lays ``/opt/harness`` out: the
    producer beside its template and the package manifest it stamps from.

    Used only by the negative controls and by the one positive control that shows
    the version is read from the manifest rather than hardcoded.
    """
    root = tmp_path / "fake-image"
    root.mkdir(parents=True, exist_ok=True)
    copy = root / PRODUCER.name
    copy.write_bytes(PRODUCER.read_bytes())
    copy.chmod(0o755)
    (root / TEMPLATE.name).write_bytes(template)
    (root / "pyproject.toml").write_text(
        f'[project]\nname = "harness"\nversion = "{version}"\n'
    )
    return copy


# --- The dependency set (AC-2) ----------------------------------------------


def test_installing_the_client_runs_no_git(tmp_path: Path) -> None:
    """The update act does not depend on git.

    An install implemented as "fast-forward the checkout, then copy the wrapper
    out of it" is the bootstrap case restated, not closed: it needs a working
    tree and a network before it can produce anything. The stub records every
    call, so the assertion is on what the producer *did*, not on what its source
    appears to do.
    """
    env, log = _stub_git(tmp_path)
    result = subprocess.run(
        [str(PRODUCER)], capture_output=True, env=env, check=False
    )

    assert result.returncode == 0, result.stderr.decode()
    assert result.stdout.startswith(b"#!/usr/bin/env bash\n"), result.stdout[:200]
    assert log.read_text() == "", (
        "the install act shelled out to git; it must depend on neither a checkout "
        f"nor a network:\n{log.read_text()}"
    )


def test_the_installed_client_does_not_depend_on_what_it_replaces(
    tmp_path: Path,
) -> None:
    """The bootstrap case, measured: producing over a hostile pre-existing client
    yields the same bytes as producing where none exists.

    A producer that diffed, patched or version-checked the client it replaces
    would need the *previous* client to have been correct — which is exactly the
    dependency #286 could not break.
    """
    absent = _produce(tmp_path)
    assert absent.returncode == 0, absent.stderr.decode()

    hostile = tmp_path / "bin" / "harness"
    hostile.parent.mkdir(parents=True, exist_ok=True)
    hostile.write_bytes(b"#!/bin/sh\nexit 77  # a prior client, wrong in every way\n")
    result = _produce(tmp_path, stdout_to=hostile)
    assert result.returncode == 0, result.stderr.decode()

    assert _normalised(hostile.read_bytes()) == _normalised(absent.stdout), (
        "the emitted client differs depending on what was already at the "
        "destination — the update act must read nothing it replaces"
    )


# --- One versioned source (AC-2, AC-4) --------------------------------------


def test_the_emitted_body_is_the_versioned_shim_verbatim(tmp_path: Path) -> None:
    """There stays exactly **one** versioned shim.

    The emitted client is a preamble followed by the byte-identical bytes of
    ``docker/harness-wrapper.sh``. Two shim sources would be two postures, which
    is the drift CAL-1123 named and this repo has paid for repeatedly — so the
    assertion is byte equality on the suffix, not a resemblance check.
    """
    result = _produce(tmp_path)
    assert result.returncode == 0, result.stderr.decode()

    body = TEMPLATE.read_bytes()
    assert result.stdout.endswith(body), (
        "the emitted client's body is not the versioned shim verbatim — a "
        "re-spelled or truncated copy is a second shim source"
    )
    preamble = result.stdout[: -len(body)]
    assert _STAMP_RE.search(preamble), (
        f"the preamble carries no install instant:\n{preamble.decode()}"
    )


def test_the_emitted_client_parses(tmp_path: Path) -> None:
    """``bash -n`` on the artifact. A preamble whose quoting is wrong produces a
    client that fails at its first invocation, on the operator's machine, with a
    syntax error naming a line they did not write."""
    result = _produce(tmp_path)
    assert result.returncode == 0, result.stderr.decode()

    client = tmp_path / "client"
    client.write_bytes(result.stdout)
    parsed = subprocess.run(
        ["bash", "-n", str(client)], capture_output=True, text=True, check=False
    )
    assert parsed.returncode == 0, f"the emitted client is not parseable:\n{parsed.stderr}"


def test_the_emitted_client_bakes_the_source_root_and_the_version(
    tmp_path: Path,
) -> None:
    """Both baked values reach the artifact, as **shell** variables rather than
    exported environment ones.

    A non-exported assignment inside the emitted script cannot be set by the
    process that invokes the client, which is the whole difference between *the
    root this client was built for* and *whatever the calling shell last
    exported*. The client re-exports the value it actually resolved; it never
    trusts an inherited one (see ``docker/harness-wrapper.sh``).
    """
    root = tmp_path / "a checkout"
    result = _produce(tmp_path, "--source-root", str(root))
    assert result.returncode == 0, result.stderr.decode()

    preamble = result.stdout[: -len(TEMPLATE.read_bytes())].decode()
    assert f"_harness_baked_source_root='{root}'" in preamble, preamble
    assert re.search(r"_harness_baked_client_version='[^']+\+\d{8}T\d{6}Z'", preamble), (
        f"no stamped version was baked in:\n{preamble}"
    )
    assert "export " not in preamble, (
        "the preamble exports nothing: an exported variable is settable by the "
        f"process that invokes the client, and a baked value must not be:\n{preamble}"
    )


def test_an_omitted_source_root_bakes_nothing(tmp_path: Path) -> None:
    """Without the flag the client resolves its source root the way a symlink
    install does. Baking an empty value instead would be worse than baking none:
    the shim's branch would fire on a value that names no checkout.

    Scoped to the **preamble**, deliberately. The shim body names the variable in
    its own branch and its own comment, so a whole-artifact substring search is
    satisfied by the body and could never fail.
    """
    result = _produce(tmp_path)
    assert result.returncode == 0, result.stderr.decode()
    preamble = result.stdout[: -len(TEMPLATE.read_bytes())]
    assert b"_harness_baked_source_root" not in preamble, preamble.decode()


# --- The trust boundary: the value is interpolated into a shell script -------


@pytest.mark.parametrize(
    "bad_root",
    ["/tmp/it's-mine", "/tmp/two\nlines"],
    ids=["single-quote", "newline"],
)
def test_a_source_root_that_could_escape_its_quoting_is_refused(
    tmp_path: Path, bad_root: str
) -> None:
    """The one injection surface this change opens, closed by refusal.

    The value is single-quoted into an emitted shell script. Single-quoting plus
    this refusal is the complete defence — attempting to *escape* the value
    instead would be a second, weaker mechanism for the same property.
    """
    result = _produce(tmp_path, "--source-root", bad_root)
    assert result.returncode == 2, result.stderr.decode()
    assert result.stdout == b"", (
        "a refusal must emit nothing on stdout — a half-written client on PATH "
        f"is worse than no install at all:\n{result.stdout!r}"
    )


def test_a_relative_source_root_is_refused(tmp_path: Path) -> None:
    """A relative root baked into a client that runs from any directory silently
    mis-targets both the freshness guard and ``PYTHONPATH`` — the two guards that
    keep the unattended loop off stale code. It must fail at install time, where
    a human is watching, not at run time where nothing reports it."""
    result = _produce(tmp_path, "--source-root", "relative/checkout")
    assert result.returncode == 2, result.stderr.decode()
    assert result.stdout == b""


def test_the_refusal_predicate_discriminates(tmp_path: Path) -> None:
    """The negative control: a legitimate absolute path containing spaces is
    **accepted**.

    Without this, a blanket refusal that rejected every root would satisfy all
    three refusal tests above while making the flag unusable — the refusals would
    read as coverage of a predicate that does not exist.
    """
    root = tmp_path / "Library" / "Application Support" / "harness checkout"
    result = _produce(tmp_path, "--source-root", str(root))
    assert result.returncode == 0, result.stderr.decode()
    assert f"_harness_baked_source_root='{root}'".encode() in result.stdout


# --- A truncated image must fail loudly -------------------------------------


def test_a_missing_template_is_refused(tmp_path: Path) -> None:
    """A producer whose template is absent must not emit half a client."""
    orphan = tmp_path / "orphan"
    orphan.mkdir()
    copy = orphan / PRODUCER.name
    copy.write_bytes(PRODUCER.read_bytes())
    copy.chmod(0o755)

    result = _produce(tmp_path, producer=copy)
    assert result.returncode == 2, result.stderr.decode()
    assert result.stdout == b""


def test_a_template_that_is_not_a_script_is_refused(tmp_path: Path) -> None:
    """A template present but truncated — no ``#!`` — is a broken image, and a
    client emitted from it would fail at its first invocation on the operator's
    machine rather than at install time."""
    copy = _fake_image(tmp_path, template=b"pkg-tarball-fragment\n")
    result = _produce(tmp_path, producer=copy)
    assert result.returncode == 2, result.stderr.decode()
    assert result.stdout == b""


def test_the_stamped_version_is_read_from_the_package_not_hardcoded(
    tmp_path: Path,
) -> None:
    """The positive control over a synthetic image: a manifest declaring 9.9.9
    stamps 9.9.9.

    Without it, the refusal tests above are the only cases the synthetic layout
    covers, and a producer that emitted a literal version would satisfy every
    other assertion in this module.
    """
    copy = _fake_image(tmp_path, template=b"#!/usr/bin/env bash\ntrue\n")
    result = _produce(tmp_path, producer=copy)
    assert result.returncode == 0, result.stderr.decode()
    assert re.search(rb"_harness_baked_client_version='9\.9\.9\+\d{8}T\d{6}Z'", result.stdout), (
        result.stdout[:400]
    )
