"""Shared test infrastructure has a neutral home, and test modules are not it.

Three accumulations of the same shape (#467, assessment finding CODE-3) said the
same thing about ``tests/unit/``: a helper's home was whichever peer module
happened to define it first.

**135 modules each bound their own repo-root constant** — 118 off
``Path(__file__).resolve().parents[2]`` under the names ``_REPO_ROOT``,
``REPO_ROOT`` and ``ROOT``, and seventeen off the **unresolved**
``Path(__file__).parent.parent.parent``. (The ticket enumerated 132 of them: it
named two of the three resolved spellings, and the AST predicate below found the
third.) The
unresolved form is the frame-mismatch hazard the repo's own craft reference
names: an unresolved root compared against a git-printed resolved path is a
latent constant-true or constant-false, and nothing about the module reading it
says which.

**30 modules imported helpers from sibling ``test_*`` modules.** A test module
that is also a library cannot be deleted, renamed, or converted without an
importer audit — the ADR 0016 triage hit exactly that, annotating one module
"Must keep exporting ``_sentences``" in the middle of a pass whose whole purpose
was deciding what to delete.

So the invariants here are structural, in ADR 0016's keep class: what the tree
must *not* contain (a test module that is an import target; a test module that
binds its own root), and what must **correspond** (the neutral homes the tree
actually has, and the ones ``CONTRIBUTING.md`` names). None of them asks whether
a sentence means the right thing.

Every predicate below reads the **AST**, never the source text. That is not
fastidiousness: this module has to describe the shapes it bans, and a regex over
source would match its own description — the trap #457 paid for, where a corpus
containing its own description cannot measure it. An ``ast.unparse`` of a *value
node* renders a string literal with its quotes, so the one shape that would
otherwise be indistinguishable from a real binding is distinguishable by
construction. Each predicate is proved to discriminate against synthetic input,
positive and near-miss, so a green tree is not the only corpus it has ever seen.
"""

from __future__ import annotations

import ast
import re
import subprocess
from pathlib import Path

import pytest

from tests._gitutil import tracked_py_sources
from tests.unit._prose import (
    REPO_ROOT,
    registered_prose_files,
    sentences,
    sentences_on_break,
)

#: The pull-request bullet that states the regrowth rule (CODE-INSIGHT-3). The
#: anchor is the bolded lead-in every sibling bullet in that section carries, so
#: an edit that renames the rule fails loudly here rather than silently
#: selecting nothing.
_CONTRIBUTING = "CONTRIBUTING.md"
_BULLET_LEAD_IN = "**Shared test helpers live in underscore modules**"

#: How far a negation may sit from the thing it negates and still be read as
#: negating it. Bound the window or the negation attaches to whichever clause is
#: convenient.
_NEGATION_GAP = 12
_IMPORT_TARGET = re.compile(r"\bimport\s+target\b", re.IGNORECASE)
_NEGATION = re.compile(r"\bnever\b|\bnot\b|\bno\b", re.IGNORECASE)


# ---------------------------------------------------------------------------
# The corpus
# ---------------------------------------------------------------------------


def _tracked_test_modules() -> list[Path]:
    """Every git-tracked ``test_*.py`` under ``tests/``.

    Tracked, not walked: a nested worktree or a stale ``__pycache__`` is excluded
    by construction rather than by a skip list that a stray path can outrun.
    """
    return [path for path in tracked_py_sources("tests") if path.name.startswith("test_")]


def _tracked_underscore_modules() -> list[Path]:
    """Every git-tracked ``_*.py`` under ``tests/`` — the neutral homes.

    Dunder modules are package plumbing, not shared infrastructure, so
    ``__init__.py`` is excluded by name rather than by path.
    """
    return [
        path
        for path in tracked_py_sources("tests")
        if path.name.startswith("_") and not path.name.startswith("__")
    ]


def _tracked_non_test_modules() -> list[Path]:
    """Every git-tracked ``.py`` under ``tests/`` that is not a ``test_*`` module.

    Wider than :func:`_tracked_underscore_modules` on purpose. The import ban has
    to hold over *everything* that could reach into a test module, and
    ``__init__.py`` — excluded from the neutral-home set as package plumbing — is
    a module like any other: an import placed there couples the same two files
    with the same consequence. A ``conftest.py``, which this tree does not have
    today, lands in this corpus the day it is added rather than in a gap.
    """
    return [
        path for path in tracked_py_sources("tests") if not path.name.startswith("test_")
    ]


