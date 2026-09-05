"""The installed settings must carry everything the settings template declares.

**The occurrence this guard cites (#489, from the #484 review).**
``settings/harness.json`` is the tracked settings template — the tree's own name
for it is *the installed-surface template* (``tests/unit/test_git_push_guard_hook.py``)
— and ``.claude/settings.json`` is this repo's installed settings. What the template
is *for* in v5 is deliberately not decided here: ``skills/init/SKILL.md`` never names it,
and #489 scopes the question out, recording only which properties must correspond.
Nothing has held the two together since v5, and the drift the unguarded interval
accumulated was found by hand at grounding time:
``autoMode.allow``'s *Closing a shipped ticket* clause cited "the same one
``/build``'s ship stage enforces" in the template and "the same one ``/ship``
enforces" in the installed file, months after ``/ship`` was retired — ``commands/``
carries no such file. A permission clause is exactly the text an operator reads to
decide what an unattended run may do, so a stale citation there points the reader at
a gate that no longer exists. #489 D2 corrected the installed file rather than
exempting it; this guard is what keeps the next such drift from shipping green.

**Admitted under ADR 0017 D5 class (e), tree-consistency.** Both operands are
tracked JSON documents, and the assertion is that they *correspond* — key for key,
value for value. Nothing here reads what a clause means; a clause is compared as an
opaque string, so a benign reword of the template followed by the same reword of the
installed file passes, and a reword of only one of them fails.

**The rule is a subtree rule, and its exemption is earned rather than listed
(#489 D1).** Every key the template declares must appear in the installed file with
a deep-equal value. Objects **recurse**, so the installed file may add keys the
template never declares — which is how ``extraKnownMarketplaces`` and the
``hooks.SessionStart`` block legitimately live in the installed file alone. Every
non-object value, **arrays included**, must be equal exactly, so an entry the
installed file appends to a template-declared list — one more ``permissions.allow``
string — is a divergence and not an addition. That asymmetry falls out of iterating
the template's own keys; it is not a list of known-different names. ``craft.md`` →
*ANY ALLOWLIST OR EXEMPTION NEEDS BOTH DIRECTIONS*: an allowlist of exempt keys
would need a control proving each entry is still needed and one proving it is not
over-broad, and would go stale the day either file grows. An exemption earned from
the subject cannot (#467's one real win).

**Why the tracked tree.** Both operands are read through
:func:`tests._gitutil.indexed_text` — the bytes git has staged, which is what
``git write-tree`` certifies and what the gate marker is named after. A guard
reading ``Path.read_text`` certifies bytes that may never be committed (#482),
and a settings file that was edited but never added is precisely the shape a
working-tree reader cannot see.

**How this guard is proved (#489 D4).** The predicate half — :func:`divergences` —
is mutation-proved with ``scripts/mutate.py`` over the synthetic samples below,
whose correct answers differ from this repo's production answer (which is the empty
list). The *file* half is out of ``mutate.py``'s reach, because ``mutate.py`` edits
working files and this module's readers resolve the index (#490: five entries would
have printed SURVIVED with no defect behind them). It is proved by **staged
probe** instead — stage a divergent ``.claude/settings.json``, run the module,
observe the red, restore the index, and re-derive ``git write-tree`` to prove the
restore was exact.
"""

from __future__ import annotations

import json
import subprocess
import tempfile
from pathlib import Path

from tests._gitutil import indexed_text, tracked_files_under
from tests.unit._prose import REPO_ROOT

#: The tracked settings template.
TEMPLATE_PATH = "settings/harness.json"

#: This repo's installed settings — the twin the template is held against.
INSTALLED_PATH = ".claude/settings.json"

#: The dotted path reported for a divergence at the document root, where there is
#: no key to name. A bare ``""`` would render as nothing in a failure message.
ROOT = "<root>"


