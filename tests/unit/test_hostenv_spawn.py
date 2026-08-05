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

from harness.hostenv import host as host_module
from harness.hostenv import spawn

_REPO = Path("/work/repo")


def _macos_forwarding(socket_path: str) -> spawn.SshAgentForwarding:
    """The forwarding ``MacOSHost`` produces for a live agent at ``socket_path``.

    Built through the real provider rather than hand-written, so these tests fail
    if the macOS pairing ever changes — which is what makes them AC-1 evidence
    rather than a restatement of the constants.
    """
    macos = host_module.MacOSHost(name="macos", env={"SSH_AUTH_SOCK": socket_path})
    macos.ssh_agent_is_live = lambda: True  # type: ignore[method-assign]
    forwarding = macos.ssh_agent_forwarding()
    assert forwarding is not None
    return forwarding


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


# ---------------------------------------------------------------------------
# ``WorkspaceMount`` — the host↔container mapping, asserted rather than assumed
# (#308 AC-2).
#
# The ticket's hazard is that "a wrong mount path breaks file references across
# the container boundary with **no error at all**". The mount is not moving —
# ``runs.worktree_path`` is recorded container-absolute, so relocating it would
# rewrite the meaning of every recorded path (#307, and the rejected alternative
# in #308's design). What ships instead is the mapping as one object that both
# sides compute with, and a named refusal when it is not a bijection.
# ---------------------------------------------------------------------------


def test_the_default_mapping_round_trips_a_path_under_the_repo() -> None:
    """``from_container(to_container(p)) == p`` — the bijection, on a real path.

    ``.worktrees/harness/<run_id>`` is not an arbitrary example: it is the exact
    shape ``runs.worktree_path`` records, so this is the mapping the ledger's
    already-written rows depend on.
    """
    mount = spawn.WorkspaceMount.default(_REPO)
    worktree = _REPO / ".worktrees/harness/01ABC"

    assert mount.to_container(worktree) == "/workspace/.worktrees/harness/01ABC"
    assert mount.from_container(mount.to_container(worktree)) == worktree


def test_a_container_path_outside_the_mount_target_is_refused() -> None:
    """``from_container``'s refusal branch — the half the round-trip cannot reach.

    ``to_container``'s refusal is covered by the mismatch tests above, but nothing
    exercised the inverse: a container path that is not under the target has no
    host counterpart, and returning ``source / path`` for it would silently invent
    one. This is the concrete case the ledger produces — a ``worktree_path`` row
    written by a *differently* mounted run — so a wrong answer here resolves a run
    to a directory that is not its worktree.
    """
    mount = spawn.WorkspaceMount.default(_REPO)

    with pytest.raises(spawn.WorkspaceNotEquivalent):
        mount.from_container("/somewhere-else/.worktrees/harness/01ABC")


def test_a_mount_source_that_is_not_the_resolved_repo_is_refused() -> None:
    """The docker daemon resolves the source in **its own** namespace.

    So a source carrying an unresolved ``..`` segment mounts whatever that
    resolves to there — a directory the caller never named — and every file
    reference afterwards silently means something else. That is the ticket's
    "no error at all" case, given an error.
    """
    with pytest.raises(spawn.WorkspaceNotEquivalent) as raised:
        _argv(mount=spawn.WorkspaceMount(source="/work/other/../repo", target="/workspace"))

    assert "/work/other/../repo" in str(raised.value), (
        "the refusal must name the offending source — it is the whole remediation"
    )


def test_a_mount_source_naming_a_different_directory_than_the_repo_is_refused() -> None:
    """The mount must be *of the repo the caller named*, not merely well-formed."""
    with pytest.raises(spawn.WorkspaceNotEquivalent):
        _argv(mount=spawn.WorkspaceMount(source="/work/elsewhere", target="/workspace"))


