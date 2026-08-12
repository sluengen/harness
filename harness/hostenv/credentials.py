"""Credential value objects and the store parser shared by every host provider.

Two credentials cross the wrapper boundary: the **agent** credential (the Claude
OAuth token, whose *store* is platform-specific) and the **tracker** credential
(``LINEAR_API_KEY`` / ``GITHUB_TOKEN``, resolved identically everywhere).

Nothing here raises on bad input. Unusable stored content is *no credential*,
never a blank one: a blank credential does not fail where it is produced, it fails
much later as an in-container 401 that reads as a review failure (CAL-941).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

#: How close to expiry a token must be before the CLI's own refresh is triggered.
#: Five minutes, carried over from the wrapper's ``_now_ms + 300000``.
REFRESH_WINDOW_MS = 300_000

_DEFAULT_GIT_NAME = "Harness"
_DEFAULT_GIT_EMAIL = "harness@local"


@dataclass(frozen=True)
class AgentCredential:
    """A Claude OAuth access token and its expiry, in epoch milliseconds.

    ``token`` is non-empty by construction — :func:`parse_credential_store` returns
    ``None`` rather than an ``AgentCredential`` carrying a blank token.
    ``expires_at_ms`` is ``0`` when the store omits it, which reads as *stale* and
    so triggers a refresh rather than trusting an unknown expiry.

    ``token`` is kept **out of the repr** (#309). Until the broker existed this
    object lived for the duration of one ``spawn`` call; it now lives in a
    :class:`~harness.hostenv.broker.CredentialBroker` reachable from
    ``repr(vars(server))`` and from any traceback that renders host state. The
    repr is narrowed, not emptied — ``expires_at_ms`` is not a secret (it is
    forwarded to the container as ``CLAUDE_CODE_OAUTH_EXPIRES_AT``) and is the
    field an operator debugging a refusal actually needs.
    """

    token: str = field(repr=False)
    expires_at_ms: int

    def is_stale(self, now_ms: int, window_ms: int = REFRESH_WINDOW_MS) -> bool:
        """Is this token at or inside the refresh window?

        ``<=`` mirrors the wrapper's ``-le`` deliberately: a token expiring at
        exactly the window boundary is refreshed, not used.
        """
        return self.expires_at_ms <= now_ms + window_ms


def parse_credential_store(text: str) -> AgentCredential | None:
    """Parse a Claude credential store into a credential, or ``None``.

    One parser serves both providers — the macOS Keychain item and the Linux/WSL
    file store hold the same JSON document, so only the *retrieval* is
    platform-specific, not the format.
    """
    try:
        data = json.loads(text)
    except (ValueError, TypeError):
        return None
    if not isinstance(data, dict):
        return None

    block = data.get("claudeAiOauth")
    if not isinstance(block, dict):
        return None

    token = block.get("accessToken")
    if not isinstance(token, str) or not token:
        return None

    raw_expiry = block.get("expiresAt")
    if raw_expiry is None:
        expires_at_ms = 0
    elif isinstance(raw_expiry, bool):  # bool is an int subclass; not a timestamp
        return None
    elif isinstance(raw_expiry, (int, float)):
        expires_at_ms = int(raw_expiry)
    elif isinstance(raw_expiry, str):
        try:
            expires_at_ms = int(raw_expiry)
        except ValueError:
            return None
    else:
        return None

    return AgentCredential(token=token, expires_at_ms=expires_at_ms)


@dataclass(frozen=True)
class TrackerCredentials:
    """The tracker backends' credentials, plus where each came from.

    ``sources`` is **diagnostics only** — it names ``env`` / ``dotenv`` / ``gh`` so
    a confused operator can see which one won, and is never used to make a
    decision. Precedence is enforced by the resolution order, not by this field.
    """

    linear_api_key: str | None = None
    github_token: str | None = None
    sources: dict[str, str] = field(default_factory=dict)


def read_dotenv_value(path: Path, key: str) -> str | None:
    """Read one ``KEY=value`` from a ``.env`` file, or ``None`` if it is not there.

    A missing file, an unreadable file, or a file with no matching line all yield
    ``None`` — never an exception. That is issue #171's guarantee made structural:
    in the bash this replaced, the same property depended on a trailing ``|| true``
    on every grep, because a no-match ``grep`` exits 1 and ``set -euo pipefail``
    would abort the whole wrapper before the ``gh auth token`` fallback could run.
    A repo whose ``.env`` legitimately omits a key could then run no verb at all.

    The value is everything after the *first* ``=`` (so a value containing ``=``
    survives, matching ``cut -d= -f2-``) with carriage returns stripped, matching
    ``tr -d '\\r'``. Surrounding whitespace is deliberately **not** stripped — the
    bash did not strip it either, and doing so here would silently change what a
    credential resolves to.
    """
    pattern = re.compile(r"^(?:export[ \t]+)?" + re.escape(key) + r"=(.*)$")
    try:
        text = path.read_text()
    except OSError:
        return None

    for line in text.splitlines():
        match = pattern.match(line)
        if match:
            return match.group(1).replace("\r", "")
    return None
