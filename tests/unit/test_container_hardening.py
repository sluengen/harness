"""Container-hardening invariants (CAL-1008).

The verb container runs LLM agents against **untrusted** ticket/diff content, so
an in-container compromise must not hand the attacker root plus write access to
the mounted repo (incl. ``.git``) or the mounted host credentials. Two static
invariants defend that boundary, and both are asserted here — always-on, no
Docker daemon required, so the in-container review gate (where the docker
integration test skips) still enforces them:

1. The runtime image drops to a **non-root** ``USER`` (``docker/Dockerfile``).
2. The documented ``~/bin/harness`` wrapper (canonical text in
   ``docker/README.md``) mounts host credentials under the **non-root user's
   home** — ``/home/harness/...``, reachable by that user — not ``/root/...``
   (mode ``700``, unreadable to a non-root process), and mounts ``~/.codex``
   **read-only**, and carries the ssh-agent key-scoping guidance.

The runtime *proof* that the built image actually runs as uid != 0 lives in the
docker-gated ``tests/integration/test_docker.py``; this file locks the source
invariants that produce it.
"""

from __future__ import annotations

import re
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.parent
DOCKERFILE = PROJECT_ROOT / "docker" / "Dockerfile"
DOCKER_README = PROJECT_ROOT / "docker" / "README.md"


def _dockerfile() -> str:
    return DOCKERFILE.read_text()


def _readme() -> str:
    return DOCKER_README.read_text()


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
# AC1 (consequence) — wrapper mounts host creds where a non-root user can read
# ---------------------------------------------------------------------------


def test_wrapper_mounts_ssh_under_nonroot_home() -> None:
    """``~/.ssh`` is mounted under /home/harness (reachable by the non-root user)."""
    text = _readme()
    assert '"$HOME/.ssh":/home/harness/.ssh:ro' in text


def test_wrapper_ssh_known_hosts_path_matches_user_home() -> None:
    """GIT_SSH_COMMAND points known_hosts at the non-root user's ~/.ssh."""
    assert "UserKnownHostsFile=/home/harness/.ssh/known_hosts" in _readme()


def test_no_secret_is_mounted_under_root_home() -> None:
    """No credential mount targets /root (mode 700, unreadable to non-root)."""
    text = _readme()
    for stale in (":/root/.ssh", ":/root/.codex", ":/root/.claude"):
        assert stale not in text, (
            f"stale mount target {stale!r} is unreadable under the non-root user; "
            "mount host credentials under /home/harness/... instead"
        )


def _ssh_forwarding_block(readme: str) -> str:
    """Return the populated ``SSH_AGENT_ARGS=( ... )`` array literal (the one that
    forwards the agent socket), or "" if absent."""
    for block in re.findall(r"SSH_AGENT_ARGS=\((.*?)\)", readme, re.DOTALL):
        if "/ssh-auth.sock:/ssh-agent" in block:
            return block
    return ""


def test_wrapper_joins_group_0_to_reach_forwarded_socket() -> None:
    """Docker Desktop forwards the agent socket as ``srw-rw---- root root``; the
    container runs uid 1000 (non-root, CAL-1008), so it can only ``connect()`` to
    the group-rw socket via group 0. The forwarding block must add ``--group-add
    0`` next to the socket mount — without it every ``git push`` over SSH (close /
    checkpoint) fails ``Permission denied (publickey)`` on a healthy host agent."""
    block = _ssh_forwarding_block(_readme())
    assert block, "no populated SSH_AGENT_ARGS block found in docker/README.md"
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
    assert '"$HOME/.codex":/home/harness/.codex:ro' in _readme()


# ---------------------------------------------------------------------------
# AC3 — README documents ssh-agent key scoping
# ---------------------------------------------------------------------------


def test_readme_documents_key_scoping() -> None:
    """The README warns that the forwarded agent should hold a scoped key."""
    assert "scoped to the target remote" in _readme()
