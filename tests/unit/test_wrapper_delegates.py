"""Guards over ``docker/harness-wrapper.sh``.

Most read the shim's own text:

* **the port ban and what it leaves behind** (#305, #307) — no ported logic still
  executing in the shell, no credential name in its code, no ``eval``;
* **the size ratchet** (:data:`EXECUTABLE_LINE_CEILING`) — the shim may not grow
  back into the thing it was cut down from;
* **the masking guard** (#383) — no command the wrapper runs may hide behind a
  declaring builtin's exit status.

One **runs** the wrapper instead —
:func:`test_an_interpreter_that_cannot_import_the_client_fails_with_the_remedy`
— because a preflight that never executes is the kind that passes while the real
path traceback-crashes. Its exception is stated here rather than left to be
inferred: a reader who took "these all read the source" for the module's rule
would file the next execution test somewhere else, or delete the ``subprocess``
import as vestigial.

The port ban came first and the docstring below is its statement.

**AC-2: the wrapper delegates the ported logic rather than duplicating it (#305).**
A port that leaves the old bash in place is not a port — it is a second
implementation that drifts. The `~/bin/harness` wrapper has already rotted this
way once: a detached copy missed CAL-1008's credential-path fix for 12 days.

**The predicate discriminates between code and prose.** The banned strings are
exactly the words a comment explaining the port needs to use — "credential
resolution used to shell out to ``security find-generic-password``" is *correct
documentation* and must stay legal, while a live call to it must fail. So the scan
strips comments first, and :func:`test_the_predicate_discriminates_code_from_prose`
proves that distinction against synthetic source rather than trusting it.
"""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).parent.parent.parent
WRAPPER = PROJECT_ROOT / "docker" / "harness-wrapper.sh"

#: Logic that moved into ``harness.hostenv`` and must no longer run in the shell.
#: Each entry is the executable spelling, not a topic word.
#:
#: ``gtimeout`` is deliberately **not** here, and the reason is a real seam rather
#: than an exemption. The ``timeout``/``gtimeout`` probe is gone from the credential
#: and identity paths — ``HostPlatform.bounded_run`` replaced it, because Python can
#: bound its own child and bash cannot. But the image-freshness guard and the
#: source-checkout sync stay in shell (see the wrapper's own comment): their job
#: includes detecting "this wrapper has no checkout behind it", which is exactly the
#: state in which checkout-resident Python cannot be imported. That retained half
#: bounds its ``git fetch`` with the same probe, and it has no alternative — the one
#: mechanism that could replace it is the one that is unavailable there.
#: :func:`test_the_timeout_probe_survives_only_in_the_retained_sync_half` pins that
#: boundary so the probe cannot quietly spread back into the ported paths.
PORTED_LOGIC = (
    "security find-generic-password",
    "claudeAiOauth",
    "gh auth token",
    "git config --global",
)

#: Credential names that must no longer appear in the wrapper's *code* (#307).
#: After the rewire the values go straight from the host providers into the docker
#: subprocess's ``env=``; the shell never holds one, so it never names one either.
CREDENTIAL_NAMES = (
    "LINEAR_API_KEY",
    "GITHUB_TOKEN",
    "CLAUDE_CODE_OAUTH_TOKEN",
    "CLAUDE_CODE_OAUTH_EXPIRES_AT",
)

