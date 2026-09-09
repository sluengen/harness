"""This repo's spine must carry the generated block its own template ships.

**The occurrence this guard cites (#489, from the v5 merge review of #481).**
``templates/spine.md`` is the ``AGENTS.md`` the plugin writes into a consuming
repo, and ``AGENTS.md`` is this repo's own copy of it. #537 made ``AGENTS.md`` the
source instruction file both hosts read, and #558 made ``CLAUDE.md`` carry it
verbatim followed by the deltas that apply on one host, so the block has one
*source* — edited in ``AGENTS.md`` and derived into ``CLAUDE.md``, never the
reverse. That derivation is this module's second subject, held further down. The region between
``<!-- spine:generated:begin harness@<version> -->`` and
``<!-- spine:generated:end -->`` is the plugin-owned half — the principles, the
laws, the lifecycle, the contract, and the enforcement summary — and everything after it
belongs to the repo. ``specs/features/plugin-surface.md`` asserts in prose that the
two blocks are byte-identical, and ADR 0017 D2 is what makes that matter — the
contract lives in the spine, unconditionally loaded, so the block is the one file
every session in every consuming repo reads. Nothing measured the assertion:
verified at #489's grounding, before this module existed, no file under ``tests/``
or ``scripts/`` referenced ``templates/spine.md`` at all. This repo
dogfoods its own plugin, so a spine edit made here and not mirrored into the
template ships a consuming repo a different set of principles and laws from the ones this
repo runs on.

**Admitted under ADR 0017 D5 class (e), tree-consistency.** Both operands are
tracked documents and the assertion is that a delimited region of each
*corresponds*, byte for byte. Nothing here reads what any law means — a
paragraph is compared as an opaque string, so a reword applied to both files
passes and a reword applied to one fails.

**Born green, and that is exactly why the samples exist.** The two blocks are
identical today, so the sweep at the bottom proves nothing about the predicate on
this tree (``craft.md`` → *Born green*). The teeth are the synthetic samples,
whose correct answers differ from the production answer of "no divergence", and
the staged probes recorded in the handoff.

**Two identically-empty extractions compare equal, so emptiness is refused.**
``craft.md`` → the identically-failed-renders class (#466: two blank captures
diffed to zero pixels and read as a match). A missing marker, a pair in the wrong
order, a duplicated marker, or a well-formed but empty region each raise here
rather than yielding ``""`` — because ``"" == ""`` is the one comparison this
guard must never make. :func:`generated_block` is where that refusal lives, so no
caller can reach the degenerate comparison.

**Why the tracked tree.** Both operands read the index through
:func:`tests._gitutil.indexed_text`. A guard over the working tree passes on the
machine that wrote the edit and says nothing about the clone that ships (#482,
#484).

**How this guard is proved (#489 D4).** :func:`generated_block` and
:func:`block_divergence` are mutation-proved with ``scripts/mutate.py`` over the
synthetic samples. The *file* half is out of ``mutate.py``'s reach, because
``mutate.py`` edits working files and these readers resolve the index (#490): it
is proved by **staged probe** — stage an edited block in ``AGENTS.md``, observe
the red, restore; then stage an edited block in ``templates/spine.md``, observe
the red in the other direction, restore; re-derive ``git write-tree`` each time
to prove the restore was exact.
"""

# size: over the ceiling on samples, not on logic — this module is one predicate
# (`generated_block` and `block_divergence`) plus its acceptance matrix, and the
# matrix is what grew. The `body` arm admits a permutation and, measured at #489's
# review, five further classes in which no line is unique to either side and
# nothing is reordered (the five are named in `block_divergence`; the permutation
# is the first shape its headline offers). That review proved a report naming one
# cause for all six is a defect an operator acts on, so each class owes its own
# sample with its own exclusive killer, each shape the headline offers is proved by
# dropping that shape alone, and the extractor's refusals and the floors on each
# operand each owe a sample too. Splitting the matrix out would put it in a different file from the
# predicate it measures and from the markers both are derived from. Grown by
# #489's F1 fix, and recorded here rather than answered by trimming the reasoning
# that names what each sample is the exclusive killer for.

from __future__ import annotations

import difflib
import json
import re
import subprocess
import tempfile
from pathlib import Path
from typing import NamedTuple

from tests._gitutil import indexed_text, tracked_files_under
from tests.unit._prose import REPO_ROOT

#: The spine the plugin writes into a consuming repo.
TEMPLATE_PATH = "templates/spine.md"

#: This repo's own spine, and the source of the derived copy below.
SPINE_PATH = "AGENTS.md"

#: The host file Claude Code loads. Since #558 it carries :data:`SPINE_PATH`
#: verbatim as a byte-exact prefix, then the deltas that apply on that host
#: alone, so the spine arrives without an ``@``-import resolution step.
DERIVED_PATH = "CLAUDE.md"

#: The updater-facing source of the one plugin release version.
PLUGIN_MANIFEST_PATH = ".claude-plugin/plugin.json"

#: ``X.Y.Z``, no leading zeros. The reference version is derived from the manifest
#: rather than restated here (#556), so this is what keeps three
#: garbage-but-identical values from agreeing with each other.
_SEMVER = re.compile(r"(?:0|[1-9]\d*)(?:\.(?:0|[1-9]\d*)){2}")

#: The block's delimiters. Both are matched at line start with indent and
#: trailing-whitespace tolerance, and with flexible spacing inside the comment,
#: because a regenerated block is machine-written and a formatting change to the
#: writer must not make this guard silent (#484, #487 — a parser that goes red or
#: quiet on a spelling its subject may legally contain is a defect). Anchoring to
#: line start is the counterfeited-delimiter remedy in ``craft.md``: prose that
#: merely *mentions* the marker mid-sentence must not open a block. Python's `re`
#: needs each lookbehind branch fixed-width, so ``re.MULTILINE`` with ``^`` is
#: used rather than a lookbehind alternation.
_BEGIN = re.compile(
    r"^[ \t]*<!--\s*spine:generated:begin\s+harness@(?P<version>[^\s>]+)\s*-->[ \t]*$",
    re.MULTILINE,
)
_END = re.compile(r"^[ \t]*<!--\s*spine:generated:end\s*-->[ \t]*$", re.MULTILINE)

#: The markers as both files spell them today, for the synthetic samples and the
#: splice below. Derived from the same literals the pattern above admits.
_HEADER = "<!-- spine:generated:begin harness@5.0.0 -->"
_FOOTER = "<!-- spine:generated:end -->"


class GeneratedBlock(NamedTuple):
    """The plugin-owned region of a spine: the version it declares and its body."""

    version: str
    body: str


