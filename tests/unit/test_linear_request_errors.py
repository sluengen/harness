"""Transport-boundary tests for ``LinearClient._request`` (CAL-1005).

Every other Linear test mocks at the ``_request`` seam, so the error-conversion
layer *inside* ``_request_sync`` — HTTP errors, GraphQL ``errors`` payloads, and
non-JSON bodies — had no coverage. These tests mock one level lower, at
``urllib.request.urlopen``, so the real conversion code runs: whatever the
transport throws or returns must surface as a :class:`LinearRequestError` and
never leak a raw ``HTTPError`` / ``JSONDecodeError`` past the Linear boundary.
"""

from __future__ import annotations

import io
import json
import urllib.error
import urllib.request
from typing import Any

import pytest

from harness.linear import LinearClient, LinearRequestError


class _FakeResponse:
    """Minimal context-manager stand-in for ``urlopen``'s return value."""

    def __init__(self, raw: bytes) -> None:
        self._raw = raw

    def __enter__(self) -> _FakeResponse:
        return self

    def __exit__(self, *exc: object) -> bool:
        return False

    def read(self) -> bytes:
        return self._raw


async def test_request_http_error_becomes_linear_request_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An ``HTTPError`` (with a server error body) surfaces as a
    ``LinearRequestError`` carrying the status code — the raw urllib error never
    escapes the boundary."""

    def fake_urlopen(req: Any, timeout: float | None = None) -> Any:  # noqa: ARG001
        raise urllib.error.HTTPError(
            url="https://api.linear.app/graphql",
            code=400,
            msg="Bad Request",
            hdrs=None,  # type: ignore[arg-type]
            fp=io.BytesIO(b'{"errors":[{"message":"invalid field"}]}'),
        )

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    client = LinearClient(api_key="fake-key")
    with pytest.raises(LinearRequestError, match="HTTP 400"):
        await client._request("query { viewer { id } }", {})


async def test_request_graphql_errors_payload_joined_into_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A 200 response whose body carries a GraphQL ``errors`` array raises
    ``LinearRequestError`` with the individual messages joined."""
    raw = json.dumps(
        {"errors": [{"message": "boom"}, {"message": "kaput"}]}
    ).encode()

    monkeypatch.setattr(
        urllib.request, "urlopen", lambda req, timeout=None: _FakeResponse(raw)  # noqa: ARG005
    )
    client = LinearClient(api_key="fake-key")
    with pytest.raises(LinearRequestError, match="boom; kaput"):
        await client._request("query { viewer { id } }", {})


async def test_request_malformed_json_becomes_linear_request_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A non-JSON body (e.g. an HTML gateway page) raises ``LinearRequestError``
    rather than leaking a bare ``JSONDecodeError``."""

    monkeypatch.setattr(
        urllib.request,
        "urlopen",
        lambda req, timeout=None: _FakeResponse(b"<html>504 Gateway Timeout</html>"),  # noqa: ARG005
    )
    client = LinearClient(api_key="fake-key")
    with pytest.raises(LinearRequestError, match="non-JSON"):
        await client._request("query { viewer { id } }", {})
