"""The agent-credential broker and the source seam it plugs into (#309).

Two things are decided here, and they pull in opposite directions on purpose.

**The request-resolving source cannot refuse.** CAL-941's rule — a refresh that
fails, hangs, or finds no CLI leaves the stale-but-present token in play, and the
container's own 401 is where that belongs — is preserved for the path that has no
second chance: the client's direct spawn and ``python3 -m harness.hostenv env``.
It is preserved *structurally*: :meth:`AgentCredentialSource.refusal` is a
concrete base method returning ``None`` and :class:`RequestRefreshingSource` does
not override it, so there is no branch that could refuse.

**The brokered source can, and does.** Once renewal is scheduled, CAL-941's
asymmetry runs the other way: the broker already tried, with the whole
inter-request interval to succeed, so a credential still inside the window is
evidence that renewal is failing rather than evidence of bad luck. Proceeding
costs a 401 twelve minutes into a ``review``; refusing costs one verb the
operator retries after ``claude`` + ``/login``.

**The predicate is the observable, never the subprocess's status.**
``HostPlatform.refresh_agent_credential`` swallows everything and returns
``None`` — it can exit 0 and write nothing at all. So "renewal failed" means *a
credential is present and still satisfies* ``is_stale(now)`` *when the request is
evaluated*, re-read against current time rather than trusted from the last
cycle's verdict (#302: the acceptance criterion sits on the observable).

Unit tier: every host here is a fake, the clock is pinned, and the renewal thread
is driven by an injected ``sleeper`` — nothing in this module sleeps or spawns.
"""

from __future__ import annotations

import threading
from pathlib import Path

import pytest

from harness.hostenv import broker as broker_module
from harness.hostenv import client, container_env
from harness.hostenv.broker import (
    ABSENT_RECHECK_MS,
    MIN_RENEWAL_INTERVAL_MS,
    RENEWAL_RETRY_MS,
    CredentialBroker,
    RenewalOutcome,
    RenewalRecord,
    next_delay_ms,
)
from harness.hostenv.container_env import (
    AgentCredentialLease,
    CredentialRenewalFailed,
    RequestRefreshingSource,
    agent_credential_is_needed,
    credential_refusal,
)
from harness.hostenv.credentials import (
    REFRESH_WINDOW_MS,
    AgentCredential,
    TrackerCredentials,
)
from harness.hostenv.host import GitIdentity, HostPlatform

#: A pinned wall clock. Nothing here reads the real one.
NOW_MS = 1_700_000_000_000

#: A value that must never be rendered by any repr or log line under test.
SENTINEL = "SENTINELTOKENVALUE"


def fresh(now_ms: int = NOW_MS, token: str = SENTINEL) -> AgentCredential:
    """A credential comfortably outside the request path's refresh window."""
    return AgentCredential(token=token, expires_at_ms=now_ms + 8 * 60 * 60 * 1000)


