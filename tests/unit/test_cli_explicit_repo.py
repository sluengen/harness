"""#306 — a verb's target repo is stated, not inferred (ADR 0012).

``$(pwd)`` was the only channel for naming a verb's target repo, so every call
meant something different depending on where the calling shell happened to be.
That broke verb calls on five separate occasions (#146, #147, #150, #155,
#159). This ticket puts an explicit ``--repo`` on every repo-acting command and
a deprecation warning behind the implicit form, which keeps working for one
release.

The guards, and why each is shaped the way it is:

* **AC-1 — the derived surface.** The leaf set comes from the *registered*
  Typer app, walked recursively, not from a list: ``tests._cliutil`` reports
  ``worktrees`` and ``promote`` as group names only, and the repo argument is
  declared on the leaves under them. A command added later with no ``--repo``
  fails here, which is the drift the AC names. ``_NO_REPO`` is asserted to be a
  subset of the derived leaves, so a stale exemption fails loudly rather than
  quietly excusing nothing.
* **The default is ``None``, never ``Path(".")``.** With a ``Path(".")`` default
  a command cannot tell *omitted* from an explicit ``--repo .``, so it would
  have to warn a caller who did state its intent. Pinning the default is what
  makes the deprecation expressible at all — and it is the property the
  non-vacuity floor below exercises against synthetic source.
* **AC-2 — one warning, stdout untouched.** Asserted by running each command
  twice, implicit and explicit, and comparing bytes. "Byte-identical to today"
  is operationalized against the explicit invocation rather than a recorded
  string: the explicit form *is* today's behaviour, so the comparison proves the
  deprecation added nothing to the JSON contract the orchestrating loop parses.
* **AC-3 — the named repo beats the CWD**, shown from a CWD that is not a repo
  at all, so a pass cannot be explained by the two paths coinciding.
* **The seam guard.** ``Path.cwd()`` may appear in ``harness/cli/`` only in
  ``_repo.py``. A verb that re-reads the CWD deep in its call stack is the bug
  class this ticket closes, and it is also how a second, unwanted warning would
  appear — so "exactly one warning" is a property of the call graph, held by
  this guard, rather than of a suppression latch.
"""

from __future__ import annotations

import json
import os
from collections.abc import Iterator
from pathlib import Path

import click
import pytest
import typer
import typer.main
from typer.testing import CliRunner

from harness.cli._repo import IMPLICIT_REPO_WARNING_PREFIX
from tests._asyncutil import run_sync
from tests._gitutil import init_repo, tracked_py_sources

cli_runner = CliRunner()

REPO_ROOT = Path(__file__).resolve().parents[2]
RUNBOOK = REPO_ROOT / "RUNBOOK.md"

#: The one option name a caller can rely on everywhere. ``worktrees`` keeps
#: ``--repo-root`` as a second name on the same parameter so existing callers
#: are undisturbed, but the surface has a single canonical spelling.
CANONICAL_REPO_OPTION = "--repo"

#: Leaves that legitimately take no repo argument. ``version`` prints the
#: package version and touches no repo, ledger, or CONTEXT.md. ``serve`` (#307)
#: is exempt for the opposite reason: it acts on *no single* repo but on every
#: repo in ``HARNESS_WORKSPACE_ROOTS``, resolving each request's target from the
#: request itself — a ``--repo`` on the host process would name one repo it then
#: had to ignore, which is the ambient-target confusion this guard exists to end.
_NO_REPO = frozenset({"version", "serve"})


# ---------------------------------------------------------------------------
# The derivation — leaves of the registered app
# ---------------------------------------------------------------------------


def _leaves(command: click.Command, prefix: str = "") -> Iterator[tuple[str, click.Command]]:
    """Every leaf command reachable from ``command``, as ``(invocation, leaf)``.

    Recurses through groups, so ``promote pr`` and ``worktrees cleanup`` are
    enumerated as leaves rather than collapsed into their group name.
    """
    if isinstance(command, click.Group):
        for name, child in command.commands.items():
            yield from _leaves(child, prefix=f"{prefix}{name} ")
    else:
        yield prefix.strip(), command


def leaf_commands(app: typer.Typer) -> dict[str, click.Command]:
    return dict(_leaves(typer.main.get_command(app)))


def _option_names(leaf: click.Command) -> set[str]:
    return {opt for param in leaf.params for opt in getattr(param, "opts", ())}


def _repo_param(leaf: click.Command) -> click.Parameter | None:
    for param in leaf.params:
        if CANONICAL_REPO_OPTION in getattr(param, "opts", ()):
            return param
    return None


