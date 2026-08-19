"""#487 AC-2 — a ``branches:`` declaration the hook cannot read says so, once.

Both enforcement hooks parse the spine's ``branches:`` block with a line scanner
and substitute ``FALLBACK_PROTECTED`` when the parse comes back empty. For any
repo using conventional branch names — most repos — that makes an **unreadable**
declaration byte-identical in effect to a readable one: the guards look healthy
right up until the repo's declaration diverges from the fallback, at which point
protection silently stops matching what the spine says. #487 filed exactly that,
found on a consumer migration; the flow-mapping spelling this change also fixes
was only the first spelling to reach it.

The fix for that spelling closes one hole. This notice is what keeps the *next*
unanticipated spelling from being indistinguishable from a readable spine: when a
file carries a ``branches:`` key and the scan yields nothing, the hook writes one
line to stderr naming that file and carries on exactly as before. Same posture as
the ``failOpen`` channel #303 added (``hooks/push-target-guard.js`` ``failOpen``,
``hooks/gate-evidence-guard.js`` ``failOpen``) and the same ``TAG`` prefix:
stdout, the exit status and the blocking contract are untouched, and no part of
the payload is echoed.

The three properties, and why each is here rather than assumed:

* **It fires, and it names the file.** :func:`test_an_unreadable_declaration_is_named_on_stderr`.
  Measured by executing the shipped module — ``require()`` does not run a hook,
  every one of them guards its entry with ``require.main === module`` — rather
  than by grepping for a reporting call, which would pass on a call no path
  reaches.
* **It stays silent on a spine that has no ``branches:`` key, and on one whose
  declaration parses.** :func:`test_a_spine_without_a_branches_key_is_silent` and
  :func:`test_a_readable_declaration_is_silent`. Without the first, a hook that
  chattered unconditionally would satisfy everything above; without the second,
  one that chattered whenever the *key* appeared would too. The second is also
  the derivation pin: the notice is keyed on what the scan produced, not on what
  the file contains.
* **It speaks once per file per process.** :func:`test_the_notice_is_written_once_per_process`.
  ``gate-evidence-guard`` resolves its declaration at two call sites
  (``declaredConfig(sessionTop)`` and ``declaredConfig(top)``), so a notice
  without the guard would double up on an ordinary Stop.

:func:`test_the_blocking_contract_is_unchanged_while_the_notice_fires` runs the
real ``push-target-guard`` binary end to end over an unreadable spine, so the
"stdout and the decision are untouched" half is observed on the production path
and not inferred from the helper calls above. Its Stop-hook counterpart is not
built here: that hook reads its trigger from the transcript first and allows
before it ever resolves a declaration, so an end-to-end run would exercise no
parse at all.

The corpus deliberately does **not** re-derive the protected sets — that is
``test_context_branch_parsing_contract.py``'s subject, and it owns the pin that
keeps these driving expressions matching the hooks' own call sites
(``test_the_expressions_match_the_call_sites_they_stand_in_for``). A rename on
either exported function surfaces here as a non-zero exit from ``node``, which
:func:`_run_parse` asserts against.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from tests.unit._prose import REPO_ROOT

_HOOKS_DIR = REPO_ROOT / "hooks"

_PUSH_HOOK = "push-target-guard.js"
_STOP_HOOK = "gate-evidence-guard.js"
_HOOKS = (_PUSH_HOOK, _STOP_HOOK)

#: The stable machine-readable marker in the notice. Tests key on this rather
#: than on the surrounding prose, which is free to be reworded — the same
#: convention ``test_hooks_fail_open_is_loud`` uses for ``fail-open:``.
_TOKEN = "unreadable-declaration:"

#: How each hook is driven down to its parse, through the exported production
#: entry point rather than through ``declaredBranches`` directly, so the notice
#: is proven to reach stderr from the composition the hook itself performs.
_DRIVE = {
    _PUSH_HOOK: "h.protectedBranches(process.cwd());",
    _STOP_HOOK: "h.protectedBranches(h.declaredConfig(process.cwd()), process.cwd());",
}

#: A spine whose ``branches:`` key is present and whose body no scanner here
#: understands: a yaml **sequence** where a mapping belongs, which is the shape a
#: hand-edit produces. This is the class the notice exists for — not the flow
#: mapping, which this change teaches both scanners to read.
_UNREADABLE = """# spine

