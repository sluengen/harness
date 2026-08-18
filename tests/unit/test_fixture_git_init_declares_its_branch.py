"""A fixture's ``git init`` must name its branch rather than inherit it (#369).

``git init`` creates whatever the **host's** ``init.defaultBranch`` says. A
fixture that then writes a ``CONTEXT.md`` declaring ``branches: integration:
main`` — or hands the repo to a verb that resolves a base branch — is only
self-consistent by accident, on hosts configured the way its author's was.

What that cost. ``tests/integration/test_serve_socket.py``'s ``workspace``
fixture built its repo with a bare ``git init -q`` and declared ``integration:
main``. On the author's machine (``init.defaultBranch=main``) it passed; on the
GitHub Actions runner it did not, because ``start`` resolves its base through
``resolve_base_branch`` and git answered ``fatal: invalid reference: main``.
**CI was red on every push to `dev` for two days**, during which four tickets
merged behind a green *local* gate. The local gate cannot see this class: it
runs on hosts that overwhelmingly default to ``main``, so the divergence was
only observable where nobody was reading.

The repo's own convention already prevented it — nearly every fixture forces the
branch (``-b dev``, ``-b main``, ``--initial-branch=dev``, ``--bare``). Exactly
two did not. This guard is what stops the next one, and it derives its subject
set from the tracked test tree so a fixture added tomorrow is scanned without
anyone remembering to list it.

**Why ``--bare`` is exempt rather than special-cased away.** A bare repository
has no working tree and no checked-out branch, so there is no default-branch
dependency to inherit; ``git init --bare`` followed by a push of an explicit
refspec is a legitimate and branch-independent shape.

**Predicate choice.** The detector reads the AST and locates the git
*subcommand*, not the word ``init`` anywhere in an argv. The cheaper text
predicate is unusable here and not hypothetically so: this tree spells
``"-m", "init"`` — a commit *message* — in more than a dozen fixtures, and a
regex ban would flag every one of them while the real defect sat elsewhere.
:func:`test_a_commit_message_reading_init_is_not_a_git_init` pins that blind
spot by feeding the detector the exact shape.

**Residual, stated rather than left implicit.** ``git -C <literal-path> init``
would not be seen, because the detector takes the first non-flag token as the
subcommand and that literal path would claim the position. No fixture here
spells that; every one passes ``cwd=``.

That residual is stated narrowly on purpose. This module's first draft claimed a
*broader* one — that no fixture builds its argv anywhere but at a call site —
and it was false: ``tests/unit/test_hooks_module_type.py`` collects argvs in a
tuple and runs them through a loop variable, which the first detector could not
see. The mutation run is what caught it, by predicting a kill that never
arrived. The detector now reads argv list literals wherever they appear, and
:func:`test_the_detector_flags_an_argv_bound_to_a_loop_variable` holds that
open.
"""

from __future__ import annotations

import ast
from pathlib import Path

from tests._gitutil import tracked_py_sources

#: The scanned base. Fixtures are the subject: no production code in this repo
#: runs ``git init``, and a production call would be a different rule with
#: different reasoning.
_SCANNED_BASE = "tests"

#: A file the derivation must still reach. Non-empty alone would go green on a
#: scan narrowed to nothing; a named member fails loudly on a rename instead of
#: quietly shrinking the subject set. The hook-manifest module builds fixture
#: repos with literal ``git init`` argvs (including the loop-variable shape this
#: detector was widened for), so it anchors both the file list and the detector.
_ANCHOR = "tests/unit/test_hooks_module_type.py"

#: Spellings that make the branch explicit. ``-b`` and ``--initial-branch`` are
#: the two git accepts; both appear in this tree.
_BRANCH_FLAGS = ("-b", "--initial-branch")

#: A repository with no working tree has no default branch to inherit.
_BARE_FLAG = "--bare"


def _constants(nodes: list[ast.expr]) -> list[str]:
    """The string constants among ``nodes``, in order, non-literals dropped.

    Dropping non-literals is what lets ``str(repo_root)`` and ``tmp_path`` sit
    anywhere in an argv without confusing the reader.
    """
    return [
        node.value
        for node in nodes
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    ]


