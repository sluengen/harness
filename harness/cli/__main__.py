"""Allow ``python -m harness.cli`` to invoke the Typer app.

Mirrors what ``[project.scripts] harness = "harness.cli:app"`` does for the
installed entrypoint. Kept as a thin file so ``import harness.cli`` is cheap.
"""

from __future__ import annotations

from harness.cli import app

if __name__ == "__main__":
    app()
