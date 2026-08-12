"""Per-request container-environment assembly — one layer above the provider seam.

``host.py`` answers *what does this platform do*; this module answers *what does
this request need*, by driving the providers once per verb invocation. The split
is a layer boundary, not a size cut: the import edge runs one way (this imports
:mod:`harness.hostenv.host`, never the reverse), and both callers of the resolver
— the ``serve`` socket path and the client's direct-spawn fallback — want this
whole layer and none of the provider internals.

**Called per request, never cached** — for the tracker credentials, the git
identity and the three spawn concerns, on every path. A persistent
``harness serve`` outlives many Claude OAuth tokens, so bind time is the one
moment whose environment is guaranteed to be stale later.

The **agent** credential is the one exception, and only over the socket (#309).
Where it comes from is a seam — an :class:`AgentCredentialSource` — with two
implementations that answer opposite questions about refusing:

``RequestRefreshingSource``
    The default, used by the client's direct spawn, ``python3 -m harness.hostenv
    env``, and any ``VerbServer`` built without a broker. It resolves on the
    request path exactly as this module always has, and it **cannot refuse** —
    :meth:`AgentCredentialSource.refusal` is a concrete base method returning
    ``None`` and this source does not override it. That is CAL-941's rule
    expressed as the absence of a branch: a path with no scheduler and no second
    chance must ship a stale-but-present token and let the container's own 401
    report it.

``harness.hostenv.broker.BrokeredSource``
    Used by a production ``harness serve``. It resolves nothing on the request
    path, and it **can** refuse, because the broker already tried ahead of time
    with the whole inter-request interval to succeed.

Stdlib only — see the package docstring.
"""

from __future__ import annotations

import sys
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path

from harness.hostenv import host as host_module
from harness.hostenv.credentials import AgentCredential
from harness.hostenv.host import HostPlatform, UnsupportedHost
from harness.hostenv.spawn import ContainerUser, SshAgentForwarding, WorkspaceMount

__all__ = [
    "AgentCredentialLease",
    "AgentCredentialSource",
    "ContainerEnv",
    "CredentialRenewalFailed",
    "RequestRefreshingSource",
    "UnsupportedHost",
    "agent_credential_is_needed",
    "credential_refusal",
    "resolve_agent_credential",
    "resolve_container_env",
]


class CredentialRenewalFailed(Exception):  # noqa: N818 — spec vocabulary, like UnsupportedHost
    """The agent credential was owed a renewal that did not take.

    Raised where the caller can still do something about it — before docker is
    touched — so the operator sees ``run claude and /login`` rather than an
    in-container 401 twelve minutes into a ``review``.
    """


@dataclass(frozen=True)
class AgentCredentialLease:
    """One request's answer about the agent credential. Never renders its value."""

    credential: AgentCredential | None = None

    def __repr__(self) -> str:
        state = "present" if self.credential is not None else "absent"
        return f"<AgentCredentialLease credential={state}>"


class AgentCredentialSource(ABC):
    """Where one request's agent credential comes from, and whether it may refuse."""

    @abstractmethod
    def agent_credential(self, host: HostPlatform) -> AgentCredentialLease:
        """The credential to forward for this request, if there is one."""

    def refusal(self, host: HostPlatform) -> str | None:
        """Why this source would refuse *right now*, or ``None``. Free of I/O.

        The base answer is ``None``, and :class:`RequestRefreshingSource` does
        not override it: a source that resolves on the request path has nothing
        to say ahead of one. Do not add an override here to "share" a refusal —
        the absence of the branch is what keeps CAL-941 true of that path.
        """
        return None


class RequestRefreshingSource(AgentCredentialSource):
    """Today's behaviour, verbatim: read the store, refreshing first if stale."""

    def agent_credential(self, host: HostPlatform) -> AgentCredentialLease:
        return AgentCredentialLease(credential=resolve_agent_credential(host))


def agent_credential_is_needed(host: HostPlatform) -> bool:
    """``False`` when the caller already exported ``CLAUDE_CODE_OAUTH_TOKEN``.

    The wrapper's ``if [[ -z ... ]]`` guard, extracted into one predicate so the
    handler's pre-flight and the resolver cannot disagree about it — and so the
    short-circuit is unforgeable rather than re-inlined at each site.
    """
    return not host.env.get("CLAUDE_CODE_OAUTH_TOKEN")


