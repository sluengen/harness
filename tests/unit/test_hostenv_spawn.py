"""``harness.hostenv.spawn`` — the one home for ``docker run`` construction (#307).

ADR 0012's load-bearing property, and the reason this is a *spawner* rather than a
proxied docker socket:

    The caller never specifies the mount, the image, the privilege, or the env.

The caller names a verb and a repo; the host constructs the invocation. This module
holds the construction for **both** callers — the ``serve`` socket path and the
client's direct-spawn fallback — so the two cannot drift apart into two different
security postures (#307 design, *Interface / contract*).

These tests are the executable form of **AC-4**: a request cannot cause a mount,
an image, or a privilege not chosen by the host. The mechanism is positional —
every caller-derived value lands *after* the image, i.e. as an argument to the
harness verb, never in the ``docker run`` option region — so a ticket literally
named ``--privileged`` is an argument to ``harness start``, not a docker flag.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from harness.hostenv import spawn

_REPO = Path("/work/repo")


def _argv(**overrides: object) -> list[str]:
    """``build_docker_argv`` with this module's defaults, overridable per case."""
    kwargs: dict[str, object] = {
        "repo": _REPO,
        "argv": ["status", "R1"],
        "image": "harness:dev",
        "env_names": ["GITHUB_TOKEN"],
        "home": Path("/home/op"),
    }
    kwargs.update(overrides)
    return spawn.build_docker_argv(**kwargs)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Non-vacuity floors. Every assertion below is about *where* a token sits in the
# argv, so a construction that emitted nothing, or that never emitted an image,
# would satisfy the bans for lack of anything to place.
# ---------------------------------------------------------------------------


def test_the_construction_is_non_empty_and_carries_an_image_boundary() -> None:
    argv = _argv()

    assert argv[0] == "docker" and argv[1] == "run", f"not a docker run: {argv[:2]}"
    assert "harness:dev" in argv, "no image in the argv — the boundary below is undefined"
    assert argv.index("harness:dev") < len(argv) - 1, (
        "the image is the last token, so no verb argv was forwarded and the "
        "after-the-image assertions below would be vacuous"
    )


def test_the_forwarded_verb_argv_actually_reaches_the_argv() -> None:
    """The floor for AC-4's positional argument: forwarded tokens must appear."""
    argv = _argv(argv=["status", "R1"])

    assert argv[-2:] == ["status", "R1"], (
        f"the verb argv is not forwarded verbatim at the tail: {argv[-4:]}"
    )


# ---------------------------------------------------------------------------
# AC-4 — the caller cannot reach the docker-option region.
# ---------------------------------------------------------------------------

def _split_at_image(argv: list[str]) -> tuple[list[str], list[str]]:
    """Split ``argv`` into (docker-option region, container-command region).

    The image is the boundary: docker stops parsing options at it and treats
    everything after as the container's command line. Every assertion about
    where a caller value landed is a statement about which side of it the value
    sits on, so the split is derived here once rather than by index arithmetic
    at each call site.
    """
    at = argv.index("harness:dev")
    return argv[:at], argv[at + 1 :]


#: Tokens that would be a host-escape if docker ever parsed them as options,
#: mapped to how many times the **host's own** construction legitimately emits
#: each in the option region. ``-v`` is 3 (workspace + the two credential
#: mounts); the rest are never emitted, so any occurrence is a caller's.
_HOST_EMITTED = {
    "--privileged": 0,
    "-v": 3,
    "--volume": 0,
    "--user": 0,
    "--entrypoint": 0,
    "--network": 0,
    "--cap-add": 0,
}
_ESCAPE_TOKENS = sorted(_HOST_EMITTED)


