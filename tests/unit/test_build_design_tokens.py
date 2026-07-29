"""The token build step (#242): generate docs/index.html's :root block from
design/03-tokens/tokens.json rather than hand-authoring two copies of the same
palette.

``scripts/build_design_tokens.py`` writes only the marker-delimited generated
region inside ``docs/index.html``'s ``<style>`` block — see
``design/03-tokens/_naming.md`` for the token-path -> CSS-variable derivation
this settles (the page's existing hand-authored variable names, e.g.
``--build``, are kept; a page-wide rename to the new namespaced scheme
(``--color-loop-build-accent``) is out of scope for this ticket).

These tests exercise the pure resolver/region functions against fixture files
under ``tests/fixtures/build_design_tokens/`` so they never depend on the
real, evolving ``docs/index.html``.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "build_design_tokens.py"
VERIFY = REPO_ROOT / "scripts" / "verify.sh"
PAGE = REPO_ROOT / "docs" / "index.html"
TOKENS = REPO_ROOT / "design" / "03-tokens" / "tokens.json"


def _module():
    """Import the standalone script as a module (``scripts/`` is not a package)."""
    spec = importlib.util.spec_from_file_location("build_design_tokens", SCRIPT)
    assert spec and spec.loader, f"cannot load {SCRIPT}"
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


bdt = _module()


def _tokens() -> dict:
    return json.loads((REPO_ROOT / "design" / "03-tokens" / "tokens.json").read_text())


def _page_with_markers(body_lines: list[str]) -> str:
    """A minimal ``<style>`` page with the generated-region markers in place,
    ``body_lines`` (already indented) sandwiched between them."""
    body = "\n".join(body_lines)
    middle = f"\n{body}\n" if body else "\n"
    return (
        "<html><head><style>\n"
        "  :root{\n"
        f"  {bdt.BEGIN_MARKER}{middle}  {bdt.END_MARKER}\n"
        "  }\n"
        "  *{box-sizing:border-box}\n"
        "</style></head></html>\n"
    )


# --------------------------------------------------------------------------- #
# AC-1 — the script exists and exposes both modes
# --------------------------------------------------------------------------- #


def test_script_is_stdlib_only() -> None:
    """AC-1: no new dependency was added to resolve/emit tokens."""
    pyproject = (REPO_ROOT / "pyproject.toml").read_text()
    assert "style-dictionary" not in pyproject.lower()
    assert "pyyaml" not in pyproject.lower()


def test_cli_exposes_write_and_check_modes() -> None:
    """AC-1: ``build_design_tokens.py`` and ``--check`` both parse."""
    parser = bdt.build_arg_parser()
    write_args = parser.parse_args([])
    check_args = parser.parse_args(["--check"])
    assert write_args.check is False
    assert check_args.check is True


# --------------------------------------------------------------------------- #
# AC-2 — resolved values are byte-identical to today's palette
# --------------------------------------------------------------------------- #


def test_resolved_vars_match_current_palette() -> None:
    """AC-2: every resolved CSS var:value matches the page's hand-authored values."""
    tokens = _tokens()
    resolved = bdt.resolve_css_vars(tokens)
    expected = {
        "--ink": "#0e1430",
        "--ink-2": "#3c4467",
        "--muted": "#6b7396",
        "--line": "#e6e8f2",
        "--card": "#ffffff",
        "--bg": "#f5f6fb",
        "--build": "#0f9d6e",
        "--build-soft": "#e6f6f0",
        "--build-ink": "#0a5e44",
        "--product": "#3b5bdb",
        "--product-soft": "#e9edfd",
        "--product-ink": "#23348f",
        "--quality": "#d97706",
        "--quality-soft": "#fdf1df",
        "--quality-ink": "#8a4b06",
        "--strategy": "#7c3aed",
        "--strategy-soft": "#f1eafd",
        "--strategy-ink": "#4c1d95",
        "--shadow": "0 1px 2px rgba(16,24,64,.05), 0 10px 30px rgba(16,24,64,.06)",
    }
    assert resolved == expected


