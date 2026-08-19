"""The plugin's hook manifest must wire exactly the hooks the tree ships.

**The occurrence this guard cites (#489, from the v5 merge review of #481).**
``hooks/hooks.json`` is how a *consuming* repo receives enforcement at all: the
plugin host reads it and runs the commands it names. Measured at base ``bfa36e8``,
before this module existed, ``git grep "hooks/hooks.json"`` named the path outside
the manifest itself in exactly these files, and not one of them *opens* it:
``commands/init.md``, telling an operator the plugin needs no per-repo wiring; a
comment in ``scripts/session-start-bootstrap.sh`` explaining why the
``SessionStart`` hook is *not* in the manifest; a docstring in
``tests/unit/test_marketplace_provenance.py`` explaining why this repo deliberately
does not set ``enabledPlugins``; and the as-built record
``specs/features/plugin-surface.md``, which names the path in its surface table,
in its provenance note, and in the *Known limitations* entry recording that the
manifest had no integrity guard and was exercised only by installation. The set is
named rather than counted, because the count is the part a later reader would act
on and the part that rots (#472). Every member is prose *about* the manifest, so
only installation exercised it — which is how a stale manifest shipped green: a
renamed hook file leaves an entry pointing at nothing, and a new hook file that
nobody wired is enforcement this repo believes it has and a consuming repo never
gets. Both directions are silent on this side of the install.

**Admitted under ADR 0017 D5 class (e), tree-consistency.** Both operands are in
the tracked tree — the manifest's command strings and the ``hooks/*.js`` files —
and the assertion is that they *correspond*. Nothing here reads what a hook does.

**Both directions, because a manifest rots both ways.** A wired command with no
file behind it is the stale direction; a tracked hook the manifest never wires is
the admitting direction, and it is the half a one-sided check misses — every entry
the manifest *does* carry resolves, so a stale-only sweep reads it as green
forever. ``craft.md`` → *ANY ALLOWLIST OR EXEMPTION NEEDS BOTH DIRECTIONS*.
:func:`manifest_difference` returns both and the sweep asserts both are empty.

**The extractor is loud, never partial (#490).** ``hook_name`` raises on a command
it cannot read rather than skipping it. #490 shipped a partial parser that fell
through **silently** on a spelling it did not admit: green where the admitted
spelling went red, with nothing in the output to distinguish "read every command"
from "read the ones it recognised". A partial parser owes a completeness
assertion, and here the completeness assertion is that there is no silent branch
at all — every command either yields a name or fails the run. The same reading
applies to the manifest walk: an empty ``hooks`` object, an empty event list, or
an entry whose ``type`` is not ``command`` raises, because an empty derived set
compares equal to another empty derived set and the sweep would pass over
nothing (``craft.md`` → *The empty comparison set*; the identically-failed-renders
class in #466).

**Why the tracked tree.** Both operands read the index —
:func:`tests._gitutil.indexed_text` for the manifest,
:func:`tests._gitutil.tracked_files_under` for the shipped set. A guard over the
working tree passes on the machine that wrote the file and says nothing about the
clone a consuming repo installs from (#484), which is the only reader that
matters here.

**How this guard is proved (#489 D4).** The predicate half — :func:`hook_name`,
:func:`manifest_hook_names`, :func:`manifest_difference` — is mutation-proved with
``scripts/mutate.py`` over the synthetic samples below, whose correct answers
differ from this repo's production answer (the empty report). The *file* half is
out of ``mutate.py``'s reach, because ``mutate.py`` edits working files and these
readers resolve the index (#490). It is proved by **staged probe** instead — stage
a manifest wiring a hook that does not exist, and separately stage a sixth
``hooks/*.js`` the manifest does not wire, run the module, observe each red,
restore the index, and re-derive ``git write-tree`` to prove the restore was exact.

**Size.** This module is over ``engineering``'s 500-line hard limit, which asks for
a justification here. The excess is samples, not logic. The manifest is nested
four levels deep — event, matcher group, entry, command — and a walk can truncate
silently at any of them, so each level owes both a sample that it is walked
(``test_every_event_in_the_manifest_is_walked``,
``test_every_group_and_entry_in_an_event_is_walked``) and a refusal that it is not
empty (``test_a_manifest_that_wires_nothing_fails_loudly``, three refusals
mutated one at a time). Splitting those across two modules would put the walk's
samples in a different file from the walk. It is not an outlier here either —
``test_promotion_step_script.py``, ``test_push_target_guard_hook.py`` and
``test_gate_evidence_hook.py`` are each longer still, the first by more than
double. Members rather than a tally, because a tally of files longer than this
one is falsified by an edit to this one (#484).
"""