#: A may-not-grow ratchet on the shim. The removed blocks were ~60 lines; without a
#: bound, logic creeps back in under a different spelling one line at a time.
#: Re-baselined *downward* as a rule, with **one** recorded exception — #383, stated
#: below along with the test the next raise has to pass.
#: Re-baselined 165 → 123 by #307, which removed the env-import block and the
#: hand-rolled ``docker run`` (158 → 116 lines) and then spent 7 of that back on
#: the interpreter/import preflight — the wrapper cannot degrade past a missing
#: client any more, so it must fail with the remedy instead of an import traceback
#: (:func:`test_an_interpreter_that_cannot_import_the_client_fails_with_the_remedy`).
#:
#: Raised 123 → 124 by #383, the **first** upward move, for the split
#: `HARNESS_WRAPPER_STATUS` assignment-and-export. **That exception is now spent
#: rather than inherited**: #312 moved the drift classification out of the shim
#: into `harness.hostenv.deployment`, so the line the raise was argued about no
#: longer exists and neither does the function it called. Leaving the argument
#: standing would leave the next reader arguing from a line they cannot find.
#:
#: Re-baselined 124 → 115 by #312, downward, which is this bound's normal
#: direction. `_wrapper_status()` and its two-line export left (−16); a branch
#: honouring a baked source root and three exports of values the client now
#: classifies arrived (+7). The classification did not disappear — it moved
#: somewhere a unit test can reach every verdict, which is what the paragraph
#: below has always said the remedy is.
#:
#: **The test the next raise must pass**, since the value of this bound is that it
#: is hard to argue past and the first exception must not become a foothold: a
#: raise is permitted only for a line that performs **no operation the wrapper did
#: not already perform**. A line adding a branch, the effect of a command the
#: wrapper was not already running, or a value it was not already computing
#: belongs in `harness.hostenv`, which is tested.
EXECUTABLE_LINE_CEILING = 115


def executable_lines(text: str) -> list[str]:
    """The shell's executable lines: comments and blank lines removed.

    Full-line comments only. A trailing comment sits on a line that also carries
    code, and stripping to the first ``#`` would corrupt any line containing a
    literal ``#`` inside a string or parameter expansion — losing real code from
    the scan, which is the direction that makes a ban predicate silently vacuous.
    """
    lines = []
    for raw in text.splitlines():
        stripped = raw.strip()
        if not stripped or stripped.startswith("#"):
            continue
        lines.append(raw)
    return lines


def _wrapper_code() -> str:
    return "\n".join(executable_lines(WRAPPER.read_text()))


def logical_lines(text: str) -> list[str]:
    """Executable lines with ``\\``-continuations folded into one line each.

    A continued command is one command. A predicate matching a single line would
    read ``exec env PYTHONPATH=… \\`` and ``  "${_HOST_PY[@]}" -m harness…`` as two
    unrelated lines and miss the invocation entirely — reporting "not rewired" for
    a wrapper that is, which is the direction that makes a guard useless rather
    than merely noisy.
    """
    joined = re.sub(r"\\\n\s*", " ", text)
    return executable_lines(joined)


def _wrapper_command_lines() -> str:
    return "\n".join(logical_lines(WRAPPER.read_text()))


@pytest.mark.parametrize("banned", PORTED_LOGIC)
def test_ported_logic_is_not_still_implemented_in_the_shell(banned: str) -> None:
    """AC-2 proper: none of the ported logic still executes in the wrapper."""
    assert banned not in _wrapper_code(), (
        f"{banned!r} still executes in the wrapper. It moved to harness.hostenv in "
        f"#305 — two implementations of a credential path is exactly the drift the "
        f"port removes."
    )


def test_the_timeout_probe_survives_only_in_the_retained_sync_half() -> None:
    """The ``gtimeout`` probe is confined to the code that cannot use Python.

    Bounding a subprocess moved to ``HostPlatform.bounded_run`` for every path that
    can reach Python. The source-checkout sync cannot — it runs in the detached-copy
    deployment where there is no checkout to import from — so it keeps the probe.
    This pins the boundary: every surviving occurrence must sit in that sync block,
    so the probe cannot spread back into a path that has an alternative.
    """
    code = _wrapper_code()
    occurrences = [line for line in code.splitlines() if "gtimeout" in line]

    assert occurrences, (
        "the probe vanished entirely — the retained sync half must still bound its "
        "`git fetch`, or an unreachable remote hangs the unattended loop"
    )

    # Bounded by the sync function's own closing brace. The previous delimiter was
    # the *next* function's name (`_wrapper_status()`), and #312 moved that logic
    # into `harness.hostenv.deployment` — so the guard broke on a rename that had
    # nothing to do with the property it protects. It broke loudly, which is the
    # right direction; this removes the coupling rather than re-pointing it at the
    # next neighbour along.
    sync_start = code.index("_sync_source_checkout()")
    sync_block = code[sync_start : code.index("\n}", sync_start)]
    for line in occurrences:
        assert line in sync_block, (
            f"a timeout probe appeared outside the retained sync half: {line.strip()!r}. "
            f"Paths that can reach Python must use HostPlatform.bounded_run."
        )


