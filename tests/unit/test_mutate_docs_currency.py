"""#366 — `CONTRIBUTING.md`'s mutation section must describe the tool that exists.

`CONTRIBUTING.md` is the one place in the repo that documents
``scripts/mutate.py``, and #365 shipped the liveness fork without touching it.
The section went on presenting *an edit that changes no behaviour kills nothing*
as a sufficient signal — which is exactly the belief #365 was built to remove,
and the belief that cost #209 two re-derivations and let an adversarial review
prove a real BLOCKING finding with invalid evidence. So the one document a
contributor reads before writing a table taught the thing the tool had just been
changed to stop.

Nothing caught it because nothing bound the doc to the module. A doc acceptance
criterion needs a measuring test, and the measurement has to **derive** its
subject set: #365's own mistake was checking `specs/`, `skills/`, `commands/`
and `agents/` for stale claims — a list of where docs were assumed to live —
rather than deriving from the tree, and then reporting that as measured.

So every obligation here is derived from the module and nothing is hand-listed:

* the outcome vocabulary from :data:`mutate.OUTCOMES`, which
  ``EntryResult.__post_init__`` makes load-bearing rather than a second copy;
* the survivor labels from :func:`mutate._label` itself, run over real results;
* the table's keys from ``dataclasses.fields(mutate.Mutation)``, which is what
  puts ``observe`` in the doc under a predicate rather than as a word somebody
  remembered;
* the exit codes from :func:`mutate.exit_code`, called;
* the refusal stages from the module's own numbered list, cross-checked against
  every ``RefusalError`` call site so the module's two accounts of itself cannot
  drift from each other before either drifts from `CONTRIBUTING.md`.

Each derivation carries a floor (:func:`test_the_derivations_are_not_vacuous`).
A parametrized guard over a derived set goes **vacuous, not red**, when the
derivation dies, and the floor is the only thing that notices — see #168/#169.
"""

from __future__ import annotations

import ast
import dataclasses
import re
import sys
from pathlib import Path

import pytest

from tests._gitutil import tracked_files_under

_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT / "scripts"))

import mutate  # noqa: E402

_CONTRIBUTING = _REPO_ROOT / "CONTRIBUTING.md"
_CONTEXT = _REPO_ROOT / "CONTEXT.md"
_MODULE = _REPO_ROOT / "scripts" / "mutate.py"

#: The mutation bullet's lead line. A named literal, which is the *floor*, not
#: the subject set — the members checked inside the span are all derived.
_ANCHOR = "- **Prove a new guard by mutating what it guards.**"

#: The next top-level bullet ends the span.
_BULLET = re.compile(r"^- \*\*", re.MULTILINE)


def _span(text: str, anchor: str, end: re.Pattern[str]) -> str:
    """The region owning a claim — failing closed rather than widening.

    A guard that silently falls back to the whole file would be satisfied by the
    words appearing anywhere, which is the vacuous shape this module exists to
    avoid. So an anchor that is missing, or present twice, is an error here
    rather than a wider search.
    """
    occurrences = text.count(anchor)
    assert occurrences == 1, f"anchor must occur exactly once, found {occurrences}: {anchor!r}"
    start = text.index(anchor)
    rest = text[start + len(anchor) :]
    match = end.search(rest)
    section = anchor + (rest[: match.start()] if match else rest)
    assert section.strip(), "the extracted span is empty"
    assert len(section) < len(text), "the span is the whole file — it is not a span"
    return section


def _flat(text: str) -> str:
    """Collapse whitespace, so an 80-column wrap cannot break a match."""
    return re.sub(r"\s+", " ", text)


def _section() -> str:
    return _flat(_span(_CONTRIBUTING.read_text(encoding="utf-8"), _ANCHOR, _BULLET))


# ---------------------------------------------------------------------------
# AC-1 / AC-4 — the section names every outcome the module can report.
# ---------------------------------------------------------------------------


def test_the_section_names_every_outcome_the_module_can_report() -> None:
    """Derived from `mutate.OUTCOMES`, so a sixth outcome cannot ship documented-by-omission.

    This is the ticket's own defect mechanized: #365 added `inert` and left the
    section describing a four-outcome tool.
    """
    section = _section()

    missing = [outcome for outcome in mutate.OUTCOMES if f"`{outcome}`" not in section]

    assert not missing, f"CONTRIBUTING's mutation section does not name {missing}"


# ---------------------------------------------------------------------------
# AC-1 — the rest of the vocabulary, each derived from the thing it describes.
# ---------------------------------------------------------------------------


