"""#456 AC-3 / AC-4 — two lifecycle rules, one home each, no inline copies.

Both halves are the same defect in two places: a rule whose *copies* said more
than its named owner did.

* **AC-3 — the base-drift reconciliation bound.** ``commands/build.md`` and
  ``commands/routine.md`` both cited ``commands/ship.md`` as the rule's home
  and then stated a two-attempt cap the home did not carry. A reader who
  followed the pointer found no bound at all. The bound moves to ship.md and
  the copies shrink to a pointer plus the consequence.
* **AC-4 — the provider query shape.** ``commands/decision.md`` embedded
  literal ``gh issue list … --json …`` and a Linear filter shape behind a
  "this is a read, not a lifecycle mutation" carve-out, while
  ``commands/digest.md`` and ``skills/tracker/SKILL.md`` said the opposite: the
  provider skills own the query recipes, invent no query shape.

**No exemption token anywhere, by construction.** The query sweep's corpus is
``commands/`` — tracked, derived from the git index — and the provider skills
that legitimately carry recipes are outside it because they live under
``skills/``, not because a list here excuses them. An exemption inside a
zero-membership sweep turns the sweep into opt-out prose, which has cost this
repo two tickets already; the fix each time was to make the exclusion follow
from the subject. It does here.

The bound sweep is scoped the same way: the subject set is *every* base-drift
paragraph in registered prose, so a fourth file restating the cap is in scope
the day it lands rather than the day someone remembers to add it.

What neither half proves: that the bound is the right number, that ship.md's
statement of it is clear, or that decision.md's replacement pointers resolve to
useful recipes. Those are meaning (ADR 0016), and the review gate owns them.
"""

from __future__ import annotations

import re
from pathlib import Path

from tests._gitutil import tracked_files_under
from tests.unit.test_distributed_prose_no_repo_ids import _registered_prose_files

# ``tests/unit/test_*.py`` → ``parents[2]`` is the repo (or worktree) root.
_REPO_ROOT = Path(__file__).resolve().parents[2]

# --- AC-3 -----------------------------------------------------------------

#: The rule's home.
_BOUND_HOME = "commands/ship.md"

#: What makes a paragraph the base-drift rule's: it names the rule. Keying on
#: the rule's own name is what makes the selection positional rather than a
#: line number that drifts on the next edit.
_BASE_DRIFT = re.compile(r"base.drift", re.IGNORECASE)

#: A retry-count bound, with the number **bound to the thing it counts**. A bare
#: ``two`` is not a bound: ``commands/ship.md``'s own base-drift paragraph ends
#: "naming the two behaviours in tension", and a predicate that read that as the
#: cap would report the home compliant while measuring an unrelated noun — the
#: constant-comparison shape, reached through a window that is too wide rather
#: than through mismatched frames.
_ATTEMPT_BOUND = re.compile(
    r"\b(?:twice|two)\b(?:\W+\w+){0,3}?\W+(?:attempts?|tr(?:y|ies)|reconcil\w*)"
    r"|(?:attempt|reconcil\w*|retr(?:y|ies|ying))\w*(?:\W+\w+){0,3}?\W+(?:twice|two)\b",
    re.IGNORECASE,
)


def _rel(path: Path) -> str:
    return path.relative_to(_REPO_ROOT).as_posix()


def _paragraphs(text: str) -> list[str]:
    return [block.strip() for block in text.split("\n\n") if block.strip()]


def _base_drift_paragraphs() -> dict[str, list[str]]:
    """``{relpath: [paragraph, …]}`` for every registered file naming the rule."""
    found: dict[str, list[str]] = {}
    for path in _registered_prose_files():
        hits = [p for p in _paragraphs(path.read_text(encoding="utf-8")) if _BASE_DRIFT.search(p)]
        if hits:
            found[_rel(path)] = hits
    return found


def test_the_base_drift_subject_set_is_live() -> None:
    """Floor: the rule's home and both former copies are all in the subject set.

    Anchored by name rather than counted. A count would rot the day a fourth
    surface points at the rule; an empty or shrunken set is the failure this
    guards against, because the absence sweep below passes over nothing exactly
    as convincingly as it passes over compliant prose.
    """
    found = _base_drift_paragraphs()
    assert found, "no registered prose names the base-drift rule at all (#456)"
    for rel in (_BOUND_HOME, "commands/build.md", "commands/routine.md"):
        assert rel in found, (
            f"{rel} no longer names the base-drift rule. The home and its two "
            "pointers are what this guard measures; if the rule moved, re-point "
            "this module rather than assuming the bound is gone (#456)"
        )


