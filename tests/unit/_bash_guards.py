"""The set of hooks ``hooks.json`` registers against the ``Bash`` tool.

Extracted at #573, when a second module needed the identical derivation. The
rule this obeys is #467's: a ``test_*.py`` another module imports has become a
library, so the shared thing moves to an underscore module rather than being
imported across test modules — and it moves rather than being copied, because
what is shared here is **a claim about the shipped registration**, not a
fixture.

That distinction is the reason this is not left duplicated. The six push-guard
suites each keep their own ``repo`` fixture on purpose, and
``test_heredoc_lexing.py`` says so in a comment: a fixture copy is cheap and its
divergence is visible. A copy of *this* is neither. It answers "which guards
does a ``Bash`` call actually run", and two independent readers of
``hooks.json`` can drift apart silently — after which one module measures the
composed control and the other measures a subset of it, both green.

It lives here rather than in :mod:`tests.unit._hooks`, which holds **captured
host payloads** — evidence recorded from a real host — and says so in its own
first line. This is a derivation over a tracked artifact in the repo, which is a
different kind of thing.

Derived, never listed. A matcher is a regex over the tool name, so this asks
each ``PreToolUse`` matcher whether it matches ``Bash`` rather than assuming the
literal string. Hardcoding the filenames would still pass after a guard was
unregistered — pinning the derived answer instead of the derivation (#458/#466),
which is the failure #562 was careful to avoid when it made the registration the
input to its own subject.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from tests.unit._prose import REPO_ROOT

HOOKS_DIR = REPO_ROOT / "hooks"
HOOKS_JSON = HOOKS_DIR / "hooks.json"


def registered_bash_guards() -> list[Path]:
    """Every hook ``hooks.json`` registers against the ``Bash`` tool.

    Returns the hook scripts in registration order. A registered entry whose
    script is absent from ``hooks/`` is skipped rather than returned, so a
    caller always receives paths it can run.
    """
    spec = json.loads(HOOKS_JSON.read_text())
    found: list[Path] = []
    for entry in spec.get("hooks", {}).get("PreToolUse", []):
        if not re.search(entry.get("matcher", ""), "Bash"):
            continue
        for hook in entry.get("hooks", []):
            name = Path(hook.get("command", "").split()[-1]).name
            script = HOOKS_DIR / name
            if script.is_file():
                found.append(script)
    return found