def _argv_candidates(tree: ast.AST) -> list[tuple[int, list[str]]]:
    """``(lineno, tokens)`` for every expression that could be a git argv.

    Two sources, because this tree spells an argv two ways and **neither
    subsumes the other**:

    * A **list literal** starting with ``"git"``, read wherever it appears
      rather than only where it is passed to a call. This is not generality for
      its own sake: ``tests/unit/test_hooks_module_type.py`` collects three
      argvs in a tuple and runs them through a loop variable
      (``for cmd in (...): subprocess.run(cmd, ...)``), so the ``git init`` is
      never an argument to any call. A detector reading only call arguments is
      blind to it — which is exactly what the #369 mutation run caught, after
      this module's first draft claimed in prose that no fixture built a call
      that way. :func:`test_the_detector_flags_an_argv_bound_to_a_loop_variable`
      is that blind spot turned into a control.
    * A **call's own positional constants**, for the helper form where ``git``
      is implied and the subcommand comes first (``_git(path, "init", "-q")``).

    A call's list argument is deliberately *not* expanded into the call's own
    tokens: the list literal is already a candidate in its own right, and
    expanding it would report the same argv twice.

    Requiring the leading ``"git"`` on the list form is what keeps an unrelated
    list of strings that happens to contain ``"init"`` from being read as a
    repository creation.
    """
    candidates: list[tuple[int, list[str]]] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.List, ast.Tuple)):
            tokens = _constants(list(node.elts))
            if tokens[:1] == ["git"]:
                candidates.append((node.lineno, tokens[1:]))
        elif isinstance(node, ast.Call):
            tokens = _constants(list(node.args))
            if tokens:
                candidates.append((node.lineno, tokens))
    return candidates


def _subcommand(tokens: list[str]) -> str | None:
    """The git subcommand ``tokens`` invokes, or ``None``.

    The first non-flag token. This is the whole reason a commit carrying the
    message ``init`` is not mistaken for a repository creation: there,
    ``commit`` claims the subcommand position and ``init`` is merely a later
    argument.
    """
    for token in tokens:
        if not token.startswith("-"):
            return token
    return None


def git_init_calls(source: str, relpath: str) -> list[str]:
    """``<relpath>:<lineno>`` for every argv that creates a repository.

    Named separately from the offender predicate below so the non-vacuity floor
    can assert the detector *finds* something. A guard whose detector silently
    returned ``[]`` would satisfy the ban having read nothing at all.
    """
    return [
        f"{relpath}:{lineno}"
        for lineno, tokens in _argv_candidates(ast.parse(source))
        if _subcommand(tokens) == "init"
    ]


def git_init_calls_inheriting_their_branch(source: str, relpath: str) -> list[str]:
    """``<relpath>:<lineno>`` for every ``git init`` that names no branch.

    Named once so the real assertion and every control route through the same
    predicate: a control carrying its own inline copy of the detector would keep
    passing while the detector it protects became a no-op.
    """
    hits: list[str] = []
    for lineno, tokens in _argv_candidates(ast.parse(source)):
        if _subcommand(tokens) != "init":
            continue
        if _BARE_FLAG in tokens:
            continue
        if any(token.startswith(_BRANCH_FLAGS) for token in tokens):
            continue
        hits.append(f"{relpath}:{lineno}")
    return hits


def _scanned_sources() -> list[Path]:
    return tracked_py_sources(_SCANNED_BASE)


def _scan(predicate) -> list[str]:
    repo_root = Path(__file__).resolve().parents[2]
    found: list[str] = []
    for path in _scanned_sources():
        relpath = str(path.relative_to(repo_root))
        found += predicate(path.read_text(encoding="utf-8"), relpath)
    return found


def test_no_fixture_inherits_its_default_branch_from_the_host() -> None:
    """The rule itself. A fixture that depends on a branch name must state it,
    so the suite means the same thing on every host that runs it."""
    offenders = _scan(git_init_calls_inheriting_their_branch)

    assert offenders == [], (
        "`git init` takes its branch from the host's `init.defaultBranch`, so a "
        "fixture that omits one is only self-consistent by accident — this is "
        "what kept CI red for two days while the local gate stayed green "
        "(#369). Pass an explicit `-b <name>` (or `--initial-branch=<name>`), "
        "matching whatever branch the fixture's spine declares or its hook "
        f"resolves. Offending sites: {offenders}"
    )


def test_the_scan_reaches_the_fixtures_it_claims_to() -> None:
    """Non-vacuity floor, on the *detector* rather than only on the file list.

    Two ways this guard could pass over nothing, and both are closed here: the
    tracked-source derivation collapsing to ``[]``, and the detector itself
    ceasing to recognise a ``git init``. The ban above is free in either case.
    """
    repo_root = Path(__file__).resolve().parents[2]
    scanned = {str(p.relative_to(repo_root)) for p in _scanned_sources()}

    assert len(scanned) > 1, f"the {_SCANNED_BASE}/ scan derived to {scanned}"
    assert _ANCHOR in scanned, (
        f"the scan no longer reaches {_ANCHOR}, which builds fixture repos "
        f"with literal `git init` argvs; it found {len(scanned)} sources"
    )

    found = _scan(git_init_calls)
    assert len(found) > 5, f"the detector no longer recognises a `git init`: {found}"
    assert any(hit.startswith(f"{_ANCHOR}:") for hit in found), (
        f"the detector no longer sees the `git init` in {_ANCHOR}; it found {found}"
    )