def test_the_bound_predicate_binds_its_number_to_what_it_counts() -> None:
    """Controls: the real wordings are caught, the real near-miss is admitted.

    The positives are the pre-#456 sentences out of ``commands/build.md`` and
    ``commands/routine.md`` — the copies this ticket removed — plus the home's
    new spelling. The negative is the real sentence sitting in the *same
    paragraph* as the home's bound: a wider window would read it as the bound
    and report every file compliant while measuring a noun about design
    conflicts.
    """
    caught = (
        "After two failed attempts — or on a genuine functional conflict,",
        "(a genuine functional conflict, or reconciliation fails twice), the gate",
        "Reconciliation is bounded here, and this is the bound's only home: two attempts.",
        "retry it twice, then hold the ticket",
    )
    for sample in caught:
        assert _ATTEMPT_BOUND.search(sample), (
            f"the predicate no longer reads a retry bound: {sample!r}"
        )

    admitted = (
        "with a comment naming the two behaviours in tension.",
        "Two consequences worth stating: on a FAIL there is nothing settled.",
        "the run stops rather than trying a third time",
        "reconcile, re-gate, re-review, ship",
    )
    for sample in admitted:
        assert not _ATTEMPT_BOUND.search(sample), (
            "the predicate reads a bound into prose that states none — with this "
            f"window every file would report compliant for free: {sample!r}"
        )


def test_the_reconciliation_bound_is_stated_only_in_its_home() -> None:
    """AC-3: ship.md carries the bound, and no other base-drift paragraph does.

    Both directions in one assertion set, because they are one property: the
    home stating it is what makes the pointers honest, and a pointer restating
    it is what let the two copies drift ahead of the home in the first place.
    """
    found = _base_drift_paragraphs()

    home = found.get(_BOUND_HOME, [])
    assert any(_ATTEMPT_BOUND.search(p) for p in home), (
        f"{_BOUND_HOME}'s base-drift rule states no bound on retrying a "
        "reconciliation. Both `/build` and `/routine` send their reader here for "
        "it, so a home without it leaves the pointer resolving to nothing (#456)"
    )

    elsewhere = [
        f"{rel}: {m.group(0)!r}"
        for rel, paragraphs in found.items()
        if rel != _BOUND_HOME
        for p in paragraphs
        for m in [_ATTEMPT_BOUND.search(p)]
        if m
    ]
    assert not elsewhere, (
        "a base-drift paragraph outside its home restates the retry bound. The "
        f"bound lives in {_BOUND_HOME} and everything else points at it — a "
        "restatement is what drifted ahead of the home last time (#456):\n  "
        + "\n  ".join(elsewhere)
    )


# --- AC-4 -----------------------------------------------------------------

#: Provider query shapes. Each is a literal an agent could paste, and each
#: belongs in a provider skill: the GitHub CLI's issue/project/API surface with
#: its machine-readable output flags, and Linear's GraphQL endpoint, key, and
#: filter syntax.
#:
#: A blacklist has **sibling slots**, and its own refusal is what routes traffic
#: into them. ``{ eq: `` was added at review, because the two literals #456
#: deleted from ``commands/decision.md`` were a ``gh issue list`` *and* a Linear
#: filter — ``labels: { name: { eq: "input" } }`` — and only the first of them
#: was in this tuple. Re-embedding the Linear half ran live against a green
#: suite. Whenever this tuple grows, ask which other spelling of the same
#: operation the ban leaves reachable, not merely whether the new one is caught.
_QUERY_SHAPES = (
    "--json",
    "--jq",
    "gh issue ",
    "gh project ",
    "gh api",
    "api.linear.app",
    "LINEAR_API_KEY",
    "{ eq: ",
)


def _offending_shapes(text: str) -> set[str]:
    """The forbidden provider query shapes present in *text*.

    The single named predicate: the sweep and its control both call it, so a
    mutation to what counts as an offence is visible in more than one test.
    """
    return {shape for shape in _QUERY_SHAPES if shape in text}


def _command_files() -> list[Path]:
    """The swept corpus: every tracked markdown file under ``commands/``.

    Derived from the git index, and drawn one directory wide. The provider
    skills that own these shapes are excluded by living somewhere else, which is
    the only kind of exclusion a zero-membership sweep can carry without
    becoming opt-out prose.
    """
    return sorted(p for p in tracked_files_under("commands") if p.suffix == ".md")