def test_the_wrapper_delegates_exactly_once() -> None:
    """One call, not a scatter of them.

    More than one would mean the shim resolves some of its environment per-concern
    again, which is the shape the port collapsed.
    """
    invocations = re.findall(r"-m\s+harness\.hostenv", _wrapper_code())

    assert len(invocations) == 1, (
        f"expected exactly one `-m harness.hostenv` invocation, found {len(invocations)}"
    )


def test_the_wrapper_never_evals_anything() -> None:
    """``eval`` in a path that has handled credentials is a code-execution seam.

    Kept from #305 even though the credential records no longer pass through the
    shell (see :func:`test_no_credential_passes_through_the_shell`): the ban costs
    nothing and the wrapper has no legitimate use for ``eval``.
    """
    assert not re.search(r"\beval\b", _wrapper_code()), "the wrapper must not eval anything"


def test_no_credential_passes_through_the_shell() -> None:
    """After the rewire (#307), no credential value enters the shell at all.

    #305 moved *resolution* into Python but still imported the resolved records
    back into bash as ``KEY=value`` — which needed NUL-terminated records, a temp
    file, and an ``export`` that could not be an ``eval``. The client now hands the
    values straight to ``docker`` through the subprocess ``env=``, so that whole
    class of handling is gone rather than made safe. This asserts it stays gone: a
    credential name appearing in the wrapper again means the records came back.
    """
    code = _wrapper_code()

    for name in CREDENTIAL_NAMES:
        assert name not in code, (
            f"{name!r} appears in the wrapper again. Credential values reach the "
            f"container through `harness.hostenv.client`'s subprocess env=, never "
            f"through the shell — re-importing them re-opens the quoting, "
            f"temp-file and NUL-record problems the rewire removed."
        )


# ---------------------------------------------------------------------------
# #307: the wrapper's tail is the client, not a second `docker run`.
# ---------------------------------------------------------------------------


def test_the_wrapper_execs_the_control_socket_client() -> None:
    """The design's *Interface / contract*, literally.

    Without this the ``hostenv`` subsystem has no live production caller: a
    running ``harness serve`` would receive zero requests, because the wrapper
    would still build its own container.
    """
    code = _wrapper_command_lines()

    assert re.search(r"exec\s+.*-m\s+harness\.hostenv\.client", code), (
        "the wrapper must end in `exec … -m harness.hostenv.client \"$(pwd)\" -- \"$@\"`. "
        "Until it does, `harness serve` has no caller and the socket is dead code."
    )


def test_the_wrapper_builds_no_container_of_its_own() -> None:
    """``docker run`` construction has exactly one home (``hostenv.spawn``).

    A second construction in bash is a second security posture: the positional
    argv rule, the pinned ``HARNESS_WORKSPACE_ROOTS`` and the ``:``-in-repo-path
    refusal are all properties of the Python builder, and none of them exist in a
    hand-rolled shell invocation.

    Scoped to ``docker run``: the image-freshness guard legitimately runs
    ``docker image inspect`` and ``docker build``, and banning the word ``docker``
    would delete a guard this rewire deliberately keeps in shell.
    """
    assert not re.search(r"docker\s+run\b", _wrapper_code()), (
        "the wrapper still constructs its own `docker run`. Container construction "
        "belongs to harness.hostenv.spawn, which both the socket path and the "
        "fallback share so they cannot drift into two postures."
    )


