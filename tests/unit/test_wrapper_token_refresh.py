"""Guard: the versioned ``~/bin/harness`` Docker wrapper must refresh a stale
Claude OAuth token before passing it into the container (CAL-941).

The wrapper's source is the versioned ``docker/harness-wrapper.sh`` (CAL-1123),
which a user symlinks or copies onto their ``PATH`` as ``harness``. Passing the
**static** Keychain access token — the pre-CAL-941 behaviour — makes every
in-container ``claude`` call 401 once the token expires, which surfaces as a
false ``review`` failure. This guard asserts the versioned wrapper still carries
the refresh contract so it cannot regress to the static-token form unnoticed.
"""

from __future__ import annotations

from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.parent
DOCKER_WRAPPER = PROJECT_ROOT / "docker" / "harness-wrapper.sh"


def _readme() -> str:
    return DOCKER_WRAPPER.read_text()


def test_wrapper_reads_token_expiry() -> None:
    """The wrapper reads the Keychain ``expiresAt`` (freshness input)."""
    text = _readme()
    assert "expiresAt" in text
    assert "CLAUDE_CODE_OAUTH_EXPIRES_AT" in text


def test_wrapper_triggers_cli_refresh_when_stale() -> None:
    """The wrapper triggers the Claude CLI's own refresh (`claude -p`) when stale."""
    text = _readme()
    assert "claude -p ok" in text


def test_wrapper_forwards_expiry_into_container() -> None:
    """The freshness marker is forwarded so `harness doctor` can check it."""
    text = _readme()
    assert "-e CLAUDE_CODE_OAUTH_EXPIRES_AT" in text


def test_wrapper_no_longer_claims_it_always_fetches_fresh() -> None:
    """The stale note that *claimed* per-invocation freshness (the bug) is gone."""
    text = _readme()
    assert "fetches\na fresh token on every invocation" not in text
    assert "fetches a fresh token on every invocation" not in text