def test_the_query_sweep_corpus_is_live_and_excludes_the_recipe_owners() -> None:
    """Floor on the corpus, and proof the exclusion is structural.

    Two halves. The corpus must hold the commands that read the tracker, or the
    sweep is scanning a set that cannot offend. And the provider skills — which
    carry these shapes correctly and in volume — must be *outside* it: if they
    ever fell inside, the only way to keep the sweep green would be an exemption
    list, and that is the failure this shape exists to avoid.
    """
    corpus = {_rel(p) for p in _command_files()}
    assert corpus, "no tracked commands/*.md — the query sweep is scanning nothing"
    for rel in ("commands/decision.md", "commands/digest.md", "commands/build.md"):
        assert rel in corpus, f"{rel} must be in the query sweep's corpus (#456)"

    for owner in ("skills/github-issues/SKILL.md", "skills/linear/SKILL.md"):
        assert owner not in corpus, (
            f"{owner} is inside the swept corpus. It owns these recipes, so the "
            "sweep would need an exemption to stay green — and an exemption "
            "token inside a zero-membership sweep is opt-out prose (#456)"
        )
        text = (_REPO_ROOT / owner).read_text(encoding="utf-8")
        assert _offending_shapes(text), (
            f"{owner} carries none of the shapes this sweep forbids elsewhere. "
            "The exclusion above is only meaningful while the recipes really do "
            "live there; otherwise the sweep bans a shape with no home (#456)"
        )


def test_no_command_embeds_a_provider_query_shape() -> None:
    """AC-4: a lifecycle command names the recipe, never the query.

    ``commands/decision.md`` carried the literal GitHub list invocation, its
    ``--json`` field list, a Linear filter shape and a ``gh issue view``, behind
    a carve-out reading that a read is not a lifecycle mutation. There is no
    such split: ``skills/tracker/SKILL.md`` routes every tracker operation
    through a provider recipe, and ``commands/digest.md`` says so in as many
    words.
    """
    offenders = [
        f"{_rel(path)}: {shape!r}"
        for path in _command_files()
        for shape in sorted(_offending_shapes(path.read_text(encoding="utf-8")))
    ]
    assert not offenders, (
        "a command embeds a provider query shape. Tracker operations — reads "
        "included — go through the `tracker` skill and the matching provider "
        "recipe, so the command names the operation and the provider owns the "
        "syntax (#456):\n  " + "\n  ".join(offenders)
    )


def test_the_query_predicate_catches_a_shape_spliced_into_a_real_command() -> None:
    """Control: the forbidden shapes are recognised inside real command prose.

    Spliced into ``commands/decision.md``'s own step 1 rather than judged over a
    standalone string, so this control cannot pass while the sweep reads a file
    the offending line is not in — the paired-splice discipline for a prose
    predicate, where there is no observable to declare.

    The verdict is the **difference** the splice makes, not the absolute set. An
    absolute form would die to the same edit as the sweep itself — the day a
    shape legitimately re-entered this file, both halves would report at once
    and neither would be exercised alone.
    """
    text = (_REPO_ROOT / "commands" / "decision.md").read_text(encoding="utf-8")
    anchor = "**Step 1 — pull the held-for-input pile.**"
    assert anchor in text, (
        "commands/decision.md lost the step this control splices into — re-point "
        "the control before assuming the sweep is fine (#456)"
    )
    for shape in _QUERY_SHAPES:
        spliced = text.replace(anchor, f"{anchor} Run `{shape} --state open`.", 1)
        added = _offending_shapes(spliced) - _offending_shapes(text)
        assert shape in added, (
            f"splicing {shape!r} into the real command adds {sorted(added)} to "
            "what the sweep sees — it does not recognise that shape"
        )


# --- AC-4, the routine's merge mechanism ----------------------------------


def test_routine_does_not_hard_assert_one_merge_mechanism() -> None:
    """Negative space: the retired wording that overrode the branch model.

    ``commands/routine.md`` step 3 deferred to ``CONTEXT.md``'s branch model and
    asserted "merge back by direct push" in the same sentence — contradictory in
    a repo whose model requires a PR. The phrase is retired vocabulary; whether
    the replacement defers *well* is the review gate's call.
    """
    text = (_REPO_ROOT / "commands" / "routine.md").read_text(encoding="utf-8")
    assert "merge back by direct push" not in text, (
        "commands/routine.md still hard-asserts a merge mechanism while deferring "
        "to the branch model in the same breath — the model is the instruction "
        "(#456)"
    )
