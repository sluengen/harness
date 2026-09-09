"""#564, #565 — the composed workflow skills stay reachable by a model caller.

``disable-model-invocation: true`` makes a skill answer only to a human typing
its slash command; the ``Skill`` tool refuses it. Five workflow skills are
driven by a caller that is *not* a human at a prompt, so the flag breaks them:

``routine`` is fired by an unattended scheduled run — the standing prompt its
own body tells operators to paste. ``build`` is fired by ``/routine``.
``review`` is fired by ``/build``'s review stage. ``CLAUDE.md`` already records
that reasoning for the latter two; #564 is what happened when ``routine`` was
swept into the operator-only bucket by category rather than by intent, and the
scheduled loop went silently dead.

``digest`` and ``assess`` joined at #565, which found the identical
contradiction the #564 reviewer had flagged: a body naming a scheduled or
unattended caller above frontmatter refusing exactly that caller. Both had live
callers refused on the operator's host at the time — two scheduled tasks firing
``/harness:digest``, and a work-pull task falling back to ``/assess code`` — so
the outage #564 fixed for ``routine`` had already happened twice more.

#627 retired ``digest`` into ``drain`` and it inherits the membership rather
than the reasoning: ``digest``'s caller was a scheduled run firing the report
half, and ``drain`` has no report half to schedule. Its caller is ``/assess``,
which invokes it to clear the improvement ledger — a composing caller of the
same kind as ``/build`` firing ``review``. The flag never enforced operator
presence for ``digest``'s drain either; the rule in the skill's body does, and
that is unchanged by the rename.

Frontmatter is admissible guard subject matter under ADR 0017 D5. The flag is
a *declaration*, and this asserts the declaration — the refusal it causes lives
in the host, not in this tree.

The control is what stops the guard being satisfied by deleting the flag
everywhere: every other workflow skill must still declare it. The two sets are
complements over the derived workflow set, so a tenth workflow skill added
tomorrow lands in the control and fails loudly until someone decides which side
it belongs on.
"""

from __future__ import annotations

import re

from tests._gitutil import indexed_text, tracked_files_under

_REPO_ROOT_MARKER = "skills"

# A workflow skill is one whose description opens with the slash trigger it
# answers to; the craft skills are read inside a session that already resolved
# them and are never dispatched by a trigger. Same derivation as
# ``test_native_codex_plugin.py`` — the set is derived, never listed.
_TRIGGER = re.compile(r"^description:\s*[\"']?/", re.MULTILINE)
_FLAG = re.compile(r"^disable-model-invocation:\s*(\S+)\s*$", re.MULTILINE)

# Named individually because the membership *is* the contract, not a proxy for
# one: each is driven by a non-human caller, and the reason differs per member.
_COMPOSED = {"routine", "build", "review", "drain", "assess"}


def _frontmatter(name: str) -> str:
    text = indexed_text(f"skills/{name}/SKILL.md")
    assert text.startswith("---\n"), f"skills/{name}/SKILL.md has no frontmatter"
    return text.split("---\n", 2)[1]


def _workflow_skills() -> set[str]:
    names = {
        path.parent.name
        for path in tracked_files_under(_REPO_ROOT_MARKER)
        if path.name == "SKILL.md" and _TRIGGER.search(_frontmatter(path.parent.name))
    }
    assert len(names) >= 9, f"expected at least the nine workflow skills, found {names}"
    return names


def test_composed_workflow_skills_do_not_disable_model_invocation() -> None:
    """#564 AC-1, #565 AC-1, #627 AC-4 — a scheduled or composing caller can fire each."""
    workflows = _workflow_skills()
    assert workflows >= _COMPOSED, (
        f"composed set names a skill that is not a workflow: {_COMPOSED - workflows}"
    )
    for name in sorted(_COMPOSED):
        declared = _FLAG.search(_frontmatter(name))
        assert declared is None, (
            f"skills/{name}/SKILL.md declares disable-model-invocation="
            f"{declared.group(1)}, which refuses its non-human caller (#564, #565)"
        )


def test_operator_only_workflow_skills_still_disable_model_invocation() -> None:
    """The control: the fix must not be 'delete the flag everywhere'."""
    operator_only = sorted(_workflow_skills() - _COMPOSED)
    assert operator_only, "no operator-only workflow skills left to control against"
    for name in operator_only:
        declared = _FLAG.search(_frontmatter(name))
        assert declared is not None and declared.group(1) == "true", (
            f"skills/{name}/SKILL.md no longer reserves itself to the operator "
            f"(declared: {declared.group(1) if declared else 'unset'})"
        )
