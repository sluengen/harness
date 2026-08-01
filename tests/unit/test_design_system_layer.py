"""design/ — the harness's own design-system layer (issue #241).

Standing up ``design/`` from ``templates/design-system.md`` (#239) is the first
real exercise of that contract: it captures ``docs/index.html``'s hand-authored
``:root`` block as tokens, rather than redesigning it. These tests pin the
acceptance criteria:

  AC-1  ``design/`` carries all eight layer directories, each with a
        ``README.md``; layers 00-03 are substantive, 04-07 are declared
        scaffolds — both facts readable from each layer's own frontmatter.
  AC-2  every markdown entry file under ``design/`` carries the five
        frontmatter fields ``templates/design-system.md`` requires: ``layer``,
        ``kind``, ``status``, ``owner``, ``last_updated``.
  AC-3  ``design/03-tokens/tokens.json`` resolves to exactly the set of colour
        and size literals ``docs/index.html`` renders today in its ``:root``
        block — capture, not redesign.
  AC-4  ``CONTEXT.md`` reads ``design_system: true`` and
        ``paths.design_system: design/``.

Regex over raw text, not PyYAML/frontmatter libraries — this repo has neither
as a declared dependency (mirrors ``test_landing_page.py``'s
``_registry_ids_by_kind``).
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

#: ``tests/unit/test_*.py`` -> ``parents[2]`` is the repo (or worktree) root.
REPO_ROOT = Path(__file__).resolve().parents[2]
DESIGN_ROOT = REPO_ROOT / "design"
PAGE = REPO_ROOT / "docs" / "index.html"
CONTEXT = REPO_ROOT / "CONTEXT.md"
TOKENS_JSON = DESIGN_ROOT / "03-tokens" / "tokens.json"

#: Layer id -> declared substance. 00-03 are substantive (frontmatter
#: ``status`` must not read ``scaffold``); 04-07 are declared scaffolds
#: (frontmatter ``status: scaffold``).
SUBSTANTIVE_LAYERS = ("00-brand", "01-voice", "02-principles", "03-tokens")
SCAFFOLD_LAYERS = ("04-primitives", "05-patterns", "06-archetypes", "07-flows")
ALL_LAYERS = SUBSTANTIVE_LAYERS + SCAFFOLD_LAYERS

_FRONTMATTER = re.compile(r"\A---\n(.*?)\n---\n", re.DOTALL)
_REQUIRED_FRONTMATTER_FIELDS = ("layer", "kind", "status", "owner", "last_updated")


def _frontmatter(md_path: Path) -> dict[str, str]:
    """Parse a markdown file's leading ``---`` frontmatter block into a dict.

    Only bare ``key: value`` scalars are needed here; nothing in this tree
    uses nested/list frontmatter.
    """
    text = md_path.read_text(encoding="utf-8")
    m = _FRONTMATTER.match(text)
    assert m, f"{md_path} has no leading frontmatter block"
    fields: dict[str, str] = {}
    for line in m.group(1).splitlines():
        if not line.strip() or ":" not in line:
            continue
        key, _, value = line.partition(":")
        fields[key.strip()] = value.strip()
    return fields


def _all_design_markdown_files() -> list[Path]:
    return sorted(DESIGN_ROOT.rglob("*.md"))


# --------------------------------------------------------------------------- #
# AC-1 — eight layer directories, each with a README, status declared
# --------------------------------------------------------------------------- #


def test_all_eight_layer_directories_exist_with_readme() -> None:
    missing = [layer for layer in ALL_LAYERS if not (DESIGN_ROOT / layer / "README.md").is_file()]
    assert not missing, f"design/ is missing a README.md for layer(s): {missing}"


def test_substantive_layers_declare_non_scaffold_status() -> None:
    for layer in SUBSTANTIVE_LAYERS:
        fm = _frontmatter(DESIGN_ROOT / layer / "README.md")
        assert fm.get("status") != "scaffold", (
            f"design/{layer}/README.md is substantive (00-03) but status reads 'scaffold'"
        )


def test_scaffold_layers_declare_scaffold_status() -> None:
    for layer in SCAFFOLD_LAYERS:
        fm = _frontmatter(DESIGN_ROOT / layer / "README.md")
        assert fm.get("status") == "scaffold", (
            f"design/{layer}/README.md is a declared scaffold (04-07) but frontmatter status reads "
            f"{fm.get('status')!r}, not 'scaffold'"
        )


def test_top_level_readme_declares_per_layer_status() -> None:
    text = (DESIGN_ROOT / "README.md").read_text(encoding="utf-8")
    assert re.search(r"(?im)^##.*status", text), "design/README.md must carry a Status section"
    for layer in ALL_LAYERS:
        assert layer in text, f"design/README.md's Status section must name layer {layer!r}"


# --------------------------------------------------------------------------- #
# AC-2 — every entry file carries the five required frontmatter fields
# --------------------------------------------------------------------------- #


def test_every_markdown_entry_carries_required_frontmatter() -> None:
    files = _all_design_markdown_files()
    assert files, "design/ has no markdown entry files to check"
    missing_by_file: dict[str, list[str]] = {}
    for path in files:
        fm = _frontmatter(path)
        missing = [f for f in _REQUIRED_FRONTMATTER_FIELDS if not fm.get(f)]
        if missing:
            missing_by_file[str(path.relative_to(REPO_ROOT))] = missing
    assert not missing_by_file, (
        f"entry file(s) missing required frontmatter field(s): {missing_by_file}"
    )


def test_frontmatter_layer_field_matches_containing_directory() -> None:
    mismatches = []
    for path in _all_design_markdown_files():
        if path.parent == DESIGN_ROOT:
            continue  # top-level design/README.md has no single owning layer
        fm = _frontmatter(path)
        expected_layer = path.parent.name
        if fm.get("layer") != expected_layer:
            mismatches.append((str(path.relative_to(REPO_ROOT)), fm.get("layer"), expected_layer))
    assert not mismatches, f"frontmatter 'layer' disagrees with directory: {mismatches}"


# --------------------------------------------------------------------------- #
# AC-3 — tokens.json resolves to exactly today's rendered :root literals
# --------------------------------------------------------------------------- #


def _root_block_values() -> set[str]:
    """The exact set of custom-property values in docs/index.html's :root block."""
    html = PAGE.read_text(encoding="utf-8")
    root_match = re.search(r":root\{(.*?)\}", html, re.DOTALL)
    assert root_match, "docs/index.html has no :root{...} block"
    pairs = re.findall(r"--[\w-]+:\s*([^;]+);", root_match.group(1))
    assert pairs, ":root block yielded no custom-property values"
    return {value.strip() for value in pairs}


