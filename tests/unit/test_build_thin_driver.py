"""CAL-715 — ``/build`` is a thin delegating driver, not a second copy of the loop.

Source: ``assessments/2026-06-15-system-and-code.md`` SYSTEM-2 (Medium) — the
sibling of the ``linear`` skill consolidation (CAL-714).

``commands/build.md`` re-encoded the start→review→ship loop the stepped trio
(``/start`` / ``/review`` / ``/ship``) already encodes, and embedded raw
``api.linear.app`` GraphQL/``jq`` blocks duplicating the provider skill. Two
parallel encodings of one loop — one re-hardcoding a provider's API — guaranteed
to drift. CAL-715 makes ``/build`` a *thin* driver: tracker operations delegate to
the ``tracker`` skill, worktree to ``worktree-isolation``, implementation to
``test-driven-development``, the review *criteria* to ``review-discipline``. Only
the autonomous-loop control (fix loop, convergence check, implement sub-agent
spawn, the machine ``SUBMIT:`` envelope + engine, abandon path) stays inline.

**What this module asserts, after #459.** Two things, each over its own home:

* the delegation paragraph in ``build.md``'s preamble names the phase skills and
  refuses to embed provider API calls (one tripwire, with polarity);
* ``process/harness.md``'s command table carries a ``/build`` row — structural
  correspondence between the command surface and the table that indexes it.

``test_build_embeds_no_linear_graphql`` was removed by #459: the no-embed sweep is
a strict subset of ``test_linear_skill::test_no_command_embeds_linear_graphql``,
which runs the same ban over every command rather than this one. A local
restatement of a tree-wide sweep adds no coverage and one more place to edit.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
BUILD = REPO_ROOT / "commands" / "build.md"
PROCESS_DOC = REPO_ROOT / "process" / "harness.md"

#: The preamble — everything before the first ``## `` heading. The delegation
#: statement is the command's opening contract, so this is the window a reader
#: meets it in; a copy that drifted into a later section is the drift, not the rule.
_PREAMBLE_END = re.compile(r"^## ", re.MULTILINE)

#: The phase skills the thin driver delegates to, each referenced by name. The
#: tracker entry is the backend-neutral protocol, not a provider: naming a
#: provider here is what CAL-715 removed.
_DELEGATIONS = (
    "tracker",
    "worktree-isolation",
    "test-driven-development",
    "review-discipline",
)

#: The refusal, anchored to what it governs. A bare negation somewhere in the
#: paragraph says nothing — almost any English paragraph carries one — so the
#: token has to sit next to the thing it forbids.
_NO_EMBEDDED_API = re.compile(
    r"\b(?:do not|don't|never|no)\b(?:\W+\w+){0,4}?\W+embed\w*\b", re.IGNORECASE
)


def _preamble() -> str:
    """``commands/build.md`` up to its first ``## `` heading."""
    text = BUILD.read_text()
    first_heading = _PREAMBLE_END.search(text)
    return text[: first_heading.start()] if first_heading else text


def _paragraphs(text: str) -> list[str]:
    return [block.strip() for block in text.split("\n\n") if block.strip()]


def _delegation_paragraphs() -> list[str]:
    """Preamble paragraphs that hand every phase in :data:`_DELEGATIONS` to a skill."""
    return [p for p in _paragraphs(_preamble()) if all(s in p for s in _DELEGATIONS)]


def test_the_driver_delegates_rather_than_re_encoding_the_loop() -> None:
    """One paragraph of the preamble delegates every phase and embeds no API (AC-1/AC-2).

    One tripwire over one rule-home (#459), replacing three unanchored
    whole-file containment checks. Its parts:

    * **anchor** — the delegation lives in exactly one preamble paragraph. Read
      as a *cardinality*, so the claim survives a rewording of that paragraph but
      fails when the delegations scatter across the file, which is the shape a
      whole-file ``"worktree-isolation" in text`` cannot distinguish from the rule.
    * **terms** — the four skills the driver hands each phase to. Words, not
      sentences: how the handoff is phrased is the review gate's business.
    * **polarity** — the refusal to embed provider API calls, with the negation
      anchored to ``embed``. That clause is the whole content of "thin": a driver
      that names all four skills *and* carries a GraphQL block has delegated
      nothing, and the pre-#459 term-set check read that as compliance.
    """
    candidates = _delegation_paragraphs()
    assert len(candidates) == 1, (
        f"commands/build.md's preamble has {len(candidates)} paragraphs delegating "
        f"all of {list(_DELEGATIONS)}; it must have exactly one. The driver is thin "
        "because one statement hands every phase to the skill that owns it — "
        "scattered or missing, the loop is being re-encoded here (CAL-715 AC-2)."
    )
    assert _NO_EMBEDDED_API.search(candidates[0]), (
        "commands/build.md's delegation paragraph no longer refuses to embed "
        "provider API calls. Naming the skills while carrying the calls anyway is "
        "the state CAL-715 removed, and it satisfies every term check (AC-1)."
    )


def test_build_in_process_command_table() -> None:
    """``/build`` has a row in the process-doc command table (AC-4).

    The table previously listed only the stepped trio + /propose / /assess /
    /update-guidance; the autonomous agent-led driver was absent (SYSTEM-2).
    """
    rows = [
        ln
        for ln in PROCESS_DOC.read_text().splitlines()
        if re.match(r"\|\s*`/build", ln)
    ]
    assert rows, (
        "process/harness.md command table has no `/build` row — the autonomous "
        "agent-led driver must appear in the command table (CAL-715 AC-4)."
    )
