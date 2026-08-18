"""#457 AC-5 — both hooks derive the same protected set from one ``CONTEXT.md``.

``hooks/push-target-guard.js`` and ``hooks/gate-evidence-guard.js`` each carry
their own parser for ``CONTEXT.md``'s ``branches:`` block, because #436 declined
a shared ``hooks/lib/`` (``test_hooks_fail_open_is_loud``,
``test_hooks_module_type`` and ``test_hooks_no_empty_catch`` all scan
``hooks/*.js`` **non-recursively**, so a subdirectory would be a hole in three
guards at once, and a shared module's own load failure would disarm both
enforcement hooks together).

The **marker** half of that duplication has been pinned by execution since #436
(``test_gate_marker_contract.py``). The **branches** half never was, and it had
already drifted in shape by the time #457 measured it: an array from one parser,
a map from the other. Shape is not the risk — the two consume their own return
value correctly. The risk is the *set that falls out*, which is what each hook
actually decides on, and where drift is silent in both directions:

* the push guard stops refusing a push to a branch the Stop hook still treats as
  shared, so unverified work lands; or
* the Stop hook skips a worktree the push guard would refuse to publish from, so
  a claim of completion goes unchallenged on a branch that matters.

This module therefore compares **protected sets, never return values**. The
differing shapes are deliberate and are not unified here; an equivalence test is
the drift control the no-shared-lib decision asks for, and unlike an extraction
it adds no new failure mode.

The corpus is the three variants the ticket names plus two that separate the
parser from its fallback: a declared block, no file at all, a malformed block, an
empty block, and values written as full refs. Each is a shape a real repo
produces — a repo that never adopted the guidance has no ``CONTEXT.md``, and a
hand-edited one is how a malformed block arrives.

:func:`test_a_declared_block_is_actually_read` is the anti-vacuity spine: without
it, two parsers that both ignored ``CONTEXT.md`` entirely and both returned the
fallback would agree perfectly on every variant.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

from tests.unit._prose import REPO_ROOT

_HOOKS_DIR = REPO_ROOT / "hooks"

_PUSH_HOOK = "push-target-guard.js"
_STOP_HOOK = "gate-evidence-guard.js"

#: How each hook's own call sites reach its protected set, transcribed. The push
#: guard resolves the repository itself; the Stop hook takes the parse and the
#: directory separately, because ``verdictFor`` reuses the parse for a second
#: question. Neither expression re-implements a parser — both call the shipped
#: functions — but the *composition* is this module's, which is why
#: :func:`test_the_expressions_match_the_call_sites_they_stand_in_for` pins it
#: against the source.
_PROTECTED_SET = {
    _PUSH_HOOK: "[...h.protectedBranches(process.cwd())].sort().join(',')",
    _STOP_HOOK: (
        "[...h.protectedBranches("
        "h.declaredConfig(process.cwd()),"
        " process.cwd())].sort().join(',')"
    ),
}

#: A repo that declares its branches. Values differ from the fallback names on
#: purpose except where they must not: ``main`` is shared with the fallback, and
#: ``feature-lane`` is a name no fallback holds, so a parser that ignored the
#: file could not produce this set by accident.
_DECLARED = """# CONTEXT.md

```yaml
repo:
  name: sample
branches:
  integration: dev-lane
  staging: staging-lane
  release: main
  experiment: feature-lane   # any key counts, not only the known roles
```
"""

#: A block whose body is a yaml sequence rather than a mapping — the shape a
#: hand-edit produces. Neither parser understands it; what matters is that they
#: fail to understand it identically and fall back together.
_MALFORMED = """# CONTEXT.md

```yaml
branches:
  - main
  - staging
    release main
```
"""

#: Declared, but with nothing under the key. The block exists and is empty, which
#: is a different code path from "no file" in both parsers.
_EMPTY_BLOCK = """# CONTEXT.md

```yaml
branches:
tracker: github
```
"""

#: Full refs, which both hooks reduce with their own ``branchName``. A parser
#: that stopped reducing would protect ``refs/heads/dev-lane`` — a name no push
#: ever names — and silently stop protecting anything.
_FULL_REFS = """# CONTEXT.md

