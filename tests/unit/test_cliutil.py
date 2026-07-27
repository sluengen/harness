"""#222 — one reader for the Typer app's registered command surface.

Filed by ``/assess code`` (steward, 2026-07-26 pm, CODE-1, Medium): the
two-line union that reads Typer's registered surface —

    names = {c.name for c in app.registered_commands if c.name is not None}
    names |= {g.name for g in app.registered_groups if g.name is not None}

stood byte-identical in three test modules, the third added by #219's own fix.
Two further modules read the ``registered_commands`` half alone. Five readers
independently deriving "what does the app expose" means a Typer API change —
or the latent bug of dropping the ``registered_groups`` half — has to be found
and fixed in five places.

This module carries both halves of the fix: direct unit tests for
:func:`tests._cliutil.registered_command_surface`, and the adoption lock that
keeps a sixth inline copy from landing.

The helper gets its own oracle deliberately. Consolidating five readers makes
that function a single point of failure — an inverted filter or a dropped half
would weaken the CLI-surface lock, the feature-spec agreement check, #219's
anti-vacuity oracle and two retirement guards at once, and every one of them
would still report green. The synthetic-app tests below are that independent
oracle, mirroring why ``test_gitutil.py`` proves ``tracked_py_sources`` against
a throw-away repo rather than trusting its callers to notice.

Acceptance criteria (this ticket):

* **AC-1** — a shared helper exposes ``registered_command_surface``. Proven by
  :func:`test_unions_commands_and_groups` and its siblings.
* **AC-2/3** — every module reads the surface through it, rather than
  re-deriving the union inline. Proven by
  :func:`test_no_test_module_reads_the_registered_surface_inline`.
* **AC-4** — the adoption lock enumerates the tracked test sources, so a
  *sixth* inline copy fails the gate. Proven by the same test, whose subject
  set is derived rather than listed (``code-quality`` Part C).
* **AC-5** — the scanned surface is unchanged: the converted call sites' own
  assertions pass untouched.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import typer

from tests._cliutil import registered_command_surface
from tests._gitutil import tracked_py_sources

# ``tests/unit/test_*.py`` → ``parents[2]`` is the repo (or worktree) root.
_REPO_ROOT = Path(__file__).resolve().parents[2]

# An inline read of any Typer app's registered surface — top-level or a
# sub-app bound to a name ending in ``app`` (``promote_app``, ``sub_app``, ...).
# ``\w*app\.`` is load-bearing: it matches inside ``promote_app.`` too, so the
# sub-app readers in test_promotion_routine_docs.py and
# test_local_orchestrator_stack_docs.py are in scope as a property of the rule
# rather than needing allowlist entries.
_INLINE_SURFACE_READ = re.compile(r"\b\w*app\.registered_(?:commands|groups)\b")

_ADOPTION_ALLOWLIST = {
    _REPO_ROOT / "tests" / "_cliutil.py",  # the one legitimate home
    _REPO_ROOT / "tests" / "unit" / "test_cliutil.py",  # carries the literal
}


def _scanned_sources() -> list[Path]:
    """The tracked test sources the adoption lock judges.

    Derived from the git-tracked set, not listed: a hard-coded tuple of today's
    adopters would pass forever while a sixth module inlined the pattern — the
    enumeration drift #219 was filed for.
    """
    return [p for p in tracked_py_sources("tests") if p not in _ADOPTION_ALLOWLIST]


# ---------------------------------------------------------------------------
# The helper's own oracle
# ---------------------------------------------------------------------------


def test_unions_commands_and_groups() -> None:
    """A sub-app's name is part of the surface, not only direct commands."""
    app = typer.Typer()
    app.command(name="start")(lambda: None)
    app.add_typer(typer.Typer(), name="promote")

    assert registered_command_surface(app) == {"start", "promote"}


def test_commands_only_app_yields_its_command_names() -> None:
    """An app with no sub-apps returns exactly its command names."""
    app = typer.Typer()
    app.command(name="start")(lambda: None)
    app.command(name="close")(lambda: None)

    assert registered_command_surface(app) == {"start", "close"}


def test_an_unnamed_registration_is_excluded() -> None:
    """A registration with no explicit ``name=`` is dropped (pre-existing).

    Typer would render such a command under its callable's function name, so
    the filtered set is a subset of the rendered surface in general. Every
    registration in ``harness/cli/__init__.py`` is named explicitly, so the two
    coincide today — this pins the contract so a later "improvement" that
    resolves implicit names cannot silently widen five guards at once.
    """
    app = typer.Typer()
    app.command(name="start")(lambda: None)
    app.command()(lambda: None)

    assert registered_command_surface(app) == {"start"}


def test_an_empty_app_yields_an_empty_set() -> None:
    """No registrations is an empty surface, not an error."""
    assert registered_command_surface(typer.Typer()) == set()


def test_a_groups_subcommands_are_not_recursed_into() -> None:
    """The surface is top-level only: a group contributes its own name."""
    sub = typer.Typer()
    sub.command(name="start")(lambda: None)
    app = typer.Typer()
    app.add_typer(sub, name="promote")

    assert registered_command_surface(app) == {"promote"}


def test_the_live_app_exposes_both_a_command_and_a_group() -> None:
    """Both halves hold against the real object, not only synthetic ones."""
    from harness.cli import app

    surface = registered_command_surface(app)
    assert {"start", "promote"} <= surface, (
        "the live CLI registers both a plain command (start) and a sub-app "
        f"group (promote); the helper returned {sorted(surface)}"
    )


# ---------------------------------------------------------------------------
# The adoption lock
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "source",
    _scanned_sources(),
    ids=lambda p: str(p.relative_to(_REPO_ROOT)),
)
def test_no_test_module_reads_the_registered_surface_inline(source: Path) -> None:
    """No tracked test module re-derives the surface (AC-2/3/4)."""
    text = source.read_text(encoding="utf-8")
    assert not _INLINE_SURFACE_READ.search(text), (
        f"{source.relative_to(_REPO_ROOT)} reads the Typer app's registered "
        "surface inline; import tests._cliutil.registered_command_surface "
        "instead, so the commands-and-groups union has one definition."
    )


def test_the_adoption_lock_scans_a_non_empty_set() -> None:
    """Anti-vacuity: a lock over an empty set passes trivially."""
    scanned = _scanned_sources()
    assert len(scanned) > 50, (
        "the adoption lock derives its subjects from the tracked test sources; "
        f"only {len(scanned)} were found, which means the derivation broke "
        "rather than that the tree is clean"
    )


@pytest.mark.parametrize(
    ("text", "flagged"),
    [
        # The two halves of the duplicated union.
        ("names = {c.name for c in app.registered_commands if c.name is not None}", True),
        ("names |= {g.name for g in app.registered_groups if g.name is not None}", True),
        # The multi-line comprehension form — the scan reads whole file text,
        # so a line break must not hide a read.
        ("names = {\n    cmd.name\n    for cmd in app.registered_commands\n}", True),
        # A sub-app reader: a receiver ending in "app" is in scope.
        ("names = sorted(c.name for c in promote_app.registered_commands if c.name)", True),
        # The adopted form, including the sub-app receiver.
        ("surface = registered_command_surface(app)", False),
        ("surface = registered_command_surface(promote_app)", False),
    ],
)
def test_inline_surface_read_detection(text: str, flagged: bool) -> None:
    """The detector's boundaries are pinned, not just its current effect."""
    assert bool(_INLINE_SURFACE_READ.search(text)) is flagged
