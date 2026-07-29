#!/usr/bin/env python3
"""Generate ``docs/index.html``'s ``:root`` token block from
``design/03-tokens/tokens.json`` (#242).

After #241 the harness has ``tokens.json`` as a declared source of truth for
the landing page's palette, but the page itself still carried its own
hand-authored ``:root`` block — two copies of the same colors, and the one
that renders was not the one that was canonical. This build closes that gap:
it resolves the *semantic* tier of ``tokens.json`` (the tier consuming code
binds to; primitives are not emitted directly, per
``design/03-tokens/_naming.md``) down to literal values and writes them into a
narrow, marker-delimited region inside the page's ``<style>`` block.

The page's existing CSS (hundreds of lines outside that region) already binds
to the hand-authored variable names -- ``--build``, ``--ink``, etc. --
directly. ``_naming.md`` proposes a namespaced rename (``--color-loop-build-
accent``) for the design system generally, but explicitly leaves *this*
ticket to settle how the generator itself names its output. Renaming every
consumer across the page is a much larger, riskier change than "add a build
step for one block" and is out of scope here (see the change spec's "Out of
scope"), so ``SEMANTIC_TO_CSS_VAR`` below maps each semantic token straight
to the page's existing variable name -- the write stays confined to the
marker region, and nothing outside it changes.

Missing or unpaired markers are a hard error: this script never guesses at
its region, and never writes anything when it cannot find it precisely.

Stdlib only (mirrors ``scripts/check_landing_page_guidance.py``): no
Style Dictionary, no npm build.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

#: ``scripts/build_*.py`` -> ``parent.parent`` is the repo (or worktree) root.
REPO_ROOT = Path(__file__).resolve().parent.parent
PAGE_DEFAULT = REPO_ROOT / "docs" / "index.html"
TOKENS_DEFAULT = REPO_ROOT / "design" / "03-tokens" / "tokens.json"

#: The generated-region markers, written at the same 2-space indent as the
#: ``:root{`` / ``}`` lines they sit between.
BEGIN_MARKER = (
    "/* design-tokens:begin — generated from design/03-tokens/tokens.json; do not edit */"
)
END_MARKER = "/* design-tokens:end */"

#: Semantic token path (dot-delimited, per ``_naming.md``) -> the CSS custom
#: property name the page's hand-authored rules already bind to. See the
#: module docstring: a deliberate rename to the namespaced scheme is out of
#: scope for this ticket.
SEMANTIC_TO_CSS_VAR = {
    "color.semantic.text.primary": "--ink",
    "color.semantic.text.secondary": "--ink-2",
    "color.semantic.text.muted": "--muted",
    "color.semantic.border.default": "--line",
    "color.semantic.surface.card": "--card",
    "color.semantic.surface.page": "--bg",
    "color.semantic.loop.build.accent": "--build",
    "color.semantic.loop.build.soft": "--build-soft",
    "color.semantic.loop.build.ink": "--build-ink",
    "color.semantic.loop.product.accent": "--product",
    "color.semantic.loop.product.soft": "--product-soft",
    "color.semantic.loop.product.ink": "--product-ink",
    "color.semantic.loop.quality.accent": "--quality",
    "color.semantic.loop.quality.soft": "--quality-soft",
    "color.semantic.loop.quality.ink": "--quality-ink",
    "color.semantic.loop.strategy.accent": "--strategy",
    "color.semantic.loop.strategy.soft": "--strategy-soft",
    "color.semantic.loop.strategy.ink": "--strategy-ink",
    "shadow.semantic.elevation.default": "--shadow",
}

#: Emission order and line grouping, mirroring the page's original
#: hand-authored layout (one line per loop/neutral group, shadow alone).
CSS_VAR_LINES = [
    ("--ink", "--ink-2", "--muted"),
    ("--line", "--card", "--bg"),
    ("--build", "--build-soft", "--build-ink"),
    ("--product", "--product-soft", "--product-ink"),
    ("--quality", "--quality-soft", "--quality-ink"),
    ("--strategy", "--strategy-soft", "--strategy-ink"),
    ("--shadow",),
]


class GeneratedRegionError(Exception):
    """The page's generated-region markers are missing, unpaired, or duplicated."""


def _get_path(tree: dict[str, Any], dotted: str) -> dict[str, Any]:
    node: Any = tree
    for part in dotted.split("."):
        node = node[part]
    return node  # type: ignore[no-any-return]