def _parse(path: Path) -> ast.Module:
    return ast.parse(path.read_text(), filename=str(path))


def _module_path(path: Path) -> str:
    """The dotted module name a tracked path is imported as."""
    return ".".join(path.relative_to(REPO_ROOT).with_suffix("").parts)


# ---------------------------------------------------------------------------
# Predicate 1 — is a test module an import target?
# ---------------------------------------------------------------------------


def _imported_test_modules(tree: ast.Module) -> list[str]:
    """The ``tests`` **test modules** this AST imports from, dotted.

    Both import forms, and relative imports too: ``from .test_foo import x``
    reaches the same module by a different spelling, and a rule that only knew
    the absolute form would be one ``.`` away from useless.
    """
    found: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            # A relative import inside ``tests.unit`` resolves under ``tests``;
            # the level is irrelevant to *what kind of module* is named.
            module = node.module or ""
            if node.level and module:
                found.extend(_test_module_names(module, relative=True))
            elif not node.level:
                found.extend(_test_module_names(module, relative=False))
        elif isinstance(node, ast.Import):
            for alias in node.names:
                found.extend(_test_module_names(alias.name, relative=False))
    return found


def _test_module_names(dotted: str, *, relative: bool) -> list[str]:
    """``[dotted]`` when it names a test module, else ``[]``."""
    if not dotted:
        return []
    parts = dotted.split(".")
    if not relative and parts[0] != "tests":
        return []
    return [dotted] if parts[-1].startswith("test_") else []


# ---------------------------------------------------------------------------
# Predicate 2 — does a module bind its own repo root?
# ---------------------------------------------------------------------------


def _module_level_statements(body: list[ast.stmt]) -> list[ast.stmt]:
    """``body`` flattened through every block that does not open a new scope.

    A binding under ``if TYPE_CHECKING:``, inside a ``try:`` that falls back, or
    in a ``with`` block is a **module attribute** — the same accumulation, one
    indent further in. A scan of ``tree.body`` alone cannot see it: measured at
    review, splicing ``if True:`` around a fresh root binding left the whole
    suite green while the module really did bind the name. ``FunctionDef`` and
    ``ClassDef`` are deliberately not descended into, because a local or a class
    attribute is not the constant this ban is about.
    """
    flattened: list[ast.stmt] = []
    for node in body:
        flattened.append(node)
        if isinstance(node, (ast.If, ast.For, ast.While, ast.With, ast.Try)):
            nested: list[ast.stmt] = [*node.body, *getattr(node, "orelse", [])]
            if isinstance(node, ast.Try):
                nested += node.finalbody
                for handler in node.handlers:
                    nested += handler.body
            flattened += _module_level_statements(nested)
    return flattened


def _root_bindings(tree: ast.Module) -> list[str]:
    """Names this AST binds to a ``Path(__file__)`` walk to an ancestor.

    The value node is unparsed, so a *string* spelling the same expression
    renders with its quotes and cannot pass for a binding.
    """
    found: list[str] = []
    for node in _module_level_statements(tree.body):
        targets: list[ast.expr]
        if isinstance(node, ast.Assign):
            targets = list(node.targets)
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            targets = [node.target]
        else:
            continue
        value = node.value
        if value is None or not _walks_to_an_ancestor(value):
            continue
        found.extend(
            target.id for target in targets if isinstance(target, ast.Name)
        )
    return found


#: The walk, with the module qualification the caller happens to have used. A
#: bare ``startswith("Path(__file__)")`` reads only ``from pathlib import Path``;
#: measured at review, splicing ``pathlib.Path(__file__).resolve().parents[2]``
#: into a real test module re-derived the constant this ticket removed and the
#: ban did not fire. The dotted prefix is optional and unanchored on the right,
#: so ``tmp_path.parents[2]`` — which names no ``Path(__file__)`` at all — stays
#: outside it.
_ROOT_WALK = re.compile(r"\A(?:[A-Za-z_]\w*\.)*Path\(__file__\)")