def generated_block(text: str, *, label: str) -> GeneratedBlock:
    """The ``spine:generated`` block ``text`` carries.

    Raises rather than degrading, in every case where the block cannot be located
    unambiguously: no opener, no closer, a closer before its opener, a duplicated
    marker, or a region with no non-whitespace content. Each of those would
    otherwise yield an empty body, and two empty bodies compare equal — which is
    the identically-failed-renders class (#466) reached through a parser instead
    of through a renderer.
    """
    openers = list(_BEGIN.finditer(text))
    closers = list(_END.finditer(text))
    if len(openers) != 1 or len(closers) != 1:
        raise AssertionError(
            f"{label} must carry exactly one `spine:generated` begin marker and one "
            f"end marker; it carries {len(openers)} and {len(closers)}. A missing "
            f"marker would yield an empty block, and two empty blocks compare equal."
        )
    opener, closer = openers[0], closers[0]
    if closer.start() < opener.end():
        raise AssertionError(
            f"{label}'s `spine:generated` end marker precedes its begin marker "
            f"(end at offset {closer.start()}, begin at {opener.start()}), so the "
            f"block cannot be read."
        )
    body = text[opener.end() : closer.start()]
    if not body.strip():
        raise AssertionError(
            f"{label}'s `spine:generated` block is empty. An empty block is not a "
            f"spine, and it would compare equal to any other empty block."
        )
    return GeneratedBlock(version=opener.group("version"), body=body)


def block_divergence(template: GeneratedBlock, spine: GeneratedBlock) -> dict[str, list[str]]:
    """How ``template``'s block differs from ``spine``'s, empty when they agree.

    ``only_in_template`` is the direction where this repo's spine fell behind the
    shipped one; ``only_in_spine`` is the direction where an edit was made here and
    never mirrored back. Every *other* byte difference — every one in which no line
    is unique to either side — leaves both those lists empty, and is reported under
    ``body`` rather than as a silently empty report over unequal bodies.

    That arm is not the reordering arm. Measured: a repeated line, a dropped
    duplicate, an extra blank line beside blank lines the block already carries, a
    changed line ending and a changed trailing newline each reach it, and each is
    reported with a non-empty diff. Not one of those five is a permutation.
    The blank-line case is not hypothetical — staging ``AGENTS.md`` with one extra
    blank line after ``## Iron laws``, with no wording touched, is how #489's review
    reached this arm on the real subject. So the message names the condition the arm
    actually tests, offers the three shapes that condition admits, and leaves the
    cause to a unified diff (``craft.md`` → *A docstring claiming coverage the code
    lacks*; #487 — a diagnostic is a measured claim). The diff is labelled with the
    two spine paths, because those are the operands the sweep passes.

    The diff is taken over ``keepends`` lines so that it is non-empty for *every*
    input reaching this arm: joining those lines reconstructs the body exactly, so
    two bodies that differ cannot split into equal lists. A locator built from
    plain ``splitlines()`` would be empty for the line-ending and trailing-newline
    classes — a report promising a diff it does not carry.
    """
    report: dict[str, list[str]] = {}
    if template.version != spine.version:
        report["version"] = [template.version, spine.version]
    if template.body != spine.body:
        template_lines = template.body.splitlines()
        spine_lines = spine.body.splitlines()
        only_in_template = [line for line in template_lines if line not in spine_lines]
        only_in_spine = [line for line in spine_lines if line not in template_lines]
        if only_in_template:
            report["only_in_template"] = only_in_template
        if only_in_spine:
            report["only_in_spine"] = only_in_spine
        if not only_in_template and not only_in_spine:
            report["body"] = [
                "the blocks differ in bytes while no line is unique to either side — a "
                "reordering, a change in how many times a line repeats, or separator "
                "bytes the line split discards, such as a line ending or a trailing "
                "newline; the unified diff below locates it",
                *difflib.unified_diff(
                    template.body.splitlines(keepends=True),
                    spine.body.splitlines(keepends=True),
                    fromfile=TEMPLATE_PATH,
                    tofile=SPINE_PATH,
                    lineterm="",
                ),
            ]
    return report


def _block(path: str) -> GeneratedBlock:
    """The staged block at ``path``. Never the working file (#482)."""
    return generated_block(indexed_text(path), label=path)


# ---------------------------------------------------------------------------
# Floors — one on each operand, plus the control that must differ
# ---------------------------------------------------------------------------


def test_every_spine_operand_is_tracked() -> None:
    """The subjects must be in the index, not merely on this disk (#484).

    Three operands since #558, which is why this is no longer named for two: a
    guard reading a ``CLAUDE.md`` that never ships would hold a correspondence
    nobody receives.
    """
    tracked = {
        path.relative_to(REPO_ROOT).as_posix()
        for path in tracked_files_under("templates")
        | tracked_files_under(SPINE_PATH)
        | tracked_files_under(DERIVED_PATH)
    }
    assert TEMPLATE_PATH in tracked, (
        f"{TEMPLATE_PATH} is not tracked by git, so the spine a consuming repo "
        f"receives is not the one this guard read. Tracked: {sorted(tracked)}"
    )
    assert SPINE_PATH in tracked, (
        f"{SPINE_PATH} is not tracked by git. Tracked: {sorted(tracked)}"
    )
    assert DERIVED_PATH in tracked, (
        f"{DERIVED_PATH} is not tracked by git, so the host file a clone loads is "
        f"not the one this guard read. Tracked: {sorted(tracked)}"
    )


def test_both_blocks_are_live() -> None:
    """Floor on each operand the comparison consumes.

    ``craft.md`` → *Floor both measured operands* (#486). Flooring one side leaves
    a reader that emptied the other indistinguishable from agreement — and here the
    comparison is a string equality, which is the shape emptiness satisfies most
    readily. Membership is pinned by a structural anchor, never cardinality: a
    heading the generated block owns, not a sentence, so a benign reword of a law
    does not go red here.
    """
    for block, label in ((_block(TEMPLATE_PATH), TEMPLATE_PATH), (_block(SPINE_PATH), SPINE_PATH)):
        # #537 split the single ``## Iron laws`` heading into the two the block now
        # owns. Both are anchored, because the block's shape is that principles come
        # first and the laws are derived from them; an extraction reaching only one
        # of them is reaching part of the block.
        for heading in ("## Principles", "## Laws"):
            assert heading in block.body, (
                f"{label}'s generated block no longer carries the {heading!r} heading — "
                f"the extraction is {len(block.body)} characters and may not be reaching "
                f"the block at all"
            )
        assert block.version, f"{label}'s begin marker declares no plugin version"


def test_the_two_operands_are_different_documents() -> None:
    """The control that must differ (#466).

    Two readers resolving to the *same* file would agree perfectly and prove
    nothing. The tail of ``templates/spine.md`` is a placeholder skeleton and the
    tail of ``AGENTS.md`` is this repo's own section, so the whole texts must
    differ even while the blocks match.
    """
    assert indexed_text(TEMPLATE_PATH) != indexed_text(SPINE_PATH), (
        "the two operands read as identical whole documents — either both readers "
        "resolved to one path, or the template stopped being a template"
    )