def expiring(now_ms: int = NOW_MS, token: str = SENTINEL) -> AgentCredential:
    """A credential *inside* the window but not yet expired.

    Deliberately not an already-expired one: the predicate under test is
    ``is_stale`` — at or inside the five-minute window — and a fixture that had
    already passed expiry would keep passing under the weaker predicate
    ``expires_at_ms <= now``.
    """
    return AgentCredential(token=token, expires_at_ms=now_ms + REFRESH_WINDOW_MS // 2)


class FakeHost(HostPlatform):
    """A host whose store, clock and refresh behaviour the test owns.

    Every method that would otherwise reach a subprocess — ``git_identity``,
    ``ssh_agent_is_live`` — is overridden, so this module stays in the unit tier.
    """

    def __init__(
        self,
        credential: AgentCredential | None = None,
        *,
        env: dict[str, str] | None = None,
        now_ms: int = NOW_MS,
    ) -> None:
        super().__init__(name="fake", env=env or {})
        self.credential = credential
        self.now = now_ms
        self.reads = 0
        self.refreshes = 0
        #: What a refresh installs into the store. ``None`` models the failure
        #: this ticket exists for: ``claude -p ok`` exits 0 and writes nothing.
        self.refresh_installs: AgentCredential | None = None

    def now_ms(self) -> int:
        return self.now

    def agent_credential(self) -> AgentCredential | None:
        self.reads += 1
        return self.credential

    def refresh_agent_credential(self, timeout_seconds: int | None = None) -> None:
        self.refreshes += 1
        if self.refresh_installs is not None:
            self.credential = self.refresh_installs

    def tracker_credentials(self, workdir: Path) -> TrackerCredentials:
        return TrackerCredentials(
            linear_api_key="linear-value", github_token="github-value", sources={}
        )

    def git_identity(self) -> GitIdentity:
        return GitIdentity(name="Fake Op", email="op@example.test")

    def ssh_agent_is_live(self) -> bool:
        return False


class RefusingSource(container_env.AgentCredentialSource):
    """A source that always refuses — the resolver's refusal path, isolated."""

    def agent_credential(self, host: HostPlatform) -> AgentCredentialLease:
        return AgentCredentialLease()

    def refusal(self, host: HostPlatform) -> str | None:
        return "renewal did not take"


def primed(host: FakeHost, log: list[str] | None = None) -> CredentialBroker:
    """A broker that has run exactly one synchronous cycle, as ``serve`` does."""
    sink = log if log is not None else []
    instance = CredentialBroker(host, log=sink.append)
    instance.prime()
    return instance


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    path = tmp_path / "repo"
    (path / ".git").mkdir(parents=True)
    return path


# ---------------------------------------------------------------------------
# The source seam — CAL-941 kept on one path, inverted on the other
# ---------------------------------------------------------------------------


def test_the_request_refreshing_source_has_no_branch_that_could_refuse() -> None:
    """CAL-941, expressed as the absence of a code path rather than a policy.

    A credential permanently inside the window whose refresh does nothing is the
    exact input that makes the brokered source refuse. The request-resolving
    source must still answer ``None``, because a client with no scheduler and no
    second chance refusing here would break a deployment whose token merely got
    close to expiry while offline.
    """
    host = FakeHost(expiring())
    source = RequestRefreshingSource()

    assert source.refusal(host) is None
    assert (
        RequestRefreshingSource.refusal is container_env.AgentCredentialSource.refusal
    ), (
        "RequestRefreshingSource has acquired its own `refusal` — CAL-941 held "
        "because there was no branch to reach, and an override is a branch"
    )


def test_the_request_refreshing_path_still_ships_a_stale_but_present_token(
    repo: Path,
) -> None:
    """The behavioural half: nothing raises, and the token still reaches docker."""
    host = FakeHost(expiring())

    resolved = container_env.resolve_container_env(repo, host=host)

    assert resolved.values["CLAUDE_CODE_OAUTH_TOKEN"] == SENTINEL
    assert host.refreshes == 1, "the request path must still attempt its own refresh"


def test_the_brokered_source_refuses_a_credential_still_inside_the_window() -> None:
    """AC-2's predicate: present *and* stale when the request is evaluated."""
    host = FakeHost(expiring())
    source = primed(host).source

    refusal = source.refusal(host)

    assert refusal is not None
    assert str(host.credential.expires_at_ms) in refusal, (
        "the refusal must name the expiry — it is the operator's only handle on "
        "how stale the credential actually is"
    )
    assert SENTINEL not in refusal


def test_the_brokered_source_does_not_refuse_a_healthy_credential() -> None:
    """The discriminator: a source refusing unconditionally would pass above."""
    host = FakeHost(fresh())

    assert primed(host).source.refusal(host) is None


def test_an_absent_store_is_never_a_renewal_failure() -> None:
    """D2, and the guard a careless implementation breaks.

    ``host-platform.md``'s *an absent store is not an unsupported host* holds
    unchanged: ``status`` and ``worktrees cleanup`` run on a host with no Claude
    installed at all. There is nothing to renew, so nothing failed to renew.
    """
    host = FakeHost(None)
    instance = primed(host)

    assert instance.state.outcome is RenewalOutcome.ABSENT
    assert instance.source.refusal(host) is None
    assert instance.source.agent_credential(host).credential is None


def test_the_refusal_is_re_evaluated_against_current_time_not_the_last_verdict() -> None:
    """A machine suspended for two hours must not keep a ``VALID`` record serving.

    The record says ``VALID`` — it was, when it was written. The predicate reads
    the credential's expiry against *now*, so the request refuses anyway. This is
    what makes the acceptance criterion sit on the observable rather than on a
    status that can fail silently open (#302).
    """
    host = FakeHost(fresh())
    instance = primed(host)
    assert instance.state.outcome is RenewalOutcome.VALID

    host.now = host.credential.expires_at_ms - REFRESH_WINDOW_MS

    assert instance.source.refusal(host) is not None, (
        "a stale credential was served because the last cycle's verdict was "
        "trusted instead of the credential's own expiry"
    )


def test_an_exported_token_short_circuits_the_refusal() -> None:
    """S4: the caller's own export precedes every credential question."""
    host = FakeHost(expiring(), env={"CLAUDE_CODE_OAUTH_TOKEN": "exported-value"})
    source = primed(host).source

    assert agent_credential_is_needed(host) is False
    assert credential_refusal(host, source) is None
    assert source.refusal(host) is not None, (
        "the source itself must still be refusing — otherwise the assertion "
        "above passes because there was nothing to short-circuit"
    )


def test_without_the_export_the_same_request_is_refused() -> None:
    """The discriminator for the short-circuit above."""
    host = FakeHost(expiring())

    assert agent_credential_is_needed(host) is True
    assert credential_refusal(host, primed(host).source) is not None


def test_the_resolver_raises_a_named_error_when_its_source_refuses(repo: Path) -> None:
    """The resolver and the handler's pre-flight consult **one** predicate.

    ``resolve_container_env`` is reachable without going through the socket —
    ``VerbServer.spawn`` called directly, for one — so the refusal cannot live
    only in the handler.
    """
    host = FakeHost(expiring())

    with pytest.raises(CredentialRenewalFailed) as excinfo:
        container_env.resolve_container_env(
            repo, host=host, credentials=RefusingSource()
        )

    assert "renewal did not take" in str(excinfo.value)


# ---------------------------------------------------------------------------
# The schedule — pure, and measured against the request path's own threshold
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "remaining_ms",
    [
        # The tightest case the property is claimed over, derived from the two
        # constants that bound it rather than written as a literal.
        MIN_RENEWAL_INTERVAL_MS + REFRESH_WINDOW_MS + 1,
        30 * 60 * 1000,
        8 * 60 * 60 * 1000,
    ],
)
def test_the_schedule_wakes_before_the_request_path_would_refuse(
    remaining_ms: int,
) -> None:
    """S8, the measuring test: the two clocks are compared, not two literals.

    ``RENEWAL_LEAD_MS`` is derived — the longest single engine call is
    ``loop.engine_timeout_seconds`` (900s) and the request path refuses inside
    ``REFRESH_WINDOW_MS`` — but the load-bearing relation is that the broker
    wakes *strictly before* the moment a request would begin refusing. Asserting
    the constants against each other would restate the arithmetic; this asserts
    the relation the arithmetic exists to produce.
    """
    expires_at_ms = NOW_MS + remaining_ms
    record = RenewalRecord(
        outcome=RenewalOutcome.VALID,
        expires_at_ms=expires_at_ms,
        attempted_at_ms=NOW_MS,
    )

    wakes_at = NOW_MS + next_delay_ms(record, NOW_MS)
    refuses_from = expires_at_ms - REFRESH_WINDOW_MS

    assert wakes_at < refuses_from, (
        f"the broker sleeps until {wakes_at} but the request path begins "
        f"refusing at {refuses_from} — a healthy system would refuse verbs"
    )


