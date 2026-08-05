"""The host-platform seam: provider detection, credential stores, git identity,
and bounded subprocess execution (#305).

``docker/harness-wrapper.sh`` carried all of this as macOS-shaped bash, which the
native ``uv tool install`` entry point cannot reach and which cannot express
Windows-via-WSL at all (ADR 0012). These tests cover the ported Python.

Every environmental input is **injected** — ``sys.platform``, the os-release path,
the environment mapping, the credential-file path — so each branch is exercised on
any machine. That is the point of the seam: a macOS dev box must be able to prove
the WSL provider, and it cannot do that by detection alone.
"""

from __future__ import annotations

import json
import os
import stat
import subprocess
import time
from pathlib import Path

import pytest

from harness.hostenv.credentials import AgentCredential
from harness.hostenv.host import (
    GitIdentity,
    LinuxHost,
    MacOSHost,
    UnsupportedHost,
    detect_host,
)


def _path_env(*prepend: Path) -> dict[str, str]:
    """PATH with stub directories in front of the real one.

    Prepending rather than replacing is load-bearing: the stubs are ``#!/usr/bin/env
    bash`` scripts, so ``bash`` must still resolve. With a PATH holding only the stub
    directory the stub never executes at all, and a test asserting "no credential"
    then passes on the failed exec instead of on the behaviour it means to cover.
    """
    parts = [str(p) for p in prepend] + [os.environ["PATH"]]
    return {"PATH": os.pathsep.join(parts)}