def test_an_interpreter_that_cannot_import_the_client_fails_with_the_remedy(
    tmp_path: Path,
) -> None:
    """The detached-copy deployment (CAL-1153), which the rewire changes.

    Before #307 a wrapper with no importable harness package warned and ran its own
    container. Now the client *is* the runtime, so it cannot continue — but it must
    still say **why** and **what to do**. Left to ``exec``, this arrives as a bare
    ``ModuleNotFoundError`` naming neither.

    Executed rather than asserted textually: a probe that does not actually run is
    exactly the kind that passes while the real path traceback-crashes.
    """
    stub_bin = tmp_path / "bin"
    stub_bin.mkdir()
    for name in ("docker", "git"):
        stub = stub_bin / name
        stub.write_text("#!/bin/sh\nexit 0\n")
        stub.chmod(0o755)

    # An interpreter that exists and runs, but cannot import the package — the
    # detached-copy case, where there is no checkout to import from.
    interpreter = stub_bin / "py"
    interpreter.write_text("#!/bin/sh\nexit 1\n")
    interpreter.chmod(0o755)

    detached = tmp_path / "harness"
    detached.write_text(WRAPPER.read_text())
    detached.chmod(0o755)

    result = subprocess.run(
        [str(detached), "version"],
        capture_output=True,
        text=True,
        cwd=tmp_path,
        env={
            **os.environ,
            "PATH": f"{stub_bin}{os.pathsep}{os.environ['PATH']}",
            "HARNESS_HOST_PYTHON": str(interpreter),
        },
    )

    assert result.returncode == 1, (
        f"expected a clean exit 1, got {result.returncode}\nstderr: {result.stderr}"
    )
    assert "harness.hostenv.client" in result.stderr, (
        "the message must name what could not be imported"
    )
    assert "HARNESS_HOST_PYTHON" in result.stderr, "the message must name the remedy"
    assert "Traceback" not in result.stderr, (
        "the failure reached Python's own import error — the probe did not fire"
    )


def test_the_image_freshness_guard_still_runs_in_the_shell() -> None:
    """The half that must *not* move, asserted alongside the half that must.

    This guard detects "this wrapper has no checkout behind it" — precisely the
    state in which checkout-resident Python cannot be imported. Moving it into the
    client would make it unable to fire in the deployment it was written for.
    """
    code = _wrapper_code()

    assert "docker image inspect" in code, (
        "the image-freshness guard left the shell. It cannot live in Python: it "
        "must work when no checkout-resident Python is importable."
    )
    assert "_sync_source_checkout()" in code, "the source-checkout sync left the shell"


def test_the_shim_stays_a_shim() -> None:
    """The may-not-grow ratchet (see EXECUTABLE_LINE_CEILING)."""
    count = len(executable_lines(WRAPPER.read_text()))

    assert count <= EXECUTABLE_LINE_CEILING, (
        f"the wrapper has grown to {count} executable lines, over the "
        f"{EXECUTABLE_LINE_CEILING} ceiling. Logic belongs in harness.hostenv, which "
        f"is tested; the wrapper is a shim. Lower this bound, never raise it."
    )


# ---------------------------------------------------------------------------
# Non-vacuity: the predicate must actually discriminate.
#
# Run over synthetic source, not over the wrapper — a guard checked only against
# the tree it guards passes for whatever reason that tree happens to satisfy.
# ---------------------------------------------------------------------------


def test_the_predicate_discriminates_code_from_prose() -> None:
    """A banned string in a comment is legal; the same string as code is not.

    This is the negative control. Without it the ban could be a blanket substring
    search that "fixes" correct documentation — and the comments explaining *why*
    the logic moved necessarily name the logic that moved.
    """
    prose_only = (
        "#!/usr/bin/env bash\n"
        "# Credential resolution used to call security find-generic-password here,\n"
        "# and parse claudeAiOauth out of it. It moved to harness.hostenv in #305.\n"
        "# The gtimeout / timeout probe and git config --global went with it.\n"
        'echo "harness"\n'
    )
    real_code = prose_only + 'TOKEN=$(security find-generic-password -s "x" -w)\n'

    prose_code = "\n".join(executable_lines(prose_only))
    for banned in PORTED_LOGIC:
        assert banned not in prose_code, (
            f"{banned!r} in a *comment* must stay legal — a guard that rewrites "
            f"accurate documentation is a defect, not a fix"
        )

    assert "security find-generic-password" in "\n".join(executable_lines(real_code)), (
        "the predicate failed to see a live call — it would pass vacuously"
    )


