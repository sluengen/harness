"""#303 — a hook that falls open must say so on stderr.

The hooks fail open by design: a hook that blocks on its own bug wedges every
``Bash`` call or every ``Write`` in the session, which is worse than one that
approves. But until #303 they fell open **silently** — an empty ``{}`` payload
flows into ``main()`` as ``tool_name === ""``, which every hook treats as "not my
tool" and returns a clean approval for, so a *parse failure* and a *deliberate
pass-through* produced byte-identical output. That is what let #302 hide: in an
ESM consumer repo ``prompt-guard.js`` swallowed its own load failure and reported
success for an unknown length of time, with the install record still saying the
prompt-injection scanner was there.

The fix keeps the posture and adds the diagnostic. stdout, the exit status and the
blocking contract are unchanged; a hook that fell open writes one line to stderr:

    [<TAG>] fail-open: <reason>: <cause>

``<TAG>`` is derived from the filename (``prompt-guard.js`` → ``[PROMPT-GUARD]``)
and this module derives the expected tag the same way, so the five inlined copies
of the helper cannot drift apart. ``<cause>`` is ``err.message`` alone — never any
part of the payload, which is attacker-influenced text: echoing what
``prompt-guard`` was scanning would re-inject it into the transcript through the
channel added to report on it.

Two classes of swallow site, and only one of them reports:

* **Class A** — the hook's own input or decision path failed and it emitted its
  approving decision anyway (the stdin read, and the top-level ``main()``
  wrapper). These must report.
* **Class B** — best-effort writes and probes, legitimately swallowed and already
  carrying explanatory comments from THE-49 (debounce markers, the
  context-monitor state cache, ``statSync`` on a missing transcript,
  ``workflow-guard``'s ``git()`` returning ``""``). These must stay silent — a
  write failure on an advisory debounce marker is genuinely nothing to report,
  and reporting it would emit noise on every tool call.

The two are told apart by a **derived rule over the source**, not a list of line
numbers: a ``catch`` whose ``try`` body reads **stdin** (``readFileSync(0``) or
invokes ``main()`` is Class A; every other ``catch`` is Class B. So a swallow site
added later is classified automatically, and neither class can drift out of view.

Acceptance criteria:

* **AC-1** — every hook, given a malformed stdin payload, writes a non-empty
  stderr naming the hook and the reason, while stdout stays its normal approving
  payload and the exit status stays 0. Measured by *executing* each hook, not by
  grepping for a reporting call.
  :func:`test_falling_open_names_the_hook_and_the_reason_on_stderr`.
* **AC-2** — the fail-open contract is unchanged: no hook blocks, wedges, or
  exits non-zero anywhere in AC-1's corpus, so a fix that turns a swallow into a
  crash fails here. :func:`test_falling_open_still_approves_and_exits_zero`,
  asserted on the same corpus.
* **AC-3** — the #302 regression is now loud. Lives in
  ``test_hooks_module_type.py``, which owns the ESM fixture it reuses:
  ``test_removing_the_manifest_is_loud_on_stderr``.
* **AC-4** — class B stays silent, classified by the derived rule above rather
  than by line number: :func:`test_class_a_sites_report_and_class_b_sites_do_not`
  over the source, and :func:`test_failing_best_effort_writes_stay_silent`
  measuring it behaviourally with a ``TMPDIR`` that does not exist.
* **AC-5** — the five hooks agree on wrapping ``main()``; ``prompt-guard.js`` no
  longer differs from the other four by accident.
  :func:`test_every_hook_wraps_main` (structural, derived from the same scanner)
  and :func:`test_a_throw_inside_main_is_caught_and_reported` (behavioural, so a
  wrapper is proven to *catch* rather than merely to be present).
* **AC-6** — ``test_hooks_no_empty_catch`` still passes (it runs in its own
  module); the classifier here requires a *reporting call* in a Class A catch,
  which is strictly stronger than that guard's "not empty".

The classifier is exercised on **synthetic source** by
:func:`test_classifier_flags_a_silent_class_a_site`,
:func:`test_classifier_flags_a_noisy_class_b_site` and
:func:`test_classifier_reads_bodies_not_just_keywords`, so an implementation that
consulted a table instead of reading the file could not produce their answers, and
:func:`test_classifier_finds_the_real_sites` pins what it finds in the shipped
tree so a classifier degraded to "nothing is Class A" fails.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_HOOKS_DIR = _REPO_ROOT / "hooks"

#: The stable machine-readable marker in a fail-open notice. Tests key on this
#: rather than on the surrounding prose, which is free to be reworded.
_TOKEN = "fail-open:"

#: The malformed payloads that drive a hook down its fail-open path. None parses
#: as JSON, so the stdin read throws wherever it happens to sit — inside
#: ``readStdin`` for two hooks, inside ``main()`` for the other three.
_MALFORMED_PAYLOADS = {
    "unparseable": "{not json",
    "empty": "",
    "truncated": '{"tool_name":',
    "binary": "\x00\xff",
}

#: The shared helper every Class A catch must call. Requiring the named helper
#: rather than any stderr write is what keeps the five inlined copies one idiom.
_REPORTS = re.compile(r"\bfailOpen\s*\(")

#: Any way of writing to stderr, which no Class B catch may do. Wider than
#: :data:`_REPORTS` so a best-effort write cannot start chattering via a
#: lower-level call that the narrower pattern would miss.
_ANY_STDERR = re.compile(r"\bfailOpen\s*\(|console\.error\b|process\.stderr\b")

#: A Class A ``try`` body: it reads stdin (file descriptor 0) or runs ``main()``.
#: Everything else is Class B. This is the derived rule AC-4 asks for.
_CLASS_A_TRY = re.compile(r"readFileSync\s*\(\s*0\b|\bmain\s*\(\s*\)")

#: What each hook's Class A sites are in the shipped tree — the floor under the
#: classifier. Pinned counts, not line numbers: moving a site does not touch this,
#: while a classifier degraded to "nothing is Class A" fails every entry.
_EXPECTED_CLASS_A = {
    "prompt-guard.js": 2,          # readStdin + the main() wrapper it gained in #303
    "git-push-guard.js": 2,        # readStdin + the main() wrapper
    "workflow-guard.js": 1,        # the main() wrapper (stdin is read inside main)
    "context-monitor.js": 1,       # ditto
    "guidance-freshness.js": 1,    # ditto
    "push-target-guard.js": 2,     # readStdin + the main() wrapper (#436)
    "gate-evidence-guard.js": 2,   # ditto
}

#: Which hooks carry Class B sites at all, so the silence half of AC-4 is
#: measured against something rather than trivially satisfied.
#:
#: The two #436 enforcement hooks carry several: a git probe that could not run,
#: a marker that is not there, a CONTEXT.md a repo never wrote, a transcript line
#: still being flushed. Each is a **decision input** rather than a failure — "no
#: marker" is precisely the answer those guards exist to act on — so each is
#: legitimately swallowed, and each must stay silent or every tool call in a
#: repo without a CONTEXT.md would chatter.
_HOOKS_WITH_CLASS_B = {
    "workflow-guard.js",
    "context-monitor.js",
    "guidance-freshness.js",
    "push-target-guard.js",
    "gate-evidence-guard.js",
}


def _node() -> str:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node not available")
    return node


def _hooks() -> list[Path]:
    hooks = sorted(_HOOKS_DIR.glob("*.js"))
    assert hooks, f"expected hook scripts under {_HOOKS_DIR}"
    return hooks


def _tag(hook: str) -> str:
    """The notice tag for ``hook``, derived from its filename.

    Both the hooks and this module derive it the same way, so the five inlined
    copies of the helper cannot drift apart without a test noticing.
    """
    return f"[{Path(hook).stem.upper()}]"


# --- the source classifier ----------------------------------------------------


def _blank_noncode(src: str) -> str:
    """Blank comment and string-literal *contents*, preserving every offset.

    Brace matching below counts ``{``/``}``; one inside a comment or a string
    would throw the count off. Offsets are preserved so slices still line up
    with the original source, and newlines are kept so a clause can still report
    the line it sits on.
    """
    out = list(src)
    i, n = 0, len(src)
    quote: str | None = None
    while i < n:
        ch = src[i]
        if quote is not None:
            if ch == "\\":
                out[i] = " "
                if i + 1 < n and src[i + 1] != "\n":
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
        if ch == "/" and i + 1 < n and src[i + 1] == "/":
            while i < n and src[i] != "\n":
                out[i] = " "
                i += 1
            continue
        if ch == "/" and i + 1 < n and src[i + 1] == "*":
            while i < n and not (src[i] == "*" and i + 1 < n and src[i + 1] == "/"):
                if src[i] != "\n":
                    out[i] = " "
                i += 1
            out[i : i + 2] = [" ", " "]
            i += 2
            continue
        i += 1
    return "".join(out)


_CATCH = re.compile(r"\bcatch\b\s*(?:\([^)]*\))?\s*\{")


def _closing_brace(blanked: str, open_at: int) -> int:
    """Index of the ``}`` closing the ``{`` at ``open_at``."""
    depth = 0
    for i in range(open_at, len(blanked)):
        if blanked[i] == "{":
            depth += 1
        elif blanked[i] == "}":
            depth -= 1
            if depth == 0:
                return i
    raise AssertionError(f"unbalanced braces from offset {open_at}")


def _opening_brace(blanked: str, close_at: int) -> int:
    """Index of the ``{`` opened by the ``}`` at ``close_at``."""
    depth = 0
    for i in range(close_at, -1, -1):
        if blanked[i] == "}":
            depth += 1
        elif blanked[i] == "{":
            depth -= 1
            if depth == 0:
                return i
    raise AssertionError(f"unbalanced braces before offset {close_at}")


class Clause:
    """One ``try``/``catch`` pair, with the two bodies the rule reads.

    Both bodies are the **blanked** text, so the rule reads code and never a
    mention of ``main()`` inside a string or a comment.
    """

    def __init__(self, source: str, try_body: str, catch_body: str, offset: int) -> None:
        self.try_body = try_body
        self.catch_body = catch_body
        self.line = source.count("\n", 0, offset) + 1

    @property
    def is_class_a(self) -> bool:
        return bool(_CLASS_A_TRY.search(self.try_body))

    @property
    def reports(self) -> bool:
        return bool(_REPORTS.search(self.catch_body))

    @property
    def writes_stderr(self) -> bool:
        return bool(_ANY_STDERR.search(self.catch_body))


def _clauses(source: str) -> list[Clause]:
    """Every ``try``/``catch`` in ``source``, as :class:`Clause` objects.

    The ``try`` body is recovered by walking back from the ``catch`` to the ``}``
    that closes the ``try`` block and then to its matching ``{``, so nesting and
    multi-statement bodies are handled without having to find the ``try``
    keyword's block by forward search.
    """
    blanked = _blank_noncode(source)
    clauses = []
    for match in _CATCH.finditer(blanked):
        catch_open = match.end() - 1
        catch_body = blanked[catch_open + 1 : _closing_brace(blanked, catch_open)]
        try_close = blanked.rfind("}", 0, match.start())
        assert try_close != -1, f"catch at offset {match.start()} has no preceding block"
        try_open = _opening_brace(blanked, try_close)
        preceding = blanked[:try_open].rstrip()
        assert preceding.endswith("try"), (
            "the block before a catch should be a try block; got "
            f"{preceding[-40:]!r} at offset {try_open}"
        )
        clauses.append(Clause(source, blanked[try_open + 1 : try_close], catch_body, match.start()))
    return clauses


def _classify(source: str) -> tuple[list[Clause], list[Clause]]:
    """``(class_a, class_b)`` clauses of ``source``, by the derived rule."""
    clauses = _clauses(source)
    return [c for c in clauses if c.is_class_a], [c for c in clauses if not c.is_class_a]


# --- the classifier's own controls, on synthetic source ------------------------


def test_classifier_flags_a_silent_class_a_site() -> None:
    """Run the real classifier over source it has never seen. Class A, silent."""
    synthetic = """
        function readStdin() {
          try { return JSON.parse(require("fs").readFileSync(0, "utf8")); }
          catch { return {}; }
        }
        try { main(); } catch { process.stdout.write("{}"); }
    """
    class_a, class_b = _classify(synthetic)
    assert len(class_a) == 2, f"expected the stdin read and the main() wrapper, got {len(class_a)}"
    assert not class_b
    assert not any(c.reports for c in class_a), (
        "neither synthetic site reports; the fixture is wrong"
    )


def test_classifier_flags_a_noisy_class_b_site() -> None:
    """A best-effort write that *does* report is Class B and must be flagged."""
    synthetic = """
        function mark(f) {
          try { fs.writeFileSync(f, "1"); }
          catch (err) { console.error("marker write failed: " + err.message); }
        }
    """
    class_a, class_b = _classify(synthetic)
    assert not class_a, "a marker write is not the hook's decision path"
    assert len(class_b) == 1
    assert class_b[0].writes_stderr, (
        "the classifier did not see the console.error in the catch body"
    )


def test_classifier_reads_bodies_not_just_keywords() -> None:
    """A ``catch`` whose ``try`` merely *mentions* main in a string is Class B.

    Pins that the rule reads the ``try`` block's code, so blanking string and
    comment contents is load-bearing rather than incidental.
    """
    synthetic = """
        try { log("call main() later"); /* main() */ } catch { return ""; }
    """
    class_a, class_b = _classify(synthetic)
    assert not class_a, "a mention of main() in a string or comment is not an invocation"
    assert len(class_b) == 1


def test_classifier_finds_the_real_sites() -> None:
    """The floor: what the rule finds in the shipped tree, pinned per hook.

    Counts rather than line numbers, so moving a site does not touch this while a
    classifier degraded to "nothing is Class A" fails every entry.
    """
    found = {hook.name: len(_classify(hook.read_text())[0]) for hook in _hooks()}
    assert found == _EXPECTED_CLASS_A, (
        "the derived Class A classification changed. If a swallow site was added "
        "or removed, update _EXPECTED_CLASS_A and make sure the new site reports "
        f"(or stays silent) as its class requires. Found: {found}"
    )
    with_class_b = {hook.name for hook in _hooks() if _classify(hook.read_text())[1]}
    assert with_class_b == _HOOKS_WITH_CLASS_B, (
        f"the set of hooks carrying best-effort (Class B) catches changed: {with_class_b}"
    )


# --- AC-4 (source half) and AC-5 (structural half) ----------------------------


@pytest.mark.parametrize("hook", [h.name for h in _hooks()])
def test_class_a_sites_report_and_class_b_sites_do_not(hook: str) -> None:
    """Every Class A catch calls the helper; no Class B catch writes stderr (AC-4)."""
    class_a, class_b = _classify((_HOOKS_DIR / hook).read_text())
    silent_a = [c.line for c in class_a if not c.reports]
    assert not silent_a, (
        f"{hook}: a catch on the hook's own input or decision path falls open "
        f"without saying so, at line(s) {silent_a}. Call failOpen() — the stdout "
        "payload and exit status stay as they are."
    )
    noisy_b = [c.line for c in class_b if c.writes_stderr]
    assert not noisy_b, (
        f"{hook}: a best-effort write or probe reports on stderr, at line(s) "
        f"{noisy_b}. These are swallowed deliberately (THE-49) and would emit "
        "noise on every tool call; leave them silent."
    )


@pytest.mark.parametrize("hook", [h.name for h in _hooks()])
def test_every_hook_wraps_main(hook: str) -> None:
    """All five hooks agree on wrapping ``main()`` (AC-5).

    Derived from the same scanner the classification uses, so degrading the
    scanner cannot leave this test passing on its own.
    """
    wrappers = [
        c
        for c in _clauses((_HOOKS_DIR / hook).read_text())
        if re.search(r"\bmain\s*\(\s*\)", c.try_body)
    ]
    assert wrappers, (
        f"{hook} does not wrap its main() call, so an exception raised after the "
        "stdin read crashes it while the other hooks fall open. The five hooks "
        "should agree on a posture rather than differ by accident (#303 AC-5)."
    )


# --- AC-1 and AC-2: measured by executing the hooks ---------------------------


def _run(
    hook: str, stdin: str, tmp_path: Path, tmpdir: Path | None = None
) -> subprocess.CompletedProcess[str]:
    """Run a shipped hook with ``stdin`` verbatim, from an isolated CWD.

    ``TMPDIR`` is redirected so the advisory debounce markers these hooks write
    cannot leak between cases — without it a second probe reads the marker the
    first left and stays silent, which would look like a real regression. Pass
    ``tmpdir`` to point it somewhere that does not exist.
    """
    cwd = tmp_path / "cwd"
    cwd.mkdir(exist_ok=True)
    markers = tmpdir if tmpdir is not None else tmp_path / "tmpdir"
    if tmpdir is None:
        markers.mkdir(exist_ok=True)
    return subprocess.run(
        [_node(), str(_HOOKS_DIR / hook)],
        input=stdin,
        text=True,
        capture_output=True,
        timeout=30,
        cwd=cwd,
        env={"PATH": "/usr/bin:/bin:/usr/local/bin", "TMPDIR": str(markers)},
    )


_MALFORMED_CASES = [(hook.name, name) for hook in _hooks() for name in sorted(_MALFORMED_PAYLOADS)]


@pytest.mark.parametrize(("hook", "payload"), _MALFORMED_CASES)
def test_falling_open_names_the_hook_and_the_reason_on_stderr(
    hook: str, payload: str, tmp_path: Path
) -> None:
    """AC-1: the fall-open is observable, and it says which hook and why."""
    proc = _run(hook, _MALFORMED_PAYLOADS[payload], tmp_path)
    assert proc.stderr.strip(), (
        f"{hook} fell open on a {payload} stdin payload and said nothing on "
        "stderr, so a disabled hook is indistinguishable from a working one — "
        "the #303 defect."
    )
    assert _tag(hook) in proc.stderr, (
        f"{hook}'s diagnostic does not carry its derived tag {_tag(hook)}, so a "
        f"session cannot tell which hook fell open. stderr was: {proc.stderr!r}"
    )
    assert _TOKEN in proc.stderr, (
        f"{hook}'s diagnostic does not carry the {_TOKEN!r} marker, so a reader "
        f"cannot tell a fall-open from an ordinary advisory. Got: {proc.stderr!r}"
    )
    reason = proc.stderr.split(_TOKEN, 1)[1].strip()
    assert len(reason) >= 10, (
        f"{hook}'s diagnostic gives no reason after {_TOKEN!r}: {proc.stderr!r}"
    )


@pytest.mark.parametrize(("hook", "payload"), _MALFORMED_CASES)
def test_falling_open_still_approves_and_exits_zero(
    hook: str, payload: str, tmp_path: Path
) -> None:
    """AC-2: the posture is unchanged — a fix that crashes instead fails here."""
    proc = _run(hook, _MALFORMED_PAYLOADS[payload], tmp_path)
    assert proc.returncode == 0, (
        f"{hook} exited {proc.returncode} on a {payload} stdin payload. Failing "
        "open is the posture: a hook that blocks on its own bug wedges the "
        f"session. stderr was: {proc.stderr!r}"
    )
    assert json.loads(proc.stdout) == {"continue": True}, (
        f"{hook} changed its stdout payload while falling open. #303 adds the "
        f"diagnostic only; the decision stays an approval. Got: {proc.stdout!r}"
    )


@pytest.mark.parametrize(("hook", "payload"), _MALFORMED_CASES)
def test_the_notice_is_one_line_and_does_not_echo_the_payload(
    hook: str, payload: str, tmp_path: Path
) -> None:
    """The notice is built from hook constants and ``err.message``, nothing else.

    stdin is attacker-influenced text — ``prompt-guard``'s whole job is that some
    of it is hostile — so a diagnostic that quoted the payload would re-inject it
    into the transcript through the channel added to report on it. One line, so a
    crafted payload cannot forge a second ``fail-open:`` notice either.
    """
    proc = _run(hook, _MALFORMED_PAYLOADS[payload], tmp_path)
    assert proc.stderr.count("\n") <= 1, (
        f"{hook} wrote a multi-line notice, which lets a crafted payload forge a "
        f"second one and flood the transcript: {proc.stderr!r}"
    )
    assert proc.stderr.count(_TOKEN) == 1, (
        f"{hook} wrote {proc.stderr.count(_TOKEN)} fail-open markers where one "
        f"was expected: {proc.stderr!r}"
    )


# --- AC-5 (behavioural half) --------------------------------------------------


def test_a_throw_inside_main_is_caught_and_reported(tmp_path: Path) -> None:
    """A wrapper must *catch*, not merely be present.

    ``guidance-freshness.js`` reaches ``rel()``'s ``file.startsWith(cwd)`` with a
    non-string ``file_path`` and raises a ``TypeError`` well past the stdin read,
    so this exercises the ``main()`` wrapper rather than the parse path — the one
    AC-5 is about. Before #303 it fell open here silently too.
    """
    proc = _run(
        "guidance-freshness.js",
        json.dumps({"tool_name": "Write", "tool_input": {"file_path": 5}}),
        tmp_path,
    )
    assert proc.returncode == 0, f"expected a fall-open, not a crash: {proc.stderr!r}"
    assert json.loads(proc.stdout) == {"continue": True}
    assert _TOKEN in proc.stderr and _tag("guidance-freshness.js") in proc.stderr, (
        "a throw raised inside main() fell open without a notice, so the wrapper "
        f"is present but silent. stderr was: {proc.stderr!r}"
    )


# --- AC-4 (behavioural half): class B stays silent ----------------------------


def _valid_payloads(hook: str, tmp_path: Path) -> dict[str, str]:
    """Valid payloads for ``hook``: its own tool, and a tool it does not watch.

    The unwatched-tool case is the pass-through a fall-open used to be
    indistinguishable from, so its silence is the other half of AC-1's claim.
    """
    unwatched = json.dumps({"tool_name": "Read", "tool_input": {"file_path": "notes.md"}})
    if hook == "context-monitor.js":
        # A transcript path that does not exist, so the statSync probe fails too.
        return {
            "watched": json.dumps({"transcript_path": str(tmp_path / "missing.jsonl")}),
            "unwatched": unwatched,
        }
    if hook == "guidance-freshness.js":
        cwd = tmp_path / "cwd"
        cwd.mkdir(exist_ok=True)
        (cwd / "CLAUDE.md").write_text("# process, but edited\n")
        (cwd / "AGENTS.md").write_text("# process\n")
        return {
            "watched": json.dumps(
                {"tool_name": "Write", "tool_input": {"file_path": str(cwd / "CLAUDE.md")}}
            ),
            "unwatched": unwatched,
        }
    if hook in ("git-push-guard.js", "push-target-guard.js"):
        return {
            "watched": json.dumps(
                {"tool_name": "Bash", "tool_input": {"command": "git push origin dev"}}
            ),
            "unwatched": unwatched,
        }
    if hook == "gate-evidence-guard.js":
        # A Stop payload naming a transcript that is not there. The trigger
        # cannot be established, so the hook allows — and the missing-file read
        # is one of its Class B swallows, which is the point of the case.
        return {
            "watched": json.dumps(
                {
                    "hook_event_name": "Stop",
                    "stop_hook_active": False,
                    "transcript_path": str(tmp_path / "missing.jsonl"),
                }
            ),
            "unwatched": unwatched,
        }
    return {
        "watched": json.dumps({"tool_name": "Write", "tool_input": {"file_path": "src/app.ts"}}),
        "unwatched": unwatched,
    }


@pytest.mark.parametrize("hook", [h.name for h in _hooks()])
@pytest.mark.parametrize("case", ["watched", "unwatched"])
def test_failing_best_effort_writes_stay_silent(hook: str, case: str, tmp_path: Path) -> None:
    """AC-4, measured: a ``TMPDIR`` that does not exist must not make a hook chatter.

    Every debounce-marker and state-cache write fails with ``ENOENT`` here, and
    every ``statSync`` on a marker misses — the whole Class B population failing
    at once. ``ENOENT`` rather than ``chmod``, because a container running the
    gate as root would ignore the permission bits and the test would pass
    vacuously. A source scan alone would not catch a diagnostic added to a shared
    write helper, so this asserts the silence on the running hooks.
    """
    missing = tmp_path / "does-not-exist"
    proc = _run(hook, _valid_payloads(hook, tmp_path)[case], tmp_path, tmpdir=missing)
    assert proc.returncode == 0, f"{hook} exited {proc.returncode}: {proc.stderr!r}"
    assert not proc.stderr.strip(), (
        f"{hook} reported on stderr although its input was valid and only its "
        "best-effort marker writes failed. Those are swallowed deliberately "
        f"(THE-49); reporting them is noise on every tool call. Got: {proc.stderr!r}"
    )