def test_the_readers_follow_the_index_not_the_disk() -> None:
    """The operands are staged blobs, and this is the sample that says so.

    :func:`test_both_spines_are_tracked` does not reach this: it asserts the
    **paths** are in the index and says nothing about the bytes read. The fixture
    diverges in the direction where a working-tree reader looks *more* correct —
    the staged spine carries an edited law while the on-disk copy matches the
    template — so a reader that took the working tree would report agreement over a
    tree that ships a divergence (#482).
    """
    agreeing = f"{_HEADER}\n\n## Iron laws\n\n1. **Test-first.**\n\n{_FOOTER}\n"
    edited = f"{_HEADER}\n\n## Iron laws\n\n1. **Test-second.**\n\n{_FOOTER}\n"
    with tempfile.TemporaryDirectory() as raw:
        repo = Path(raw)
        subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True)
        (repo / "template.md").write_text(agreeing, encoding="utf-8")
        spine = repo / "spine.md"
        spine.write_text(edited, encoding="utf-8")
        subprocess.run(["git", "add", "template.md", "spine.md"], cwd=repo, check=True)

        # Restore an agreeing spine on disk, unstaged.
        spine.write_text(agreeing, encoding="utf-8")

        staged_text = indexed_text("spine.md", repo_root=repo)
        on_disk_text = spine.read_text(encoding="utf-8")
        assert staged_text != on_disk_text, (
            "the fixture failed to diverge — this sample would pass either way"
        )
        template_block = generated_block(
            indexed_text("template.md", repo_root=repo), label="template.md"
        )
        staged = block_divergence(template_block, generated_block(staged_text, label="staged"))
        assert staged == {
            "only_in_template": ["1. **Test-first.**"],
            "only_in_spine": ["1. **Test-second.**"],
        }, f"the reader returned something other than the staged blob: {staged}"
        assert (
            block_divergence(template_block, generated_block(on_disk_text, label="disk")) == {}
        ), (
            "the fixture's on-disk copy must read as agreeing, or this sample does "
            "not separate an index reader from a working-tree reader"
        )


def test_the_extractor_reads_the_real_spine() -> None:
    """Paired splice: prove the reader reaches real spine bytes.

    ``craft.md`` → *A prose mutation needs a paired splice to prove it was live*.
    Every sample below runs over synthetic strings, and the sweep is born green, so
    nothing else here would notice a reader that had stopped resolving either file.
    Splicing a line into the *real* spine's block, at a location inside the
    delimiters, and requiring it reported **there** separates "the two blocks
    agree" from "neither block was read".
    """
    real = indexed_text(SPINE_PATH)
    spliced = "A line this spine never carried."
    doctored = real.replace(f"\n{_FOOTER}", f"\n{spliced}\n{_FOOTER}")
    assert doctored != real, "the splice did not land, so nothing below measures the reader"
    template = _block(TEMPLATE_PATH)
    before = block_divergence(template, _block(SPINE_PATH))
    after = block_divergence(template, generated_block(doctored, label="spliced"))
    assert spliced not in before.get("only_in_spine", []), (
        "the spliced line must not already be reported, or its appearance "
        "afterwards proves nothing about the reader"
    )
    assert spliced in after.get("only_in_spine", []), (
        "a line spliced inside the real spine's block was not reported — the "
        "extractor is not reaching real spine bytes, and a clean sweep would be "
        "indistinguishable from a sweep that read nothing"
    )


# ---------------------------------------------------------------------------
# The predicate's teeth — synthetic samples, both directions
# ---------------------------------------------------------------------------


def _spine(body: str, *, version: str = "5.0.0", tail: str = "") -> str:
    """A synthetic spine carrying ``body`` inside the markers and ``tail`` after."""
    return (
        f"# How work happens here\n\n"
        f"<!-- spine:generated:begin harness@{version} -->\n{body}\n{_FOOTER}\n{tail}"
    )


def test_content_outside_the_markers_is_not_compared() -> None:
    """The exemption, earned from the delimiters rather than listed.

    Everything after the end marker belongs to the repo — this repo's ``## This
    repo`` section against the template's placeholder skeleton — so a rule
    comparing whole files would be permanently red. That is the stale direction of
    the exemption: it must still be needed.
    """
    template = generated_block(_spine("## Iron laws", tail="{placeholder}\n"), label="t")
    spine = generated_block(_spine("## Iron laws", tail="This repo builds a plugin.\n"), label="s")
    assert block_divergence(template, spine) == {}


def test_a_line_only_the_template_carries_is_reported() -> None:
    """The direction where this repo's spine fell behind the shipped one."""
    template = generated_block(_spine("## Iron laws\n1. Test-first.\n2. Measure it."), label="t")
    spine = generated_block(_spine("## Iron laws\n1. Test-first."), label="s")
    assert block_divergence(template, spine) == {"only_in_template": ["2. Measure it."]}


def test_a_line_only_this_repo_carries_is_reported() -> None:
    """The direction where an edit was made here and never mirrored back.

    This is the half that actually rots: the spine is the file a session edits,
    and the template is the file nobody opens.
    """
    template = generated_block(_spine("## Iron laws\n1. Test-first."), label="t")
    spine = generated_block(_spine("## Iron laws\n1. Test-first.\n2. Ship fast."), label="s")
    assert block_divergence(template, spine) == {"only_in_spine": ["2. Ship fast."]}


def test_a_reworded_line_is_reported_from_both_sides() -> None:
    """A reword is both directions in one edit, and neither may mask the other."""
    template = generated_block(_spine("## Iron laws\n1. Test-first."), label="t")
    spine = generated_block(_spine("## Iron laws\n1. Test-second."), label="s")
    assert block_divergence(template, spine) == {
        "only_in_template": ["1. Test-first."],
        "only_in_spine": ["1. Test-second."],
    }


def test_a_reordered_block_is_reported() -> None:
    """The same lines in a different order are not the same block.

    A predicate comparing line *sets* would pass this while still catching every
    sample above, so without it the weaker degradation is indistinguishable from
    the rule. The report carries a diff rather than two empty lists, which would
    render as a failure with nothing in it.
    """
    template = generated_block(_spine("## Iron laws\n1. First.\n2. Second."), label="t")
    spine = generated_block(_spine("## Iron laws\n2. Second.\n1. First."), label="s")
    report = block_divergence(template, spine)
    assert set(report) == {"body"}, f"a reordering did not reach the body arm: {report}"
    headline, *located = report["body"]
    assert "no line is unique to either side" in headline, headline
    assert "a reordering" in headline, (
        f"the headline dropped the one shape this input actually is: {headline}"
    )
    assert any(line.startswith("+2. Second.") for line in located), (
        f"the diff does not locate the moved line: {located}"
    )


