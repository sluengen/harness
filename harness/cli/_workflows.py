"""Shared workflow directory resolution for CLI commands.

This module exists so ``harness run``, ``harness decision approve``, and
``harness decision reject`` all use the same four-step lookup rather than
each hard-coding ``Path("workflows")``.

Public symbol: :func:`_resolve_workflows_dir`.
"""

from __future__ import annotations

import importlib.resources
import os
from pathlib import Path


def _resolve_workflows_dir(explicit: Path | None) -> Path:
    """Resolve the workflow directory using the four-step fallback chain.

    Priority:
    1. ``explicit`` — the ``--workflows-dir`` CLI flag when provided.
    2. ``$HARNESS_WORKFLOWS_DIR`` environment variable.
    3. ``Path("workflows")`` relative to CWD — preserved for in-repo dev use.
    4. ``importlib.resources.files("harness.workflows")`` — bundled package
       data available after ``uv tool install .`` or ``pip install .``.

    Steps 3 and 4 are only selected when the candidate directory actually
    exists. Steps 1 and 2 are trusted as-is (the caller supplied them
    deliberately).

    Returns:
        A :class:`~pathlib.Path` for the resolved directory. If none of the
        fallbacks locate an existing directory, returns ``Path("workflows")``
        so callers surface the original "workflow not found" error.
    """
    if explicit is not None:
        return explicit

    env_val = os.environ.get("HARNESS_WORKFLOWS_DIR")
    if env_val:
        return Path(env_val)

    cwd_local = Path("workflows")
    if cwd_local.is_dir():
        return cwd_local.resolve()

    # Installed package data — available when harness is installed as a
    # distribution package (uv tool install / pip install).
    try:
        pkg_ref = importlib.resources.files("harness.workflows")
        pkg_path = Path(str(pkg_ref))
        if pkg_path.is_dir():
            return pkg_path
    except Exception:  # noqa: BLE001, S110 — broad catch intentional; many failure modes
        pass

    # Final fallback: callers receive a "workflow not found" error if the
    # directory does not exist at this path. This preserves the original
    # error message rather than introducing a new one.
    return Path("workflows")