```yaml
repo:
  name: sample
branches:
  - main
  - staging
```
"""

#: The second unreadable spelling, and the one that separates the notice's
#: **detector** from its **parsers**: a flow *sequence*. The key is on the line
#: and nothing follows the colon that either arm can read — no indented block, no
#: flow mapping — so a detector narrowed to "a bare ``branches:`` line" (which is
#: what the block arm keys on) reports nothing here while :data:`_UNREADABLE`
#: still fires. Enumerating both spellings is what makes the wider detector
#: load-bearing rather than incidental.
_UNREADABLE_INLINE = """# spine

```yaml
repo:
  name: sample
branches: [main, staging]
```
"""

#: The third unreadable spelling: a **nested** flow mapping. The flow arm accepts
#: a brace body that carries no braces of its own, and the constant it is written
#: as says so — a nested mapping "is left to the unreadable notice rather than
#: half-parsed". That is a claim about behaviour, so it is measured here rather
#: than asserted in a comment: widening the arm's body to admit nesting is a
#: mutation that survived the corpus this module shipped with, half-parsing
#: ``{name: deep-lane}`` into a branch name no repository ever declared.
_UNREADABLE_NESTED_FLOW = """# spine

```yaml
branches: {integration: {name: deep-lane}}
```
"""

#: The fourth: a flow mapping wrapped over several lines. Also legal yaml, also
#: out of the arm's reach by construction, and named in the same comment as
#: landing on the notice. Without it the "out of scope too" half of that comment
#: is unmeasured in exactly the way #487 was filed for.
_UNREADABLE_MULTILINE_FLOW = """# spine

```yaml
branches: {
  integration: wrapped-lane,
  release: wrapped-main
}
```
"""

#: The fifth: a plain scalar where a mapping belongs. Legal yaml, and the one
#: spelling here that a reader could mistake for a working declaration, because it
#: names a branch in plain sight. Neither arm reads it, so the branch it names is
#: not protected — which is worth one line on stderr rather than nothing.
_UNREADABLE_SCALAR = """# spine

```yaml
repo:
  name: sample
branches: lonely-lane
```
"""

#: The sixth, and a **limitation** rather than a shape nobody would write: a block
#: declaration whose key line carries an inline comment. The block arm keys on a
#: bare ``branches:`` line, so the perfectly readable mapping below it is skipped —
#: and this repository's own spine writes inline comments on four sibling lines of
#: the very block this parser reads, which is how close the spelling sits. The
#: refusal predates #487 (the old scanner was silent about it); pinning it here is
#: what makes the state observed rather than assumed, and is where a later change
#: that teaches the arm to tolerate the comment reports itself.
_UNREADABLE_KEY_COMMENT = """# spine

```yaml
repo:
  name: sample
branches:   # the shared ones
  integration: commented-lane
  release: commented-main
```
"""

#: Every spelling the parsers refuse, keyed by the shape that makes it
#: unreadable. The notice is what the refusal costs, so each one is driven
#: through the same assertions rather than trusted to the comment that names it.
_UNREADABLE_FIXTURES = {
    "sequence-block": _UNREADABLE,
    "flow-sequence": _UNREADABLE_INLINE,
    "nested-flow": _UNREADABLE_NESTED_FLOW,
    "multiline-flow": _UNREADABLE_MULTILINE_FLOW,
    "plain-scalar": _UNREADABLE_SCALAR,
    "key-comment-block": _UNREADABLE_KEY_COMMENT,
}

#: A spine with no ``branches:`` key at all: the ordinary un-adopted repo. The
#: control. A hook that chattered here would emit noise on every tool call in
#: every repository that never adopted the guidance.
_NO_BRANCHES = """# spine

