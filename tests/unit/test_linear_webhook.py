"""Tests for intake.linear_webhook — Linear webhook intake (sibling process).

Tests are organised around the six acceptance criteria implied by CAL-301:

AC1 — verify_signature: HMAC-SHA256 validation (positive + negative).
AC2 — route_event: correct routing by action, type, state, workflow_map.
AC3 — HTTP handler: correct HTTP responses for valid/invalid requests.
AC4 — run_harness: subprocess is spawned with correct arguments.
AC5 — config_from_env: reads environment variables; exits on missing secret.
AC6 — build_server: constructs a bound HTTPServer; serve_forever contract.
"""

from __future__ import annotations

import dataclasses
import hashlib
import hmac
import http.client
import json
import threading
from typing import Any
from unittest.mock import patch

import pytest

# ---------------------------------------------------------------------------
# Import guard — skip the whole module if intake isn't on sys.path yet.
# This makes the test file discoverable even before implementation lands.
# ---------------------------------------------------------------------------

pytest.importorskip(
    "intake.linear_webhook",
    reason="intake.linear_webhook not importable — check pythonpath in pyproject.toml",
)

from intake.linear_webhook import (  # noqa: E402,I001
    WebhookConfig,
    build_server,
    config_from_env,
    make_handler,
    route_event,
    run_harness,
    verify_signature,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_sig(body: bytes, secret: str) -> str:
    """Compute the expected Linear HMAC-SHA256 hex digest."""
    return hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def _default_config(**overrides: Any) -> WebhookConfig:
    """WebhookConfig with a test secret, overridable per test."""
    kwargs: dict[str, Any] = {"secret": "test-secret"}
    kwargs.update(overrides)
    return WebhookConfig(**kwargs)


def _issue_payload(
    *,
    action: str = "create",
    identifier: str = "CAL-1",
    state_name: str = "Backlog",
) -> dict[str, Any]:
    """Minimal Linear Issue webhook payload."""
    return {
        "type": "Issue",
        "action": action,
        "data": {
            "identifier": identifier,
            "state": {"name": state_name},
        },
    }


# ---------------------------------------------------------------------------
# AC1 — verify_signature
# ---------------------------------------------------------------------------


class TestVerifySignature:
    def test_valid_signature_returns_true(self) -> None:
        body = b'{"type":"Issue"}'
        sig = _make_sig(body, "my-secret")
        assert verify_signature(body, "my-secret", sig) is True

    def test_wrong_secret_returns_false(self) -> None:
        body = b'{"type":"Issue"}'
        sig = _make_sig(body, "real-secret")
        assert verify_signature(body, "wrong-secret", sig) is False

    def test_tampered_body_returns_false(self) -> None:
        body = b'{"type":"Issue"}'
        sig = _make_sig(body, "my-secret")
        tampered = body + b"extra"
        assert verify_signature(tampered, "my-secret", sig) is False

    def test_empty_signature_returns_false(self) -> None:
        body = b'{"type":"Issue"}'
        assert verify_signature(body, "my-secret", "") is False

    def test_uppercase_hex_signature_accepted(self) -> None:
        """Linear may send uppercase hex; verification must be case-insensitive."""
        body = b'{"type":"Issue"}'
        sig = _make_sig(body, "my-secret").upper()
        assert verify_signature(body, "my-secret", sig) is True

    def test_empty_body_valid_signature(self) -> None:
        body = b""
        sig = _make_sig(body, "my-secret")
        assert verify_signature(body, "my-secret", sig) is True


# ---------------------------------------------------------------------------
# AC2 — route_event
# ---------------------------------------------------------------------------


class TestRouteEvent:
    def test_issue_create_returns_default_workflow(self) -> None:
        config = _default_config(workflow="build")
        payload = _issue_payload(action="create", identifier="CAL-5")
        result = route_event(payload, config)
        assert result == ("build", "CAL-5")

    def test_non_issue_type_ignored(self) -> None:
        config = _default_config()
        payload = {"type": "Comment", "action": "create", "data": {"identifier": "CAL-5"}}
        assert route_event(payload, config) is None

    def test_remove_action_ignored(self) -> None:
        config = _default_config()
        payload = _issue_payload(action="remove", identifier="CAL-5")
        assert route_event(payload, config) is None

    def test_update_without_mapping_ignored(self) -> None:
        config = _default_config()
        payload = _issue_payload(action="update", identifier="CAL-5")
        assert route_event(payload, config) is None

    def test_missing_identifier_ignored(self) -> None:
        config = _default_config()
        payload = {"type": "Issue", "action": "create", "data": {}}
        assert route_event(payload, config) is None

    def test_missing_data_key_ignored(self) -> None:
        config = _default_config()
        payload = {"type": "Issue", "action": "create"}
        assert route_event(payload, config) is None

    def test_missing_type_ignored(self) -> None:
        config = _default_config()
        payload = {"action": "create", "data": {"identifier": "CAL-5"}}
        assert route_event(payload, config) is None

    def test_update_with_specific_state_mapping(self) -> None:
        config = _default_config(
            workflow_map={"update:In Progress": "build"},
        )
        payload = _issue_payload(action="update", identifier="CAL-7", state_name="In Progress")
        result = route_event(payload, config)
        assert result == ("build", "CAL-7")

    def test_update_with_wildcard_mapping(self) -> None:
        config = _default_config(workflow_map={"update:*": "triage"})
        payload = _issue_payload(action="update", identifier="CAL-8", state_name="Todo")
        result = route_event(payload, config)
        assert result == ("triage", "CAL-8")

    def test_specific_mapping_wins_over_wildcard(self) -> None:
        """Specific ``action:state`` key must beat wildcard ``action:*``."""
        config = _default_config(
            workflow_map={
                "create:Backlog": "triage",
                "create:*": "build",
            }
        )
        payload = _issue_payload(action="create", identifier="CAL-9", state_name="Backlog")
        result = route_event(payload, config)
        assert result == ("triage", "CAL-9")

    def test_create_wildcard_overrides_default(self) -> None:
        config = _default_config(
            workflow="build",
            workflow_map={"create:*": "custom"},
        )
        payload = _issue_payload(action="create", identifier="CAL-10")
        result = route_event(payload, config)
        assert result == ("custom", "CAL-10")

    def test_payload_with_null_state(self) -> None:
        """state can be null in the payload; routing still works."""
        config = _default_config()
        payload = {
            "type": "Issue",
            "action": "create",
            "data": {"identifier": "CAL-11", "state": None},
        }
        result = route_event(payload, config)
        assert result == ("build", "CAL-11")


# ---------------------------------------------------------------------------
# AC3 — HTTP handler
# ---------------------------------------------------------------------------


def _post_to_server(
    port: int,
    path: str,
    body: bytes,
    secret: str,
    *,
    sign: bool = True,
    extra_headers: dict[str, str] | None = None,
) -> int:
    """Send a POST to the local test server; return the status code."""
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    sig = _make_sig(body, secret) if sign else "invalid-sig"
    headers: dict[str, str] = {
        "content-type": "application/json",
        "content-length": str(len(body)),
        "linear-signature": sig,
    }
    if extra_headers:
        headers.update(extra_headers)
    conn.request("POST", path, body=body, headers=headers)
    resp = conn.getresponse()
    status = resp.status
    conn.close()
    return status


def _serve_one(server: Any) -> None:
    """Serve exactly one request in a thread."""
    server.handle_request()


class TestHttpHandler:
    """Integration-level tests using a real socket server on a random port."""

    def _start(self, config: WebhookConfig) -> Any:
        """Build a server on port 0 (OS assigns) and return it."""
        return build_server("127.0.0.1", 0, config)

    def test_valid_create_event_returns_200(self) -> None:
        config = _default_config()
        server = self._start(config)
        port = server.server_address[1]

        body = json.dumps(_issue_payload()).encode()

        with patch("intake.linear_webhook.run_harness") as mock_run:
            thread = threading.Thread(target=_serve_one, args=(server,))
            thread.start()
            status = _post_to_server(port, "/webhook", body, config.secret)
            thread.join(timeout=5)

        server.server_close()
        assert status == 200
        mock_run.assert_called_once_with("CAL-1", "build", config)

    def test_invalid_signature_returns_401(self) -> None:
        config = _default_config()
        server = self._start(config)
        port = server.server_address[1]
        body = json.dumps(_issue_payload()).encode()

        thread = threading.Thread(target=_serve_one, args=(server,))
        thread.start()
        status = _post_to_server(port, "/webhook", body, config.secret, sign=False)
        thread.join(timeout=5)

        server.server_close()
        assert status == 401

    def test_invalid_json_returns_400(self) -> None:
        config = _default_config()
        server = self._start(config)
        port = server.server_address[1]
        body = b"not-json"
        sig = _make_sig(body, config.secret)

        thread = threading.Thread(target=_serve_one, args=(server,))
        thread.start()

        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        conn.request(
            "POST",
            "/webhook",
            body=body,
            headers={
                "content-type": "text/plain",
                "content-length": str(len(body)),
                "linear-signature": sig,
            },
        )
        resp = conn.getresponse()
        status = resp.status
        conn.close()
        thread.join(timeout=5)

        server.server_close()
        assert status == 400

    def test_unknown_path_returns_404(self) -> None:
        config = _default_config()
        server = self._start(config)
        port = server.server_address[1]
        body = b"{}"

        thread = threading.Thread(target=_serve_one, args=(server,))
        thread.start()
        status = _post_to_server(port, "/other", body, config.secret)
        thread.join(timeout=5)

        server.server_close()
        assert status == 404

    def test_ignored_event_still_returns_200(self) -> None:
        """Non-Issue events must return 200 (webhook acknowledged, not acted on)."""
        config = _default_config()
        server = self._start(config)
        port = server.server_address[1]

        payload = {"type": "Comment", "action": "create", "data": {"identifier": "CAL-1"}}
        body = json.dumps(payload).encode()

        with patch("intake.linear_webhook.run_harness") as mock_run:
            thread = threading.Thread(target=_serve_one, args=(server,))
            thread.start()
            status = _post_to_server(port, "/webhook", body, config.secret)
            thread.join(timeout=5)

        server.server_close()
        assert status == 200
        mock_run.assert_not_called()

    def test_trailing_slash_path_accepted(self) -> None:
        """/webhook/ (trailing slash) must also return 200."""
        config = _default_config()
        server = self._start(config)
        port = server.server_address[1]

        body = json.dumps(_issue_payload()).encode()

        with patch("intake.linear_webhook.run_harness"):
            thread = threading.Thread(target=_serve_one, args=(server,))
            thread.start()
            status = _post_to_server(port, "/webhook/", body, config.secret)
            thread.join(timeout=5)

        server.server_close()
        assert status == 200


# ---------------------------------------------------------------------------
# AC4 — run_harness
# ---------------------------------------------------------------------------


class TestRunHarness:
    def test_spawns_correct_command(self) -> None:
        config = _default_config(harness_bin="harness", workflow="build", base_branch="staging")

        with patch("intake.linear_webhook.subprocess") as mock_subproc:
            run_harness("CAL-99", "build", config)

        mock_subproc.Popen.assert_called_once_with(
            ["harness", "run", "build", "--linear=CAL-99", "--base=staging"],
            start_new_session=True,
            stdin=mock_subproc.DEVNULL,
            stdout=mock_subproc.DEVNULL,
            stderr=mock_subproc.DEVNULL,
        )

    def test_custom_harness_bin(self) -> None:
        config = _default_config(harness_bin="/usr/local/bin/harness")

        with patch("intake.linear_webhook.subprocess") as mock_subproc:
            run_harness("CAL-5", "build", config)

        cmd = mock_subproc.Popen.call_args[0][0]
        assert cmd[0] == "/usr/local/bin/harness"

    def test_oserror_logged_not_raised(self) -> None:
        """OSError from Popen must be caught and logged; server must not crash."""
        config = _default_config()

        with patch("intake.linear_webhook.subprocess.Popen", side_effect=OSError("not found")):
            # Should not raise.
            run_harness("CAL-1", "build", config)


# ---------------------------------------------------------------------------
# AC5 — config_from_env
# ---------------------------------------------------------------------------


class TestConfigFromEnv:
    def test_reads_secret(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("LINEAR_WEBHOOK_SECRET", "env-secret")
        monkeypatch.delenv("HARNESS_BIN", raising=False)
        monkeypatch.delenv("HARNESS_WORKFLOW", raising=False)
        monkeypatch.delenv("HARNESS_BASE_BRANCH", raising=False)
        monkeypatch.delenv("HARNESS_WORKFLOW_MAP", raising=False)

        config = config_from_env()

        assert config.secret == "env-secret"
        assert config.harness_bin == "harness"
        assert config.workflow == "build"
        assert config.base_branch == "main"
        assert config.workflow_map == {}

    def test_reads_all_env_vars(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("LINEAR_WEBHOOK_SECRET", "s3cr3t")
        monkeypatch.setenv("HARNESS_BIN", "/usr/bin/harness")
        monkeypatch.setenv("HARNESS_WORKFLOW", "bugfix")
        monkeypatch.setenv("HARNESS_BASE_BRANCH", "staging")
        monkeypatch.setenv("HARNESS_WORKFLOW_MAP", '{"create:*": "triage"}')

        config = config_from_env()

        assert config.secret == "s3cr3t"
        assert config.harness_bin == "/usr/bin/harness"
        assert config.workflow == "bugfix"
        assert config.base_branch == "staging"
        assert config.workflow_map == {"create:*": "triage"}

    def test_exits_when_secret_missing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("LINEAR_WEBHOOK_SECRET", raising=False)

        with pytest.raises(SystemExit) as exc_info:
            config_from_env()

        assert exc_info.value.code == 1

    def test_exits_on_invalid_workflow_map_json(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("LINEAR_WEBHOOK_SECRET", "s3cr3t")
        monkeypatch.setenv("HARNESS_WORKFLOW_MAP", "not-json")

        with pytest.raises(SystemExit) as exc_info:
            config_from_env()

        assert exc_info.value.code == 1


# ---------------------------------------------------------------------------
# AC6 — build_server / WebhookConfig
# ---------------------------------------------------------------------------


class TestBuildServer:
    def test_returns_bound_http_server(self) -> None:
        import http.server

        config = _default_config()
        server = build_server("127.0.0.1", 0, config)
        try:
            assert isinstance(server, http.server.HTTPServer)
            host, port = server.server_address
            assert host == "127.0.0.1"
            assert port > 0
        finally:
            server.server_close()

    def test_each_call_creates_independent_handler(self) -> None:
        """Two servers must not share handler state."""
        config_a = _default_config(secret="secret-a")
        config_b = _default_config(secret="secret-b")

        server_a = build_server("127.0.0.1", 0, config_a)
        server_b = build_server("127.0.0.1", 0, config_b)
        try:
            handler_a = make_handler(config_a)
            handler_b = make_handler(config_b)
            # Handlers are independent types (different classes from make_handler).
            assert handler_a is not handler_b
        finally:
            server_a.server_close()
            server_b.server_close()


class TestWebhookConfig:
    def test_defaults(self) -> None:
        config = WebhookConfig(secret="x")
        assert config.harness_bin == "harness"
        assert config.workflow == "build"
        assert config.base_branch == "main"
        assert config.workflow_map == {}

    def test_frozen(self) -> None:
        config = WebhookConfig(secret="x")
        with pytest.raises(dataclasses.FrozenInstanceError):
            config.secret = "y"  # type: ignore[misc]
