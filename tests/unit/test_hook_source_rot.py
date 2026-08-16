"""#457 AC-6 — two rot classes the hook sources kept re-growing, closed structurally.

Both are negative-space assertions over the shipped sources (ADR 0016): what the
text must **not** contain, never what it must say. Neither reads meaning, and
neither can be satisfied by rewording.

**A count of the hooks, written into the hooks.** Five of the seven carried a
comment beginning "the other four hooks" or "all five hooks" — true when written,
false from the moment the bundle grew, and the comment that told a reader how
many hooks existed was the least reliable place to learn it. The remedy is not a
corrected number: a correct count rots on the next hook exactly as the last one
did, and pinning it in a test is the cardinality floor ``craft.md`` warns about
under *Floors decay into decoration*. So the rule is that a hook does not state
how many hooks there are at all — "every other hook" carries the same meaning and
cannot go stale.

**Advisory state named without a scope.** The debounce and threshold files live
in ``os.tmpdir()``, which is machine-global: a fixed filename means two sessions
in two checkouts share one marker and silence each other. Each affected hook has
a behavioural test for its own state (``test_workflow_guard_hook``,
``test_context_monitor_hook``, ``test_guidance_freshness_hook``); what those
cannot do is fail for the *next* state file somebody adds. This one does — a
literal filename joined onto the temp directory is refused wherever it appears.

Each detector is exercised on synthetic source
(:func:`test_the_count_detector_reads_a_source_it_is_given`,
:func:`test_the_scope_detector_reads_a_source_it_is_given`) so a detector
degraded to "finds nothing" fails there rather than reading as a clean sweep, and
each sweep is floored on a live subject so it cannot pass over an empty corpus.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tests._gitutil import tracked_files_under  # noqa: E402

#: A *totalising* count of the hooks: a determiner covering the whole bundle,
#: then a number, then the noun. Number words and digits both, because the rot
#: arrived as "all five hooks" and would return as "all 7 hooks".
#:
#: The determiner is what makes this a rule rather than a ban on arithmetic. A
#: comment may still say "crashing this one hook alone" or "the two hooks answer
#: the same question", because neither claims to describe the bundle and neither
#: goes stale when the bundle grows — only a claim about *all* of them does.
#:
#: It is a floor against the family that has actually recurred here, not a proof
#: that no count can be phrased past it: "there are seven hooks" is spelled with
#: a determiner this alternation carries, but a determined author has other
#: sentences available. Widening a blacklist has no completion condition
#: (``craft.md`` → *A paraphrase tuple drawn from the sweep's own alternation
#: measures itself*), so whether a comment's phrasing is genuinely countless
#: stays the reviewer's judgment; this closes the wordings that were shipped.
_HOOK_COUNT = re.compile(
    r"\b(?:all|each of|every one of|the other|there are)\s+(?:the\s+)?"
    r"(?:one|two|three|four|five|six|seven|eight|nine|ten|\d+)\s+hooks?\b",
    re.IGNORECASE,
)

#: A temp-directory path built from a string literal — the unscoped form. The
#: scoped helper interpolates a digest of the working directory, so it reaches
#: ``path.join`` as a template literal and never as a quote.
_UNSCOPED_STATE = re.compile(r"os\.tmpdir\(\)\s*,\s*[\"']")

#: The call every hook that keeps state makes. Floors the sweep above: with no
#: hook using the temp directory at all there is nothing for it to be right
#: about (``craft.md`` → *The empty comparison set*).
_TMPDIR_USE = "os.tmpdir()"


def _hook_sources() -> dict[str, str]:
    """Every tracked hook's source, keyed by filename.

    From the git index, so an untracked scratch copy of a hook cannot make the
    sweep red and a deleted one cannot keep it green.
    """
    return {
        path.name: path.read_text(encoding="utf-8")
        for path in tracked_files_under("hooks")
        if path.suffix == ".js"
    }


def _counts_the_hooks(sources: dict[str, str]) -> dict[str, list[str]]:
    return {
        name: found for name, text in sources.items() if (found := _HOOK_COUNT.findall(text))
    }


def _names_state_without_scope(sources: dict[str, str]) -> list[str]:
    return sorted(name for name, text in sources.items() if _UNSCOPED_STATE.search(text))


# --- the detectors can fire ---------------------------------------------------


def test_the_count_detector_reads_a_source_it_is_given() -> None:
    """Positive control, fed the pre-fix wording verbatim.

    Also fed the three shapes that must survive it, because a rule an author
    cannot comply with gets deleted rather than followed: the countless
    replacement, a count of something that is not hooks, and a count bound to a
    *named* group rather than to the bundle — the last of which is the boundary
    the determiner draws, and the one a bare "``N`` hooks" ban would flatten.
    """
    flagged = _counts_the_hooks(
        {
            "stale.js": "// All five hooks wrap main() the same way.\n",
            "digits.js": "// See the identical helper in the other 6 hooks.\n",
            "fine.js": "// See the identical helper in every other hook.\n",
            "unrelated.js": "// Two branches are protected by default.\n",
            "specific.js": "// crashing this one hook alone, not the session.\n",
        }
    )

    assert sorted(flagged) == ["digits.js", "stale.js"], (
        f"the detector must flag a spelled-out and a numeric count of the whole "
        f"bundle, and none of: a countless phrasing, a count of something else, "
        f"or a count bound to a named group; got {flagged}"
    )


def test_the_scope_detector_reads_a_source_it_is_given() -> None:
    """Positive control: the literal form is caught, the scoped form is not."""
    unscoped = _names_state_without_scope(
        {
            "stale.js": 'const D = path.join(os.tmpdir(), "guidance-thing-warned");\n',
            "scoped.js": "const D = path.join(os.tmpdir(), `guidance-thing-${key}`);\n",
        }
    )

    assert unscoped == ["stale.js"], (
        f"the detector must separate a literal temp-directory filename from one "
        f"interpolating a per-repository key; got {unscoped}"
    )


# --- the sweeps run over a live corpus ----------------------------------------


def test_the_hook_corpus_this_module_reads_is_live() -> None:
    """Floor: both sweeps have subjects, and the second has a subject that
    actually keeps state — otherwise it is right about nothing."""
    sources = _hook_sources()
    keepers = sorted(name for name, text in sources.items() if _TMPDIR_USE in text)

    assert "workflow-guard.js" in sources, (
        f"the tracked hook corpus lost its anchor; got {sorted(sources)}"
    )
    assert keepers, (
        "no hook keeps state in the temp directory any more, so the unscoped-state "
        "sweep passes over nothing. If that is deliberate, retire the sweep in the "
        "same change rather than leaving it as decoration."
    )


# --- the sweeps ---------------------------------------------------------------


def test_no_hook_states_how_many_hooks_there_are() -> None:
    """A count in a comment is a fact about the bundle, kept in the worst place.

    Correcting the number is not the fix — the corrected number rots on the next
    hook, and a test pinning it rots with it. A hook says "every other hook" and
    stays true.
    """
    flagged = _counts_the_hooks(_hook_sources())

    assert not flagged, (
        f"hook sources stating how many hooks exist: {dict(sorted(flagged.items()))}. "
        "Write the claim without a number — the count changes and the comment does not."
    )


def test_no_hook_keeps_machine_global_state_under_a_fixed_name() -> None:
    """State in ``os.tmpdir()`` is shared by every session on the machine.

    A fixed filename therefore makes one session's debounce another session's
    silence, in a repository it has never seen. The scope suffix is what turns
    machine-global state into per-repository state.
    """
    unscoped = _names_state_without_scope(_hook_sources())

    assert not unscoped, (
        f"hooks joining a literal filename onto the temp directory: {unscoped}. "
        "Build the path through the hook's scopedState helper so two checkouts "
        "cannot share one marker."
    )
