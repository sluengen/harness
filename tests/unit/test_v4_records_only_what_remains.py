"""#435 — the surviving documents describe only what survived (ADR 0015 AC3).

`tests/unit/test_v4_teardown.py` holds the other half of the same decision: the
retired subsystems are gone from the index. Gone from the index is not the same
as gone from the record — a repo can pass every absence assertion while its
`CONTEXT.md` still sends a reader to a deleted file and its process doc still
tells an agent to run a verb that no longer exists. That is the failure this
module measures, and it does so **two ways, because they fail for different
reasons**.

**(a) Reference resolution — the half that binds.** Every repo-relative path the
entry documents name must resolve to a tracked file. This is the assertion that
actually catches a teardown: it is keyed on *the path the document names*, so
deleting a file turns it **red**, never green. A misspelt pattern makes it
resolve fewer paths, which the floor catches; a deleted subject makes it fail
loudly. It cannot be satisfied by an empty tree, an empty file set, or a regex
that matches nothing.

**(b) Retired vocabulary — the prose half.** A document can name no path at all
and still instruct an agent to run `harness close`. So every *sentence* in the
live Markdown surface that uses the retired vocabulary must also mark it as
retired. This half is a prose predicate, and prose predicates are the most
expensive defect class in this repo's history, so it carries the full control
set the pattern demands: a positive control proving the predicate fires on the
wording it forbids, and a negative control proving the sentences that *record*
the retirement stay legal. A guard whose cheapest fix is deleting a true
sentence is worse than no guard.

Both controls run against **synthetic text**, never against a live file. A
control that reads the tree goes silently inert the moment the tree changes —
this teardown found two that already had, and they still read as controls while
flagging nothing.

What is deliberately **not** forbidden is as load-bearing as what is:

* `harness promote` / `/promote` survives. The `dev → staging → main` topology
  and its nightly automation are kept by operator decision; only the audited
  verb that used to drive them is retired, and the command now drives plain git.
* `assurance.trivial_certify` survives. It is a script the *consuming repo*
  supplies, not harness machinery — the certifier that read it was deleted, the
  hook it names was not.

Getting either wrong would delete live guidance, which is why they are stated
here rather than left to be inferred from the token set's silence.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

from tests._gitutil import tracked_files_under
from tests.unit.test_review_discipline_watchlist_entry_currency import _sentences

_REPO_ROOT = Path(__file__).resolve().parents[2]

#: This module names every banned token in order to look for it, so it is its own
#: worst offender and must never be its own subject. The live sweep projects to
#: Markdown, where a ``.py`` module cannot appear — the exclusion is what keeps
#: that true if the projection is ever widened.
_SELF = "tests/unit/test_v4_records_only_what_remains.py"


# ---------------------------------------------------------------------------
# (a) Every path the entry documents name resolves to a tracked file.
# ---------------------------------------------------------------------------

#: The documents an agent is *required* to read before doing anything here:
#: ``CONTEXT.md`` (this repo's values), the canonical process doc and the three
#: byte-identical mirrors a host may load instead, and ``registry.yaml`` (the
#: manifest naming every distributed file). A dangling path in any of these is
#: read as fact by the next agent to start work, which is why these five are the
#: subject rather than the whole tree.
_ENTRY_DOCUMENTS = (
    "CONTEXT.md",
    "process/harness.md",
    "CLAUDE.md",
    "AGENTS.md",
    "GEMINI.md",
    "registry.yaml",
)

#: A path-shaped token: backtick-quoted (```scripts/verify.sh```) or a markdown
#: link target (``](specs/decisions/0015-....md)``). Both forms, because the
#: process doc uses links for its headline pointers and backticks for everything
#: else, and a guard that read only one would silently cover half the file.
_TOKEN = re.compile(r"`([^`\n]+)`|\]\(([^)\s#]+)")

#: What counts as a repo-relative path once extracted. A slash is required, so
#: this never judges a bare filename: ``SPEC.md`` appears throughout the
#: universal guidance as the *consuming* repo's design doc when ``feature_specs``
#: is off, and that reference is correct even though this repo has no such file.
#: Judging bare names would make the guard demand the deletion of true, portable
#: instructions.
_PATH_SHAPED = re.compile(r"[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)*/?")

#: Extensions a named file must carry. Without it, prose like ``pass/fail`` and
#: ``dev/staging`` would be judged as paths.
_FILE_SUFFIXES = (".md", ".py", ".sh", ".js", ".json", ".yaml", ".yml", ".toml", ".html")


def _candidates(text: str) -> list[str]:
    """Every path-shaped token ``text`` names, in order.

    A backticked span is split on whitespace before matching, because the
    documents write invocations rather than bare paths — ``bash
    scripts/verify.sh``, ``uv run --extra dev pytest tests/unit/x.py``. Matching
    the whole span would skip every path that appears inside a command, which is
    most of them in ``CONTEXT.md``.
    """
    found: list[str] = []
    for match in _TOKEN.finditer(text):
        span, link = match.group(1), match.group(2)
        words = span.split() if span is not None else [link]
        found += [word for word in words if _PATH_SHAPED.fullmatch(word)]
    return found


#: A ``registry.yaml`` entry key: an indented ``<path>: { ... }`` line. The
#: registry names its paths as YAML keys rather than in prose, so the
#: backtick/link extractor above finds nothing in it — without this it would sit
#: in the subject list looking covered while contributing zero assertions, which
#: is the shape this whole module exists to catch.
_REGISTRY_KEY = re.compile(r"^\s+['\"]?([A-Za-z0-9_./-]+)['\"]?:\s*\{", re.MULTILINE)

#: The blocks whose keys are paths. ``profiles:`` is deliberately excluded: its
#: entries are profile names, and one of them carries an inline
#: ``default_layers: { ... }`` map that matches the key pattern exactly. Scoping
#: by block rather than tightening the pattern keeps the pattern able to read
#: every real entry spelling.
_PATH_BLOCKS = ("\nfiles:", "\nmeta:")


def _declared_paths(text: str) -> list[str]:
    """Every path ``registry.yaml`` declares as a distributed or meta file."""
    found: list[str] = []
    for block in _PATH_BLOCKS:
        if block not in text:
            continue
        body = text[text.index(block) + len(block) :]
        end = re.search(r"^\S", body, re.MULTILINE)
        found += _REGISTRY_KEY.findall(body[: end.start()] if end else body)
    return found


def _tracked_paths() -> tuple[frozenset[str], frozenset[str]]:
    """Every tracked file, and every directory holding one, repo-relative.

    Directories are derived rather than listed: ``CONTEXT.md``'s ``paths:``
    block names ``tests/``, ``specs/proposals/`` and friends, which are real
    destinations a reader follows and must resolve just as a file does.
    """
    files = frozenset(
        str(path.relative_to(_REPO_ROOT)) for path in tracked_files_under(".")
    )
    directories = frozenset(
        f"{parent}/"
        for name in files
        for parent in Path(name).parents
        if str(parent) != "."
    )
    return files, directories


def _unresolved(
    text: str, *, files: frozenset[str], directories: frozenset[str]
) -> tuple[list[str], int]:
    """``(paths that resolve to nothing, count that resolved)`` for one document.

    One function, called by the live sweep and by both controls below, so the
    controls exercise the predicate the sweep runs rather than a re-spelling of
    it. Returning the resolved count alongside the failures is what lets the
    caller assert a floor: a predicate that stopped matching would report no
    failures *and* no resolutions, and only one of those is asserted upward.
    """
    dangling: list[str] = []
    resolved = 0
    for raw in _candidates(text):
        if raw.endswith("/"):
            target, known = raw, directories
        elif "/" in raw and raw.endswith(_FILE_SUFFIXES):
            target, known = raw, files
        else:
            continue
        if target in known:
            resolved += 1
        else:
            dangling.append(target)
    return dangling, resolved


#: The floor under the **prose** half: paths named in backticks and links. Well
#: below what the entry documents actually carry, and there only to fail an
#: extraction that stopped extracting — without it, a broken ``_TOKEN`` or
#: ``_PATH_SHAPED`` reports zero dangling paths, which reads exactly like a
#: clean tree.
#:
#: Set just under the 77 measured across the six entry documents at the teardown.
#: It sat at 30 against that same population, which is slack enough to swallow
#: ``CONTEXT.md`` — the document contributing 37 of the 77 — without the floor
#: moving. A floor that survives losing its largest subject is not measuring the
#: extraction, only asserting that something was extracted.
_RESOLUTION_FLOOR = 72

#: The floor under the **registry** half, which is counted separately and not
#: pooled with the one above. Mutating ``_TOKEN`` to match nothing was the entry
#: that found this: against a single pooled floor the registry's forty-odd keys
#: kept the total over the line, so the prose extractor could die completely and
#: the sweep stayed green. Two halves that can fail independently need two
#: floors, or the larger one masks the other.
#:
#: Set just under the 60 keys measured at the teardown, for the reason above: at
#: 40 the pattern could stop reading a third of the registry and stay green.
_REGISTRY_FLOOR = 55


def test_every_path_the_entry_documents_name_resolves() -> None:
    """No required-reading document sends an agent to a file that is not there."""
    files, directories = _tracked_paths()
    dangling: list[str] = []
    resolved = 0
    for relpath in _ENTRY_DOCUMENTS:
        text = (_REPO_ROOT / relpath).read_text(encoding="utf-8")
        found, count = _unresolved(text, files=files, directories=directories)
        dangling += [f"{relpath}: {path}" for path in found]
        resolved += count
    assert resolved >= _RESOLUTION_FLOOR, (
        f"only {resolved} repo paths resolved from the prose of "
        f"{list(_ENTRY_DOCUMENTS)} — the extraction has stopped finding them, so "
        f"the dangling check below is passing over almost nothing"
    )

    # The registry names its paths as YAML keys, which the prose extractor
    # cannot see. Judged against the index rather than the filesystem, so a
    # deleted-but-still-on-disk file cannot satisfy it.
    declared = _declared_paths((_REPO_ROOT / "registry.yaml").read_text(encoding="utf-8"))
    assert len(declared) >= _REGISTRY_FLOOR, (
        f"only {len(declared)} registry entry keys parsed — the key pattern has "
        f"stopped matching, so the registry contributes nothing to this sweep"
    )
    dangling += [f"registry.yaml: {path}" for path in declared if path not in files]
    resolved += sum(1 for path in declared if path in files)

    assert not dangling, (
        "these required-reading documents name repo paths that resolve to no "
        "tracked file. ADR 0015 deleted a great deal; a pointer left behind is "
        "read as fact by the next agent to start work:\n  " + "\n  ".join(dangling)
    )
    assert resolved >= _RESOLUTION_FLOOR + _REGISTRY_FLOOR, (
        f"only {resolved} repo paths resolved in total across "
        f"{list(_ENTRY_DOCUMENTS)} — both halves passed their own floor but the "
        f"combined count is below the sum, which should be impossible"
    )


def test_the_registry_key_pattern_reads_the_shapes_the_file_uses() -> None:
    """Positive control for the registry half, on synthetic YAML.

    Every spelling the file actually uses, because the key extractor is the only
    thing standing between ``registry.yaml`` and a silent zero: an entry it
    cannot read is an entry nothing checks. Three lines must **not** parse — a
    comment, a block header, and ``profiles:``'s inline ``default_layers`` map,
    which matches the entry pattern exactly and is the live case that made the
    block scoping necessary rather than tidy.
    """
    yaml = (
        "registry_format: 1\n"
        "profiles:\n"
        "  harness:\n"
        "    default_layers: { design_system: false, feature_specs: false }\n"
        "files:\n"
        "  skills/code-quality/SKILL.md: { id: code-quality, version: 1.0.0 }\n"
        '  "commands/build.md": { id: build, version: 1.11.0 }\n'
        "  'agents/dev.md': { id: dev, version: 0.1.0 }\n"
        "meta:\n"
        "  BOOTSTRAP.md: { id: bootstrap, version: 0.1.0 }\n"
        "  # skills/retired/SKILL.md: { id: retired }\n"
    )
    assert _declared_paths(yaml) == [
        "skills/code-quality/SKILL.md",
        "commands/build.md",
        "agents/dev.md",
        "BOOTSTRAP.md",
    ], _declared_paths(yaml)


def test_the_resolver_flags_a_path_that_was_deleted() -> None:
    """Positive control: a named path that is not tracked is reported.

    Synthetic, and deliberately spelled with paths this teardown really removed,
    because the shape that matters is a *plausible* pointer — one that read
    correctly the day it was written.
    """
    text = (
        "The as-built record is `specs/features/verb-model.md`, and the CLI "
        "contract is [cli-surface](specs/features/cli-surface.md). Cadence "
        "bounds live in `scripts/cadence.py`."
    )
    dangling, resolved = _unresolved(
        text, files=frozenset({"CONTEXT.md"}), directories=frozenset()
    )
    assert dangling == [
        "specs/features/verb-model.md",
        "specs/features/cli-surface.md",
        "scripts/cadence.py",
    ], dangling
    assert resolved == 0, resolved


def test_the_resolver_leaves_portable_and_placeholder_references_alone() -> None:
    """Negative control: the three shapes that must never be judged.

    Each is a reference the universal guidance makes on purpose, and each would
    be a *false* failure — the cheapest fix for which is deleting a correct,
    portable instruction:

    * a bare filename (``SPEC.md``, ``CONTEXT.md``) names the **consuming**
      repo's file, not one of ours;
    * a placeholder (``specs/features/<feature>.md``) is a shape a consumer
      fills in;
    * a real tracked path must resolve, or the control proves nothing about the
      discrimination it claims to make.
    """
    text = (
        "Read `SPEC.md` when `feature_specs` is off, otherwise the record is "
        "`specs/features/<feature>.md`. The gate is `bash scripts/verify.sh` "
        "and the tests live in `tests/`. Verdicts are `pass/fail`."
    )
    dangling, resolved = _unresolved(
        text,
        files=frozenset({"scripts/verify.sh"}),
        directories=frozenset({"tests/"}),
    )
    assert dangling == [], dangling
    assert resolved == 2, (
        f"expected the two real paths to resolve, got {resolved} — a control "
        f"that resolves nothing proves only that nothing was judged"
    )


# ---------------------------------------------------------------------------
# (b) No live document still instructs an agent in the retired vocabulary.
# ---------------------------------------------------------------------------

#: Paths whose text is a **historical record** and may describe the runtime as
#: it was, in the present tense of its own day. Exempt by *category*, not by
#: filename, so a new proposal, assessment, decision or retired spec is covered
#: the day it lands rather than the day someone extends a list.
#:
#: ``specs/retired/`` is the load-bearing one here: #435 moved six as-built
#: records into it, and their whole value is that they still describe the verbs,
#: the ledger and the container exactly as they worked. Their dated supersede
#: banners are what makes the exemption honest, and
#: ``tests/unit/test_docs_consistency.py`` requires one on every file in the
#: directory, so the exemption cannot go silent.
_HISTORICAL_PREFIXES = (
    "assessments/",
    "specs/proposals/",
    "specs/retired/",
    "specs/decisions/",
)

#: The vocabulary of the retired runtime: the audited verbs, the wrapper's
#: install path, the repo's own unattended-routine command, the ledger, the loop
#: those verbs formed, and the skill ADR 0015 retires by name.
#:
#: Two absences are deliberate and are the reason this set is hand-written
#: rather than derived from "every word the teardown deleted":
#:
#: * ``harness promote`` is **not** here. The promotion topology and its nightly
#:   automation are kept by operator decision; the command survives, rewritten
#:   to plain git. Banning it would delete a live release path's documentation.
#: * ``assurance.trivial_certify`` is **not** here. It names a script the
#:   *consuming repo* supplies; the harness-side certifier that read it is gone,
#:   the hook is not.
_RETIRED_TOKENS = re.compile(
    r"harness\s+(?:run|start|review|close|serve|doctor|defer|release|certify"
    r"|reclaim|checkpoint|worktrees)\b"
    r"|~/bin/harness"
    r"|/harness routine"
    r"|the run ledger"
    r"|verb loop"
    r"|CLI verb"
    r"|harness engine"
    r"|spend breaker"
    r"|guidance-coherence",
    re.IGNORECASE,
)

#: **Why the token set is anchored, and what it therefore cannot see.** The verb
#: alternations require the literal word ``harness`` in front, because every one
#: of them — ``start``, ``review``, ``close``, ``ship`` — is *also* the name of a
#: live command. A predicate keyed on the bare word would flag the correct
#: instruction on nearly every page, and the cheapest fix for that failure is
#: deleting true prose. The three phrases added by the review pass
#: (``CLI verb``, ``harness engine``, ``spend breaker``) are exactly the shapes
#: that gap let through: unambiguous names for retired machinery that collide
#: with no live command.
#:
#: ``audited verb`` is deliberately **not** here, and the reason is the same one
#: that keeps the marker set narrow. Two superseded Decision blocks — inside
#: files that are otherwise live — use the phrase to state what was decided. The
#: blocks carry dated supersede notes, but this sweep's unit is the *sentence*,
#: so it cannot see a block-level note, and adding the phrase would make its
#: cheapest fix an edit to a historical record. A sweep that rewrites history to
#: stay green is not measuring the live surface.

#: Words that mark a sentence as *recording* the retirement rather than
#: instructing in it. A live document may — and several must — say the mechanism
#: existed and no longer does.
#:
#: Citing the ticket is deliberately not a marker. ``#435`` next to a claim says
#: nothing about whether the claim is being made or retired; the sentence has to
#: say what happened.
_RETIREMENT_MARKERS = re.compile(
    r"\bretire\w*|\bsupersed\w*|\bno longer\b|\bwas\b|\bwere\b|\buntil\b"
    r"|\breplac\w*|\bdeleted\b|\bremoved\b|\bformerly\b|\binert\b|\bnothing reads\b"
    r"|\bpreviously\b",
    re.IGNORECASE,
)


#: Suffixes the live projection reads. ``.json`` is here because the review pass
#: found the settings files carrying paragraph-long permission rationales naming
#: the retired routines — distributed guidance an agent reads as current fact,
#: and wholly outside a Markdown-only projection. That was a gap in the
#: projection, not a scope choice: nothing about a permission rationale makes it
#: less of a live instruction for being written inside a JSON string.
_LIVE_SUFFIXES = (".md", ".json")


def _live_markdown() -> list[str]:
    """Every tracked prose file that can carry a *live* instruction."""
    return sorted(
        rel
        for rel in (
            str(path.relative_to(_REPO_ROOT)) for path in tracked_files_under(".")
        )
        if rel.endswith(_LIVE_SUFFIXES)
        and not rel.startswith(_HISTORICAL_PREFIXES)
        and rel != _SELF
    )


def _classify_runtime_sentences(text: str) -> tuple[list[str], int]:
    """``(sentences instructing in the retired vocabulary, count recording it)``.

    The one home of the sweep's predicate. The live sweep needs both halves — the
    offenders it fails on and the compliant count its floor asserts upward — and
    the controls need the offender half; returning both from one function is what
    stops the sweep re-spelling the predicate its controls certify. It did
    re-spell it: the loop below carried its own
    ``_RETIRED_TOKENS`` / ``_RETIREMENT_MARKERS`` conditions, so the controls and
    the live path were near-twins rather than the same code, and a change to one
    condition could pass the controls while the sweep read differently.
    """
    offenders: list[str] = []
    recorded = 0
    for sentence in _sentences(text):
        if not _RETIRED_TOKENS.search(sentence):
            continue
        if _RETIREMENT_MARKERS.search(sentence):
            recorded += 1
        else:
            offenders.append(sentence)
    return offenders, recorded


def _live_runtime_instructions(text: str) -> list[str]:
    """Sentences of ``text`` using the retired vocabulary without retiring it.

    The offender half of :func:`_classify_runtime_sentences`, so a control that
    calls this exercises exactly the code the live sweep runs.
    """
    return _classify_runtime_sentences(text)[0]


#: The floor under the live sweep's *compliant* count. The retirement is a large
#: event and the records that describe it are supposed to name what went; if
#: almost nothing mentions the vocabulary at all, the token set has stopped
#: recognising it and the offender check is passing over nothing.
#:
#: Set just under the 9 measured at the teardown. It sat at 6 with the same
#: population, which is enough slack that a third of the records could stop being
#: recognised without the floor noticing — the same defect the two floors above
#: carried, one order smaller.
_RECORDED_FLOOR = 8


def test_no_live_document_still_instructs_in_the_retired_vocabulary() -> None:
    """The retired runtime survives only as a recorded retirement (AC3)."""
    offenders: list[str] = []
    recorded = 0
    for relpath in _live_markdown():
        text = (_REPO_ROOT / relpath).read_text(encoding="utf-8", errors="replace")
        found, count = _classify_runtime_sentences(text)
        recorded += count
        offenders += [f"{relpath}: {' '.join(s.split())[:160]}" for s in found]

    assert not offenders, (
        "ADR 0015 retired the verbs, the wrapper, the ledger and the "
        "`guidance-coherence` skill. These live sentences still present them as "
        "something an agent can do:\n  " + "\n  ".join(offenders)
    )
    assert recorded >= _RECORDED_FLOOR, (
        f"only {recorded} live sentences mention the retired runtime at all — "
        f"the records are supposed to *record* what went, so this few means the "
        f"token set has stopped recognising the vocabulary and the check above "
        f"is passing over nothing"
    )


def test_the_predicate_catches_the_instruction_it_forbids() -> None:
    """Positive control: the detector fires on the wording it bans.

    Without it the sweep is green on a token set that matches nothing, and the
    ``recorded`` floor would not save it — a floor counts *compliant* sentences,
    so a predicate that stopped matching drives both counts to zero and only one
    of them is asserted upward.

    **One token per sentence, deliberately.** The sweep's unit is the sentence,
    so a control that packs four banned tokens into one sentence proves only
    that *at least one* of them is still recognised — dropping the other three
    from the pattern would leave it green. Written this way, every alternation
    in :data:`_RETIRED_TOKENS` has its own sentence and its own way to fail, and
    the mutation table can retire them one at a time.
    """
    live = (
        "Run `harness start CAL-42` to open it. "
        "Then `harness review --run-id <id>` records a verdict. "
        "Finally `harness close` merges the branch. "
        "The host process is `harness serve`. "
        "Check the install with `harness doctor`. "
        "Park a blocked ticket with `harness defer <TICKET>`. "
        "Cut an image with `harness release`. "
        "A trivial diff goes through `harness certify`. "
        "A dead run is recovered by `harness reclaim --stale`. "
        "Bank partial progress with `harness checkpoint`. "
        "Sweep stale trees with `harness worktrees cleanup`. "
        "The wrapper is on PATH as `~/bin/harness`. "
        "`/harness routine build` drives the hourly tick. "
        "Every mutation is appended to the run ledger. "
        "The verb loop is what an orchestrating agent drives. "
        "Dispatch never happens inside the deterministic start CLI verb. "
        "The harness engine owns container construction. "
        "The extra agent counts against the spend breaker. "
        "`/assess system` pulls `guidance-coherence` for its standards."
    )
    sentences = _sentences(live)
    assert len(sentences) == 19, sentences
    caught = _live_runtime_instructions(live)
    assert caught == sentences, (
        f"the predicate missed a sentence instructing in the retired runtime: "
        f"expected all {len(sentences)}, caught {len(caught)}. Missed: "
        f"{[s for s in sentences if s not in caught]}"
    )


def test_prose_that_records_the_retirement_stays_legal() -> None:
    """Negative control: a true sentence about what went is not a violation.

    This is the discrimination the guard exists to make. Every record updated by
    this teardown has to *name* what was retired in order to say it is gone, and
    the ADR describes the whole of it. A predicate keyed on the bare vocabulary
    would flag all of them, and the cheapest fix for that failure is to delete a
    correct explanation rather than a false instruction.

    **One marker per sentence, and no sentence carrying a second.** Mutating
    ``\\breplac\\w*`` out of the pattern is what forced this: every sentence that
    used it also said "was", so the edit changed nothing and the entry reported
    ``SURVIVED (UNPROVEN)`` — the control was passing for a reason other than
    the marker under test. Written this way, retiring any one alternation turns
    exactly one sentence into a false offender, so every marker has its own way
    to fail.

    The last two entries are the operator decisions the token set deliberately
    leaves out. They carry **no** retirement marker at all and must still pass,
    because they name live commands in the present tense — a different reason
    from every sentence above them, and one worth checking rather than assuming.
    """
    for sentence in (
        # One retirement marker each; nothing else in the marker set appears.
        "ADR 0015 retires `harness close`.",
        "The `guidance-coherence` skill is superseded by ADR 0015.",
        "`harness serve` no longer exists.",
        "`~/bin/harness` was the developer wrapper's install path.",
        "The `harness worktrees` sweeps were host-side chores.",
        "`/harness routine build` drove the hourly tick until ADR 0015.",
        "`/routine` replaces `/harness routine build`.",
        "`harness certify` is deleted.",
        "`harness reclaim` is removed.",
        "`harness checkpoint`, formerly a mid-run banking step.",
        "A `harness defer` invocation is inert.",
        "Nothing reads the run ledger.",
        "Previously an hourly tick shelled out to `harness start`.",
        # No marker at all, and correct: these commands are not retired.
        "Run `/promote dev to staging` to drive a promotion with plain git.",
        "A `trivial` run is certified by the repo's `assurance.trivial_certify` "
        "command, which fails closed.",
    ):
        assert not _live_runtime_instructions(sentence), sentence


def test_the_sweep_reads_a_populated_live_surface() -> None:
    """The projection is not empty, and does not include this module.

    Both halves matter. An empty ``_live_markdown()`` makes the sweep vacuous —
    it would report no offenders because it read no files. And this module
    contains every banned token as a literal, so if the projection ever widened
    to reach it, the sweep would flag itself and the obvious fix would be to
    weaken the token set.
    """
    live = _live_markdown()
    assert len(live) >= 85, (
        f"only {len(live)} live Markdown files projected — the sweep is reading "
        f"almost nothing: {live}"
    )
    # 85 is just under the 90 measured at the teardown. It sat at 40 against that
    # same population, which is slack enough to lose the entire `skills/` tree —
    # or every command doc — without the floor moving, and a projection that
    # silently stopped reaching a tree is exactly what this floor exists for.
    assert _SELF not in live, "this module must never be its own subject"
    # The projection's *width* is pinned, not only its size. Narrowing
    # `_LIVE_SUFFIXES` back to Markdown drops every distributed settings file
    # from the sweep, and the count floor above does not notice: four files out
    # of ninety-odd is well inside its slack. The settings pair is named because
    # it is the surface the review pass found unswept, carrying paragraph-long
    # permission rationales an agent reads as current fact.
    assert ".json" in _LIVE_SUFFIXES, (
        "the live projection stopped reading JSON. `settings/harness.json` and "
        "`.claude/settings.json` are distributed guidance whose prose lives "
        "inside JSON strings; a Markdown-only projection never sees them."
    )
    for settings in ("settings/harness.json", ".claude/settings.json"):
        assert settings in live, f"{settings} is not in the swept surface"
    assert not any(rel.startswith(_HISTORICAL_PREFIXES) for rel in live), (
        "a historical record leaked into the live projection; those files "
        "describe the runtime as it worked and must stay exempt"
    )


def test_the_historical_exemption_names_real_trees() -> None:
    """Every exempt prefix holds tracked files.

    An exemption over an empty directory is a hole nothing fills: it silently
    excuses nothing today and would excuse anything dropped there tomorrow
    without the banner rule that justifies the exemption ever being applied.
    """
    for prefix in _HISTORICAL_PREFIXES:
        assert tracked_files_under(prefix.rstrip("/")), (
            f"{prefix} is exempt from the retired-vocabulary sweep but holds no "
            f"tracked file — the exemption is measuring nothing"
        )


def test_the_historical_exemption_is_exactly_these_four_trees() -> None:
    """The exemption list is pinned by membership, not merely by non-emptiness.

    Both this and :data:`_RETIREMENT_MARKERS` below are **grants**, and a sweep
    keyed on grants fails *open* when one is appended: adding ``"skills/"`` here
    would exempt the whole distributed skill set from the retired-vocabulary
    sweep, and every assertion in this module would stay green — the
    non-emptiness check above passes on a wider list just as happily as on this
    one. Pinning the set is what makes an addition a decision someone has to
    write down rather than a silent widening.
    """
    assert _HISTORICAL_PREFIXES == (
        "assessments/",
        "specs/proposals/",
        "specs/retired/",
        "specs/decisions/",
    ), (
        f"the historical exemption changed to {_HISTORICAL_PREFIXES}. Each entry "
        f"excuses a whole tree from the sweep; adding one is a decision about "
        f"what stops being checked, so it belongs in this assertion too."
    )


def test_the_retirement_markers_are_pinned() -> None:
    r"""The marker vocabulary is pinned, for the same fail-open reason.

    A marker excuses a sentence from the sweep. Appending an alternation that
    matches common prose — ``\bhook\w*`` was the one an independent mutation
    table found surviving — excuses every sentence containing that word, so a
    live instruction to run a retired verb would pass as long as it also
    mentioned a hook. The negative control below proves the markers that *are*
    here work; only a membership pin catches one that should not be.
    """
    assert _RETIREMENT_MARKERS.pattern == (
        r"\bretire\w*|\bsupersed\w*|\bno longer\b|\bwas\b|\bwere\b|\buntil\b"
        r"|\breplac\w*|\bdeleted\b|\bremoved\b|\bformerly\b|\binert\b|\bnothing reads\b"
        r"|\bpreviously\b"
    ), (
        f"the retirement-marker set changed to {_RETIREMENT_MARKERS.pattern!r}. "
        f"Every alternation is a grant that excuses a sentence from the sweep — "
        f"widening it narrows what this module checks, silently."
    )


#: Every entry document, with the reason it is required reading. A **membership**
#: assertion, because ``_ENTRY_DOCUMENTS`` is hand-written and dropping an entry
#: from it removes a document from the resolution sweep without failing anything:
#: the floor absorbs the loss, the dangling check simply stops reading the file,
#: and both stay green. ``CONTEXT.md`` is the one that mattered — it contributes
#: 37 of the 77 resolved paths, so it is both the most valuable subject and the
#: cheapest to lose unnoticed.
_REQUIRED_ENTRY_DOCUMENTS = {
    "CONTEXT.md": "this repo's own values, and the densest source of repo paths",
    "process/harness.md": "the canonical process doc every agent reads",
    "registry.yaml": "the manifest naming every distributed file",
    "CLAUDE.md": "a byte-identical mirror an agent host may load instead",
    "AGENTS.md": "a byte-identical mirror an agent host may load instead",
    "GEMINI.md": "a byte-identical mirror an agent host may load instead",
}


def test_the_entry_documents_are_tracked_and_mirrored() -> None:
    """The (a) subject list names real files, and covers every required document.

    ``_ENTRY_DOCUMENTS`` is hand-written, so a typo in it silently drops a
    document from the resolution sweep while every assertion stays green. Git is
    asked directly rather than the filesystem, so an untracked scratch copy
    cannot satisfy it.
    """
    tracked = subprocess.run(
        ["git", "-C", str(_REPO_ROOT), "ls-files", "--error-unmatch", *_ENTRY_DOCUMENTS],
        capture_output=True,
        text=True,
        check=False,
    )
    assert tracked.returncode == 0, (
        f"an entry document is not tracked under the name this module uses: "
        f"{tracked.stderr.strip()}"
    )
    for required, reason in _REQUIRED_ENTRY_DOCUMENTS.items():
        assert required in _ENTRY_DOCUMENTS, (
            f"{required} dropped out of the resolution sweep's subject list. It "
            f"is required reading: {reason}. Removing it costs nothing visible — "
            f"no assertion fails, the sweep just stops reading the file."
        )