def credential_refusal(host: HostPlatform, source: AgentCredentialSource) -> str | None:
    """Why this request cannot run, or ``None``. The one predicate.

    Called by ``harness serve``'s pre-flight (so the refusal lands on the wire
    before docker is touched) **and** by :func:`resolve_container_env` (so a
    caller reaching the resolver directly gets the same answer). One function,
    two callers: a second copy of this ordering is a second thing to get wrong,
    and getting the order wrong means an exported token stops short-circuiting.
    """
    if not agent_credential_is_needed(host):
        return None
    return source.refusal(host)


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
    #: The uid/gid the container runs as (#380). ``None`` on a host whose daemon
    #: remaps bind-mount ownership — macOS — where the image's baked uid already
    #: owns the mount. Defaulted here so a test can build a ``ContainerEnv``
    #: without a provider; production always carries the provider's answer.
    container_user: ContainerUser | None = None


def resolve_container_env(
    workdir: Path,
    *,
    host: HostPlatform | None = None,
    credentials: AgentCredentialSource | None = None,
) -> ContainerEnv:
    """Resolve one request's credentials and commit identity through the providers.

    **Called per request, never cached** (#307 design, *Interface / contract*).
    The caching version of this function is correct for an hour: a Claude OAuth
    token expires, and a persistent ``harness serve`` outlives many of them. It is
    also the reason resolution cannot be lifted to process start — a server binds
    once and serves for days, so bind time is the one moment whose environment is
    guaranteed to be stale later.

    ``workdir`` is the **requested repo**, not the caller's cwd: ``.env`` lives in
    the target repo, and a persistent server's cwd is whatever shell started it.

    ``credentials`` selects where the *agent* credential comes from. The default
    is :class:`RequestRefreshingSource` — today's behaviour — so every caller
    that does not pass one is unchanged, which is what keeps ``client.py`` and
    ``__main__.py`` at a zero diff across #309.

    Raises :class:`UnsupportedHost` — deliberately, rather than returning empty
    values. A blank credential does not fail where it is produced; it fails much
    later as an in-container 401 that reads as a review failure (CAL-941). Raises
    :class:`CredentialRenewalFailed` for the same reason, when the source is one
    that can refuse.
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
    # store read, no `claude -p ok`, and no refusal. This is the wrapper's
    # `if [[ -z ... ]]` guard preserved, and it is what lets the wrapper's own
    # tests run without touching a real Keychain. It is asked first, through the
    # same predicate the socket's pre-flight uses.
    #
    # No new name enters `values` here. That is what makes AC-4 hold by
    # construction: every credential this resolver can emit is already a member
    # of `client.FORWARDED_ENV_NAMES`, so the review container's
    # push-credential ban still scans the whole set.
    source = credentials if credentials is not None else RequestRefreshingSource()
    refusal = credential_refusal(host, source)
    if refusal is not None:
        raise CredentialRenewalFailed(refusal)
    if agent_credential_is_needed(host):
        lease = source.agent_credential(host)
        if lease.credential is not None:
            values["CLAUDE_CODE_OAUTH_TOKEN"] = lease.credential.token
            values["CLAUDE_CODE_OAUTH_EXPIRES_AT"] = str(lease.credential.expires_at_ms)

    # All three spawn concerns are the provider's — two since #308, the container
    # user since #380. The liveness gate is unchanged: it lives inside
    # `ssh_agent_forwarding`, so the gate and the mount source are one decision
    # rather than two that can disagree.
    #
    # Two of the three can refuse — `workspace_mount` with WorkspaceNotEquivalent,
    # `container_user` with UnsafeContainerUser — and both propagate. A repo that
    # cannot be mounted equivalently, or a caller running as root, must stop here
    # where the message names the cause and the remedy, rather than running
    # against a directory that does not mean what the caller thinks or handing
    # untrusted content a root container.
    identity = host.git_identity()
    return ContainerEnv(
        values=values,
        ssh_agent=host.ssh_agent_forwarding(),
        workspace_mount=host.workspace_mount(Path(workdir)),
        container_user=host.container_user(),
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