def test_the_container_ban_discriminates_code_from_prose() -> None:
    """``docker run`` in a comment must stay legal; a live one must not.

    The wrapper's own comments explain *why* it no longer builds a container, so
    they necessarily say ``docker run``. A blanket substring search would delete
    the explanation of the change it is enforcing — and, worse, would then pass on
    a wrapper whose real invocation had crept back in under a comment.
    """
    prose_only = (
        "#!/usr/bin/env bash\n"
        "# The tail used to be a hand-rolled docker run; #307 replaced it with the\n"
        "# control-socket client, whose fallback spawns the identical container.\n"
        'exec python3 -m harness.hostenv.client "$(pwd)" -- "$@"\n'
    )
    real_code = prose_only + 'docker run --rm -v "$(pwd)":/workspace "$IMAGE" "$@"\n'

    assert not re.search(r"docker\s+run\b", "\n".join(executable_lines(prose_only))), (
        "a `docker run` in a *comment* must stay legal"
    )
    assert re.search(r"docker\s+run\b", "\n".join(executable_lines(real_code))), (
        "the predicate failed to see a live `docker run` — it would pass vacuously"
    )


def test_the_credential_ban_discriminates_code_from_prose() -> None:
    """Same control for the credential-name ban, which is the broader predicate."""
    prose_only = (
        "#!/usr/bin/env bash\n"
        "# LINEAR_API_KEY and GITHUB_TOKEN are resolved by the host providers and\n"
        "# handed to docker through the client's subprocess env=, not exported here.\n"
        'exec python3 -m harness.hostenv.client "$(pwd)" -- "$@"\n'
    )
    real_code = prose_only + 'export GITHUB_TOKEN="$(gh auth token)"\n'

    prose_code = "\n".join(executable_lines(prose_only))
    for name in CREDENTIAL_NAMES:
        assert name not in prose_code, (
            f"{name!r} in a *comment* must stay legal — the comment explaining the "
            f"rewire has to name what moved"
        )

    assert "GITHUB_TOKEN" in "\n".join(executable_lines(real_code)), (
        "the predicate failed to see a live export — it would pass vacuously"
    )


def test_continuation_folding_joins_a_split_command_and_nothing_else() -> None:
    """The helper the exec assertion depends on, exercised on synthetic source.

    Both directions matter: a continued command must become one line, and two
    genuinely separate commands must **not** be welded together — otherwise a
    predicate could match an ``exec`` on one line against a module name on a
    completely unrelated one.
    """
    split = 'exec env PYTHONPATH="x" \\\n  python3 -m harness.hostenv.client "$(pwd)" -- "$@"\n'
    separate = 'exec docker run "$IMAGE"\npython3 -m harness.hostenv.client\n'

    folded = logical_lines(split)
    assert len(folded) == 1, "a continued command must fold into one logical line"
    assert re.search(r"exec\s+.*-m\s+harness\.hostenv\.client", folded[0])

    assert len(logical_lines(separate)) == 2, "unrelated commands must stay separate"
    assert not re.search(
        r"exec\s+.*-m\s+harness\.hostenv\.client", logical_lines(separate)[0]
    ), "folding welded two unrelated commands into a false match"


def test_the_exec_assertion_would_notice_a_wrapper_that_never_rewired() -> None:
    """The positive predicate needs a floor too.

    A regex that matched anything would report success on the pre-#307 wrapper,
    which is exactly the state the finding described.
    """
    pre_rewire = 'exec docker run --rm -v "$(pwd)":/workspace "$IMAGE" "$@"\n'

    assert not re.search(r"exec\s+.*-m\s+harness\.hostenv\.client", pre_rewire), (
        "the exec predicate matches a wrapper that was never rewired"
    )