def _labels() -> set[str]:
    """Both rendered survivor labels, from `_label` itself rather than retyped."""
    return {
        mutate._label(_result(observe=observe))
        for observe in ((), ("-c", "print(1)"))
    }


def _result(*, outcome: str = "survived", observe: tuple[str, ...] = ()) -> mutate.EntryResult:
    return mutate.EntryResult(
        mutation=mutate.Mutation(
            id="e", file="f.py", old="a", new="b", kills=frozenset({"t::t"}), observe=observe
        ),
        outcome=outcome,
        observed=frozenset(),
        missing=frozenset(),
        unexpected=frozenset(),
        collected=1,
        duration_s=0.1,
    )


def test_the_section_names_both_rendered_survivor_labels() -> None:
    """`SURVIVED (LIVE)` / `SURVIVED (UNPROVEN)` are what a reader actually sees.

    Derived by calling `_label`, so a change to how a survivor is printed makes
    the doc stale here rather than in someone's memory.
    """
    section = _section()

    missing = [label for label in sorted(_labels()) if label not in section]

    assert not missing, f"the section does not carry the rendered label(s) {missing}"


def test_the_section_names_every_field_of_a_table_entry() -> None:
    """Derived from `Mutation`'s fields — which is what puts `observe` under a
    predicate rather than leaving it as a word somebody remembered to add."""
    section = _section()
    fields = [f.name for f in dataclasses.fields(mutate.Mutation)]

    missing = [name for name in fields if f"`{name}`" not in section]

    assert not missing, f"the section does not name the table key(s) {missing}"


def _exit_codes() -> set[int]:
    """Every code `exit_code` can return, by calling it once per outcome."""
    return {
        mutate.exit_code(
            mutate.Report(
                baseline=mutate.Baseline(passed=frozenset(), collected=1, duration_s=0.1),
                results=(_result(outcome=outcome),),
                work_dir=Path("/tmp"),
                select=(),
            )
        )
        for outcome in mutate.OUTCOMES
    }


def test_the_section_names_every_exit_code_and_that_four_dominates_one() -> None:
    section = _section()

    missing = [str(code) for code in sorted(_exit_codes()) if f"`{code}`" not in section]

    assert not missing, f"the section does not name exit code(s) {missing}"
    assert re.search(r"`4` dominates `1`", section), (
        "the section must say that 4 dominates 1 — the two mean different work, "
        "and a reader who treats them alike is back to #209's position"
    )


def test_the_section_no_longer_calls_killing_nothing_self_evident() -> None:
    """The negative pin on the retired claim (#365 changed what it asserted).

    Anchored on the *discriminating* clause, not on the word "kills": the
    section legitimately still discusses killing nothing — it now says that is
    ambiguous rather than self-evident.
    """
    section = _section()

    assert "changes no behaviour kills nothing" not in section, (
        "the retired claim is back: killing nothing was presented as a sufficient "
        "signal, which is the belief #365 removed and #209 paid for"
    )
    assert re.search(r"not\*{0,2}\s+by itself|\*\*not\*\* by itself", section), (
        "the section must say that killing nothing is not by itself evidence"
    )


# ---------------------------------------------------------------------------
# AC-2 — the refusal stages, and the module's two accounts of them agreeing.
# ---------------------------------------------------------------------------


def _documented_stages() -> list[str]:
    """The ordered stage list, from the module docstring's own numbered list."""
    doc = mutate.__doc__ or ""
    block = _span(
        doc,
        "Every refusal happens **before any file is written**",
        re.compile(r"^\w+ a survivor", re.MULTILINE),
    )
    return [name.lower() for name in re.findall(r"^\d+\. \*\*(\w+)\*\*", block, re.MULTILINE)]


def _raised_reasons() -> set[str]:
    """Every `reason` a `RefusalError` is constructed with, read from the AST."""
    tree = ast.parse(_MODULE.read_text(encoding="utf-8"))
    return {
        node.args[0].value
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "RefusalError"
        and node.args
        and isinstance(node.args[0], ast.Constant)
        and isinstance(node.args[0].value, str)
    }


def test_the_modules_two_accounts_of_its_refusals_agree() -> None:
    """The docstring's numbered list vs. what the code actually raises.

    Checked before either is compared to `CONTRIBUTING.md`, so an in-module
    drift is named as such instead of surfacing as a documentation failure.
    """
    assert set(_documented_stages()) == _raised_reasons(), (
        f"docstring lists {sorted(_documented_stages())}, code raises "
        f"{sorted(_raised_reasons())}"
    )


