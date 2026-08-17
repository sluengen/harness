"""Issue #401 — tracker ownership and active-backend guidance guards.

**What this module asserts (#459).** Two halves.

*Negative space* — the repo-active surface (what this GitHub-tracked repo's
own agents read) must not direct an agent to Linear, and the ``create``
contract must not carry a ``deliberate exception``. Both sweeps are unchanged
in predicate. What changed is the Linear sweep's floor: ``len(corpus) >= 5``
over a hardcoded five-element tuple is a constant asserting on itself — it
cannot fail while the tuple is a literal, and it decays into decoration the
moment anyone edits the tuple to satisfy it (``craft.md`` → *Floors decay into
decoration*, which prescribes pinning **membership**, not length). The floor
now pins the three members that make the sweep mean anything: emptying or
gutting the corpus goes red.

*One tripwire* — the ``### `create` contract`` section, read as its own slice.
Five whole-file phrase pins (``"UTF-8 body file"``, ``"mandatory initial Todo
placement"``, ``"canonical identifier and URL"``, ``"partial creation"``,
``"Never create a duplicate"``) were brittle to any rewording and blind to
direction; what replaces them is the anchored window, the words the contract
cannot be stated without, and the **negation bound to ``duplicate``** — the
rule's one irreversible instruction (``code-quality`` Part C → *A guard over
prose owns structure and negative space, never meaning*; ADR 0016).

Note the module name is historical: it holds no topology assertion. That guard
is ``test_guidance_efficiency_topology``.
"""

from __future__ import annotations

import re

from tests.unit._prose import REPO_ROOT

_NEGATION = re.compile(
    r"\b(never|not|no|nothing|none|neither|nor|cannot|can't)\b", re.IGNORECASE
)


def _read(relative: str) -> str:
    return (REPO_ROOT / relative).read_text()


def _sentences(block: str) -> list[str]:
    """*block* flattened to one line and split into sentences.

    The terminator may be followed by markdown emphasis or a closing bracket
    (``skill.**``, ``(…).``) — consuming those is load-bearing, not cosmetic:
    a bolded lead-in that ends ``.**`` otherwise glues its sentence to the
    next one and widens every negation window that reads this (``craft.md`` →
    *The text unit is part of the predicate*). A dry run of this module's #459
    mutation table surfaced exactly that: an inverted clause survived on a
    negation belonging to the sentence after it.
    """
    flat = " ".join(block.split())
    return [s for s in re.split(r"(?<=[.!?])[*_`\"')\]]*\s+", flat) if s.strip()]


def _create_contract_section() -> str:
    """The body of ``### `create` contract`` in the tracker skill."""
    text = _read("skills/tracker/SKILL.md")
    start = text.index("### `create` contract")
    end = text.index("\n## ", start + 1)
    return text[start:end]


def test_tracker_states_no_deliberate_exception_to_the_create_contract() -> None:
    """Negative space — ``create`` admits no documented escape hatch."""
    assert "deliberate exception" not in _read("skills/tracker/SKILL.md")


def test_create_contract_states_its_inputs_outputs_and_failure_mode() -> None:
    """Tripwire — the ``create`` contract section states one filing contract.

    Terms the contract cannot be stated without: ``utf-8`` (the body form),
    ``todo`` (mandatory initial placement), ``identifier`` and ``url`` (what a
    successful create returns), ``partial`` (the failure it must report rather
    than paper over). Polarity: the sentence naming ``duplicate`` carries a
    negation — never create one. That is the only clause here whose inversion
    is silently destructive, and a term co-occurrence cannot see it.
    """
    section = _create_contract_section()
    lowered = section.lower()
    for term in ("utf-8", "todo", "identifier", "url", "partial"):
        assert term in lowered, (
            f"the tracker `create` contract must state {term!r} (#401)."
        )
    duplicate = [s for s in _sentences(lowered) if "duplicate" in s]
    assert duplicate, (
        "the `create` contract must say what to do about a duplicate after a "
        "partial creation (#401)."
    )
    assert any(_NEGATION.search(s) for s in duplicate), (
        "the duplicate clause must carry its negation — a partial creation is "
        "repaired, never re-filed. Without it the section reads the same on a "
        "contract that told an agent to retry by creating a second issue (#401)."
    )


def test_active_repo_guidance_does_not_direct_agents_to_linear() -> None:
    # The repo-active surface: what this GitHub-tracked repo's own agents read.
    # ``commands/harness.md`` was a member until #435 retired it.
    corpus = (
        "CONTEXT.md",
        "commands/promote.md",
        "commands/routine.md",
        "settings/harness.json",
        ".claude/settings.json",
    )
    # Membership floor, not a length floor: a count over a literal tuple is a
    # constant asserting on itself. These three are the files whose removal
    # would hollow the sweep out — the repo's own config and both settings
    # twins (`craft.md` -> *Floors decay into decoration*).
    assert {"CONTEXT.md", "settings/harness.json", ".claude/settings.json"} <= set(
        corpus
    ), "the sweep's corpus lost a load-bearing member — it now measures less"
    active = {relative: _read(relative) for relative in corpus}
    forbidden = (
        "LINEAR_API_KEY",
        "Linear ticket",
        "Linear mutation",
        "Linear credentials",
        "repo.linear",
        "linear_cli",
        "linear_token",
        "Linear",
    )
    offenders = {
        relative: [token for token in forbidden if token in text]
        for relative, text in active.items()
        if any(token in text for token in forbidden)
    }
    assert not offenders, f"active GitHub guidance still directs agents to Linear: {offenders}"