def cwd_defaulted_params(app: typer.Typer) -> dict[str, str]:
    """Leaves declaring a parameter that defaults to ``Path(".")``.

    The ambient-CWD default ADR 0012 retires, derived independently of what any
    flag is *called* — which is what keeps the assertion below from being a
    statement about the set it was derived from.
    """
    out: dict[str, str] = {}
    for invocation, leaf in _leaves(typer.main.get_command(app)):
        for param in leaf.params:
            if isinstance(param.default, Path) and param.default == Path("."):
                out[invocation] = param.name
    return out


def _harness_leaves() -> dict[str, click.Command]:
    from harness.cli import app

    return leaf_commands(app)


# ---------------------------------------------------------------------------
# AC-1 — every repo-acting command accepts the explicit argument
# ---------------------------------------------------------------------------


def test_the_leaf_enumeration_reaches_into_the_sub_apps() -> None:
    """Anti-vacuity for the enumeration itself: a derivation that silently
    stopped at the top level would make every parametrized case below pass
    while leaving ``promote`` and ``worktrees`` unguarded."""
    leaves = _harness_leaves()
    assert "promote pr" in leaves, sorted(leaves)
    assert "worktrees cleanup" in leaves, sorted(leaves)


def test_the_no_repo_exemption_names_only_real_leaves() -> None:
    """A stale exemption must fail loudly rather than excuse nothing."""
    assert set(_harness_leaves()) >= _NO_REPO


@pytest.mark.parametrize("invocation", sorted(set(_harness_leaves()) - _NO_REPO))
def test_command_accepts_the_explicit_repo_argument(invocation: str) -> None:
    """AC-1: every repo-acting leaf accepts ``--repo``."""
    names = _option_names(_harness_leaves()[invocation])
    assert CANONICAL_REPO_OPTION in names, (
        f"`harness {invocation}` acts on a repo but does not accept "
        f"{CANONICAL_REPO_OPTION}: {sorted(names)}"
    )


@pytest.mark.parametrize("invocation", sorted(set(_harness_leaves()) - _NO_REPO))
def test_the_repo_argument_can_represent_its_own_omission(invocation: str) -> None:
    """The default is ``None``: omission and an explicit ``--repo .`` must be
    distinguishable, or the deprecation warning cannot be emitted on one
    without also firing on the other."""
    param = _repo_param(_harness_leaves()[invocation])
    assert param is not None
    assert param.default is None, (
        f"`harness {invocation}` defaults --repo to {param.default!r}; "
        "omission must be representable as None"
    )


def test_no_command_keeps_an_ambient_cwd_default() -> None:
    """The ambient-CWD default is gone from the whole registered surface.

    Derived from the parameter *defaults*, independent of what any flag is
    named — so a future command that reintroduces the channel under a new name
    fails here even though it never says "repo".
    """
    from harness.cli import app

    assert cwd_defaulted_params(app) == {}


def test_the_cwd_default_derivation_sees_a_novel_flag_name() -> None:
    """The non-vacuity floor for :func:`cwd_defaulted_params`.

    Run the real derivation over synthetic source carrying a value nothing in
    the production tree declares — a ``Path(".")`` default on an option called
    ``--target-tree``. Without this, the emptiness assertion above would be
    equally satisfied by a derivation that had quietly stopped finding
    anything.
    """
    synthetic = typer.Typer()
    nested = typer.Typer()
    cwd_default = typer.Option(Path("."), "--target-tree")

    @synthetic.command("toplevel")
    def _toplevel(target_tree: Path = cwd_default) -> None:  # pragma: no cover
        ...

    @nested.command("leaf")
    def _leaf(target_tree: Path = cwd_default) -> None:  # pragma: no cover
        ...

    synthetic.add_typer(nested, name="group")

    assert cwd_defaulted_params(synthetic) == {
        "toplevel": "target_tree",
        "group leaf": "target_tree",
    }


# ---------------------------------------------------------------------------
# AC-2 / AC-3 — the behaviour, through the real CLI
# ---------------------------------------------------------------------------

#: The promotion the ``repo`` fixture seeds, so the promotion subcommands below
#: execute their real bodies instead of exiting at the not-found branch.
_SEEDED_PROMOTION = "seeded-p1"

