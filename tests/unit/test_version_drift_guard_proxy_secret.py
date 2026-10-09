"""A failed read through a declared proxy never echoes the proxy URL (#767).

A proxy URL can carry credentials (``http://user:secret@host:port``), and the
hook writes its fail-open line to stderr, which a host may log. Admitted under
ADR 0017 D5 class (a): it runs the hook as a node subprocess.
"""

from __future__ import annotations

import socket
from pathlib import Path

from tests.unit.test_version_drift_guard_hook import (
    UNRESOLVABLE_URL,
    _assert_quiet,
    _plugin_root,
    _run,
)

SECRET = "s3cr3t-proxy-pass"


def test_a_failed_proxied_read_names_no_proxy_credential(tmp_path: Path) -> None:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    proc, _ = _run(
        _plugin_root(tmp_path, "1.0.0"),
        UNRESOLVABLE_URL,
        env={"http_proxy": f"http://operator:{SECRET}@127.0.0.1:{port}"},
    )
    _assert_quiet(proc)
    assert "VERSION-DRIFT-GUARD" in proc.stderr, "the control: a failed read is reported"
    assert SECRET not in proc.stderr + proc.stdout, proc.stderr
