"""#239 — templates/design-system.md: the eight-layer scaffold contract.

Distributes the *contract* for standing up a layered design system, not a
vendored tree (accepted proposal `design-system-scaffold`, Option D). An agent
reading this doc generates the tree repo-native; `skills/design-system/SKILL.md`
already points at it via `CONTEXT.md` `paths.design_system` but had nothing at
the other end. This guard pins the doc's presence, registration, and the
content an adopting agent must find, modelled on
:mod:`tests.unit.test_adjustment_template` (registration/header parity) and
:mod:`tests.unit.test_size_guard_reference` (content pinning of a distributed
reference doc).

Acceptance criteria:

* **AC-1** — the file exists, carries a matching version header, and is
  registered in `registry.yaml` under `profiles: [harness]`.
* **AC-2** — the doc names all eight layers (in order), the one-way dependency
  rule, the three rules, the five frontmatter fields, and the three token
  tiers.
* **AC-3** — the doc names the stack seam as the adopting repo's job and cites
  both worked shapes (typed TS for a mobile/Expo build; CSS custom properties
  for runtime multi-tenant theming) — scoped to that section, not the whole
  file.
* **AC-4** — `bash scripts/verify.sh` passes; the pre-existing guards this doc
  is subject to (footprint, header/registry parity, distributed-prose cites,
  no repo ids, CHANGELOG bounds) are exercised by the full suite, not
  re-implemented here.
"""

from __future__ import annotations

import re
from pathlib import Path

# ``tests/unit/test_*.py`` → ``parents[2]`` is the repo (or worktree) root.
REPO_ROOT = Path(__file__).resolve().parents[2]
TEMPLATE = REPO_ROOT / "templates" / "design-system.md"
REGISTRY = REPO_ROOT / "registry.yaml"

#: The eight layer ids, in dependency order — the numeric prefix *is* the order.
LAYERS = (
    "00-brand",
    "01-voice",
    "02-principles",
    "03-tokens",
    "04-primitives",
    "05-patterns",
    "06-archetypes",
    "07-flows",
)


def _section(text: str, heading: str) -> str:
    """The body of the Markdown section whose heading text equals ``heading``,
    up to the next heading of the same-or-higher level or EOF — scopes an
    assertion to one section so a mention elsewhere cannot satisfy it (mirrors
    ``tests/unit/test_design_system_composition.py::_section``)."""
    lines = text.splitlines()
    start: int | None = None
    level = 0
    for i, line in enumerate(lines):
        m = re.match(r"(#+)\s+(.*)$", line)
        if m and m.group(2).strip() == heading:
            start, level = i + 1, len(m.group(1))
            break
    assert start is not None, f"section heading not found: {heading!r}"
    body: list[str] = []
    for line in lines[start:]:
        m = re.match(r"(#+)\s+", line)
        if m and len(m.group(1)) <= level:
            break
        body.append(line)
    return "\n".join(body)


def _text() -> str:
    return TEMPLATE.read_text(encoding="utf-8")


# --- AC-1: presence, header, registration ------------------------------------


def test_template_exists_with_version_header() -> None:
    assert TEMPLATE.exists(), "templates/design-system.md must exist (#239)."
    assert re.search(r"guidance:template-design-system@[\d.]+", _text()), (
        "templates/design-system.md must carry a "
        "`guidance:template-design-system@x.y.z` header."
    )


def test_registered_in_harness_profile_with_matching_version() -> None:
    header_match = re.search(r"guidance:template-design-system@([\d.]+)", _text())
    assert header_match, "header missing — see test_template_exists_with_version_header"
    header_version = header_match.group(1)

    entry = re.search(
        r"templates/design-system\.md:\s*\{[^}]*\}", REGISTRY.read_text()
    )
    assert entry, (
        "registry.yaml files: must list templates/design-system.md with "
        "id: template-design-system (#239)."
    )
    assert "id: template-design-system" in entry.group(0)
    assert "profiles: [harness]" in entry.group(0) or "harness" in entry.group(0)

    registry_version = re.search(r"version:\s*([\d.]+)", entry.group(0))
    assert registry_version, f"no version field in registry entry: {entry.group(0)!r}"
    assert registry_version.group(1) == header_version, (
        f"header version {header_version!r} does not match registry.yaml's "
        f"{registry_version.group(1)!r}."
    )