#: One runnable invocation per repo-acting leaf, minus ``--repo``/``--db``.
#: Every entry refuses deterministically against an empty ledger, before any
#: tracker or network call — the assertion is about the repo argument and
#: nothing else.
_MINIMAL_ARGV: dict[str, list[str]] = {
    "start": ["start", "T-1"],
    "design": ["design"],
    "review": ["review"],
    "certify": ["certify"],
    "close": ["close", "T-1"],
    "checkpoint": ["checkpoint"],
    "cancel": ["cancel", "01J"],
    "defer": ["defer", "T-1", "--reason", "x"],
    "release": ["release", "T-1", "--resolution", "x"],
    "reclaim": ["reclaim", "01J"],
    "doctor": ["doctor"],
    "status": ["status", "01J"],
    "logs": ["logs", "01J"],
    "events": ["events", "01J"],
    "runs": ["runs"],
    "stats": ["stats"],
    "worktrees list": ["worktrees", "list"],
    "worktrees cleanup": ["worktrees", "cleanup"],
    "promote start": ["promote", "start"],
    "promote continue": ["promote", "continue", "--promotion-id", _SEEDED_PROMOTION],
    "promote status": ["promote", "status", "--promotion-id", _SEEDED_PROMOTION],
    "promote pr": ["promote", "pr", "--promotion-id", _SEEDED_PROMOTION],
    "promote escalate": ["promote", "escalate", "--promotion-id", _SEEDED_PROMOTION],
}


def test_every_repo_acting_leaf_has_a_behavioural_case() -> None:
    """A leaf added later cannot silently skip AC-2's coverage."""
    assert set(_MINIMAL_ARGV) == set(_harness_leaves()) - _NO_REPO


