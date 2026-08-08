"""AC-2: the wrapper delegates the ported logic rather than duplicating it (#305).

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
#: bound, logic creeps back in under a different spelling one line at a time. Only
#: ever re-baselined *downward* — raising it is the drift this guard exists to stop.
#: Re-baselined 165 → 123 by #307, which removed the env-import block and the
#: hand-rolled ``docker run`` (158 → 116 lines) and then spent 7 of that back on
#: the interpreter/import preflight — the wrapper cannot degrade past a missing
#: client any more, so it must fail with the remedy instead of an import traceback
#: (:func:`test_an_interpreter_that_cannot_import_the_client_fails_with_the_remedy`).
#:
#: Raised 123 → 124 by #383, the **first** upward move and the one shape that
#: warrants one: the added line is `export HARNESS_WRAPPER_STATUS` split off from
#: its own assignment, so it carries no logic at all — it is one statement written
#: as two commands, because the single-command form takes *export's* exit status
#: and silently swallowed a failing `_wrapper_status` under `set -e`. What this
#: ratchet exists to stop is ported logic creeping back "one line at a time under
#: a different spelling"; a correctness fix that adds a line of pure formatting is
#: the case where the proxy and the property it stands for come apart, and
#: contorting the fix onto one line with a `;` to keep the number would be
#: optimising the measure over the thing measured. The rule is otherwise
#: unchanged, and this is not licence for the next raise: anything that adds a
#: *branch, a command, or a value* belongs in `harness.hostenv`, which is tested.
EXECUTABLE_LINE_CEILING = 124


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

    sync_block = code[code.index("_sync_source_checkout()") : code.index("_wrapper_status()")]
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