# size: the manifest nests four levels — event, matcher group, entry, command —
# and a walk can truncate silently at any of them, so each level owes both a
# sample that it is walked and a refusal that it is not empty. The excess is
# those samples, not logic; splitting them out would put the walk's samples in a
# different file from the walk. See the Size note above for the enumeration.

from __future__ import annotations

import json
import re
import subprocess
import tempfile
from pathlib import Path

from tests._gitutil import indexed_text, tracked_files_under
from tests.unit._prose import REPO_ROOT

#: The manifest the plugin host reads.
MANIFEST_PATH = "hooks/hooks.json"

#: The tree the hook sources live in.
HOOKS_DIR = "hooks"

#: A manifest command. Today every one of the five reads
#: ``node ${CLAUDE_PLUGIN_ROOT}/hooks/<name>.js``. The unbraced ``$CLAUDE_PLUGIN_ROOT``
#: is admitted alongside the braced form because both are legal spellings of the
#: same variable and a manifest edit may reach for either: a parser that goes
#: silent — or red — on a correct spelling its subject may legally contain is a
#: defect, not strictness (#484, #487). Nothing looser is admitted: a command
#: that does not resolve through the plugin root cannot be matched to a tracked
#: file, so it must fail rather than be guessed at.
_HOOK_COMMAND = re.compile(
    r"^node\s+(?:\$\{CLAUDE_PLUGIN_ROOT\}|\$CLAUDE_PLUGIN_ROOT)/hooks/"
    r"(?P<name>[A-Za-z0-9][A-Za-z0-9._-]*)\.js$"
)


def hook_name(command: str) -> str:
    """The hook file stem ``command`` runs.

    Raises on a command this extractor cannot read. Skipping it would drop the
    entry from the wired set, so the hook it names would be reported as *shipped
    but not wired* — a failure pointing at the wrong operand — or, if the same
    hook were wired correctly elsewhere, as nothing at all (#490).
    """
    match = _HOOK_COMMAND.match(command.strip())
    if match is None:
        raise AssertionError(
            f"{MANIFEST_PATH} carries a command this guard cannot read: {command!r}. "
            f"The shape it knows is `node ${{CLAUDE_PLUGIN_ROOT}}/hooks/<name>.js`. "
            f"Either fix the command or teach this extractor the new shape — it "
            f"must not fall through silently (#490)."
        )
    return match.group("name")