def _walks_to_an_ancestor(value: ast.expr) -> bool:
    """Is this expression a repo-root walk, and *only* that?

    A ``BinOp`` is rejected first, and that rejection is the whole difference
    between this predicate and one that measures nothing useful.
    ``Path(__file__).resolve().parents[2] / "templates" / "CONTEXT.template.md"``
    starts with the same walk and is not a root binding — it is a *derived* path,
    which every module is entitled to hold. A predicate that cannot tell the two
    apart reports one more offender than there are, and the one it is wrong
    about is a module doing nothing wrong.
    """
    if isinstance(value, ast.BinOp):
        return False
    source = ast.unparse(value)
    return _ROOT_WALK.match(source) is not None and "parent" in source


# ---------------------------------------------------------------------------
# The invariants
# ---------------------------------------------------------------------------


def test_no_test_module_is_an_import_target() -> None:
    """A ``test_*.py`` module is never something another module imports from."""
    offenders: dict[str, list[str]] = {}
    for path in _tracked_test_modules():
        imported = _imported_test_modules(_parse(path))
        if imported:
            offenders[str(path.relative_to(REPO_ROOT))] = sorted(set(imported))
    assert offenders == {}, (
        "a test module is being used as a library — move the helper to a "
        f"neutral underscore module and re-point the importer: {offenders}"
    )


def test_no_other_module_under_tests_imports_from_a_test_module() -> None:
    """Nothing else under ``tests/`` reaches into a test module either.

    Without this, the ban above is satisfiable by routing the same coupling
    through ``_prose.py`` — the helper would still live in a test module and
    still be undeletable, with one more hop hiding it. The corpus is every
    non-``test_*`` module rather than the neutral homes alone, because
    ``__init__.py`` would otherwise be a hop the ban does not watch.
    """
    offenders: dict[str, list[str]] = {}
    for path in _tracked_non_test_modules():
        imported = _imported_test_modules(_parse(path))
        if imported:
            offenders[str(path.relative_to(REPO_ROOT))] = sorted(set(imported))
    assert offenders == {}, f"a neutral home imports from a test module: {offenders}"


def test_no_test_module_binds_its_own_repo_root() -> None:
    """The repository root is imported from the shared home, never re-derived."""
    offenders: dict[str, list[str]] = {}
    for path in _tracked_test_modules():
        bindings = _root_bindings(_parse(path))
        if bindings:
            offenders[str(path.relative_to(REPO_ROOT))] = bindings
    assert offenders == {}, (
        "a test module derives its own repo root — import REPO_ROOT from "
        f"tests.unit._prose instead: {offenders}"
    )


def test_the_swept_corpora_are_live() -> None:
    """The floors, outside the sweeps they protect.

    Every invariant above collects offenders and asserts the collection is
    empty, which is constant-true over an empty corpus (``craft.md`` → *The
    empty subject set*). Both corpora come from ``git ls-files``, so a moved
    tree, a changed prefix or a query that stops matching empties them while
    every assertion still passes — measured at review, narrowing
    :func:`_tracked_test_modules` to nothing left the whole suite green.

    Non-empty plus a **named anchor**, never a count: a pinned cardinality is
    the drift these guards exist to remove, and it would have to be edited by
    the same change that adds the next module. The two homes floors also close
    the correspondence test's shared-empty case, where a bullet naming nothing
    and a tree holding nothing compare equal.
    """
    tests = {str(path.relative_to(REPO_ROOT)) for path in _tracked_test_modules()}
    homes = {str(path.relative_to(REPO_ROOT)) for path in _tracked_underscore_modules()}
    others = {str(path.relative_to(REPO_ROOT)) for path in _tracked_non_test_modules()}
    assert homes <= others, (
        "the import ban's corpus no longer covers every neutral home: "
        f"{sorted(homes - others)}"
    )
    assert Path(__file__).name in {Path(rel).name for rel in tests}, (
        f"the test-module corpus does not contain this module: {sorted(tests)[:5]} — "
        "the derivation stopped matching and every ban above is now vacuous"
    )
    assert {"tests/_gitutil.py", "tests/unit/_prose.py"} <= homes, (
        f"the neutral-home corpus is missing a home this repo has: {sorted(homes)}"
    )


