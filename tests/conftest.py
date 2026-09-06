"""Suite-wide environment hygiene.

One fixture, for one reason. ``scripts/verify.sh``'s public path delegates to
``node scripts/gate-marker.js run``, which launches the declared gate with
``HARNESS_GATE_MARKER_RUNNER`` set on its environment — and pytest is a
grandchild of that launch, so every process this suite spawns inherits the
variable when the suite is run by the gate and does not when it is run by hand.
Since #559 the value is the identity of the repository being gated rather than
a bare ``1``, which is what lets the runner tell a genuine re-entry from a gate
that legitimately runs the runner against some *other* repository.

That difference used to be invisible. Since #510 the runner reads its own
variable and refuses to re-enter itself: a declared gate that calls ``run``
again would re-run the gate at every level and let an inner level mint a marker
for a tree whose outer stages are still running. Every test that drives ``run``
as a **public entry** was such a caller, so under the gate they were refused with
exit 3 while passing under a bare ``pytest``: 57 tests, across the marker,
contract, push-guard, Stop-hook and mutation-lock modules, measured on the run
that landed the refusal.

Since #559 the refusal is narrower than the fixture that answers it. These tests
drive ``run`` against throwaway ``tmp_path`` repositories, whose identity is not
the identity a gate run would have put on the environment, so the guard no longer
refuses them. Measured when that guard landed, by neutering this fixture and
running the suite with the variable inherited: it passed unchanged, so the drop
is no longer what keeps the suite green.

It is retained on the narrower claim it can still make — the suite means the
same thing however it is launched — and kept rather than deleted because the
property it protects is one a future test could quietly need: a case that drove
``run`` against *this* repository would be the same-identity case, and would be
refused.

The variable is therefore dropped once, here, rather than scrubbed at each of
the subprocess environments that would otherwise have to remember. A test that
needs the internal-mode variable sets it explicitly on the environment it
passes, which ``tests/unit/test_verify_toolchain_preflight.py`` already does;
nothing is prevented, only inherited.
"""

from __future__ import annotations

import os
from collections.abc import Iterator

import pytest

#: The runner's internal-mode variable. Named here rather than imported: the
#: three implementations of the marker convention each carry their own copy of
#: the name on purpose (ADR 0018), and a test helper importing one of them would
#: make this file a fourth reader of it.
INTERNAL_MODE = "HARNESS_GATE_MARKER_RUNNER"


@pytest.fixture(autouse=True, scope="session")
def _public_entry_environment() -> Iterator[None]:
    """Run the suite as a public caller of the gate runner, never as its child."""
    inherited = os.environ.pop(INTERNAL_MODE, None)
    try:
        yield
    finally:
        if inherited is not None:
            os.environ[INTERNAL_MODE] = inherited