def manifest_hook_names(manifest: object) -> set[str]:
    """Every hook stem ``manifest`` wires, across every event.

    Every structural surprise raises rather than yielding a shorter set: a
    manifest that derived to ``set()`` would compare equal to a ``hooks/`` tree
    that derived to ``set()``, and the sweep would pass over two empty operands
    (``craft.md`` → *The empty comparison set*).
    """
    if not isinstance(manifest, dict) or not isinstance(manifest.get("hooks"), dict):
        raise AssertionError(
            f"{MANIFEST_PATH} has no `hooks` object at its root — parsed a "
            f"{type(manifest).__name__}. Nothing can be derived from it."
        )
    events = manifest["hooks"]
    if not events:
        raise AssertionError(
            f"{MANIFEST_PATH} declares no events at all. An empty manifest wires "
            f"nothing, and an empty derived set would read as agreement with an "
            f"empty hooks tree."
        )
    names: set[str] = set()
    for event, groups in events.items():
        if not isinstance(groups, list) or not groups:
            raise AssertionError(
                f"{MANIFEST_PATH} event {event!r} is not a non-empty list of "
                f"matcher groups — it is {groups!r}."
            )
        for group in groups:
            entries = group.get("hooks") if isinstance(group, dict) else None
            if not isinstance(entries, list) or not entries:
                raise AssertionError(
                    f"{MANIFEST_PATH} event {event!r} carries a matcher group with "
                    f"no `hooks` list: {group!r}."
                )
            for entry in entries:
                if not isinstance(entry, dict) or entry.get("type") != "command":
                    raise AssertionError(
                        f"{MANIFEST_PATH} event {event!r} carries an entry this "
                        f"guard cannot classify: {entry!r}. Only `type: command` "
                        f"names a hook file; an unclassified member fails here "
                        f"rather than dropping out of the wired set."
                    )
                command = entry.get("command")
                if not isinstance(command, str):
                    raise AssertionError(
                        f"{MANIFEST_PATH} event {event!r} carries a command entry "
                        f"with no command string: {entry!r}."
                    )
                names.add(hook_name(command))
    return names


def shipped_hook_names(*, repo_root: Path = REPO_ROOT) -> set[str]:
    """The stems of the ``*.js`` files git tracks under ``hooks/``.

    The suffix filter is what keeps ``hooks.json`` and ``package.json`` out: they
    live in the same tree and are not hooks, so a stem-only derivation would
    report both as shipped-but-unwired forever.
    """
    return {
        path.stem
        for path in tracked_files_under(HOOKS_DIR, repo_root=repo_root)
        if path.suffix == ".js"
    }


def manifest_difference(wired: set[str], shipped: set[str]) -> dict[str, list[str]]:
    """What each side has that the other does not, empty when they agree.

    ``wired_but_not_shipped`` is the stale direction (the manifest names a file
    that is gone); ``shipped_but_not_wired`` is the admitting direction (the tree
    grew a hook and the manifest did not).
    """
    report: dict[str, list[str]] = {}
    missing = sorted(wired - shipped)
    unwired = sorted(shipped - wired)
    if missing:
        report["wired_but_not_shipped"] = missing
    if unwired:
        report["shipped_but_not_wired"] = unwired
    return report


def _manifest() -> object:
    """The staged manifest, parsed. Never the working file (#482)."""
    return json.loads(indexed_text(MANIFEST_PATH))


# ---------------------------------------------------------------------------
# Floors — one on each operand the comparison consumes
# ---------------------------------------------------------------------------


def test_the_manifest_and_the_hook_sources_are_tracked() -> None:
    """The subjects must be in the index, not merely on this disk (#484)."""
    tracked = {
        path.relative_to(REPO_ROOT).as_posix()
        for path in tracked_files_under(HOOKS_DIR)
    }
    assert MANIFEST_PATH in tracked, (
        f"{MANIFEST_PATH} is not tracked by git, so the manifest a consuming repo "
        f"installs is not the one this guard read. Tracked: {sorted(tracked)}"
    )
    assert "hooks/gate-evidence-guard.js" in tracked, (
        f"the Stop hook's source is not tracked under {HOOKS_DIR}/. Tracked: "
        f"{sorted(tracked)}"
    )


def test_the_shipped_set_is_live_and_excludes_the_non_hooks() -> None:
    """Floor on the tree operand, and the pin on its suffix filter.

    ``craft.md`` → *Floors decay into decoration*: membership, never cardinality.
    The negative half is the filter's other direction — ``hooks.json`` and
    ``package.json`` sit in the same tree, and a stem-only derivation would report
    both as shipped-but-unwired on every run.
    """
    shipped = shipped_hook_names()
    assert "gate-evidence-guard" in shipped, (
        f"the shipped-hook derivation no longer contains the Stop hook — it "
        f"yielded {sorted(shipped)}"
    )
    assert "hooks" not in shipped and "package" not in shipped, (
        f"the derivation is counting non-hook files in hooks/ — it yielded "
        f"{sorted(shipped)}"
    )