def test_a_repeated_line_is_reported_with_a_diff() -> None:
    """A duplicated line reaches the ``body`` arm, and it is not a reordering.

    ``craft.md`` → *A docstring claiming coverage the code lacks*, met one level on
    in the report the guard prints. Every difference in which no line is unique to
    either side lands here, and only one of the shapes the headline offers is a
    permutation; this input is not it, because it repeats a line the other block
    carries once. A report naming the wrong cause is worse than a bare one — the
    reader looks for a reordering, finds none, and reads a real failure as a false
    positive.

    Its exclusive killer is a report narrowed to whitespace-only differences: a
    difference in *content* multiplicity then falls out of the arm entirely, which
    no other sample here notices.

    This sample also carries the diff's **orientation**, because the labels are a
    wiring field and nothing else pins them (``craft.md`` → *The wiring-field
    survivor*). Transposing ``fromfile``/``tofile`` leaves the ``+``/``-`` sequence
    orientation untouched and tells the operator that the side carrying the extra
    line is the other one — a false report of exactly the kind this ticket exists
    to refuse, and green in every other sample here.
    """
    template = generated_block(_spine("## Iron laws\n1. First.\n2. Second."), label="t")
    spine = generated_block(_spine("## Iron laws\n1. First.\n1. First.\n2. Second."), label="s")
    report = block_divergence(template, spine)
    assert set(report) == {"body"}, f"a repeated line did not reach the body arm: {report}"
    headline, *located = report["body"]
    assert "no line is unique to either side" in headline, headline
    assert "the same lines in a different order" not in headline, (
        f"the report names a reordering as the cause of a difference that is not "
        f"one: {headline}"
    )
    assert "repeats" in headline, (
        f"the headline no longer offers the shape this input is — a reader given "
        f"only the permutation reading looks for the wrong thing: {headline}"
    )
    assert located[:2] == [f"--- {TEMPLATE_PATH}", f"+++ {SPINE_PATH}"], (
        f"the diff is labelled with the wrong sides, so every `+` line reads as "
        f"belonging to the file that does not carry it: {located[:2]}"
    )
    assert any(line.startswith("+1. First.") for line in located), (
        f"the diff does not locate the repeated line, so the reader is told a "
        f"difference exists and handed nothing to find it with: {located}"
    )


def test_an_extra_blank_line_is_reported_with_a_diff() -> None:
    """The drift two hand-edited spines actually produce.

    Measured at #489's review: staging ``AGENTS.md`` with one extra blank line
    after ``## Iron laws`` — no wording touched — reached this arm and was reported
    as a reordering. The empty line is already carried by both blocks, so it is
    unique to neither and the two ``only_in_*`` lists stay empty. This is the
    sample the real subject supplies, and the one an operator is likeliest to meet.

    Its exclusive killer is a locator that drops whitespace-only lines: the
    repeated-line and line-ending samples still diff cleanly without them, and only
    this one goes silent.
    """
    template = generated_block(_spine("## Iron laws\n\n1. First."), label="t")
    spine = generated_block(_spine("## Iron laws\n\n\n1. First."), label="s")
    report = block_divergence(template, spine)
    assert set(report) == {"body"}, f"an extra blank line did not reach the body arm: {report}"
    headline, *located = report["body"]
    assert "no line is unique to either side" in headline, headline
    assert "the same lines in a different order" not in headline, (
        f"one extra blank line was reported as a reordering: {headline}"
    )
    assert "repeats" in headline, (
        f"the headline no longer offers the shape this input is — an added blank "
        f"line is a repeat of a line the block already carries: {headline}"
    )
    assert any(line.startswith("+") and not line[1:].strip() for line in located), (
        f"the diff does not locate the added blank line: {located}"
    )


def test_a_line_ending_difference_is_reported_with_a_diff() -> None:
    """The class a line-split diff cannot see, which is why the diff keeps its ends.

    A block re-saved with CRLF endings differs in bytes while splitting into
    exactly the same lines, so a locator built from ``splitlines()`` would be
    **empty** here and the report would promise a diff it did not carry — the
    identically-failed-renders class (#466) reached through a diagnostic. Taking
    the diff over ``keepends`` lines is what makes the promise hold, because
    joining those lines reconstructs the body exactly: two bodies that differ
    cannot split into equal ``keepends`` lists. This sample is that guarantee's
    exclusive killer.
    """
    template = generated_block(_spine("## Iron laws\n1. First."), label="t")
    spine = generated_block(_spine("## Iron laws\r\n1. First."), label="s")
    report = block_divergence(template, spine)
    assert set(report) == {"body"}, f"a line-ending change did not reach the body arm: {report}"
    headline, *located = report["body"]
    assert "no line is unique to either side" in headline, headline
    assert "separator bytes" in headline, (
        f"the headline no longer offers the shape this input is, and it is the "
        f"shape a reader is least likely to guess unaided: {headline}"
    )
    assert located, (
        "the report carries no diff at all — the locator was built from a line "
        "split that discards exactly the bytes this difference lives in"
    )
    assert "+## Iron laws\r\n" in located, (
        f"the diff carries no line ending to compare, so it cannot locate a "
        f"difference that lives in one: {located}"
    )


def test_a_version_skew_is_reported() -> None:
    """The marker's own version is part of the correspondence.

    Two blocks generated by different plugin versions are not the same block even
    when their bodies happen to agree, and the version is the only thing in the
    region that says which generator wrote it.
    """
    template = generated_block(_spine("## Iron laws", version="5.0.0"), label="t")
    spine = generated_block(_spine("## Iron laws", version="4.9.0"), label="s")
    assert block_divergence(template, spine) == {"version": ["5.0.0", "4.9.0"]}


def test_two_agreeing_blocks_report_nothing() -> None:
    """The passing direction.

    Without this, a predicate that reported everything as a divergence would
    satisfy every sample above and still be useless.
    """
    body = "\n## Iron laws\n\n1. **Test-first.**\n2. **Measure it.**\n"
    assert block_divergence(
        generated_block(_spine(body), label="t"), generated_block(_spine(body), label="s")
    ) == {}


def _rejects(text: str, needle: str) -> None:
    """Assert :func:`generated_block` fails loudly on ``text``."""
    try:
        generated_block(text, label="sample")
    except AssertionError as exc:
        assert needle in str(exc), f"the failure did not explain itself: {exc}"
    else:
        raise AssertionError(f"a malformed spine was accepted: {text!r}")


def test_a_spine_with_no_markers_fails_loudly() -> None:
    """``craft.md`` → the identically-failed-renders class (#466).

    Two files that both lack the markers would both extract to ``""``, and
    ``"" == ""`` reads as perfect agreement. Refusing at extraction is what makes
    that comparison unreachable — so this sample asserts the *pair* fails, not
    merely that one file does.
    """
    bare = "# How work happens here\n\nNo generated block here at all.\n"
    _rejects(bare, "exactly one")
    _rejects(bare, "compare equal")


