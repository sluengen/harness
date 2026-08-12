"""Credential staleness, the refresh flow, and tracker-credential precedence (#305).

These are the behaviours ``tests/unit/test_wrapper_token_refresh.py`` used to assert
as *text* in the shell script. They are asserted here as behaviour instead, which is
the point of the port: a grep for ``expiresAt`` proves the word is present, not that
a stale token is ever actually refreshed.
"""

from __future__ import annotations

import json
import os
import stat
import time
from pathlib import Path

import pytest

from harness.hostenv.credentials import (
    REFRESH_WINDOW_MS,
    AgentCredential,
    parse_credential_store,
    read_dotenv_value,
)
from harness.hostenv.host import LinuxHost

NOW_MS = 1_700_000_000_000


def _path_env(*prepend: Path, **extra: str) -> dict[str, str]:
    """Stub directories in front of the real PATH, so ``bash`` still resolves."""
    parts = [str(p) for p in prepend] + [os.environ["PATH"]]
    return {"PATH": os.pathsep.join(parts), **extra}


def _stub(directory: Path, name: str, body: str) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    path.write_text(body)
    path.chmod(path.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    return path


def _store(path: Path, token: str, expires_at: int) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"claudeAiOauth": {"accessToken": token, "expiresAt": expires_at}}))
    return path


# ---------------------------------------------------------------------------
# Staleness — the boundary the whole refresh decision turns on
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "expires_at_ms, expected_stale",
    [
        (NOW_MS + REFRESH_WINDOW_MS, True),  # exactly at the window: `-le`, so stale
        (NOW_MS + REFRESH_WINDOW_MS + 1, False),  # one ms outside: fresh
        (NOW_MS + REFRESH_WINDOW_MS - 1, True),
        (0, True),  # store omitted the expiry: refresh rather than trust it
        (NOW_MS - 1, True),  # already expired
    ],
    ids=["at-boundary", "just-outside", "just-inside", "unknown-expiry", "expired"],
)
def test_is_stale_boundary(expires_at_ms: int, expected_stale: bool) -> None:
    """``<=`` mirrors the bash ``-le`` exactly.

    Off by one millisecond in the wrong direction and a token that expires during
    the container's run is passed in as fresh, which surfaces as a false ``review``
    failure rather than as a credential problem (CAL-941).
    """
    credential = AgentCredential(token="t", expires_at_ms=expires_at_ms)
    assert credential.is_stale(NOW_MS) is expected_stale


def test_parse_credential_store_round_trips_a_real_document() -> None:
    parsed = parse_credential_store(
        json.dumps({"claudeAiOauth": {"accessToken": "abc", "expiresAt": 42}})
    )
    assert parsed == AgentCredential(token="abc", expires_at_ms=42)


def test_parse_credential_store_defaults_a_missing_expiry_to_zero() -> None:
    """A missing expiry is unknown, and unknown reads as stale (see is_stale)."""
    parsed = parse_credential_store(json.dumps({"claudeAiOauth": {"accessToken": "abc"}}))
    assert parsed is not None
    assert parsed.expires_at_ms == 0
    assert parsed.is_stale(NOW_MS) is True


@pytest.mark.parametrize(
    "document",
    ["", "   ", "not json", "[]", '"a string"', json.dumps({"claudeAiOauth": "not-an-object"})],
    ids=["empty", "whitespace", "garbage", "array", "string", "wrong-shape"],
)
def test_parse_credential_store_never_raises(document: str) -> None:
    assert parse_credential_store(document) is None


# ---------------------------------------------------------------------------
# The refresh flow — a stale token triggers the CLI's own refresh, once
# ---------------------------------------------------------------------------


def test_a_stale_credential_is_refreshed_and_the_fresh_value_read_back(tmp_path: Path) -> None:
    """The end-to-end contract CAL-941 exists for.

    The ``claude`` stub rewrites the fixture store the way the real CLI rewrites the
    Keychain, so this measures the whole loop: detect stale → refresh → re-read.
    """
    store = _store(tmp_path / ".credentials.json", token="stale", expires_at=NOW_MS - 1)
    calls = tmp_path / "claude-calls.log"
    _stub(
        tmp_path / "bin",
        "claude",
        f'#!/usr/bin/env bash\necho "$*" >> "{calls}"\n'
        f"cat > '{store}' <<'EOF'\n"
        + json.dumps({"claudeAiOauth": {"accessToken": "fresh", "expiresAt": NOW_MS + 10**7}})
        + "\nEOF\n",
    )
    host = LinuxHost(
        name="linux", env=_path_env(tmp_path / "bin", HARNESS_CLAUDE_CREDENTIALS_FILE=str(store))
    )

    before = host.agent_credential()
    assert before is not None and before.is_stale(NOW_MS)

    host.refresh_agent_credential()
    after = host.agent_credential()

    assert after == AgentCredential(token="fresh", expires_at_ms=NOW_MS + 10**7)
    assert calls.read_text().strip() == "-p ok"
    assert calls.read_text().count("\n") == 1, "refresh must be attempted exactly once"