```yaml
branches:
  integration: refs/heads/dev-lane
  release: refs/remotes/origin/main
```
"""

_VARIANTS = {
    "declared": _DECLARED,
    "missing": None,
    "malformed": _MALFORMED,
    "empty-block": _EMPTY_BLOCK,
    "full-refs": _FULL_REFS,
}


def _node() -> str:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node not available")
    return node


def _git(repo: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", *args], cwd=repo, check=True, capture_output=True, text=True
    )
    return completed.stdout.strip()


def _repo_with(tmp_path: Path, context: str | None, spine: str | None = None) -> Path:
    """A repository whose ``CONTEXT.md`` is ``context`` and ``CLAUDE.md`` is
    ``spine``; either is absent for ``None``.

    No remote and so no ``origin/HEAD``: that arm adds the same name to both
    sets by the same call, so including it would only add a second reason for
    the sets to agree.
    """
    root = tmp_path / "repo"
    root.mkdir(parents=True)
    _git(root, "init", "-q", "--initial-branch=dev")
    _git(root, "config", "user.email", "t@example.com")
    _git(root, "config", "user.name", "t")
    if context is not None:
        (root / "CONTEXT.md").write_text(context)
    if spine is not None:
        (root / "CLAUDE.md").write_text(spine)
    (root / "a.txt").write_text("one\n")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "first")
    return root


def _protected(hook: str, repo: Path) -> set[str]:
    """The protected set ``hook`` derives, by executing the shipped module.

    ``require()``ing a hook does not run it — every hook guards its entry point
    with ``require.main === module`` — so this reads the real implementation
    rather than a restatement of it.
    """
    script = (
        "const h = require(process.env.HOOK_PATH);"
        f"process.stdout.write(String({_PROTECTED_SET[hook]}));"
    )
    proc = subprocess.run(
        [_node(), "-e", script],
        cwd=repo,
        capture_output=True,
        text=True,
        timeout=60,
        env={**os.environ, "HOOK_PATH": str(_HOOKS_DIR / hook)},
    )
    assert proc.returncode == 0, (
        f"{hook} could not produce a protected set (rc={proc.returncode}): {proc.stderr.strip()}"
    )
    return {name for name in proc.stdout.strip().split(",") if name}


def _fallback() -> set[str]:
    proc = subprocess.run(
        [
            _node(),
            "-e",
            "process.stdout.write(require(process.env.HOOK_PATH).FALLBACK_PROTECTED.join(','))",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=60,
        env={**os.environ, "HOOK_PATH": str(_HOOKS_DIR / _PUSH_HOOK)},
    )
    assert proc.returncode == 0, proc.stderr
    return set(proc.stdout.strip().split(","))


# --- the equivalence ----------------------------------------------------------


@pytest.mark.parametrize("variant", sorted(_VARIANTS))
def test_both_parsers_derive_the_same_protected_set(variant: str, tmp_path: Path) -> None:
    """One ``CONTEXT.md``, two parsers, one answer.

    The comparison is over the sets each hook *decides on*, not over the values
    the parsers return: an array and a map are different objects that must mean
    the same thing, and unifying them is explicitly not what this change does.
    """
    repo = _repo_with(tmp_path, _VARIANTS[variant])

    from_push = _protected(_PUSH_HOOK, repo)
    from_stop = _protected(_STOP_HOOK, repo)

    assert from_push == from_stop, (
        f"the two CONTEXT.md parsers disagree on the {variant!r} fixture: "
        f"push-target-guard protects {sorted(from_push)}, gate-evidence-guard "
        f"protects {sorted(from_stop)}. One hook is now refusing pushes to "
        "branches the other treats as ordinary, or the reverse — and the "
        "duplication was accepted only on the condition that it stays equivalent."
    )
    assert from_push, (
        f"both parsers derived an empty protected set on {variant!r}, so the "
        "equality above compares nothing. Every variant must protect something: "
        "the fallback exists precisely so an unreadable declaration still does."
    )


# --- anti-vacuity: the file is really read ------------------------------------


def test_a_declared_block_is_actually_read(tmp_path: Path) -> None:
    """The spine of this module.

    Two parsers that both ignored ``CONTEXT.md`` and both returned the fallback
    would satisfy every equality above on every variant, forever. This is the one
    assertion that separates *agreeing* from *agreeing because neither of them
    looks*, and it is deliberately outside the parametrization so an empty
    variant map cannot delete it.
    """
    repo = _repo_with(tmp_path, _DECLARED)
    fallback = _fallback()

    for hook in (_PUSH_HOOK, _STOP_HOOK):
        derived = _protected(hook, repo)
        assert "feature-lane" in derived, (
            f"{hook} did not read the declared branches: {sorted(derived)}. "
            "`feature-lane` sits under an invented role key, which is the point "
            "— every value in the block counts, not only the known roles."
        )
        assert derived != fallback, (
            f"{hook} returned the fallback set for a repo that declares its own "
            "branches, so CONTEXT.md is not being read at all"
        )


def test_an_unreadable_declaration_falls_back_rather_than_protecting_nothing(
    tmp_path: Path,
) -> None:
    """The direction that is dangerous to get wrong.

    A parser that returned "no branches declared" as "nothing is protected"
    would make a malformed ``CONTEXT.md`` an unlock rather than a degradation.
    Both hooks must instead reach the conservative fallback, and this pins the
    fallback's *membership* against each parser's answer rather than a count.
    """
    fallback = _fallback()

    for variant in ("missing", "malformed", "empty-block"):
        repo = _repo_with(tmp_path / variant, _VARIANTS[variant])
        for hook in (_PUSH_HOOK, _STOP_HOOK):
            assert _protected(hook, repo) == fallback, (
                f"{hook} did not fall back to the conservative set on the "
                f"{variant!r} fixture. An unreadable declaration must protect "
                "more, never less."
            )


# --- the expressions above stand in for real call sites -----------------------


def test_the_expressions_match_the_call_sites_they_stand_in_for() -> None:
    """The composition in :data:`_PROTECTED_SET` is this module's, so pin it.

    The parsers themselves are executed, not restated — but *how* each hook's
    protected set is assembled from them is written here, and a hook whose call
    site stopped composing them this way would leave this module measuring an
    equivalence nothing in production depends on (``craft.md`` → *Exercise the
    production path, not merely a production constant*).

    Structural, not semantic (ADR 0016): it asserts the two calls appear in the
    source that has to make them, and says nothing about what the surrounding
    code means.
    """
    push = (_HOOKS_DIR / _PUSH_HOOK).read_text(encoding="utf-8")
    stop = (_HOOKS_DIR / _STOP_HOOK).read_text(encoding="utf-8")

    assert "protectedBranches(dir)" in push, (
        f"{_PUSH_HOOK} no longer resolves its protected set from a directory "
        "alone, so this module's expression for it is stale"
    )
    assert "protectedBranches(declared, " in stop, (
        f"{_STOP_HOOK} no longer composes protectedBranches over a parsed "
        "declaration, so this module's expression for it is stale"
    )
    assert "declaredConfig(sessionTop)" in stop and "declaredConfig(top)" in stop, (
        f"{_STOP_HOOK} no longer resolves its declaration through "
        "declaredConfig at both call sites, so this module's expression for "
        "it is stale"
    )
    for hook_name, source in ((_PUSH_HOOK, push), (_STOP_HOOK, stop)):
        assert 'CLAUDE.md' in source and 'CONTEXT.md' in source, (
            f"{hook_name} no longer reads the spine first with the CONTEXT.md "
            "fallback, so the preference tests below measure a path that is "
            "not the production one"
        )


# --- the spine is preferred; CONTEXT.md is the fallback (v5) -------------------

_SPINE_DECLARED = _DECLARED.replace("# CONTEXT.md", "# spine").replace(
    "feature-lane", "spine-lane"
)


@pytest.mark.parametrize("hook", [_PUSH_HOOK, _STOP_HOOK])
def test_the_spine_wins_when_both_files_declare(hook: str, tmp_path: Path) -> None:
    """A repo carrying both files reads ``CLAUDE.md``, not ``CONTEXT.md``.

    The two fixtures declare different sets, so a hook still reading
    ``CONTEXT.md`` first produces ``feature-lane`` and fails here.
    """
    repo = _repo_with(tmp_path, _DECLARED, spine=_SPINE_DECLARED)
    got = _protected(hook, repo)
    assert "spine-lane" in got and "feature-lane" not in got, (
        f"{hook} read CONTEXT.md although CLAUDE.md declares branches: {got}"
    )


@pytest.mark.parametrize("hook", [_PUSH_HOOK, _STOP_HOOK])
def test_a_spine_without_branches_falls_through(hook: str, tmp_path: Path) -> None:
    """A generic ``CLAUDE.md`` with no ``branches:`` block must not mask the
    declaration in ``CONTEXT.md`` — the un-migrated-repo case."""
    repo = _repo_with(tmp_path, _DECLARED, spine="# just a memory file\n")
    got = _protected(hook, repo)
    assert "feature-lane" in got, (
        f"{hook} let a block-less CLAUDE.md mask CONTEXT.md's declaration: {got}"
    )