def test_a_spine_missing_one_marker_fails_loudly() -> None:
    """Half a delimiter pair is not a block, in either direction."""
    _rejects(f"{_HEADER}\n## Iron laws\n", "exactly one")
    _rejects(f"## Iron laws\n{_FOOTER}\n", "exactly one")


def test_markers_in_the_wrong_order_fail_loudly() -> None:
    """A closer before its opener would slice backwards and yield ``""``."""
    _rejects(f"{_FOOTER}\n## Iron laws\n{_HEADER}\n", "precedes")


def test_a_duplicated_marker_fails_loudly() -> None:
    """Two openers make the block ambiguous, and picking one silently is a guess."""
    _rejects(f"{_HEADER}\n## Iron laws\n{_HEADER}\n## Again\n{_FOOTER}\n", "exactly one")


def test_a_well_formed_but_empty_block_fails_loudly() -> None:
    """The degenerate case the markers cannot rule out on their own.

    A correctly delimited region containing only whitespace still extracts to
    something that compares equal to any other such region.
    """
    _rejects(f"{_HEADER}\n\n   \n{_FOOTER}\n", "empty")


def test_prose_mentioning_the_marker_does_not_open_a_block() -> None:
    """The opener is anchored to line start, and this is what says so.

    ``craft.md`` → *A paired delimiter can be counterfeited by prose that mentions
    it*. ``AGENTS.md``'s own third line discusses the ``spine:generated`` block in
    ordinary prose, and this module's docstring names both markers, so a document
    *about* the syntax is the structurally most exposed corpus for this defect. An
    unanchored opener would start the block at the mention and swallow the real
    marker line into the body.
    """
    text = (
        "# How work happens here\n\n"
        f"The block below is delimited by `{_HEADER}` and everything after it is "
        "the repo's own.\n\n"
        f"{_HEADER}\n## Iron laws\n{_FOOTER}\n"
    )
    block = generated_block(text, label="sample")
    assert block.body.strip() == "## Iron laws", (
        f"the mention was read as an opener — the body is {block.body!r}"
    )


def test_a_regenerated_marker_with_different_spacing_still_parses() -> None:
    """A legal spelling the writer may emit must not read as nothing.

    #484 and #487 are the same defect twice: a pattern admitting one spelling of
    its subject went silent or red on another that was equally correct. The
    markers are machine-written HTML comments, where interior spacing carries no
    meaning.
    """
    text = (
        "<!--  spine:generated:begin   harness@5.1.0  -->\n"
        "## Iron laws\n"
        "<!--   spine:generated:end   -->\n"
    )
    block = generated_block(text, label="sample")
    assert block == GeneratedBlock(version="5.1.0", body="\n## Iron laws\n")


# ---------------------------------------------------------------------------
# The sweep — AC-3, over the real documents
# ---------------------------------------------------------------------------


def test_the_spine_and_its_template_carry_the_same_generated_block() -> None:
    """AC-3: the plugin-owned region of the template and the spine it seeds is
    byte-identical."""
    difference = block_divergence(_block(TEMPLATE_PATH), _block(SPINE_PATH))
    assert difference == {}, (
        f"{SPINE_PATH}'s generated block has drifted from {TEMPLATE_PATH}'s. "
        f"`only_in_template` names lines the shipped spine carries that this repo "
        f"does not; `only_in_spine` names lines edited here and never mirrored "
        f"back, so a consuming repo would receive different principles and laws "
        f"from the ones this repo runs on. Both are wrong: {difference}"
    )


def version_disagreements(manifest: str, template: str, spine: str) -> dict[str, object]:
    """Where the updater selector and the two spine markers fail to name one version.

    The manifest is the **reference**, derived rather than restated (#556 / D7).
    The literal that used to sit here had to be edited once per release cycle —
    which the fix lane may not do at all (law 7) and which the test-lock hook
    refuses in the change lane — so the start-of-cycle bump rule was unshippable
    while it stood. It was also a hardcoded answer masquerading as a guard, the
    repo's most-repeated defect class (#458, #466: pin the derivation, not the
    derived answer); the property this module names in its own docstring is
    *agreement*, to which a particular number contributed nothing.

    What the literal was incidentally holding is kept explicitly: with the
    reference derived, three garbage-but-identical values agree with each other
    and the equality says nothing, so a reference that is not an ``X.Y.Z``
    version is itself the disagreement.
    """
    carried: dict[str, object] = {
        PLUGIN_MANIFEST_PATH: json.loads(manifest).get("version"),
        TEMPLATE_PATH: generated_block(template, label=TEMPLATE_PATH).version,
        SPINE_PATH: generated_block(spine, label=SPINE_PATH).version,
    }
    reference = carried[PLUGIN_MANIFEST_PATH]
    if not isinstance(reference, str) or _SEMVER.fullmatch(reference) is None:
        return {PLUGIN_MANIFEST_PATH: f"not an X.Y.Z version: {reference!r}"}
    return {home: value for home, value in carried.items() if value != reference}


def _sample(manifest: str, template: str, spine: str) -> tuple[str, str, str]:
    """Three synthetic homes, at versions this repo has never published (#458)."""
    return (
        json.dumps({"name": "harness", "version": manifest}),
        _spine("## Laws", version=template),
        _spine("## Laws", version=spine),
    )


def test_the_three_homes_agree_on_a_version_this_repo_never_published() -> None:
    """#458: the reference is *derived* from the manifest, never restated here."""
    assert version_disagreements(*_sample("2.3.4", "2.3.4", "2.3.4")) == {}


def test_a_marker_that_moved_without_the_manifest_is_reported() -> None:
    """The property #496 recorded, kept: a release that moves one value and not the
    others makes consumers disagree about which guidance they have."""
    assert version_disagreements(*_sample("2.3.4", "2.3.4", "2.3.5")) == {SPINE_PATH: "2.3.5"}


def test_three_identically_unusable_versions_do_not_compare_equal() -> None:
    """What the deleted literal was holding, made explicit.

    With the reference derived rather than restated, three garbage-but-identical
    values agree with each other and the equality says nothing — the
    identically-failed-operands class (#466). The shape refusal is what keeps the
    test refusing a version that is not a version.
    """
    assert version_disagreements(*_sample("seven", "seven", "seven")) != {}


def test_the_manifest_and_both_spines_name_the_current_release() -> None:
    """#496: the updater selector and both shipped spine markers agree.

    The plugin manager selects releases from ``plugin.json`` while hydration
    writes the version embedded in ``templates/spine.md``. A release that moves
    only one of those values makes consumers disagree about which guidance they
    have, even when the generated bodies compare byte-for-byte. All operands are
    read from the index: this is a release contract over the tree that ships.
    """
    disagreements = version_disagreements(
        indexed_text(PLUGIN_MANIFEST_PATH), indexed_text(TEMPLATE_PATH), indexed_text(SPINE_PATH)
    )
    assert disagreements == {}, disagreements