def _stub(directory: Path, name: str, body: str) -> Path:
    """Write an executable stub onto a throwaway PATH directory."""
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    path.write_text(body)
    path.chmod(path.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    return path


def _write_store(path: Path, token: str = "tok", expires_at: int = 1234) -> Path:
    path.write_text(json.dumps({"claudeAiOauth": {"accessToken": token, "expiresAt": expires_at}}))
    return path


# ---------------------------------------------------------------------------
# The Linux/WSL provider — AC-1's explicit "tested against a fixture credential
# store". This is the first failing test: harness.hostenv does not exist yet.
# ---------------------------------------------------------------------------


def test_linux_provider_reads_a_fixture_credential_store(tmp_path: Path) -> None:
    """The file-store provider parses a fixture store into a credential.

    A macOS dev box has no WSL Claude install, so a *fixture* store is the only
    honest way to prove this provider. The path is injected rather than searched.
    """
    store = _write_store(tmp_path / ".credentials.json", token="wsl-token", expires_at=99)
    host = LinuxHost(name="wsl", env={"HARNESS_CLAUDE_CREDENTIALS_FILE": str(store)})

    assert host.agent_credential() == AgentCredential(token="wsl-token", expires_at_ms=99)


def test_linux_provider_names_the_path_it_searched_when_absent(tmp_path: Path) -> None:
    """An absent store yields no credential and a diagnostic naming the path.

    Naming the path is the whole remediation for the one thing this ticket could
    not verify — where Claude Code stores credentials under WSL. An operator who
    can see which path was tried can point ``HARNESS_CLAUDE_CREDENTIALS_FILE`` at
    the right one; a bare "no credential" leaves them guessing.
    """
    missing = tmp_path / "nope" / ".credentials.json"
    host = LinuxHost(name="wsl", env={"HARNESS_CLAUDE_CREDENTIALS_FILE": str(missing)})

    assert host.agent_credential() is None
    assert str(missing) in "\n".join(host.diagnostics)


def test_linux_provider_credential_path_precedence(tmp_path: Path) -> None:
    """Override beats CLAUDE_CONFIG_DIR beats ``~/.claude``."""
    override = _write_store(tmp_path / "override.json", token="from-override")
    config_dir = tmp_path / "cfg"
    config_dir.mkdir()
    _write_store(config_dir / ".credentials.json", token="from-config-dir")
    home = tmp_path / "home"
    (home / ".claude").mkdir(parents=True)
    _write_store(home / ".claude" / ".credentials.json", token="from-home")

    base = {"CLAUDE_CONFIG_DIR": str(config_dir), "HOME": str(home)}

    with_override = LinuxHost(
        name="wsl", env={**base, "HARNESS_CLAUDE_CREDENTIALS_FILE": str(override)}
    )
    assert with_override.agent_credential() is not None
    assert with_override.agent_credential().token == "from-override"  # type: ignore[union-attr]

    with_config = LinuxHost(name="wsl", env=base)
    assert with_config.agent_credential().token == "from-config-dir"  # type: ignore[union-attr]

    home_only = LinuxHost(name="linux", env={"HOME": str(home)})
    assert home_only.agent_credential().token == "from-home"  # type: ignore[union-attr]


@pytest.mark.parametrize(
    "body",
    [
        "not json at all",
        json.dumps({"somethingElse": {}}),
        json.dumps({"claudeAiOauth": {"accessToken": ""}}),
        json.dumps({"claudeAiOauth": {"accessToken": "t", "expiresAt": "not-an-int"}}),
    ],
    ids=["malformed", "missing-key", "empty-token", "bad-expiry"],
)
def test_linux_provider_treats_unusable_store_content_as_no_credential(
    tmp_path: Path, body: str
) -> None:
    """Unusable content is "no credential", never an exception and never a blank one.

    A blank credential is the failure mode scenario 3 of the ticket calls out: it
    surfaces much later as an in-container 401 rather than at the point of failure.
    """
    store = tmp_path / ".credentials.json"
    store.write_text(body)
    host = LinuxHost(name="wsl", env={"HARNESS_CLAUDE_CREDENTIALS_FILE": str(store)})

    assert host.agent_credential() is None


# ---------------------------------------------------------------------------
# The macOS provider
# ---------------------------------------------------------------------------


def test_macos_provider_reads_the_keychain_item(tmp_path: Path) -> None:
    """The Keychain argv is preserved verbatim and its JSON parsed."""
    payload = json.dumps({"claudeAiOauth": {"accessToken": "mac-token", "expiresAt": 777}})
    _stub(
        tmp_path / "bin",
        "security",
        f'#!/usr/bin/env bash\necho "$*" >> "{tmp_path}/argv.log"\ncat <<\'EOF\'\n{payload}\nEOF\n',
    )
    host = MacOSHost(name="macos", env=_path_env(tmp_path / "bin"))

    assert host.agent_credential() == AgentCredential(token="mac-token", expires_at_ms=777)
    argv = (tmp_path / "argv.log").read_text()
    assert "find-generic-password" in argv
    assert "Claude Code-credentials" in argv


@pytest.mark.parametrize(
    "body",
    ["#!/usr/bin/env bash\nexit 1\n", "#!/usr/bin/env bash\necho 'garbage'\n"],
    ids=["nonzero-exit", "unparseable-output"],
)
def test_macos_provider_missing_or_failing_keychain_is_no_credential(
    tmp_path: Path, body: str
) -> None:
    _stub(tmp_path / "bin", "security", body)
    host = MacOSHost(name="macos", env=_path_env(tmp_path / "bin"))

    assert host.agent_credential() is None


def test_macos_provider_absent_security_binary_is_no_credential(tmp_path: Path) -> None:
    """An empty PATH means no ``security`` at all — still no traceback."""
    empty = tmp_path / "empty"
    empty.mkdir()
    host = MacOSHost(name="macos", env={"PATH": str(empty)})

    assert host.agent_credential() is None


# ---------------------------------------------------------------------------
# Provider detection — AC-4
# ---------------------------------------------------------------------------


def test_detect_host_selects_macos(tmp_path: Path) -> None:
    host = detect_host(platform="darwin", osrelease_path=tmp_path / "none", env={})
    assert isinstance(host, MacOSHost)
    assert host.name == "macos"


@pytest.mark.parametrize(
    "osrelease, env, expected",
    [
        ("Linux version 5.15.0-microsoft-standard-WSL2", {}, "wsl"),
        ("Linux version 5.15.0-MICROSOFT", {}, "wsl"),
        ("Linux version 6.1.0-generic", {"WSL_DISTRO_NAME": "Ubuntu"}, "wsl"),
        ("Linux version 6.1.0-generic", {}, "linux"),
    ],
    ids=["osrelease-microsoft", "osrelease-case-insensitive", "env-marker", "plain-linux"],
)
def test_detect_host_distinguishes_wsl_from_plain_linux(
    tmp_path: Path, osrelease: str, env: dict[str, str], expected: str
) -> None:
    """WSL *is* Linux, so ``sys.platform`` alone cannot make this call.

    The next ADR 0012 tickets (path translation, ssh-agent forwarding) need the
    distinction, and an error message must be able to say which host it is on.
    """
    osrelease_path = tmp_path / "osrelease"
    osrelease_path.write_text(osrelease)

    host = detect_host(platform="linux", osrelease_path=osrelease_path, env=env)

    assert isinstance(host, LinuxHost)
    assert host.name == expected


def test_detect_host_tolerates_an_unreadable_osrelease(tmp_path: Path) -> None:
    """A missing /proc/version is plain Linux, not a crash."""
    host = detect_host(platform="linux", osrelease_path=tmp_path / "absent", env={})
    assert host.name == "linux"


def test_unsupported_platform_names_the_platform_and_the_missing_provider(
    tmp_path: Path,
) -> None:
    """AC-4: a named, actionable error — not an empty credential surfacing as a 401."""
    with pytest.raises(UnsupportedHost) as excinfo:
        detect_host(platform="win32", osrelease_path=tmp_path / "none", env={})

    message = str(excinfo.value)
    assert "win32" in message
    assert "provider" in message.lower()
    assert excinfo.value.platform == "win32"


# ---------------------------------------------------------------------------
# Git identity — shared across providers
# ---------------------------------------------------------------------------


def test_git_identity_reads_global_config(tmp_path: Path) -> None:
    _stub(
        tmp_path / "bin",
        "git",
        '#!/usr/bin/env bash\nfor a in "$@"; do\n'
        '  if [[ "$a" == "user.name" ]]; then echo "Ada"; exit 0; fi\n'
        '  if [[ "$a" == "user.email" ]]; then echo "ada@example.com"; exit 0; fi\n'
        "done\nexit 1\n",
    )
    host = LinuxHost(name="linux", env=_path_env(tmp_path / "bin"))

    assert host.git_identity() == GitIdentity(name="Ada", email="ada@example.com")


def test_git_identity_defaults_are_applied_per_field(tmp_path: Path) -> None:
    """A name with no email keeps the name — the default fills only the gap.

    The bash it replaces used a per-field ``|| echo`` fallback; collapsing to an
    all-or-nothing default would silently discard a configured name.
    """
    _stub(
        tmp_path / "bin",
        "git",
        '#!/usr/bin/env bash\nfor a in "$@"; do\n'
        '  if [[ "$a" == "user.name" ]]; then echo "Ada"; exit 0; fi\n'
        "done\nexit 1\n",
    )
    host = LinuxHost(name="linux", env=_path_env(tmp_path / "bin"))

    assert host.git_identity() == GitIdentity(name="Ada", email="harness@local")


def test_git_identity_falls_back_entirely_when_git_is_absent(tmp_path: Path) -> None:
    empty = tmp_path / "empty"
    empty.mkdir()
    host = LinuxHost(name="linux", env={"PATH": str(empty)})

    assert host.git_identity() == GitIdentity(name="Harness", email="harness@local")


# ---------------------------------------------------------------------------
# Bounded execution — what "timeout selection" was selecting *for*
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("host_factory", [MacOSHost, LinuxHost], ids=["macos", "linux"])
def test_bounded_run_kills_a_child_that_overruns_the_bound(
    tmp_path: Path, host_factory: type
) -> None:
    """Both providers bound a child, on a host shipping neither ``timeout`` nor ``gtimeout``.

    The bash probed for those binaries because a shell cannot bound its own child;
    Python can, so the deliverable is the *bounding*, not the probe. macOS ships
    neither binary — which is precisely why the probe existed.
    """
    host = host_factory(name="test", env=_path_env())

    started = time.monotonic()
    result = host.bounded_run(["sleep", "10"], seconds=1)
    elapsed = time.monotonic() - started

    assert elapsed < 5, f"child was not killed at the bound (took {elapsed:.1f}s)"
    assert result.returncode != 0


@pytest.mark.parametrize("host_factory", [MacOSHost, LinuxHost], ids=["macos", "linux"])
def test_bounded_run_returns_a_fast_childs_output(tmp_path: Path, host_factory: type) -> None:
    host = host_factory(name="test", env=_path_env())

    result = host.bounded_run(["echo", "hello"], seconds=30)

    assert result.returncode == 0
    assert "hello" in result.stdout


@pytest.mark.parametrize("host_factory", [MacOSHost, LinuxHost], ids=["macos", "linux"])
def test_bounded_run_reports_an_absent_binary_without_raising(
    tmp_path: Path, host_factory: type
) -> None:
    """A missing binary is a non-zero result, not an OSError escaping the module."""
    empty = tmp_path / "empty"
    empty.mkdir()
    host = host_factory(name="test", env={"PATH": str(empty)})

    result = host.bounded_run(["definitely-not-a-real-binary"], seconds=5)

    assert result.returncode != 0


def test_bounded_run_never_uses_a_shell(tmp_path: Path) -> None:
    """List-form argv, ``shell=False`` — a credential-bearing argument must never be
    re-parsed by a shell."""
    host = LinuxHost(name="linux", env=_path_env())

    result = host.bounded_run(["echo", "$(touch /tmp/pwned-305)"], seconds=10)

    assert "$(touch" in result.stdout
    assert not Path("/tmp/pwned-305").exists()


def test_bounded_run_is_a_completed_process(tmp_path: Path) -> None:
    """The return type is the stdlib's, so callers need no bespoke wrapper."""
    host = LinuxHost(name="linux", env=_path_env())

    assert isinstance(host.bounded_run(["echo", "x"], seconds=5), subprocess.CompletedProcess)
