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
#:
#: **It is also the one fixture in this corpus that constrains how wide the block
#: arm's key test may be**, which is worth stating because it is not what a reader
#: would guess. #488 replaced that test with "the key's value, comment stripped,
#: is empty"; mutating it to *always* open a block was measured against all five
#: spellings here and only this one died. The other four survive because nothing
#: inside them parses either way — a sequence body and a scalar body yield no
#: pairs however the block was entered — whereas this fixture's indented
#: ``integration: wrapped-lane,`` does match, so an over-wide key test half-parses
#: it into ``wrapped-lane,`` (trailing comma and all) and the notice stops firing.
#: Deleting this fixture would leave #488 AC-5 with no fixture measuring it.
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

#: #506: accepted parser pairs surrounding an unsupported quoted key are still
#: one declaration.  The old scanners silently preserved the accepted pair and
#: discarded this key; this fixture proves the production notice/fallback path
#: now treats the whole declaration as unreadable instead.
_UNREADABLE_PARTIAL_FLOW = """# spine

```yaml
branches: {\"integration\": partial-flow-lane, release: partial-flow-main}
```
"""

_UNREADABLE_PARTIAL_BLOCK = """# spine

```yaml
branches:
  integration: partial-block-lane
  \"release\": partial-block-main
```
"""

#: **Formerly the sixth unreadable spelling; readable since #488.** A block
#: declaration whose key line carries an inline comment. The block arm used to
#: key on a bare ``branches:`` line, so the perfectly readable mapping below it
#: was skipped — and this repository's own spine writes inline comments on
#: sibling lines of the very block this parser reads, ``branches.release`` among
#: them, which is how close the spelling sat. #488 asks whether the key's
#: *value*, comment stripped, is empty,
#: and this fixture moved with the behaviour: it now sits in
#: :data:`_READABLE_FIXTURES` below, where the notice must **not** fire.
#:
#: The move is the point. The comment this fixture used to carry said it was
#: "where a later change that teaches the arm to tolerate the comment reports
#: itself" — so leaving it among the unreadable spellings after #488 would have
#: turned a pinned limitation into a false one.
_READABLE_KEY_COMMENT = """# spine

```yaml
repo:
  name: sample
branches:   # the shared ones
  integration: commented-lane
  release: commented-main
```
"""

#: #488 spelling 2, on the readable side: a comma inside a quoted flow value.
#: Unlike the other two this one never fired the notice — both parsers cut the
#: value in half *identically*, so the declaration looked readable and was not.
#: It belongs in this corpus because the notice must stay silent here after the
#: fix as well, and because a fix that made the arm bail on an unfamiliar value
#: rather than parse it would show up as a new notice.
_READABLE_QUOTED_COMMA = """# spine

```yaml
branches: {integration: 'also,comma', release: "has,comma", extra: plain-lane}
```
"""

