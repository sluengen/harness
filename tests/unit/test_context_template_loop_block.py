"""The three loop knobs carry one value in three places, and the prose says so — #291.

``harness/loop_budget.py`` reads three integers out of a ``loop:`` block:
``max_review_cycles``, ``wall_clock_budget_minutes`` and
``engine_timeout_seconds``. Each has a code-level constant used when the key —
or the whole ``CONTEXT.md`` — is absent, so each value exists in three places:
the constant, this repo's own ``CONTEXT.md``, and the block a bootstrapped repo
receives in ``templates/CONTEXT.template.md``.

Two of those three places were unguarded. The template shipped **no** ``loop:``
block at all, so every bootstrapped repo ran on the constants with nowhere to
see or set them — while ``harness/cli/design.py`` told a repo that just lost a
design run to *"raise ``engine_timeout_seconds`` in CONTEXT.md's ``loop:``
block"*, remediation naming a block their ``CONTEXT.md`` did not have. And the
``engine_timeout_seconds`` retune (600 → 720) moved this repo's configured value
without moving the constant, so the unconfigured path silently ran a different
ceiling from the configured one.

These guards pin all three places against **the constants**, which are the
source: ``load_loop_budget`` never reads the template (an installed repo has no
template), so the template and ``CONTEXT.md`` are copies that must not drift.
The knob table is *derived* rather than restated — the constant's name is
``DEFAULT_`` + the key upper-cased — so a fourth knob added to ``LoopBudget`` is
covered here the day it is added rather than the day someone remembers to
extend a list.

The parse is single-sourced too: :data:`harness.loop_budget._KEY_PATTERN` is the
runtime reader's own regex, imported rather than recopied, so a guard cannot
pass against a pattern the engine does not use.
"""

from __future__ import annotations

import re
from pathlib import Path

from harness import loop_budget
from harness.loop_budget import load_loop_budget
from tests.unit.test_review_discipline_watchlist_entry_currency import _sentences

_REPO_ROOT = Path(__file__).resolve().parents[2]
_TEMPLATE = _REPO_ROOT / "templates" / "CONTEXT.template.md"
_CONTEXT = _REPO_ROOT / "CONTEXT.md"

# The knobs `LoopBudget` carries, in field order. The matching constant is
# derived from the key, never written out beside it (see the module docstring).
_KEYS = ("max_review_cycles", "wall_clock_budget_minutes", "engine_timeout_seconds")

_IDENTIFIER = re.compile(r"DEFAULT_[A-Z_]+")

# Phrases that assert two numbers are deliberately *held apart*. Applied only to
# a sentence already proven to be describing an equality, so the marker set does
# not have to distinguish a true divergence claim from a false one — by the time
# it is consulted, any divergence claim is false.
_DIVERGENCE_MARKERS = (
    "not applied",
    "unlike",
    "differs",
    "diverges",
    "held apart",
    "rather than",
)


def _constant(key: str) -> int:
    """The code-level fallback for ``key`` — derived from the key's own name."""
    return int(getattr(loop_budget, f"DEFAULT_{key.upper()}"))


def _configured(text: str, key: str) -> int | None:
    """The value ``key`` is set to, read with the runtime reader's own pattern.

    ``None`` when the key is absent or does not parse as a bare integer — which
    is exactly when :func:`load_loop_budget` falls back to the constant, so the
    distinction "set to 720" versus "absent and defaulting to 720" is
    recoverable here even though the loaded budget cannot tell them apart.
    """
    match = re.search(
        loop_budget._KEY_PATTERN.format(key=re.escape(key)), text, re.MULTILINE
    )
    return int(match.group(1)) if match else None


def _comment(text: str, key: str) -> str:
    """The inline ``#`` comment on ``key``'s line — the prose about that knob."""
    match = re.search(rf"^\s*{re.escape(key)}:[^\n]*$", text, re.MULTILINE)
    assert match is not None, f"{key} must appear in the file under test"
    _, _, comment = match.group(0).partition("#")
    return comment.strip()


# --- AC-2: the template ships the block ---------------------------------------


def test_template_declares_every_loop_key() -> None:
    """The bootstrap template carries all three knobs as bare integers (AC-2).

    Presence is asserted *directly* rather than through
    :func:`load_loop_budget`, because a missing key falls back to its constant —
    so a loaded budget that reads ``(6, 110, 720)`` proves nothing about whether
    the template says anything at all.
    :func:`test_the_parse_finds_nothing_when_the_block_is_missing` is the
    negative control that pins that reasoning.
    """
    text = _TEMPLATE.read_text(encoding="utf-8")

    missing = [key for key in _KEYS if _configured(text, key) is None]
    assert not missing, (
        f"templates/CONTEXT.template.md must declare {sorted(missing)} in its "
        "`loop:` block as bare integers. A repo bootstrapped from the template "
        "otherwise has no place to set the knobs, and `harness design`'s "
        "engine_timeout remediation names a block it does not have."
    )


def test_template_values_match_the_constants() -> None:
    """Every value shipped in the template equals its code constant (AC-3).

    This is the anti-drift half: a future retune that moves a constant without
    moving the template hands every bootstrapped repo a block that *looks*
    configured while describing a budget the harness no longer runs.
    """
    text = _TEMPLATE.read_text(encoding="utf-8")

    for key in _KEYS:
        assert _configured(text, key) == _constant(key), (
            f"templates/CONTEXT.template.md sets `{key}` to "
            f"{_configured(text, key)} but harness/loop_budget.py's "
            f"DEFAULT_{key.upper()} is {_constant(key)}. Move them together."
        )