def test_at_the_derived_headroom_the_floor_governs_rather_than_the_lead() -> None:
    """The boundary of the property above, named rather than left implicit.

    A minimum interval is what stops a store with an unknown expiry spinning the
    thread, and any floor makes the strict inequality above false somewhere. That
    somewhere is here, and it is exactly ``MIN_RENEWAL_INTERVAL_MS +
    REFRESH_WINDOW_MS`` of remaining life: the broker's wake coincides with the
    first refusing moment rather than preceding it. Below that the credential is
    already being retried every ``RENEWAL_RETRY_MS``, which is the regime the
    refusal exists for.
    """
    expires_at_ms = NOW_MS + MIN_RENEWAL_INTERVAL_MS + REFRESH_WINDOW_MS
    record = RenewalRecord(
        outcome=RenewalOutcome.VALID,
        expires_at_ms=expires_at_ms,
        attempted_at_ms=NOW_MS,
    )

    assert next_delay_ms(record, NOW_MS) == MIN_RENEWAL_INTERVAL_MS
    assert NOW_MS + next_delay_ms(record, NOW_MS) == expires_at_ms - REFRESH_WINDOW_MS


@pytest.mark.parametrize(
    ("outcome", "expected"),
    [
        (RenewalOutcome.ABSENT, ABSENT_RECHECK_MS),
        (RenewalOutcome.FAILED, RENEWAL_RETRY_MS),
    ],
)
def test_the_non_valid_outcomes_reschedule_on_their_own_cadence(
    outcome: RenewalOutcome, expected: int
) -> None:
    """``ABSENT`` re-checks so an operator's ``claude login`` is picked up without
    a restart; ``FAILED`` retries fast because the request path is refusing."""
    record = RenewalRecord(
        outcome=outcome, expires_at_ms=NOW_MS + 10**9, attempted_at_ms=NOW_MS
    )

    assert next_delay_ms(record, NOW_MS) == expected


