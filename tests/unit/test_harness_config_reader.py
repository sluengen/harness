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
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from tests._gitutil import indexed_text, tracked_files_under

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


@pytest.mark.parametrize(
    ("reader", "block", "expected"),
    [
        ("declaredLoop", "loop:\n  max_review_cycles: 3\n", {"max_review_cycles": "3"}),
        ("declaredCommands", 'commands:\n  verify: "bash x.sh"\n', {"verify": "bash x.sh"}),
        ("declaredPaths", "paths:\n  tests: tests/\n", {"tests": "tests/"}),
    ],
)
def test_every_map_the_criterion_names_is_readable(
    tmp_path: Path, reader: str, block: str, expected: dict
) -> None:
    """AC-2 names roles, commands **and** loop settings. `branches` has a caller
    today and these two do not — the review workflow that reads the loop numbers
    is T2's. Exercising them here is what keeps them from being unverified code
    waiting for a caller, which is how the fourth hand-rolled parser gets written."""
    repo = _repo(tmp_path, f"map-{reader}", block)
    proc = _run_node(
        f"const c = require(process.env.READER);"
        f"process.stdout.write(JSON.stringify(c.{reader}(process.cwd())));",
        repo,
        {"READER": str(READER)},
    )
    assert proc.returncode == 0, proc.stderr
    assert json.loads(proc.stdout) == expected


def test_a_declaration_outside_any_fence_is_reported_not_silently_skipped(
    tmp_path: Path,
) -> None:
    """The one case the fenced narrowing can hide.

    Markdown sources are read only inside ` ```yaml ` fences, because the three
    parsers this reader replaces scanned whole files and a prose example could
    decide the protected set. The cost of that narrowing is a spine declaring
    ``branches:`` outside a fence: the extraction is empty, so the caller falls
    back — and without this, with nothing on stderr. That silence is the #487
    harm the unreadable notice exists to prevent, so the narrowing has to be
    audible. The declaration is *noticed*, never parsed.
    """
    repo = _repo(tmp_path, "unfenced", "# Spine\n\nbranches:\n  integration: trunk\n",
                 filename="CLAUDE.md")
    proc = _run_node(
        "const c = require(process.env.READER);"
        "const r = c.declaredBranches(process.cwd(), (f) => process.stderr.write('NOTICE ' + f));"
        "process.stdout.write(JSON.stringify(r));",
        repo,
        {"READER": str(READER)},
    )
    assert proc.returncode == 0, proc.stderr
    assert json.loads(proc.stdout) == {}, "an unfenced declaration must not be parsed"
    assert "NOTICE" in proc.stderr, (
        "an unfenced declaration fell back to the conservative set silently — "
        "indistinguishable from a repo that declares nothing"
    )


def test_a_source_that_declares_nothing_is_not_reported(tmp_path: Path) -> None:
    """The other side of the same predicate. Without it, a reader that reported
    every source would pass the test above while making every unadopted repo
    chatter on every tool call."""
    repo = _repo(tmp_path, "quiet", "# Spine\n\nNo configuration here.\n", filename="CLAUDE.md")
    proc = _run_node(
        "const c = require(process.env.READER);"
        "c.declaredBranches(process.cwd(), (f) => process.stderr.write('NOTICE ' + f));",
        repo,
        {"READER": str(READER)},
    )
    assert proc.returncode == 0, proc.stderr
    assert "NOTICE" not in proc.stderr, "an honest absence must stay silent"


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
def _js_modules() -> list[str]:
    """The tracked modules, by repo-relative path.

    Read through the index rather than the working tree, which is what
    `.claude/rules/scripts.md` requires of a guard: a guard over the working tree
    passes on bytes that are not the bytes that ship.
    """
    return sorted(
        path.relative_to(REPO_ROOT).as_posix()
        for path in tracked_files_under("hooks") | tracked_files_under("scripts")
        if path.suffix == ".js"
    )


@pytest.mark.parametrize("token", PARSER_TOKENS)
def test_no_module_but_the_shared_reader_carries_a_parser(token: str) -> None:
    """AC-2's real claim. Equivalence between two parsers was the #457 control,
    and it could not see #488 because both copies were wrong identically. One
    parser is what removes that class, so the guard is on the *count* of parsers,
    not on their agreement."""
    homes = sorted(
        name for name in _js_modules() if token in indexed_text(name)
    )
    assert set(homes) <= {"scripts/harness-config.js"}, f"{token} is also declared in {homes}"


