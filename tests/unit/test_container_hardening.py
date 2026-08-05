"""Container-hardening invariants (CAL-1008, CAL-1123).

The verb container runs LLM agents against **untrusted** ticket/diff content, so
an in-container compromise must not hand the attacker root plus write access to
the mounted repo (incl. ``.git``) or the mounted host credentials. Two static
invariants defend that boundary, and both are asserted here — always-on, no
Docker daemon required, so the in-container review gate (where the docker
integration test skips) still enforces them:

1. The runtime image drops to a **non-root** ``USER`` (``docker/Dockerfile``).
2. The versioned ``~/bin/harness`` wrapper (``docker/harness-wrapper.sh``) mounts
   host credentials under the **non-root user's home** — ``/home/harness/...``,
   reachable by that user — not ``/root/...`` (mode ``700``, unreadable to a
   non-root process), and mounts ``~/.codex`` **read-only**, and joins group 0 to
   reach the forwarded ssh-agent socket.

The wrapper is a **real, versioned file** (CAL-1123), not a heredoc embedded in
prose: it is ``bash -n``-clean in CI and is the single source ``docker/README.md``
references for installation. These guards therefore lock the *installed artifact*
— the file a user copies or symlinks onto their ``PATH`` — rather than prose that
can silently drift from it. The ssh-agent key-scoping guidance stays a
documentation invariant on ``docker/README.md`` (it is prose, not wrapper code).

The runtime *proof* that the built image actually runs as uid != 0 lives in the
docker-gated ``tests/integration/test_docker.py``; this file locks the source
invariants that produce it.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import warnings
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).parent.parent.parent
DOCKERFILE = PROJECT_ROOT / "docker" / "Dockerfile"
DOCKER_README = PROJECT_ROOT / "docker" / "README.md"
WRAPPER = PROJECT_ROOT / "docker" / "harness-wrapper.sh"


def _dockerfile() -> str:
    return DOCKERFILE.read_text()


def _readme() -> str:
    return DOCKER_README.read_text()


def _wrapper() -> str:
    return WRAPPER.read_text()


def _shellcheck_unavailable_warning() -> str | None:
    """The visibility warning to emit when ``shellcheck`` is not on ``PATH``, else
    ``None`` (CAL-1150).

    Factored out of :func:`test_wrapper_is_shellcheck_clean` so the "the skip is
    visible, not silent" behaviour (AC3) is unit-testable without invoking
    ``pytest.skip``. When shellcheck is present the guard runs its real assertion,
    so there is nothing to warn about.
    """
    if shutil.which("shellcheck") is not None:
        return None
    return (
        "shellcheck is not installed, so the docker/harness-wrapper.sh "
        "shellcheck-clean guard did not run (bash -n remains the always-on "
        "floor). Install shellcheck to enforce SC-class warnings on the wrapper."
    )


def _last_user_directive(dockerfile: str) -> str | None:
    """Return the value of the last ``USER`` instruction, or None if absent."""
    value: str | None = None
    for line in dockerfile.splitlines():
        stripped = line.strip()
        if stripped.upper().startswith("USER "):
            value = stripped.split(maxsplit=1)[1].strip()
    return value


# ---------------------------------------------------------------------------
# AC1 — the runtime image runs non-root
# ---------------------------------------------------------------------------


def test_dockerfile_declares_a_user_directive() -> None:
    """The Dockerfile pins a runtime ``USER`` (root is the implicit default)."""
    assert _last_user_directive(_dockerfile()) is not None, (
        "docker/Dockerfile must declare a USER directive so the runtime process "
        "does not default to root."
    )


def test_dockerfile_user_is_not_root() -> None:
    """The declared ``USER`` is an unprivileged user, not root / uid 0."""
    user = _last_user_directive(_dockerfile())
    assert user not in {None, "root", "0"}, (
        f"container must run non-root; USER resolves to {user!r}"
    )


# ---------------------------------------------------------------------------
# CAL-1123 — the wrapper is a real, versioned, lintable file
# ---------------------------------------------------------------------------


def test_wrapper_file_exists_with_bash_shebang() -> None:
    """The wrapper is a versioned script, not prose: it exists and starts with a
    bash shebang so it is executable and lintable in isolation."""
    assert WRAPPER.exists(), (
        "docker/harness-wrapper.sh must exist as the versioned source of the "
        "~/bin/harness wrapper (CAL-1123)"
    )
    assert _wrapper().startswith("#!/usr/bin/env bash"), (
        "the wrapper must start with a bash shebang so it runs as a real script"
    )


def test_wrapper_file_is_executable() -> None:
    """The versioned wrapper carries the executable bit, so a symlink/copy onto
    PATH runs without a separate ``chmod +x``."""
    import os

    assert os.access(WRAPPER, os.X_OK), (
        "docker/harness-wrapper.sh must be executable (git-tracked mode 755)"
    )


def test_wrapper_is_bash_syntax_clean() -> None:
    """AC1: the versioned wrapper is ``bash -n``-clean, so a syntax error is
    caught by the gate (this test) rather than at a user's next run."""
    result = subprocess.run(
        ["bash", "-n", str(WRAPPER)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        f"docker/harness-wrapper.sh failed `bash -n`:\n{result.stderr}"
    )


def test_the_tty_flag_is_conditional_and_never_an_empty_argument() -> None:
    """CAL-1150's property, retargeted by #307 to where the flags are now built.

    The original shape was bash-specific: an unquoted ``$([[ -t 0 ]] && echo
    "-it")`` word-splits (shellcheck SC2046), so the wrapper assembled a
    ``TTY_ARGS`` array with the set-or-empty-safe expansion instead. Construction
    moved into ``harness.hostenv.spawn``, where that hazard cannot exist — a list
    has no word-splitting — so what survives is the **behaviour** the array
    protected: ``-it`` when stdin is a terminal, and *no* argument at all
    otherwise. An empty-string argument would reach docker as a bogus positional.
    """
    interactive = _verb_container_argv(tty=True)
    piped = _verb_container_argv(tty=False)

    assert "-it" in interactive
    assert "-it" not in piped
    assert "" not in piped, (
        "an empty argument reached the docker argv — the empty case must pass "
        "nothing, not a blank string"
    )
    assert len(interactive) == len(piped) + 1, (
        "the two invocations differ by more than the tty flag"
    )



def test_shellcheck_skip_is_visible_when_absent(monkeypatch: pytest.MonkeyPatch) -> None:
    """AC3 (CAL-1150): when shellcheck is absent the guard does not *silently*
    skip — :func:`_shellcheck_unavailable_warning` returns a message the guard
    emits as a warning, so the gate's warnings summary reports that the wrapper
    shellcheck check did not run."""
    monkeypatch.setattr(shutil, "which", lambda _name: None)
    message = _shellcheck_unavailable_warning()
    assert message is not None
    assert "shellcheck" in message


def test_no_shellcheck_warning_when_present(monkeypatch: pytest.MonkeyPatch) -> None:
    """AC3 (CAL-1150): when shellcheck *is* available there is nothing to warn
    about — the guard runs the real assertion, so no visibility warning fires."""
    monkeypatch.setattr(shutil, "which", lambda _name: "/usr/bin/shellcheck")
    assert _shellcheck_unavailable_warning() is None


def test_wrapper_is_shellcheck_clean() -> None:
    """AC1 (ideal): the wrapper is shellcheck-clean where shellcheck is available.
    When the linter is absent (it is not in the image or on every host) the guard
    warns and skips rather than skipping silently (AC3, CAL-1150), so the gate
    surfaces that the check did not run; ``bash -n`` above remains the always-on
    floor."""
    shellcheck = shutil.which("shellcheck")
    if shellcheck is None:
        warnings.warn(
            _shellcheck_unavailable_warning(),
            stacklevel=2,
        )
        pytest.skip("shellcheck not installed; bash -n is the always-on floor")
    result = subprocess.run(
        [shellcheck, str(WRAPPER)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        f"docker/harness-wrapper.sh failed shellcheck:\n{result.stdout}"
    )


def test_readme_references_wrapper_and_does_not_embed_it() -> None:
    """AC2: docker/README.md references the versioned wrapper file for
    installation rather than embedding the full script as prose. The tell-tale
    invocation line (``exec docker run``) must live only in the wrapper, so the
    README cannot silently drift from the installed artifact."""
    readme = _readme()
    assert "harness-wrapper.sh" in readme, (
        "docker/README.md must reference docker/harness-wrapper.sh for installation"
    )
    assert "exec docker run" not in readme, (
        "docker/README.md must not embed the full wrapper script; the "
        "`exec docker run` invocation belongs only in docker/harness-wrapper.sh"
    )


# ---------------------------------------------------------------------------
# AC1 (consequence) — wrapper mounts host creds where a non-root user can read
# ---------------------------------------------------------------------------


def _macos_forwarding(socket_path: str) -> object:
    """The agent forwarding ``MacOSHost`` produces for a live agent (#308).

    Built through the real provider rather than hand-written. The properties below
    were the wrapper's proven macOS behaviour, and #308 moved *where the decision
    is made* without changing what macOS does — so asserting them over the
    provider's own output is what makes them evidence of that, rather than a
    restatement of the constants they came from.
    """
    from harness.hostenv import host as host_module

    macos = host_module.MacOSHost(name="macos", env={"SSH_AUTH_SOCK": socket_path})
    macos.ssh_agent_is_live = lambda: True  # type: ignore[method-assign]
    forwarding = macos.ssh_agent_forwarding()
    assert forwarding is not None
    return forwarding


def _verb_container_argv(**overrides: object) -> list[str]:
    """The real ``docker run`` argv for a verb container.

    **Retargeted by #307.** These properties were asserted as text in
    ``docker/harness-wrapper.sh`` until the wrapper stopped constructing its own
    container; construction now lives in ``harness.hostenv.spawn``, shared by the
    socket path and the client's fallback. Reading the built argv is the stronger
    form of the same assertion — it exercises the construction rather than
    searching a file for a spelling.
    """
    from harness.hostenv import spawn

    kwargs: dict[str, object] = {
        "repo": Path("/work/repo"),
        "argv": ["status", "R1"],
        "image": "harness:dev",
        "env_names": ("GITHUB_TOKEN",),
        "home": Path("/home/op"),
        "ssh_agent": _macos_forwarding("/tmp/agent.sock"),
    }
    kwargs.update(overrides)
    return spawn.build_docker_argv(**kwargs)  # type: ignore[arg-type]


def test_wrapper_mounts_ssh_under_nonroot_home() -> None:
    """``~/.ssh`` is mounted under /home/harness (reachable by the non-root user)."""
    assert "/home/op/.ssh:/home/harness/.ssh:ro" in _verb_container_argv()


def test_wrapper_ssh_known_hosts_path_matches_user_home() -> None:
    """GIT_SSH_COMMAND points known_hosts at the non-root user's ~/.ssh."""
    assert any(
        "UserKnownHostsFile=/home/harness/.ssh/known_hosts" in arg
        for arg in _verb_container_argv()
    )


def test_no_secret_is_mounted_under_root_home() -> None:
    """No credential mount targets /root (mode 700, unreadable to non-root)."""
    wrapper = _wrapper()
    for stale in (":/root/.ssh", ":/root/.codex", ":/root/.claude"):
        assert stale not in wrapper, (
            f"stale mount target {stale!r} is unreadable under the non-root user; "
            "mount host credentials under /home/harness/... instead"
        )


def test_wrapper_joins_group_0_to_reach_forwarded_socket() -> None:
    """Docker Desktop forwards the agent socket as ``srw-rw---- root root``; the
    container runs uid 1000 (non-root, CAL-1008), so it can only ``connect()`` to
    the group-rw socket via group 0. Forwarding the socket must add ``--group-add
    0`` — without it every ``git push`` over SSH (close / checkpoint) fails
    ``Permission denied (publickey)`` on a healthy host agent."""
    forwarding = _verb_container_argv()
    assert "/run/host-services/ssh-auth.sock:/ssh-agent" in forwarding, (
        "the agent socket was not mounted"
    )
    assert "--group-add" in forwarding and "0" in forwarding, (
        "forwarding the ssh-agent must add '--group-add 0' so the non-root "
        "container user can reach the root-owned, group-rw agent socket"
    )

    assert "--group-add" not in _verb_container_argv(ssh_agent=None), (
        "group 0 was joined with no agent socket to reach — the grant must be "
        "scoped to the case that needs it"
    )


# ---------------------------------------------------------------------------
# AC2 — ~/.codex is mounted read-only
# ---------------------------------------------------------------------------


def test_wrapper_mounts_codex_readonly() -> None:
    """``~/.codex`` is mounted :ro — nothing in-container writes it (Claude is the
    in-container engine; codex is host-only, ADR 0002), so read-only is safe."""
    assert "/home/op/.codex:/home/harness/.codex:ro" in _verb_container_argv()


# ---------------------------------------------------------------------------
# AC3 — README documents ssh-agent key scoping
# ---------------------------------------------------------------------------


def test_readme_documents_key_scoping() -> None:
    """The README warns that the forwarded agent should hold a scoped key."""
    assert "scoped to the target remote" in _readme()


# ---------------------------------------------------------------------------
# The container writes no bytecode into the mounted host tree (#278)
# ---------------------------------------------------------------------------
#
# Python run inside the container writes ``__pycache__/*.pyc`` whose embedded
# source paths are the *container's* (``/workspace/...``) into the tree the host
# also uses. CPython validates a cache entry against the source's recorded mtime
# and size, not its content, so a later **host** run loads those entries and any
# test relying on ``inspect.getsource`` / ``linecache`` fails with ``OSError:
# could not get source code`` — a false red on the very gate that certifies a
# review (observed on run 01KYWT8MJ7GVE3X8T1FYWB69YJ, #275).
#
# The fix pins ``PYTHONDONTWRITEBYTECODE=1`` at each invocation seam rather than
# in the image: the wrapper's staleness guard compares the image against
# ``git log -1 --format=%ct -- harness/``, a path a ``docker/``-only change never
# touches, so an image ``ENV`` would ship green and still leak until something
# forced a rebuild. The wrapper is symlinked from the checkout, so a change to it
# is live on the next invocation.

# The two invocation formats under docker/. Deriving the seam set from the
# directory (rather than naming the two files) is what makes a third seam added
# later fail this guard instead of slipping through — docs are excluded because
# prose does not invoke a container.
_SEAM_SUFFIXES = (".sh", ".yml", ".yaml")

# Accepts both formats' pinned spellings — shell ``-e NAME=1`` and YAML
# ``NAME: "1"`` — and rejects an empty or absent value, which CPython treats as
# "off".
_BYTECODE_PINNED_RE = re.compile(r'PYTHONDONTWRITEBYTECODE\s*[:=]\s*"?1"?')

_WORKSPACE_MOUNT_RE = re.compile(r":/workspace\b")


def _uncommented(text: str) -> str:
    """Drop whole-line comments — both formats use ``#`` — so a mount or a flag
    that only appears in an example inside a comment does not count as real."""
    return "\n".join(
        line for line in text.splitlines() if not line.lstrip().startswith("#")
    )


def _mounting_seams() -> dict[str, str]:
    """Every ``docker/`` file that actually invokes a container with a host tree
    mounted at ``/workspace``, as ``{filename: uncommented text}``."""
    return {
        path.name: body
        for path in sorted((PROJECT_ROOT / "docker").iterdir())
        if path.is_file()
        and path.suffix in _SEAM_SUFFIXES
        and _WORKSPACE_MOUNT_RE.search(body := _uncommented(path.read_text()))
    }


def test_the_seam_derivation_still_finds_the_declarative_seam() -> None:
    """The derived guard below is only as good as its subject set: a derivation
    that silently matched nothing would pass while enforcing nothing.

    **The wrapper left this set in #307** and its absence is now correct rather
    than a regression: it no longer builds a container, so it mounts nothing. That
    makes this floor thinner than it was, which is why the *programmatic* seam has
    its own behavioural guard immediately below — the two together still cover
    every way a host tree reaches ``/workspace``.
    """
    seams = _mounting_seams()
    assert "docker-compose.yml" in seams, (
        "the /workspace-mount derivation no longer finds the compose seam "
        f"(found {sorted(seams)}) — fix the derivation, not the assertion"
    )
    assert "harness-wrapper.sh" not in seams, (
        "the wrapper mounts a host tree again — construction belongs to "
        "harness.hostenv.spawn, which both spawn paths share"
    )


def test_the_programmatic_seam_mounts_at_workspace_and_pins_bytecode() -> None:
    """The seam the text derivation cannot see, asserted behaviourally.

    ``harness.hostenv.spawn`` builds its mount from constants, so no substring
    search of the source would find ``:/workspace`` — and a guard that cannot see
    the live seam is a guard over nothing. Reading the constructed argv is the
    honest instrument, and it covers **both** spawn paths at once, since they
    share this construction.
    """
    argv = _verb_container_argv()

    assert any(arg.endswith(":/workspace") for arg in argv), (
        "the spawner no longer mounts the repo at /workspace — that mount is what "
        "makes the verbs repo-agnostic (CAL-675)"
    )
    assert "PYTHONDONTWRITEBYTECODE=1" in argv, (
        "the spawner mounts a host tree but does not pin PYTHONDONTWRITEBYTECODE=1, "
        "so container-authored bytecode lands in the mount and false-reddens the "
        "next host gate run (#278)"
    )
    assert "PYTHONDONTWRITEBYTECODE" not in argv, (
        "the bare form forwards the *host's* value, and a host exporting it empty "
        "silently disables the protection — CPython treats only a non-empty value "
        "as on. Pin the literal."
    )
    assert "HARNESS_WORKSPACE_ROOTS=/workspace" in argv, (
        "the in-container allowlist must be pinned to the mount point, never "
        "forwarded from a host-side value that is meaningless in the container"
    )


def test_every_mounting_seam_suppresses_bytecode_writes() -> None:
    """Each seam that bind-mounts a host tree pins PYTHONDONTWRITEBYTECODE=1.

    Without it the container leaves host-invalid ``.pyc`` in the mount and the
    next host gate run false-reddens (#278).
    """
    for name, body in _mounting_seams().items():
        assert _BYTECODE_PINNED_RE.search(body), (
            f"docker/{name} mounts a host tree at /workspace but does not pin "
            "PYTHONDONTWRITEBYTECODE=1, so container-authored bytecode lands in "
            "the mount and false-reddens the next host gate run (#278)"
        )


def test_bytecode_suppression_is_pinned_not_forwarded_from_the_host() -> None:
    """``-e PYTHONDONTWRITEBYTECODE`` (bare) would forward the *host's* value, and
    a host exporting it empty silently disables the protection — CPython treats
    only a non-empty value as on. Pin the literal, as HARNESS_WORKSPACE_ROOTS is
    pinned for the same class of reason."""
    for name, body in _mounting_seams().items():
        for forwarded in (
            r"-e\s+PYTHONDONTWRITEBYTECODE\s*(\\|$)",
            r"PYTHONDONTWRITEBYTECODE:\s*\"?\$\{",
        ):
            assert not re.search(forwarded, body, re.MULTILINE), (
                f"docker/{name} forwards PYTHONDONTWRITEBYTECODE from the host "
                "instead of pinning it to 1; an empty host value would disable it"
            )


# ---------------------------------------------------------------------------
# #308 AC-3 — no bearer push credential reaches the review container.
# ---------------------------------------------------------------------------


def test_no_push_credential_reaches_the_review_container() -> None:
    """A bearer push credential must not be handed to the verb that reads a diff.

    **Read the history before reading this as a port.** CAL-622 shipped a
    tokenized-https push fallback — ``GIT_CONFIG_*`` ``insteadOf`` rules plus a
    credential helper supplying ``x-access-token``, scoped to ``close`` and
    deliberately withheld from ``review``. That mechanism lived in
    ``harness/launcher.py``, which CAL-712 deleted with the workflow engine; its
    only surviving description is ``specs/retired/hermes-orchestration.md``. So
    this is **not** a port of a live feature, and a reader who assumes it is will
    mistake this for a vacuous pass. Today ``close`` pushes over ssh.

    What survives is the *intent*, and it is worth guarding because the reasoning
    still holds: ``review`` runs an engine over an untrusted diff, so a bearer
    token in its environment is exfiltratable by the thing it is reviewing. This
    is the regression guard that fails the day one is reintroduced there.

    ``GITHUB_TOKEN`` is the deliberate exception and is *not* a push credential
    here — it is the **tracker** credential this repo's GitHub backend needs to
    comment on the issue, so scoping it to ``close`` would break ``review``. It
    crosses **by name** (``-e GITHUB_TOKEN``), so its value never enters the argv
    and never reaches ``ps``; that distinction is the assertion below.
    """
    argv = _verb_container_argv(argv=["review", "R1"])

    banned = ("GH_TOKEN", "GIT_CONFIG_", "insteadOf", "credential.helper")
    for token in argv:
        for pattern in banned:
            assert pattern not in token, (
                f"the review container's argv carries {token!r}, which matches the "
                f"bearer-push-credential pattern {pattern!r} — review reads an "
                f"untrusted diff and must not hold a credential that can push"
            )

    assert "GITHUB_TOKEN" in argv, (
        "the tracker credential must still be forwarded — review comments on the issue"
    )
    assert not any(tok.startswith("GITHUB_TOKEN=") for tok in argv), (
        "GITHUB_TOKEN was passed by value; its secret would be visible in ps"
    )


def test_the_push_credential_ban_would_catch_a_reintroduced_one() -> None:
    """The negative control: the ban above must be able to fail.

    Every banned pattern is absent from today's argv, so the test passes whether
    or not its predicate discriminates anything — the shape #181 records. This
    runs the same predicate over an argv that *does* carry a push credential and
    asserts it is caught, so a ban that had been narrowed to nothing fails here.
    """
    banned = ("GH_TOKEN", "GIT_CONFIG_", "insteadOf", "credential.helper")
    reintroduced = _verb_container_argv(
        argv=["review", "R1"], env_names=("GITHUB_TOKEN", "GH_TOKEN")
    )

    assert any(pattern in token for token in reintroduced for pattern in banned), (
        "the ban matched nothing in an argv that carries GH_TOKEN — the predicate "
        "no longer discriminates, so the guard above is vacuous"
    )