# ---------------------------------------------------------------------------
# The second correspondence — the host file carries the spine verbatim (#558)
# ---------------------------------------------------------------------------
#
# Admitted under ADR 0017 D5 class (e), tree-consistency, on the same footing as
# the block comparison above: both operands are tracked documents, and the
# assertion is that one *corresponds* to a region of the other byte for byte.
# Nothing here reads what any sentence means, so a reword applied to both files
# passes and a reword applied to one fails.
#
# Why a prefix and not the delimited-block comparison already in this module:
# `generated_block` extracts the plugin-owned region, so comparing that region
# would pass a `CLAUDE.md` whose *tail* — the repo-owned half, everything after
# an end marker — had drifted from the source. The contract #558 buys is the
# whole of `AGENTS.md`, not the generated block of it.
#
# Not asserted here, per law 1: `CLAUDE.md` carries the `spine:generated` version
# stamp after #558, but it is **not** a fourth operand in `version_disagreements`
# below. A byte-exact prefix makes its stamp agree with `AGENTS.md` by
# construction, so enumerating it would be a second measurement of one fact
# (#492 — de-duplication is a deletion; the survivor here is the prefix
# relation). That subsumption holds *only* while the relation asserted is a
# prefix; weaken it to "contains" and the version stamp needs its own operand.
#
# The boundary marker (#594) changes none of this. `<!-- spine:copy:end -->` is
# written into the remainder, at position `len(source)` — inside the tail this
# predicate already treats as opaque, not the prefix. All three clauses hold
# unchanged: clause 1 (the prefix relation) is the same bytes it always was,
# clause 3 (a non-empty remainder) is satisfied more strongly, not less, since
# the remainder now opens with the marker. The subsumption argument above is
# likewise unmoved: the marker carries no version and sits below the
# `spine:generated` stamp, so the relation excluding `CLAUDE.md` from
# `version_disagreements` is still a prefix, not a containment.


def derived_spine_divergence(
    source: str,
    derived: str,
    *,
    source_label: str = SPINE_PATH,
    derived_label: str = DERIVED_PATH,
) -> dict[str, list[str]]:
    """Report how ``derived`` departs from carrying ``source`` as a byte-exact prefix.

    Returns ``{}`` when the contract holds and ``{"prefix": [...]}`` when it does
    not. The contract is three clauses and nothing else: ``derived`` starts with
    ``source`` byte for byte with no normalisation; neither operand is empty or
    whitespace-only; and the remainder after the prefix carries non-whitespace
    content. The boundary is positional — character ``len(source)`` — with no
    marker, delimiter or sentinel defining the join.

    Whitespace at the join may migrate across the boundary and the relation still
    holds, correctly: adding a trailing newline to ``source`` leaves ``derived``
    still carrying it verbatim, with the blank line moved from the tail's side to
    the prefix's. That is the property, not a hole in it.

    A human can check the same thing without a test runner::

        git show :AGENTS.md > /tmp/a && git show :CLAUDE.md > /tmp/c
        cmp -n "$(wc -c < /tmp/a)" /tmp/a /tmp/c

    Silence means the prefix holds; a non-empty tail after that many bytes means
    the deltas survived.

    The empty refusals are per-document and evaluated first, so ``("", "")`` can
    never reach the comparison — ``"" == ""`` is the one comparison this guard
    must never make (#466). The third refusal is a property of the *pair*, so
    unlike :func:`generated_block`'s it cannot live in a per-document extractor;
    it sits immediately after the prefix test instead.
    """
    assert source.strip(), (
        f"{source_label} is empty or whitespace-only, so it is a prefix of every "
        f"file and this correspondence would hold for anything"
    )
    assert derived.strip(), (
        f"{derived_label} is empty or whitespace-only, so nothing was compared"
    )

    cut = len(source)
    if derived.startswith(source):
        assert derived[cut:].strip(), (
            f"{derived_label} is only the copy: it carries {source_label} and no "
            f"host deltas after it. A hydration that dropped the deltas looks "
            f"exactly like this, so it is refused rather than passed"
        )
        return {}

    limit = min(len(source), len(derived))
    offset = limit
    for index in range(limit):
        if source[index] != derived[index]:
            offset = index
            break

    repair = (
        f"{source_label} is the source; re-derive {derived_label} as the whole of "
        f"{source_label} followed by the existing host deltas."
    )
    if len(derived) < cut and source.startswith(derived):
        headline = (
            f"{derived_label} stops inside the copy: it carries the first "
            f"{len(derived)} of {cut} characters of {source_label} and nothing "
            f"more. {repair}"
        )
    else:
        headline = (
            f"{derived_label} disagrees with {source_label} at a character inside "
            f"the copied region. {repair}"
        )

    line_number = source[:offset].count("\n") + 1
    locator = (
        f"first difference at character {offset} of {source_label}, "
        f"line {line_number}"
    )
    diff = list(
        difflib.unified_diff(
            source.splitlines(keepends=True),
            derived[:cut].splitlines(keepends=True),
            fromfile=source_label,
            tofile=f"{derived_label} (first {cut} characters)",
            lineterm="",
        )
    )
    return {"prefix": [headline, locator, *diff]}


def _pair() -> tuple[str, str]:
    """The staged source and derived spines. Never the working files (#482)."""
    return indexed_text(SPINE_PATH), indexed_text(DERIVED_PATH)


def _rejects_pair(source: str, derived: str, needle: str) -> None:
    """Assert :func:`derived_spine_divergence` fails loudly on this pair."""
    try:
        derived_spine_divergence(source, derived)
    except AssertionError as exc:
        assert needle in str(exc), f"the failure did not explain itself: {exc}"
    else:
        raise AssertionError(
            f"a degenerate pair was accepted: {source!r} / {derived!r}"
        )


#: A minimal source document for the synthetic pairs below, and the tail a legal
#: derived file carries after it. Both are deliberately unlike this repo's real
#: documents: a sample whose correct answer is the production answer measures
#: nothing (``craft.md`` → *Born green*).
_SOURCE = "# Spine\n\nA law.\nAnother law.\n"
_TAIL = "\n# Host deltas\n\nOne delta.\n"

#: The boundary the derivation writes at the end of the copied region (#594).
#: A later hydration re-derives from it whatever has drifted above it, so it is
#: recovery machinery for that procedure and **not** an operand of the predicate
#: below — the contract is still the prefix relation and nothing else.
_COPY_END = "<!-- spine:copy:end -->"
_BOUNDARY = f"\n{_COPY_END}\n"