def divergences(template: object, installed: object, *, path: str = "") -> list[str]:
    """Dotted paths at which ``installed`` fails to carry what ``template`` declares.

    The rule, stated once (#489 D1):

    * an **object** in the template is recursed into — every key it declares must be
      present in ``installed``, and keys ``installed`` adds are not looked at, which
      is the whole exemption;
    * every **other** value, arrays and scalars alike, must be equal **exactly**,
      by type as well as by value. A list is not recursed into, so appending to a
      template-declared list is a divergence rather than an addition;
    * a template object facing a non-object is a divergence at that key, not a
      crash.

    Types are compared as well as values because JSON's ``true`` and ``1`` are
    ``==`` in Python: without it a boolean silently swapped for a number would read
    as agreement (``craft.md`` → *A comparison whose operands live in different
    frames is constant*).

    The result is sorted, so a caller comparing it against an expected list does not
    depend on dict ordering.
    """
    if isinstance(template, dict):
        if not isinstance(installed, dict):
            return [path or ROOT]
        found: list[str] = []
        for key, value in template.items():
            child = f"{path}.{key}" if path else key
            if key not in installed:
                found.append(child)
            else:
                found.extend(divergences(value, installed[key], path=child))
        return sorted(found)
    if type(template) is not type(installed) or template != installed:
        return [path or ROOT]
    return []


def _document(path: str) -> object:
    """The staged JSON at ``path``, parsed. Never the working file (#482)."""
    return json.loads(indexed_text(path))


# ---------------------------------------------------------------------------
# Floors — one on each operand, plus the control that must differ
# ---------------------------------------------------------------------------


def test_both_settings_documents_are_tracked() -> None:
    """The subjects must be in the index, not merely on this disk.

    #484: a guard over the working tree passes on the machine that wrote the file
    and says nothing about a fresh clone — and a clone is the only place either of
    these documents does anything.
    """
    tracked = {
        path.relative_to(REPO_ROOT).as_posix()
        for path in tracked_files_under("settings") | tracked_files_under(".claude")
    }
    assert TEMPLATE_PATH in tracked, (
        f"{TEMPLATE_PATH} is not tracked by git, so the bytes this guard read are "
        f"not the bytes a clone receives. Tracked: {sorted(tracked)}"
    )
    assert INSTALLED_PATH in tracked, (
        f"{INSTALLED_PATH} is not tracked by git. Tracked: {sorted(tracked)}"
    )


def test_the_template_operand_is_live() -> None:
    """Floor on the side the comparison iterates.

    ``craft.md`` → *The empty comparison set*: :func:`divergences` walks the
    template's keys, so a template that parsed to ``{}`` would make the sweep below
    green over nothing at all, with no skip and no warning. Membership is pinned,
    never cardinality — a count is the very drift this guard exists to remove.
    """
    template = _document(TEMPLATE_PATH)
    assert isinstance(template, dict)
    assert {"permissions", "autoMode", "hooks"} <= set(template), (
        f"the template no longer declares the three sections this guard was built "
        f"over — it declares {sorted(template)}"
    )
    assert "Bash(git push origin dev)" in template["permissions"]["allow"], (
        "the template's permissions.allow no longer carries the integration-branch "
        f"push grant — it carries {template['permissions']['allow']}"
    )


def test_the_installed_operand_is_live_and_is_the_other_file() -> None:
    """Floor on the side the comparison consumes, and the control that must differ.

    ``craft.md`` → *Floor both measured operands* (#486: ``assert big <= base`` held
    at ``0 <= 21`` because the unfloored operand had been emptied). Flooring only
    the template leaves a reader that resolved *both* paths to the same file
    indistinguishable from two files that agree — the identically-failed-renders
    class (#466), where two equally broken operands compare equal. The anchor is a
    key the installed file carries and the template deliberately does not, so it
    fails if the two readers ever collapse onto one document.
    """
    installed = _document(INSTALLED_PATH)
    template = _document(TEMPLATE_PATH)
    assert isinstance(installed, dict)
    assert "extraKnownMarketplaces" in installed, (
        f"the installed file no longer declares extraKnownMarketplaces, the key "
        f"that distinguishes it from the template — it declares {sorted(installed)}"
    )
    assert "extraKnownMarketplaces" not in template, (
        "the template has grown extraKnownMarketplaces, so the anchor above no "
        "longer separates the two operands; pick a key only the installed file has"
    )


