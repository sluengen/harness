"""#457 AC-5 — both hooks derive the same protected set from one ``CONTEXT.md``.

``hooks/push-target-guard.js`` and ``hooks/gate-evidence-guard.js`` each carry
their own parser for ``CONTEXT.md``'s ``branches:`` block, because #436 declined
a shared ``hooks/lib/`` (``test_hooks_fail_open_is_loud`` and
``test_hooks_module_type`` both scan
``hooks/*.js`` **non-recursively**, so a subdirectory would be a hole in those
guards at once, and a shared module's own load failure would disarm both
enforcement hooks together).

The **marker** half of that duplication has been pinned by execution since #436
(``test_gate_marker_contract.py``, which since #500 holds three copies in one
language rather than two in JavaScript and one in Python). The **branches** half
never was, and it had already drifted in shape by the time #457 measured it: an
array from one parser, a map from the other. Shape is not the risk — the two
consume their own return value correctly. The risk is the *set that falls out*,
which is what each hook actually decides on, and where drift is silent in both
directions:

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
#: The separator is a **newline**, not a comma. A branch name may legally contain
#: a comma — ``{release: "has,comma"}`` is the #488 fixture that proves it — and a
#: comma-joined transport splits that one name into two on the way back, so the
#: harness would report a defect the hook does not have. A newline cannot appear
#: in a branch name (git refuses it), so it separates without ambiguity.
_JOIN = "\\n"

_PROTECTED_SET = {
    _PUSH_HOOK: f"[...h.protectedBranches(process.cwd())].sort().join('{_JOIN}')",
    _STOP_HOOK: (
        "[...h.protectedBranches("
        "h.declaredConfig(process.cwd()),"
        f" process.cwd())].sort().join('{_JOIN}')"
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

#: The flow-mapping spelling of a declaration (#487). Byte-for-byte valid yaml
#: that ``yaml.safe_load`` reads exactly as it reads :data:`_DECLARED`'s block,
#: and that a line scanner keyed on a bare ``branches:`` line reads as *nothing*
#: — the whole defect.
#:
#: The declaration appears here in **exactly one** form. There is no block-form
#: ``branches:`` anywhere in this fixture, so a scanner without the flow arm has
#: nothing else it could have found; ``repo:`` is a block mapping on purpose, to
#: keep the fixture a realistic spine without giving the old scanner a second
#: chance. Every value is a name no ``FALLBACK_PROTECTED`` entry carries (floored
#: in :func:`test_a_flow_mapping_declaration_is_actually_read`), so "parsed
#: correctly" can never be confused with "fell back". The three spellings the arm
#: has to survive are all present at once: several pairs, a quoted value, and a
#: comment after the closing brace.
_FLOW_MAPPING = """# CONTEXT.md

```yaml
repo:
  name: sample
branches: {integration: flow-lane, staging: "quoted-lane", release: brace-lane}  # still yaml
```
"""

#: The values :data:`_FLOW_MAPPING` declares, named once so the fixture and the
#: assertion cannot drift apart.
_FLOW_VALUES = {"flow-lane", "quoted-lane", "brace-lane"}

#: An empty flow mapping. Legal yaml, and a genuinely empty declaration rather
#: than an unreadable one, so the conservative fallback is the right answer —
#: the same answer the ``empty-block`` variant gets by the other spelling. This
#: variant is a regression guard on the flow arm *not over-reaching*: an arm that
#: threw, or that produced a stray value, on ``{}`` fails here.
_EMPTY_FLOW = """# CONTEXT.md

```yaml
branches: {}
tracker: github
```
"""

#: #488 spelling 1 — a block declaration whose **key line carries an inline
#: comment**. Legal yaml, and one keystroke from this repository's own spine:
#: ``CLAUDE.md``'s yaml block already writes inline comments on sibling lines of
#: the very block this parser reads — ``branches.release`` among them, inside the
#: ``branches:`` mapping itself. Until #488 the block arm keyed on
#: ``/^branches:\s*$/`` against the trimmed line, so the perfectly ordinary
#: mapping below the comment was skipped entirely and both hooks fell back.
#:
#: The comment text names a branch-shaped word on purpose. A fix that stripped
#: the comment by splitting the line rather than by asking whether the key's
#: *value* is empty could leak ``ignored-lane`` into the protected set, and
#: :func:`test_a_key_line_comment_is_actually_read` refuses exactly that.
_KEY_COMMENT_BLOCK = """# CONTEXT.md

