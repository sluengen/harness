"""intake/linear_webhook.py — Linear webhook intake (sibling process).

Listens for incoming Linear webhook POST requests, validates the HMAC-SHA256
signature, and shells out to ``harness run <workflow> --linear=<id>`` on
matching issue events.

This is a **sibling process** to the harness (SPEC §2, §17.4): it lives
outside the ``harness`` Python package and invokes the harness via its CLI,
keeping the harness boundary clean.

Usage::

    LINEAR_WEBHOOK_SECRET=<secret> python -m intake.linear_webhook

Environment variables:
    LINEAR_WEBHOOK_SECRET    Required. Webhook secret from Linear settings.
    HARNESS_BIN              Path to the harness binary (default: ``harness``).
    HARNESS_WORKFLOW         Workflow name to run on issue create (default: ``build``).
    HARNESS_BASE_BRANCH      Base branch for ``harness run --base`` (default: ``main``).
    HARNESS_WORKFLOW_MAP     JSON object mapping ``"<action>:<state>"`` → workflow name.
                             Example: ``'{"update:In Progress": "build"}'``

Exit codes:
    0   Server stopped cleanly (SIGINT).
    1   Configuration error (missing ``LINEAR_WEBHOOK_SECRET`` or bad JSON map).
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import hmac
import http.server
import json
import logging
import os
import sqlite3
import subprocess
import sys
from dataclasses import dataclass, field
from typing import Any

__all__ = [
    "WebhookConfig",
    "verify_signature",
    "route_event",
    "run_harness",
    "reconcile_event",
    "find_active_runs_for_linear_id",
    "cancel_run",
    "make_handler",
    "build_server",
    "config_from_env",
    "main",
]

_LOG = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class WebhookConfig:
    """Immutable runtime configuration for the webhook server.

    All values are fixed at construction time; the handler captures a
    reference to one instance for the lifetime of the server.
    """

    secret: str
    """Linear webhook signing secret (HMAC-SHA256 key)."""

    harness_bin: str = "harness"
    """Path or name of the ``harness`` binary (resolved via PATH if bare name)."""

    workflow: str = "build"
    """Default workflow to fire on ``Issue.create`` events."""

    base_branch: str = "main"
    """Value passed as ``--base`` to every ``harness run`` call."""

    workflow_map: dict[str, str] = field(default_factory=dict)
    """Optional override mapping ``"<action>:<state_name>"`` → workflow name.

    Keys: ``"create:<state_name>"``, ``"update:<state_name>"``, or
    ``"create:*"`` / ``"update:*"`` as a wildcard for any state.
    Specific key wins over wildcard; wildcard wins over ``workflow`` default.

    Example::

        {"update:In Progress": "build", "create:*": "triage"}
    """

    db_path: str = ".harness/harness.db"
    """Path to the harness SQLite database file (for reconciliation queries)."""

    active_states: frozenset[str] = frozenset({"Backlog", "Todo", "In Progress", "In Review"})
    """Linear state names that indicate a ticket is actively being worked on.

    Reconciliation only triggers when a ticket moves to a state NOT in this set.
    Frozenset is immutable so the default is safe on a frozen dataclass.
    """


# ---------------------------------------------------------------------------
# Core logic (pure functions — easy to test in isolation)
# ---------------------------------------------------------------------------


def verify_signature(body: bytes, secret: str, received: str) -> bool:
    """Return ``True`` iff the Linear HMAC-SHA256 signature is valid.

    Linear computes the signature as::

        HMAC-SHA256(key=<webhook_secret>, msg=<raw_request_body>)

    and sends it hex-encoded in the ``linear-signature`` request header.
    Uses :func:`hmac.compare_digest` to prevent timing attacks.

    Args:
        body: Raw (undecoded) request body bytes.
        secret: The webhook secret configured in Linear.
        received: The value of the ``linear-signature`` header.

    Returns:
        ``True`` if the computed digest matches ``received`` (case-insensitive).
        ``False`` when ``received`` is empty or the digests differ.
    """
    if not received:
        return False
    expected = hmac.new(
        secret.encode("utf-8"),
        body,
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(expected, received.lower())


def route_event(
    payload: dict[str, Any],
    config: WebhookConfig,
) -> tuple[str, str] | None:
    """Map a Linear webhook payload to ``(workflow, linear_identifier)``.

    Routing rules (evaluated in order of precedence):

    1. ``workflow_map["<action>:<state_name>"]`` — specific action + state.
    2. ``workflow_map["<action>:*"]`` — wildcard for any state of that action.
    3. Default ``config.workflow`` for ``create`` events (no mapping needed).
    4. ``None`` — event is ignored (non-Issue type, ``remove`` action, ``update``
       events not in ``workflow_map``, missing ``identifier``).

    Args:
        payload: Parsed JSON from the Linear webhook request body.
        config: Server configuration (workflow defaults + map).

    Returns:
        ``(workflow_name, linear_identifier)`` or ``None`` if the event
        should not trigger a run.
    """
    if payload.get("type") != "Issue":
        return None

    action = payload.get("action", "")
    if action not in ("create", "update"):
        return None

    data: dict[str, Any] = payload.get("data") or {}
    identifier: str = data.get("identifier", "")
    if not identifier:
        return None

    state_obj: dict[str, Any] = data.get("state") or {}
    state_name: str = state_obj.get("name", "")

    # Consult workflow_map: specific key first, then wildcard.
    for key in (f"{action}:{state_name}", f"{action}:*"):
        if key in config.workflow_map:
            return (config.workflow_map[key], identifier)

    # Default: fire config.workflow on create events only.
    if action == "create":
        return (config.workflow, identifier)

    return None


def run_harness(identifier: str, workflow: str, config: WebhookConfig) -> None:
    """Spawn ``harness run <workflow> --linear=<identifier> --base=<branch>``.

    Uses :func:`subprocess.Popen` with ``start_new_session=True`` so the
    child process is decoupled from the server's process group. The server
    does **not** wait for the child to complete — it returns immediately after
    spawning and the child runs independently.

    All child file descriptors (stdin, stdout, stderr) are redirected to
    ``/dev/null`` so the detached process cannot inherit the server's
    terminal or block on I/O.

    OSError (e.g. harness binary not found) is caught and logged rather than
    crashing the server — individual event failures must not take down the
    intake process.

    Args:
        identifier: Linear issue identifier (e.g. ``"CAL-301"``).
        workflow: Workflow name to run (e.g. ``"build"``).
        config: Server config supplying ``harness_bin`` and ``base_branch``.
    """
    cmd = [
        config.harness_bin,
        "run",
        workflow,
        f"--linear={identifier}",
        f"--base={config.base_branch}",
    ]
    _LOG.info("spawning: %s", " ".join(cmd))
    try:
        subprocess.Popen(
            cmd,
            start_new_session=True,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except OSError as exc:
        _LOG.error("failed to spawn harness for %s: %s", identifier, exc)


# ---------------------------------------------------------------------------
# Reconciliation (symphony-pattern: cancel runs when ticket leaves active state)
# ---------------------------------------------------------------------------


def reconcile_event(
    payload: dict[str, Any],
    config: WebhookConfig,
) -> str | None:
    """Return the Linear identifier when a ticket leaves an active state.

    Reconciliation applies only to ``Issue`` ``update`` events where the new
    state is not in ``config.active_states``.  All other events return ``None``
    so the caller knows no cancellation is needed.

    Args:
        payload: Parsed JSON from the Linear webhook request body.
        config: Server configuration supplying ``active_states``.

    Returns:
        The Linear identifier (e.g. ``"CAL-302"``) if cancellation is needed,
        or ``None`` if the event should not trigger reconciliation.
    """
    if payload.get("type") != "Issue":
        return None
    if payload.get("action") != "update":
        return None

    data: dict[str, Any] = payload.get("data") or {}
    identifier: str = data.get("identifier", "")
    if not identifier:
        return None

    state_obj: dict[str, Any] = data.get("state") or {}
    state_name: str = state_obj.get("name", "")
    if not state_name:
        return None

    if state_name in config.active_states:
        return None

    return identifier


def find_active_runs_for_linear_id(identifier: str, db_path: str) -> list[str]:
    """Return run_ids of ``running``/``pending`` runs for a Linear identifier.

    Queries the harness SQLite database using ``json_extract`` to match the
    ``$.linear`` field in ``inputs_json``.

    Returns ``[]`` when the database file does not exist or on any
    ``sqlite3.OperationalError`` (e.g. missing table).

    Args:
        identifier: Linear issue identifier (e.g. ``"CAL-302"``).
        db_path: Path to the harness SQLite database file.

    Returns:
        List of ``run_id`` strings for active runs, or ``[]``.
    """
    import os as _os

    if not _os.path.exists(db_path):
        return []

    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.execute(
            "SELECT run_id FROM runs"
            " WHERE status IN ('running', 'pending')"
            " AND json_extract(inputs_json, '$.linear') = ?",
            (identifier,),
        )
        rows = cursor.fetchall()
        conn.close()
        return [str(row[0]) for row in rows]
    except sqlite3.OperationalError as exc:
        _LOG.warning("find_active_runs_for_linear_id: db error for %s: %s", identifier, exc)
        return []


def cancel_run(run_id: str, db_path: str) -> None:
    """Mark a harness run as ``cancelled`` in the database.

    Only updates runs whose current ``status`` is ``running`` or ``pending``,
    so already-terminal runs (completed, failed, cancelled) are not touched.
    Also stamps ``completed_at`` with the current UTC timestamp.

    Does nothing (no raise) when the database file does not exist.
    Catches ``sqlite3.OperationalError`` — logs and swallows so a DB schema
    mismatch cannot crash the intake server.

    Args:
        run_id: The ``run_id`` to cancel.
        db_path: Path to the harness SQLite database file.
    """
    import os as _os

    if not _os.path.exists(db_path):
        return

    completed_at = _dt.datetime.now(_dt.UTC).isoformat()
    try:
        conn = sqlite3.connect(db_path)
        conn.execute(
            "UPDATE runs SET status = 'cancelled', completed_at = ?"
            " WHERE run_id = ? AND status IN ('running', 'pending')",
            (completed_at, run_id),
        )
        conn.commit()
        conn.close()
        _LOG.info("cancelled run %s", run_id)
    except sqlite3.OperationalError as exc:
        _LOG.error("cancel_run: db error for %s: %s", run_id, exc)


# ---------------------------------------------------------------------------
# HTTP server
# ---------------------------------------------------------------------------


def make_handler(config: WebhookConfig) -> type[http.server.BaseHTTPRequestHandler]:
    """Return a ``BaseHTTPRequestHandler`` subclass bound to ``config``.

    Creates a fresh class per call so multiple server instances (e.g., in
    tests) hold independent configs without class-level state leaking between
    them.

    Args:
        config: Webhook configuration forwarded into the handler's closure.

    Returns:
        A new class that handles POST ``/webhook`` and ``/webhook/``.
    """

    class _LinearHandler(http.server.BaseHTTPRequestHandler):
        """Handle POST /webhook — rejects every other path or method."""

        def do_POST(self) -> None:  # noqa: N802
            if self.path not in ("/webhook", "/webhook/"):
                self._respond(404)
                return

            raw_len = int(self.headers.get("content-length", 0))
            body = self.rfile.read(raw_len)

            sig = self.headers.get("linear-signature", "")
            if not verify_signature(body, config.secret, sig):
                _LOG.warning("rejected webhook: invalid signature")
                self._respond(401)
                return

            try:
                payload: dict[str, Any] = json.loads(body)
            except json.JSONDecodeError:
                _LOG.warning("rejected webhook: body is not valid JSON")
                self._respond(400)
                return

            result = route_event(payload, config)
            if result is not None:
                workflow, identifier = result
                run_harness(identifier, workflow, config)

            reconcile_id = reconcile_event(payload, config)
            if reconcile_id is not None:
                _LOG.info("reconciling runs for %s", reconcile_id)
                for run_id in find_active_runs_for_linear_id(reconcile_id, config.db_path):
                    cancel_run(run_id, config.db_path)

            self._respond(200)

        def _respond(self, code: int) -> None:
            self.send_response(code)
            self.end_headers()

        def log_message(self, fmt: str, *args: Any) -> None:
            _LOG.debug(fmt, *args)

    return _LinearHandler


def build_server(
    host: str,
    port: int,
    config: WebhookConfig,
) -> http.server.HTTPServer:
    """Construct and bind an :class:`http.server.HTTPServer`.

    Args:
        host: Interface to bind (e.g., ``"0.0.0.0"`` or ``"127.0.0.1"``).
        port: TCP port to listen on. Pass ``0`` to let the OS assign a free port.
        config: Webhook configuration forwarded to :func:`make_handler`.

    Returns:
        A bound (but not yet serving) :class:`http.server.HTTPServer`.
    """
    return http.server.HTTPServer((host, port), make_handler(config))


# ---------------------------------------------------------------------------
# Environment-driven configuration
# ---------------------------------------------------------------------------


def config_from_env() -> WebhookConfig:
    """Build a :class:`WebhookConfig` from environment variables.

    Required:
        ``LINEAR_WEBHOOK_SECRET`` — the webhook signing secret.

    Optional:
        ``HARNESS_BIN``, ``HARNESS_WORKFLOW``, ``HARNESS_BASE_BRANCH``,
        ``HARNESS_WORKFLOW_MAP`` (JSON string),
        ``HARNESS_DB_PATH``,
        ``HARNESS_ACTIVE_STATES`` (JSON array of strings).

    Raises:
        SystemExit(1): when ``LINEAR_WEBHOOK_SECRET`` is unset, when
            ``HARNESS_WORKFLOW_MAP`` contains invalid JSON, or when
            ``HARNESS_ACTIVE_STATES`` contains invalid JSON or is not an array.
    """
    secret = os.environ.get("LINEAR_WEBHOOK_SECRET", "")
    if not secret:
        print(
            "error: LINEAR_WEBHOOK_SECRET environment variable is required",
            file=sys.stderr,
        )
        sys.exit(1)

    workflow_map: dict[str, str] = {}
    raw_map = os.environ.get("HARNESS_WORKFLOW_MAP", "")
    if raw_map:
        try:
            workflow_map = json.loads(raw_map)
        except json.JSONDecodeError:
            print(
                "error: HARNESS_WORKFLOW_MAP is not valid JSON",
                file=sys.stderr,
            )
            sys.exit(1)

    active_states: frozenset[str] = frozenset({"Backlog", "Todo", "In Progress", "In Review"})
    raw_states = os.environ.get("HARNESS_ACTIVE_STATES", "")
    if raw_states:
        try:
            parsed = json.loads(raw_states)
        except json.JSONDecodeError:
            print(
                "error: HARNESS_ACTIVE_STATES is not valid JSON",
                file=sys.stderr,
            )
            sys.exit(1)
        if not isinstance(parsed, list):
            print(
                "error: HARNESS_ACTIVE_STATES must be a JSON array",
                file=sys.stderr,
            )
            sys.exit(1)
        active_states = frozenset(parsed)

    return WebhookConfig(
        secret=secret,
        harness_bin=os.environ.get("HARNESS_BIN", "harness"),
        workflow=os.environ.get("HARNESS_WORKFLOW", "build"),
        base_branch=os.environ.get("HARNESS_BASE_BRANCH", "main"),
        workflow_map=workflow_map,
        db_path=os.environ.get("HARNESS_DB_PATH", ".harness/harness.db"),
        active_states=active_states,
    )


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    """CLI entry point for ``python -m intake.linear_webhook``.

    Args:
        argv: Argument list (defaults to ``sys.argv[1:]``).

    Returns:
        Exit code: ``0`` on clean shutdown, ``1`` on configuration error.
    """
    import argparse

    parser = argparse.ArgumentParser(
        prog="python -m intake.linear_webhook",
        description=(
            "Linear webhook intake — fires ``harness run`` on ticket events. "
            "See SPEC §2 (external layer) for architectural context."
        ),
    )
    parser.add_argument(
        "--host",
        default="0.0.0.0",  # noqa: S104
        help="Host interface to bind (default: 0.0.0.0)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8765,
        help="TCP port to listen on (default: 8765)",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Logging verbosity (default: INFO)",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=args.log_level,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    config = config_from_env()

    server = build_server(args.host, args.port, config)
    _LOG.info("Linear webhook intake listening on %s:%d", args.host, args.port)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        _LOG.info("shutdown")

    return 0


if __name__ == "__main__":
    sys.exit(main())
