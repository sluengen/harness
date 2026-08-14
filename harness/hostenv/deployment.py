"""How the ``harness`` client on ``PATH`` was deployed (#312).

This classification used to be ``_wrapper_status()`` in
``docker/harness-wrapper.sh``. AC-4 is satisfied as **preserved**, not retired:
the same environment variable, the same four verdicts and the same ``doctor``
mapping survive unchanged — a fifth, ``image``, joins them for the deployment
#312 adds. Two reasons for the relocation, recorded here rather than left to be
inferred from a diff:

1. The shim sits on a line-count ratchet (``EXECUTABLE_LINE_CEILING``) with no
   headroom, and that ratchet's own written remedy is that logic belongs in
   ``harness.hostenv``, which is tested. Moving fourteen lines of branching out
   is what pays for the stamp the same ticket adds.
2. A bash branch is the one kind of branch in this repo that no unit test can
   reach directly. Every verdict below now has one, and the four end-to-end tests
   that execute the real shim keep proving the *whole* path still agrees.

**Why the ``image`` verdict is checked first.** An image-installed client sitting
inside a checkout is a plain file whose bytes differ from the versioned shim — it
carries the install preamble. Any branch reached before the stamp therefore calls
it ``drifted`` and ``doctor`` FAILs a correct install. The ordering is load-bearing
and is pinned by ``test_the_image_verdict_precedes_the_content_comparison``.

Stdlib only — see the package docstring.
"""

from __future__ import annotations

import filecmp
from dataclasses import dataclass
from pathlib import Path

__all__ = ["DEPLOYMENT_STATUSES", "Deployment", "classify"]

#: Every verdict :func:`classify` can produce. Deliberately **not** in precedence
#: order — ``detached`` is decided before ``symlink`` and this tuple ends with it —
#: because the order that matters is the one written in :func:`classify` and a
#: second, differently-ordered statement of it would be a claim nothing checks.
#: ``doctor`` maps each member; ``tests/unit/test_client_deployment.py``
#: parametrises over this tuple so a sixth verdict cannot arrive without a report.
DEPLOYMENT_STATUSES = ("image", "symlink", "copy", "drifted", "detached")

#: Where a checkout keeps the one versioned shim. The client compares against
#: this path, never against a second, image-only copy: two shim sources would be
#: two postures, which is the drift CAL-1123 named.
VERSIONED_SHIM = Path("docker") / "harness-wrapper.sh"


@dataclass(frozen=True)
class Deployment:
    """How the client on ``PATH`` got there, and which version it is.

    ``status`` is one of :data:`DEPLOYMENT_STATUSES`, or ``""`` when nothing
    mediated the invocation — a native install, or a pre-#312 shim that reports
    its own verdict instead. ``version`` is the install stamp, or ``""`` for a
    deployment that has none: a symlink's version follows the checkout, and
    saying so is more honest than synthesising a plausible number.
    """

    status: str
    version: str


def classify(*, client_path: str, source_root: str, client_version: str) -> Deployment:
    """Classify the client at ``client_path`` against the checkout at ``source_root``.

    All three inputs are strings straight out of the environment the shim
    exported, so an absent one is ``""`` rather than ``None``.
    """
    if client_version:
        return Deployment(status="image", version=client_version)
    if not client_path:
        return Deployment(status="", version="")

    versioned = Path(source_root) / VERSIONED_SHIM if source_root else None
    if versioned is None or not versioned.is_file():
        return Deployment(status="detached", version="")

    client = Path(client_path)
    if client.is_symlink():
        return Deployment(status="symlink", version="")
    if _same_bytes(client, versioned):
        return Deployment(status="copy", version="")
    return Deployment(status="drifted", version="")


def _same_bytes(left: Path, right: Path) -> bool:
    """``cmp -s``, which is what the shim used. ``shallow=False`` because the
    question is whether the copy has fallen behind its source — and size-and-mtime
    equality is exactly the comparison that answers that wrong."""
    try:
        return filecmp.cmp(left, right, shallow=False)
    except OSError:
        # An unreadable or vanished client cannot be shown identical, and the
        # honest verdict for "it does not match the versioned source" is the one
        # that tells the operator to re-install.
        return False