```yaml
repo:
  name: sample
branches:   # the shared ones, not ignored-lane
  integration: comment-lane
  release: comment-main
```
"""

#: The values :data:`_KEY_COMMENT_BLOCK` declares, and the word its comment
#: mentions but does not declare.
_KEY_COMMENT_VALUES = {"comment-lane", "comment-main"}
_KEY_COMMENT_NON_VALUE = "ignored-lane"

#: #488 spelling 2 — a **comma inside a quoted value**. Until #488 the flow arm
#: split its body on every comma, so this fixture derived ``{"has`` (a name
#: opening with a quote character, which no branch can be) and dropped the real
#: ``has,comma`` entirely. Both hooks were wrong *identically*, which is why the
#: parametrized equivalence below could not see it and why
#: :func:`test_a_quoted_comma_is_actually_read` exists.
#:
#: Both quoting styles appear, and **each carries a comma of its own**. That is
#: the dimension the first version of this fixture held constant: its
#: single-quoted value was ``'single-lane'``, comma-free, so ``[^,]*`` plus
#: ``stripQuotes`` produced the identical answer whether or not the single-quote
#: alternative existed. Deleting that alternative from both hooks left the whole
#: suite green while ``{integration: 'has,comma'}`` derived the fragment
#: ``'has`` in production — the #488 defect itself, surviving for single quotes
#: only (``craft.md`` → *a corpus is blind to a dimension its fixtures all hold
#: constant*). One bare value is kept beside them so the fix still cannot be a
#: rule that only reads quoted values.
_QUOTED_COMMA_FLOW = """# CONTEXT.md

```yaml
repo:
  name: sample
branches: {integration: 'also,comma', release: "has,comma", extra: plain-lane}
```
"""

#: The values :data:`_QUOTED_COMMA_FLOW` declares. Both quoted values were
#: destroyed by the old splitter, one per quoting style, and removing either
#: alternative of ``FLOW_PAIR`` is killed by a different one of them — which is
#: what makes both alternatives measured rather than merely present.
#: ``plain-lane`` is the bare control.
_QUOTED_COMMA_VALUES = {"also,comma", "has,comma", "plain-lane"}

#: #488 spelling 3 — **CRLF line endings** with an ordinary indented block. The
#: asymmetry this closes is exact: the flow arm ran against ``line.trim()``,
#: which drops the ``\r``, while the block arm ran ``PAIR`` against the raw
#: line, where ``/(.*)$/`` cannot cross a ``\r`` because JavaScript counts it as
#: a line terminator — ``PAIR.exec("  integration: crlf-lane\r")`` was ``null``.
#: So the *same* declaration parsed in the flow spelling and vanished in the
#: block spelling. Any consumer cloned on Windows under ``core.autocrlf=true`` is
#: in this state.
#:
#: :data:`_CRLF_FLOW` is its other half: without it the fix could be "the block
#: arm now tolerates ``\r``" while the flow arm silently stopped doing so.
#: Built by joining on ``\r\n`` rather than written as one literal: the fixture
#: is legible as the yaml it is, and every line ending comes from one place, so
#: none can be missed by eye.
_CRLF_BLOCK = "\r\n".join(
    [
        "# CONTEXT.md",
        "",
        "```yaml",
        "repo:",
        "  name: sample",
        "branches:",
        "  integration: crlf-lane",
        "  release: crlf-main",
        "```",
        "",
    ]
)

_CRLF_FLOW = "\r\n".join(
    [
        "# CONTEXT.md",
        "",
        "```yaml",
        "branches: {integration: crlf-flow-lane, release: crlf-flow-main}",
        "```",
        "",
    ]
)

_CRLF_BLOCK_VALUES = {"crlf-lane", "crlf-main"}
_CRLF_FLOW_VALUES = {"crlf-flow-lane", "crlf-flow-main"}

_PARTIAL_FLOW = """# CONTEXT.md

```yaml
branches: {\"integration\": partial-flow-lane, release: partial-flow-main}
```
"""

_PARTIAL_BLOCK = """# CONTEXT.md

```yaml
branches:
  integration: partial-block-lane
  \"release\": partial-block-main
```
"""

_DUPLICATE_VALUE_BLOCK = """# CONTEXT.md