@pytest.mark.parametrize("token", _ESCAPE_TOKENS)
def test_a_hostile_verb_argument_lands_after_the_image(token: str) -> None:
    """A caller token that *looks* like a docker option is a verb argument.

    This is the mechanism behind AC-4: position, not sanitization. Rejecting the
    token by name would be a blocklist that the next docker flag defeats.
    """
    argv = _argv(argv=["start", token, "/:/host"])
    options, command = _split_at_image(argv)

    assert token in command, f"{token!r} was dropped rather than forwarded to the verb"
    assert "/:/host" in command
    # The host legitimately emits some of these tokens itself (``-v`` for the
    # workspace mount), so the claim is not "absent from the argv" but "the
    # caller's occurrence is not in the region docker parses as options".
    assert command.count(token) == 1
    assert options.count(token) == _HOST_EMITTED[token], (
        f"{token!r} appears {options.count(token)}× in the docker-option region, "
        f"but the host emits it {_HOST_EMITTED[token]}× — a caller value reached it"
    )


def test_every_mount_target_is_host_chosen() -> None:
    """``-v`` targets are the workspace and the two read-only credential mounts.

    Derived from the emitted argv rather than asserted as a literal list, so a
    fourth mount added later fails here instead of passing unnoticed.
    """
    argv = _argv(argv=["start", "-v", "/:/host"])
    options, _ = _split_at_image(argv)

    # A mount spec is ``host:container[:opts]`` — the target is field 1. Only the
    # option region is scanned: the caller's own ``-v /:/host`` sits after the
    # image, where it is an argument to ``harness start``, not a mount.
    targets = {
        options[i + 1].split(":")[1] for i, tok in enumerate(options) if tok == "-v"
    }

    assert targets == {"/workspace", "/home/harness/.ssh", "/home/harness/.codex"}, (
        f"unexpected mount targets {sorted(targets)} — a caller value reached a -v"
    )


def test_the_workspace_mount_names_the_resolved_repo_and_nothing_else() -> None:
    argv = _argv()
    mounts = [argv[i + 1] for i, tok in enumerate(argv) if tok == "-v"]

    assert f"{_REPO}:/workspace" in mounts, f"workspace mount missing from {mounts}"
    assert "-w" in argv and argv[argv.index("-w") + 1] == "/workspace"


def test_the_credential_mounts_are_read_only() -> None:
    argv = _argv()
    mounts = [argv[i + 1] for i, tok in enumerate(argv) if tok == "-v"]

    for mount in mounts:
        if mount.endswith("/.ssh") or mount.endswith("/.codex"):
            pytest.fail(f"credential mount {mount!r} is not marked :ro")
    assert any(m.endswith(":ro") for m in mounts), "no read-only mount emitted"


def test_a_repo_path_containing_a_colon_is_rejected() -> None:
    """A ``:`` in the repo would inject ``-v`` field structure (host:container:opts).

    The one caller-derived value that legitimately sits in the docker-option
    region is the resolved repo path, so it is the one value that must not be
    able to carry the separator that region is parsed with.
    """
    with pytest.raises(spawn.UnsafeRepoPath):
        _argv(repo=Path("/work/re:po"))


def test_secrets_are_passed_by_name_never_by_value() -> None:
    """``-e NAME`` — docker reads the value from the spawning process's env.

    A value in the argv would land in ``ps`` output for every user on the host.
    """
    argv = _argv(env_names=["GITHUB_TOKEN", "CLAUDE_CODE_OAUTH_TOKEN"])

    for name in ("GITHUB_TOKEN", "CLAUDE_CODE_OAUTH_TOKEN"):
        assert name in argv, f"{name} not forwarded"
        assert not any(tok.startswith(f"{name}=") for tok in argv), (
            f"{name} was passed by value — its secret would be visible in ps"
        )


def test_the_pinned_environment_is_pinned_by_value() -> None:
    """The two settings whose *empty* value silently disables them (#278, CAL-584)."""
    argv = _argv()

    assert "HARNESS_WORKSPACE_ROOTS=/workspace" in argv, (
        "the in-container allowlist must be pinned by value, not forwarded by name"
    )
    assert "PYTHONDONTWRITEBYTECODE=1" in argv, (
        "CPython treats only a NON-EMPTY value as on, so this must be pinned to 1"
    )


def test_a_tty_is_requested_only_when_the_caller_has_one() -> None:
    assert "-it" not in _argv(tty=False)
    assert "-it" in _argv(tty=True)


