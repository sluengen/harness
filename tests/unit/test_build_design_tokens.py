"""The token build step (#242): generate docs/index.html's :root block from
design/03-tokens/tokens.json rather than hand-authoring two copies of the same
palette.

``scripts/build_design_tokens.py`` writes only the marker-delimited generated
region inside ``docs/index.html``'s ``<style>`` block — see
``design/03-tokens/_naming.md`` for the token-path -> CSS-variable derivation
this settles (the page's existing hand-authored variable names, e.g.
``--build``, are kept; a page-wide rename to the new namespaced scheme
(``--color-loop-build-accent``) is out of scope for this ticket).

The resolver and region-writer are exercised against pages synthesised in
``tmp_path``, so nothing about the page's evolving prose can reach them. The
consumer sweep ``--check`` grew in #466 cannot be tested that way: its subject
*is* the real ``docs/index.html``, and a control spliced into a shorter corpus
would prove only that the sweep reads some text. Those tests therefore splice
into the real page and assert about the splice — see
:func:`test_planted_duplicate_control_paired_splice_into_the_real_page`.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

from tests.unit._prose import REPO_ROOT

SCRIPT = REPO_ROOT / "scripts" / "build_design_tokens.py"
VERIFY = REPO_ROOT / "scripts" / "verify.sh"
PAGE = REPO_ROOT / "docs" / "index.html"
TOKENS = REPO_ROOT / "design" / "03-tokens" / "tokens.json"

# size: one script's acceptance suite — case enumeration over the four surfaces
# of build_design_tokens.py (the token resolver, the region write, the region
# check, and the consumer sweep #466 added to --check). Over the ceiling on
# recorded reasoning rather than on logic: better than a quarter of these lines
# are docstrings and comments, most of them naming the mutation a given control
# is the exclusive killer for, which is the half a later reader cannot
# reconstruct. Splitting by surface would put the sweep's controls in a
# different file from the markers and the resolver they are derived from, and a
# control separated from its subject is the shape that goes inert unnoticed.


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


def _relative_luminance(color: str) -> float:
    """Return the WCAG relative luminance of a six-digit CSS hex colour."""
    channels = (int(color[index : index + 2], 16) / 255 for index in range(1, 7, 2))

    def linearize(channel: float) -> float:
        return channel / 12.92 if channel <= 0.04045 else ((channel + 0.055) / 1.055) ** 2.4

    red, green, blue = (linearize(channel) for channel in channels)
    return 0.2126 * red + 0.7152 * green + 0.0722 * blue


def _contrast_ratio(foreground: str, background: str) -> float:
    darker, lighter = sorted((_relative_luminance(foreground), _relative_luminance(background)))
    return (lighter + 0.05) / (darker + 0.05)


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
        "--muted": "#656d8c",
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


@pytest.mark.parametrize(
    ("surface", "background"),
    (
        ("page", "#f5f6fb"),
        ("card", "#ffffff"),
        ("marker", "#f2f3fa"),
        ("blue body-gradient endpoint", "#eef1ff"),
        ("green body-gradient endpoint", "#eafff6"),
    ),
)
def test_muted_normal_text_meets_aa_on_every_rendered_surface(
    surface: str, background: str
) -> None:
    """#530 AC-1/2: normal muted text has 4.5:1 contrast on every real surface.

    The named cases are the page, card, marker, and both body-gradient
    endpoints used by the normal-size muted selectors in ``docs/index.html``.
    Keeping each surface as its own parametrized case gives a failing endpoint
    an exclusive, readable result; see review-discipline craft, *Floors decay
    into decoration*.
    """
    muted = bdt.resolve_css_vars(_tokens())["--muted"]
    ratio = _contrast_ratio(muted, background)

    assert ratio >= 4.5, (
        f"muted text {muted} has only {ratio:.4f}:1 contrast on the {surface} "
        f"surface {background}; WCAG 2.1 AA requires 4.5:1"
    )


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


# --------------------------------------------------------------------------- #
# #466 — no token value is hand-copied as a hex literal outside the region
# --------------------------------------------------------------------------- #

#: The sweep is ``scripts/build_design_tokens.py``'s own — the same function the
#: gate's drift stage runs. Every assertion and every control below calls it, so
#: a change to how the shipped stage scans is a change to what they measure. A
#: control that re-implements the predicate agrees with itself and stops
#: controlling the thing that ships (``review-discipline`` craft: *exercise the
#: production path*).
_sweep = bdt.find_token_literals_outside_region


def _duplicate_vars(findings: list) -> set[str]:
    return {f.css_var for f in findings}


def test_hex_token_subject_set_is_live() -> None:
    """Non-vacuity floor for the sweep: its derived subject set is non-empty and
    still holds the vars the page binds by name.

    Membership with named anchors, never cardinality — a pinned count is the very
    drift this guard exists to remove, and it rots on the next token.
    """
    hex_values = bdt.hex_token_values(_tokens())
    assert hex_values, "no token resolves to a hex colour — the sweep has no subjects"
    for anchor in ("--card", "--product-ink", "--quality", "--strategy-ink"):
        assert anchor in hex_values, f"{anchor} is no longer a hex-valued semantic token"
    # The filter's default branch means "not my subject", so a token whose value
    # is not a bare hex literal leaves the sweep silently. Pin the exclusion set
    # by membership rather than pinning only ``--shadow``'s absence: a token
    # added tomorrow as a gradient, ``rgba(…)`` or ``color-mix(…)`` then has to
    # be placed here deliberately — swept in some other form, or recorded as
    # unsweepable — instead of falling through into a hole nothing reports.
    unswept = set(bdt.resolve_css_vars(_tokens())) - set(hex_values)
    assert unswept == {"--shadow"}, (
        "--shadow resolves to a box-shadow declaration, not a hex literal, and is "
        "the only token the hex sweep may skip. These fell out of it unplaced: "
        f"{sorted(unswept - {'--shadow'})}"
    )


def test_the_subject_set_re_derives_from_the_tokens_it_is_handed() -> None:
    """The sweep looks for the values it was *given*, not the ones it shipped with.

    The floor above pins the subject set's **keys**, which come from this
    module's own ``SEMANTIC_TO_CSS_VAR`` map — so it holds identically whether
    the values are resolved from ``tokens.json`` or hand-listed. Every other
    test here feeds the real tokens, whose answer is eighteen six-digit values,
    so that answer written out as a literal satisfies all of them, and so does a
    subject filter narrowed to exactly six digits. Both were measured live at
    review and neither killed anything.

    So feed a synthetic token tree whose correct answer *differs* from today's —
    one value revalued, one in the 3-digit form, one in the 8-digit form with an
    alpha pair — and require the production sweep to find those and to have
    stopped looking for the values they replaced. That second half is what a
    subject set carrying both the derived and the shipped answer would fail.
    """
    shipped = bdt.hex_token_values(_tokens())
    tokens = _tokens()  # a fresh parse, so the edits below cannot leak sideways
    tokens["color"]["primitive"]["neutral"]["card"]["value"] = "#abcdef"
    tokens["color"]["primitive"]["neutral"]["bg"]["value"] = "#fed"
    tokens["color"]["primitive"]["build"]["base"]["value"] = "#11223344"
    revalued = {"--card": "#abcdef", "--bg": "#fed", "--build": "#11223344"}

    derived = bdt.hex_token_values(tokens)
    assert {var: derived.get(var) for var in revalued} == revalued, (
        "the subject set does not re-derive from the tokens it is handed — the "
        f"3-digit and 8-digit forms are token values too: {derived}"
    )

    lines = PAGE.read_text(encoding="utf-8").split("\n")
    end = bdt._find_marker(lines, bdt.END_MARKER)
    planted = "  .planted{" + "; ".join(
        f"--p{i}:{value}" for i, value in enumerate(list(revalued.values()) + [
            shipped["--card"], shipped["--bg"], shipped["--build"]
        ])
    ) + "}"
    page = "\n".join(lines[: end + 2] + [planted] + lines[end + 2 :])

    found = {(f.css_var, f.value) for f in _sweep(page, tokens)}
    assert found == set(revalued.items()), (
        "the sweep must flag the three revalued token values and must no longer "
        f"be looking for the values they replaced: {sorted(found)}"
    )


def test_no_token_value_is_hand_copied_outside_the_generated_region() -> None:
    """#466 AC-1: the page has one source for every token value.

    Every hex literal outside the generated region that byte-duplicates a
    resolved token value is a second copy the drift gate cannot see.
    """
    duplicates = _sweep(PAGE.read_text(encoding="utf-8"), _tokens())
    assert not duplicates, (
        "docs/index.html hand-copies token values outside the generated region. "
        "The drift gate certifies only the region, so a token revalue leaves "
        "these stale. Use the var() instead:\n  "
        + "\n  ".join(d.describe() for d in duplicates)
    )


def test_planted_duplicate_control_paired_splice_into_the_real_page() -> None:
    """#466 AC-2: the sweep is not inert, and its window is neither empty nor
    the whole file.

    A paired splice, per ``review-discipline`` craft: the *same* token value is
    inserted at three locations in the *real* page — after the region, before it,
    and inside it — and the inside splice must get the opposite verdict from the
    other two. The outside splices dying is what proves the sweep reads the
    page's live prose rather than some shorter corpus; the inside splice
    surviving is what proves the exclusion window is really the certified region
    and not the entire file.

    Both sides of that window are exercised on purpose. The window is a closed
    interval, so losing its lower half (``i < begin`` scanned) changes nothing
    the page can show today — the twenty lines above the marker are ``<meta>``
    tags carrying no colour — and a head splice is the only thing that fails when
    it goes. A landing page acquires a ``theme-color`` meta the day someone wants
    a tinted mobile chrome, and that is a hand copy in exactly that dead zone.
    """
    page_text = PAGE.read_text(encoding="utf-8")
    tokens = _tokens()
    hex_values = bdt.hex_token_values(tokens)
    baseline = _sweep(page_text, tokens)

    # Plant a value the page does not already carry outside the region, so each
    # verdict is about the splice alone. Derived, so the control keeps working
    # as the page's own duplicates come and go; if every token were already
    # duplicated there would be no clean probe, and this fails rather than
    # quietly measuring nothing.
    clean = [v for v in sorted(hex_values) if v not in _duplicate_vars(baseline)]
    assert clean, "no token value is free of existing duplicates — no clean probe"
    planted_var = clean[0]
    planted = hex_values[planted_var]

    lines = page_text.split("\n")
    begin = bdt._find_marker(lines, bdt.BEGIN_MARKER)
    end = bdt._find_marker(lines, bdt.END_MARKER)

    # Outside: two lines past the region's end marker — must be flagged, at the
    # line it was planted on.
    outside = lines[: end + 2] + [f"  .planted{{color:{planted}}}"] + lines[end + 2 :]
    planted_line = end + 3  # 1-based line number of the spliced line
    flagged = [f for f in _sweep("\n".join(outside), tokens) if f.css_var == planted_var]
    assert flagged, (
        f"a planted {planted} ({planted_var}) outside the generated region was "
        "not flagged — the sweep is inert"
    )
    assert [f.line for f in flagged] == [planted_line], (
        f"the finding must name the planted site (line {planted_line}): {flagged}"
    )
    assert flagged[0].value == planted, "the finding must carry the literal it found"

    # Before: the same value twice on one line above the begin marker — must be
    # flagged at line 1, and the finding must carry the multiplicity, because a
    # site with three stale copies and a site with one are different repairs.
    head = [f"  .planted{{color:{planted}; background:{planted}}}", *lines]
    head_flagged = [f for f in _sweep("\n".join(head), tokens) if f.css_var == planted_var]
    assert head_flagged, (
        f"a planted {planted} ({planted_var}) BEFORE the begin marker was not "
        "flagged — the sweep's window has lost its lower half"
    )
    assert (head_flagged[0].line, head_flagged[0].copies) == (1, 2), (
        f"the finding must name the planted site and how many copies sit on it: "
        f"{head_flagged[0]!r}"
    )
    assert "line 1 (x2)" in head_flagged[0].describe(), (
        f"the report line must render the multiplicity: "
        f"{head_flagged[0].describe()!r}"
    )

    # Inside: the same value, inside the region — must not be flagged at all.
    inside = lines[: begin + 1] + [f"    --planted:{planted};"] + lines[begin + 1 :]
    inside_findings = _sweep("\n".join(inside), tokens)
    assert planted_var not in _duplicate_vars(inside_findings), (
        f"a {planted} spliced INSIDE the generated region must not be flagged; "
        f"the exclusion window is wrong:\n  {inside_findings}"
    )


def test_the_exclusion_window_stops_exactly_at_the_markers() -> None:
    """The two lines the window *touches* are swept, not swallowed.

    The splices above plant two lines clear of the region, which proves the
    window is roughly right and leaves either bound free to move by one: at
    review, ``end`` → ``end + 1`` and ``begin`` → ``begin - 1`` were both live
    and both survived this module. Each swallows one line of reachable page
    text — the line abutting a marker is ordinary CSS, and it is where a hand
    copy of a token value is *most* likely to be written, because it is the
    text sitting next to the block those values come from.

    So plant on both abutting lines at once and require both back. The two
    findings also have to name distinct sites: a window that collapsed to a
    single line would still report something.
    """
    page_text = PAGE.read_text(encoding="utf-8")
    tokens = _tokens()
    value = bdt.hex_token_values(tokens)["--product-ink"]

    lines = page_text.split("\n")
    begin = bdt._find_marker(lines, bdt.BEGIN_MARKER)
    end = bdt._find_marker(lines, bdt.END_MARKER)
    spliced = (
        lines[:begin]
        + [f"  .before{{color:{value}}}"]
        + lines[begin : end + 1]
        + [f"  .after{{color:{value}}}"]
        + lines[end + 1 :]
    )
    # 1-based: the splice above shifts the end marker down by one, so the line
    # abutting it below is ``end + 1 + 1`` in 0-based terms, ``end + 3`` here.
    abutting = [begin + 1, end + 3]

    findings = _sweep("\n".join(spliced), tokens)
    assert [f.line for f in findings] == abutting, (
        f"a {value} on the line abutting each marker must be swept — the "
        f"window may not eat either neighbour. Expected {abutting}: {findings}"
    )


def test_the_sweep_is_word_bounded_on_the_right() -> None:
    """A token value that is merely a *prefix* of a longer hex literal is a
    different colour, and must not be flagged.

    Splices ``#RRGGBBaa`` — the 8-digit form, whose first six digits are a live
    token value — outside the region. Without the right-hand boundary the sweep
    reads that as the token and reports a duplicate that is not one. The page
    carries no such literal today, so this is the only thing standing between
    the boundary clause and a silent regression: deleting it leaves the rest of
    this module green.
    """
    page_text = PAGE.read_text(encoding="utf-8")
    tokens = _tokens()
    hex_values = bdt.hex_token_values(tokens)
    baseline = _sweep(page_text, tokens)

    probe_var = "--product-ink"
    probe = hex_values[probe_var]
    assert len(probe) == 7, f"{probe_var} is not a 6-digit hex; pick another probe"

    lines = page_text.split("\n")
    end = bdt._find_marker(lines, bdt.END_MARKER)
    # ``#23348f`` + an alpha pair: a longer literal that merely starts with it.
    longer = lines[: end + 2] + [f"  .planted{{color:{probe}a1}}"] + lines[end + 2 :]

    findings = _sweep("\n".join(longer), tokens)
    assert findings == baseline, (
        f"{probe}a1 is not {probe} — the sweep matched a token value inside a "
        f"longer hex literal:\n  {findings}"
    )


def test_the_sweep_matches_a_token_value_in_any_case() -> None:
    """``#23348F`` is the same colour as ``#23348f`` and is the same stale copy.

    ``tokens.json`` and the page both happen to be lowercase today, so nothing
    else in this module distinguishes a case-insensitive sweep from a
    case-sensitive one — dropping the flag would leave every other test green
    while an uppercase hand copy walked straight past the guard.
    """
    page_text = PAGE.read_text(encoding="utf-8")
    tokens = _tokens()
    hex_values = bdt.hex_token_values(tokens)

    probe_var = "--product-ink"
    probe = hex_values[probe_var]
    assert probe.islower(), f"{probe_var} is not lowercase; this probe assumes it is"

    lines = page_text.split("\n")
    end = bdt._find_marker(lines, bdt.END_MARKER)
    upper = lines[: end + 2] + [f"  .planted{{color:{probe.upper()}}}"] + lines[end + 2 :]
    planted_line = end + 3

    findings = _sweep("\n".join(upper), tokens)
    flagged = [f for f in findings if f.css_var == probe_var]
    assert flagged and flagged[0].line == planted_line, (
        f"an uppercase {probe.upper()} outside the region was not flagged as a "
        f"copy of {probe_var}: {findings}"
    )


def test_sweep_refuses_a_page_whose_markers_do_not_resolve() -> None:
    """An unresolvable anchor must fail, never sweep an empty or whole-file
    window (``review-discipline`` craft: the empty comparison set).

    Two ways a marker pair fails to resolve, and only one of them makes
    ``_find_marker`` raise on its own. A *missing* marker it answers for; a pair
    in the wrong order it answers happily, and ``begin <= i <= end`` over a
    reversed pair excludes nothing, so the sweep would silently take the whole
    file as its window — the certified region included. Both cases belong here,
    or the order check has no killer.
    """
    tokens = _tokens()
    hex_values = bdt.hex_token_values(tokens)
    page_text = PAGE.read_text(encoding="utf-8")

    unmarked = page_text.replace(bdt.BEGIN_MARKER, "/* relocated */")
    with pytest.raises(bdt.GeneratedRegionError):
        _sweep(unmarked, tokens)

    reversed_pair = "\n".join(
        [
            f"  {bdt.END_MARKER}",
            f"  .planted{{color:{hex_values['--card']}}}",
            f"  {bdt.BEGIN_MARKER}",
        ]
    )
    with pytest.raises(bdt.GeneratedRegionError):
        _sweep(reversed_pair, tokens)


# --------------------------------------------------------------------------- #
# #466 (amended) — the consumer sweep runs inside the gate, not only in the
# test suite: ``build_design_tokens.py --check`` is the drift stage
# ``scripts/verify.sh`` runs, so the sweep has to fail *there*.
# --------------------------------------------------------------------------- #


def _page_with_lines_after_the_region(extra: list[str]) -> str:
    """The real page with ``extra`` spliced in two lines past the end marker."""
    lines = PAGE.read_text(encoding="utf-8").split("\n")
    end = bdt._find_marker(lines, bdt.END_MARKER)
    return "\n".join(lines[: end + 2] + extra + lines[end + 2 :])


#: The 1-based line number of the first line ``_page_with_lines_after_the_region``
#: splices in — two past the end marker.
_FIRST_PLANTED_LINE = (
    bdt._find_marker(PAGE.read_text(encoding="utf-8").split("\n"), bdt.END_MARKER) + 3
)


def _planted_page(tmp_path: Path, extra: list[str]) -> Path:
    page_path = tmp_path / "index.html"
    page_path.write_text(_page_with_lines_after_the_region(extra), encoding="utf-8")
    return page_path


def _check(page_path: Path) -> int:
    """``main`` in ``--check`` mode — the exact call ``scripts/verify.sh``'s
    design-token stage makes, minus the process boundary (the script's entry
    point is ``raise SystemExit(main())``)."""
    return bdt.main(["--check", "--page", str(page_path), "--tokens", str(TOKENS)])


def test_check_reports_a_token_value_hand_copied_outside_the_region(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """#466 AC-1 (amended): the gate stage itself sweeps the consumer.

    Two planted sites, one carrying two copies, so the report has to name the
    literal, the line it sits on, the ``var(--…)`` that replaces it, and how
    many copies that line carries — a site with two stale copies and a site
    with one are different repairs.
    """
    value = bdt.resolve_css_vars(_tokens())["--product-ink"]
    page_path = _planted_page(
        tmp_path,
        [
            f"  .planted-a{{color:{value}}}",
            f"  .planted-b{{color:{value}; border-color:{value}}}",
        ],
    )

    assert _check(page_path) == 1, (
        "a token value hand-copied outside the generated region must fail the "
        "gate's drift stage"
    )
    captured = capsys.readouterr()
    report = captured.out + captured.err
    assert value in report, "the failure must name the literal"
    assert "var(--product-ink)" in report, "the failure must name the replacement var"
    assert f"line {_FIRST_PLANTED_LINE}:" in report, (
        f"the failure must name the first site's line:\n{report}"
    )
    assert f"line {_FIRST_PLANTED_LINE + 1} (x2):" in report, (
        f"the failure must name the second site and its multiplicity:\n{report}"
    )


def test_check_ignores_a_page_local_shade_outside_the_region(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """#466 AC-2 (amended): the sweep does not over-reach.

    ``#eef1fb`` is a page-local shade the page already carries three times
    outside the region; the nearest token, ``--product-soft``, is ``#e9edfd`` —
    a different colour. Planting more copies exactly where the probe above
    plants its duplicates must leave the gate green, or the stage would be
    demanding a ``var(--…)`` that does not exist. The two probes differ in one
    variable — whether the planted literal is a token value — so this one is
    what separates "the sweep found a hand copy" from "the sweep flags any hex
    literal outside the region".
    """
    shade = "#eef1fb"
    assert shade not in set(bdt.resolve_css_vars(_tokens()).values()), (
        f"{shade} has become a token value; this probe needs a non-token shade"
    )
    page_path = _planted_page(
        tmp_path,
        [
            f"  .planted-a{{color:{shade}}}",
            f"  .planted-b{{color:{shade}; border-color:{shade}}}",
        ],
    )

    assert _check(page_path) == 0, (
        "a page-local shade with no token identity must not fail the gate:\n"
        + "".join(capsys.readouterr())
    )


def test_the_sweep_is_an_additional_failure_condition_not_a_replacement(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """#466 AC-3 (amended): ``--check`` still certifies the generated region.

    Three pages, differing only in which of the two conditions they break, so
    each report is shown to be reachable on its own. A drift-only page must
    still fail with the drift report and *without* the hand-copy report — the
    shape that catches the sweep having been wired in as a replacement for the
    region check, or either report being emitted whenever the other fires.
    """
    value = bdt.resolve_css_vars(_tokens())["--product-ink"]
    drifted = _page_with_lines_after_the_region([]).replace(
        "--ink:#0e1430", "--ink:#000000"
    )
    copied = _page_with_lines_after_the_region([f"  .planted{{color:{value}}}"])
    both = copied.replace("--ink:#0e1430", "--ink:#000000")

    verdicts = {}
    for name, text in (("drift", drifted), ("copy", copied), ("both", both)):
        page_path = tmp_path / f"{name}.html"
        page_path.write_text(text, encoding="utf-8")
        code = _check(page_path)
        captured = capsys.readouterr()
        verdicts[name] = (code, captured.out + captured.err)

    for name, (code, report) in verdicts.items():
        assert code == 1, f"the {name} page must fail the gate:\n{report}"

    assert "has drifted from" in verdicts["drift"][1]
    assert "hand-copies token values" not in verdicts["drift"][1], (
        "a page whose only fault is region drift must not be reported as "
        f"hand-copying anything:\n{verdicts['drift'][1]}"
    )
    assert "hand-copies token values" in verdicts["copy"][1]
    assert "has drifted from" not in verdicts["copy"][1], (
        "a page whose region is clean must not be reported as drifted:\n"
        f"{verdicts['copy'][1]}"
    )
    assert "has drifted from" in verdicts["both"][1]
    assert "hand-copies token values" in verdicts["both"][1], (
        "a page breaking both conditions must report both — the sweep is an "
        f"additional condition, not a replacement:\n{verdicts['both'][1]}"
    )


def test_main_writes_the_region_in_write_mode(tmp_path: Path) -> None:
    """``main`` with no ``--check`` regenerates rather than reporting."""
    tokens_path = tmp_path / "tokens.json"
    tokens_path.write_text(json.dumps(_tokens()))
    page_path = tmp_path / "index.html"
    page_path.write_text(_page_with_markers([]))

    assert bdt.main(["--page", str(page_path), "--tokens", str(tokens_path)]) == 0
    assert bdt.check_generated_region(page_path, tokens_path) == []


def test_main_exits_2_when_the_page_markers_do_not_resolve(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """An unresolvable region is infrastructure, not drift, and keeps its own
    exit code.

    Both halves of ``--check`` resolve the markers, so both can raise; the
    entry point has to turn either into exit 2 rather than a traceback, or the
    gate's failure would be indistinguishable from a red tree.
    """
    page_path = tmp_path / "index.html"
    page_path.write_text(
        PAGE.read_text(encoding="utf-8").replace(bdt.BEGIN_MARKER, "/* relocated */"),
        encoding="utf-8",
    )

    assert _check(page_path) == 2
    err = capsys.readouterr().err
    assert bdt.BEGIN_MARKER in err and "found 0" in err, (
        f"the refusal must name the marker it could not resolve: {err!r}"
    )


def test_check_cli_exits_nonzero_on_a_hand_copied_token_value(tmp_path: Path) -> None:
    """The gate reads an exit code, not a return value.

    ``scripts/verify.sh`` runs this module as a script under ``set -e``, so the
    report above only stops the gate if the process exits non-zero. Runs the
    real command line to prove the entry point carries the verdict across the
    process boundary.
    """
    value = bdt.resolve_css_vars(_tokens())["--product-ink"]
    page_path = _planted_page(tmp_path, [f"  .planted{{color:{value}}}"])

    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--check", "--page", str(page_path), "--tokens", str(TOKENS)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 1, (
        f"the script must exit 1 on a hand-copied token value, not "
        f"{result.returncode}:\n{result.stdout}\n{result.stderr}"
    )
    assert "var(--product-ink)" in result.stdout + result.stderr
