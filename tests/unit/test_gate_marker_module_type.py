"""#500 — the gate-marker helper must parse as CommonJS in an ESM consumer repo.

Admission (ADR 0017 D5): class (a) — a shipped program executed under a
consumer-shaped root, plus class (d)/(e) over the one-key manifest that makes it
load.

The #302 mechanism, applied to a second directory. Node resolves a ``.js`` file's
module type from the **nearest** ``package.json`` walking up from the file. The
harness ships ``scripts/gate-marker.js`` as bare ``.js``, and ``commands/init.md``
copies it into a consuming repo's ``scripts/``, so without a manifest that walk
terminates at *that repo's root* — a root the harness does not control. Where it
declares ``"type": "module"`` (any modern TS/Vite/ESM repo), Node parses the
helper as ESM and it dies at its first ``require``.

That failure is **loud** here, which is what makes the manifest a correctness fix
rather than a silent-disarm fix: every operation of this CLI has an observable on
its success path, a load failure is an uncaught error before ``main()`` runs, and
neither of ``scripts/verify.sh``'s two invocations of it can fail quietly. The
preflight is wrapped in ``|| _preflight_status=$?`` — deliberately, so ``set -e``
never sees it — and any non-zero status that wrapper captures leaves the gate at
the reserved exit 97; the ``write`` on the success path is unguarded, so there
``set -e`` ends the gate before it prints its success line. There is no path on
which a mis-typed module produces a marker or a green gate. #302's own subject
was the opposite — ``prompt-guard.js`` exited 0 with an approving payload having
scanned nothing — and the distinction is worth stating because it is what makes
this the cheaper of the two problems, not because it makes it acceptable: a gate
that cannot run is a gate.

**Why ``.js`` with a manifest and not ``.cjs``.** On the merits ``.cjs`` is the
better answer for a file with no installed callers: the extension is
authoritative regardless of any manifest and has no directory-wide side effect
anywhere. It is rejected because the ticket names ``.js`` verbatim, and the
rejection is recorded with its reason in ADR 0018 rather than left as folklore.
The side effect the manifest defers — in a consumer whose ``scripts/`` already
holds ESM ``.js`` siblings, this manifest retypes *their* files — belongs to
#501, which owns hydration.

Both operands below are the **git index**, deliberately: the subject is what a
fresh clone and a hydrating consumer receive, and a guard over the working file
passes on the machine that wrote it (#484). That puts this module outside
``scripts/mutate.py``'s reach — its mutations are proved by staged probe (#490).

**Three guards here are admitted by argument, not by class (#510).**
:func:`test_hydration_rejects_mixed_module_sources_for_every_manifest_suffix`,
:func:`test_the_hydration_predicate_states_absence_is_not_consent`, and their
floor read ``commands/init.md`` and assert what that document *says*, which is
none of ADR 0017 D5's five admitted classes. **The exception and its retirement
condition are recorded where the policy lives — ADR 0018's Consequences — not
here**, so a future ``/assess`` reads the bound rather than the precedent; this
note is a pointer to it, and the consequence it carries is that #510's AC-5 and
AC-6 are discharged by a documentation guard rather than by behavioural
coverage.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from tests._gitutil import indexed_text

MANIFEST = "scripts/package.json"
HELPER = "scripts/gate-marker.js"

#: The **one** canonical home of the hydration procedure. ``skills/command-init``
#: and its ``.codex`` mirror are generated from this file and already held to it
#: byte-for-byte by the Codex drift guard, so parametrizing over all three
#: measured one document three times.
HYDRATION = "commands/init.md"

#: The heading that separates the two procedures inside that document. Used to
#: derive the corpus floor below rather than to hardcode a paragraph count.
REFRESH_HEADING = "## `--refresh`"

#: How the closed-world predicate is recognised in either procedure.
PREDICATE = "recognised managed helper"

#: The phrase that names *what* the predicate ranges over. A paragraph carrying
#: :data:`PREDICATE` without it has kept the words and lost the subject.
ANCHOR = "immediate module-bearing source"

#: The predicate's **polarity**, in the two spellings the two procedures use.
#: Required because the tokens above survive a rewrite that says the opposite —
#: that absence of ``*.js`` *is* consent — and a guard that cannot tell a rule
#: from its negation is not holding the rule (craft.md → *Mutate the rule into
#: its opposite, not only out of existence*).
CONSENT_NEGATIONS = ("does not establish consent", "is not consent")

#: The other half of that polarity: the retention clause must not be negated.
#: ``"retains every gate asset" in paragraph`` is satisfied by *"never retains
#: every gate asset"*, which inverts the instruction while passing the token
#: check.
NEGATED_RETENTION = re.compile(r"\b(?:not|never|no longer|cannot|rarely)\s+retains?\b")

MODULE_SUFFIXES = ("js", "mjs", "cjs", "ts", "mts", "cts")


def _node() -> str:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node not available")
    return node


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=repo, check=True, capture_output=True, text=True
    ).stdout.strip()


def _esm_consumer(tmp_path: Path) -> Path:
    """A repository whose root declares ESM, carrying the two shipped files.

    Written out of the index rather than hand-authored, so deleting or retyping
    the real manifest propagates here and the positive case goes red instead of
    quietly testing a stand-in.
    """
    fixture = tmp_path / "consumer"
    (fixture / "scripts").mkdir(parents=True)
    (fixture / "package.json").write_text(json.dumps({"type": "module"}) + "\n")
    for relative in (HELPER, MANIFEST):
        (fixture / relative).write_text(indexed_text(relative), encoding="utf-8")
    _git(fixture, "init", "-q", "--initial-branch=main")
    _git(fixture, "config", "user.email", "t@example.com")
    _git(fixture, "config", "user.name", "t")
    _git(fixture, "add", "-A")
    _git(fixture, "commit", "-q", "-m", "consumer")
    return fixture


def _run_tree(fixture: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [_node(), HELPER, "tree"],
        cwd=fixture,
        capture_output=True,
        text=True,
        timeout=60,
    )


def test_the_manifest_declares_commonjs() -> None:
    """Parsed, not string-matched, so a ``"type": "module"`` typo fails here."""
    assert json.loads(indexed_text(MANIFEST))["type"] == "commonjs"


def test_the_helper_answers_under_an_esm_root(tmp_path: Path) -> None:
    """The behaviour, not the load: an answer, not merely an exit status.

    Asserting exit 0 alone would be satisfied by a helper that printed nothing,
    so the observable is the tree oid the consumer's gate would record.
    """
    proc = _run_tree(_esm_consumer(tmp_path))

    assert proc.returncode == 0, (
        f"the helper did not run in a consumer repo whose root package.json "
        f'declares "type": "module": {proc.stderr.strip()!r}'
    )
    assert len(proc.stdout.strip()) == 40, (
        f"the helper exited 0 without printing a tree oid: {proc.stdout!r}"
    )


def test_removing_the_manifest_breaks_the_helper_loudly(tmp_path: Path) -> None:
    """What binds the case above to the shipped manifest.

    Without this, the positive case would also pass in a repo that has no ESM
    root at all and would prove nothing. Loudness is asserted as well as failure,
    and stderr is where the loudness has to land: a module-type load failure is
    an uncaught error, so it exits 1, and ``verify.sh``'s wrapper reserves exit
    2 for a refusal the helper itself reported and routes everything else to
    *the gate-marker helper could not run … exited 1*. The wrapper can therefore
    say only that the helper exited non-zero, which is why stderr is asserted
    rather than the exit status alone: stderr is where the cause appears at all,
    as Node's ``require is not defined`` ReferenceError.
    """
    fixture = _esm_consumer(tmp_path)
    (fixture / MANIFEST).unlink()

    proc = _run_tree(fixture)

    assert proc.returncode != 0, (
        "the helper still ran with scripts/package.json removed, so the fixture "
        "is not exercising module resolution and the positive case proves nothing"
    )
    assert proc.stderr.strip(), "the helper failed to load and said nothing about it"
    assert proc.stdout.strip() == "", (
        f"the helper printed an answer it could not have computed: {proc.stdout!r}"
    )


def _predicate_paragraphs() -> dict[str, list[str]]:
    """The closed-world predicate as it appears in each of the two procedures.

    The corpus floor is **derived**, not counted: ``commands/init.md`` carries
    two hydration procedures, first-time setup and ``--refresh``, split by one
    heading, and each owns a copy of the predicate. Filtering the whole document
    by a phrase and then asserting ``all(...)`` is the shape that reads green
    over an empty list — delete the phrase and the corpus shrinks to nothing
    while every assertion still holds (craft.md → *``all()`` over a possibly-
    empty iterable is constant-true*). Splitting first means a deleted predicate
    empties *one named half* and fails there.
    """
    text = indexed_text(HYDRATION)
    head, marker, tail = text.partition(REFRESH_HEADING)
    assert marker, f"{HYDRATION} no longer separates its procedures with {REFRESH_HEADING!r}"
    return {
        "first-time setup": [p for p in head.split("\n\n") if PREDICATE in p],
        "--refresh": [p for p in tail.split("\n\n") if PREDICATE in p],
    }


def test_both_hydration_procedures_carry_the_closed_world_predicate() -> None:
    """The floor for the parametrized guard below.

    Each procedure must carry the predicate, so a hydration path that quietly
    lost its classification step is a red test naming the half it went missing
    from. **Presence and an anchor, never a count**: pinning the cardinality at
    one paragraph apiece makes a legitimate second paragraph red, and the reflex
    repair is to bump the number, which is how a floor decays into decoration
    (craft.md → *Floors decay into decoration*). The anchor is what stops the
    weaker assertion from passing on a paragraph that kept the phrase and lost
    the subject.
    """
    found = _predicate_paragraphs()

    for name, paragraphs in found.items():
        assert paragraphs, (
            f"{HYDRATION} ({name}) no longer states the closed-world predicate "
            f"{PREDICATE!r} anywhere in that procedure"
        )
        assert any(ANCHOR in paragraph for paragraph in paragraphs), (
            f"{HYDRATION} ({name}) states {PREDICATE!r} without naming what it "
            f"ranges over ({ANCHOR!r})"
        )


def test_the_hydration_predicate_states_absence_is_not_consent() -> None:
    """#510 AC-5: the predicate is *positive*, and says so in both directions.

    The suffix guard below checks that the vocabulary is present. Vocabulary is
    polarity-blind: rewriting the paragraph to say that absence of ``*.js`` **is**
    consent, or that an unclassifiable directory does **not** retain its gate
    assets, keeps every required token and inverts the instruction an agent
    follows. Each assertion here has its own exclusive killer — delete the
    negative clause, or negate the retention clause — which is what the token
    checks cannot do.
    """
    for procedure, paragraphs in _predicate_paragraphs().items():
        for paragraph in paragraphs:
            assert any(clause in paragraph for clause in CONSENT_NEGATIONS), (
                f"{HYDRATION} ({procedure}) states the closed-world predicate "
                f"without saying that absence is not consent (one of "
                f"{CONSENT_NEGATIONS!r})"
            )
            negated = NEGATED_RETENTION.search(paragraph)
            assert negated is None, (
                f"{HYDRATION} ({procedure}) negates the retention clause "
                f"({negated.group(0)!r}), inverting what hydration does with an "
                "unclassifiable directory"
            )


@pytest.mark.parametrize("suffix", MODULE_SUFFIXES)
def test_hydration_rejects_mixed_module_sources_for_every_manifest_suffix(suffix: str) -> None:
    """#510 AC-5/AC-6: a manifest retypes each listed sibling, not only ``*.js``.

    Hydration is an instruction to an agent, not a program, so this reads the one
    canonical document rather than executing anything: it is a **documentation
    guard**, and ADR 0017 D5 does not admit a class for it — see the module's
    closing note. What it can hold mechanically is that both procedures still
    enumerate every suffix ``scripts/package.json`` can retype, and still say
    that anything else retains the assets *and names the blocker*, which is the
    half of AC-5 a reader would otherwise take on trust.

    The constraint this imposes on the document, said here so a future author
    reads a red as the rule rather than as a bug: the loop runs over **every**
    paragraph that mentions the predicate, so every mention must re-state the
    whole enumeration — all six suffixes, the retention clause, and the blocking
    path. Each procedure derives exactly one such paragraph at this tree, so the
    obligation is invisible until someone adds a second; when that happens the
    repair is to complete that paragraph, or to write it without naming the
    predicate, never to relax this loop to *some paragraph somewhere*.
    """
    for procedure, paragraphs in _predicate_paragraphs().items():
        for paragraph in paragraphs:
            assert f"*.{suffix}" in paragraph, (
                f"{HYDRATION} ({procedure}) does not classify *.{suffix} "
                f"before writing {MANIFEST}"
            )
            assert "retains every gate asset" in paragraph, (
                f"{HYDRATION} ({procedure}) permits mixed ownership without "
                "retaining the managed assets"
            )
            assert "blocking path" in paragraph, (
                f"{HYDRATION} ({procedure}) retains the assets without naming the "
                "path that blocked hydration"
            )
