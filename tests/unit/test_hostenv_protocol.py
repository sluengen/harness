"""The control-socket wire contract — framing, socket path, refusal reasons (#307).

The socket is the new security boundary (ADR 0012): anyone who can ``connect()``
can run any registered verb against any allowlisted repo with the host's
credentials injected. Everything that makes that boundary defensible is decided
here — the strict three-key schema that makes ``image`` / ``volumes`` /
``privileged`` / ``env`` **inexpressible** rather than merely ignored, and the
size cap that bounds what an unauthenticated peer can make the server allocate.

Stdlib-only, like the rest of ``harness.hostenv``: the client runs on the host
under a bare ``python3`` before any container exists.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from harness.hostenv import protocol

# ---------------------------------------------------------------------------
# Socket path resolution
# ---------------------------------------------------------------------------


def test_an_explicit_socket_env_var_wins() -> None:
    env = {
        "HARNESS_CONTROL_SOCKET": "/custom/h.sock",
        "XDG_RUNTIME_DIR": "/run/user/1000",
        "HOME": "/home/op",
    }

    assert protocol.socket_path(env) == Path("/custom/h.sock")


def test_xdg_runtime_dir_is_preferred_over_home() -> None:
    """A tmpfs the OS clears on logout beats a dotfile that outlives the session."""
    env = {"XDG_RUNTIME_DIR": "/run/user/1000", "HOME": "/home/op"}

    assert protocol.socket_path(env) == Path("/run/user/1000/harness/control.sock")


def test_home_is_the_fallback() -> None:
    env = {"HOME": "/home/op"}

    assert protocol.socket_path(env) == Path("/home/op/.harness/control.sock")


# ---------------------------------------------------------------------------
# Request framing — the strict schema is what closes AC-4 at the wire level.
# ---------------------------------------------------------------------------


def test_a_request_round_trips() -> None:
    encoded = protocol.encode_request(repo=Path("/work/repo"), argv=["status", "R1"])
    decoded = protocol.decode_request(encoded)

    assert decoded.repo == Path("/work/repo")
    assert decoded.argv == ["status", "R1"]


def test_the_encoded_request_is_exactly_three_keys() -> None:
    payload = json.loads(protocol.encode_request(repo=Path("/w/r"), argv=["version"]))

    assert set(payload) == {"protocol", "repo", "argv"}


#: The four things a caller must not be able to say. Each is a docker capability
#: the *host* chooses; a request that could carry one would make this a proxied
#: docker socket rather than a spawner (ADR 0012).
_FORBIDDEN_KEYS = [
    ("image", "evil:latest"),
    ("volumes", "/:/host"),
    ("privileged", True),
    ("env", {"AWS_SECRET_ACCESS_KEY": "x"}),
]


@pytest.mark.parametrize("key, value", _FORBIDDEN_KEYS)
def test_an_extra_key_is_refused_rather_than_ignored(key: str, value: object) -> None:
    """AC-4 at the wire: unknown keys are a refusal, not a silent drop.

    Ignoring them would work identically today and fail open the day a future
    version gives one of these names a meaning.
    """
    raw = json.dumps({"protocol": 1, "repo": "/w/r", "argv": ["start"], key: value})

    with pytest.raises(protocol.BadRequest):
        protocol.decode_request(raw)


@pytest.mark.parametrize(
    "raw",
    [
        "",
        "not json",
        "{}",
        '{"protocol": 1, "repo": "/w/r"}',
        '{"protocol": 1, "argv": ["start"]}',
        '{"protocol": 99, "repo": "/w/r", "argv": ["start"]}',
        '{"protocol": 1, "repo": "/w/r", "argv": "start"}',
        '{"protocol": 1, "repo": "/w/r", "argv": [1, 2]}',
        '{"protocol": 1, "repo": 5, "argv": ["start"]}',
        '{"protocol": 1, "repo": "relative/path", "argv": ["start"]}',
    ],
)
def test_a_malformed_request_is_refused(raw: str) -> None:
    with pytest.raises(protocol.BadRequest):
        protocol.decode_request(raw)


def test_an_oversized_request_is_refused_without_parsing() -> None:
    """The size cap bounds what an unauthenticated peer can make us allocate."""
    raw = json.dumps(
        {"protocol": 1, "repo": "/w/r", "argv": ["x" * (protocol.MAX_REQUEST_BYTES)]}
    )

    with pytest.raises(protocol.BadRequest):
        protocol.decode_request(raw)


def test_the_size_cap_admits_a_realistic_request() -> None:
    """Non-vacuity for the cap: it must not refuse ordinary traffic.

    A cap set to zero would pass the test above for every input.
    """
    long_reason = "x" * 4000  # a `defer --reason` body, the largest real argv
    encoded = protocol.encode_request(
        repo=Path("/work/repo"), argv=["defer", "307", "--reason", long_reason]
    )

    assert protocol.decode_request(encoded).argv[-1] == long_reason


# ---------------------------------------------------------------------------
# Response framing
# ---------------------------------------------------------------------------


def test_a_success_response_round_trips() -> None:
    decoded = protocol.decode_response(protocol.encode_success(exit_code=3))

    assert decoded.ok is True
    assert decoded.exit_code == 3
    assert decoded.reason is None


def test_a_refusal_response_round_trips() -> None:
    encoded = protocol.encode_refusal(protocol.Reason.UNKNOWN_VERB, "no such verb: run")
    decoded = protocol.decode_response(encoded)

    assert decoded.ok is False
    assert decoded.reason == protocol.Reason.UNKNOWN_VERB
    assert "run" in (decoded.error or "")


def test_a_success_response_carries_no_verb_output() -> None:
    """Output crosses on the caller's own fds, never through the response.

    Buffering a run's stdout in the server would be run-describing state living
    outside the ledger — the thing ADR 0012's no-run-state constraint forbids.
    """
    payload = json.loads(protocol.encode_success(exit_code=0))

    assert set(payload) == {"protocol", "ok", "exit_code"}


# ---------------------------------------------------------------------------
# Client exit mapping
# ---------------------------------------------------------------------------


def test_a_successful_response_exits_with_the_container_code() -> None:
    for code in (0, 1, 2, 3, 5):
        assert protocol.exit_code_for(protocol.decode_response(
            protocol.encode_success(exit_code=code)
        )) == code


@pytest.mark.parametrize(
    "reason, expected",
    [
        (protocol.Reason.BAD_REQUEST, 2),
        (protocol.Reason.UNKNOWN_VERB, 2),
        (protocol.Reason.REPO_NOT_ALLOWED, 2),
        (protocol.Reason.REPO_MISMATCH, 2),
        (protocol.Reason.SPAWN_FAILED, 1),
    ],
)
def test_a_refusal_maps_onto_the_cli_exit_contract(
    reason: protocol.Reason, expected: int
) -> None:
    """2 is the CLI's invocation-refusal code; 1 is an unexpected error (SPEC §11).

    ``spawn_failed`` is the one refusal that is not the caller's fault, so it
    must not be reported as a bad invocation.
    """
    response = protocol.decode_response(protocol.encode_refusal(reason, "…"))

    assert protocol.exit_code_for(response) == expected


def test_every_reason_has_an_exit_mapping() -> None:
    """Derived over the enum, so a reason added later fails here rather than
    falling through to an accidental default."""
    for reason in protocol.Reason:
        response = protocol.decode_response(protocol.encode_refusal(reason, "…"))
        assert protocol.exit_code_for(response) in (1, 2)


# ---------------------------------------------------------------------------
# A malformed *response* is a refusal too (#307 review, cycle 1)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw",
    [
        '{"protocol": 1, "ok": false}',                       # no reason
        '{"protocol": 1, "ok": true, "exit_code": "three"}',   # non-int exit code
        '[]',
    ],
)
def test_a_malformed_response_raises_the_catchable_error(raw: str) -> None:
    """Every decode failure must surface as :class:`BadRequest`.

    The client guards this call with ``except protocol.BadRequest``. A bare
    ``KeyError`` or ``ValueError`` escaping here would crash the client with a
    traceback *after* the request was already delivered — the one situation
    where it must instead report that the verb may have run and name the ledger
    as the record.

    ``{"reason": "nonesuch"}`` **left this list in #309** and is asserted
    immediately below instead. It was never malformed — it is a well-formed
    refusal from a newer server, and reporting it as a decode failure made the
    client say the verb *may have run* about a request that spawned nothing.
    """
    with pytest.raises(protocol.BadRequest):
        protocol.decode_response(raw)


# ---------------------------------------------------------------------------
# Forward skew: a reason this client does not know (#309, D4)
# ---------------------------------------------------------------------------


def test_an_unknown_refusal_reason_is_decoded_rather_than_rejected() -> None:
    """Adding a wire reason must not make an older client claim the verb ran.

    Before #309 this frame raised :class:`BadRequest`, and the client's handler
    for that says *"the verb may have run. The ledger is the record."* — the
    worst available message for a refusal, where nothing was spawned at all. The
    frame is well-formed; only the vocabulary is newer. So it decodes with
    ``reason=None``, which :func:`protocol.exit_code_for` already maps to 1, and
    the server's own message is preserved rather than discarded.
    """
    frame = json.dumps(
        {
            "protocol": protocol.PROTOCOL_VERSION,
            "ok": False,
            "reason": "reason_from_a_newer_server",
            "error": "the host's Claude credential expired",
        }
    )

    response = protocol.decode_response(frame)

    assert response.ok is False
    assert response.reason is None
    assert "reason_from_a_newer_server" in (response.error or ""), (
        "the unrecognised reason must survive into the message — it is the only "
        "record of what the newer server actually refused for"
    )
    assert "the host's Claude credential expired" in (response.error or ""), (
        "the server's own message was discarded, leaving the operator nothing"
    )
    assert protocol.exit_code_for(response) == 1


def test_a_known_refusal_reason_still_decodes_to_its_enum_member() -> None:
    """The discriminator for the branch above.

    A ``decode_response`` that gave up on *every* reason string would satisfy
    the test above while destroying the exit-code mapping for the five reasons
    this client does know.
    """
    frame = protocol.encode_refusal(protocol.Reason.REPO_NOT_ALLOWED, "nope")

    response = protocol.decode_response(frame)

    assert response.reason is protocol.Reason.REPO_NOT_ALLOWED
    assert protocol.exit_code_for(response) == 2


def test_the_credential_refusal_is_a_named_reason_exiting_two() -> None:
    """AC-2's *named* error, on the wire.

    ``repo_not_allowed`` was rejected for this (#309, D4): the client would
    print ``repo_not_allowed: the agent credential expired``, and the audit
    line — the socket's only record of who asked for what — would attribute a
    credential outage to the repo allowlist.
    """
    response = protocol.decode_response(
        protocol.encode_refusal(protocol.Reason.CREDENTIAL_UNAVAILABLE, "expired")
    )

    assert response.reason is protocol.Reason.CREDENTIAL_UNAVAILABLE
    assert response.reason.value == "credential_unavailable"
    assert protocol.exit_code_for(response) == 2