def test_primitives_are_not_emitted_directly() -> None:
    """AC-2 design constraint: only semantic-tier paths drive emission."""
    tokens = _tokens()
    assert set(bdt.resolve_css_vars(tokens)) == set(bdt.SEMANTIC_TO_CSS_VAR.values())


# --------------------------------------------------------------------------- #
# AC-3 — idempotent
# --------------------------------------------------------------------------- #


def test_build_is_idempotent(tmp_path: Path) -> None:
    tokens_path = tmp_path / "tokens.json"
    tokens_path.write_text(json.dumps(_tokens()))
    page_path = tmp_path / "index.html"
    page_path.write_text(_page_with_markers([]))

    bdt.write_generated_region(page_path, tokens_path)
    once = page_path.read_text()
    bdt.write_generated_region(page_path, tokens_path)
    twice = page_path.read_text()
    assert once == twice


# --------------------------------------------------------------------------- #
# AC-4 — the write never touches a byte outside the markers
# --------------------------------------------------------------------------- #


def test_build_confines_diff_to_generated_region(tmp_path: Path) -> None:
    tokens = _tokens()
    tokens_path = tmp_path / "tokens.json"
    tokens_path.write_text(json.dumps(tokens))
    page_path = tmp_path / "index.html"
    page_path.write_text(_page_with_markers([]))
    bdt.write_generated_region(page_path, tokens_path)
    before = page_path.read_text().splitlines()

    tokens["color"]["primitive"]["build"]["base"]["value"] = "#123456"
    tokens_path.write_text(json.dumps(tokens))
    bdt.write_generated_region(page_path, tokens_path)
    after = page_path.read_text().splitlines()

    assert len(before) == len(after)
    begin_idx = before.index(f"  {bdt.BEGIN_MARKER}")
    end_idx = before.index(f"  {bdt.END_MARKER}")
    for i, (b, a) in enumerate(zip(before, after, strict=True)):
        if begin_idx < i < end_idx:
            continue
        assert b == a, f"line {i} outside the generated region changed"
    assert any(
        before[i] != after[i] for i in range(begin_idx + 1, end_idx)
    ), "changed token should have altered the generated region"


# --------------------------------------------------------------------------- #
# AC-5 — missing/unpaired markers refuse, and write nothing
# --------------------------------------------------------------------------- #


def test_no_markers_at_all_refuses_and_writes_nothing(tmp_path: Path) -> None:
    tokens_path = tmp_path / "tokens.json"
    tokens_path.write_text(json.dumps(_tokens()))
    page_path = tmp_path / "index.html"
    html = "<style>\n  :root{\n    --ink:#0e1430;\n  }\n</style>\n"
    page_path.write_text(html)

    with pytest.raises(bdt.GeneratedRegionError):
        bdt.write_generated_region(page_path, tokens_path)
    assert page_path.read_text() == html


def test_unpaired_begin_marker_refuses(tmp_path: Path) -> None:
    tokens_path = tmp_path / "tokens.json"
    tokens_path.write_text(json.dumps(_tokens()))
    page_path = tmp_path / "index.html"
    html = f"<style>\n  :root{{\n  {bdt.BEGIN_MARKER}\n  }}\n</style>\n"
    page_path.write_text(html)

    with pytest.raises(bdt.GeneratedRegionError):
        bdt.write_generated_region(page_path, tokens_path)
    assert page_path.read_text() == html


def test_unpaired_end_marker_refuses(tmp_path: Path) -> None:
    tokens_path = tmp_path / "tokens.json"
    tokens_path.write_text(json.dumps(_tokens()))
    page_path = tmp_path / "index.html"
    html = f"<style>\n  :root{{\n  {bdt.END_MARKER}\n  }}\n</style>\n"
    page_path.write_text(html)

    with pytest.raises(bdt.GeneratedRegionError):
        bdt.write_generated_region(page_path, tokens_path)
    assert page_path.read_text() == html