def _resolve_value(tree: dict[str, Any], dotted: str) -> str:
    """Follow ``{dotted.path}`` references down to a literal token value."""
    value = _get_path(tree, dotted)["value"]
    while isinstance(value, str) and value.startswith("{") and value.endswith("}"):
        value = _get_path(tree, value[1:-1])["value"]
    return value  # type: ignore[no-any-return]


def resolve_css_vars(tokens: dict[str, Any]) -> dict[str, str]:
    """Resolve every semantic token to its literal value, keyed by CSS var name."""
    return {
        css_var: _resolve_value(tokens, path)
        for path, css_var in SEMANTIC_TO_CSS_VAR.items()
    }


def render_region_lines(tokens: dict[str, Any]) -> list[str]:
    """The generated region's body lines (4-space indented, no markers)."""
    resolved = resolve_css_vars(tokens)
    lines = []
    for group in CSS_VAR_LINES:
        decls = "; ".join(f"{var}:{resolved[var]}" for var in group)
        lines.append(f"    {decls};")
    return lines


def _find_marker(lines: list[str], marker: str) -> int:
    indices = [i for i, line in enumerate(lines) if line.strip() == marker]
    if len(indices) != 1:
        raise GeneratedRegionError(
            f"expected exactly one {marker!r} line, found {len(indices)}"
        )
    return indices[0]


def _replace_region(page_text: str, tokens: dict[str, Any]) -> str:
    lines = page_text.split("\n")
    try:
        begin = _find_marker(lines, BEGIN_MARKER)
        end = _find_marker(lines, END_MARKER)
    except GeneratedRegionError as exc:
        raise GeneratedRegionError(
            f"docs/index.html: cannot find the generated-region markers "
            f"({BEGIN_MARKER!r} / {END_MARKER!r}): {exc}"
        ) from exc
    if begin >= end:
        raise GeneratedRegionError(
            "docs/index.html: the begin marker must precede the end marker"
        )
    new_lines = lines[: begin + 1] + render_region_lines(tokens) + lines[end:]
    return "\n".join(new_lines)


def write_generated_region(page_path: Path, tokens_path: Path) -> None:
    """Write the resolved tokens into ``page_path``'s generated region.

    Raises ``GeneratedRegionError`` (writing nothing) when the markers cannot
    be found unambiguously.
    """
    page_text = page_path.read_text(encoding="utf-8")
    tokens = json.loads(tokens_path.read_text(encoding="utf-8"))
    new_text = _replace_region(page_text, tokens)
    page_path.write_text(new_text, encoding="utf-8")


def check_generated_region(page_path: Path, tokens_path: Path) -> list[str]:
    """Compare the committed generated region against what the build would
    produce. Returns a list of human-readable drift descriptions (empty when
    the region matches). Raises ``GeneratedRegionError`` if markers are
    missing/unpaired.
    """
    page_text = page_path.read_text(encoding="utf-8")
    tokens = json.loads(tokens_path.read_text(encoding="utf-8"))
    lines = page_text.split("\n")
    begin = _find_marker(lines, BEGIN_MARKER)
    end = _find_marker(lines, END_MARKER)
    if begin >= end:
        raise GeneratedRegionError(
            "docs/index.html: the begin marker must precede the end marker"
        )
    committed = lines[begin + 1 : end]
    expected = render_region_lines(tokens)
    if committed == expected:
        return []
    return [
        f"line {begin + 1 + i}: committed {c!r} != generated {e!r}"
        for i, (c, e) in enumerate(zip(committed, expected, strict=False))
        if c != e
    ] or [f"generated region has {len(expected)} lines, page has {len(committed)}"]


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else "")
    parser.add_argument(
        "--page", type=Path, default=PAGE_DEFAULT, help="path to the landing page HTML"
    )
    parser.add_argument(
        "--tokens", type=Path, default=TOKENS_DEFAULT, help="path to tokens.json"
    )
    parser.add_argument(
        "--check", action="store_true", help="check the committed region for drift; do not write"
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    try:
        if args.check:
            drift = check_generated_region(args.page, args.tokens)
            if drift:
                print(
                    f"design tokens: {args.page} has drifted from {args.tokens}:",
                    file=sys.stderr,
                )
                for line in drift:
                    print(f"  {line}", file=sys.stderr)
                return 1
            print(f"design tokens: OK — {args.page} matches {args.tokens}.")
            return 0
        write_generated_region(args.page, args.tokens)
        print(f"design tokens: wrote the generated region in {args.page}.")
        return 0
    except GeneratedRegionError as exc:
        print(f"design tokens: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
