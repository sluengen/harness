"""#510 — where ``gate-marker.js`` gets the gate command, and what it may read.

Admission (ADR 0017 D5): class (a), both halves, by two different routes. The
corpus **executes** ``scripts/gate-marker.js``, calling the parser the runner
calls. The origin guard reads that program's own source to answer a question
about its control flow — the shape ``tests/unit/test_mutate.py`` already earns
for the one argv the mutation instrument may build, and admitted for the same
reason: the property is about executable code, and no execution can demonstrate
the *absence* of a path into it.

Two properties, one subject — the declaration that decides which command may
mint a marker.

**The parser.** ``declaredVerify`` is this tree's *third* hand-rolled reader of
the spine's yaml block, after the two in ``hooks/push-target-guard.js`` and
``hooks/gate-evidence-guard.js``. Repo law: a parser must accept every legal
spelling its subject already contains, and the subject's own file is the first
corpus (#484/#487). The sibling reader carries that scar twice over — #487 for
the flow mapping it read as nothing, #488 for the inline comment on the key
line, the comma inside a quoted value, and CRLF endings — and the comment beside
its block arm records that **this repository's own spine writes inline comments
on sibling lines of the very block being read**. Every one of those spellings is
in the corpus below, in the shape ``test_context_branch_parsing_contract.py``
uses: the two real spine files first as the floor, then one fixture per
spelling, each declaring a value that no other fixture and no fallback produces,
so "parsed correctly" can never be confused with "fell back" or "read the wrong
line".

Three spellings are refused **deliberately**, and the corpus pins the refusal
rather than the value, because a fragment executed as a command is worse than a
loud exit 3:

* a block or folded scalar (``verify: |``, ``verify: >``) — a line reader
  returns the indicator character itself, and ``sh -c ">"`` exits 2, the code
  this CLI reserves for a fact about the repository;
* a value that opens with a quote without being one whole enclosing quoted
  scalar — unterminated, or carrying content after its close. Measured at the
  third review cycle: ``verify: "printf outer" && "printf inner"`` has *even*
  quote parity, so no open-state check sees it, and stripping "one surrounding
  pair" left ``printf outer" && "printf inner``, which ``sh`` re-tokenised into
  a different command that **exited 0 and wrote a marker** for a tree whose
  declared gate never ran;
* the one-line flow mapping ``commands: {verify: …}`` — legal yaml the sibling
  *does* read for ``branches:``. ADR 0018 records it as deliberately unread
  here: a second flow parser earns nothing when the alternative is an explicit
  refusal, and the block spelling is what every hydrated spine writes.

**The origin.** AC-4 says no per-invocation source for the gate command exists.
The test this replaces set an environment variable that appears nowhere in the
tree and asserted the run still succeeded — an assertion no mutation could kill,
because no code reads that name. The property is not "this particular variable
is ignored"; it is that the string reaching ``spawnSync("sh", ["-c", …])``
comes from a file read and from nothing else. That is a question about the
source, and it is answered the way ``tests/unit/test_mutate.py`` answers the
same shape for its one permitted argv: derive the permitted shape from the
subject, then feed the predicate synthetic sources whose answers differ from
this tree's, so a shape matcher and a hardcoded pass are distinguishable (#458).

Which operand each half reads, because that decides the mutation instrument
(#490). The origin guard reads ``scripts/gate-marker.js`` as the **working
file**, so it stays inside ``scripts/mutate.py``'s reach; the two spine fixtures
at the top of the corpus read the **git index**, because the tree a marker
certifies is the staged one (#482), and they are provable only by a staged
probe. Everything else in the corpus is a literal in this module.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess

import pytest

from tests._gitutil import indexed_text
from tests.unit._prose import REPO_ROOT

HELPER = REPO_ROOT / "scripts" / "gate-marker.js"

#: What this repository's own spine declares. Hardcoded on purpose: it is the
#: string ``CLAUDE.md`` carries under ``commands.verify`` and the command every
#: completion claim in this repo runs, so re-deriving it with a second parser
#: here would compare the subject against itself. Changing this repo's gate
#: command turns this test red, which is the correct amount of friction.
OWN_GATE = "bash scripts/verify.sh"


def _node() -> str:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node not available")
    return node


def _declared(text: str) -> str:
    """Ask the shipped parser what ``text`` declares.

    Returns ``"OK <command>"`` or ``"ERR <ClassName>: <message>"``. The class
    name is carried back rather than swallowed so a ``TypeError`` from a broken
    parser cannot read as a deliberate refusal — two identically-failed runs
    compare equal otherwise (craft.md → *Two identically-failed runs compare
    equal*).

    ``require``-ing the helper does not run it: its entry point sits behind
    ``require.main === module``. The spine text travels in the environment, so
    no fixture is re-quoted through a shell on the way in.
    """
    script = (
        "const h = require(process.env.HELPER_PATH);"
        "try { process.stdout.write('OK ' + h.declaredVerify(process.env.SPINE_TEXT, 'SPINE')); }"
        "catch (err) { process.stdout.write("
        "'ERR ' + err.constructor.name + ': ' + err.message); }"
    )
    proc = subprocess.run(
        [_node(), "-e", script],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=60,
        env={**os.environ, "HELPER_PATH": str(HELPER), "SPINE_TEXT": text},
    )
    assert proc.returncode == 0, f"the parser crashed: {proc.stderr.strip()}"
    return proc.stdout


def _value(text: str) -> str:
    """The command ``text`` declares; fails loudly when it declares none."""
    answer = _declared(text)
    assert answer.startswith("OK "), answer
    return answer[len("OK ") :]


def _refusal(text: str) -> str:
    """The refusal ``text`` earns; fails loudly when it parses to a command."""
    answer = _declared(text)
    assert answer.startswith("ERR GateDeclarationError: "), answer
    return answer


def _spine(*lines: str, newline: str = "\n") -> str:
    """A spine fixture: a fenced yaml block with a little prose around it."""
    return newline.join(["# CLAUDE.md", "", "```yaml", *lines, "```", ""])


# --- the floor: this repository's own spine files ------------------------------


@pytest.mark.parametrize("spine", ["CLAUDE.md", "AGENTS.md"])
def test_the_repositorys_own_spine_declares_the_gate_it_runs(spine: str) -> None:
    """The subject's own file is the first corpus (#484/#487).

    Both are real, both are large, and ``AGENTS.md`` is the generated Codex
    mirror — so a parser that only survives a hand-written five-line fixture
    fails here. Read from the git **index**: the tree the gate certifies is the
    staged one (#482).
    """
    assert _value(indexed_text(spine)) == OWN_GATE


# --- one fixture per legal spelling --------------------------------------------

#: Every case is ``(id, spine text, expected)``. ``expected`` is the command the
#: spelling declares, or ``None`` where the refusal is the contract. No two
#: fixtures declare the same command and none declares :data:`OWN_GATE`, so a
#: parser that fell back to a constant, or that read a neighbouring fixture's
#: line, produces the wrong answer rather than an accidentally right one.
_CASES: list[tuple[str, str, str | None]] = [
    (
        # #488's first spelling, one keystroke from this repo's own spine. Until
        # the fix the key had to be *literally* empty, so this line was not read
        # as opening a block at all and the gate became permanently unrunnable
        # (exit 3). The comment names a command-shaped word: a fix that split the
        # line instead of asking the value could leak `ignored-command` through.
        "comment-on-the-key-line",
        _spine("commands:   # the managed ones, not ignored-command", "  verify: make key-comment"),
        "make key-comment",
    ),
    (
        # A `commands: <scalar>` line used to abort the whole scan, so any prose
        # or example line above the block killed the real declaration below it.
        "prose-line-before-the-block",
        _spine(
            "# interview for commands: bootstrap first",
            "commands:",
            "  verify: make after-prose",
        ),
        "make after-prose",
    ),
    (
        # The same defect with the key at column 0, where the block reader looks.
        "scalar-commands-line-before-the-block",
        "commands: see the interview\n\n```yaml\ncommands:\n  verify: make after-scalar\n```\n",
        "make after-scalar",
    ),
    (
        # An indented example block cannot hijack the read: the declaration is a
        # top-level key of the spine's config map.
        "indented-example-block-before-the-real-one",
        _spine(
            "guidance:",
            "  commands:",
            "    verify: make indented-example",
            "commands:",
            "  verify: make real-declaration",
        ),
        "make real-declaration",
    ),
    (
        # Two top-level declarations are an ambiguity, not a race the first one
        # wins. The sibling reader takes the first `branches:` block; here the
        # command decides what may mint evidence, so ambiguity fails closed.
        "two-top-level-blocks",
        _spine("commands:", "  verify: make first-block")
        + _spine("commands:", "  verify: make second-block"),
        None,
    ),
    (
        # yaml allows space before the colon; the sibling's key pattern does too.
        "space-before-the-colon",
        _spine("commands :", "  verify: make spaced-key"),
        "make spaced-key",
    ),
    (
        # A comment after the value, the ordinary case, and the one the old
        # `\s+#` strip already handled — kept so the rewrite cannot lose it.
        "comment-after-the-value",
        _spine("commands:", "  verify: make trailing-comment   # the gate"),
        "make trailing-comment",
    ),
    (
        # Comments are cut **outside quotes only**. Cutting first made a
        # perfectly ordinary quoted command unreadable (exit 3).
        "hash-inside-a-quoted-value",
        _spine("commands:", '  verify: "npm test # smoke"'),
        "npm test # smoke",
    ),
    (
        # A `#` with no whitespace before it is not a comment in a yaml plain
        # scalar. A deliberate departure from the sibling's `indexOf('#')`, kept
        # from the reader this replaces, and pinned so it is not lost by drift.
        "hash-without-preceding-space",
        _spine("commands:", "  verify: make target#1"),
        "make target#1",
    ),
    (
        "single-quoted-value",
        _spine("commands:", "  verify: 'make single-quoted'"),
        "make single-quoted",
    ),
    (
        # Quote parity is a dimension every fixture above holds constant, and a
        # corpus is blind to one (craft.md → *A corpus is blind to any dimension
        # its fixtures hold constant*). An apostrophe inside a plain scalar is
        # ordinary text — yaml opens a quoted scalar only at the *start* of a
        # value — so this declaration is legal and its trailing comment is still
        # a comment. A reader that tracks quotes anywhere left the state open,
        # never cut the comment, and handed `sh` a longer command than the spine
        # declares.
        "apostrophe-in-a-plain-scalar",
        _spine("commands:", "  verify: echo it's fine   # the gate"),
        "echo it's fine",
    ),
    (
        # The same open state, in the direction where the value really is quoted:
        # nothing closes it, so there is no scalar here to read. Refused rather
        # than handed on with its opening quote attached.
        "unterminated-quoted-value",
        _spine("commands:", '  verify: "make unterminated'),
        None,
    ),
    (
        # The serious one. Quote parity is *even*, so an open-state check alone
        # admits it, and stripping "one matching pair of surrounding quotes"
        # deletes the two quotes that never delimited the whole value — yielding
        # `printf outer" && "printf inner`, which `sh` re-tokenises into a
        # different command that can exit 0 and mint a marker for a tree whose
        # declared gate never ran. Not a legal yaml scalar: a quoted scalar is
        # the whole value or it is nothing.
        "quoted-scalar-with-trailing-content",
        _spine("commands:", '  verify: "printf outer" && "printf inner"'),
        None,
    ),
    (
        # #488's third spelling: a clone made under `core.autocrlf=true`. The
        # trailing `\r` cannot be crossed by `(.*)$` in JavaScript, so the whole
        # block parsed to nothing in the sibling while its flow spelling was fine.
        "crlf-line-endings",
        _spine("commands:", "  verify: make crlf-value", newline="\r\n"),
        "make crlf-value",
    ),
    (
        # A tab *inside* the declared value. The reader expanded tabs across the
        # whole line before matching, so this value reached `sh` as
        # `make<space><space>tab-value` — the runner launching a command the
        # spine does not declare, which is the silent mis-derivation ADR 0018
        # refuses indicators and fragments to prevent (#510, sixth review cycle).
        "tab-inside-the-value",
        _spine("commands:", "  verify: make\ttab-value"),
        "make\ttab-value",
    ),
    (
        # The half of that expansion which must survive the fix, and the paired
        # splice that proves it was live (craft.md → *A prose mutation needs a
        # paired splice to prove it was live*, read here for code): tabs in
        # **indentation** are still expanded, so a tab-indented entry and a
        # space-indented sibling line up at the same lead. Drop the expansion
        # and the two leads differ (1 against 2), `verify` is read as a nested
        # key, and the spine becomes unrunnable. Green before the fix as well as
        # after — it pins what the fix must not take with it.
        "tab-indented-sibling-of-a-space-indented-entry",
        _spine("commands:", "\tbootstrap: make tab-bootstrap", "  verify: make tab-indent"),
        "make tab-indent",
    ),
    (
        # A sibling key at the same indentation, and one nested deeper, neither of
        # which is the declaration.
        "siblings-and-a-nested-key",
        _spine(
            "commands:",
            "  bootstrap: make bootstrap-value",
            "  test: make test-value",
            "  verify: make among-siblings",
            "  extra:",
            "    verify: make nested-decoy",
            "branches:",
            "  integration: dev",
        ),
        "make among-siblings",
    ),
    (
        # The worst case the review named: a line reader returns the indicator
        # itself, and `sh -c ">"` exits 2 — the code reserved for a fact about
        # the repository. A silent mis-derivation that runs a fragment.
        "folded-scalar",
        _spine("commands:", "  verify: >", "    make folded"),
        None,
    ),
    (
        "block-scalar",
        _spine("commands:", "  verify: |", "    make literal"),
        None,
    ),
    (
        "yaml-anchor",
        _spine("commands:", "  verify: &gate make anchored"),
        None,
    ),
    (
        "alias",
        _spine("commands:", "  verify: *gate"),
        None,
    ),
    (
        # Deliberately unread, recorded in ADR 0018. It must refuse, never
        # produce the fragment a naive scalar read would.
        "flow-mapping-commands",
        _spine('commands: {verify: "make flow-value"}'),
        None,
    ),
    (
        "flow-mapping-value",
        _spine("commands:", "  verify: {command: make flow-inner}"),
        None,
    ),
    (
        "flow-sequence-value",
        _spine("commands:", "  verify: [make, seq]"),
        None,
    ),
    (
        "empty-value",
        _spine("commands:", "  verify:"),
        None,
    ),
    (
        "empty-quoted-value",
        _spine("commands:", '  verify: ""'),
        None,
    ),
    (
        "value-that-is-only-a-comment",
        _spine("commands:", "  verify:   # to be decided"),
        None,
    ),
    (
        "no-verify-key",
        _spine("commands:", "  test: make only-test"),
        None,
    ),
    (
        "no-commands-block",
        _spine("branches:", "  integration: dev"),
        None,
    ),
    (
        "duplicate-verify-key",
        _spine("commands:", "  verify: make first", "  verify: make second"),
        None,
    ),
]


@pytest.mark.parametrize(
    ("text", "expected"),
    [(text, expected) for _, text, expected in _CASES],
    ids=[name for name, _, _ in _CASES],
)
def test_every_legal_spelling_parses_and_every_refused_one_refuses(
    text: str, expected: str | None
) -> None:
    """One case per spelling, each with an answer of its own.

    A refusal is asserted as a refusal *of the parser's own class*, not merely
    as "no command": a crash and a decision are the same absence of a value, and
    only one of them is the contract.
    """
    if expected is None:
        _refusal(text)
    else:
        assert _value(text) == expected


def test_no_two_fixtures_share_an_answer() -> None:
    """The corpus's own floor.

    A fixture whose expected value duplicates another's, or duplicates the
    command this repository declares, cannot separate *parsed this line* from
    *fell back* or *read the neighbour* — the dimension a corpus most often
    holds constant (craft.md → *A corpus is blind to any dimension its fixtures
    hold constant*).
    """
    values = [expected for _, _, expected in _CASES if expected is not None]

    assert len(values) == len(set(values)), sorted(values)
    assert OWN_GATE not in values
    assert sum(1 for _, _, expected in _CASES if expected is None) >= 2


# --- the origin: no per-invocation source for the command ----------------------

#: The one shell entry the runner is permitted to build, as its literal parts.
#: Stated as constants so each is sampled by a synthetic source below.
SHELL_BINARY = "sh"
SHELL_FLAG = "-c"

#: The one binary this file may spawn with an argument vector instead. Its two
#: helpers pass argv arrays that no shell reads, and one of their operands is a
#: path chosen by whoever created a worktree — the reason they are argv in the
#: first place.
GIT_BINARY = "git"

#: The tokens that make a value per-invocation rather than checked-in. ``argv``
#: covers both ``process.argv`` and the parameter every dispatch here passes
#: under that name.
TAINTED = ("process.env", "process.argv", "argv")

#: What the permitted origin must actually be. A closure that reached the
#: command without reading a file at all would satisfy every prohibition above
#: while proving nothing (#467 — a sweep needs a floor on its corpus).
FILE_READ = "readFileSync"


def _blank(source: str) -> str:
    """Blank comment and string-literal *contents*, preserving every offset.

    Brace and bracket matching counts delimiters, and this file's own strings
    contain ``"{}"`` and ``"[]"`` as data. Offsets are preserved so a slice of
    the blanked text lines up with the same slice of the original, which is how
    the literals below are read back. The spelling is
    ``tests/unit/test_hooks_fail_open_is_loud.py``'s, whose subject is the same
    kind of file.
    """
    out = list(source)
    i, n = 0, len(source)
    quote: str | None = None
    while i < n:
        ch = source[i]
        if quote is not None:
            if ch == "\\":
                out[i] = " "
                if i + 1 < n and source[i + 1] != "\n":
                    out[i + 1] = " "
                i += 2
                continue
            if ch == quote:
                quote = None
            elif ch != "\n":
                out[i] = " "
            i += 1
            continue
        if ch in "\"'`":
            quote = ch
            i += 1
            continue
        if ch == "/" and i + 1 < n and source[i + 1] == "/":
            while i < n and source[i] != "\n":
                out[i] = " "
                i += 1
            continue
        if ch == "/" and i + 1 < n and source[i + 1] == "*":
            while i < n and not (source[i] == "*" and i + 1 < n and source[i + 1] == "/"):
                if source[i] != "\n":
                    out[i] = " "
                i += 1
            out[i : i + 2] = [" ", " "]
            i += 2
            continue
        i += 1
    return "".join(out)


def _matching(blanked: str, open_at: int) -> int:
    """Index of the delimiter closing the one at ``open_at``."""
    pairs = {"(": ")", "[": "]", "{": "}"}
    opener = blanked[open_at]
    closer = pairs[opener]
    depth = 0
    for i in range(open_at, len(blanked)):
        if blanked[i] in pairs:
            depth += 1
        elif blanked[i] in pairs.values():
            depth -= 1
            if depth == 0:
                assert blanked[i] == closer, f"mismatched delimiter at offset {i}"
                return i
    raise AssertionError(f"unbalanced delimiter from offset {open_at}")


def _split_arguments(blanked: str, source: str, open_at: int) -> list[tuple[str, int]]:
    """``(text, offset)`` for each top-level argument of the group at ``open_at``.

    The offset is where that argument's text begins in ``source``, so a nested
    group can be re-entered without searching for its delimiter by eye.
    """
    close_at = _matching(blanked, open_at)
    parts: list[tuple[str, int]] = []
    depth = 0
    start = open_at + 1

    def piece(begin: int, end: int) -> tuple[str, int]:
        text = source[begin:end]
        return text.strip(), begin + (len(text) - len(text.lstrip()))

    for i in range(start, close_at):
        ch = blanked[i]
        if ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth -= 1
        elif ch == "," and depth == 0:
            parts.append(piece(start, i))
            start = i + 1
    tail = piece(start, close_at)
    if tail[0] or parts:
        parts.append(tail)
    return parts


def _functions(blanked: str, source: str) -> dict[str, tuple[int, int]]:
    """Every top-level ``function name(…) {…}`` and ``class Name {…}``, by body span.

    Top level only — a nested declaration is not the module's own definition,
    and a name resolved to one would be a different function than the one this
    guard then reads. These are the module-level names whose bodies the walk
    below can **read**; every other module-level name is classified by
    :func:`_module_bindings` as inert or as unreadable.
    """
    spans: dict[str, tuple[int, int]] = {}
    for match in re.finditer(r"^function\s+([A-Za-z_$][\w$]*)\s*\(", blanked, re.MULTILINE):
        opener = blanked.index("{", _matching(blanked, match.end() - 1))
        spans[match.group(1)] = (opener, _matching(blanked, opener) + 1)
    for match in re.finditer(r"^class\s+([A-Za-z_$][\w$]*)\b", blanked, re.MULTILINE):
        opener = blanked.index("{", match.end())
        spans[match.group(1)] = (opener, _matching(blanked, opener) + 1)
    return spans


#: A module-level ``const``/``let``/``var`` binding and the head of its
#: initializer. Anchored at column 0: a binding indented inside a function is
#: that function's local, and the walk covers a local through the taint scan over
#: the body that declares it.
_MODULE_BINDING = re.compile(r"^(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*(.*)$", re.MULTILINE)

#: The destructured form, which is how this file binds ``spawnSync``.
_MODULE_DESTRUCTURED = re.compile(r"^(?:const|let|var)\s*\{([^}]*)\}\s*=\s*(.*)$", re.MULTILINE)

#: An initializer whose value cannot carry a gate command: a ``require`` of a
#: **Node builtin** — ``node:`` prefixed, so ``require("./sneaky")`` is not
#: inert — or a literal (regex, string, number, keyword). Earned from the
#: subject rather than listed: every module-level name this file binds is one of
#: these or a function/class, and the mutants below are exactly the spellings
#: that are neither (craft.md → *make the allowlist earn itself from the
#: subject*).
#:
#: Matched against the **whole** initializer, not its first character. Anchoring
#: at the head asked *does this open like a literal*, and the answer is yes for
#: ``"" + process.env.SNEAK`` — an expression the guard then classified inert and
#: skipped everywhere it was read (#510, sixth review cycle). A template literal
#: is inert only with no ``${…}`` substitution, for the same reason.
_INERT_INITIALIZER = re.compile(
    r"""(?:
        require\(\s*"node:[a-z_]+"\s*\)     # a Node builtin, by its prefixed name
      | "(?:[^"\\]|\\.)*"                   # a double-quoted string
      | '(?:[^'\\]|\\.)*'                   # a single-quoted string
      | `[^`$\\]*`                          # a template with no substitution
      | /(?:[^/\\\n]|\\.)+/[a-z]*           # a regex literal
      | -?\d[\w.]*                          # a number, in any base
      | true | false | null | undefined
    )\s*;?\s*""",
    re.VERBOSE,
)


def _inert_initializer(text: str) -> bool:
    """Whether ``text`` is *wholly* one of the values that cannot carry a command."""
    return _INERT_INITIALIZER.fullmatch(text.strip()) is not None


def _module_bindings(source: str) -> tuple[set[str], set[str]]:
    """``(inert, opaque)`` — every module-level name that is not a span.

    ``inert`` is a name bound to a Node-builtin ``require`` or to a literal;
    calling one cannot introduce a per-invocation source. ``opaque`` is every
    other module-level binding — an arrow, a function expression, an object
    literal, a call — a *value* this guard cannot read, and therefore an
    offender the moment the walked closure calls it.
    """
    inert: set[str] = set()
    opaque: set[str] = set()
    for match in _MODULE_BINDING.finditer(source):
        target = inert if _inert_initializer(match.group(2)) else opaque
        target.add(match.group(1))
    for match in _MODULE_DESTRUCTURED.finditer(source):
        target = inert if _inert_initializer(match.group(2)) else opaque
        for name in match.group(1).split(","):
            bound = name.split(":")[-1].strip()
            if bound:
                target.add(bound)
    return inert, opaque


#: The **root** of every identifier reference in a body, whatever position it
#: occupies — callee, operand, argument, or the right-hand side of a binding.
#: Scanning references rather than call sites is what closes the frontier the
#: sixth review cycle found: a module-level name that was merely read
#: (``INJECTED || declaredVerify(…)``) never reached the classification below,
#: so the fail-closed branch fired only when a name was followed by ``(``.
#:
#: The lookbehind drops anything after a ``.``, which is what keeps a property
#: (``gate.command``), a method on a chained call (``line.replace(…).replace(…)``)
#: and a method on a literal (``/\\s/.test(…)``) out: those names are not
#: module-level bindings, and their receiver is an expression living inside the
#: body being scanned, covered by that body's own taint scan.
_REFERENCE = re.compile(r"(?<![\w$.])([A-Za-z_$][\w$]*)")


def shell_entries(source: str) -> list[tuple[int, str, str | None]]:
    """``(offset, expression, problem)`` for every shell spawn in ``source``.

    A spawn is *not* a shell entry only when its first argument is the literal
    ``"git"``: those two helpers pass an argument vector, which no shell reads,
    and one of their operands is a path chosen by whoever created a worktree.
    Everything else must be the one permitted shape — ``spawnSync("sh", ["-c",
    <expression>], …)`` — so a spawn of another binary, of a computed binary, or
    of ``sh`` with an extra operand cannot slip past unclassified.

    Split out from the offender predicate so the floor can assert the scan found
    something: an extractor that silently returned ``[]`` would satisfy "nothing
    unsafe reaches the shell" having read nothing at all (#467).
    """
    blanked = _blank(source)
    entries: list[tuple[int, str, str | None]] = []
    for match in re.finditer(r"\bspawnSync\s*\(", blanked):
        arguments = _split_arguments(blanked, source, match.end() - 1)
        if not arguments:
            continue
        binary = arguments[0][0]
        if binary == json.dumps(GIT_BINARY):
            continue
        argv = arguments[1][0] if len(arguments) > 1 else ""
        if binary != json.dumps(SHELL_BINARY):
            entries.append(
                (match.start(), binary, f"the shell binary is not the literal {SHELL_BINARY!r}")
            )
            continue
        if not argv.startswith("["):
            entries.append((match.start(), argv, "the shell entry's argv is not a literal list"))
            continue
        elements = _split_arguments(blanked, source, arguments[1][1])
        spelled = [text for text, _ in elements]
        if len(elements) != 2 or spelled[0] != json.dumps(SHELL_FLAG):
            entries.append(
                (
                    match.start(),
                    argv,
                    f"the shell entry is not exactly {SHELL_FLAG!r} plus one operand",
                )
            )
            continue
        entries.append((match.start(), spelled[1], None))
    return entries


def command_origins(source: str) -> tuple[list[str], set[str]]:
    """``(offenders, closure)`` for every command ``source`` hands to a shell.

    ``closure`` is the set of top-level functions that can produce one of those
    commands, walked from the name filling the ``-c`` slot: the assignments to
    that name inside **the function containing the spawn**, then the functions
    those assignments call, transitively. Resolved by the spawn's offset rather
    than by which body happens to mention the name — the payload this file
    writes carries a ``gate:`` field, so a name-based search finds the emitter
    and reports a defect the code does not have.

    An offender is a per-invocation value entering that closure by one of these
    routes: a slot filled by something other than a name bound to a call, an
    assignment whose right-hand side is not a call to a function declared in this
    file, a tainted token anywhere inside one of them, or — the frontier below —
    a module-level name this walk cannot read.

    **Which positions are classified.** The subject of the trichotomy is a
    **module-level name**, and it is classified in every position a walked body
    mentions one: as a callee (``helper(cwd)``), as the receiver of a call
    (``reader.pick(cwd)``), and as a bare reference (``INJECTED ||
    declaredVerify(…)``). Two earlier spellings of this paragraph read wider than
    the code. The first claimed the walk caught "any way" a per-invocation value
    entered the closure (#510, third cycle). The second stated the trichotomy
    correctly but the code applied it only where a name was followed by ``(``, so
    a name that was merely *read* never reached it — and end to end, binding
    ``process.env.HARNESS_GATE_COMMAND`` at module level and returning it from
    ``gateCommand`` ran an attacker-chosen command, minted that tree's marker and
    exited 0, while this file reported 45 passed (#510, sixth cycle).

    **The trichotomy.** A top-level ``function`` or ``class`` is walked. A name
    bound *wholly* to a Node-builtin ``require`` or to a literal is inert. Any
    other module-level name — an arrow, a function expression, an object literal,
    a call, or an expression that merely opens with a literal — is a value this
    guard **cannot read** and is reported rather than skipped. That last branch
    is the fail-closed frontier: the guard goes red on a producer it does not
    understand instead of treating it as *not my subject* (craft.md → *A guard
    over an enumerable dimension must fail on an unclassified member*). Its cost
    is stated plainly: a future benign module-level helper referenced anywhere in
    this closure turns this test red until someone classifies it.

    **What is still not classified — a limit, not closure.** A name that is not
    module-level is *skipped*: a parameter, a local, a language construct
    (``if``, ``for``, ``catch``), or a property after a ``.`` (there the receiver
    is the classified name). Those are covered only by the :data:`TAINTED` token
    scan over the body that declares them, so a local carrying no tainted token
    is invisible here. Measured rather than assumed: fed a walked body containing
    ``const {pick} = require("./sneaky")`` and a ``pick(cwd)`` call, this
    predicate returns no offender, while the same binding written at module level
    is reported. Closing that would mean resolving locals, which is a different
    guard; what is claimed here is the module-level frontier only.

    One function, called by the tree-wide assertion **and** by every synthetic
    case, so a change to how production is scanned is a change to what every
    control measures (craft.md → *A positive control must exercise the
    predicate, not re-implement it*).
    """
    blanked = _blank(source)
    spans = _functions(blanked, source)
    inert, opaque = _module_bindings(source)
    offenders: list[str] = []
    closure: set[str] = set()
    for offset, slot, problem in shell_entries(source):
        if problem is not None:
            offenders.append(f"{problem}: {slot}")
            continue
        reached = [token for token in TAINTED if re.search(rf"\b{re.escape(token)}\b", slot)]
        if reached:
            offenders.append(f"the command slot reads {reached[0]} directly: {slot}")
            continue
        name = re.fullmatch(r"([A-Za-z_$][\w$]*)(?:\.[A-Za-z_$][\w$]*)*", slot)
        if name is None:
            offenders.append(f"the command is not read off a bound name: {slot}")
            continue
        root = name.group(1)
        holder = next(
            (span for span in spans.values() if span[0] < offset < span[1]),
            None,
        )
        if holder is None:
            offenders.append(f"the spawn of {slot} sits in no function this guard can read")
            continue
        bindings = re.findall(
            rf"(?:^|[^\w$.]){root}\s*=\s*([^;\n]+)",
            _blank(source[holder[0] : holder[1]]),
            re.MULTILINE,
        )
        if not bindings:
            offenders.append(f"{root!r} is never bound in the function that spawns it")
        pending = []
        for binding in bindings:
            call = re.fullmatch(r"\s*([A-Za-z_$][\w$]*)\s*\(.*\)\s*", binding, re.DOTALL)
            if call is None or call.group(1) not in spans:
                offenders.append(f"{root} is assigned something other than a local call: {binding}")
                continue
            pending.append(call.group(1))
        while pending:
            current = pending.pop()
            if current in closure:
                continue
            closure.add(current)
            body = _blank(source[spans[current][0] : spans[current][1]])
            for token in TAINTED:
                if re.search(rf"\b{re.escape(token)}\b", body):
                    offenders.append(f"{current}() reaches the gate command through {token}")
            for root in _REFERENCE.findall(body):
                if root in spans:
                    pending.append(root)
                elif root in opaque:
                    offenders.append(
                        f"{current} references {root}, which this guard cannot read"
                    )
                elif root not in inert:
                    # A parameter, a local, a property key, or a language
                    # construct: declared inside a body this walk scans for
                    # TAINTED itself.
                    continue
    return offenders, closure


def test_the_gate_command_can_only_come_from_a_file_the_tree_carries() -> None:
    """AC-4: no per-invocation source for the gate command exists.

    ADR 0018's boundary is that ``run`` cannot be turned into a wrapper that
    mints success for a caller-supplied process. Sourcing the command from the
    spine keeps it: a process that can rewrite ``commands.verify`` can already
    rewrite ``verify.sh``, the same local trust domain. What must not exist is
    any per-invocation source — an operand, an environment variable, argv — and
    that is what this measures, rather than measuring that one invented variable
    name happens to be ignored.

    ``runGate`` itself names ``process.env``, legitimately, to *set* the internal
    variable on the child's environment. The scan is therefore over the closure
    that **produces the command**, not over the function that spawns it.
    """
    source = (REPO_ROOT / "scripts" / "gate-marker.js").read_text(encoding="utf-8")
    spans = _functions(_blank(source), source)

    entries = shell_entries(source)
    offenders, closure = command_origins(source)

    assert len(entries) == 1, f"expected exactly one shell entry to constrain, got {entries}"
    assert offenders == []
    assert closure, "the command's producer chain is empty, so nothing was scanned"
    assert any(
        FILE_READ in source[spans[name][0] : spans[name][1]] for name in sorted(closure)
    ), (
        f"no function in {sorted(closure)} reads a file, so the command this guard "
        "calls checked-in has no checked-in origin"
    )


#: Synthetic sources whose answers **differ from this tree's**: one per constant
#: in the permitted shape, one per way a per-invocation value could arrive. Fed
#: only production source, a shape matcher and a hardcoded pass are
#: indistinguishable (#458).
_CLEAN = """
const fs = require("node:fs");
function declaredVerify(text, source) {
  return text.split("\\n")[0];
}
function gateCommand(cwd) {
  const text = fs.readFileSync(cwd, "utf8");
  return { command: declaredVerify(text, cwd) };
}
function runGate(cwd) {
  let gate;
  gate = gateCommand(cwd);
  const result = spawnSync("sh", ["-c", gate.command], {
    env: Object.assign({}, process.env, { RUNNER: "1" }),
  });
  return result.status;
}
"""

_ORIGIN_CASES: list[tuple[str, str, bool]] = [
    ("production-shape", _CLEAN, True),
    (
        "environment-reaches-the-parser",
        _CLEAN.replace(
            'return text.split("\\n")[0];',
            'return process.env.HARNESS_GATE_COMMAND || text.split("\\n")[0];',
        ),
        False,
    ),
    (
        "environment-reaches-the-resolver",
        _CLEAN.replace(
            "return { command: declaredVerify(text, cwd) };",
            "return { command: process.env.GATE || declaredVerify(text, cwd) };",
        ),
        False,
    ),
    (
        "argv-reaches-the-resolver",
        _CLEAN.replace("function gateCommand(cwd) {", "function gateCommand(cwd, argv) {").replace(
            "return { command: declaredVerify(text, cwd) };",
            "return { command: argv[1] || declaredVerify(text, cwd) };",
        ),
        False,
    ),
    (
        "the-slot-is-filled-from-the-environment-directly",
        _CLEAN.replace('["-c", gate.command]', '["-c", process.env.GATE]'),
        False,
    ),
    (
        "the-slot-is-a-template-built-around-the-declaration",
        _CLEAN.replace('["-c", gate.command]', '["-c", `${gate.command} ${process.argv[3]}`]'),
        False,
    ),
    (
        "the-name-is-rebound-to-an-operand",
        _CLEAN.replace("gate = gateCommand(cwd);", "gate = { command: process.argv[3] };"),
        False,
    ),
    (
        "a-second-binding-slips-past-the-first",
        _CLEAN.replace(
            "gate = gateCommand(cwd);",
            "gate = gateCommand(cwd);\n  gate = { command: process.env.GATE };",
        ),
        False,
    ),
    # The three spellings a producer can take that are not a top-level
    # ``function`` declaration (#510, third review cycle). Each one survived the
    # enumerate-the-producers frontier, because a callee absent from the enumerated
    # spans fell into a default branch meaning *not my subject* — and end to end,
    # the first of them let an environment variable choose the gate command while
    # this guard read green (craft.md → *A guard over an enumerable dimension must
    # fail on an unclassified member*).
    (
        "arrow-const-helper-reads-env",
        _CLEAN.replace(
            "function gateCommand(cwd) {",
            'const helper = (cwd) => process.env.SNEAK || fs.readFileSync(cwd, "utf8");\n'
            "function gateCommand(cwd) {",
        ).replace('const text = fs.readFileSync(cwd, "utf8");', "const text = helper(cwd);"),
        False,
    ),
    (
        "const-function-expression-reads-argv",
        _CLEAN.replace(
            "function gateCommand(cwd) {",
            "const chosen = function (cwd) { return process.argv[3]; };\n"
            "function gateCommand(cwd) {",
        ).replace(
            "return { command: declaredVerify(text, cwd) };",
            "return { command: chosen(cwd) || declaredVerify(text, cwd) };",
        ),
        False,
    ),
    (
        "object-method-reads-env",
        _CLEAN.replace(
            "function gateCommand(cwd) {",
            "const reader = { pick(cwd) { return process.env.GATE; } };\n"
            "function gateCommand(cwd) {",
        ).replace(
            "return { command: declaredVerify(text, cwd) };",
            "return { command: reader.pick(cwd) || declaredVerify(text, cwd) };",
        ),
        False,
    ),
    # The same frontier in the position nobody looked at (#510, sixth review
    # cycle). The three cases above all put the unreadable producer in *callee*
    # position, and the walk only classified a name that was followed by `(`; a
    # module-level name merely **referenced** fell through unclassified. End to
    # end, inserting `const INJECTED = process.env.HARNESS_GATE_COMMAND;` above
    # `PAIR` and returning it from `gateCommand` let an environment variable
    # choose the gate command, mint a marker and exit 0, while this file
    # reported 45 passed.
    (
        "module-level-name-referenced-rather-than-called",
        _CLEAN.replace(
            "function gateCommand(cwd) {",
            "const INJECTED = process.env.SNEAK;\nfunction gateCommand(cwd) {",
        ).replace(
            "return { command: declaredVerify(text, cwd) };",
            "return { command: INJECTED || declaredVerify(text, cwd) };",
        ),
        False,
    ),
    # And the same reference behind an initializer that merely *opens* like a
    # literal. A head-anchored inert test reads `"" + process.env.SNEAK` as a
    # string, so the name is classified inert and the reference scan above skips
    # it — the allowlist admitting a member it was never meant to (craft.md →
    # *A guard over an enumerable dimension must fail on an unclassified
    # member*).
    (
        "module-level-name-bound-to-an-expression-opening-with-a-literal",
        _CLEAN.replace(
            "function gateCommand(cwd) {",
            'const INJECTED = "" + process.env.SNEAK;\nfunction gateCommand(cwd) {',
        ).replace(
            "return { command: declaredVerify(text, cwd) };",
            "return { command: INJECTED || declaredVerify(text, cwd) };",
        ),
        False,
    ),
    (
        "the-shell-binary-stops-being-a-literal",
        _CLEAN.replace('spawnSync("sh"', "spawnSync(process.env.SHELL"),
        False,
    ),
    (
        "the-shell-entry-grows-an-operand",
        _CLEAN.replace('["-c", gate.command]', '["-c", gate.command, process.argv[3]]'),
        False,
    ),
]


@pytest.mark.parametrize(
    ("source", "permitted"),
    [(source, permitted) for _, source, permitted in _ORIGIN_CASES],
    ids=[name for name, _, _ in _ORIGIN_CASES],
)
def test_the_origin_predicate_admits_only_the_checked_in_shape(
    source: str, permitted: bool
) -> None:
    """The predicate's own controls, on source it has never seen.

    The permitted case is the floor in the other direction: without it a
    predicate that condemned everything would pass every negative case and read
    as a working guard (craft.md → *Floors decay into decoration*).
    """
    offenders, _ = command_origins(source)

    assert (offenders == []) is permitted, offenders