def test_an_unknown_expiry_is_floored_rather_than_spinning_the_thread() -> None:
    """``expires_at_ms == 0`` is what the store omitting ``expiresAt`` produces."""
    record = RenewalRecord(
        outcome=RenewalOutcome.VALID, expires_at_ms=0, attempted_at_ms=NOW_MS
    )

    assert next_delay_ms(record, NOW_MS) == MIN_RENEWAL_INTERVAL_MS


# ---------------------------------------------------------------------------
# The cycle
# ---------------------------------------------------------------------------


def test_a_fresh_credential_is_recorded_valid_without_a_refresh() -> None:
    host = FakeHost(fresh())

    record = primed(host).state

    assert record.outcome is RenewalOutcome.VALID
    assert record.expires_at_ms == host.credential.expires_at_ms
    assert host.refreshes == 0, "a credential outside the window was refreshed anyway"


def test_an_absent_store_is_recorded_absent_without_a_refresh() -> None:
    """There is nothing to renew, so ``claude -p ok`` must not be run at all."""
    host = FakeHost(None)

    assert primed(host).state.outcome is RenewalOutcome.ABSENT
    assert host.refreshes == 0


def test_a_stale_credential_is_renewed_and_recorded_valid_when_the_refresh_takes() -> None:
    host = FakeHost(expiring())
    host.refresh_installs = fresh(token="renewed-value")

    record = primed(host).state

    assert host.refreshes == 1
    assert record.outcome is RenewalOutcome.VALID
    assert record.expires_at_ms == host.refresh_installs.expires_at_ms