@pytest.fixture
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A repo whose *default* ledger already holds the promotion ``_MINIMAL_ARGV``
    names, so the promotion subcommands run their real bodies.

    Seeding is load-bearing, not setup convenience. With an empty ledger,
    ``promote pr`` and ``promote escalate`` exit at ``_read_or_not_found``'s
    not-found branch — *before* the code that resolves the repo a second time.
    A double deprecation warning shipped behind exactly that: the AC-2 cases
    passed while the invocation they were meant to cover never reached the line
    that broke the invariant. The ledger goes at the default path, with no
    ``--db`` in the argv, because the resolution under test is the default one.
    """
    root = tmp_path / "repo"
    init_repo(root)
    monkeypatch.setenv("HARNESS_WORKSPACE_ROOTS", str(tmp_path))

    from harness.state import promotions

    run_sync(
        promotions.insert_promotion(
            promotions.Promotion(
                promotion_id=_SEEDED_PROMOTION,
                repo=str(root),
                from_branch="dev",
                to_branch="staging",
                status="needs_ticket",
                created_at="2026-08-05T00:00:00+00:00",
                updated_at="2026-08-05T00:00:00+00:00",
                promotion_branch="promote/2026-08-05-dev-to-staging",
            ),
            db_path=root / ".harness" / "harness.db",
        )
    )
    return root


def test_the_seeded_promotion_is_actually_reachable(repo: Path) -> None:
    """Floor for the fixture above: prove the promotion subcommands get *past*
    the not-found branch.

    Without this, a fixture that silently stopped seeding — a renamed id, a
    moved default ledger path — would return the AC-2 cases to the state that
    hid the double-warning bug, and every one of them would still pass.
    """
    result = _invoke_from(repo, _MINIMAL_ARGV["promote status"])

    assert '"error": "not_found"' not in result.stdout, result.stdout


def _invoke_from(cwd: Path, argv: list[str]) -> click.testing.Result:
    from harness.cli import app

    previous = Path.cwd()
    os.chdir(cwd)
    try:
        return cli_runner.invoke(app, argv)
    finally:
        os.chdir(previous)


@pytest.mark.parametrize("invocation", sorted(_MINIMAL_ARGV))
def test_omitting_repo_warns_once_and_leaves_stdout_identical(
    invocation: str, repo: Path, tmp_path: Path
) -> None:
    """AC-2: the implicit form still works, warns exactly once on stderr, and
    produces stdout byte-identical to the explicit form."""
    argv = _MINIMAL_ARGV[invocation]

    implicit = _invoke_from(repo, argv)
    explicit = _invoke_from(repo, [*argv, "--repo", str(repo)])

    assert implicit.exit_code == explicit.exit_code, implicit.output
    assert implicit.stdout == explicit.stdout
    assert IMPLICIT_REPO_WARNING_PREFIX not in implicit.stdout

    assert implicit.stderr.count(IMPLICIT_REPO_WARNING_PREFIX) == 1, implicit.stderr
    assert explicit.stderr.count(IMPLICIT_REPO_WARNING_PREFIX) == 0, explicit.stderr


def test_an_explicit_dot_is_not_warned_about(repo: Path) -> None:
    """``--repo .`` is the stated form this deprecation asks callers to adopt;
    warning about it would make the deprecation unactionable."""
    result = _invoke_from(repo, ["runs", "--repo", "."])
    assert IMPLICIT_REPO_WARNING_PREFIX not in result.stderr


def test_an_explicit_db_suppresses_the_warning_on_a_read_command(
    repo: Path, tmp_path: Path
) -> None:
    """``--db`` decides the whole question for a read command, so the CWD
    decides nothing and there is no ambiguity to warn about."""
    result = _invoke_from(repo, ["runs", "--db", str(tmp_path / "absent.db")])
    assert IMPLICIT_REPO_WARNING_PREFIX not in result.stderr


def test_an_explicit_db_still_warns_on_a_verb_that_uses_git(
    repo: Path, tmp_path: Path
) -> None:
    """``--db`` does not settle it for a verb: git still resolves against the
    repo root, so an omitted ``--repo`` is still an ambient read."""
    result = _invoke_from(repo, ["checkpoint", "--db", str(tmp_path / "absent.db")])
    assert result.stderr.count(IMPLICIT_REPO_WARNING_PREFIX) == 1, result.stderr


def test_explicit_repo_from_an_unrelated_cwd_acts_on_the_named_repo(
    repo: Path, tmp_path: Path
) -> None:
    """AC-3: the named repo wins over the ambient CWD.

    Run from a directory that is not a git top-level: implicitly this is
    refused *for that directory*, so reaching the ledger refusal instead can
    only mean the named repo was used.
    """
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    absent_db = tmp_path / "absent.db"

    refused = _invoke_from(elsewhere, ["checkpoint", "--db", str(absent_db)])
    assert refused.exit_code == 2
    assert str(elsewhere) in (refused.stderr + refused.stdout)

    named = _invoke_from(
        elsewhere, ["checkpoint", "--repo", str(repo), "--db", str(absent_db)]
    )
    assert named.exit_code == 2, named.output
    assert json.loads(named.stdout)["reason"] == "no_ledger"


# ---------------------------------------------------------------------------
# The seam — one ambient read, in one module
# ---------------------------------------------------------------------------


def _cli_sources() -> list[Path]:
    """The git-tracked modules under ``harness/cli/``.

    The base argument is load-bearing: ``tracked_py_sources()`` with no bases
    enumerates nothing, so a scan written without one is a guard that reads zero
    files and passes unconditionally. The floor below is what catches that.
    """
    return tracked_py_sources("harness/cli")


def test_the_seam_scan_actually_reads_the_cli_package() -> None:
    """Non-vacuity floor for the seam guard.

    A scan over an empty file set reports no offenders for the same reason a
    clean tree does. Pin that the corpus is populated and contains the one
    module the guard exempts, so "no offenders" means *checked and clean*
    rather than *nothing checked*.
    """
    sources = _cli_sources()
    assert len(sources) > 20, sources
    assert REPO_ROOT / "harness" / "cli" / "_repo.py" in sources


def test_only_the_repo_seam_reads_the_working_directory() -> None:
    """``Path.cwd()`` belongs to ``_repo.py`` alone.

    A second ambient read anywhere in ``harness/cli/`` is both the bug class
    this ticket closes and the mechanism by which a second deprecation warning
    would appear, so the property is guarded structurally rather than inferred
    from the warning counts above.
    """
    offenders = sorted(
        str(path.relative_to(REPO_ROOT))
        for path in _cli_sources()
        if path.name != "_repo.py" and "Path.cwd()" in path.read_text(encoding="utf-8")
    )
    assert offenders == [], (
        "these modules read the working directory directly; route the repo "
        f"through harness.cli._repo.repo_arg_or_cwd instead: {offenders}"
    )


# ---------------------------------------------------------------------------
# AC-4 — the out-of-repo callers an operator must update
# ---------------------------------------------------------------------------


def test_runbook_records_the_out_of_repo_callers() -> None:
    """AC-4: the implicit form cannot be removed until callers outside this
    checkout state their repo, and a caller this checkout does not contain can
    only be tracked in the operational runbook."""
    text = RUNBOOK.read_text(encoding="utf-8")

    assert "harness-work-pull" in text, (
        "RUNBOOK.md does not name the out-of-repo scheduled task that invokes "
        "the verbs implicitly (#306 AC-4)"
    )
    assert CANONICAL_REPO_OPTION in text
    assert "docker/harness-wrapper.sh" in text, (
        "RUNBOOK.md must record that the wrapper cannot yet forward an explicit "
        "--repo, since that blocks removing the implicit form (#306)"
    )
