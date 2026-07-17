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


def test_wrapper_builds_tty_flags_without_command_substitution() -> None:
    """AC1/AC2 (CAL-1150): the ``-it`` flags are assembled via a bash array —
    the shellcheck-clean idiom the file already uses for ``SSH_AGENT_ARGS`` —
    not an unquoted ``$(...)`` command substitution (SC2046). This guards the fix
    on hosts where shellcheck itself is unavailable (the always-on host): ``bash
    -n`` does not catch SC2046, so without this a future edit could silently
    reintroduce the warning. The array preserves the TTY behaviour: ``-it`` is
    passed when stdin is a terminal and omitted otherwise."""
    wrapper = _wrapper()
    assert '$([[ -t 0 ]] && echo' not in wrapper, (
        "the SC2046-prone `$([[ -t 0 ]] && echo \"-it\")` command substitution must "
        "be gone — it word-splits unquoted (shellcheck SC2046)"
    )
    assert "TTY_ARGS=(" in wrapper, (
        "the wrapper must build the -it flags in a TTY_ARGS array, mirroring "
        "SSH_AGENT_ARGS"
    )
    assert '${TTY_ARGS[@]+"${TTY_ARGS[@]}"}' in wrapper, (
        "TTY_ARGS must expand with the set-or-empty-safe array idiom "
        '${TTY_ARGS[@]+\"${TTY_ARGS[@]}\"}, so an empty array passes no argument'
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


def test_wrapper_mounts_ssh_under_nonroot_home() -> None:
    """``~/.ssh`` is mounted under /home/harness (reachable by the non-root user)."""
    assert '"$HOME/.ssh":/home/harness/.ssh:ro' in _wrapper()


def test_wrapper_ssh_known_hosts_path_matches_user_home() -> None:
    """GIT_SSH_COMMAND points known_hosts at the non-root user's ~/.ssh."""
    assert "UserKnownHostsFile=/home/harness/.ssh/known_hosts" in _wrapper()


def test_no_secret_is_mounted_under_root_home() -> None:
    """No credential mount targets /root (mode 700, unreadable to non-root)."""
    wrapper = _wrapper()
    for stale in (":/root/.ssh", ":/root/.codex", ":/root/.claude"):
        assert stale not in wrapper, (
            f"stale mount target {stale!r} is unreadable under the non-root user; "
            "mount host credentials under /home/harness/... instead"
        )


def _ssh_forwarding_block(wrapper: str) -> str:
    """Return the populated ``SSH_AGENT_ARGS=( ... )`` array literal (the one that
    forwards the agent socket), or "" if absent."""
    for block in re.findall(r"SSH_AGENT_ARGS=\((.*?)\)", wrapper, re.DOTALL):
        if "/ssh-auth.sock:/ssh-agent" in block:
            return block
    return ""


def test_wrapper_joins_group_0_to_reach_forwarded_socket() -> None:
    """Docker Desktop forwards the agent socket as ``srw-rw---- root root``; the
    container runs uid 1000 (non-root, CAL-1008), so it can only ``connect()`` to
    the group-rw socket via group 0. The forwarding block must add ``--group-add
    0`` next to the socket mount — without it every ``git push`` over SSH (close /
    checkpoint) fails ``Permission denied (publickey)`` on a healthy host agent."""
    block = _ssh_forwarding_block(_wrapper())
    assert block, "no populated SSH_AGENT_ARGS block found in docker/harness-wrapper.sh"
    assert "--group-add 0" in block, (
        "the ssh-agent forwarding block must include '--group-add 0' so the "
        "non-root container user can reach the root-owned, group-rw agent socket"
    )


# ---------------------------------------------------------------------------
# AC2 — ~/.codex is mounted read-only
# ---------------------------------------------------------------------------


def test_wrapper_mounts_codex_readonly() -> None:
    """``~/.codex`` is mounted :ro — nothing in-container writes it (Claude is the
    in-container engine; codex is host-only, ADR 0002), so read-only is safe."""
    assert '"$HOME/.codex":/home/harness/.codex:ro' in _wrapper()


# ---------------------------------------------------------------------------
# AC3 — README documents ssh-agent key scoping
# ---------------------------------------------------------------------------


def test_readme_documents_key_scoping() -> None:
    """The README warns that the forwarded agent should hold a scoped key."""
    assert "scoped to the target remote" in _readme()
