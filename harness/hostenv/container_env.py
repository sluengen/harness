"""Per-request container-environment assembly — one layer above the provider seam.

``host.py`` answers *what does this platform do*; this module answers *what does
this request need*, by driving the providers once per verb invocation. The split
is a layer boundary, not a size cut: the import edge runs one way (this imports
:mod:`harness.hostenv.host`, never the reverse), and both callers of the resolver
— the ``serve`` socket path and the client's direct-spawn fallback — want this
whole layer and none of the provider internals.

**Called per request, never cached.** A persistent ``harness serve`` outlives many
Claude OAuth tokens, so bind time is the one moment whose environment is
guaranteed to be stale later.

Stdlib only — see the package docstring.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

from harness.hostenv import host as host_module
from harness.hostenv.credentials import AgentCredential
from harness.hostenv.host import HostPlatform, UnsupportedHost
from harness.hostenv.spawn import SshAgentForwarding, WorkspaceMount

__all__ = [
    "ContainerEnv",
    "UnsupportedHost",
    "resolve_agent_credential",
    "resolve_container_env",
]


@dataclass(frozen=True)
class ContainerEnv:
    """Everything the host resolves for one verb container, for one request.

    ``values`` are credential and identity values destined for the spawned
    ``docker`` process's own environment, from which docker forwards the
    credentials **by name** (``-e NAME``) — so no value ever appears in an argv,
    and therefore never in ``ps``. ``git_identity`` is separated out because it is
    pinned *by value* on the docker command line rather than forwarded by name,
    exactly as the wrapper pinned it.
    """

    values: dict[str, str]
    git_identity: dict[str, str]
    diagnostics: tuple[str, ...]
    #: How this host forwards its agent, but **only** when one is actually live —
    #: ``None`` otherwise, so a stale ``SSH_AUTH_SOCK`` never mounts a dead socket.
    #: Provider-produced since #308: which socket is *mounted* is platform-specific
    #: even though which socket is *probed* is not.
    ssh_agent: SshAgentForwarding | None = None
    #: The repo bind mount the provider allows for this request. ``None`` only in
    #: the resolver's own tests; production callers always carry the provider's.
    workspace_mount: WorkspaceMount | None = None


def resolve_container_env(workdir: Path, *, host: HostPlatform | None = None) -> ContainerEnv:
    """Resolve one request's credentials and commit identity through the providers.

    **Called per request, never cached** (#307 design, *Interface / contract*).
    The caching version of this function is correct for an hour: a Claude OAuth
    token expires, and a persistent ``harness serve`` outlives many of them. It is
    also the reason resolution cannot be lifted to process start — a server binds
    once and serves for days, so bind time is the one moment whose environment is
    guaranteed to be stale later.

    ``workdir`` is the **requested repo**, not the caller's cwd: ``.env`` lives in
    the target repo, and a persistent server's cwd is whatever shell started it.

    Raises :class:`UnsupportedHost` — deliberately, rather than returning empty
    values. A blank credential does not fail where it is produced; it fails much
    later as an in-container 401 that reads as a review failure (CAL-941).
    """
    # Reached through the module, not bound at import: `detect_host` is the seam
    # every provider test substitutes, and an import-bound reference would make
    # this resolver silently unpatchable — the shape that just cost eight tests.
    host = host_module.detect_host(platform=sys.platform) if host is None else host

    values: dict[str, str] = {}

    tracker = host.tracker_credentials(Path(workdir))
    if tracker.linear_api_key:
        values["LINEAR_API_KEY"] = tracker.linear_api_key
    if tracker.github_token:
        values["GITHUB_TOKEN"] = tracker.github_token

    # An already-exported token short-circuits the whole agent-credential path: no
    # store read, no `claude -p ok`. This is the wrapper's `if [[ -z ... ]]` guard
    # preserved, and it is what lets the wrapper's own tests run without touching a
    # real Keychain.
    if not host.env.get("CLAUDE_CODE_OAUTH_TOKEN"):
        credential = resolve_agent_credential(host)
        if credential is not None:
            values["CLAUDE_CODE_OAUTH_TOKEN"] = credential.token
            values["CLAUDE_CODE_OAUTH_EXPIRES_AT"] = str(credential.expires_at_ms)

    # Both spawn concerns are the provider's since #308. The liveness gate is
    # unchanged — it now lives inside `ssh_agent_forwarding`, so the gate and the
    # mount source are one decision rather than two that can disagree.
    #
    # `workspace_mount` can refuse (WorkspaceNotEquivalent), which propagates: a
    # repo that cannot be mounted equivalently must stop here, where the message
    # names the path and the remedy, rather than running against a directory that
    # does not mean what the caller thinks.
    identity = host.git_identity()
    return ContainerEnv(
        values=values,
        ssh_agent=host.ssh_agent_forwarding(),
        workspace_mount=host.workspace_mount(Path(workdir)),
        git_identity={
            "GIT_AUTHOR_NAME": identity.name,
            "GIT_AUTHOR_EMAIL": identity.email,
            "GIT_COMMITTER_NAME": identity.name,
            "GIT_COMMITTER_EMAIL": identity.email,
        },
        diagnostics=tuple(host.diagnostics),
    )


def resolve_agent_credential(host: HostPlatform) -> AgentCredential | None:
    """Read the credential, refreshing it first if it is at or inside the window.

    A refresh that fails leaves the stale-but-present token in play — the
    container's own 401 is where that belongs, and refusing to start would break a
    deployment whose token is merely close to expiry.
    """
    credential = host.agent_credential()
    if credential is None:
        return None
    if not credential.is_stale(host.now_ms()):
        return credential

    host.refresh_agent_credential()
    return host.agent_credential() or credential