```yaml
repo:
  name: sample
tracker: github
paths:
  tests: tests/
```
"""

#: A spine whose declaration is written in the flow form this change teaches the
#: scanners to read. The second control, and the derivation pin: the key is
#: present, so a notice fired on *the key* rather than on *what the scan
#: produced* fails here. Its values are names no ``FALLBACK_PROTECTED`` entry
#: carries, so a scanner that still read nothing from it would fall back — and
#: fall back is precisely the state the notice reports.
_READABLE_FLOW = """# spine

```yaml
branches: {integration: quiet-lane, release: hush-lane}
```
"""

#: The third control, and the one that pins the detector's **anchor**. The
#: detector is deliberately wider than either parser arm, and the failure mode of
#: a wide detector is firing on text that is not a declaration at all: a spine
#: whose prose happens to name the key mid-sentence, which every document
#: describing this guidance does. Dropping the ``^`` from the detector is a
#: mutation that survived the corpus this module shipped with — it turns an
#: ordinary sentence into an unreadable declaration and reports one on every hook
#: firing in the repository.
_PROSE_MENTION = """# spine

The branches: named in this sentence are prose, not a declaration, and the
guidance this repository follows discusses branches: constantly.

```yaml
repo:
  name: sample
tracker: github
```
"""

#: A ``CONTEXT.md`` that declares readable branch names, for the repository shape
#: where the spine's declaration is unreadable and the pre-v5 file behind it is
#: not. ``ctx-lane`` is a name no ``FALLBACK_PROTECTED`` entry carries (floored in
#: :func:`test_the_notice_does_not_claim_a_fallback_that_is_not_in_force`), so a
#: guard that protects it is one reading this file rather than falling back.
_READABLE_CONTEXT = """# CONTEXT.md

