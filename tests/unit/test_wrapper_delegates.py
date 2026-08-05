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

import re
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

#: A may-not-grow ratchet on the shim. The removed blocks were ~60 lines; without a
#: bound, logic creeps back in under a different spelling one line at a time. Only
#: ever re-baselined *downward* — raising it is the drift this guard exists to stop.
EXECUTABLE_LINE_CEILING = 165


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


def test_the_wrapper_never_evals_the_helper_output() -> None:
    """The helper's output carries credentials; ``eval`` would let one execute.

    A token containing ``;`` or ``$(...)`` must reach the container as bytes, not
    as something the shell re-parses.
    """
    code = _wrapper_code()

    assert not re.search(r"\beval\b", code), "the wrapper must not eval anything"
    assert 'export "${_kv?}"' in code or 'export "$_kv"' in code, (
        "the env import must use `export \"$KEY=value\"`, not eval"
    )


def test_the_helper_output_is_read_nul_delimited() -> None:
    """A credential may legitimately contain a newline.

    Read line-wise, such a token splits into two records and the second is exported
    as whatever it happens to spell.
    """
    assert "read -r -d ''" in _wrapper_code(), (
        "the env import must read NUL-terminated records (`read -r -d ''`)"
    )


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