def test_the_prefix_reader_reaches_real_spine_bytes() -> None:
    """Paired splice: prove both readers reach real bytes.

    ``craft.md`` → *A prose mutation needs a paired splice to prove it was live*.
    The sweep below is born green — the two files agree today — so nothing else
    here separates "the host file carries the spine" from "neither file was
    read". Splicing a line into the *real* staged spine and requiring it reported
    is what makes that distinction.
    """
    source, derived = _pair()
    spliced = "A line this spine never carried."
    doctored = source.replace("\n## This repo\n", f"\n{spliced}\n## This repo\n")
    assert doctored != source, (
        "the splice did not land, so nothing below measures the reader"
    )
    assert derived_spine_divergence(source, derived) == {}, (
        "the real pair must agree before the splice, or the report afterwards "
        "proves nothing about the reader"
    )
    after = derived_spine_divergence(doctored, derived)
    assert after, (
        "a line spliced into the real spine was not reported — the reader is not "
        "reaching real bytes, and a clean sweep would be indistinguishable from a "
        "sweep that read nothing"
    )
    assert any(spliced in line for line in after["prefix"]), (
        f"the report did not carry the spliced line: {after['prefix'][:3]}"
    )


def test_an_edit_below_the_prefix_reports_nothing() -> None:
    """The legitimate-edit control, on the real subject.

    ``craft.md`` → a kill table cannot see a false positive (#511). Every sample
    below is a kill; this is the row that goes red if the predicate is widened to
    whole-file equality, which would refuse every host delta the contract exists
    to permit.
    """
    source, derived = _pair()
    assert derived_spine_divergence(source, derived + "\n- A new host delta.\n") == {}


def test_a_source_edit_that_was_never_mirrored_is_reported() -> None:
    """The source gained a line inside the copied region; the copy did not.

    *Exclusive killer:* a predicate that compares only the opening of each file,
    or normalises whitespace, or compares lengths — each is green on a pair whose
    divergence sits in the middle and leaves both files plausible.
    """
    grown = _SOURCE.replace("A law.\n", "A law.\nA third law.\n")
    report = derived_spine_divergence(grown, _SOURCE + _TAIL)
    assert set(report) == {"prefix"}, report
    assert any("A third law." in line for line in report["prefix"]), report["prefix"]
    assert "re-derive" in report["prefix"][0]


def test_a_derived_edit_inside_the_prefix_is_reported() -> None:
    """The other direction: the copy was reworded, the source untouched.

    *Exclusive killer:* a guard that only notices the source growing — a ``len()``
    comparison rather than a prefix test — which is green here because both
    documents are the same length.
    """
    reworded = _SOURCE.replace("Another law.", "Another rule.") + _TAIL
    report = derived_spine_divergence(_SOURCE, reworded)
    assert set(report) == {"prefix"}, report
    assert "line 4" in report["prefix"][1], report["prefix"][1]
    assert "character" in report["prefix"][1]


def test_the_boundary_marker_does_not_excuse_a_drifted_copy() -> None:
    """The boundary marker is hydration's recovery locator, not a relaxation
    of this gate's contract (#594). A drifted copy is reported even when it
    carries a well-formed boundary marker below the drift.

    *Exclusive killer:* the relaxation this ticket invites —
    ``if _COPY_END in derived: return {}``, on the reasoning that a later hydration
    will re-derive it anyway. That mutant is green on every other row in this
    module and returns ``{}`` here. The gate's job is unchanged by #594: it says
    the copy is correct **now**, not that something will fix it later. *What it
    does not kill:* a boundary-splitting reimplementation
    (``derived.split(_COPY_END)[0] == source``), which also reports on this
    input — :func:`test_the_boundary_marker_is_not_an_operand_of_this_predicate`
    below is that one's killer.
    """
    drifted = _SOURCE.replace("Another law.", "Another rule.")
    report = derived_spine_divergence(_SOURCE, drifted + _BOUNDARY + _TAIL)
    assert set(report) == {"prefix"}, report


def test_the_boundary_marker_is_not_an_operand_of_this_predicate() -> None:
    """The marker locates nothing for this guard; only the prefix does (#594).

    *Exclusive killer:* any reimplementation that locates the copy region by the
    marker rather than by position — ``derived.split(_COPY_END)[0] == source``
    and every variant. Those report on this input; the shipped predicate
    returns ``{}``, because the contract is the prefix and everything after
    ``len(source)`` is the tail as far as *this guard* is concerned. The
    division is the subtle part of the whole ticket: the guard asserts the
    prefix; the boundary marker is hydration's recovery locator. A file in
    this shape is legal to the gate and would have its ``extra\\n`` replaced and
    reported by the next hydration (see ``skills/hydrate/SKILL.md`` step 12,
    *Reporting the overwrite*). Both are correct; they answer different questions.
    """
    assert derived_spine_divergence(_SOURCE, _SOURCE + "extra\n" + _BOUNDARY + _TAIL) == {}


