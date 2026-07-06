"""License guard — the repo ships an MIT license, coherently declared.

The harness is going public (2026-07-06 open-sourcing decision). Two surfaces
must agree that the license is MIT, and a public reader must find the license
text where they expect it:

* a root ``LICENSE`` file carrying the standard MIT text and the copyright line;
* ``pyproject.toml`` declaring MIT (and no longer ``Proprietary``), so the
  package metadata matches the shipped license.

This guard is git-aware (``tracked_files_under``): a ``LICENSE`` that exists only
on an author's disk must still fail on a clean checkout, since a public reader
sees only the committed tree.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

from tests._gitutil import tracked_files_under

_REPO_ROOT = Path(__file__).resolve().parents[2]
_LICENSE = _REPO_ROOT / "LICENSE"
_PYPROJECT = _REPO_ROOT / "pyproject.toml"


def test_license_file_is_tracked_mit() -> None:
    """A committed root ``LICENSE`` carries the MIT text and the copyright line."""
    assert _LICENSE.resolve() in tracked_files_under("LICENSE"), (
        "No tracked LICENSE at the repo root. A public reader looks for the "
        "license there; ship it (MIT, per the open-sourcing decision)."
    )
    text = _LICENSE.read_text()
    assert "MIT License" in text, "LICENSE must carry the standard MIT text."
    assert "Scott Luengen" in text, "LICENSE must carry the copyright holder."


def test_pyproject_declares_mit_not_proprietary() -> None:
    """``pyproject.toml`` declares MIT and no longer says ``Proprietary``."""
    raw = _PYPROJECT.read_text()
    assert "Proprietary" not in raw, (
        "pyproject.toml still declares a Proprietary license; the repo is MIT."
    )
    license_field = tomllib.loads(raw)["project"]["license"]
    # PEP 639 SPDX string (``license = \"MIT\"``) or the legacy table
    # (``license = { text = \"MIT\" }``) — accept either declared form.
    declared = license_field if isinstance(license_field, str) else license_field.get("text")
    assert declared == "MIT", f"pyproject [project].license must be MIT, got {license_field!r}."