# --- AC-2: the eight layers, the dependency rule, the three rules, the -------
# --- frontmatter contract, the three token tiers -----------------------------


def test_names_all_eight_layers_in_order() -> None:
    text = _text()
    positions = [text.find(layer) for layer in LAYERS]
    assert all(p != -1 for p in positions), (
        f"not every layer id is named: {dict(zip(LAYERS, positions, strict=True))}"
    )
    assert positions == sorted(positions), (
        "the eight layers are not listed in ascending dependency order — a "
        "shuffled list loses the order the numeric prefix encodes."
    )


def test_states_the_one_way_dependency_rule() -> None:
    text = _text().lower()
    assert "downward" in text or "one-way" in text, (
        "the doc must state the one-way dependency rule — a layer may consume "
        "the layers above/below it, nothing reaches the other way."
    )


def test_states_the_three_rules() -> None:
    text = _text().lower()
    assert "downward" in text, "rule 1 (no downward reach) is not stated"
    assert "semantic" in text and "consuming code" in text, (
        "rule 2 (semantic tokens only in consuming code) is not stated"
    )
    assert "archetype" in text and "chrome" in text, (
        "rule 3 (chrome belongs to the archetype) is not stated"
    )


def test_names_the_five_frontmatter_fields() -> None:
    text = _text()
    for field in ("layer", "kind", "status", "owner", "last_updated"):
        assert field in text, f"frontmatter field {field!r} is not named"


def test_names_the_three_token_tiers() -> None:
    text = _text().lower()
    for tier in ("primitive", "semantic", "component"):
        assert tier in text, f"token tier {tier!r} is not named"


# --- AC-3: the stack seam is the adopting repo's job, both worked shapes ----
# --- cited, scoped to the seam section ---------------------------------------


def _seam_section() -> str:
    text = _text()
    for heading in (
        "The stack seam",
        "Stack seam",
        "The stack seam — the adopting repo's job",
    ):
        try:
            return _section(text, heading)
        except AssertionError:
            continue
    raise AssertionError(
        "no stack-seam heading found in templates/design-system.md — expected "
        "a section naming the seam as the adopting repo's job"
    )


def test_stack_seam_is_the_adopting_repos_job() -> None:
    section = _seam_section().lower()
    assert "adopting repo" in section or "your repo" in section, (
        "the stack-seam section must name the seam as the adopting repo's job, "
        "not something this doc implements"
    )


def test_cites_both_worked_seam_shapes() -> None:
    section = _seam_section().lower()
    assert "typescript" in section or "typed" in section, (
        "the build-time typed-module shape is not cited in the seam section"
    )
    assert "css custom propert" in section, (
        "the runtime CSS-custom-property shape is not cited in the seam section"
    )


# --- Boundary guard (Security): no private repo names or local paths --------


def test_doc_carries_no_private_repo_names_or_local_paths() -> None:
    text = _text()
    forbidden = ("calibrate", "nano-erp", "~/Code/", "/Users/", "/home/")
    hits = [token for token in forbidden if token in text]
    assert not hits, (
        f"templates/design-system.md names private repo(s)/local path(s) {hits!r} "
        "— this doc ships to every consuming repo; cite worked shapes by stack, "
        "not by source repo name or absolute path."
    )


def test_boundary_guard_has_teeth() -> None:
    """A copy carrying a forbidden token would be caught (proves the guard is
    not vacuously green on the real file)."""
    tainted = _text() + "\nSee ~/Code/some-repo/design/ for reference.\n"
    hits = [token for token in ("calibrate", "nano-erp", "~/Code/") if token in tainted]
    assert hits == ["~/Code/"], hits


# --- Anti-vacuity -------------------------------------------------------------


def test_seam_section_is_non_empty() -> None:
    assert _seam_section().strip(), "the stack-seam section parsed empty"
