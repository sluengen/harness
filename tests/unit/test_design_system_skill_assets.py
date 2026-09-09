"""#626 — the design system ships as skill-attached assets, or a consumer gets none of it.

`/harness:hydrate` step 11 copies a skill's shipped assets to the destination
that skill's own guidance names. `design-system` is the first skill to use that
step, and what it carries is the whole of what a consumer receives: the eight
tiers, the token source, and the builder that resolves it into a page. A tier
that never entered the skill's asset tree is a layer the consumer's design
system silently lacks — the hydration reports a copy and the tree is short a
directory, with nothing saying so.

**Admitted under ADR 0017 D5 class (c), asset integrity, with one class (e)
tree-consistency assertion.** The subject is which files the tree carries and
whether the path `harness.yaml` declares corresponds to them — never what any
of those files says. The reference-implementation warning AC-3 requires is
prose, verified in review, and carries no predicate here: a guard over document
meaning is what that rule refuses.

**Why the tracked tree.** `test_seeded_assets_are_tracked.py` already holds every
file under `skills/` to the index, so this module asks the narrower question that
one cannot: not *is what is on disk tracked*, but *is the required set present at
all*. A tier deleted from both disk and index passes that guard and fails this one.
"""

from __future__ import annotations

from tests._gitutil import tracked_files_under
from tests.unit._prose import REPO_ROOT

#: The skill whose assets hydration copies out.
SKILL_DIR = "skills/design-system"

#: Where its shipped assets live, relative to the repo root.
ASSETS = f"{SKILL_DIR}/assets"

#: The eight tiers, in dependency order. The zero-padded prefix *is* that order,
#: so the names are the contract and not merely labels.
TIERS = (
    "00-brand",
    "01-voice",
    "02-principles",
    "03-tokens",
    "04-primitives",
    "05-patterns",
    "06-archetypes",
    "07-flows",
)


def _tracked_asset_paths() -> set[str]:
    """Every tracked file under the skill, as repo-relative POSIX strings."""
    return {
        path.relative_to(REPO_ROOT).as_posix()
        for path in tracked_files_under(SKILL_DIR, repo_root=REPO_ROOT)
    }


def test_every_tier_is_present_in_the_shipped_asset_tree() -> None:
    """AC-1: all eight tiers reach a consumer, not merely the substantive ones."""
    tracked = _tracked_asset_paths()
    missing = [
        tier
        for tier in TIERS
        if not any(path.startswith(f"{ASSETS}/{tier}/") for path in tracked)
    ]
    assert not missing, (
        f"{ASSETS} carries no tracked file under {missing} — hydration would copy "
        f"out a design system missing those tiers. Tracked asset paths: "
        f"{sorted(tracked)}"
    )


def test_the_token_source_and_its_builder_travel_with_the_skill() -> None:
    """AC-1: the token *mechanism*, not just the structure, is what ships."""
    tracked = _tracked_asset_paths()
    required = {
        f"{ASSETS}/03-tokens/tokens.json",
        f"{ASSETS}/build_design_tokens.py",
    }
    assert required <= tracked, (
        f"{sorted(required - tracked)} is not tracked under {ASSETS}; the skill "
        f"ships a structure with no way to resolve a token into a page"
    )


def test_the_skill_has_a_skill_file() -> None:
    """A directory under `skills/` with no `SKILL.md` is not a skill.

    Hydration step 11 copies assets to the destination *the skill's own guidance*
    names, so the guidance is load-bearing rather than decorative.
    """
    assert (REPO_ROOT / SKILL_DIR / "SKILL.md").is_file(), (
        f"{SKILL_DIR}/SKILL.md is absent, so nothing names where these assets go"
    )


def test_this_repo_consumes_the_assets_where_it_declares_them() -> None:
    """Class (e): `paths.design_system` and the asset tree are the same directory.

    AC-2's other half. This repo keeps building `docs/index.html` from these
    tokens, so its declared design directory has to *be* the shipped tree rather
    than a second copy of it — two copies is the drift this system exists to
    remove.
    """
    declared = ""
    for line in (REPO_ROOT / "harness.yaml").read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped.startswith("design_system:") and "paths" not in stripped:
            declared = stripped.split(":", 1)[1].split("#")[0].strip()
    assert declared, "harness.yaml declares no paths.design_system"

    resolved = (REPO_ROOT / declared).resolve()
    assert resolved == (REPO_ROOT / ASSETS).resolve(), (
        f"harness.yaml points paths.design_system at {declared!r}, but the shipped "
        f"assets are at {ASSETS}/ — this repo would be reading a different tree "
        f"from the one it ships"
    )
    assert resolved.is_dir(), f"{declared} does not exist"


def test_the_tiers_are_where_the_builder_looks_for_them() -> None:
    """The builder resolves its token source relative to its own directory.

    That is what lets one file serve both this repo — whose design directory is
    nested three deep under `skills/` — and a consumer whose `paths.design_system`
    is a repo-root `design/`. A builder carrying a fixed repo-relative path works
    in exactly one of those.
    """
    builder = REPO_ROOT / ASSETS / "build_design_tokens.py"
    tokens = builder.parent / "03-tokens" / "tokens.json"
    assert tokens.is_file(), (
        f"{builder} sits beside no 03-tokens/tokens.json; its token default cannot "
        f"resolve from its own location"
    )