def test_a_refresh_that_exits_cleanly_and_writes_nothing_is_recorded_failed() -> None:
    """The whole reason the predicate is the observable.

    ``refresh_agent_credential`` returns ``None`` and swallows every error: it
    cannot report failure. Here it "succeeds" — no exception, no complaint — and
    leaves the store exactly as it was. The only way to know is to look at what
    is in the store afterwards.
    """
    host = FakeHost(expiring())
    host.refresh_installs = None

    record = primed(host).state

    assert host.refreshes == 1
    assert record.outcome is RenewalOutcome.FAILED
    assert record.detail, "a failure must say what was observed"


# ---------------------------------------------------------------------------
# The renewal thread — deterministic, and nothing sleeps
# ---------------------------------------------------------------------------


class FakeSleeper:
    """The injected wait. Records what it was asked for; stops on demand.

    This is the whole reason the thread is testable without a wall clock: the
    broker never calls ``time.sleep``, it calls something with this shape, and
    the default is a ``threading.Event.wait`` that ``stop()`` can interrupt.
    """

    def __init__(self, stop_after: int) -> None:
        self.seconds: list[float] = []
        self._stop_after = stop_after

    def __call__(self, seconds: float) -> bool:
        self.seconds.append(seconds)
        return len(self.seconds) > self._stop_after


def test_the_renewal_thread_renews_on_the_derived_schedule() -> None:
    """Two cycles, driven to completion by the sleeper's own answer.

    The synchronisation is the thread returning plus ``join`` — never a
    wall-clock wait — and the delays are compared against ``next_delay_ms``
    rather than a literal, so a loop that hardcoded an interval fails here.
    """
    host = FakeHost(fresh())
    sleeper = FakeSleeper(stop_after=2)
    instance = CredentialBroker(host, log=lambda _line: None, sleeper=sleeper)
    instance.prime()
    reads_after_priming = host.reads

    instance.start()
    instance.stop()

    expected = next_delay_ms(instance.state, NOW_MS) / 1000
    assert expected > MIN_RENEWAL_INTERVAL_MS / 1000, (
        "the fixture's credential is close enough to expiry that the schedule's "
        "floor governs — a loop hardcoding the floor would pass below"
    )
    assert sleeper.seconds == [expected, expected, expected]
    assert host.reads - reads_after_priming == 2, (
        f"the thread ran {host.reads - reads_after_priming} cycles, not the two "
        f"the sleeper allowed before asking it to stop"
    )


def test_stop_ends_the_thread_and_is_idempotent() -> None:
    """Shutdown must never block, and must be safe to call twice or never-started.

    The default sleeper is the broker's own ``Event.wait``, so ``stop()`` setting
    that event is what returns the thread from a twenty-minute wait immediately.
    """
    host = FakeHost(fresh())
    instance = CredentialBroker(host, log=lambda _line: None)
    instance.prime()

    instance.start()
    instance.stop()

    assert [t for t in threading.enumerate() if t.name == broker_module.THREAD_NAME] == []
    instance.stop()  # second stop
    CredentialBroker(host, log=lambda _line: None).stop()  # never started


def test_an_exception_in_a_cycle_is_logged_and_recorded_as_failed() -> None:
    """Nothing is swallowed: it surfaces as a log line *and* as the next refusal."""

    class ExplodingHost(FakeHost):
        def agent_credential(self) -> AgentCredential | None:
            raise RuntimeError("the keychain went away")

    host = ExplodingHost(fresh())
    lines: list[str] = []
    sleeper = FakeSleeper(stop_after=1)
    instance = CredentialBroker(host, log=lines.append, sleeper=sleeper)

    instance.start()
    instance.stop()

    assert instance.state.outcome is RenewalOutcome.FAILED
    assert any("the keychain went away" in line for line in lines), (
        f"the cycle's exception reached no log line: {lines}"
    )