@pytest.mark.parametrize(
    "body",
    ["#!/usr/bin/env bash\nexit 1\n", "#!/usr/bin/env bash\nsleep 60\n"],
    ids=["refresh-fails", "refresh-hangs"],
)
def test_a_failed_or_hung_refresh_leaves_the_stale_token_usable(tmp_path: Path, body: str) -> None:
    """A refresh that cannot run must not escalate into a hard failure.

    This is the wrapper's ``|| true`` preserved deliberately. Failing hard here would
    take a deployment that works offline-with-a-warm-token and break it outright;
    the container's own 401 is the correct place for that to surface.

    The hung case also proves the bound is real — a sleep far longer than the bound
    returns rather than hanging the unattended loop. The bound is overridden to 1s so
    the proof does not cost the production 60s on every gate run; the code path under
    test is identical.
    """
    store = _store(tmp_path / ".credentials.json", token="stale", expires_at=NOW_MS - 1)
    _stub(tmp_path / "bin", "claude", body)
    host = LinuxHost(
        name="linux", env=_path_env(tmp_path / "bin", HARNESS_CLAUDE_CREDENTIALS_FILE=str(store))
    )

    started = time.monotonic()
    host.refresh_agent_credential(timeout_seconds=1)  # must not raise
    assert time.monotonic() - started < 30, "the refresh bound did not hold"

    assert host.agent_credential() == AgentCredential(token="stale", expires_at_ms=NOW_MS - 1)


def test_a_refresh_with_no_claude_cli_is_a_silent_no_op(tmp_path: Path) -> None:
    store = _store(tmp_path / ".credentials.json", token="stale", expires_at=NOW_MS - 1)
    empty = tmp_path / "empty"
    empty.mkdir()
    host = LinuxHost(
        name="linux",
        env={"PATH": str(empty), "HARNESS_CLAUDE_CREDENTIALS_FILE": str(store)},
    )

    host.refresh_agent_credential()

    assert host.agent_credential() is not None


# ---------------------------------------------------------------------------
# Tracker credentials — precedence, and #171's structural guarantee
# ---------------------------------------------------------------------------


def test_env_beats_dotenv_beats_gh(tmp_path: Path) -> None:
    (tmp_path / ".env").write_text("LINEAR_API_KEY=from-dotenv\nGITHUB_TOKEN=from-dotenv\n")
    _stub(tmp_path / "bin", "gh", '#!/usr/bin/env bash\necho "from-gh"\n')

    from_env = LinuxHost(
        name="linux",
        env=_path_env(tmp_path / "bin", GITHUB_TOKEN="from-env", LINEAR_API_KEY="from-env"),
    ).tracker_credentials(tmp_path)
    assert from_env.github_token == "from-env"
    assert from_env.linear_api_key == "from-env"
    assert from_env.sources["GITHUB_TOKEN"] == "env"

    from_dotenv = LinuxHost(name="linux", env=_path_env(tmp_path / "bin")).tracker_credentials(
        tmp_path
    )
    assert from_dotenv.github_token == "from-dotenv"
    assert from_dotenv.sources["GITHUB_TOKEN"] == "dotenv"


def test_gh_is_the_last_resort_and_only_for_the_github_token(tmp_path: Path) -> None:
    """A ``gh`` OAuth token rotates ~8h, so it is fetched fresh — but only when
    nothing higher-precedence supplied one, and never for Linear (issue #170)."""
    _stub(tmp_path / "bin", "gh", '#!/usr/bin/env bash\necho "fresh-gh-token"\n')
    host = LinuxHost(name="linux", env=_path_env(tmp_path / "bin"))

    credentials = host.tracker_credentials(tmp_path)  # no .env at all

    assert credentials.github_token == "fresh-gh-token"
    assert credentials.sources["GITHUB_TOKEN"] == "gh"
    assert credentials.linear_api_key is None


def test_gh_is_not_consulted_when_the_token_is_already_resolved(tmp_path: Path) -> None:
    calls = tmp_path / "gh-calls.log"
    _stub(tmp_path / "bin", "gh", f'#!/usr/bin/env bash\necho called >> "{calls}"\necho tok\n')
    host = LinuxHost(name="linux", env=_path_env(tmp_path / "bin", GITHUB_TOKEN="already-set"))

    host.tracker_credentials(tmp_path)

    assert not calls.exists(), "gh must not be invoked when the token is already resolved"


