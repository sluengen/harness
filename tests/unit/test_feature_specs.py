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

Since #280 the module also measures one frontmatter **value**. ``last_updated``
was required to exist and never read, so all four records drifted to declaring a
currency that was false — the same unmeasured-claim family as #275, one file
over. The date guard below reads the value against git and is derived from the
tracked tree, so a fifth feature spec is covered on arrival.
"""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path

import pytest

from tests._cliutil import registered_command_surface
from tests._gitutil import last_commit_date, tracked_files_under

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
_REQUIRED_FRONTMATTER = ("feature", "status", "last_updated", "tickets")


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


# --- The `last_updated` value: a declared currency git can check (#280) ---


def _tracked_feature_spec_md() -> list[Path]:
    """Every tracked ``specs/features/*.md``, sorted.

    Derived from the tracked tree rather than from :data:`_EXPECTED_FEATURES`,
    so a fifth feature spec is governed by the date rule the moment it is
    committed, with no edit here (AC-3). The two subject sets answer different
    questions and deliberately stay separate: ``_EXPECTED_FEATURES`` encodes
    *these four subsystems must each have a record* — a claim a derived set
    cannot make, because deriving it would let the record's absence satisfy it.
    """
    return sorted(p for p in tracked_files_under("specs/features") if p.suffix == ".md")


def _declared_last_updated(path: Path) -> date:
    """The ``last_updated`` value from ``path``'s frontmatter, as a date.

    Both failure modes assert rather than raise, so an uncustomized template
    copy (``last_updated: YYYY-MM-DD``) reports what is wrong with the file
    instead of surfacing a bare ``ValueError`` traceback.
    """
    text = path.read_text(encoding="utf-8")
    fm_match = re.match(r"^---\n(.*?)\n---\n", text, re.DOTALL)
    assert fm_match, f"{path.name} is missing the YAML frontmatter block"
    value_match = re.search(
        r"^last_updated:\s*(\S+)", fm_match.group(1), re.MULTILINE
    )
    assert value_match, (
        f"{path.name} frontmatter is missing the required `last_updated:` key "
        "(templates/feature.md shape)"
    )
    raw = value_match.group(1)
    try:
        return date.fromisoformat(raw)
    except ValueError:
        raise AssertionError(
            f"{path.name} declares `last_updated: {raw}`, which is not an "
            "ISO-8601 YYYY-MM-DD date — an uncustomized template copy or a "
            "typo. The value is read, not just required (#280)."
        ) from None


@pytest.mark.parametrize(
    "path", _tracked_feature_spec_md(), ids=lambda p: p.name
)
def test_feature_spec_last_updated_is_not_behind_its_last_commit(
    path: Path,
) -> None:
    """A feature spec's declared currency is not older than its content (AC-2).

    ``feature_specs: true`` makes these records the contract (``CLAUDE.md``:
    *"Read the relevant as-built record before changing behaviour… It is the
    contract"*), so a frozen date is worse than no date — it actively asserts a
    currency that is false. Requiring the key without reading its value let all
    four drift; ``run-ledger.md`` alone absorbed seven changes while its date sat
    still.

    The bound is ``>=``, so a spec edited and dated today passes on the commit
    that lands it. No upper bound is asserted: a date ahead of the last commit
    claims no false currency, and checking it would need a wall clock in a test.
    """
    committed = last_commit_date(path)
    if committed is None:
        pytest.skip(
            f"git reports no commit for {path.name} — a staged-but-uncommitted "
            "spec. Nothing to compare a declared date against. A truncated "
            "history is *not* this case: it raises ShallowHistoryError, so a "
            "shallow tree goes red and named rather than silently skipping "
            "(#326)."
        )
    declared = _declared_last_updated(path)
    assert declared >= committed, (
        f"specs/features/{path.name} declares last_updated: {declared} but its "
        f"last content commit is {committed}. The as-built record is the "
        "contract (feature_specs: true) — a frozen date asserts a currency that "
        f"is false. Set last_updated to the day this edit commits (>= {committed})."
    )


def test_the_last_updated_guard_covers_every_expected_feature_spec() -> None:
    """The date guard's derived subject set is not silently empty.

    A parametrized guard over a derived set passes vacuously when the set
    evaluates to nothing — a wrong pathspec, or tests run outside a checkout —
    and a vacuous pass here reads exactly like a currency it never measured.
    The floor is the four records AC-1 already requires; it is a subset check,
    not equality, because the set is meant to grow.
    """
    covered = {p.stem for p in _tracked_feature_spec_md()}
    assert set(_EXPECTED_FEATURES) <= covered, (
        "the last_updated guard derives its subjects from the tracked tree, and "
        f"that set ({sorted(covered)}) is missing expected feature specs "
        f"{sorted(set(_EXPECTED_FEATURES) - covered)} — the guard would pass "
        "without measuring them"
    )


def test_an_uncustomized_template_date_fails_with_a_readable_message(
    tmp_path: Path,
) -> None:
    """``last_updated: YYYY-MM-DD`` asserts, rather than raising ``ValueError``.

    The literal placeholder is what a spec copied from ``templates/feature.md``
    carries, so it is the most likely malformed value in practice. A bare
    ``ValueError`` traceback would not say which file or what is wrong with it.
    """
    spec = tmp_path / "placeholder.md"
    spec.write_text(
        "---\nfeature: x\nstatus: implemented\nlast_updated: YYYY-MM-DD\n"
        "tickets: [CAL-1]\n---\n\n## Behaviour\n",
        encoding="utf-8",
    )
    with pytest.raises(AssertionError, match="not an ISO-8601"):
        _declared_last_updated(spec)


def test_a_missing_last_updated_key_fails_with_a_readable_message(
    tmp_path: Path,
) -> None:
    """A frontmatter block with no ``last_updated:`` line names the missing key."""
    spec = tmp_path / "keyless.md"
    spec.write_text(
        "---\nfeature: x\nstatus: implemented\ntickets: [CAL-1]\n---\n\n"
        "## Behaviour\n",
        encoding="utf-8",
    )
    with pytest.raises(AssertionError, match="missing the required"):
        _declared_last_updated(spec)


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
    """Relative ``.md`` links in the **live** migrated surface resolve (AC-3).

    Covers SPEC.md and ``specs/features/`` — the as-built record, which a reader
    is expected to follow. Each link is resolved relative to the file that
    contains it, so a doc moved to a deeper directory whose relative links were
    not re-based against the new depth is caught (the CAL-661 review surfaced
    exactly this in the re-homed banners).

    ``specs/retired/`` is **out of scope**, and that is a decision rather than an
    oversight. A retired spec is a frozen record of how something worked; its
    links rot the moment the tree moves past it, and the only way to keep them
    resolving is to keep editing frozen history — which corrupts the record this
    guard exists alongside. #435 made the choice concrete: retiring the
    ``/harness`` command namespace left seven retired engine docs pointing at
    ``commands/harness.md``, all of them accurate about their own era. The same
    historical-by-category exemption ``specs/retired/`` already carries in the
    retirement sweeps applies here.
    """
    migrated = {_SPEC_INDEX} | {
        p for p in tracked_files_under("specs/features") if p.suffix == ".md"
    }
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


def _verb_model_sections() -> set[str]:
    """The verb names ``verb-model.md`` gives a ``### `<verb>`` section to.

    A verb's section heading opens ``### `<name>` — …``; the tracker-switch and
    routing headings under the same H2 carry no backticked leading token and
    are excluded by the pattern rather than by an exclusion list.
    """
    text = (_FEATURES_DIR / "verb-model.md").read_text(encoding="utf-8")
    return set(re.findall(r"^### `(\w+)`", text, re.MULTILINE))


def test_verb_model_spec_documents_every_audited_verb() -> None:
    """The as-built record carries a section for every audited lifecycle verb.

    ``cli-surface.md`` is current because
    :func:`test_cli_surface_spec_matches_registered_commands` locks it against
    the registered surface. ``verb-model.md`` had no equivalent guard, and so
    ADR 0007's ``design`` verb shipped (#210–#213) into a canonical record that
    gave it no section at all while ``start``, ``review`` and ``close`` each
    had one (#224/#228). Under ``feature_specs: true`` that record *is* the
    contract, so an omission here is a contract defect, not a doc nit.

    The verb set is **derived**, not listed twice: it is
    :data:`tests.unit.test_cli_surface_locked._AUDITED_VERBS` — the one place
    the audited set is declared — intersected against what the CLI actually
    registers, so a verb that is audited but unregistered fails loudly here
    rather than silently shrinking what this guard covers
    (``code-quality`` Part C).
    """
    from harness.cli import app
    from tests.unit.test_cli_surface_locked import _AUDITED_VERBS

    registered = registered_command_surface(app)
    unregistered = _AUDITED_VERBS - registered
    assert not unregistered, (
        f"Audited verbs that the CLI does not register: {sorted(unregistered)}. "
        "Fix the derivation or the registration — do not narrow the audited "
        "set to match, which would shrink this guard silently."
    )
    assert len(_AUDITED_VERBS) >= 2, (
        f"Derived only {_AUDITED_VERBS} as the audited verb set — too few for "
        "this guard to mean anything. An empty or singleton set makes the "
        "check below pass trivially."
    )

    missing = _AUDITED_VERBS - _verb_model_sections()
    assert not missing, (
        f"specs/features/verb-model.md has no '### `<verb>`' section for: "
        f"{sorted(missing)}. It is the as-built record for the verb model "
        "(feature_specs: true), so every audited lifecycle verb must be "
        "documented there as a verb — not only mentioned inside another "
        "verb's scenarios."
    )


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