def test_the_two_shared_sentence_splitters_are_not_interchangeable() -> None:
    """The shared home keeps two splitters; this is what says they are two.

    :mod:`tests.unit._prose` states that :func:`sentences` and
    :func:`sentences_on_break` "disagree about what ends a sentence, and both
    disagreements are load-bearing where they are used", and #467 kept every
    consumer on the one it already had. Nothing measured that: collapsing
    ``sentences_on_break`` into ``sentences`` was mutation-proved at review to
    change the units it yields over a real tree document and to kill no test in
    the suite. So the docstring claimed a property the suite lacked, which is
    ``craft.md`` → *A docstring claiming coverage the code lacks*.

    Structural correspondence, not meaning: two functions over one derived
    corpus, required to disagree somewhere. It says nothing about *which*
    consumer should hold which — that judgement stays with the reviewer — but a
    later simplification that makes one an alias of the other cannot pass.
    """
    corpus = registered_prose_files()
    assert corpus, "the registered-prose corpus derived to nothing"
    disagreements: list[str] = []
    for path in corpus:
        text = path.read_text(encoding="utf-8")
        if sentences(text) != sentences_on_break(text):
            disagreements.append(str(path.relative_to(REPO_ROOT)))
    assert disagreements, (
        "`sentences` and `sentences_on_break` produce identical units over every "
        "registered prose file — they are no longer two splitters, and a consumer "
        "pointed at the wrong one would be indistinguishable from a correct tree"
    )


def test_the_shared_root_is_the_resolved_form() -> None:
    """``REPO_ROOT`` is resolved, so it compares in git's frame.

    An unresolved root and a git-printed path differ on any host whose checkout
    sits under a symlink — a comparison that is then constant-true or
    constant-false rather than wrong-looking.
    """
    assert REPO_ROOT.resolve() == REPO_ROOT


def test_the_shared_root_binding_resolves_at_its_source() -> None:
    """The shared binding calls ``.resolve()``, asserted over the binding itself.

    The value comparison above cannot fail on a checkout that sits under no
    symlink, which is most of them: it is a real invariant with a host-dependent
    witness, and on this host ``.resolve()`` is a no-op. This one reads the
    binding, so the frame decision the 17 unresolved modules got wrong is
    asserted wherever the suite runs.
    """
    tree = _parse(REPO_ROOT / "tests" / "unit" / "_prose.py")
    bindings = [
        node
        for node in tree.body
        if isinstance(node, ast.Assign)
        and any(isinstance(t, ast.Name) and t.id == "REPO_ROOT" for t in node.targets)
    ]
    assert len(bindings) == 1, (
        f"tests/unit/_prose.py must bind REPO_ROOT exactly once; found {len(bindings)}"
    )
    assert "resolve()" in ast.unparse(bindings[0].value), (
        "the shared REPO_ROOT is not resolved at its binding — an unresolved root "
        "compared against a git-printed path is a latent constant-true/false"
    )


def test_the_shared_root_is_the_repository_root() -> None:
    top_level = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    assert Path(top_level).resolve() == REPO_ROOT


# ---------------------------------------------------------------------------
# The predicates discriminate
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "source",
    [
        pytest.param("from tests.unit.test_foo import _bar", id="absolute-from"),
        pytest.param("import tests.unit.test_foo", id="absolute-import"),
        pytest.param("from tests.test_foo import _bar", id="top-level-from"),
        pytest.param("from .test_foo import _bar", id="relative-from"),
        pytest.param("from ..unit.test_foo import _bar", id="relative-parent-from"),
    ],
)
def test_the_import_predicate_flags_a_real_import_target(source: str) -> None:
    assert _imported_test_modules(ast.parse(source)) != []


@pytest.mark.parametrize(
    "source",
    [
        pytest.param("from tests.unit._prose import REPO_ROOT", id="neutral-home"),
        pytest.param("from tests._gitutil import init_repo", id="git-home"),
        pytest.param("from .._gitutil import init_repo", id="relative-neutral-home"),
        pytest.param("import pytest", id="third-party"),
        pytest.param(
            "from mypkg.test_foo import _bar", id="test-module-outside-tests"
        ),
        pytest.param("test_foo = 1", id="a-name-not-an-import"),
    ],
)
def test_the_import_predicate_clears_a_near_miss(source: str) -> None:
    assert _imported_test_modules(ast.parse(source)) == []