def test_the_line_ceiling_actually_counts_code() -> None:
    """The ratchet must not be satisfiable by commenting logic out.

    A ceiling that counted raw lines would be met by a file of pure comments, and a
    ceiling that counted nothing would be met by anything.
    """
    assert executable_lines("# just a comment\n\n   \n") == []
    assert len(executable_lines('echo one\n# comment\necho two\n')) == 2


def test_the_delegation_count_would_notice_a_second_call() -> None:
    """The exactly-once assertion is measuring, not asserting a constant."""
    two = 'python3 -m harness.hostenv env\npython3 -m harness.hostenv env\n'

    assert len(re.findall(r"-m\s+harness\.hostenv", two)) == 2


# ---------------------------------------------------------------------------
# #383 — no command the wrapper runs may hide behind a builtin's exit status.
#
# Here rather than in test_container_hardening.py, which owns the *image*:
# this scans the wrapper's own source for a shape that must not appear in it,
# which is exactly what every other guard in this module does, and it sits
# beside EXECUTABLE_LINE_CEILING — the other bound #383 had to argue with.
# ---------------------------------------------------------------------------


#: The builtins that declare a variable and therefore supply the *statement's*
#: exit status, hiding the substitution's. ``export`` is the one the wrapper hit,
#: but ``local`` is the commonest spelling of this defect and the wrapper is full
#: of it, so scanning for ``export`` alone would leave the likeliest next
#: occurrence to CI — which is precisely the reliance this guard exists to remove.
_DECLARING_BUILTINS = ("export", "readonly", "declare", "typeset", "local")

#: A declaring builtin whose value is a command substitution, in code rather than
#: in a comment. Matched per line via ``.match``, so the position anchor is the
#: start of each line and ``\s*`` is what tolerates indentation. That anchoring is
#: also the whole of the code/prose discrimination: a declaring builtin must be
#: the line's first word, so the wrapper's own comment beside the fixed line —
#: which quotes this pattern — cannot reach it.
#:
#: The value is scanned with ``(?:(?!\s#).)*`` rather than ``[^#]*``: the point is
#: to stop at a **trailing comment**, and a trailing comment is a ``#`` preceded by
#: whitespace. Excluding every ``#`` also stops at the one inside ``${BASE#prefix}``
#: and misses the substitution after it — a real spelling, and the miss is pinned
#: by a positive control rather than left to be discovered. Both substitution
#: spellings are covered because a rewrite reaching for backticks is the same
#: defect in older clothes.
_MASKING_DECLARATION = re.compile(
    r"\s*(?:" + "|".join(_DECLARING_BUILTINS) + r")"
    r"(?:\s+-[A-Za-z]+)*"
    r"\s+[A-Za-z_][A-Za-z0-9_]*=(?:(?!\s#).)*(?:\$\(|`)"
)


def _masking_declarations(script: str) -> list[str]:
    """Every line of ``script`` that declares a variable from a command it runs.

    There is deliberately no comment-stripping step. One was written and then
    removed as dead: :data:`_MASKING_DECLARATION` is applied with ``match``, so a
    declaring builtin must be the line's first word, and no comment line can
    reach the pattern at all. A skip that never changes an answer is not a
    safeguard — it is a claim about the predicate that the predicate does not
    need, and the next reader would maintain it as though it did.
    """
    return [
        line.strip() for line in script.splitlines() if _MASKING_DECLARATION.match(line)
    ]