def test_duplicate_begin_marker_refuses(tmp_path: Path) -> None:
    tokens_path = tmp_path / "tokens.json"
    tokens_path.write_text(json.dumps(_tokens()))
    page_path = tmp_path / "index.html"
    html = (
        f"<style>\n  :root{{\n  {bdt.BEGIN_MARKER}\n  {bdt.BEGIN_MARKER}\n"
        f"  {bdt.END_MARKER}\n  }}\n</style>\n"
    )
    page_path.write_text(html)

    with pytest.raises(bdt.GeneratedRegionError):
        bdt.write_generated_region(page_path, tokens_path)
    assert page_path.read_text() == html


# --------------------------------------------------------------------------- #
# --check mode
# --------------------------------------------------------------------------- #


def test_check_passes_when_region_matches(tmp_path: Path) -> None:
    tokens_path = tmp_path / "tokens.json"
    tokens_path.write_text(json.dumps(_tokens()))
    page_path = tmp_path / "index.html"
    page_path.write_text(_page_with_markers([]))
    bdt.write_generated_region(page_path, tokens_path)

    assert bdt.check_generated_region(page_path, tokens_path) == []


def test_check_reports_drift(tmp_path: Path) -> None:
    tokens = _tokens()
    tokens_path = tmp_path / "tokens.json"
    tokens_path.write_text(json.dumps(tokens))
    page_path = tmp_path / "index.html"
    page_path.write_text(_page_with_markers([]))
    bdt.write_generated_region(page_path, tokens_path)

    tokens["color"]["primitive"]["build"]["base"]["value"] = "#123456"
    tokens_path.write_text(json.dumps(tokens))

    drift = bdt.check_generated_region(page_path, tokens_path)
    assert drift, "changed token must be reported as drift"
    assert any("--build" in d for d in drift)


# --------------------------------------------------------------------------- #
# #243 AC-1 — the gate step is wired into scripts/verify.sh
# --------------------------------------------------------------------------- #


def test_check_wired_into_verify_sh() -> None:
    """``scripts/verify.sh`` invokes the drift guard, so the gate runs it."""
    verify = VERIFY.read_text(encoding="utf-8")
    assert "build_design_tokens.py --check" in verify, (
        "scripts/verify.sh must invoke the design-token drift guard"
    )


def test_check_cli_passes_on_real_page() -> None:
    """AC-1: the real, committed page matches tokens.json — the gate step passes."""
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--check"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        f"--check failed on the real page (exit {result.returncode}):\n"
        f"{result.stdout}\n{result.stderr}"
    )


# --------------------------------------------------------------------------- #
# #243 AC-2 — a hand-edit to the generated region fails the gate
# --------------------------------------------------------------------------- #


def test_check_cli_fails_on_hand_edited_region(tmp_path: Path) -> None:
    """A hand-edit inside the generated region fails ``--check``, naming the
    drifted property and the regenerating command."""
    page_path = tmp_path / "index.html"
    page_path.write_text(
        PAGE.read_text(encoding="utf-8").replace("--ink:#0e1430", "--ink:#000000"),
        encoding="utf-8",
    )

    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--check", "--page", str(page_path), "--tokens", str(TOKENS)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0, "a hand-edited region must fail the gate"
    output = result.stdout + result.stderr
    assert "--ink" in output, "the failure must name the drifted property"
    assert "build_design_tokens.py" in output, (
        "the failure must name the regenerating command"
    )


# --------------------------------------------------------------------------- #
# #243 AC-3 — a tokens.json change without regenerating fails the gate
# --------------------------------------------------------------------------- #


def test_check_cli_fails_when_tokens_changed_without_regenerating(tmp_path: Path) -> None:
    """A ``tokens.json`` edit the page was never regenerated against fails
    ``--check`` the same way a hand-edit does — the check is symmetric."""
    tokens = _tokens()
    tokens["color"]["primitive"]["build"]["base"]["value"] = "#123456"
    tokens_path = tmp_path / "tokens.json"
    tokens_path.write_text(json.dumps(tokens))

    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--check", "--page", str(PAGE), "--tokens", str(tokens_path)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0, "an unregenerated tokens.json change must fail the gate"
    assert "--build" in (result.stdout + result.stderr), (
        "the failure must name the drifted property"
    )