@pytest.mark.parametrize(
    "source",
    [
        pytest.param("X = Path(__file__).resolve().parents[2]", id="resolved-parents"),
        pytest.param("X = Path(__file__).parent.parent.parent", id="unresolved-chain"),
        pytest.param("X = Path(__file__).resolve().parents[1]", id="other-depth"),
        pytest.param("X: Path = Path(__file__).resolve().parents[2]", id="annotated"),
        pytest.param(
            "X = pathlib.Path(__file__).resolve().parents[2]", id="qualified-pathlib"
        ),
        pytest.param(
            "if True:\n    X = Path(__file__).resolve().parents[2]", id="inside-a-block"
        ),
        pytest.param(
            "try:\n    X = Path(__file__).resolve().parents[2]\nexcept OSError:\n    pass",
            id="inside-a-try",
        ),
    ],
)
def test_the_root_predicate_flags_a_real_binding(source: str) -> None:
    assert _root_bindings(ast.parse(source)) == ["X"]


@pytest.mark.parametrize(
    "source",
    [
        pytest.param('X = "Path(__file__).resolve().parents[2]"', id="string-literal"),
        pytest.param("X = Path(__file__)", id="no-walk"),
        pytest.param("X = tmp_path.parents[2]", id="not-from-file"),
        pytest.param("X = REPO_ROOT / 'registry.yaml'", id="derived-from-shared"),
        pytest.param(
            'X = Path(__file__).resolve().parents[2] / "templates" / "CONTEXT.md"',
            id="derived-path-off-the-same-walk",
        ),
        pytest.param(
            "def f():\n    X = Path(__file__).resolve().parents[2]", id="function-local"
        ),
        pytest.param(
            "class C:\n    X = Path(__file__).resolve().parents[2]", id="class-attribute"
        ),
        pytest.param(
            "if True:\n    def f():\n        X = Path(__file__).resolve().parents[2]",
            id="function-local-inside-a-block",
        ),
    ],
)
def test_the_root_predicate_clears_a_near_miss(source: str) -> None:
    assert _root_bindings(ast.parse(source)) == []


# ---------------------------------------------------------------------------
# The regrowth rule is written down (CODE-INSIGHT-3)
# ---------------------------------------------------------------------------


def _contributing_bullet() -> str:
    """The list item stating the regrowth rule, from its bolded lead-in.

    Refuses rather than returns empty when the anchor does not resolve: a
    silently-empty slice makes every assertion over it pass.
    """
    text = (REPO_ROOT / _CONTRIBUTING).read_text()
    start = text.find(_BULLET_LEAD_IN)
    assert start != -1, (
        f"{_CONTRIBUTING} no longer carries the bullet lead-in "
        f"{_BULLET_LEAD_IN!r} — the anchor this guard reads is gone"
    )
    rest = text[start:]
    end = rest.find("\n- ")
    return rest if end == -1 else rest[:end]


def _named_homes(bullet: str) -> set[str]:
    return set(re.findall(r"tests/[\w/]*_[\w]+\.py", bullet))


def test_the_regrowth_bullet_names_exactly_the_tree_s_neutral_homes() -> None:
    """The documented homes and the real ones correspond, both directions.

    Adding a third shared home without documenting it fails here; so does
    documenting a module the tree does not have. A count would catch neither.
    """
    documented = _named_homes(_contributing_bullet())
    actual = {
        str(path.relative_to(REPO_ROOT)) for path in _tracked_underscore_modules()
    }
    assert documented == actual


def _bans_the_import_target(text: str) -> bool:
    """A negation within :data:`_NEGATION_GAP` words of "import target".

    Bounded, and bound to *this* clause: an unbounded search finds the "never"
    from some other sentence and reports a ban the prose does not make.
    """
    for match in _IMPORT_TARGET.finditer(text):
        window = text[: match.start()].split()[-_NEGATION_GAP:]
        if any(_NEGATION.fullmatch(word.strip(".,;:'\"")) for word in window):
            return True
    return False


def test_the_regrowth_bullet_bans_a_test_module_as_an_import_target() -> None:
    assert _bans_the_import_target(_contributing_bullet())


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        pytest.param(
            "a test module is never an import target", True, id="adjacent-negation"
        ),
        pytest.param("a test module is an import target", False, id="no-negation"),
        pytest.param(
            "never do that. " + "word " * 20 + "a test module is an import target",
            False,
            id="negation-out-of-range",
        ),
        pytest.param("this is not an import target", True, id="not-form"),
        pytest.param("a test module is a library", False, id="subject-absent"),
    ],
)
def test_the_ban_predicate_discriminates(text: str, expected: bool) -> None:
    assert _bans_the_import_target(text) is expected
