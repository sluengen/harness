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

from harness.hostenv import host as host_module
from harness.hostenv import spawn
from harness.hostenv.credentials import AgentCredential
from harness.hostenv.host import (
    GitIdentity,
    LinuxHost,
    MacOSHost,
    UnsupportedHost,
    WslHost,
    detect_host,
)
from harness.hostenv.spawn import DOCKER_DESKTOP_AGENT_SOCKET, WorkspaceNotEquivalent


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


# ---------------------------------------------------------------------------
# Platform-specific spawn concerns (#308): the ssh-agent pairing each provider
# chooses, and the workspace mount it will allow.
#
# Both were macOS constants inlined in ``spawn.build_docker_argv``. The hazard is
# not that they were wrong on macOS — they are the wrapper's proven behaviour —
# but that reusing them elsewhere is silently wrong: under WSL the Docker Desktop
# bridge and ``SSH_AUTH_SOCK`` name *different agents*, so the liveness probe would
# pass against one and the mount forward the other.
# ---------------------------------------------------------------------------


def _live_agent(host: object, socket_path: str) -> object:
    """Pin the liveness probe true, so these tests are about the *pairing* alone."""
    host.ssh_agent_is_live = lambda: True  # type: ignore[attr-defined]
    host.env["SSH_AUTH_SOCK"] = socket_path  # type: ignore[attr-defined]
    return host


@pytest.mark.parametrize(
    ("host_factory", "expected_source", "expected_groups"),
    [
        pytest.param(
            lambda: MacOSHost(name="macos", env={}),
            "/run/host-services/ssh-auth.sock",
            ("0",),
            id="macos-mounts-docker-desktops-bridge",
        ),
        pytest.param(
            lambda: LinuxHost(name="linux", env={}),
            "/tmp/probed-agent.sock",
            (),
            id="linux-mounts-the-probed-socket-itself",
        ),
        pytest.param(
            lambda: WslHost(name="wsl", env={}),
            "/tmp/probed-agent.sock",
            (),
            id="wsl-mounts-the-probed-socket-not-the-bridge",
        ),
    ],
)
def test_each_provider_pairs_the_probed_socket_with_its_own_mount_source(
    host_factory: object, expected_source: str, expected_groups: tuple[str, ...]
) -> None:
    """The ``(probed, source)`` pair, per provider — the invariant #308 exists for.

    macOS is the **only** platform where the two differ: its ``SSH_AUTH_SOCK`` is a
    per-session launchd path that does not exist inside the VM, and Docker Desktop
    bridges the agent at a fixed path instead. A native Linux daemon shares the
    kernel namespace, so the probed socket *is* the mountable one.

    Under WSL, reusing the macOS constant would forward the **Windows** agent while
    having probed an agent inside the distro — different key sets, so every push
    fails ``Permission denied (publickey)`` against a healthy agent. This is the
    assertion that would have caught that.
    """
    host = _live_agent(host_factory(), "/tmp/probed-agent.sock")  # type: ignore[operator]

    forwarding = host.ssh_agent_forwarding()  # type: ignore[attr-defined]

    assert forwarding is not None, "a live agent must produce a forwarding"
    assert forwarding.probed == "/tmp/probed-agent.sock", (
        "the probed socket must be the host's own — it is the liveness signal"
    )
    assert forwarding.source == expected_source
    assert forwarding.group_add == expected_groups
    assert forwarding.target == "/ssh-agent"


def test_only_macos_forwards_docker_desktops_bridge() -> None:
    """The non-vacuity floor under the table above.

    Every row could agree on one shared constant and the parametrized test would
    still pass; this states the discrimination directly, so a provider that
    silently adopted the bridge path fails here even if the table were edited.
    """
    sources = {}
    for host in (
        MacOSHost(name="macos", env={}),
        LinuxHost(name="linux", env={}),
        WslHost(name="wsl", env={}),
    ):
        _live_agent(host, "/tmp/probed-agent.sock")
        forwarding = host.ssh_agent_forwarding()
        assert forwarding is not None
        sources[host.name] = forwarding.source

    bridging = {name for name, src in sources.items() if src == DOCKER_DESKTOP_AGENT_SOCKET}
    assert bridging == {"macos"}, (
        f"providers mounting Docker Desktop's bridge are {sorted(bridging)} — only "
        f"macOS may, because only there does the host socket not exist in the VM"
    )


@pytest.mark.parametrize(
    "host_factory",
    [
        pytest.param(lambda: MacOSHost(name="macos", env={}), id="macos"),
        pytest.param(lambda: LinuxHost(name="linux", env={}), id="linux"),
        pytest.param(lambda: WslHost(name="wsl", env={}), id="wsl"),
    ],
)
def test_no_provider_forwards_an_agent_that_is_not_live(host_factory: object) -> None:
    """A dead socket mounted, plus a group grant, is a privilege with no benefit."""
    host = host_factory()  # type: ignore[operator]
    host.env["SSH_AUTH_SOCK"] = "/tmp/stale-agent.sock"
    host.ssh_agent_is_live = lambda: False  # type: ignore[attr-defined]

    assert host.ssh_agent_forwarding() is None

    without_socket = host_factory()  # type: ignore[operator]
    without_socket.ssh_agent_is_live = lambda: pytest.fail(  # type: ignore[attr-defined]
        "the liveness probe is a subprocess — it must not run when there is no socket"
    )
    assert without_socket.ssh_agent_forwarding() is None


