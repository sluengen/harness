"""Host-platform abstraction for the wrapper's pre-container work (#305, ADR 0012).

``docker/harness-wrapper.sh`` carried credential resolution, subprocess-timeout
selection, image-freshness comparison and git-identity resolution as macOS-shaped
bash. None of it was reachable from the native ``uv tool install`` entry point,
and ADR 0012 makes Windows-via-WSL a supported platform — which shell built around
``security find-generic-password`` cannot express at all.

**Stdlib only.** Nothing in this package may import pydantic, typer, aiosqlite or
ulid. The wrapper runs it on the *host*, before any container exists, under an
interpreter that is frequently not the project venv — so a third-party import here
would make the wrapper depend on the very environment it is being run to set up.
``tests/unit/test_hostenv_stdlib_only.py`` holds that line.
"""

from __future__ import annotations