def test_a_mount_source_that_is_a_string_prefix_of_the_repo_is_still_refused() -> None:
    """``/work/repo-evil`` must not pass as ``/work/repo``.

    The same prefix hazard ``rewrite_repo_argument`` guards; asserted here too
    because this is a *different* comparison in a different function.
    """
    with pytest.raises(spawn.WorkspaceNotEquivalent):
        _argv(mount=spawn.WorkspaceMount(source="/work/repo-evil", target="/workspace"))


def test_a_relative_mount_target_is_refused() -> None:
    """``-w`` and ``HARNESS_WORKSPACE_ROOTS`` are absolute-path contracts.

    A relative target would make the allowlist compare against something that is
    not a root, which the in-container check reads as "outside every root".
    """
    with pytest.raises(spawn.WorkspaceNotEquivalent):
        _argv(mount=spawn.WorkspaceMount(source=str(_REPO), target="workspace"))


def test_the_three_places_the_target_is_emitted_cannot_disagree() -> None:
    """One value, three uses: the ``-v`` target, ``-w``, and the pinned allowlist.

    They are read back out of the constructed argv rather than compared to the
    literal ``/workspace``, so this asserts they agree *with each other* — which
    is the property — instead of re-asserting the constant.
    """
    mount = spawn.WorkspaceMount(source=str(_REPO), target="/elsewhere")
    argv = _argv(mount=mount)

    mounts = [argv[i + 1] for i, tok in enumerate(argv) if tok == "-v"]
    workdir = argv[argv.index("-w") + 1]
    allowlist = next(
        tok.split("=", 1)[1] for tok in argv if tok.startswith("HARNESS_WORKSPACE_ROOTS=")
    )

    assert f"{_REPO}:{mount.target}" in mounts, f"the workspace mount is not in {mounts}"
    assert workdir == mount.target == allowlist, (
        f"-w is {workdir!r}, the allowlist is {allowlist!r}, the mount target is "
        f"{mount.target!r} — a file reference means a different thing in each"
    )


def test_the_default_mount_is_still_workspace() -> None:
    """The non-vacuity floor under the test above.

    That test proves the three uses agree with *each other*; without this one
    they could agree on any value, including one that strands every recorded
    ``runs.worktree_path``. The mount point is deliberately not moving in #308.
    """
    assert spawn.WorkspaceMount.default(_REPO).target == "/workspace"
    assert "HARNESS_WORKSPACE_ROOTS=/workspace" in _argv()


def test_a_path_outside_the_repo_has_no_container_spelling() -> None:
    """``to_container`` refuses rather than inventing a mapping for an unmounted path."""
    mount = spawn.WorkspaceMount.default(_REPO)

    with pytest.raises(spawn.WorkspaceNotEquivalent):
        mount.to_container(Path("/etc/passwd"))


def test_the_agent_mount_source_is_dockers_bridge_not_the_host_socket() -> None:
    """Docker Desktop bridges the host agent at a fixed **in-VM** path.

    The host's own ``SSH_AUTH_SOCK`` on macOS is a per-session launchd path that
    exists only on the host; bind-mounting it into the Linux VM forwards nothing,
    and every ``git push`` over SSH (close / checkpoint) then fails
    ``Permission denied (publickey)`` against a perfectly healthy agent. The host
    socket is the *liveness signal*; the mount source is Docker's bridge.

    Since #308 the pairing is the **provider's** to state, not this module's — so
    this builds it through ``MacOSHost`` rather than passing a bare socket path.
    The asserted argv is byte-identical to what the wrapper proved, which is AC-1:
    the refactor moved where the decision is made, not what macOS does.
    """
    forwarding = _macos_forwarding("/private/tmp/com.apple.launchd.abc/Listeners")
    argv = _argv(ssh_agent=forwarding)
    mounts = [argv[i + 1] for i, tok in enumerate(argv) if tok == "-v"]
    agent_mounts = [m for m in mounts if "ssh-a" in m or "ssh_a" in m]

    assert agent_mounts == ["/run/host-services/ssh-auth.sock:/ssh-agent"], (
        f"the agent mount is {agent_mounts} — it must source Docker Desktop's "
        f"in-VM bridge path, never the host's own launchd socket"
    )
    assert not any("com.apple.launchd" in tok for tok in argv), (
        "the host's launchd socket path leaked into the container invocation"
    )
    assert forwarding.probed == "/private/tmp/com.apple.launchd.abc/Listeners", (
        "the probed socket must be retained — it is the evidence that liveness was "
        "checked against the same agent whose bridge is mounted"
    )