def test_the_shared_reader_really_is_the_parser() -> None:
    """The anti-vacuity half. Without it, deleting the reader outright would turn
    every parametrisation above green."""
    text = indexed_text("scripts/harness-config.js")
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
    require_call = re.compile(r"require\s*\(([^)]*)\)")
    for name in _js_modules():
        text = indexed_text(name)
        for expression in require_call.findall(text):
            # Every ``require`` whose expression is not a plain Node builtin or a
            # literal. Filtering on "harness-config" first was the narrower bug
            # one step along: ``require(process.env.HARNESS_READER)`` names the
            # module nowhere, so it was skipped before the walk could see it.
            if re.fullmatch(r'\s*"node:[a-z_]+"\s*|\s*"[a-z_]+"\s*', expression):
                continue
            if expression.strip().startswith('"./') and "harness-config" not in expression:
                continue
            # The expression itself, and every identifier feeding it. A guard that
            # only read the `require` line passed a two-line resolution —
            # `const dir = process.env.X;` then `require(path.join(dir, …))` —
            # because neither line carried both tokens. The subject is the
            # syntactic position a per-invocation value can occupy, not one line.
            operands = set(re.findall(r"[A-Za-z_$][\w$]*", expression))
            reachable = expression
            for line in text.splitlines():
                declared = re.match(r"\s*(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=(.*)$", line)
                if declared and declared.group(1) in operands:
                    reachable += "\n" + declared.group(2)
            assert "process.env" not in reachable and "argv" not in reachable, (
                f"{name} resolves the shared reader through a per-invocation value: "
                f"{expression.strip()}"
            )


# --- #588: the `queue:` block, the one home for the WIP limit -----------------
#
# The limit is the amendment's only mechanical control (spine P0 / P3): a queue
# with no cap converts every finding into a commitment. The numbers live in
# `harness.yaml` and nowhere else, so the reader that already serves the hooks
# and the marker helper serves them too rather than growing a fifth parser.

QUEUE_DEFAULTS = {"wip_limit": 6, "active_projects": 3, "project_field": "none", "projects": {}}


def _queue(tmp_path: Path, name: str, config: str) -> dict:
    """`queueSettings` over a scratch repo declaring ``config``."""
    repo = _repo(tmp_path, name, config)
    proc = _run_node(
        "const c = require(process.env.READER);"
        "process.stdout.write(JSON.stringify(c.queueSettings(process.cwd())));",
        repo,
        {"READER": str(READER)},
    )
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


def test_the_queue_keys_default_when_the_block_is_absent(tmp_path: Path) -> None:
    """AC-2, first half. A repo that declares no `queue:` still has a limit.

    The defaults are the amendment's starting values (six, three), and
    ``project_field`` defaults to ``none`` — the repo is its own single queue —
    because a reader that guessed ``milestone`` would have every filing consult a
    field the repo never declared.
    """
    assert _queue(tmp_path, "queue-absent", "branches:\n  integration: dev\n") == QUEUE_DEFAULTS


def test_declared_queue_values_are_returned_as_numbers(tmp_path: Path) -> None:
    """A declared block wins over every default, and the two counts are integers.

    Strings would compare lexically at every call site — ``"10" < "6"`` — which
    is the whole failure mode of returning a raw map for a value that bounds a
    count.
    """
    declared = _queue(
        tmp_path,
        "queue-declared",
        "queue:\n  wip_limit: 10\n  active_projects: 1\n  project_field: milestone\n",
    )
    assert declared == {
        "wip_limit": 10,
        "active_projects": 1,
        "project_field": "milestone",
        "projects": {},
    }


def test_a_per_project_override_is_read(tmp_path: Path) -> None:
    """AC-2, second half. Some initiatives carry their own loop and pace.

    The override is one **flat** key spelling the path the spine names, because
    :func:`blockMap` reads a flat mapping by design: a genuinely nested block is
    refused whole rather than half-read, which is
    :func:`test_a_nested_projects_block_is_refused_rather_than_half_read`.
    """
    declared = _queue(
        tmp_path,
        "queue-override",
        "queue:\n  wip_limit: 6\n  projects.lifecycle-reset.wip_limit: 12\n",
    )
    assert declared["wip_limit"] == 6
    assert declared["projects"] == {"lifecycle-reset": {"wip_limit": 12}}


