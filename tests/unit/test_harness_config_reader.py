"""#537 AC-2 — one reader serves both hooks and the marker helper.

Until this ticket the repo carried **three** hand-rolled readers of the same
subject: ``declaredBranches`` in ``hooks/push-target-guard.js`` and again in
``hooks/gate-evidence-guard.js``, and the ``commands.verify`` reader in
``scripts/gate-marker.js``. #487, #488 and #510 are all bugs in one of the three
that the other two either shared or were spared by accident.

#436 declined a shared ``hooks/lib/`` for two stated reasons, and this module
holds both of them rather than overturning them silently:

* ``test_hooks_fail_open_is_loud`` and ``test_hooks_module_type`` scan
  ``hooks/*.js`` **non-recursively**, so a subdirectory would be a hole in those
  guards. The shared reader is therefore at ``scripts/harness-config.js``, beside
  the marker helper that must also reach it, and those two scans keep their
  meaning unchanged.
* *"A shared module's own load failure would disarm both enforcement hooks
  together."* That is the risk :func:`test_an_unloadable_reader_leaves_both_hooks_protecting`
  measures directly, by making the module unloadable and asserting each hook
  still derives the conservative fallback set — the same state a repo that never
  adopted the guidance is in every day.

**The RED this module was written on.** The two hook parsers cut a value at the
first ``#`` anywhere in it (``raw.indexOf("#")``). YAML opens a comment at ``#``
only when whitespace precedes it, so ``integration: dev#1`` declares a branch
named ``dev#1`` and the old parsers read ``dev``. The consequence is not
cosmetic: the push guard would not recognise ``dev#1`` as protected, so an
unreviewed push to the repo's own integration branch would be approved. The
marker helper's reader already got this right (#510); the fix is that there is
now one reader and it is that one.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
READER = REPO_ROOT / "scripts" / "harness-config.js"
HOOKS = REPO_ROOT / "hooks"

#: The hooks that resolve a protected branch set, and the expression that yields
#: it. Both shapes are kept — one returns names, one returns a map — because the
#: shapes are each hook's own business; what must agree is the set.
#: The **protected set** each hook derives, which is the thing that decides
#: whether a push is refused. Never the parse result: a hook whose reader returns
#: nothing still protects the fallback, and that difference is the whole subject
#: of :func:`test_an_unloadable_reader_leaves_both_hooks_protecting`. The two
#: expressions differ because the hooks compose their own steps differently; what
#: must agree is the set.
PROTECTED = {
    "push-target-guard.js": "[...h.protectedBranches(process.cwd())].join('\\n')",
    "gate-evidence-guard.js": (
        "[...h.protectedBranches(h.declaredConfig(process.cwd()), process.cwd())].join('\\n')"
    ),
}


def _node() -> str:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node not available")
    return node


def _run_node(script: str, cwd: Path, env: dict[str, str] | None = None):
    return subprocess.run(
        [_node(), "-e", script],
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=60,
        env={**os.environ, **(env or {})},
    )


def _repo(tmp_path: Path, name: str, config: str, filename: str = "harness.yaml") -> Path:
    root = tmp_path / name
    root.mkdir(parents=True)
    subprocess.run(["git", "init", "-q", "--initial-branch=dev"], cwd=root, check=True)
    # ``newline=""`` disables newline translation, so a CRLF fixture really
    # carries CRLF on every host. :func:`test_the_crlf_fixture_really_carries_crlf`
    # measures that rather than trusting it.
    (root / filename).write_text(config, newline="")
    return root


# --- The three legal spellings of ``branches:`` -------------------------------
#
# Every one of these is valid YAML a real loader reads identically, and each was
# a live bug at some point: the flow mapping parsed as nothing (#487), and a
# comma inside a quoted value cut the value in half (#488).

BLOCK = "branches:\n  integration: dev\n  release: main\n"
FLOW = "branches: {integration: dev, release: main}\n"
QUOTED = 'branches:\n  integration: "dev"\n  release: \x27main\x27\n'

SPELLINGS = {"block": BLOCK, "flow": FLOW, "quoted": QUOTED}


@pytest.mark.parametrize("spelling", sorted(SPELLINGS))
def test_the_three_legal_spellings_parse_identically(tmp_path: Path, spelling: str) -> None:
    """AC-2. One reader, one answer, whichever legal spelling declares it."""
    repo = _repo(tmp_path, spelling, SPELLINGS[spelling])
    proc = _run_node(
        "const c = require(process.env.READER);"
        "process.stdout.write(JSON.stringify(c.declaredBranches(process.cwd())));",
        repo,
        {"READER": str(READER)},
    )
    assert proc.returncode == 0, proc.stderr
    assert json.loads(proc.stdout) == {"integration": "dev", "release": "main"}


def test_a_hash_without_leading_whitespace_is_part_of_the_branch_name(tmp_path: Path) -> None:
    """The RED. ``dev#1`` is a branch name; the old hook parsers read ``dev``.

    A branch the parser mis-reads is a branch the push guard does not protect,
    so this is an unreviewed push to the integration branch, not a typo.
    """
    repo = _repo(tmp_path, "hash", "branches:\n  integration: dev#1\n")
    proc = _run_node(
        "const c = require(process.env.READER);"
        "process.stdout.write(c.declaredBranches(process.cwd()).integration || '');",
        repo,
        {"READER": str(READER)},
    )
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout == "dev#1"


def test_a_hash_after_whitespace_still_opens_a_comment(tmp_path: Path) -> None:
    """The other side of the same predicate — without it, a reader that never
    cut a comment at all would pass the test above."""
    repo = _repo(tmp_path, "comment", "branches:\n  integration: dev # the shared one\n")
    proc = _run_node(
        "const c = require(process.env.READER);"
        "process.stdout.write(c.declaredBranches(process.cwd()).integration || '');",
        repo,
        {"READER": str(READER)},
    )
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout == "dev"


def test_the_crlf_fixture_really_carries_crlf(tmp_path: Path) -> None:
    """#488 reached production because every fixture was LF. This asserts the
    bytes before the parse asserts the behaviour."""
    repo = _repo(tmp_path, "crlf", BLOCK.replace("\n", "\r\n"))
    assert b"\r\n" in (repo / "harness.yaml").read_bytes()
    proc = _run_node(
        "const c = require(process.env.READER);"
        "process.stdout.write(JSON.stringify(c.declaredBranches(process.cwd())));",
        repo,
        {"READER": str(READER)},
    )
    assert proc.returncode == 0, proc.stderr
    assert json.loads(proc.stdout) == {"integration": "dev", "release": "main"}


# --- The sources the one reader reads, in order -------------------------------


@pytest.mark.parametrize("filename", ["harness.yaml", "AGENTS.md", "CLAUDE.md", "CONTEXT.md"])
def test_every_declared_source_is_read(tmp_path: Path, filename: str) -> None:
    """calibrate and nano-erp have not migrated: their config is still a fenced
    block in ``CLAUDE.md``, and their hooks must keep working on the day this
    lands. One reader over several sources is still one reader."""
    body = BLOCK if filename == "harness.yaml" else f"# Spine\n\n```yaml\n{BLOCK}```\n"
    repo = _repo(tmp_path, filename.replace(".", "-"), body, filename=filename)
    proc = _run_node(
        "const c = require(process.env.READER);"
        "process.stdout.write(JSON.stringify(c.declaredBranches(process.cwd())));",
        repo,
        {"READER": str(READER)},
    )
    assert proc.returncode == 0, proc.stderr
    assert json.loads(proc.stdout) == {"integration": "dev", "release": "main"}


def test_harness_yaml_wins_over_a_stale_fenced_block(tmp_path: Path) -> None:
    """A migrated repo keeps its prose spine. If the stale fenced block could
    still win, the migration would be a no-op nobody noticed."""
    repo = _repo(tmp_path, "precedence", "branches:\n  integration: from-yaml\n")
    (repo / "CLAUDE.md").write_text("```yaml\nbranches:\n  integration: from-markdown\n```\n")
    proc = _run_node(
        "const c = require(process.env.READER);"
        "process.stdout.write(c.declaredBranches(process.cwd()).integration || '');",
        repo,
        {"READER": str(READER)},
    )
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout == "from-yaml"


# --- #436's objection, held ---------------------------------------------------


@pytest.mark.parametrize("hook", sorted(PROTECTED))
def test_an_unloadable_reader_leaves_both_hooks_protecting(tmp_path: Path, hook: str) -> None:
    """#436's second reason for declining a shared module, measured.

    The module is made unloadable by pointing the hooks' resolution at a
    directory that has no ``harness-config.js`` in it. A hook that crashed here
    would wedge every ``Bash`` call in the session; a hook that fell open to an
    *empty* protected set would approve a push to ``dev``. Neither is acceptable,
    so the required behaviour is the third one: degrade to the conservative
    fallback, which is exactly the state an unadopted repo is in.
    """
    repo = _repo(tmp_path, f"noreader-{hook}", BLOCK)
    # The hook resolves the reader as ``../scripts/harness-config.js`` from its
    # own directory, and that path has **no override** — an environment variable
    # naming it would itself be a way to leave the guard protecting nothing. So
    # the module is made unloadable the only way production could suffer it: the
    # hook is copied somewhere with no sibling ``scripts/``, which is what a
    # half-materialized install looks like.
    stage = tmp_path / "stage" / "hooks"
    stage.mkdir(parents=True)
    shutil.copy(HOOKS / hook, stage / hook)
    for sibling in HOOKS.glob("*.js"):
        shutil.copy(sibling, stage / sibling.name)
    shutil.copy(HOOKS / "package.json", stage / "package.json")
    assert not (tmp_path / "stage" / "scripts").exists()
    proc = _run_node(
        "const h = require(process.env.HOOK_PATH);"
        f"process.stdout.write(String({PROTECTED[hook]}));",
        repo,
        {"HOOK_PATH": str(stage / hook)},
    )
    assert proc.returncode == 0, f"the hook crashed instead of falling open: {proc.stderr}"
    derived = {name for name in proc.stdout.split("\n") if name}
    assert {"dev", "main"} <= derived, (
        f"an unloadable reader left {hook} protecting {derived or 'nothing'}"
    )
    assert "fail-open" in proc.stderr, "a hook that fell open must say so on stderr (#303)"


# --- The reader is the only reader --------------------------------------------

#: Tokens distinctive to a hand-rolled yaml reader. Spelled as tokens rather than
#: as a file list so a *fourth* parser added tomorrow reddens this without anyone
#: editing a list here — including one that copies the shape under a new name,
#: since the scalar-layer names travel with the shape.
PARSER_TOKENS = (
    "FLOW_PAIR",
    "INDICATOR",
    "withoutComment",
    "stripQuotes",
    "BRANCHES_FLOW",
    "COMMANDS_KEY",
)

#: Every module that could hold one. Both directories, non-recursively — the same
#: scan shape ``test_hooks_fail_open_is_loud`` uses, and the reason #537 put the
#: shared reader in ``scripts/`` rather than in a ``hooks/lib/`` those scans
#: cannot see.
def _js_modules() -> list[Path]:
    return sorted([*HOOKS.glob("*.js"), *(REPO_ROOT / "scripts").glob("*.js")])


@pytest.mark.parametrize("token", PARSER_TOKENS)
def test_no_module_but_the_shared_reader_carries_a_parser(token: str) -> None:
    """AC-2's real claim. Equivalence between two parsers was the #457 control,
    and it could not see #488 because both copies were wrong identically. One
    parser is what removes that class, so the guard is on the *count* of parsers,
    not on their agreement."""
    homes = sorted(
        path.relative_to(REPO_ROOT).as_posix()
        for path in _js_modules()
        if token in path.read_text()
    )
    assert set(homes) <= {"scripts/harness-config.js"}, f"{token} is also declared in {homes}"


def test_the_shared_reader_really_is_the_parser() -> None:
    """The anti-vacuity half. Without it, deleting the reader outright would turn
    every parametrisation above green."""
    text = (REPO_ROOT / "scripts" / "harness-config.js").read_text()
    owned = ("FLOW_PAIR", "INDICATOR", "withoutComment")
    missing = [token for token in owned if token not in text]
    assert not missing, f"the shared reader carries no {missing}"


def test_no_environment_variable_can_redirect_the_reader() -> None:
    """ADR 0018's boundary, extended to the module that now does the reading.

    A variable naming the directory the reader is loaded from is a
    *per-invocation* source for both the gate command and the protected branch
    set: one export supplies a module returning any command, or a protected set
    of ``{integration: "nothing"}``, with no write to the tree and no trace in
    it. Rewriting the checked-in reader is the same local trust domain as
    rewriting ``verify.sh``; setting a variable is not.

    An earlier draft of this ticket shipped exactly that variable, to make the
    test above possible. The test was rewritten to copy the hook instead.
    """
    for module in [*HOOKS.glob("*.js"), *(REPO_ROOT / "scripts").glob("*.js")]:
        text = module.read_text()
        for line in text.splitlines():
            if "harness-config.js" not in line and "harness-config" not in line:
                continue
            assert "process.env" not in line, (
                f"{module.name} resolves the shared reader through an environment "
                f"variable: {line.strip()}"
            )