def test_ssh_agent_is_forwarded_only_when_the_host_has_one() -> None:
    without = _argv(ssh_agent=None)
    assert not any("ssh-agent" in tok or "ssh-auth" in tok for tok in without)

    with_agent = _argv(ssh_agent=_macos_forwarding("/tmp/agent.sock"))
    mounts = [with_agent[i + 1] for i, tok in enumerate(with_agent) if tok == "-v"]
    # The host path is the liveness signal; the mount source is Docker's bridge —
    # see test_the_agent_mount_source_is_dockers_bridge_not_the_host_socket.
    assert any("ssh-auth.sock" in m for m in mounts), (
        f"the agent socket is not mounted: {mounts}"
    )


def test_group_add_is_emitted_per_group_the_provider_asks_for() -> None:
    """Empty means *no* ``--group-add``, not a group named ``""``.

    macOS needs group 0 to reach Docker Desktop's root-owned bridged socket; a
    Linux host mounting a socket the invoking user already owns needs no such
    grant, and emitting one would be a privilege the platform does not require.
    """
    macos = _argv(ssh_agent=_macos_forwarding("/tmp/agent.sock"))
    assert macos[macos.index("--group-add") + 1] == "0"

    unprivileged = _argv(
        ssh_agent=spawn.SshAgentForwarding(source="/tmp/a.sock", probed="/tmp/a.sock")
    )
    assert "--group-add" not in unprivileged, (
        "a provider asking for no supplementary group must get none"
    )
    assert any("/tmp/a.sock:/ssh-agent" in tok for tok in unprivileged), (
        "the socket is still forwarded — only the group grant is absent"
    )


def test_a_colon_bearing_agent_socket_is_refused() -> None:
    """The agent socket is the *second* value in the docker option region.

    This module's docstring says every caller-derived value lands after the image,
    and the repo path "is the one value validated by content". Moving forwarding
    behind the provider made that second claim false for the two providers whose
    source is environment-derived rather than a fixed constant: ``LinuxHost`` and
    ``WslHost`` both mount ``SSH_AUTH_SOCK`` verbatim.

    ``-v`` splits on ``:``, so a socket path containing one silently re-parses into
    a different mount: ``/tmp/a:b/agent.sock:/ssh-agent`` reads as source ``/tmp/a``,
    target ``b/agent.sock``, mode ``/ssh-agent``. The failure is a docker parse
    error at spawn time, which sends the operator to docker rather than to the
    malformed value — so refuse it here, by content, with a named error.
    """
    with pytest.raises(spawn.UnsafeAgentSocket):
        spawn.SshAgentForwarding(
            source="/tmp/a:b/agent.sock", probed="/tmp/a:b/agent.sock"
        )


def test_a_well_formed_agent_socket_is_still_accepted() -> None:
    """The non-vacuity floor for the refusal above.

    A ban that refused everything would satisfy the test above just as well. This
    pins that the ordinary path — the one every provider actually produces — still
    constructs and still reaches the argv.
    """
    forwarding = spawn.SshAgentForwarding(source="/tmp/a.sock", probed="/tmp/a.sock")
    assert forwarding.target == spawn.AGENT_SOCKET_TARGET, (
        "the target must come from the module constant, not a second literal that "
        "can disagree with it"
    )
    assert any("/tmp/a.sock:/ssh-agent" in tok for tok in _argv(ssh_agent=forwarding))


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
