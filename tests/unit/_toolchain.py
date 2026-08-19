"""The suite's host dependencies, derived from the tracked test sources (#491).

The gate's toolchain preflight (``scripts/verify.sh``) refuses with the reserved
exit 97 — *the gate could not run* — when a tool it needs is unrunnable. Its
probe set was remembered rather than derived, so it could only drift one way: a
test admits a host dependency, the preflight never hears of it, and the gate
goes green over tests that silently did not run.

The membership rule this module implements is the decision recorded in
``specs/architecture-principles.md`` → *The gate's toolchain preflight probes
what the suite resolves off `PATH`*:

    **A binary enters the preflight exactly when a test resolves it off
    ``PATH`` at run time**, and that set is derived from the tracked test
    sources rather than restated.

The key is **resolution**, not spawning, and that is a measurement rather than a
preference: ``node`` — the confirmed miss the rule exists for — never appears as
a literal ``argv[0]`` anywhere in ``tests/``. Every hook module reaches it
through a ``_node()`` helper returning the absolute path
``shutil.which("node")`` resolved, so a derivation keyed on spawn sites derives
a set that does not contain it, and ships green. The severe direction is also
the silent one: a binary the suite *spawns* by name is absent loudly
(``FileNotFoundError``, a red test), while a binary the suite *resolves* and
skips on is absent invisibly.

Two derivations live here, and they are the two halves of one contract:

:func:`declared_binaries` answers *what the suite depends on*. A call to the
function bound by ``shutil.which`` whose argument this cannot name is a
**refusal**, never a fall-through — a partial parser that goes silent on a
spelling it does not know would leave the preflight held against a set with a
hole in it (#490), which is the failure mode a green run cannot show.

:func:`skip_sites` answers *whether that is the whole set*. It is the
completion condition: the derived set is exhaustive only while the suite has no
other way to make its outcome depend on the host, so every skip-shaped
construct must sit in a function that also resolves a binary. Anything else is
an offender, and the change introducing a new conditional-execution mechanism
answers the membership question in place.

Both read the **git index** (:func:`tests._gitutil.indexed_text`) rather than
the working file: ``git write-tree`` certifies the index, the gate marker is
named after the tree it produces, and a verdict binds to that oid — so the
index is the only operand that answers "what will ship" (#482). Unstaged work
is invisible to these guards, which their failure messages say.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass

from tests._gitutil import indexed_text, tracked_py_sources
from tests.unit._prose import REPO_ROOT

#: The module and function whose call is the declaration. Named rather than
#: matched as text, so an alias for either resolves and a same-named local does
#: not (#490 — derive names from the import).
WHICH_MODULE = "shutil"
WHICH_FUNCTION = "which"

#: A construct is *skip-shaped* when the last component of its dotted name is
#: one of these. ``pytest.skip``, ``pytest.mark.skipif`` and
#: ``pytest.importorskip`` are the spellings that exist; the rule is written on
#: the last component so an unknown head — a second test framework, a helper
#: module re-exporting one of them — is still seen rather than skipped over.
SKIP_NAMES = frozenset({"skip", "skipif", "importorskip"})


@dataclass(frozen=True)
class SkipSite:
    """One place the suite can decline to run, and what declares it."""

    origin: str
    lineno: int
    #: The spelling as written — ``pytest.skip``, ``pt.mark.skipif``, ``skip``.
    spelling: str
    #: The innermost enclosing function, or ``None`` at module scope.
    scope: str | None
    #: The binaries resolved off ``PATH`` in that same function.
    declares: tuple[str, ...]

    @property
    def compliant(self) -> bool:
        """A skip is permitted exactly where the same function resolves a binary.

        The exemption is **earned from the subject**, not granted by a list: it
        is the presence of the declaring call in the same function, so a rename,
        a move, or a fourteenth duplicate carries it along. Every allowlist this
        repo has written went stale in one direction or admitted in the other
        (#449 → #458).
        """
        return self.scope is not None and bool(self.declares)

    def why(self) -> str:
        if self.scope is None:
            return (
                f"{self.origin}:{self.lineno}: `{self.spelling}` sits at module scope, "
                "where no function can declare the host dependency it is conditional on"
            )
        return (
            f"{self.origin}:{self.lineno}: `{self.spelling}` in {self.scope}() makes this "
            f"suite's outcome depend on the host, but {self.scope}() resolves no binary "
            f"with {WHICH_MODULE}.{WHICH_FUNCTION}(<name>). A skip is how the suite "
            "silently runs less than it claims, so it is permitted only where the "
            "dependency it is conditional on is declared — and declaring it is what "
            "puts the binary in the gate's toolchain preflight"
        )


def _dotted(node: ast.expr) -> str | None:
    """``a.b.c`` for an attribute chain rooted in a plain name; ``None`` otherwise."""
    parts: list[str] = []
    current: ast.expr = node
    while isinstance(current, ast.Attribute):
        parts.append(current.attr)
        current = current.value
    if not isinstance(current, ast.Name):
        return None
    parts.append(current.id)
    return ".".join(reversed(parts))


def _locally_bound(tree: ast.Module) -> set[str]:
    """Names this module binds itself — a ``def``, a ``class``, an assignment.

    A local ``def which(...)`` is not ``shutil.which``, and a local object with
    a ``.skip()`` method is not pytest's. Reading either as the real thing is a
    guard going red on correct code, which is a defect and not strictness
    (#484).
    """
    bound: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
            bound.add(node.name)
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    bound.add(target.id)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            bound.add(node.target.id)
    return bound


def _which_spellings(tree: ast.Module) -> tuple[set[str], set[str]]:
    """``(module aliases, bare names)`` this module binds to ``shutil.which``.

    Both halves are read off the **imports**, so ``import shutil as sh`` and
    ``from shutil import which as _w`` resolve while a same-named local does
    not. Imports are collected with :func:`ast.walk` rather than off
    ``tree.body``: one nested inside a function or a ``try:`` is a legal
    spelling, and a scan that misses it goes silent rather than red (#467).
    """
    modules: set[str] = set()
    bare: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == WHICH_MODULE:
                    modules.add(alias.asname or alias.name)
        elif isinstance(node, ast.ImportFrom) and node.module == WHICH_MODULE:
            for alias in node.names:
                if alias.name == WHICH_FUNCTION:
                    bare.add(alias.asname or alias.name)
    shadowed = _locally_bound(tree)
    return modules - shadowed, bare - shadowed


def _is_which_call(call: ast.Call, modules: set[str], bare: set[str]) -> bool:
    func = call.func
    if isinstance(func, ast.Name):
        return func.id in bare
    if isinstance(func, ast.Attribute) and func.attr == WHICH_FUNCTION:
        return isinstance(func.value, ast.Name) and func.value.id in modules
    return False


def _which_calls(tree: ast.Module, origin: str) -> list[tuple[ast.Call, str]]:
    """Every resolution call, paired with the literal name it resolves.

    Every call is either **named or refused**; there is no third outcome. That
    is the completeness half of the derivation, and it is why a spelling this
    cannot read fails loudly instead of shrinking the derived set by one.
    """
    modules, bare = _which_spellings(tree)
    resolved: list[tuple[ast.Call, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not _is_which_call(node, modules, bare):
            continue
        argument = node.args[0] if node.args else None
        if isinstance(argument, ast.Constant) and isinstance(argument.value, str):
            resolved.append((node, argument.value))
            continue
        spelling = "no argument" if argument is None else ast.unparse(argument)
        raise AssertionError(
            f"{origin}:{node.lineno}: this call resolves a binary off PATH but names "
            f"it with {spelling}, which cannot be read off the tree. The gate's "
            "toolchain preflight is derived from these calls, so a name only known "
            "at run time would leave the preflight held against a set with a hole "
            "in it — pass a string literal, or extend this derivation deliberately"
        )
    return resolved


def declared_binaries(source: str, *, origin: str = "<source>") -> set[str]:
    """The binaries ``source`` resolves off ``PATH``.

    Takes the text rather than reading one file, because a derivation fed only
    production data is indistinguishable from a hardcoded constant: its tests
    feed it sources whose answer differs from this repo's (#458).
    """
    tree = ast.parse(source, filename=origin)
    return {name for _, name in _which_calls(tree, origin)}


def _enclosing_scopes(tree: ast.Module) -> dict[int, str | None]:
    """Innermost enclosing function name, by node identity.

    A class body is not a scope for this purpose — a skip there is still the
    module's — but a nested ``def`` is, so a helper's declaration does not
    excuse its caller's skip.
    """
    scopes: dict[int, str | None] = {}

    def walk(node: ast.AST, scope: str | None) -> None:
        for child in ast.iter_child_nodes(node):
            inner = (
                child.name
                if isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef)
                else scope
            )
            scopes[id(child)] = inner
            walk(child, inner)

    scopes[id(tree)] = None
    walk(tree, None)
    return scopes


def skip_sites(source: str, *, origin: str = "<source>") -> list[SkipSite]:
    """Every skip-shaped construct in ``source``, with what declares it.

    The completion condition. Both decorators and calls are read: a
    ``@pytest.mark.skipif`` is the same silent degradation as a
    ``pytest.skip()``, and a scan that read only calls would miss it.
    """
    tree = ast.parse(source, filename=origin)
    scopes = _enclosing_scopes(tree)
    local = _locally_bound(tree)

    declared: dict[str | None, set[str]] = {}
    for call, name in _which_calls(tree, origin):
        declared.setdefault(scopes.get(id(call)), set()).add(name)

    candidates: list[ast.expr] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            candidates.append(node.func)
        elif isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
            candidates.extend(node.decorator_list)

    sites: list[SkipSite] = []
    seen: set[tuple[int, int]] = set()
    for candidate in candidates:
        spelling = _dotted(candidate)
        if spelling is None or spelling.rsplit(".", 1)[-1] not in SKIP_NAMES:
            continue
        if spelling.split(".", 1)[0] in local:
            continue
        key = (candidate.lineno, candidate.col_offset)
        if key in seen:
            continue
        seen.add(key)
        scope = scopes.get(id(candidate))
        sites.append(
            SkipSite(
                origin=origin,
                lineno=candidate.lineno,
                spelling=spelling,
                scope=scope,
                declares=tuple(sorted(declared.get(scope, set()))),
            )
        )
    return sites


def indexed_test_sources() -> dict[str, str]:
    """The tracked ``tests/**/*.py`` corpus, as the index has it.

    Tracked, not on-disk: a guard whose subject is "what a fresh clone gets"
    passes on the machine that wrote the file if it reads the working tree
    (#484). Keyed by repo-relative path so a failure names a file rather than a
    machine-specific absolute path.
    """
    sources: dict[str, str] = {}
    for path in tracked_py_sources("tests"):
        relative = path.relative_to(REPO_ROOT).as_posix()
        sources[relative] = indexed_text(relative)
    return sources


def declared_binaries_from_tree() -> set[str]:
    """:func:`declared_binaries` over the whole indexed test corpus."""
    found: set[str] = set()
    for relative, source in indexed_test_sources().items():
        found |= declared_binaries(source, origin=relative)
    return found


def skip_sites_from_tree() -> list[SkipSite]:
    """:func:`skip_sites` over the whole indexed test corpus."""
    sites: list[SkipSite] = []
    for relative, source in indexed_test_sources().items():
        sites.extend(skip_sites(source, origin=relative))
    return sites