def test_the_wired_set_is_live() -> None:
    """Floor on the manifest operand — the one a bad edit can empty.

    ``craft.md`` → *Floor both measured operands* (#486: ``assert big <= base``
    held at ``0 <= 21`` because the unfloored operand had been emptied). The
    anchor is a hook wired under ``Stop``, not under ``PreToolUse``, so a walk
    that read only the first event fails here rather than in the sweep.
    """
    wired = manifest_hook_names(_manifest())
    assert "gate-evidence-guard" in wired, (
        f"the manifest walk no longer reaches the Stop event — it yielded "
        f"{sorted(wired)}"
    )


def test_the_reader_follows_the_index_not_the_disk() -> None:
    """The manifest operand is the staged blob, and this is the sample that says so.

    :func:`test_the_manifest_and_the_hook_sources_are_tracked` does not reach
    this: it asserts the **path** is in the index and says nothing about the bytes
    read. The fixture diverges in the direction where a working-tree reader looks
    *more* correct — the staged manifest wires a hook that does not exist, while
    the on-disk copy is correct — so a reader that took the working tree would
    report agreement over a tree that ships a broken manifest (#482).
    """
    correct = {
        "hooks": {
            "Stop": [
                {
                    "hooks": [
                        {
                            "type": "command",
                            "command": "node ${CLAUDE_PLUGIN_ROOT}/hooks/real.js",
                        }
                    ]
                }
            ]
        }
    }
    broken = json.loads(json.dumps(correct))
    broken["hooks"]["Stop"][0]["hooks"][0]["command"] = (
        "node ${CLAUDE_PLUGIN_ROOT}/hooks/ghost.js"
    )
    with tempfile.TemporaryDirectory() as raw:
        repo = Path(raw)
        subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True)
        (repo / "hooks").mkdir()
        (repo / "hooks" / "real.js").write_text("// hook\n", encoding="utf-8")
        manifest = repo / "hooks" / "hooks.json"
        manifest.write_text(json.dumps(broken), encoding="utf-8")
        subprocess.run(["git", "add", "hooks"], cwd=repo, check=True)

        # Restore a correct manifest on disk, unstaged.
        manifest.write_text(json.dumps(correct), encoding="utf-8")

        staged = json.loads(indexed_text("hooks/hooks.json", repo_root=repo))
        on_disk = json.loads(manifest.read_text(encoding="utf-8"))
        assert staged != on_disk, (
            "the fixture failed to diverge — this sample would pass either way"
        )
        shipped = shipped_hook_names(repo_root=repo)
        assert shipped == {"real"}, f"the fixture's hooks tree derived to {shipped}"
        assert manifest_difference(manifest_hook_names(staged), shipped) == {
            "wired_but_not_shipped": ["ghost"],
            "shipped_but_not_wired": ["real"],
        }, "the reader returned something other than the staged blob"
        assert manifest_difference(manifest_hook_names(on_disk), shipped) == {}, (
            "the fixture's on-disk copy must read as agreeing, or this sample does "
            "not separate an index reader from a working-tree reader"
        )