def test_the_section_names_every_refusal_stage_in_the_order_applied() -> None:
    """Order is the claim, not just vocabulary — `observable` runs *after*
    `prediction` so a mistyped node id is never paid for at observable prices.

    Matched on the bold form, because the section legitimately uses "table" and
    "baseline" as ordinary words elsewhere and bare matching would let an
    ordering check pass by accident.
    """
    section = _section()
    stages = _documented_stages()

    missing = [stage for stage in stages if f"**{stage}**" not in section]
    assert not missing, f"the section does not name refusal stage(s) {missing}"

    positions = [section.index(f"**{stage}**") for stage in stages]
    assert positions == sorted(positions), (
        f"the section lists the stages in a different order than the module "
        f"applies them ({stages})"
    )


# ---------------------------------------------------------------------------
# AC-3 — CONTEXT.md routes a reader to the instrument.
# ---------------------------------------------------------------------------


def test_context_routes_a_reader_to_the_mutation_harness() -> None:
    """`CLAUDE.md` sends every session to `CONTEXT.md` first, so this is the
    entry point a session without prior knowledge actually reaches.

    Before #366 the only route was an operator-local memory file, which does not
    exist for a fresh session or for anyone else.
    """
    section = _flat(
        _span(
            _CONTEXT.read_text(encoding="utf-8"),
            "## Where deeper truth lives",
            re.compile(r"^## ", re.MULTILINE),
        )
    )

    assert "scripts/mutate.py" in section, (
        "CONTEXT.md's 'Where deeper truth lives' must route to the mutation harness"
    )
    assert "CONTRIBUTING.md" in section, "and to the section that explains how to drive it"


@pytest.mark.parametrize("relpath", ["scripts/mutate.py", "CONTRIBUTING.md"])
def test_every_path_the_route_names_exists_in_the_tracked_tree(relpath: str) -> None:
    """A route to a file that does not exist is not a route.

    Tracked rather than on-disk: a path that resolves only in the author's
    working copy is not published to anyone (the git-aware-guard principle).
    """
    tracked = tracked_files_under(relpath, repo_root=_REPO_ROOT)

    assert tracked, f"{relpath} is named as a route but is not tracked by git"


# ---------------------------------------------------------------------------
# AC-5 — the floor. Every derivation above can collapse silently.
# ---------------------------------------------------------------------------


def test_the_derivations_are_not_vacuous() -> None:
    """A parametrized or comprehension-driven check over an empty derived set
    passes over nothing, with no skip and no warning (#168/#169).

    Named anchors are the floor, not the subject set: the guards above derive
    their members, and these assertions are what make a collapsed derivation go
    red instead of green.
    """
    assert mutate.OUTCOMES, "the outcome vocabulary derived to nothing"
    assert {"killed", "inert"} <= set(mutate.OUTCOMES), mutate.OUTCOMES

    stages = _documented_stages()
    assert stages, "the refusal-stage list derived to nothing"
    assert "observable" in stages, stages

    fields = {f.name for f in dataclasses.fields(mutate.Mutation)}
    assert "observe" in fields, fields

    assert _exit_codes(), "the exit-code set derived to nothing"
    assert 4 in _exit_codes(), _exit_codes()

    labels = _labels()
    assert len(labels) == 2, f"both survivor labels must be distinct: {labels}"

    assert _raised_reasons(), "no RefusalError call sites were found"


def test_the_span_extractor_fails_closed() -> None:
    """The helper every guard above depends on, proven to refuse rather than widen.

    Without this, an anchor that stopped matching would make each check read the
    whole file — and every one of them would pass for the wrong reason.
    """
    text = "- **A.** one\n- **B.** two\n"

    with pytest.raises(AssertionError, match="exactly once"):
        _span(text, "- **missing.**", _BULLET)

    with pytest.raises(AssertionError, match="exactly once"):
        _span("x\nx\n", "x", _BULLET)

    # The widening case, and the reason it is spelled out separately: when the
    # anchor opens the file and nothing ends it, the "span" *is* the file, and
    # every check built on it would then be satisfied by a match anywhere in the
    # document. Mutation-found — the `<` below was unprotected until this case
    # existed, and `<=` passed the whole suite.
    whole = "- **A.** only"
    with pytest.raises(AssertionError, match="whole file"):
        _span(whole, whole, _BULLET)

    assert _span(text, "- **A.**", _BULLET).strip() == "- **A.** one"