def test_no_declaration_masks_the_status_of_the_command_it_runs() -> None:
    """AC-2: the wrapper never lets a declaring builtin swallow a failure (#383).

    ``export NAME="$(f)"`` is one command, and its exit status is **export's** —
    which does not carry the substitution's. Under the wrapper's ``set -euo
    pipefail`` a failing ``f`` therefore does not stop the script; it spawns a
    container with an empty value and no complaint. This is what SC2155 names,
    and the reason the fix is a real behaviour change rather than a lint
    appeasement. ``local``, ``readonly``, ``declare`` and ``typeset`` mask
    identically, and ``local`` is both the commonest spelling and the one the
    wrapper uses most, so the predicate covers all five rather than the one
    occurrence that prompted it.

    This guard backs up rather than duplicates
    ``tests/unit/test_container_hardening.py``'s
    ``test_wrapper_is_shellcheck_clean``, because that one is satisfiable by
    silencing it: a ``# shellcheck disable=SC2155`` above the line makes
    shellcheck exit 0 and changes nothing about the masking. This reads the code,
    so the only way to satisfy it is to separate the declaration from the
    assignment. It also runs where shellcheck is absent, which is every developer
    host here — the other half of why the defect went unobserved from #307 until
    #380, the first half being that ``verify.sh`` is ``set -euo pipefail`` with
    the docker stage first, so a red docker stage aborted before the stage
    carrying either guard ever ran on the runner. The two halves of one argument
    now sit in two modules; ``test_container_hardening.py`` owns the container's
    security boundary and this module owns the shim's shape, and shell
    correctness belongs cleanly to neither.
    """
    offenders = _masking_declarations(WRAPPER.read_text())

    assert not offenders, (
        "docker/harness-wrapper.sh declares a variable from a command it runs, so "
        "that command's failure is swallowed by the builtin's own exit status:\n  "
        + "\n  ".join(offenders)
        + "\nSplit it: `NAME=\"$(f)\"` on one line, `export NAME` on the next."
    )


def test_the_masking_predicate_discriminates_on_synthetic_source() -> None:
    """The oracle, proven against source written for it rather than trusted.

    A guard asserting the absence of a pattern passes just as green when its
    pattern matches nothing at all, so the positive cases are what stop this
    becoming a test that cannot fail. The ``shellcheck disable`` case is the one
    that matters most: it is precisely the shape that satisfies the linter while
    leaving the defect in place, and it must still be caught here.

    Each negative case names the piece of the predicate it exists to pin, so a
    later simplification that deletes one has something to fail against — an
    ``allowed`` entry no part of the pattern is responsible for is decoration.
    """
    caught = (
        'export HARNESS_WRAPPER_STATUS="$(_wrapper_status)"',
        "export FOO=$(date)",
        "  export INDENTED=\"$(uname)\"",
        "export LEGACY=`uname`",
        '# shellcheck disable=SC2155\nexport SILENCED="$(_wrapper_status)"',
        # The four spellings that mask identically. `local` is the one the
        # wrapper actually reaches for, which is why scanning `export` alone
        # would have left the likeliest next occurrence to CI.
        '  local VERSIONED="$(_wrapper_source_root)"',
        'readonly PINNED="$(uname)"',
        'declare -x DECLARED="$(uname)"',
        'typeset -x TYPESET="$(uname)"',
        # `[^#]*` must not stop at a `#` that is part of the value.
        'export TRIMMED="${BASE#prefix}$(uname)"',
    )
    allowed = (
        # The fix's own shape.
        'STATUS="$(_wrapper_status)"\nexport STATUS',
        # No substitution at all.
        'export LITERAL="harness"',
        "export PATH=/opt/git/bin:$PATH",
        # The `.match` anchor: a declaring builtin must be the line's first
        # word, so prose quoting the pattern is documentation rather than code —
        # which the wrapper's own comment beside the fixed line relies on.
        '# a comment about export FOO="$(bar)" is documentation, not code',
        # `[^#]*`: a trailing comment mentioning a substitution does not make the
        # assignment before it a masking one.
        'export LITERAL="harness"  # unlike $(uname), this is fixed',
        # The declaring builtin must be the first word: a substitution inside
        # some other command's arguments is not a masked declaration.
        '  echo "export INLINE=\\"$(f)\\"" > /tmp/generated',
        # A bare assignment is the correct form and must stay legal even for a
        # name that looks like a declaration keyword's.
        'local_value="$(uname)"',
    )

    for source in caught:
        assert _masking_declarations(source), (
            f"predicate missed a masking declaration: {source!r}"
        )
    for source in allowed:
        assert not _masking_declarations(source), (
            f"predicate condemned a legitimate line: {source!r}"
        )
