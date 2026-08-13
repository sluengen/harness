"""Background renewal of the agent credential, off the request path (#309).

ADR 0012 names what the persistent host process is allowed to be: *"a credential
broker, a spawner, and a scheduler — nothing that outlives a request describes a
run."* The spawner and the scheduler shipped with #307; this is the broker.

**What it buys.** Before this, every verb request read the host's credential
store and, inside the five-minute window, ran ``claude -p ok`` — a subprocess
bounded at sixty seconds — before docker was touched. That cost sat on the
request, and worse, a token five minutes from expiry was handed to a ``review``
that legitimately runs twelve minutes; the 401 arrived mid-run and read as a
review failure. Renewing twenty minutes ahead on a background thread removes
both.

**What it costs, stated plainly.** The token now lives in this process
continuously rather than for the duration of one ``spawn`` call. That creates no
new principal — anyone who can reach the socket can already run any verb with the
credential injected, and anyone who can read this process's memory holds the same
uid and can read the store directly — but it does widen one window: a core dump
now yields the token at any moment rather than only during a spawn. Three
properties keep the widening from becoming a leak, and each is asserted by a
test: nothing here renders a value in a ``repr``, nothing writes one to a log
line, and no name enters the container argv (secrets cross by name, values
through the subprocess environment).

**Failure is an observable, never an exit status.**
``HostPlatform.refresh_agent_credential`` swallows everything and returns
``None`` — it can exit 0 and write nothing. So a cycle judges itself by re-reading
the store: a credential that is still :meth:`~AgentCredential.is_stale` after a
refresh is a failed renewal, whatever the subprocess said (#302).

Stdlib only — see the package docstring.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum

from harness.hostenv.container_env import AgentCredentialLease, AgentCredentialSource
from harness.hostenv.credentials import AgentCredential
from harness.hostenv.host import HostPlatform

__all__ = [
    "ABSENT_RECHECK_MS",
    "MIN_RENEWAL_INTERVAL_MS",
    "RENEWAL_JOIN_SECONDS",
    "RENEWAL_LEAD_MS",
    "RENEWAL_RETRY_MS",
    "THREAD_NAME",
    "BrokeredSource",
    "CredentialBroker",
    "RenewalOutcome",
    "RenewalRecord",
    "next_delay_ms",
]

#: How far ahead of expiry a healthy credential is renewed. **Derived, not
#: guessed**: the longest a single engine call may run is
#: ``loop.engine_timeout_seconds`` (900s), and the request path begins refusing
#: inside ``REFRESH_WINDOW_MS`` (300s). Renewing twenty minutes out therefore
#: leaves any credential served in a healthy system at least fifteen minutes of
#: life, which a twelve-minute ``review`` fits inside.
RENEWAL_LEAD_MS = 20 * 60 * 1000

#: How soon a failed renewal is retried. Short, because the request path is
#: refusing verbs for as long as this state lasts.
RENEWAL_RETRY_MS = 60 * 1000

#: How often an absent store is re-checked, so an operator running ``claude``
#: and ``/login`` while ``serve`` is up is picked up without a restart.
ABSENT_RECHECK_MS = 5 * 60 * 1000

#: The floor on any wake. Without it a store with an unknown expiry —
#: ``expires_at_ms == 0``, which reads as stale — would spin the thread.
MIN_RENEWAL_INTERVAL_MS = 30 * 1000

#: How long :meth:`CredentialBroker.stop` waits for the thread. Shutdown is
#: never blocked: if the thread is mid-``claude -p ok`` the join times out and
#: the daemon thread dies with the process, matching the recorded reasoning for
#: ``VerbServer.block_on_close = False``.
RENEWAL_JOIN_SECONDS = 1.0

#: The renewal thread's name, so a test (and an operator reading a traceback)
#: can identify it without matching on a target function.
THREAD_NAME = "harness-credential-broker"


class RenewalOutcome(StrEnum):
    """What a cycle observed. Three states, and each has exactly one answer."""

    #: A usable credential is held. Requests are served with it.
    VALID = "valid"
    #: The store holds nothing. Requests run with no agent credential, and are
    #: **never** refused — an absent store is not a renewal failure.
    ABSENT = "absent"
    #: A credential is held but renewal did not take. Requests are refused.
    FAILED = "failed"


@dataclass(frozen=True)
class RenewalRecord:
    """What the last cycle observed. Carries no token — safe to repr and to log."""

    outcome: RenewalOutcome
    expires_at_ms: int
    attempted_at_ms: int
    detail: str = ""


def next_delay_ms(record: RenewalRecord, now_ms: int) -> int:
    """When to wake next, in milliseconds. Pure — the whole schedule, no clock.

    A ``VALID`` record wakes :data:`RENEWAL_LEAD_MS` before its expiry, floored
    at :data:`MIN_RENEWAL_INTERVAL_MS`. The floor is why the "wakes before the
    request path would refuse" property is stated over credentials with more than
    ``MIN_RENEWAL_INTERVAL_MS + REFRESH_WINDOW_MS`` of life left: below that the
    floor governs, the wake coincides with (or follows) the first refusing
    moment, and the credential is already in the regime the refusal exists for.
    """
    if record.outcome is RenewalOutcome.ABSENT:
        return ABSENT_RECHECK_MS
    if record.outcome is RenewalOutcome.FAILED:
        return RENEWAL_RETRY_MS
    return max(record.expires_at_ms - RENEWAL_LEAD_MS - now_ms, MIN_RENEWAL_INTERVAL_MS)


class CredentialBroker:
    """Holds one agent credential and keeps it fresh on a background thread.

    Constructed against the host detected at ``serve`` startup, not per request:
    the whole point is that the request path asks this object rather than the
    store. :meth:`prime` runs one cycle synchronously **before the socket
    serves**, so no request ever observes an unknown state and the first request
    cannot trigger a renewal.
    """

    def __init__(
        self,
        host: HostPlatform,
        *,
        log: Callable[[str], None],
        sleeper: Callable[[float], bool] | None = None,
    ) -> None:
        self._host = host
        self._log = log
        self._stopping = threading.Event()
        #: ``(seconds) -> stop requested``. The injection point that makes the
        #: thread testable with no sleeping anywhere; the default is the stop
        #: event's own wait, which is what lets ``stop()`` return the thread
        #: from a twenty-minute sleep immediately.
        self._sleeper = sleeper if sleeper is not None else self._stopping.wait
        self._lock = threading.Lock()
        self._credential: AgentCredential | None = None
        self._record = RenewalRecord(
            outcome=RenewalOutcome.ABSENT,
            expires_at_ms=0,
            attempted_at_ms=0,
            detail="not yet primed",
        )
        self._thread: threading.Thread | None = None
        self._source = BrokeredSource(self)

    # -- what the request path sees -----------------------------------------

    @property
    def state(self) -> RenewalRecord:
        return self.snapshot()[1]

    @property
    def source(self) -> AgentCredentialSource:
        """The seam to hand to ``VerbServer(credentials=…)``."""
        return self._source

    def snapshot(self) -> tuple[AgentCredential | None, RenewalRecord]:
        """The credential and the record that describes it, read together.

        One lock acquisition rather than two, because they are committed
        together: a reader that took them separately could pair a fresh
        credential with the previous cycle's verdict.
        """
        with self._lock:
            return self._credential, self._record

    def __repr__(self) -> str:
        _credential, record = self.snapshot()
        return (
            f"<CredentialBroker outcome={record.outcome.value} "
            f"expires_at_ms={record.expires_at_ms}>"
        )

    # -- the cycle ----------------------------------------------------------

    def prime(self) -> RenewalRecord:
        """Run one cycle synchronously. The startup moment, named.

        Deliberately the same cycle :meth:`renew_once` runs: priming that
        differed from renewing would be a second code path exercised exactly
        once per process, which is where a bug lives undisturbed.
        """
        return self.renew_once()

    def renew_once(self) -> RenewalRecord:
        """Read the store, renew if owed, and record what was *observed*."""
        now_ms = self._host.now_ms()
        credential = self._host.agent_credential()

        if credential is None:
            return self._commit(
                None,
                RenewalRecord(
                    outcome=RenewalOutcome.ABSENT,
                    expires_at_ms=0,
                    attempted_at_ms=now_ms,
                    detail="the host store holds no agent credential",
                ),
            )

        if not credential.is_stale(now_ms):
            return self._commit(
                credential,
                RenewalRecord(
                    outcome=RenewalOutcome.VALID,
                    expires_at_ms=credential.expires_at_ms,
                    attempted_at_ms=now_ms,
                    detail="read from the host store, outside the refresh window",
                ),
            )

        # The refresh reports nothing — it swallows every error and returns
        # None — so the store is re-read and the *credential* is the verdict.
        self._host.refresh_agent_credential()
        renewed = self._host.agent_credential() or credential
        if renewed.is_stale(self._host.now_ms()):
            return self._commit(
                renewed,
                RenewalRecord(
                    outcome=RenewalOutcome.FAILED,
                    expires_at_ms=renewed.expires_at_ms,
                    attempted_at_ms=now_ms,
                    detail=(
                        "the renewal left a credential inside the refresh window; "
                        "run `claude` on this host and `/login`"
                    ),
                ),
            )
        return self._commit(
            renewed,
            RenewalRecord(
                outcome=RenewalOutcome.VALID,
                expires_at_ms=renewed.expires_at_ms,
                attempted_at_ms=now_ms,
                detail="renewed",
            ),
        )

    def _commit(
        self, credential: AgentCredential | None, record: RenewalRecord
    ) -> RenewalRecord:
        """Swap the credential and its record together, then log per policy.

        The lock is held for the pointer swap only, never across the refresh
        subprocess — a request must never queue behind a sixty-second
        ``claude -p ok``, which is the cost this module exists to delete.
        """
        with self._lock:
            previous = self._record
            self._credential = credential
            self._record = record

        # A failure is logged every cycle, not only on transition: it is the
        # operator's one notice, and the refusals it explains keep happening.
        # A healthy or absent state is logged only on change, so a broker
        # renewing happily does not write a line every twenty minutes.
        if record.outcome is RenewalOutcome.FAILED or record.outcome is not previous.outcome:
            self._log(
                f"harness serve: agent credential {record.outcome.value} "
                f"expires_at_ms={record.expires_at_ms} ({record.detail})"
            )
        return record

    # -- the thread ---------------------------------------------------------

    def start(self) -> None:
        """Launch the renewal loop on a daemon thread. Idempotent."""
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._loop, name=THREAD_NAME, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        """Ask the thread to finish and wait briefly. Never blocks shutdown.

        Safe on a broker that was never started, and safe to call twice — the
        ``serve`` command calls it from a ``finally``, which also runs on the
        path where ``build_server`` produced no broker at all.
        """
        self._stopping.set()
        thread, self._thread = self._thread, None
        if thread is not None:
            thread.join(RENEWAL_JOIN_SECONDS)

    def _loop(self) -> None:
        """Sleep on the derived schedule, then renew, until asked to stop.

        Sleep *first*: :meth:`prime` has already run a cycle, so renewing
        immediately here would refresh nothing and double the startup cost.
        """
        while True:
            delay_ms = next_delay_ms(self.state, self._host.now_ms())
            if self._sleeper(delay_ms / 1000):
                return
            try:
                self.renew_once()
            except Exception as exc:  # noqa: BLE001 — the loop must outlive one bad cycle
                # Nothing is swallowed: it surfaces twice, as this line and as
                # the next request's refusal.
                self._commit(
                    None,
                    RenewalRecord(
                        outcome=RenewalOutcome.FAILED,
                        expires_at_ms=0,
                        attempted_at_ms=self._host.now_ms(),
                        detail=f"the renewal cycle raised {type(exc).__name__}: {exc}",
                    ),
                )


class BrokeredSource(AgentCredentialSource):
    """The request path's view of the broker: no store read, and it may refuse."""

    def __init__(self, broker: CredentialBroker) -> None:
        self._broker = broker

    def __repr__(self) -> str:
        return f"<BrokeredSource {self._broker!r}>"

    def agent_credential(self, host: HostPlatform) -> AgentCredentialLease:
        """The broker's credential.

        ``host`` is deliberately ignored, and that is the point rather than an
        oversight: this credential was read by the broker's own host at renewal
        time, so the request touches no store and runs no subprocess.
        """
        credential, _record = self._broker.snapshot()
        return AgentCredentialLease(credential=credential)

    def refusal(self, host: HostPlatform) -> str | None:
        """Refuse when a credential is held and is *still* inside the window.

        Re-evaluated against current time rather than trusting the last cycle's
        verdict: a renewal thread that died, or a machine suspended for two
        hours, must not keep a ``VALID`` record serving an expired token.

        An absent credential is never a refusal (D2) — there is nothing to
        renew, so nothing failed to renew, and a host with no Claude at all must
        still run ``status`` and ``worktrees cleanup``.
        """
        credential, _record = self._broker.snapshot()
        if credential is None:
            return None
        if not credential.is_stale(host.now_ms()):
            return None
        return (
            f"the host's Claude agent credential is inside its refresh window "
            f"(expires_at_ms={credential.expires_at_ms}) and background renewal "
            f"has not taken. No container was spawned. Run `claude` on this host "
            f"and `/login`, then retry."
        )