```yaml
branches:
  integration: shared-lane
  release: shared-lane
```
"""

_VARIANTS = {
    "declared": _DECLARED,
    "missing": None,
    "malformed": _MALFORMED,
    "empty-block": _EMPTY_BLOCK,
    "full-refs": _FULL_REFS,
    "flow-mapping": _FLOW_MAPPING,
    "empty-flow": _EMPTY_FLOW,
    "key-comment-block": _KEY_COMMENT_BLOCK,
    "quoted-comma-flow": _QUOTED_COMMA_FLOW,
    "crlf-block": _CRLF_BLOCK,
    "crlf-flow": _CRLF_FLOW,
    "partial-flow": _PARTIAL_FLOW,
    "partial-block": _PARTIAL_BLOCK,
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
        # ``newline=""`` disables newline translation on write. On a POSIX host
        # it changes nothing (``os.linesep`` is already ``\n``); it matters on the
        # platform whose clones produce a CRLF spine to begin with. The property
        # that is measured rather than assumed is the bytes on disk —
        # :func:`test_the_crlf_fixtures_really_carry_crlf`.
        (root / "CONTEXT.md").write_text(context, newline="")
    if spine is not None:
        (root / "CLAUDE.md").write_text(spine, newline="")
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
    return {name for name in proc.stdout.split("\n") if name}


def _fallback() -> set[str]:
    proc = subprocess.run(
        [
            _node(),
            "-e",
            "process.stdout.write("
            f"require(process.env.HOOK_PATH).FALLBACK_PROTECTED.join('{_JOIN}'))",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=60,
        env={**os.environ, "HOOK_PATH": str(_HOOKS_DIR / _PUSH_HOOK)},
    )
    assert proc.returncode == 0, proc.stderr
    return {name for name in proc.stdout.split("\n") if name}


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


def _assert_actually_read(
    tmp_path: Path, fixture: str, expected: set[str], spelling: str
) -> None:
    """Both hooks derive exactly ``expected`` from ``fixture``, and it is not the fallback.

    The read-assertion #488 AC-2 asks for, factored once because the three
    spellings need it identically. It is called only from tests that sit
    **outside** the parametrized equivalence, which is the whole point: the
    equivalence asks the two parsers to *agree*, and two parsers that both
    ignored a spelling agree perfectly by both falling back — the exact way #487
    passed on a broken tree.

    Three floors, because each one alone is satisfiable by a defect:

    * ``expected`` is non-empty and disjoint from the fallback, asserted before
      anything is parsed, so a later edit that moved one of these names into
      ``FALLBACK_PROTECTED`` reports itself here rather than quietly turning the
      comparison vacuous (``craft.md`` → *the empty comparison set*).
    * ``derived`` is non-empty — the operand a defect empties (#486).
    * ``derived == expected`` **exactly**, not containment. Containment passes a
      parser that also emits a fourth name nobody declared, which is precisely
      what the old comma splitter did.
    """
    fallback = _fallback()
    assert fallback, "the fallback set derived to nothing, so every comparison below is vacuous"
    assert expected, f"the {spelling!r} fixture declares no values, so this measures nothing"
    assert expected.isdisjoint(fallback), (
        f"the {spelling!r} fixture's values {sorted(expected)} overlap the fallback "
        f"{sorted(fallback)}, so a parser that ignored the fixture entirely could still "
        "produce them and this test would stop measuring the parse"
    )

    repo = _repo_with(tmp_path, fixture)
    for hook in (_PUSH_HOOK, _STOP_HOOK):
        derived = _protected(hook, repo)
        assert derived, (
            f"{hook} derived an empty protected set from the {spelling!r} spelling, "
            "so it read nothing at all"
        )
        assert derived != fallback, (
            f"{hook} returned the fallback set for the {spelling!r} spelling, so that "
            "declaration is not being read and the branches it names are unprotected"
        )
        assert derived == expected, (
            f"{hook} derived {sorted(derived)} from the {spelling!r} spelling, not "
            f"{sorted(expected)}. Equality rather than containment: a parser that "
            "emits an extra name nobody declared is the #488 comma defect itself."
        )


def test_a_key_line_comment_is_actually_read(tmp_path: Path) -> None:
    """#488 AC-1/AC-2, spelling 1 — an inline comment on the ``branches:`` key line.

    The block arm keyed on a *bare* ``branches:`` line, and yaml permits a
    comment after any key, so this declaration yielded nothing from either hook
    while looking entirely ordinary in the file. This repository's own spine
    writes inline comments on sibling lines of the same yaml block,
    ``branches.release`` — inside the ``branches:`` mapping itself — among them.

    The second assertion is the leak control. The fix asks whether the key's
    value — comment stripped — is empty, rather than widening the key pattern; a
    fix that instead split the line on whitespace, or that treated the comment
    body as a value, would admit ``ignored-lane`` from the comment text. Nothing
    in the equality above forbids that on its own, because a set that gained one
    extra member would still differ from the fallback.
    """
    _assert_actually_read(tmp_path, _KEY_COMMENT_BLOCK, _KEY_COMMENT_VALUES, "key-comment-block")

    repo = _repo_with(tmp_path / "leak", _KEY_COMMENT_BLOCK)
    for hook in (_PUSH_HOOK, _STOP_HOOK):
        assert _KEY_COMMENT_NON_VALUE not in _protected(hook, repo), (
            f"{hook} read {_KEY_COMMENT_NON_VALUE!r} out of the key line's *comment* and "
            "protected it as a branch. The comment is not part of the declaration."
        )


def test_a_quoted_comma_is_actually_read(tmp_path: Path) -> None:
    """#488 AC-1/AC-2, spelling 2 — a comma inside a quoted flow value.

    The one spelling of the three that was **silent**: the flow arm split its
    body on every comma, so both hooks derived a name beginning with a quote
    character and dropped the declared ``has,comma`` — wrong identically, which
    satisfies the parametrized equivalence perfectly and fires no notice.

    The explicit no-quote-character assertion is the shape pin. ``has,comma``
    being present already implies the split stopped, but a parser that produced
    it *and* also emitted the fragment ``"has`` would fail the equality above for
    a reason a reader would have to reconstruct; naming the character makes the
    defect legible where it is measured.
    """
    _assert_actually_read(tmp_path, _QUOTED_COMMA_FLOW, _QUOTED_COMMA_VALUES, "quoted-comma-flow")

    repo = _repo_with(tmp_path / "quotes", _QUOTED_COMMA_FLOW)
    for hook in (_PUSH_HOOK, _STOP_HOOK):
        derived = _protected(hook, repo)
        assert not [name for name in derived if '"' in name or "'" in name], (
            f"{hook} derived a branch name carrying a quote character: {sorted(derived)}. "
            "No branch can be named that; it is a fragment of a value the parser cut in half."
        )


def test_crlf_line_endings_are_actually_read(tmp_path: Path) -> None:
    """#488 AC-1/AC-2, spelling 3 — CRLF, in **both** arms.

    The block arm ran ``PAIR`` against the raw line, and ``/(.*)$/`` cannot cross
    a ``\r``, so a CRLF spine's block declaration parsed to nothing while the
    *same* declaration in the flow spelling parsed correctly. Any consumer cloned
    on Windows under ``core.autocrlf=true`` is in that state today.

    Both halves run here. The block half is the defect; the flow half is the
    control that the fix did not trade one arm for the other — a ``\r`` stripped
    in a way that broke the flow arm's own trim would pass a block-only test.
    """
    _assert_actually_read(tmp_path / "block", _CRLF_BLOCK, _CRLF_BLOCK_VALUES, "crlf-block")
    _assert_actually_read(tmp_path / "flow", _CRLF_FLOW, _CRLF_FLOW_VALUES, "crlf-flow")


def test_the_crlf_fixtures_really_carry_crlf(tmp_path: Path) -> None:
    """The floor under the fixture itself.

    A CRLF test whose fixture reached disk as LF measures the ordinary block
    spelling twice and passes on a tree where the defect is untouched — the
    #466 identically-passed-renders shape. Python's default newline translation
    on write is exactly how that happens, so the property is measured on the
    bytes the parser will actually read rather than trusted to the literal.
    """
    for spelling, fixture in (("crlf-block", _CRLF_BLOCK), ("crlf-flow", _CRLF_FLOW)):
        assert "\r\n" in fixture, f"the {spelling!r} literal carries no CRLF"
        repo = _repo_with(tmp_path / spelling, fixture)
        written = (repo / "CONTEXT.md").read_bytes()
        assert b"\r\n" in written, (
            f"the {spelling!r} fixture reached disk with its CRLF translated away, so "
            "the CRLF tests are measuring the ordinary LF spelling"
        )
        assert b"\n" not in written.replace(b"\r\n", b""), (
            f"the {spelling!r} fixture reached disk with mixed line endings, so a parser "
            "could satisfy it by reading only the LF-terminated lines"
        )


def test_a_flow_mapping_declaration_is_actually_read(tmp_path: Path) -> None:
    """#487 AC-1 — the flow spelling is *parsed*, not merely tolerated.

    The parametrized equivalence above only asks the two parsers to **agree**,
    and two parsers that both ignored the flow form would agree perfectly by both
    returning the fallback (``craft.md`` → *Exercise the production path, not
    merely a production constant*). This is the assertion that separates
    agreeing from agreeing-because-neither-of-them-looks, and it sits outside the
    parametrization so an empty variant map cannot delete it.

    Both operands of the inequality are floored. An empty derived set satisfies
    ``!= fallback`` while measuring nothing, and an empty fallback satisfies it
    for the opposite wrong reason (``craft.md`` → *The empty comparison set*).
    The disjointness floor is the third: it pins the fixture property the
    inequality rests on, so a later edit that moved one of these names into
    ``FALLBACK_PROTECTED`` reports itself here instead of quietly weakening the
    test.
    """
    fallback = _fallback()
    assert fallback, "the fallback set derived to nothing, so every comparison below is vacuous"
    assert _FLOW_VALUES.isdisjoint(fallback), (
        f"the flow fixture's values {sorted(_FLOW_VALUES)} now overlap the fallback set "
        f"{sorted(fallback)}, so a parser that ignored the fixture entirely could still "
        "produce them and this test would stop measuring the parse"
    )

    repo = _repo_with(tmp_path, _FLOW_MAPPING)
    for hook in (_PUSH_HOOK, _STOP_HOOK):
        derived = _protected(hook, repo)
        assert derived, (
            f"{hook} derived an empty protected set from the flow-mapping fixture, so the "
            "assertions below compare nothing"
        )
        assert derived == _FLOW_VALUES, (
            f"{hook} did not read the flow-mapping declaration: {sorted(derived)}. "
            "`branches: {integration: …}` is byte-for-byte valid yaml that a real loader "
            "reads identically to the block form, so a scanner that sees nothing in it "
            "protects branches the repo never declared and misses the ones it did (#487)."
        )
        assert derived != fallback, (
            f"{hook} returned the fallback set for a repo that declares its branches as a "
            "flow mapping, so the declaration is not being read at all"
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

    for variant in ("missing", "malformed", "empty-block", "empty-flow"):
        repo = _repo_with(tmp_path / variant, _VARIANTS[variant])
        for hook in (_PUSH_HOOK, _STOP_HOOK):
            assert _protected(hook, repo) == fallback, (
                f"{hook} did not fall back to the conservative set on the "
                f"{variant!r} fixture. An unreadable declaration must protect "
                "more, never less."
            )


@pytest.mark.parametrize(
    ("spelling", "fixture"),
    (("partial-flow", _PARTIAL_FLOW), ("partial-block", _PARTIAL_BLOCK)),
)
def test_a_partially_read_declaration_falls_back_completely(
    spelling: str, fixture: str, tmp_path: Path
) -> None:
    """#506 AC-4 — one unsupported pair invalidates the whole declaration.

    These are valid YAML mappings with a readable pair before a quoted key the
    deliberately small scanner does not support.  Before #506, each hook kept
    the first name, suppressing its unreadable notice and leaving the other
    declared branch unprotected.  The contract is complete-or-unreadable, so
    the production protected-set composition must select the conservative
    fallback rather than a subset.
    """
    fallback = _fallback()
    assert fallback, "the fallback set derived to nothing, so this regression measures nothing"

    repo = _repo_with(tmp_path, fixture)
    for hook in (_PUSH_HOOK, _STOP_HOOK):
        assert _protected(hook, repo) == fallback, (
            f"{hook} retained a partial protected set for {spelling!r}; an unsupported "
            "pair must discard the complete declaration rather than leave another "
            f"declared branch unprotected: {sorted(_protected(hook, repo))}"
        )


def test_a_block_mapping_may_assign_one_branch_to_multiple_roles(tmp_path: Path) -> None:
    """#506 review finding — duplicate values are not duplicate keys.

    The supported declaration grammar permits any role key, and the protected
    set naturally de-duplicates branch names.  Distinct keys that assign the
    same branch must therefore remain a complete readable mapping in both
    independently implemented parsers; only a repeated key is ambiguous.
    """
    _assert_actually_read(
        tmp_path, _DUPLICATE_VALUE_BLOCK, {"shared-lane"}, "duplicate-value-block"
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