def test_a_failed_cycle_logs_every_time_and_a_healthy_one_only_on_change() -> None:
    """A broker renewing happily every twenty minutes must not write a line each
    time; a broker that is failing must, because that line is the operator's only
    notice before the refusals start."""
    host = FakeHost(fresh())
    lines: list[str] = []
    instance = CredentialBroker(host, log=lines.append)

    instance.prime()
    instance.renew_once()
    after_healthy = len(lines)

    host.credential = expiring()
    instance.renew_once()
    instance.renew_once()

    assert after_healthy == 1, f"a healthy re-read logged a repeat line: {lines}"
    assert len(lines) - after_healthy == 2, (
        f"a failing cycle logged only on transition: {lines}"
    )


# ---------------------------------------------------------------------------
# AC-3 — nothing on the brokered surface renders a credential value
# ---------------------------------------------------------------------------


def test_no_broker_surface_renders_a_credential_value() -> None:
    """The residency change (§6) is acceptable only while this holds.

    The credential now lives in the process continuously rather than for one
    ``spawn`` call, so it is reachable from ``repr(vars(server))`` and from any
    traceback rendering host state. Each of these four is on that path.
    """
    host = FakeHost(expiring())
    instance = primed(host)

    rendered = [
        repr(instance),
        repr(instance.source),
        repr(instance.state),
        repr(AgentCredentialLease(credential=host.credential)),
        repr(host.credential),
    ]

    for text in rendered:
        assert SENTINEL not in text, f"a credential value was rendered by {text!r}"
    assert str(host.credential.expires_at_ms) in repr(instance), (
        "the broker's repr says nothing useful — the expiry is not a secret and "
        "is the field an operator debugging a refusal needs"
    )
    assert str(host.credential.expires_at_ms) in repr(host.credential), (
        "AgentCredential's repr was emptied rather than narrowed"
    )


# ---------------------------------------------------------------------------
# AC-4 — the close-only push scoping cannot be bypassed by a new env name
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("brokered", [False, True])
def test_every_credential_name_the_resolver_emits_is_one_the_argv_forwards(
    repo: Path, brokered: bool
) -> None:
    """The gap the existing hardening ban cannot see.

    ``test_container_hardening.py::test_no_push_credential_reaches_the_review_container``
    scans ``client.FORWARDED_ENV_NAMES`` and fails the day a push credential is
    added to it. It goes *blind*, rather than failing, if the resolver starts
    emitting a credential under a name that tuple does not carry — the value
    would reach the child's environment without ever appearing in the scanned
    set. So the derived set here comes from a real ``resolve_container_env``
    call under both sources, not from a literal.
    """
    host = FakeHost(fresh())
    source = primed(host).source if brokered else RequestRefreshingSource()

    resolved = container_env.resolve_container_env(repo, host=host, credentials=source)
    emitted = set(resolved.values)

    assert emitted, "the resolver emitted nothing — the subset below is vacuous"
    assert "CLAUDE_CODE_OAUTH_TOKEN" in emitted, (
        "the agent credential is missing from the derived set, so this test is "
        "no longer measuring the path it exists to measure"
    )
    assert emitted <= set(client.FORWARDED_ENV_NAMES), (
        f"the resolver emits {sorted(emitted - set(client.FORWARDED_ENV_NAMES))}, "
        f"which the container argv does not forward by name — a credential "
        f"crossing outside FORWARDED_ENV_NAMES is invisible to the review "
        f"container's push-credential ban"
    )


def test_the_brokered_source_hands_over_the_brokers_own_credential(repo: Path) -> None:
    """The lease is the broker's, and the request's host is never consulted for it."""
    host = FakeHost(fresh(token="brokered-value"))
    source = primed(host).source
    reads_after_priming = host.reads

    lease = source.agent_credential(host)

    assert lease.credential is not None
    assert lease.credential.token == "brokered-value"
    assert host.reads == reads_after_priming, (
        "the brokered source read the store — that read is the per-request cost "
        "this ticket exists to remove"
    )