def test_the_agent_mount_source_is_dockers_bridge_not_the_host_socket() -> None:
    """Docker Desktop bridges the host agent at a fixed **in-VM** path.

    The host's own ``SSH_AUTH_SOCK`` on macOS is a per-session launchd path that
    exists only on the host; bind-mounting it into the Linux VM forwards nothing,
    and every ``git push`` over SSH (close / checkpoint) then fails
    ``Permission denied (publickey)`` against a perfectly healthy agent. The host
    socket is the *liveness signal*; the mount source is Docker's bridge.

    Selecting this per platform — a native Linux daemon does mount the host socket
    directly — is #308's *platform-specific spawn concerns*. This pins today's
    behaviour, which is the wrapper's proven one, until that lands.
    """
    argv = _argv(ssh_auth_sock="/private/tmp/com.apple.launchd.abc/Listeners")
    mounts = [argv[i + 1] for i, tok in enumerate(argv) if tok == "-v"]
    agent_mounts = [m for m in mounts if "ssh-a" in m or "ssh_a" in m]

    assert agent_mounts == ["/run/host-services/ssh-auth.sock:/ssh-agent"], (
        f"the agent mount is {agent_mounts} — it must source Docker Desktop's "
        f"in-VM bridge path, never the host's own launchd socket"
    )
    assert not any("com.apple.launchd" in tok for tok in argv), (
        "the host's launchd socket path leaked into the container invocation"
    )


def test_ssh_agent_is_forwarded_only_when_the_host_has_one() -> None:
    without = _argv(ssh_auth_sock=None)
    assert not any("ssh-agent" in tok or "ssh-auth" in tok for tok in without)

    with_agent = _argv(ssh_auth_sock="/tmp/agent.sock")
    mounts = [with_agent[i + 1] for i, tok in enumerate(with_agent) if tok == "-v"]
    # The host path is the liveness signal; the mount source is Docker's bridge —
    # see test_the_agent_mount_source_is_dockers_bridge_not_the_host_socket.
    assert any("ssh-auth.sock" in m for m in mounts), (
        f"the agent socket is not mounted: {mounts}"
    )


# ---------------------------------------------------------------------------
# ``rewrite_repo_argument`` — the argv-translation half of #351.
# ---------------------------------------------------------------------------


def test_a_separated_repo_argument_is_rewritten_to_the_mount_point() -> None:
    out = spawn.rewrite_repo_argument(["review", "--repo", str(_REPO)], _REPO)

    assert out == ["review", "--repo", "/workspace"]


def test_an_equals_form_repo_argument_is_rewritten() -> None:
    out = spawn.rewrite_repo_argument(["review", f"--repo={_REPO}"], _REPO)

    assert out == ["review", "--repo=/workspace"]


def test_argv_without_a_repo_argument_is_forwarded_untouched() -> None:
    """The verb then emits its own deprecation warning, exactly as today.

    Appending ``--repo /workspace`` here would need per-leaf knowledge of which
    commands accept the flag, which this stdlib-only module cannot derive.
    """
    argv = ["version"]

    assert spawn.rewrite_repo_argument(argv, _REPO) == argv


def test_a_repo_argument_naming_a_different_repo_is_refused() -> None:
    """Only one repo is mounted, so a second one cannot be translated — only refused."""
    with pytest.raises(spawn.RepoMismatch):
        spawn.rewrite_repo_argument(["review", "--repo", "/work/other"], _REPO)


def test_a_mismatching_repo_that_is_a_string_prefix_is_still_refused() -> None:
    """``/work/repo-evil`` must not pass for repo ``/work/repo``.

    The anti-vacuity case for the comparison: a ``startswith`` check would accept
    this, and every other case in this file would still pass.
    """
    with pytest.raises(spawn.RepoMismatch):
        spawn.rewrite_repo_argument(["review", "--repo", "/work/repo-evil"], _REPO)


def test_the_rewrite_does_not_touch_a_repo_valued_verb_argument() -> None:
    """Only the ``--repo`` option's own value is rewritten, not a matching literal."""
    out = spawn.rewrite_repo_argument(["defer", "307", "--reason", str(_REPO)], _REPO)

    assert out == ["defer", "307", "--reason", str(_REPO)]
