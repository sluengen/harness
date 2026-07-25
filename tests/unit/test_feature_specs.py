"""CAL-661 — the harness's as-built record lives in ``specs/features/``.

With ``feature_specs`` on (``CONTEXT.md``, CAL-660), the harness dogfoods the
feature-spec surface it publishes: the as-built record of each current
verb-model subsystem is a ``specs/features/<feature>.md`` in the
``templates/feature.md`` shape, not a design doc under ``specs/``. This guard is
the executable form of the migration's acceptance criteria:

* **AC-1** — each current verb-model subsystem (the verb model, the run ledger,
  the worktree lifecycle, the CLI surface) has a ``specs/features/<feature>.md``
  in the feature-spec shape: the ``templates/feature.md`` frontmatter keys and a
  ``## Behaviour`` section (the canonical "how does it work?" answer).
* **AC-3** — the SPEC.md index has no dangling links: every relative ``.md``
  link in SPEC.md resolves to a file git tracks. A row that points the reader at
  a moved or never-created spec is worse than none.

The check is structural: a regression that deletes a feature spec, drops a
required section, or leaves a dangling SPEC.md link fails here.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from tests._cliutil import registered_command_surface
from tests._gitutil import tracked_files_under

_REPO_ROOT = Path(__file__).resolve().parents[2]
_FEATURES_DIR = _REPO_ROOT / "specs" / "features"
_SPEC_INDEX = _REPO_ROOT / "SPEC.md"

#: The current verb-model subsystems, each of which must carry a feature spec
#: (AC-1). The slug is the ``specs/features/<slug>.md`` basename.
_EXPECTED_FEATURES = (
    "verb-model",
    "run-ledger",
    "worktree-lifecycle",
    "cli-surface",
)

#: Frontmatter keys required by ``templates/feature.md``.
_REQUIRED_FRONTMATTER = ("feature", "status", "last_updated", "linear")


def _feature_path(slug: str) -> Path:
    return _FEATURES_DIR / f"{slug}.md"


def _tracked_feature_specs() -> set[Path]:
    return tracked_files_under("specs/features")


@pytest.mark.parametrize("slug", _EXPECTED_FEATURES)
def test_feature_spec_exists_and_is_tracked(slug: str) -> None:
    """Each current verb-model subsystem has a tracked feature spec (AC-1)."""
    path = _feature_path(slug)
    assert path.resolve() in _tracked_feature_specs(), (
        f"expected feature spec {path.relative_to(_REPO_ROOT)} to exist and be "
        "git-tracked — AC-1 requires each current verb-model subsystem to carry "
        "a specs/features/<feature>.md as-built record"
    )


@pytest.mark.parametrize("slug", _EXPECTED_FEATURES)
def test_feature_spec_has_template_frontmatter(slug: str) -> None:
    """Each feature spec carries the ``templates/feature.md`` frontmatter keys."""
    text = _feature_path(slug).read_text(encoding="utf-8")
    fm_match = re.match(r"^---\n(.*?)\n---\n", text, re.DOTALL)
    assert fm_match, f"{slug}.md is missing the YAML frontmatter block"
    frontmatter = fm_match.group(1)
    for key in _REQUIRED_FRONTMATTER:
        assert re.search(rf"^{key}:", frontmatter, re.MULTILINE), (
            f"{slug}.md frontmatter is missing the required `{key}:` key "
            "(templates/feature.md shape)"
        )


@pytest.mark.parametrize("slug", _EXPECTED_FEATURES)
def test_feature_spec_has_behaviour_section(slug: str) -> None:
    """Each feature spec has the canonical ``## Behaviour`` section (AC-1)."""
    text = _feature_path(slug).read_text(encoding="utf-8")
    assert re.search(r"^## Behaviour\b", text, re.MULTILINE), (
        f"{slug}.md is missing the `## Behaviour` section — the canonical "
        "answer to 'how does it work?' (templates/feature.md)"
    )


#: A relative markdown link target ending in ``.md`` — e.g. ``](specs/x.md)``
#: or ``](specs/features/y.md#anchor)``. Absolute (``http``) links are skipped.
_MD_LINK = re.compile(r"\]\((?!https?://)([^)#]+\.md)(?:#[^)]*)?\)")


def test_spec_index_has_no_dangling_links() -> None:
    """Every relative ``.md`` link in SPEC.md resolves to a tracked file (AC-3)."""
    tracked = tracked_files_under(".")
    text = _SPEC_INDEX.read_text(encoding="utf-8")
    dangling: list[str] = []
    for target in _MD_LINK.findall(text):
        resolved = (_REPO_ROOT / target).resolve()
        if resolved not in tracked:
            dangling.append(target)
    assert not dangling, (
        "SPEC.md links to spec files that are not tracked (dangling links): "
        f"{sorted(set(dangling))}"
    )


def test_no_dangling_links_in_the_migrated_specs() -> None:
    """Relative ``.md`` links in the migrated surface resolve (AC-3).

    Covers SPEC.md and every file this migration authors or moves —
    ``specs/features/`` (the as-built record) and ``specs/retired/`` (the
    re-homed engine docs). Each link is resolved relative to the file that
    contains it, so a doc moved to a deeper directory whose relative links were
    not re-based against the new depth is caught (the CAL-661 review surfaced
    exactly this in the re-homed banners).
    """
    migrated = (
        {_SPEC_INDEX}
        | {p for p in tracked_files_under("specs/features") if p.suffix == ".md"}
        | {p for p in tracked_files_under("specs/retired") if p.suffix == ".md"}
    )
    dangling: list[str] = []
    for path in sorted(migrated):
        for target in _MD_LINK.findall(path.read_text(encoding="utf-8")):
            if not (path.parent / target).resolve().exists():
                dangling.append(f"{path.relative_to(_REPO_ROOT)} -> {target}")
    assert not dangling, f"dangling relative .md links in the migrated specs: {dangling}"


