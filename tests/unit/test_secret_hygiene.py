"""Secret hygiene — no env / credential file is tracked, and it stays that way.

The repo is public (2026-07-06 open-sourcing decision). A tracked ``.env`` or
private-key file leaks a live secret to every reader *and* into permanent
history, where scrubbing it means a history rewrite. A full-history entropy
audit (``gitleaks`` v8.30.1, RUNBOOK "Pre-public secret audit") found zero
secrets and confirmed ``.env`` was never added; this guard keeps the tree clean
going forward by refusing any tracked env / credential file.

The guard is git-aware (``tracked_files_under``): it judges the **committed**
tree, so a local ``.env`` on an author's disk (correctly gitignored, untracked)
does not trip it — only a file that actually entered the index does. If a future
change genuinely needs to track something this pattern matches (an
``.env.example`` template is already excluded), widen ``_ALLOWED`` as a
conscious, reviewed decision rather than by loosening the pattern.
"""

from __future__ import annotations

import re
from pathlib import Path

from tests._gitutil import tracked_files_under

_REPO_ROOT = Path(__file__).resolve().parents[2]

# Files whose basename carries a live secret and must never be committed:
# dotenv files (any suffix), private keys, and key-bundle formats.
_SECRET_RE = re.compile(
    r"""(?ix)                       # case-insensitive, verbose
    (^\.env(\.|$)                   # .env, .env.local, .env.production, ...
     | \.pem$                       # PEM private keys / certs
     | \.p12$ | \.pfx$ | \.pkcs12$  # key bundles
     | \.key$ | \.keystore$         # raw keys / keystores
     | ^id_(rsa|dsa|ecdsa|ed25519)(\.|$)  # SSH private keys
    )""",
)

# Dotenv *templates* are conventionally committed and hold no real secret.
_ALLOWED = re.compile(r"(?i)^\.env\.(example|sample|template|dist)$")


def _is_secret_file(path: Path) -> bool:
    name = path.name
    if _ALLOWED.match(name):
        return False
    return _SECRET_RE.search(name) is not None


def test_no_env_or_secret_file_is_tracked() -> None:
    """No committed file is a dotenv / private-key / keystore file."""
    offenders = sorted(
        str(path.relative_to(_REPO_ROOT))
        for path in tracked_files_under(".")
        if _is_secret_file(path)
    )
    assert not offenders, (
        "Secret-bearing files are tracked and would leak on a public repo "
        f"(remove them from the index and from history if already pushed): {offenders}"
    )


def test_gitignore_ignores_env_files() -> None:
    """``.gitignore`` keeps dotenv files out of the index by default.

    Ignoring ``.env`` / ``.env.*`` is what makes the guard above hold in
    practice — a developer's local ``.env`` cannot be ``git add``-ed by accident
    (only a deliberate ``git add -f`` gets past it).
    """
    patterns = {
        line.strip()
        for line in (_REPO_ROOT / ".gitignore").read_text().splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }
    assert ".env" in patterns, ".gitignore must ignore .env"
    assert ".env.*" in patterns, ".gitignore must ignore .env.* variants"