def _resolve_token_tree(node: Any, root: dict[str, Any]) -> Any:
    """Resolve a tokens.json leaf's ``value``, following ``{dotted.path}`` refs."""
    if isinstance(node, dict) and "value" in node:
        value = node["value"]
        ref = re.fullmatch(r"\{([\w.-]+)\}", value) if isinstance(value, str) else None
        if ref:
            target: Any = root
            for part in ref.group(1).split("."):
                target = target[part]
            return _resolve_token_tree(target, root)
        return value
    raise TypeError(f"not a token leaf: {node!r}")


def _resolved_leaf_values(node: Any, root: dict[str, Any]) -> set[str]:
    """Walk a tokens.json (sub)tree, collecting every resolved leaf value."""
    if isinstance(node, dict) and "value" in node:
        return {_resolve_token_tree(node, root)}
    values: set[str] = set()
    if isinstance(node, dict):
        for key, child in node.items():
            if key.startswith("_"):
                continue
            values |= _resolved_leaf_values(child, root)
    return values


def test_tokens_json_parses_as_three_tier_structure() -> None:
    data = json.loads(TOKENS_JSON.read_text(encoding="utf-8"))
    assert "color" in data, "tokens.json must carry a 'color' namespace"
    color = data["color"]
    assert "primitive" in color, "'color' namespace must have a 'primitive' tier"
    assert "semantic" in color, "'color' namespace must have a 'semantic' tier"
    assert "component" in data, "tokens.json must declare a top-level 'component' tier"


def test_tokens_json_resolved_values_match_rendered_root_block_exactly() -> None:
    data = json.loads(TOKENS_JSON.read_text(encoding="utf-8"))
    resolved = _resolved_leaf_values(data, data)
    rendered = _root_block_values()
    missing = rendered - resolved
    extra = resolved - rendered
    assert not missing, f"tokens.json is missing value(s) the page renders: {missing}"
    assert not extra, f"tokens.json carries value(s) the page does not render: {extra}"


# --------------------------------------------------------------------------- #
# AC-4 — CONTEXT.md flips the layer + path
# --------------------------------------------------------------------------- #


def test_context_declares_design_system_layer_on() -> None:
    text = CONTEXT.read_text(encoding="utf-8")
    assert re.search(r"^\s*design_system:\s*true\s*(?:#.*)?$", text, re.MULTILINE), (
        "CONTEXT.md must set layers.design_system: true"
    )


def test_context_declares_design_system_path() -> None:
    text = CONTEXT.read_text(encoding="utf-8")
    assert re.search(r"^\s*design_system:\s*design/\s*(?:#.*)?$", text, re.MULTILINE), (
        "CONTEXT.md must set paths.design_system: design/"
    )