```yaml
branches:
  integration: ctx-lane
```
"""


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


def _repo(tmp_path: Path, *, spine: str | None = None, context: str | None = None) -> Path:
    """A committed repository carrying ``CLAUDE.md`` and/or ``CONTEXT.md``."""
    root = tmp_path / "repo"
    root.mkdir(parents=True)
    _git(root, "init", "-q", "--initial-branch=dev")
    _git(root, "config", "user.email", "t@example.com")
    _git(root, "config", "user.name", "t")
    if spine is not None:
        (root / "CLAUDE.md").write_text(spine)
    if context is not None:
        (root / "CONTEXT.md").write_text(context)
    (root / "a.txt").write_text("one\n")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "first")
    return root


def _run_parse(hook: str, repo: Path, *, times: int = 1) -> subprocess.CompletedProcess[str]:
    """Resolve ``hook``'s protected set in ``repo``, ``times`` times in one process.

    Executes the shipped module: ``require()``ing a hook does not run it, so this
    reads the real implementation rather than a restatement of it.
    """
    script = "const h = require(process.env.HOOK_PATH);" + _DRIVE[hook] * times
    proc = subprocess.run(
        [_node(), "-e", script],
        cwd=repo,
        capture_output=True,
        text=True,
        timeout=60,
        env={**os.environ, "HOOK_PATH": str(_HOOKS_DIR / hook)},
    )
    assert proc.returncode == 0, (
        f"{hook} could not resolve a protected set (rc={proc.returncode}): {proc.stderr.strip()}"
    )
    return proc


def _fallback() -> set[str]:
    """``FALLBACK_PROTECTED``, read off the shipped module."""
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
    return {name for name in proc.stdout.strip().split(",") if name}


def _tag(hook: str) -> str:
    """The notice tag for ``hook``, derived from its filename exactly as the hook
    derives its own ``TAG`` — so the two cannot drift apart silently."""
    return f"[{Path(hook).stem.upper()}]"


# --- the notice fires and names the file --------------------------------------


@pytest.mark.parametrize("spelling", sorted(_UNREADABLE_FIXTURES))
@pytest.mark.parametrize("hook", _HOOKS)
def test_an_unreadable_declaration_is_named_on_stderr(
    hook: str, spelling: str, tmp_path: Path
) -> None:
    """AC-2 — the fallback stops being indistinguishable from a real parse.

    The spine here declares ``branches:`` and yields nothing, so the hook is
    about to protect ``FALLBACK_PROTECTED`` while the repository believes its
    own declaration is in force. One line on stderr is what makes that state
    visible from any guarded push instead of from an incident.

    Both unreadable spellings run: the sequence body under a bare key, and the
    flow sequence on the key's own line. Only the second one can fail if the
    detector degrades to the block arm's own entry test, which is the degradation
    that would quietly re-create #487 for every spelling nobody anticipated.
    """
    repo = _repo(tmp_path, spine=_UNREADABLE_FIXTURES[spelling])
    proc = _run_parse(hook, repo)

    assert _TOKEN in proc.stderr, (
        f"{hook} said nothing about a CLAUDE.md whose branches: key parsed to nothing. "
        f"It is now silently protecting the fallback set instead (#487). Got: {proc.stderr!r}"
    )
    assert _tag(hook) in proc.stderr, (
        f"{hook}'s notice does not name the hook that wrote it, so an operator "
        f"reading a session transcript cannot tell which guard degraded: {proc.stderr!r}"
    )
    assert str(repo / "CLAUDE.md") in proc.stderr, (
        f"{hook}'s notice does not name the file it could not read, which is the "
        f"one fact needed to fix it: {proc.stderr!r}"
    )
    assert len([line for line in proc.stderr.splitlines() if line.strip()]) == 1, (
        f"{hook} wrote more than one line for a single unreadable declaration: {proc.stderr!r}"
    )


@pytest.mark.parametrize("hook", _HOOKS)
def test_the_notice_names_the_file_it_actually_read(hook: str, tmp_path: Path) -> None:
    """The derivation pin on the filename.

    A notice that hardcoded ``CLAUDE.md`` would satisfy the test above forever.
    Here the spine is **absent** and the unreadable declaration is in
    ``CONTEXT.md``, the pre-v5 fallback both hooks still consult, so the correct
    answer differs from the one the tree usually produces.
    """
    repo = _repo(tmp_path, context=_UNREADABLE)
    proc = _run_parse(hook, repo)

    assert str(repo / "CONTEXT.md") in proc.stderr, (
        f"{hook} did not name CONTEXT.md as the file whose declaration it could "
        f"not read: {proc.stderr!r}"
    )
    assert "CLAUDE.md" not in proc.stderr, (
        f"{hook} named a spine this repository does not have, so the notice is "
        f"reporting a constant rather than the file it read: {proc.stderr!r}"
    )


# --- the controls: silence where silence is correct ---------------------------


@pytest.mark.parametrize("hook", _HOOKS)
def test_a_spine_without_a_branches_key_is_silent(hook: str, tmp_path: Path) -> None:
    """The control without which "always chatters" would pass.

    A repository that never adopted the guidance has no declaration to be
    unreadable, and the conservative fallback applying there is the design, not a
    degradation. ``test_hooks_fail_open_is_loud`` asserts empty stderr on valid
    input for every hook; this is the same bound, stated where the notice lives.
    """
    repo = _repo(tmp_path, spine=_NO_BRANCHES)
    proc = _run_parse(hook, repo)

    assert not proc.stderr.strip(), (
        f"{hook} reported an unreadable declaration for a spine that declares no "
        f"branches at all. That is every un-adopted repository, on every tool "
        f"call: {proc.stderr!r}"
    )


@pytest.mark.parametrize("hook", _HOOKS)
def test_a_readable_declaration_is_silent(hook: str, tmp_path: Path) -> None:
    """The second control, and the derivation pin on the predicate.

    The ``branches:`` key is present here and the scan succeeds, so a notice
    keyed on *the key being there* rather than on *the scan producing nothing*
    fires and fails. The fixture is the flow spelling on purpose: it is the one
    this change teaches the scanners to read, so this also fails if the parser
    arm regresses — the notice would then be correct and still unwanted.
    """
    repo = _repo(tmp_path, spine=_READABLE_FLOW)
    proc = _run_parse(hook, repo)

    assert not proc.stderr.strip(), (
        f"{hook} reported an unreadable declaration for a spine it parsed "
        f"successfully: {proc.stderr!r}"
    )


@pytest.mark.parametrize("hook", _HOOKS)
def test_prose_that_mentions_the_key_is_not_a_declaration(hook: str, tmp_path: Path) -> None:
    """The anchor control.

    The detector has to be wider than the parsers — that is what keeps the next
    unanticipated spelling from being silent — and *wider* is one edit away from
    *unanchored*. This spine mentions the key twice in a sentence and declares
    nothing, which is the shape of every document that describes this guidance,
    including the spine of the repository shipping the hook. An unanchored
    detector reports an unreadable declaration here, on a file that has none.
    """
    repo = _repo(tmp_path, spine=_PROSE_MENTION)
    proc = _run_parse(hook, repo)

    assert not proc.stderr.strip(), (
        f"{hook} read a mid-sentence mention of the key as a declaration it could "
        f"not parse, so ordinary prose now produces a notice: {proc.stderr!r}"
    )


# --- once per file per process ------------------------------------------------


@pytest.mark.parametrize("hook", _HOOKS)
def test_the_notice_is_written_once_per_process(hook: str, tmp_path: Path) -> None:
    """Two resolutions in one process, one notice.

    ``gate-evidence-guard`` resolves a declaration at two call sites on an
    ordinary Stop (``declaredConfig(sessionTop)`` and ``declaredConfig(top)``),
    and a stderr line repeated per call is how a diagnostic becomes noise. The
    floor is the single-call count measured in the same test rather than a
    constant: without it, a notice that stopped firing altogether would satisfy
    ``<= 1``.
    """
    repo = _repo(tmp_path, spine=_UNREADABLE)

    once = _run_parse(hook, repo, times=1).stderr.count(_TOKEN)
    twice = _run_parse(hook, repo, times=2).stderr.count(_TOKEN)

    assert once == 1, (
        f"{hook} wrote {once} notices for one resolution of an unreadable "
        "declaration, so the comparison below measures nothing"
    )
    assert twice == 1, (
        f"{hook} wrote {twice} notices when its declaration was resolved twice in "
        "one process. Both hooks read the spine more than once per invocation, so "
        "a per-call notice repeats on every hook firing."
    )


def test_two_unreadable_files_are_both_named(tmp_path: Path) -> None:
    """Once per **file**, not once per process.

    ``gate-evidence-guard`` resolves its declaration through ``declaredConfig``,
    which reads the spine and then ``CONTEXT.md`` behind it, so a repository
    part-way through the v5 migration can present two unreadable declarations in
    one process. Deduplicating on anything but the filename silences the second —
    a mutation that survived the corpus this module shipped with — and the file
    that goes unreported is the one still in force.

    The single-file count is measured in the same run as the floor, so a notice
    that stopped firing altogether cannot satisfy the comparison.
    """
    one = _repo(tmp_path / "one", spine=_UNREADABLE)
    both = _repo(tmp_path / "both", spine=_UNREADABLE, context=_UNREADABLE)

    from_one = _run_parse(_STOP_HOOK, one).stderr
    from_both = _run_parse(_STOP_HOOK, both).stderr

    assert from_one.count(_TOKEN) == 1, (
        f"one unreadable file produced {from_one.count(_TOKEN)} notices, so the "
        "comparison below measures nothing"
    )
    assert from_both.count(_TOKEN) == 2, (
        f"two unreadable declarations in one process produced "
        f"{from_both.count(_TOKEN)} notices: {from_both!r}"
    )
    for name in ("CLAUDE.md", "CONTEXT.md"):
        assert str(both / name) in from_both, (
            f"{name} was not named, so an operator fixing the reported file would "
            f"still be running on an unreadable declaration: {from_both!r}"
        )


# --- the contract around the notice is unchanged ------------------------------


def test_the_blocking_contract_is_unchanged_while_the_notice_fires(tmp_path: Path) -> None:
    """End to end on the production path: the notice is additive.

    The real ``push-target-guard`` binary, a real ``git push`` payload, an
    unreadable spine and no gate marker. The hook must still exit 0, still write
    its decision to stdout, and still deny — the notice rides alongside on
    stderr. A fix that turned an unreadable declaration into a crash, or into a
    changed decision, fails here rather than in production.

    ``dev`` is a ``FALLBACK_PROTECTED`` name, which is the point: the fallback is
    exactly what is in force when the declaration cannot be read, and the deny it
    produces is the behaviour that must survive the notice.
    """
    repo = _repo(tmp_path, spine=_UNREADABLE)
    payload = {
        "tool_name": "Bash",
        "cwd": str(repo),
        "tool_input": {"command": "git push origin dev"},
    }
    proc = subprocess.run(
        [_node(), str(_HOOKS_DIR / _PUSH_HOOK)],
        input=json.dumps(payload),
        cwd=repo,
        capture_output=True,
        text=True,
        timeout=60,
        env={**os.environ},
    )

    assert proc.returncode == 0, f"the hook exited {proc.returncode}: {proc.stderr!r}"
    assert proc.stdout.strip(), f"the hook wrote no decision at all: {proc.stderr!r}"
    output = json.loads(proc.stdout).get("hookSpecificOutput", {})
    assert output.get("permissionDecision") == "deny", (
        "a push to a fallback-protected branch with no gate marker was not "
        f"refused: {output!r}"
    )
    assert _TOKEN in proc.stderr, (
        "the end-to-end path never reported the unreadable declaration, so the "
        f"notice is only reachable from the helper calls above: {proc.stderr!r}"
    )


def test_the_notice_does_not_claim_a_fallback_that_is_not_in_force(tmp_path: Path) -> None:
    """What the notice may claim is bounded by what the hook then does.

    A repository can carry an unreadable declaration in its spine and a readable
    one in the ``CONTEXT.md`` behind it — the shape of a repo part-way through the
    v5 migration. The parse of the spine yields nothing, so the notice fires; but
    the conservative fallback is **not** what protects the branches afterwards,
    ``CONTEXT.md``'s declaration is. A notice asserting the fallback is in force
    is therefore false exactly where an operator would act on it, and it is the
    kind of false sentence a later reader builds an argument on
    (``craft.md`` → *A comment asserting an unmeasured precondition*).

    Measured end to end on the production path rather than through a helper
    composition: ``ctx-lane`` is denied, and it is denied because the declaration
    this file could still read names it. The floor is the fallback set itself —
    if ``ctx-lane`` ever joined it, the deny below would prove nothing.
    """
    fallback = _fallback()
    assert fallback, "the fallback set derived to nothing, so the floor below is vacuous"
    assert "ctx-lane" not in fallback, (
        f"`ctx-lane` is now a FALLBACK_PROTECTED name ({sorted(fallback)}), so a deny "
        "on it no longer distinguishes CONTEXT.md's declaration from the fallback"
    )

    repo = _repo(tmp_path, spine=_UNREADABLE, context=_READABLE_CONTEXT)
    payload = {
        "tool_name": "Bash",
        "cwd": str(repo),
        "tool_input": {"command": "git push origin ctx-lane"},
    }
    proc = subprocess.run(
        [_node(), str(_HOOKS_DIR / _PUSH_HOOK)],
        input=json.dumps(payload),
        cwd=repo,
        capture_output=True,
        text=True,
        timeout=60,
        env={**os.environ},
    )

    assert proc.returncode == 0, f"the hook exited {proc.returncode}: {proc.stderr!r}"
    output = json.loads(proc.stdout).get("hookSpecificOutput", {})
    assert output.get("permissionDecision") == "deny", (
        "a push to a branch CONTEXT.md declares was not refused, so this test is no "
        f"longer measuring a repository whose fallback is out of force: {output!r}"
    )
    assert _TOKEN in proc.stderr, (
        f"the unreadable spine went unreported: {proc.stderr!r}"
    )
    assert "conservative" not in proc.stderr.lower(), (
        "the notice claims the conservative fallback set is in force while the deny "
        f"above proves CONTEXT.md's declaration is what protected the branch: {proc.stderr!r}"
    )