def test_the_walk_reads_the_real_manifest() -> None:
    """Paired splice: prove the reader reaches real manifest bytes.

    ``craft.md`` → *A prose mutation needs a paired splice to prove it was live*.
    Every sample below runs over synthetic dicts; nothing else here would notice a
    reader that had stopped resolving the manifest. Splicing a command the
    extractor is known to read into the *real* manifest text, and requiring the
    name it yields to appear **there**, separates "the manifest agrees" from "the
    manifest was never read".
    """
    real = indexed_text(MANIFEST_PATH)
    spliced = "a-hook-this-repo-never-had"
    before = manifest_hook_names(json.loads(real))
    doctored = real.replace(
        "${CLAUDE_PLUGIN_ROOT}/hooks/prompt-guard.js",
        f"${{CLAUDE_PLUGIN_ROOT}}/hooks/{spliced}.js",
    )
    assert doctored != real, (
        "the splice did not land — the manifest no longer wires prompt-guard the "
        "way this sample expects, so nothing below measures the reader"
    )
    after = manifest_hook_names(json.loads(doctored))
    assert spliced not in before, (
        "the splice name must not already be wired, or its appearance afterwards "
        "proves nothing about the reader"
    )
    assert spliced in after, (
        "a command spliced into the real manifest was not read — the walk is not "
        "reaching real manifest bytes, and a clean sweep would be "
        "indistinguishable from a sweep that read nothing"
    )


# ---------------------------------------------------------------------------
# The predicate's teeth — synthetic samples, both directions
# ---------------------------------------------------------------------------


def _manifest_wiring(*names: str) -> dict[str, object]:
    """A minimal well-formed manifest wiring ``names`` under one event."""
    return {
        "hooks": {
            "PreToolUse": [
                {
                    "matcher": "Bash",
                    "hooks": [
                        {
                            "type": "command",
                            "command": f"node ${{CLAUDE_PLUGIN_ROOT}}/hooks/{name}.js",
                        }
                        for name in names
                    ],
                }
            ]
        }
    }


def test_a_wired_hook_with_no_file_behind_it_is_reported() -> None:
    """The stale direction: a renamed or deleted hook leaves a dangling entry."""
    assert manifest_difference({"prompt-guard", "ghost"}, {"prompt-guard"}) == {
        "wired_but_not_shipped": ["ghost"]
    }


def test_a_shipped_hook_the_manifest_never_wires_is_reported() -> None:
    """The admitting direction — the half a one-sided check cannot see.

    Every entry the manifest carries resolves, so a stale-only sweep is green
    while a consuming repo silently receives less enforcement than this repo has.
    """
    assert manifest_difference({"prompt-guard"}, {"prompt-guard", "new-guard"}) == {
        "shipped_but_not_wired": ["new-guard"]
    }


def test_an_agreeing_manifest_reports_nothing() -> None:
    """The passing direction.

    Without this, a predicate that reported everything as a difference would
    satisfy both samples above and still be useless.
    """
    assert manifest_difference({"a", "b"}, {"b", "a"}) == {}


def test_both_directions_are_reported_at_once() -> None:
    """A rename is both directions in one edit, and neither may mask the other."""
    assert manifest_difference({"old-name"}, {"new-name"}) == {
        "wired_but_not_shipped": ["old-name"],
        "shipped_but_not_wired": ["new-name"],
    }


def test_every_event_in_the_manifest_is_walked() -> None:
    """A walk that read only the first event would derive a strict subset.

    The real manifest declares two events, so this is the shape that would fail
    silently in one direction and read as a stale hooks tree in the other.
    """
    manifest = {
        "hooks": {
            "PreToolUse": [
                {
                    "matcher": "Bash",
                    "hooks": [
                        {
                            "type": "command",
                            "command": "node ${CLAUDE_PLUGIN_ROOT}/hooks/first.js",
                        }
                    ],
                }
            ],
            "Stop": [
                {
                    "hooks": [
                        {
                            "type": "command",
                            "command": "node ${CLAUDE_PLUGIN_ROOT}/hooks/second.js",
                            "timeout": 15,
                        }
                    ]
                }
            ],
        }
    }
    assert manifest_hook_names(manifest) == {"first", "second"}


def test_every_group_and_entry_in_an_event_is_walked() -> None:
    """Two entries in one group, and two groups in one event, both count."""
    manifest = _manifest_wiring("one", "two")
    manifest["hooks"]["PreToolUse"].append(  # type: ignore[index,union-attr]
        {
            "matcher": "Write",
            "hooks": [
                {
                    "type": "command",
                    "command": "node ${CLAUDE_PLUGIN_ROOT}/hooks/three.js",
                }
            ],
        }
    )
    assert manifest_hook_names(manifest) == {"one", "two", "three"}


