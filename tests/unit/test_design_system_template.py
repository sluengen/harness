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
* **AC-2** — the doc names all eight layers **in order**; the numeric prefix
  *is* the dependency order, so this is a derivation over the layer ids rather
  than a claim about prose.
* **AC-3** — the doc names the stack seam as the adopting repo's job and cites
  both worked shapes (typed TS for a mobile/Expo build; CSS custom properties
  for runtime multi-tenant theming) — scoped to that section, not the whole
  file.
* **AC-4** — `bash scripts/verify.sh` passes; the pre-existing guards this doc
  is subject to (footprint, header/registry parity, distributed-prose cites,
  no repo ids, CHANGELOG bounds) are exercised by the full suite, not
  re-implemented here.

**What changed under #459.** AC-2's four whole-file word pins — `downward`,
`semantic` + `consuming code`, `archetype` + `chrome`, the five frontmatter
field names, the three token tiers — were unanchored co-occurrence over an
860-line document: they could not tell a doc that stated the rules from one
that stated their opposites, and they broke on any rewording that preserved
them. They are gone; the layer-order derivation is what survives as AC-2, and
AC-3's two functions collapse into one anchored tripwire over the stack-seam
section (`code-quality` Part C → *A guard over prose owns structure and
negative space, never meaning*; ADR 0016). The private-path sweep stays as
negative space — its control was re-implementing the predicate on a locally
built token tuple rather than calling it, so the predicate is now extracted
and both the guard and the control run it (`craft.md` → *A positive control
must exercise the predicate, not re-implement it*).
"""

from __future__ import annotations

import re

from tests.unit._prose import REPO_ROOT

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


# --- AC-2: the eight layers, in dependency order -----------------------------


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


def test_stack_seam_is_the_adopting_repos_job_with_both_shapes() -> None:
    """Tripwire — the seam section hands the seam to the adopting repo and
    shows both worked shapes.

    Terms: ``adopting repo`` / ``your repo`` (whose job it is), ``typed`` or
    ``typescript`` (the build-time shape), ``css custom propert`` (the runtime
    shape).

    **This rule has no polarity, and none is faked here.** AC-3 is a *breadth*
    claim — the seam is delegated, and two worked shapes are shown — not a
    prohibition. The section's negation tokens are attached to other rules
    inside it (*generated output never hand-edited*, *the contract does not
    mandate a package*), so binding a negation to this claim would be
    decoration that a benign edit elsewhere in the paragraph could satisfy.
    Whether the section still delegates rather than dictates is the review
    gate's (ADR 0016).
    """
    section = _seam_section().lower()
    assert "adopting repo" in section or "your repo" in section, (
        "the stack-seam section must name the seam as the adopting repo's job, "
        "not something this doc implements"
    )
    assert "typescript" in section or "typed" in section, (
        "the build-time typed-module shape is not cited in the seam section"
    )
    assert "css custom propert" in section, (
        "the runtime CSS-custom-property shape is not cited in the seam section"
    )


# --- Boundary guard (Security): no private repo names or local paths --------

#: Tokens that must never appear in a doc that ships to every consuming repo.
PRIVATE_TOKENS = ("calibrate", "nano-erp", "~/Code/", "/Users/", "/home/")


def _private_token_hits(text: str) -> list[str]:
    """The boundary predicate: which private repo names / local paths leak.

    Shared by the sweep and its control, so the control exercises the *same*
    predicate the sweep calls rather than a re-spelled copy of it — the class
    ``craft.md`` → *A positive control must exercise the predicate, not
    re-implement it* names, and the defect the pre-#459 control carried.
    """
    return [token for token in PRIVATE_TOKENS if token in text]


def test_doc_carries_no_private_repo_names_or_local_paths() -> None:
    hits = _private_token_hits(_text())
    assert not hits, (
        f"templates/design-system.md names private repo(s)/local path(s) {hits!r} "
        "— this doc ships to every consuming repo; cite worked shapes by stack, "
        "not by source repo name or absolute path."
    )


def test_boundary_guard_has_teeth() -> None:
    """A copy carrying a forbidden token would be caught (proves the guard is
    not vacuously green on the real file)."""
    tainted = _text() + "\nSee ~/Code/some-repo/design/ for reference.\n"
    assert _private_token_hits(tainted) == ["~/Code/"], _private_token_hits(tainted)


# --- Anti-vacuity -------------------------------------------------------------


def test_seam_section_is_non_empty() -> None:
    assert _seam_section().strip(), "the stack-seam section parsed empty"