def test_a_derived_file_shorter_than_its_source_names_the_truncation() -> None:
    """A copy that stops partway carries no tail, and is named as truncated.

    *Exclusive killers, two.* Collapsing the two branches into one message tells
    an operator "they differ at character k" for a file that is merely short —
    the wrong-cause-named defect this module already refuses elsewhere. And
    evaluating the relation in the **wrong direction** (``source.startswith(
    derived)``) returns ``{}`` on exactly this shape, because a truncated copy
    *is* a prefix of its source — the one shape where the inverted relation is
    silently satisfied rather than merely reported differently.
    """
    truncated = _SOURCE[: len(_SOURCE) // 2]
    report = derived_spine_divergence(_SOURCE, truncated)
    assert set(report) == {"prefix"}, report
    assert "stops inside the copy" in report["prefix"][0], report["prefix"][0]
    assert str(len(truncated)) in report["prefix"][0]
    assert str(len(_SOURCE)) in report["prefix"][0]


def test_a_line_ending_change_inside_the_prefix_is_reported() -> None:
    """CRLF inside the copied region is a divergence, and the diff shows it.

    *Exclusive killer:* a locator built from plain ``splitlines()``. A difference
    living only in a line ending splits into equal lists, so the report would
    promise a diff it does not carry — #466 arriving through a diagnostic.
    """
    crlf = _SOURCE.replace("\n", "\r\n") + _TAIL
    report = derived_spine_divergence(_SOURCE, crlf)
    assert set(report) == {"prefix"}, report
    assert any("\r" in line for line in report["prefix"][2:]), (
        "the diff carried no carriage return, so it does not show the difference "
        "the headline claims"
    )


def test_two_agreeing_spines_report_nothing() -> None:
    """The passing direction. Without it, a predicate that reported everything
    would satisfy every kill above.

    Also the marker-less-pair control (#594): neither operand here carries
    ``<!-- spine:copy:end -->``, unlike the two boundary-marker samples below
    (``test_the_boundary_marker_does_not_excuse_a_drifted_copy`` and
    ``test_the_boundary_marker_is_not_an_operand_of_this_predicate``), so this
    row's agreement is evidence about the prefix relation with no marker
    involved at all — do not cull it as redundant with those two.
    """
    assert derived_spine_divergence(_SOURCE, _SOURCE + _TAIL) == {}


def test_whitespace_at_the_join_may_move_across_the_boundary() -> None:
    """A trailing newline added to the source keeps the relation true.

    The boundary is positional, so whitespace at the join may sit on either side:
    the loaded bytes are still the source verbatim followed by the deltas. Pinned
    so a later editor does not "tighten" the contract with a rule requiring the
    tail to begin with exactly one newline — that clause has no protective value
    and goes red on formatter churn.
    """
    assert derived_spine_divergence(_SOURCE + "\n", _SOURCE + "\n" + _TAIL) == {}
    assert derived_spine_divergence(_SOURCE, _SOURCE + "\n" + _TAIL) == {}


def test_an_empty_operand_is_refused_rather_than_compared_equal() -> None:
    """``craft.md`` → the identically-empty class (#466).

    *Exclusive killer:* a refusal written ``== ""`` rather than ``.strip()``, or
    one that floors a single operand — ``("", "")`` then returns ``{}`` and reads
    as perfect agreement, which is the comparison this guard must never make.

    The absent-file case is held here plus the tracked floor above, deliberately
    not by an :func:`indexed_text` call: that raises ``CalledProcessError`` for an
    untracked path, which is an unreadable subprocess traceback rather than a
    guard explaining itself.
    """
    for source, derived in (("", "x\n"), ("  \n", "x\n"), ("", "")):
        _rejects_pair(source, derived, "empty")
    for source, derived in (("x\n", ""), ("x\n", " \t\n")):
        _rejects_pair(source, derived, "empty")


def test_a_derived_file_that_is_only_the_copy_is_refused() -> None:
    """A host file that is the copy and nothing else lost its deltas.

    *Exclusive killer:* a remainder check written ``derived != source`` instead of
    ``.strip()`` on the remainder — the whitespace-tailed spelling then passes and
    a hydration that dropped the deltas ships.
    """
    _rejects_pair(_SOURCE, _SOURCE, "only the copy")
    _rejects_pair(_SOURCE, _SOURCE + "\n\n   \n", "only the copy")


def test_the_smallest_legal_pair_is_accepted() -> None:
    """The false-positive control sitting beside each refusal above (#511).

    Three near-misses that must stay green: a minimal source with a minimal tail
    and no newline at the join (beside the ``only the copy`` refusal); a minimal
    source whose tail is a heading (beside it too); and a single-character source
    (beside the ``empty`` refusals). *Fails when:* a refusal is written too wide —
    flooring on a line count, a heading, or a minimum length.
    """
    assert derived_spine_divergence("#\n", "#\nx") == {}
    assert derived_spine_divergence("#\n", "#\n\n# deltas\n") == {}
    assert derived_spine_divergence("x", "xy") == {}


def test_content_above_the_copy_is_a_divergence_not_a_containment() -> None:
    """The relation is a **prefix**, never a containment — and a decision rests on it.

    *Exclusive killer:* ``derived.startswith(source)`` weakened to
    ``source in derived``. That mutation survives every other row in this module,
    because in all of them the copy already starts at character 0. Here it does
    not: a ``CLAUDE.md`` carrying frontmatter or a title *above* the copy still
    contains the spine, so the weakened form returns ``{}``.

    Why it is worth a row of its own: the *Not asserted here* note above
    :func:`derived_spine_divergence` excludes ``CLAUDE.md`` from
    :func:`version_disagreements` on the grounds that a byte-exact prefix makes
    its ``spine:generated`` stamp agree *by construction*. Containment does not
    buy that — a stamp that merely appears somewhere in the file is not a stamp
    that agrees. Without this row the module states a load-bearing property that
    nothing measures, and a later simplification to ``in`` would keep the suite
    green while quietly removing the basis for that exclusion (pin the
    derivation, not the derived answer).
    """
    prefixed = "---\ntitle: Host notes\n---\n" + _SOURCE + _TAIL
    report = derived_spine_divergence(_SOURCE, prefixed)
    assert set(report) == {"prefix"}, report


def test_the_host_file_carries_the_spine_verbatim() -> None:
    """The sweep (#558). ``CLAUDE.md`` carries ``AGENTS.md`` as a byte-exact prefix.

    Born green once the copy lands, which is why every row above exists. This is
    the row that goes red when either file is edited without the other.
    """
    source, derived = _pair()
    report = derived_spine_divergence(source, derived)
    assert report == {}, "\n".join(
        [f"{DERIVED_PATH} no longer carries {SPINE_PATH} verbatim:", *report["prefix"]]
    )


def test_the_host_file_marks_where_the_copy_ends() -> None:
    """The boundary marker sweep (#594). ``CLAUDE.md`` marks where the copied
    region ends, so a later hydration can re-derive the deltas from a declared
    position rather than by comparing bytes against a possibly-drifted source.

    Two properties, both live. *Position*: the marker opens the remainder,
    asserted positionally rather than by containment — ``_COPY_END in derived``
    would pass for a marker anywhere, including inside the copy region, which is
    this module's own prefix-versus-containment lesson
    (``test_content_above_the_copy_is_a_divergence_not_a_containment``) one
    level down. *Exactly one*: what makes the file bounded under the procedure
    in ``skills/hydrate/SKILL.md`` — two or more anchored markers and nothing can tell which
    delimits the deltas. This also subsumes "``AGENTS.md`` carries none":
    ``AGENTS.md`` is a prefix of ``CLAUDE.md``, so an occurrence there would be
    a second occurrence here (law 1 — no separate assertion for it).

    The first line is read with ``lstrip("\\n")`` and ``.strip()`` deliberately:
    asserting the remainder starts with the boundary bytes exactly would go red
    when a trailing newline legitimately migrates across the join, which
    ``test_whitespace_at_the_join_may_move_across_the_boundary`` exists to say
    must not happen. Interior comment spacing is *not* tolerated here — these
    bytes are hand-written in this repo and canonical; the tolerant reading is
    ``skills/hydrate/SKILL.md``'s job, over files this repo does not own.

    Born red at the tree this test was authored on: ``CLAUDE.md`` does not yet
    carry the marker. Green once #594's ``CLAUDE.md`` edit lands (AC-5).
    """
    source, derived = _pair()
    remainder = derived[len(source) :]
    first_line = remainder.lstrip("\n").split("\n", 1)[0].strip()
    assert first_line == _COPY_END, (
        f"{DERIVED_PATH}'s remainder after the {SPINE_PATH} prefix does not open "
        f"with {_COPY_END!r}; its first line is {first_line!r}"
    )
    assert derived.count(_COPY_END) == 1, (
        f"{DERIVED_PATH} carries {derived.count(_COPY_END)} occurrences of "
        f"{_COPY_END!r}, not exactly one, so the file is not bounded"
    )