def test_the_readers_follow_the_index_not_the_disk() -> None:
    """The operands are staged blobs, and this is the sample that says so.

    ``.claude/rules/scripts.md`` → *a guard asserts a property of the tracked
    tree, never the working directory*. :func:`test_both_settings_documents_are_tracked` does not
    reach this: it asserts the **paths** are in the index and says nothing about the
    bytes read. Measured at the #482 review on the sibling module, a tree staging a
    wrong file passed 12/12 while ``git write-tree`` reported an oid whose content
    was wrong.

    The fixture diverges in the direction where a working-tree reader looks *more*
    correct, not less: the staged installed file is missing a template-declared key,
    while the on-disk copy carries it. A reader that took the working tree would
    report agreement over a tree that ships a divergence.
    """
    with tempfile.TemporaryDirectory() as raw:
        repo = Path(raw)
        subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True)
        template = repo / "template.json"
        installed = repo / "installed.json"
        template.write_text(json.dumps({"permissions": {"allow": ["Read"]}}), encoding="utf-8")
        installed.write_text(json.dumps({"permissions": {}}), encoding="utf-8")
        subprocess.run(["git", "add", "template.json", "installed.json"], cwd=repo, check=True)

        # Restore a correct installed file on disk, unstaged.
        installed.write_text(json.dumps({"permissions": {"allow": ["Read"]}}), encoding="utf-8")

        staged = json.loads(indexed_text("installed.json", repo_root=repo))
        on_disk = json.loads(installed.read_text(encoding="utf-8"))
        assert staged != on_disk, (
            "the fixture failed to diverge — this sample would pass either way"
        )
        declared = json.loads(indexed_text("template.json", repo_root=repo))
        assert divergences(declared, staged) == ["permissions.allow"], (
            "the reader returned something other than the staged blob"
        )
        assert divergences(declared, on_disk) == [], (
            "the fixture's on-disk copy must read as agreeing, or this sample does "
            "not separate an index reader from a working-tree reader"
        )


def test_the_predicate_reads_the_real_settings_documents() -> None:
    """Paired splice: prove the readers reach real settings bytes.

    ``craft.md`` → *A prose mutation needs a paired splice to prove it was live*.
    Every sample below runs over synthetic dicts; nothing else here would notice a
    reader that had stopped resolving either file. Splicing a key the predicate is
    known to catch into the *real* template, and requiring it reported **there**,
    separates "the two documents agree" from "the documents were never read".
    """
    template = _document(TEMPLATE_PATH)
    installed = _document(INSTALLED_PATH)
    assert isinstance(template, dict)
    spliced = "a-settings-key-this-repo-never-had"
    before = divergences(template, installed)
    after = divergences({**template, spliced: True}, installed)
    assert spliced not in before, (
        "the splice key must not already be reported, or its appearance afterwards "
        "proves nothing about the reader"
    )
    assert spliced in after, (
        "a key spliced into the real template was not reported — the readers are "
        "not reaching real settings bytes, and a clean sweep would be "
        "indistinguishable from a sweep that read nothing"
    )


# ---------------------------------------------------------------------------
# The predicate's teeth — synthetic samples, both directions
# ---------------------------------------------------------------------------


def test_a_template_key_the_installed_file_lacks_is_reported() -> None:
    """The admitting direction: the installed file fell behind the template."""
    assert divergences({"a": 1, "b": 2}, {"a": 1}) == ["b"]


def test_a_template_declared_value_that_differs_is_reported() -> None:
    """The drift D2 corrected, in miniature: same key, divergent clause.

    The dotted path is what makes a failure actionable — this is the shape that
    actually rotted, three levels down in ``autoMode.allow``.
    """
    assert divergences({"p": {"q": "build"}}, {"p": {"q": "ship"}}) == ["p.q"]