def test_a_dotenv_missing_the_key_yields_an_empty_value_not_an_abort(tmp_path: Path) -> None:
    """Issue #171, now structural rather than dependent on a trailing ``|| true``.

    In the bash this replaces, a no-match ``grep`` exits 1 and ``set -euo pipefail``
    killed the entire wrapper before the ``gh`` fallback could run — so a repo whose
    ``.env`` legitimately omits a key could run *no verb at all*. The guarantee is
    now a property of the parser: no match is ``None``, and resolution continues.
    """
    (tmp_path / ".env").write_text("SOMETHING_ELSE=x\n")
    _stub(tmp_path / "bin", "gh", '#!/usr/bin/env bash\necho "gh-fallback"\n')
    host = LinuxHost(name="linux", env=_path_env(tmp_path / "bin"))

    credentials = host.tracker_credentials(tmp_path)

    assert credentials.linear_api_key is None
    assert credentials.github_token == "gh-fallback", "the gh fallback must still be reached"


def test_a_missing_dotenv_is_not_an_error(tmp_path: Path) -> None:
    host = LinuxHost(name="linux", env={"PATH": str(tmp_path / "nothing")})

    credentials = host.tracker_credentials(tmp_path / "no-such-dir")

    assert credentials.linear_api_key is None
    assert credentials.github_token is None


@pytest.mark.parametrize(
    "line, expected",
    [
        ("GITHUB_TOKEN=plain", "plain"),
        ("export GITHUB_TOKEN=exported", "exported"),
        ("export\tGITHUB_TOKEN=tabbed", "tabbed"),
        ("GITHUB_TOKEN=has=equals=signs", "has=equals=signs"),
        ("GITHUB_TOKEN=trailing-cr\r", "trailing-cr"),
        ("GITHUB_TOKEN=", ""),
    ],
    ids=["plain", "export", "tab", "embedded-equals", "carriage-return", "empty"],
)
def test_dotenv_value_parsing_matches_the_shell_it_replaces(
    tmp_path: Path, line: str, expected: str
) -> None:
    """``cut -d= -f2-`` semantics: everything after the *first* ``=``, ``\\r`` stripped.

    The embedded-equals case is the one a naive ``split("=")`` gets wrong, and a
    GitHub token containing ``=`` would be silently truncated into an invalid
    credential that fails as a 401 much later.
    """
    (tmp_path / ".env").write_text(line + "\n")
    assert read_dotenv_value(tmp_path / ".env", "GITHUB_TOKEN") == expected


def test_dotenv_ignores_a_key_that_is_only_a_prefix(tmp_path: Path) -> None:
    """``GITHUB_TOKEN_OLD`` must not satisfy a lookup for ``GITHUB_TOKEN``."""
    (tmp_path / ".env").write_text("GITHUB_TOKEN_OLD=wrong\nGITHUB_TOKEN=right\n")
    assert read_dotenv_value(tmp_path / ".env", "GITHUB_TOKEN") == "right"


def test_dotenv_takes_the_first_match(tmp_path: Path) -> None:
    """``head -1`` semantics, preserved."""
    (tmp_path / ".env").write_text("GITHUB_TOKEN=first\nGITHUB_TOKEN=second\n")
    assert read_dotenv_value(tmp_path / ".env", "GITHUB_TOKEN") == "first"


def test_a_credential_value_is_never_written_into_a_diagnostic(tmp_path: Path) -> None:
    """Diagnostics name the *source* and the failure, never the value.

    Diagnostics go to stderr, which is captured in logs and CI output; a token that
    leaks there outlives the process that read it.
    """
    store = _store(tmp_path / ".credentials.json", token="super-secret-value", expires_at=1)
    host = LinuxHost(name="linux", env={"HARNESS_CLAUDE_CREDENTIALS_FILE": str(store)})

    credential = host.agent_credential()

    assert credential is not None and credential.token == "super-secret-value"
    assert "super-secret-value" not in "\n".join(host.diagnostics)


def test_a_credential_value_is_never_rendered_by_its_own_repr() -> None:
    """The same rule as the diagnostic above, for the object rather than the log.

    Until #309 this mattered less: an ``AgentCredential`` existed for the
    duration of one ``spawn`` call. It now lives in a ``CredentialBroker`` for
    the life of the ``serve`` process, reachable from ``repr(vars(server))`` and
    from any traceback that renders host state — so the field is excluded from
    the repr rather than trusted to stay out of one.

    The floor matters as much as the ban: ``expires_at_ms`` must still appear.
    It is not a secret — it is forwarded to the container as
    ``CLAUDE_CODE_OAUTH_EXPIRES_AT`` — and it is the field an operator debugging
    a ``credential_unavailable`` refusal needs. A repr emptied wholesale would
    satisfy the ban and help nobody.
    """
    credential = AgentCredential(token="super-secret-value", expires_at_ms=NOW_MS)

    rendered = repr(credential)

    assert "super-secret-value" not in rendered, (
        f"the credential value is rendered by its own repr: {rendered}"
    )
    assert str(NOW_MS) in rendered, (
        f"the repr was emptied rather than narrowed: {rendered}"
    )