def test_the_detector_flags_a_bare_list_form_init() -> None:
    """Positive control: the exact shape ``tests/_gitutil.py`` carried."""
    sample = 'subprocess.run(["git", "init", "-q"], cwd=path)\n'

    assert git_init_calls_inheriting_their_branch(sample, "s.py") == ["s.py:1"]


def test_the_detector_flags_a_helper_form_init() -> None:
    """Positive control for the other shape in this tree, where the repo path is
    positional and ``git`` is implied by the helper (``_git(path, "init")``). A
    detector keyed on a literal leading ``"git"`` would miss every one of these
    while the list-form control above still passed."""
    sample = '_git(path, "init", "-q")\n'

    assert git_init_calls_inheriting_their_branch(sample, "s.py") == ["s.py:1"]


def test_the_detector_flags_an_argv_bound_to_a_loop_variable() -> None:
    """The blind spot the mutation run found, turned into a control.

    ``tests/unit/test_hooks_module_type.py`` builds three argvs in a tuple and
    runs each through a loop variable, so the ``git init`` is an argument to no
    call at all. The first draft of this detector read only call arguments and
    was silently blind to it — the guard reported zero offenders over a file it
    could not see. Keyed on the list literal, so it does not matter what the
    argv is later passed to, or whether it is passed to anything.
    """
    sample = (
        "for cmd in (\n"
        '    ["git", "init"],\n'
        '    ["git", "config", "user.name", "t"],\n'
        "):\n"
        "    subprocess.run(cmd, cwd=fixture)\n"
    )

    assert git_init_calls_inheriting_their_branch(sample, "s.py") == ["s.py:2"]


def test_an_unrelated_list_naming_init_is_not_an_argv() -> None:
    """Negative control for the cost of reading list literals everywhere.

    Widening the detector past call arguments buys the loop-variable shape above
    but risks reading any list of strings as a command. The leading ``"git"`` is
    what separates them, so a list that merely contains ``init`` — a table of
    verb names, say — stays untouched.
    """
    sample = 'VERBS = ["init", "start", "review"]\n'

    assert git_init_calls(sample, "s.py") == []
    assert git_init_calls_inheriting_their_branch(sample, "s.py") == []


def test_the_detector_accepts_a_short_branch_flag() -> None:
    """Negative control. ``-b dev`` is the fix; flagging it would ban the
    remedy."""
    sample = '_git(repo_root, "init", "-b", "dev")\n'

    assert git_init_calls_inheriting_their_branch(sample, "s.py") == []


def test_the_detector_accepts_the_long_branch_flag() -> None:
    """Negative control for the second legal spelling, which this tree uses in
    two places. A detector checking only for ``-b`` would flag both."""
    sample = 'subprocess.run(["git", "init", "--initial-branch=main"])\n'

    assert git_init_calls_inheriting_their_branch(sample, "s.py") == []


def test_the_detector_accepts_a_bare_repository() -> None:
    """Negative control. A bare repo has no working tree and no checked-out
    branch, so there is no host default to inherit."""
    sample = 'subprocess.run(["git", "init", "-q", "--bare", str(origin)])\n'

    assert git_init_calls_inheriting_their_branch(sample, "s.py") == []


def test_a_commit_message_reading_init_is_not_a_git_init() -> None:
    """The control written out of the rejected predicate's blind spot.

    A text or regex ban — the cheaper detector — would flag this sample, because
    it spells ``init`` inside the argv. That is not hypothetical prose: more than
    a dozen fixtures in this tree commit with exactly this message, and every one
    of them would have been reported as an offender. The sample asserts *both*
    directions, so the blind spot is explicit rather than implied by a bare
    non-match.
    """
    sample = '_git(repo, "commit", "--allow-empty", "-q", "-m", "init")\n'

    assert '"init"' in sample, (
        "the sample must spell the flagged word, which is exactly why a text "
        "ban would certify this commit as a repository creation"
    )
    assert git_init_calls_inheriting_their_branch(sample, "s.py") == []
    assert git_init_calls(sample, "s.py") == []