def test_a_key_the_installed_file_adds_is_not_a_divergence() -> None:
    """The exemption, earned from the template rather than listed.

    This is the stale direction of the exemption: it must still be *needed*. The
    installed file legitimately carries ``extraKnownMarketplaces`` and a
    ``hooks.SessionStart`` block that the template never declares, and a rule
    demanding equality both ways would be permanently red on the real tree.
    """
    assert divergences({"a": 1}, {"a": 1, "extraKnownMarketplaces": {"harness": {}}}) == []


def test_a_key_added_inside_a_template_declared_object_is_not_a_divergence() -> None:
    """Objects recurse, so the exemption reaches nested additions too.

    ``hooks.SessionStart`` is exactly this shape: the template declares ``hooks``,
    and the installed file adds an event inside it.
    """
    assert divergences(
        {"hooks": {"Stop": [1]}}, {"hooks": {"Stop": [1], "SessionStart": [2]}}
    ) == []


def test_an_entry_added_to_a_template_declared_list_is_a_divergence() -> None:
    """The exemption's other direction: it must not be over-broad.

    An array is compared exactly and never recursed into, so a *widened* permission
    list is caught. This is the half a naive "the installed file may add things"
    rule would swallow, and it is the one that matters: the retired
    ``test_settings_derived_parity`` existed to refuse a permission clause carrying
    fewer stated bounds than the operator accepted.
    """
    assert divergences(
        {"permissions": {"allow": ["Read"]}},
        {"permissions": {"allow": ["Read", "Bash(*)"]}},
    ) == ["permissions.allow"]


def test_a_reordered_template_declared_list_is_a_divergence() -> None:
    """Exact equality, not set equality.

    A predicate comparing ``sorted(...)`` or ``set(...)`` would pass this while
    still catching the sample above, so without it the weaker degradation is
    indistinguishable from the rule. Order is meaningful in a permissions list that
    a reader scans top to bottom.
    """
    assert divergences({"a": ["x", "y"]}, {"a": ["y", "x"]}) == ["a"]


def test_an_object_replaced_by_a_scalar_is_reported_not_raised() -> None:
    """A template object facing a non-object fails as a divergence, loudly and once.

    Recursing blindly would raise ``AttributeError`` from inside the predicate,
    which reads as a broken guard rather than as the divergence it is.
    """
    assert divergences({"hooks": {"Stop": []}}, {"hooks": "disabled"}) == ["hooks"]


def test_a_boolean_swapped_for_a_number_is_reported() -> None:
    """Type is part of the comparison, because ``True == 1`` in Python.

    ``craft.md`` → *A comparison whose operands live in different frames is
    constant*: a value-only comparison reads two different JSON documents as one.
    """
    assert divergences({"enabled": True}, {"enabled": 1}) == ["enabled"]


def test_two_agreeing_documents_report_nothing() -> None:
    """The passing direction, over every shape at once.

    Without this, a predicate that reported everything as a divergence would satisfy
    every sample above and still be useless.
    """
    document = {
        "permissions": {"allow": ["Read", "Write"], "deny": []},
        "autoMode": {"allow": ["$defaults"]},
        "hooks": {"Stop": [{"hooks": [{"type": "command", "command": "node x.js"}]}]},
    }
    assert divergences(document, json.loads(json.dumps(document))) == []


def test_a_divergence_at_the_document_root_is_named() -> None:
    """The root has no key, and an unnamed divergence renders as nothing."""
    assert divergences({"a": 1}, ["a"]) == [ROOT]


# ---------------------------------------------------------------------------
# The sweep — AC-1, over the real documents
# ---------------------------------------------------------------------------


def test_the_installed_settings_carry_the_template_surface() -> None:
    """AC-1: every property ``settings/harness.json`` declares is in the installed twin."""
    diverged = divergences(_document(TEMPLATE_PATH), _document(INSTALLED_PATH))
    assert diverged == [], (
        f"{INSTALLED_PATH} has drifted from {TEMPLATE_PATH} at these dotted paths: "
        f"{diverged}. Every key the template declares must be present with a "
        f"deep-equal value; the installed file may add keys the template does not "
        f"declare, but it may not change or extend one the template does."
    )