def test_both_plugin_root_spellings_are_read() -> None:
    """A legal spelling the manifest may contain must not read as nothing.

    #484 and #487 are the same defect twice: a parser whose pattern admitted one
    spelling of its subject went silent — or red — on another that was equally
    correct.
    """
    assert hook_name("node ${CLAUDE_PLUGIN_ROOT}/hooks/prompt-guard.js") == "prompt-guard"
    assert hook_name("node $CLAUDE_PLUGIN_ROOT/hooks/prompt-guard.js") == "prompt-guard"


def _rejects(sample: object, needle: str) -> None:
    """Assert ``manifest_hook_names`` or ``hook_name`` fails loudly on ``sample``."""
    try:
        if isinstance(sample, str):
            hook_name(sample)
        else:
            manifest_hook_names(sample)
    except AssertionError as exc:
        assert needle in str(exc), (
            f"the failure did not name the offending input {needle!r}: {exc}"
        )
    else:
        raise AssertionError(f"{sample!r} was accepted silently")


def test_a_command_the_extractor_cannot_read_fails_loudly() -> None:
    """An unreadable command is red, never a silent skip (#490).

    Three shapes that must not fall through: a path that does not resolve through
    the plugin root (so it cannot be matched to a tracked file), an interpreter
    this manifest does not use, and a suffix that is not ``.js``. Each is a
    plausible edit, and each would otherwise shrink the wired set and report the
    hook it names under the wrong direction.
    """
    _rejects("node hooks/prompt-guard.js", "hooks/prompt-guard.js")
    _rejects("bash ${CLAUDE_PLUGIN_ROOT}/hooks/prompt-guard.sh", "bash")
    _rejects("node ${CLAUDE_PLUGIN_ROOT}/hooks/prompt-guard.mjs", "mjs")


def test_an_entry_of_an_unclassified_type_fails_loudly() -> None:
    """``craft.md`` → *A guard over an enumerable dimension must fail on an
    unclassified member*. A future entry kind must be placed here deliberately,
    not dropped out of the wired set on the day it is introduced.
    """
    manifest = _manifest_wiring("prompt-guard")
    manifest["hooks"]["PreToolUse"][0]["hooks"][0]["type"] = "output"  # type: ignore[index]
    _rejects(manifest, "output")


def test_a_manifest_that_wires_nothing_fails_loudly() -> None:
    """An empty derived set must not compare equal to an empty shipped set.

    ``craft.md`` → *The empty comparison set* and the identically-failed-renders
    class (#466): two operands that both derived to nothing agree perfectly. Each
    level of the walk refuses emptiness, so the three shapes that could empty the
    set all fail instead.
    """
    _rejects({"hooks": {}}, "declares no events")
    _rejects({"hooks": {"Stop": []}}, "Stop")
    _rejects({"hooks": {"Stop": [{"matcher": "Bash", "hooks": []}]}}, "Stop")
    _rejects({"nothing": {}}, "no `hooks` object")


# ---------------------------------------------------------------------------
# The sweep — AC-2, over the real manifest and the real tree
# ---------------------------------------------------------------------------


def test_the_manifest_wires_exactly_the_shipped_hooks() -> None:
    """AC-2: the manifest and the tracked ``hooks/*.js`` set agree, both ways."""
    difference = manifest_difference(manifest_hook_names(_manifest()), shipped_hook_names())
    assert difference == {}, (
        f"{MANIFEST_PATH} has drifted from the tracked hooks/ tree. "
        f"`wired_but_not_shipped` names commands pointing at files that are gone — "
        f"the host runs them and fails. `shipped_but_not_wired` names hooks a "
        f"consuming repo never receives. Both are wrong: {difference}"
    )
