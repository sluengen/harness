"""Every workflow declares an explicit least-privilege ``permissions`` block (CAL-1029).

A workflow that declares nothing inherits the **repo-level default**, which is a
setting in the GitHub UI: no test can see it, no reviewer reads it, and widening
it silently widens every job that stayed silent. The default is read-only today,
which is exactly what makes a missing block invisible — there is no symptom until
the day the setting changes. An explicit block pins the grant at the workflow,
where it is reviewable in the diff.

Note the threat is *not* fork pull requests: a public repo hands a fork PR a
read-only token regardless of the default. It is the ``push: [main]`` trigger,
which runs with the repo's own token, that a widened default would reach.

``ci.yml`` carried no block at all. These guards hold the contract for every
workflow in the directory, so a new one cannot land without declaring what it
needs — including the nightly promotion, whose ``contents: write`` is the widest
grant left in the tree now that ADR 0015 has retired the image release (#435).

The workflows are parsed as text (PyYAML is not a project dependency). That is
enough to catch the regression
this targets — a workflow with no block at all — without pretending to evaluate
GitHub's effective-permission resolution.

*Source:* CAL-1029 (go public — repo settings sweep, step 5).
"""

from __future__ import annotations

import re
from pathlib import Path

from tests.unit._prose import REPO_ROOT

_WORKFLOW_DIR = REPO_ROOT / ".github" / "workflows"

#: A ``permissions:`` key at any indent — top-level or job-level both satisfy
#: least privilege, so a workflow that scopes its grant per-job is accepted.
_PERMISSIONS_RE = re.compile(r"^\s*permissions:\s*$", re.M)

#: The only grant CI needs: read the code it tests. Anything wider on a workflow
#: that runs untrusted fork PRs is the thing this guard exists to stop.
_CI_EXPECTED_GRANT = "contents: read"


def _workflows() -> list[Path]:
    return sorted(_WORKFLOW_DIR.glob("*.yml"))


def test_workflow_dir_is_non_empty() -> None:
    """Non-vacuity: the guards below must actually scan something.

    A glob that silently returns nothing would make every assertion here pass by
    default — the failure mode that makes a guard worse than no guard.
    """
    assert _workflows(), f"no workflows found under {_WORKFLOW_DIR} — the guards below are vacuous"


def test_every_workflow_declares_permissions() -> None:
    """No workflow relies on the repo-level default (CAL-1029)."""
    missing = [w.name for w in _workflows() if not _PERMISSIONS_RE.search(w.read_text())]
    assert not missing, (
        f"{missing} declare no `permissions:` block, so they inherit whatever the "
        "repo-level default happens to be — a setting outside this repo's review. "
        "Declare the grant explicitly at the workflow or job (CAL-1029)."
    )


def test_ci_workflow_is_read_only() -> None:
    """``ci.yml`` grants only ``contents: read`` (CAL-1029).

    The job checks out, installs uv, and runs the verify gate: it pushes nothing,
    publishes no package, and mints no OIDC token, so the checkout is the whole
    requirement. This is the measuring test for "least privilege" — it pins the
    actual grant rather than merely asserting that *some* block exists, which a
    ``write-all`` block would satisfy just as well.
    """
    text = (_WORKFLOW_DIR / "ci.yml").read_text()
    assert _CI_EXPECTED_GRANT in text, (
        f"ci.yml must grant `{_CI_EXPECTED_GRANT}` — it only needs to read the "
        "checkout it tests (CAL-1029)."
    )
    for forbidden in ("write-all", "contents: write", "packages: write", "id-token: write"):
        assert forbidden not in text, (
            f"ci.yml grants `{forbidden}`, which a lint-and-test job never needs "
            "(CAL-1029)."
        )