# --- Semantic coverage: the canonical record must match production behaviour ---
# Shape + link checks pass even when the prose contradicts the code. These guards
# tie specific documented contracts to the code that implements them, so a spec
# that drifts from production behaviour fails here (CAL-661 review).


def _registered_surface() -> set[str]:
    """Every top-level command and sub-app the Typer app registers."""
    from harness.cli import app

    return registered_command_surface(app)


def _documented_surface() -> set[str]:
    """The top-level ``harness <cmd>`` tokens in cli-surface.md's surface block."""
    text = _feature_path("cli-surface").read_text(encoding="utf-8")
    blocks = re.findall(r"```[a-z]*\n(.*?)```", text, re.DOTALL)
    surface = next(b for b in blocks if "harness start" in b)
    cmds: set[str] = set()
    for line in surface.splitlines():
        line = line.strip()
        if line.startswith("harness "):
            cmds.add(line.split()[1])
    return cmds


def test_cli_surface_spec_matches_registered_commands() -> None:
    """cli-surface.md documents exactly the commands the CLI registers.

    Catches the drift class the review found (a doc naming a command the CLI
    does not implement, or omitting one it does).
    """
    assert _documented_surface() == _registered_surface()


def _registered_flags() -> dict[str, set[str]]:
    """Map each command / subcommand path to its registered ``--long`` flags."""
    import click
    import typer

    from harness.cli import app

    flags: dict[str, set[str]] = {}

    def walk(cmd: object, prefix: list[str]) -> None:
        if isinstance(cmd, click.Group):
            for name, sub in cmd.commands.items():
                walk(sub, [*prefix, name])
            return
        opts: set[str] = set()
        for param in cmd.params:  # type: ignore[attr-defined]
            for opt in (*param.opts, *param.secondary_opts):
                if opt.startswith("--"):
                    opts.add(opt)
        flags[" ".join(prefix)] = opts

    root = typer.main.get_command(app)
    for name, sub in root.commands.items():  # type: ignore[attr-defined]
        walk(sub, [name])
    return flags


def _documented_flags() -> dict[str, set[str]]:
    """Map each documented command path to the ``--flags`` cli-surface.md shows."""
    text = _feature_path("cli-surface").read_text(encoding="utf-8")
    blocks = re.findall(r"```[a-z]*\n(.*?)```", text, re.DOTALL)
    surface = next(b for b in blocks if "harness start" in b)
    documented: dict[str, set[str]] = {}
    for line in surface.splitlines():
        line = line.split("#", 1)[0].strip()
        if not line.startswith("harness "):
            continue
        tokens = line.split()[1:]
        path = [t for t in tokens if t[0] not in "<[-"]
        opts = set(re.findall(r"--[a-z][a-z-]*", line))
        documented[" ".join(path)] = opts
    return documented


def test_cli_surface_flags_are_real() -> None:
    """Every flag cli-surface.md documents is a real registered flag (no phantoms)."""
    registered = _registered_flags()
    phantom: list[str] = []
    for path, opts in _documented_flags().items():
        known = registered.get(path, set())
        for opt in opts:
            if opt not in known:
                phantom.append(f"{path} {opt}")
    assert not phantom, (
        f"cli-surface.md documents flags the CLI does not register: {phantom}"
    )


def test_verb_output_keys_match_the_models() -> None:
    """Every field of the verb output models is documented in verb-model.md."""
    from harness.cli.close import CloseOutput
    from harness.cli.review import ReviewOutput
    from harness.cli.start import StartOutput

    verb_model = _feature_path("verb-model").read_text(encoding="utf-8")
    missing: list[str] = []
    for model in (StartOutput, ReviewOutput, CloseOutput):
        for field in model.model_fields:
            if f"`{field}`" not in verb_model:
                missing.append(f"{model.__name__}.{field}")
    assert not missing, (
        f"verb-model.md omits documented output keys present in the models: {missing}"
    )


def test_worktree_spec_matches_path_constants() -> None:
    """worktree-lifecycle.md states the path/branch conventions the code uses."""
    from harness.identity import WORKTREES_SUBDIR

    text = _feature_path("worktree-lifecycle").read_text(encoding="utf-8")
    assert str(WORKTREES_SUBDIR) in text, (
        f"worktree-lifecycle.md must state the worktree root {WORKTREES_SUBDIR}"
    )
    assert "harness/<run_id>" in text, (
        "worktree-lifecycle.md must state the `harness/<run_id>` branch pattern"
    )


def test_verb_specs_name_the_code_verdicts_and_statuses() -> None:
    """The verdict and run-status literals in the specs match the code."""
    from typing import get_args

    from harness.cli.review import Verdict

    verb_model = _feature_path("verb-model").read_text(encoding="utf-8")
    for verdict in get_args(Verdict):
        assert f"`{verdict}`" in verb_model, (
            f"verb-model.md must name the `{verdict}` review verdict"
        )

    ledger = _feature_path("run-ledger").read_text(encoding="utf-8")
    for status in ("open", "closed"):
        assert f"`{status}`" in ledger, (
            f"run-ledger.md must name the `{status}` verb-model run status"
        )