def test_a_nested_projects_block_is_refused_rather_than_half_read(tmp_path: Path) -> None:
    """A nested spelling yields the defaults, never a partial map.

    ``blockMap`` returns ``null`` for an indentation it cannot read, and the
    surrounding source is reported through ``onUnreadable``. The danger this pins
    is the other outcome: a half-read block that returned ``wip_limit`` and
    silently dropped the override, which reads as a repo declining an override it
    actually declared.
    """
    config = (
        "queue:\n"
        "  wip_limit: 6\n"
        "  projects:\n"
        "    lifecycle-reset:\n"
        "      wip_limit: 12\n"
    )
    repo = _repo(tmp_path, "queue-nested", config)
    proc = _run_node(
        "const c = require(process.env.READER);"
        "const seen = [];"
        "const q = c.queueSettings(process.cwd(), (s) => seen.push(s));"
        "process.stdout.write(JSON.stringify({q, seen}));",
        repo,
        {"READER": str(READER)},
    )
    assert proc.returncode == 0, proc.stderr
    result = json.loads(proc.stdout)
    assert result["q"] == QUEUE_DEFAULTS
    assert [Path(s).name for s in result["seen"]] == ["harness.yaml"]


def test_a_value_that_is_not_a_positive_count_falls_back_to_the_default(tmp_path: Path) -> None:
    """A limit this reader cannot read as a positive integer is not a limit.

    Returning ``"six"`` or ``0`` would put an unusable bound in front of every
    caller; the default is the one value every caller already handles. The
    template declares both counts explicitly so a typo is visible in the diff.
    """
    declared = _queue(
        tmp_path, "queue-nonsense", "queue:\n  wip_limit: six\n  active_projects: 0\n"
    )
    assert declared["wip_limit"] == QUEUE_DEFAULTS["wip_limit"]
    assert declared["active_projects"] == QUEUE_DEFAULTS["active_projects"]


def _queue_with_notices(tmp_path: Path, name: str, config: str) -> tuple[dict, list[str]]:
    """`queueSettings` over a scratch repo, with the sources it could not read."""
    repo = _repo(tmp_path, name, config)
    proc = _run_node(
        "const c = require(process.env.READER);"
        "const seen = [];"
        "const q = c.queueSettings(process.cwd(), (s) => seen.push(s));"
        "process.stdout.write(JSON.stringify({q, seen}));",
        repo,
        {"READER": str(READER)},
    )
    assert proc.returncode == 0, proc.stderr
    result = json.loads(proc.stdout)
    return result["q"], [Path(s).name for s in result["seen"]]


def test_this_repo_declares_a_queue_block_the_one_reader_can_read(tmp_path: Path) -> None:
    """The tracked `harness.yaml` declares one queue, in a spelling that parses.

    Three assertions, and the third is what makes the first two mean anything.
    ``project_field: none`` is also the reader's *default*, so asserting the
    returned value alone would pass over a `harness.yaml` carrying no ``queue:``
    block at all — the born-green trap (``craft.md``). So the block's presence is
    asserted directly, its readability through the notice channel, and a
    **control** replaces it with the nested spelling this flat reader refuses:
    the control must report the source unreadable, or the empty notice list above
    is evidence of nothing.

    The per-project mechanics are for the product repos, whose initiatives file a
    dozen tickets at once; this repo's work arrives from feedback one initiative
    at a time, so it is its own single queue. Read from the **index**, so a
    working-tree edit cannot make it pass on the machine that wrote it (#482).
    """
    config = indexed_text(Path("harness.yaml"))
    assert config is not None, "harness.yaml is not tracked"
    assert "\nqueue:\n" in config, (
        "harness.yaml declares no top-level `queue:` block, so every bound this "
        "repo runs under is the reader's default and nothing records the choice"
    )

    declared, unreadable = _queue_with_notices(tmp_path, "queue-this-repo", config)
    assert declared["project_field"] == "none"
    assert unreadable == [], (
        f"the one reader could not read {unreadable} — this repo's own queue "
        "declaration is in a spelling that silently falls back to the defaults"
    )

    nested = config.replace(
        "\nqueue:\n", "\nqueue:\n  projects:\n    a:\n      wip_limit: 2\n", 1
    )
    _, control_unreadable = _queue_with_notices(tmp_path, "queue-control", nested)
    assert control_unreadable == ["harness.yaml"], (
        "the notice channel never fired on a block this reader cannot parse, so "
        "the empty notice list above proves nothing about the real declaration"
    )