# -- the container user: the third platform-specific spawn concern (#380) ----


def _pinned_ids(monkeypatch: pytest.MonkeyPatch, uid: int, gid: int) -> None:
    """Make every provider read ``uid``/``gid`` as the invoking user's.

    Patched on the module's ``os`` rather than read live, because a live read is
    exactly what cannot discriminate: on any uid-1000 box — which is most of them,
    and is what the image bakes — a provider returning the constant 1000 and a
    provider returning the invoking uid produce the same answer.
    """
    monkeypatch.setattr(host_module.os, "getuid", lambda: uid)
    monkeypatch.setattr(host_module.os, "getgid", lambda: gid)


def test_only_macos_leaves_the_container_on_the_images_baked_uid(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """One override, and it is macOS's — the inverse of the ssh-agent split.

    There, macOS is the exception because its host path is unusable inside the
    VM. Here it is the exception because its daemon has already solved the
    problem: Docker Desktop remaps bind-mount ownership to whatever uid the
    container runs as, so the image's baked 1000 owns the mount by construction.
    Every daemon sharing the host's kernel namespace reports the host's real
    ownership instead, and there the container must *be* the invoking user.
    """
    _pinned_ids(monkeypatch, 4242, 4243)

    users = {
        provider.name: provider.container_user()
        for provider in (
            MacOSHost(name="macos", env={}),
            LinuxHost(name="linux", env={}),
            WslHost(name="wsl", env={}),
        )
    }

    pinning = {name for name, user in users.items() if user is not None}
    assert "linux" in pinning, (
        "no provider pins the container's uid, so the discrimination below holds "
        "over an empty set — the table collapsing to all-None must be red"
    )
    assert pinning == {"linux", "wsl"}, (
        f"providers leaving the container on the image's baked uid are "
        f"{sorted(set(users) - pinning)} — only macOS may, because only there "
        f"does the daemon remap mount ownership"
    )


def test_the_linux_provider_pins_the_invoking_uid_not_a_constant(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The uid comes from the *caller*, not from a second copy of the image's.

    This is the assertion the whole ticket turns on. A provider hardcoding 1000
    would satisfy every structural test above and still fail on the one host that
    matters — the CI runner, and any Linux operator who is not the first account
    on the machine.
    """
    _pinned_ids(monkeypatch, 4242, 4243)

    user = LinuxHost(name="linux", env={}).container_user()

    assert user == spawn.ContainerUser(uid=4242, gid=4243)
    assert user is not None and user.spec() == "4242:4243", (
        "the emitted spelling must be uid:gid in that order — reversed, the "
        "container runs as a user that owns nothing"
    )


def test_a_root_invocation_is_refused_rather_than_spawned(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Running the harness as root must not hand the container root.

    The container runs untrusted content, so "not root" is a property to keep
    rather than a default to inherit from the caller. Refused where the object is
    built, so a provider cannot carry an unsafe user as far as spawn time.
    """
    _pinned_ids(monkeypatch, 0, 0)

    with pytest.raises(spawn.UnsafeContainerUser) as raised:
        LinuxHost(name="linux", env={}).container_user()

    assert "0" in str(raised.value), (
        "the refusal must name the uid it refused — it is the whole remediation"
    )


# -- AC-4: the /mnt/c case has a decided, documented behaviour ---------------


_DRVFS_MOUNTS = """\
/dev/sdc / ext4 rw,relatime 0 0
drivers /usr/lib/wsl/drivers drvfs ro,nosuid,nodev,noatime 0 0
C:\\134 /mnt/c drvfs rw,noatime,uid=1000,gid=1000,case=off 0 0
"""

_NON_DEFAULT_ROOT_MOUNTS = """\
/dev/sdc / ext4 rw,relatime 0 0
C:\\134 /c drvfs rw,noatime,uid=1000,gid=1000,case=off 0 0
"""


def test_a_windows_filesystem_repo_is_refused_under_wsl(tmp_path: Path) -> None:
    """AC-4. The decided behaviour is **refuse**, and the refusal must be actionable.

    A repo on ``/mnt/c`` reaches the container across drvfs, whose permission,
    symlink and case semantics are not the distro's — and the harness's verbs
    depend on all three (mode bits on hooks, the ``.git`` file of a linked
    worktree, case-sensitive path comparison). Warning and proceeding would
    reproduce exactly the silent breakage this ticket names; supporting it would
    be a claim no one has exercised. Moving the repo is a remedy the operator
    controls, so the refusal names it.
    """
    mounts = tmp_path / "mounts"
    mounts.write_text(_DRVFS_MOUNTS)
    host = WslHost(name="wsl", env={}, mounts_path=mounts)

    with pytest.raises(WorkspaceNotEquivalent) as raised:
        host.workspace_mount(Path("/mnt/c/Users/op/repo"))

    message = str(raised.value)
    assert "/mnt/c/Users/op/repo" in message, "the refusal must name the path"
    assert "#313" in message, (
        "the message must name the ticket where WSL support is earned, so an "
        "operator can see this is undecided-pending-validation, not a bug"
    )
    assert "drvfs" in message


def test_a_repo_inside_the_wsl_filesystem_is_accepted(tmp_path: Path) -> None:
    """The other half. Without this the refusal could be unconditional."""
    mounts = tmp_path / "mounts"
    mounts.write_text(_DRVFS_MOUNTS)
    host = WslHost(name="wsl", env={}, mounts_path=mounts)

    mount = host.workspace_mount(Path("/home/op/src/repo"))

    assert mount.target == "/workspace"
    # Compared against the *resolved* spelling, not the literal, because that is
    # the contract (`WorkspaceMount.validate` refuses anything else) and because
    # this suite runs on macOS, where /home is a firmlink.
    assert mount.source == str(Path("/home/op/src/repo").resolve())


def test_the_refusal_follows_the_mount_table_not_the_mnt_prefix(tmp_path: Path) -> None:
    """``wsl.conf`` can set ``root=/c/``, so the prefix is a fallback, not the rule.

    Detection reads the fstype of the repo's longest-matching mount entry. A host
    that automounts its Windows drives somewhere other than ``/mnt`` must still be
    refused, and a ``/mnt/...`` path that is *not* a Windows filesystem must not be.
    """
    mounts = tmp_path / "mounts"
    mounts.write_text(_NON_DEFAULT_ROOT_MOUNTS)
    host = WslHost(name="wsl", env={}, mounts_path=mounts)

    with pytest.raises(WorkspaceNotEquivalent):
        host.workspace_mount(Path("/c/Users/op/repo"))

    # /mnt/data is on ext4 here (it falls under `/`), so the prefix alone must not
    # condemn it.
    accepted = host.workspace_mount(Path("/mnt/data/repo"))
    assert accepted.source == str(Path("/mnt/data/repo").resolve())


def test_an_unreadable_mount_table_falls_back_to_the_automount_prefix(
    tmp_path: Path,
) -> None:
    """Fail *safe*, not open: with no evidence, the documented default applies.

    ``/proc/mounts`` is always readable on a real WSL distro; this is the
    belt-and-braces path, and proceeding as if a ``/mnt/c`` repo were fine is the
    one outcome that reproduces the silent failure.
    """
    host = WslHost(name="wsl", env={}, mounts_path=tmp_path / "does-not-exist")

    with pytest.raises(WorkspaceNotEquivalent):
        host.workspace_mount(Path("/mnt/c/Users/op/repo"))

    accepted = host.workspace_mount(Path("/home/op/src/repo"))
    assert accepted.source == str(Path("/home/op/src/repo").resolve()), (
        "the fallback must condemn only the automount prefix — a distro path with "
        "no mount table to consult is still an ordinary repo"
    )


@pytest.mark.parametrize(
    "host_factory",
    [
        pytest.param(lambda: MacOSHost(name="macos", env={}), id="macos"),
        pytest.param(lambda: LinuxHost(name="linux", env={}), id="linux"),
    ],
)
def test_a_non_wsl_provider_does_not_refuse_a_mnt_path(host_factory: object) -> None:
    """``/mnt/c`` is an ordinary directory name on macOS and plain Linux.

    The negative control for the refusal: a predicate keyed on the path spelling
    rather than on the platform would break every Linux host with a ``/mnt``
    layout, and nothing else in the suite would notice.
    """
    host = host_factory()  # type: ignore[operator]

    assert host.workspace_mount(Path("/mnt/c/data/repo")).target == "/workspace"


def test_detect_host_returns_the_wsl_provider_for_a_wsl_marker(tmp_path: Path) -> None:
    """The seam is only reachable if detection actually selects it.

    Without this, every WSL assertion above would be testing a class nothing
    constructs — the shape #181 records as a guard that certifies itself.
    """
    osrelease = tmp_path / "version"
    osrelease.write_text("Linux version 5.15.0-microsoft-standard-WSL2")

    resolved = detect_host(platform="linux", osrelease_path=osrelease, env={})

    assert isinstance(resolved, WslHost)
    assert resolved.name == "wsl"

    plain = tmp_path / "plain"
    plain.write_text("Linux version 6.1.0-generic")
    ordinary = detect_host(platform="linux", osrelease_path=plain, env={})
    assert not isinstance(ordinary, WslHost), (
        "a plain Linux host must not get the WSL provider — its refusal would be "
        "wrong there, and its agent pairing is only coincidentally the same"
    )