#: #488 spelling 3, on the readable side: CRLF with an ordinary indented block.
#: Written as an explicit literal and asserted to reach disk with its endings
#: intact by :func:`test_the_crlf_fixture_really_carries_crlf` — a CRLF fixture
#: silently translated to LF would measure the ordinary block spelling and pass
#: on a tree where the defect is untouched.
_READABLE_CRLF = "\r\n".join(
    [
        "# spine",
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

#: Every spelling the parsers refuse, keyed by the shape that makes it
#: unreadable. The notice is what the refusal costs, so each one is driven
#: through the same assertions rather than trusted to the comment that names it.
_UNREADABLE_FIXTURES = {
    "sequence-block": _UNREADABLE,
    "flow-sequence": _UNREADABLE_INLINE,
    "nested-flow": _UNREADABLE_NESTED_FLOW,
    "multiline-flow": _UNREADABLE_MULTILINE_FLOW,
    "plain-scalar": _UNREADABLE_SCALAR,
    "partial-flow": _UNREADABLE_PARTIAL_FLOW,
    "partial-block": _UNREADABLE_PARTIAL_BLOCK,
}

#: The floor under the corpus above. #488 moved one spelling out of it, and a
#: later change that emptied it — or narrowed it to a single shape — would leave
#: every assertion parametrized over it constant-true while reading nothing
#: (``craft.md`` → *a sweep over a corpus needs a floor on the corpus*). Five is
#: the count after the move, and it is stated as a floor rather than an equality
#: so adding a newly-discovered unreadable spelling is not a test edit.
_MIN_UNREADABLE_SPELLINGS = 7

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
        # ``newline=""`` disables newline translation on write. Measured on a
        # POSIX host it changes nothing — ``os.linesep`` is ``\n`` there, so a
        # ``\r\n`` literal already survives the default — and a mutation removing
        # it is correctly reported inert. It is here for the platform where the
        # default *does* rewrite line endings, which is the same platform whose
        # clones produce the CRLF spine in the first place (#488 spelling 3).
        # What is actually measured, on every host, is the bytes that reached
        # disk: :func:`test_the_crlf_fixture_really_carries_crlf`.
        (root / "CLAUDE.md").write_text(spine, newline="")
    if context is not None:
        (root / "CONTEXT.md").write_text(context, newline="")
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


#: Every spelling the parsers **do** read, and where the notice must therefore
#: stay silent. ``flow-mapping`` is #487's; the other three are #488's, and the
#: reason they are here rather than in :data:`_UNREADABLE_FIXTURES` is the
#: behaviour change itself — AC-3 asks that the fix report itself where today's
#: behaviour is recorded, and this map is that record.
_READABLE_FIXTURES = {
    "flow-mapping": _READABLE_FLOW,
    "key-comment-block": _READABLE_KEY_COMMENT,
    "quoted-comma-flow": _READABLE_QUOTED_COMMA,
    "crlf-block": _READABLE_CRLF,
}


@pytest.mark.parametrize("spelling", sorted(_READABLE_FIXTURES))
@pytest.mark.parametrize("hook", _HOOKS)
def test_a_readable_declaration_is_silent(hook: str, spelling: str, tmp_path: Path) -> None:
    """#488 AC-1/AC-3 — the second control, and the derivation pin on the predicate.

    The ``branches:`` key is present in every fixture here and every scan
    succeeds, so a notice keyed on *the key being there* rather than on *the scan
    producing nothing* fires and fails.

    The corpus is the four spellings the scanners were taught to read: #487's
    flow mapping, and #488's key-line comment, quoted comma, and CRLF block. Each
    also fails here if its parser arm regresses — the notice would then be
    correct and still unwanted, which is the honest way round for a
    silence assertion to break.

    ``key-comment-block`` in particular used to live in
    :data:`_UNREADABLE_FIXTURES`, where it pinned the fallback. Its presence here
    is what makes #488 report itself at the place its behaviour was recorded.
    """
    repo = _repo(tmp_path, spine=_READABLE_FIXTURES[spelling])
    proc = _run_parse(hook, repo)

    assert not proc.stderr.strip(), (
        f"{hook} reported an unreadable declaration for the {spelling!r} spine, which it "
        f"parses successfully: {proc.stderr!r}"
    )


def test_the_two_corpora_are_disjoint_and_populated() -> None:
    """The floor under both sweeps, and the pin on #488's move.

    Two parametrized families above read these maps, and an assertion
    parametrized over an emptied map is constant-true while measuring nothing
    (``craft.md`` → *a sweep over a corpus needs a floor on the corpus*). Both
    directions are stated because a spelling that drifted into **both** maps
    would assert the notice must fire and must not fire, and pytest would report
    only whichever ran second.

    ``key-comment-block`` is named explicitly on the readable side: it is the one
    spelling #488 moved, and a revert that put it back among the unreadable
    fixtures is exactly the regression this module exists to catch.
    """
    assert len(_UNREADABLE_FIXTURES) >= _MIN_UNREADABLE_SPELLINGS, (
        f"the unreadable corpus holds {len(_UNREADABLE_FIXTURES)} spellings, below the "
        f"floor of {_MIN_UNREADABLE_SPELLINGS}. Every assertion parametrized over it is "
        "weaker than it was, and an empty corpus would make them all vacuous."
    )
    assert _READABLE_FIXTURES, "the readable corpus is empty, so the silence control is vacuous"
    overlap = set(_UNREADABLE_FIXTURES) & set(_READABLE_FIXTURES)
    assert not overlap, (
        f"{sorted(overlap)} is listed as both unreadable and readable, so this module "
        "asserts the notice must fire and must not fire for the same spine"
    )
    assert "key-comment-block" in _READABLE_FIXTURES, (
        "the key-line-comment spelling is no longer recorded as readable. #488 moved it "
        "out of the unreadable corpus because the block arm now tolerates the comment; "
        "if that behaviour was reverted, revert this module's claim with it."
    )


def test_the_crlf_fixture_really_carries_crlf(tmp_path: Path) -> None:
    """The floor under the CRLF fixture's own bytes.

    A CRLF fixture whose ``\r`` was translated away on write measures the
    ordinary block spelling, passes on a tree where the defect is untouched, and
    reads as coverage — the #466 identically-passed-renders shape. Python's
    default newline translation is exactly how that happens, so this measures the
    bytes the hook will read rather than the literal in this file.
    """
    assert "\r\n" in _READABLE_CRLF, "the CRLF literal carries no CRLF"
    repo = _repo(tmp_path, spine=_READABLE_CRLF)
    written = (repo / "CLAUDE.md").read_bytes()
    assert b"\r\n" in written, (
        "the CRLF fixture reached disk with its line endings translated, so the CRLF "
        "case is measuring the ordinary LF spelling"
    )
    assert b"\n" not in written.replace(b"\r\n", b""), (
        "the CRLF fixture reached disk with mixed line endings, so a parser could "
        "satisfy it by reading only the LF-terminated lines"
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


@pytest.mark.parametrize("spelling", ("sequence-block", "partial-flow", "partial-block"))
def test_the_blocking_contract_is_unchanged_while_the_notice_fires(
    spelling: str, tmp_path: Path
) -> None:
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
    repo = _repo(tmp_path, spine=_UNREADABLE_FIXTURES[spelling])
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
    # Anchored on the **claim**, not on one word of it. Until #537 this asserted
    # only that `conservative` was absent, so rewording the sentence to "using the
    # fallback set" satisfied it while saying the same false thing — the shape
    # `craft.md` calls a prose obligation anchored on a noun phrase, which reads
    # the same inverted. The claim is falsifiable in one direction: the notice may
    # not say that the fallback, by any of its names, is what is in force, because
    # the deny above proves it is not.
    fallback = _fallback_protected()
    assert fallback, "the fallback set could not be read, so this assertion is vacuous"
    said = proc.stderr.lower()
    claimed = [w for w in ("conservative", "fallback", "default") if w in said]
    assert not claimed, (
        f"the notice claims the {claimed} set is in force while the deny above proves "
        f"CONTEXT.md's declaration is what protected the branch: {proc.stderr!r}"
    )
    named = sorted(name for name in fallback if name in proc.stderr)
    assert not named, (
        f"the notice names {named} — members of the fallback set — while the branch "
        f"actually protected came from CONTEXT.md: {proc.stderr!r}"
    )


def _fallback_protected() -> set[str]:
    """``FALLBACK_PROTECTED`` as the shipped hook exports it.

    Read from the module rather than restated, so the assertion above is driven by
    the real set and a name added to it is covered without anyone editing a list.
    """
    proc = subprocess.run(
        [
            _node(),
            "-e",
            "process.stdout.write(require(process.env.HOOK).FALLBACK_PROTECTED.join(String.fromCharCode(10)))",
        ],
        capture_output=True,
        text=True,
        timeout=60,
        env={**os.environ, "HOOK": str(_HOOKS_DIR / "push-target-guard.js")},
    )
    assert proc.returncode == 0, proc.stderr
    return {name for name in proc.stdout.split("\n") if name}