def test_template_parses_with_the_runtime_reader(tmp_path: Path) -> None:
    """The shipped block is readable *in situ*, not merely present (AC-2/AC-3).

    Copying the template verbatim to a repo's ``CONTEXT.md`` is what a bootstrap
    does, so this feeds the whole file to the **real loader** rather than to
    :func:`_configured`'s re-application of its regex. That is what makes it a
    distinct measure: ``_configured`` only proves the pattern matches somewhere,
    while ``load_loop_budget`` also wires each key name to a ``LoopBudget``
    field. Mutating the loader to read ``engine_timeout_seconds`` from the
    ``max_review_cycles`` key kills this test and
    :func:`test_shipped_context_matches_the_constants` while every pattern-based
    test above stays green — a mis-wiring only the loader can show.
    """
    (tmp_path / "CONTEXT.md").write_text(
        _TEMPLATE.read_text(encoding="utf-8"), encoding="utf-8"
    )

    budget = load_loop_budget(tmp_path)

    assert budget == loop_budget.LoopBudget(*(_constant(key) for key in _KEYS))


def test_the_parse_finds_nothing_when_the_block_is_missing(tmp_path: Path) -> None:
    """Negative control — the three tests above cannot pass off the fallback.

    Strip the knobs from the template and two things must hold: the direct parse
    finds nothing (so the presence check is a real measure), while
    :func:`load_loop_budget` still returns the very same numbers the tests above
    assert (so a check written only through the loader would be satisfied by a
    template that says nothing). That gap is the whole reason the presence and
    the in-situ checks are separate tests.
    """
    text = _TEMPLATE.read_text(encoding="utf-8")
    for key in _KEYS:
        text = re.sub(
            loop_budget._KEY_PATTERN.format(key=re.escape(key)),
            "",
            text,
            flags=re.MULTILINE,
        )
    (tmp_path / "CONTEXT.md").write_text(text, encoding="utf-8")

    assert [_configured(text, key) for key in _KEYS] == [None, None, None]
    assert load_loop_budget(tmp_path) == loop_budget.LoopBudget(
        *(_constant(key) for key in _KEYS)
    )


# --- AC-1 / AC-4: this repo's own CONTEXT.md ----------------------------------


def test_shipped_context_matches_the_constants() -> None:
    """This repo configures exactly what an unconfigured repo falls back to (AC-1).

    Generalises ``test_shipped_context_configures_the_same_value_the_code_defaults_to``
    (``tests/unit/test_cli_reclaim.py``, #260) from the wall clock to all three
    knobs. Where the two diverge, this repo's ledger evidence — the only evidence
    there is — has been used to tune a value that no consuming repo receives.
    """
    budget = load_loop_budget(_REPO_ROOT)

    assert budget == loop_budget.LoopBudget(*(_constant(key) for key in _KEYS))


def test_context_prose_asserts_no_divergence_that_does_not_exist() -> None:
    """A knob's comment may not deny an equality the same line establishes (AC-4).

    Two steps, and both are needed. First the relation is **derived**: every
    ``DEFAULT_*`` identifier a knob's comment names must resolve in
    ``harness.loop_budget`` and must equal the value configured on that same
    line. Only then — knowing the measured relation *is* equality — is the
    sentence naming that identifier required to carry no divergence marker.

    Step one alone goes green the moment the constant is flipped, without the
    comment being touched at all, so it cannot stand for AC-4's requirement that
    the *correction* be measured. Step two alone is a phrase pin that a reword
    slips past. Together they derive the claim from the numbers and then require
    the prose not to contradict it.

    Honest residual: a false claim phrased without any of the markers still
    passes. This covers the class the ticket names — an explicit "held apart"
    assertion beside numbers that are equal — not all possible false prose.
    """
    text = _CONTEXT.read_text(encoding="utf-8")

    named_anywhere = 0
    for key in _KEYS:
        comment = _comment(text, key)
        configured = _configured(text, key)
        for identifier in _IDENTIFIER.findall(comment):
            named_anywhere += 1
            assert hasattr(loop_budget, identifier), (
                f"CONTEXT.md's `{key}` comment names {identifier}, which no "
                "longer exists in harness/loop_budget.py — prose that names "
                "code is checked against the code."
            )
            assert getattr(loop_budget, identifier) == configured, (
                f"CONTEXT.md sets `{key}` to {configured} while the "
                f"{identifier} it names is {getattr(loop_budget, identifier)}."
            )
            for sentence in _sentences(comment):
                if identifier not in sentence:
                    continue
                lowered = sentence.lower()
                marker = next(
                    (m for m in _DIVERGENCE_MARKERS if m in lowered), None
                )
                assert marker is None, (
                    f"CONTEXT.md's `{key}` comment says {marker!r} about "
                    f"{identifier}, but that constant and the configured value "
                    f"are both {configured}. The sentence asserts a divergence "
                    "that does not exist."
                )

    assert named_anywhere, (
        "no `loop:` comment names its DEFAULT_* constant, so this guard "
        "measured nothing. The engine-timeout comment in particular must state "
        "the lockstep it now keeps, naming the constant it keeps step with."
    )


# --- the nesting the retune must not invert -----------------------------------


def test_the_engine_ceiling_nests_inside_the_wall_clock() -> None:
    """A per-subprocess ceiling only means something inside a larger per-run one.

    Pins the *ordering*, not the numbers, in the spirit of
    ``tests/unit/test_timeout_budgets_coherent.py``: either knob may be retuned
    as long as a single engine invocation still cannot outlast the run budget
    that encloses it.
    """
    assert (
        loop_budget.DEFAULT_ENGINE_TIMEOUT_SECONDS
        < loop_budget.DEFAULT_WALL_CLOCK_BUDGET_MINUTES * 60
    )
