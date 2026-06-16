"""A gate verb's docstring cites the *gate-strictness* decision (D2), not the
*routing-discipline* decision (D5).

CAL-633/635/636 (``test_retired_spec_cites.py`` / ``test_events_spec_cites.py`` /
``test_module_home_spec_cites.py``) guard the **§-cite** class — a docstring
naming a wrong or retired ``SPEC.md §x`` section. This guard covers the adjacent
**decision-id-cite** class: a docstring naming a wrong ``harness-as-tool.md``
decision. A §-cite grep cannot catch it — ``D5`` is a perfectly live decision,
so its mere presence is not the fault; the fault is that it labels the *wrong*
rationale for the property the docstring describes.

The fault this closes: ``harness/cli/close.py`` attributed the HEAD-bound close
gate ("closing a ticket must be impossible unless a run was started and the
current tree passed review") to decision **D5**. Per the proposal's own decision
table, that property is **D2** ("How strict is the ``close`` gate? Resolved: bind
the passing review to HEAD"); **D5** is a *different* decision —
routing-discipline (every git/ticket mutation goes through a verb). The sibling
half of the same gate, ``harness/cli/review.py``, already cites **D2**
correctly, and ``specs/architecture-principles.md`` attributes the gate to
**D2** — ``close.py`` was the lone outlier.

The contract: **the close gate is decision D2; a gate verb's module docstring
cites D2 as the gate's rationale and never misattributes it to the
routing-discipline decision (D5).** The two ``harness/cli`` verbs whose entire
purpose is the gate — ``close`` (enforces it) and ``review`` (records the
HEAD-bound verdict it enforces) — are the scope: their module docstrings exist to
explain the gate, so the gate decision is the one they cite.

The decision→meaning map is parsed from the proposal's decision table, not
hard-coded: the test resolves *which* id is the gate decision and *which* is the
routing decision from the table's titles, then asserts those are D2 and D5. So a
renumber of the proposal fails this loudly (at :func:`test_decision_table_pins`)
instead of letting the sweep silently track the wrong id. (A future, deliberate
need to cite D5 from a gate verb — e.g. documenting ``close``'s routing backstop —
would trip the sweep; that is the intended deliberate-update point, exactly as
the §-cite guards work.)

Acceptance criteria:

* **AC-1** — ``harness/cli/close.py`` cites **D2** (not D5) for the HEAD-bound
  gate. Proven by :func:`test_gate_verb_docstrings_cite_the_gate_decision` (which
  fails against the original ``**D5**`` cite).
* **AC-2** — the guard derives D2=gate / D5=routing by parsing the proposal
  table, failing loudly on a renumber. Proven by :func:`test_decision_table_pins`.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_PROPOSAL = _REPO_ROOT / "specs" / "proposals" / "harness-as-tool.md"

# A decision-table row opens ``| **Dn — <title>** | ...``. The em-dash (U+2014)
# is the title separator; ``.+?`` is non-greedy so it stops at the closing ``**``.
_DECISION_ROW_RE = re.compile(r"\*\*(D\d+)\s*—\s*(.+?)\*\*")

# A decision cited in a docstring: ``decision **D2**``, ``(D2)``, or a bare
# word-bounded ``D2``. Word boundaries keep it from matching inside identifiers.
_CITE_RE = re.compile(r"\bD\d+\b")

# The two verbs whose module docstrings exist to explain the close gate.
_GATE_VERBS = ("close", "review")


def _decision_titles(proposal_text: str) -> dict[str, str]:
    """Map each decision id to its table-row title (lower-cased)."""
    return {
        did: title.strip().lower()
        for did, title in _DECISION_ROW_RE.findall(proposal_text)
    }


def _gate_decision(titles: dict[str, str]) -> str:
    """The id of the decision that fixes how strict the ``close`` gate is."""
    hits = [d for d, t in titles.items() if "close" in t and "gate" in t]
    assert len(hits) == 1, f"expected exactly one close-gate decision, got {hits}"
    return hits[0]


def _routing_decision(titles: dict[str, str]) -> str:
    """The id of the routing-discipline decision."""
    hits = [d for d, t in titles.items() if "routing" in t]
    assert len(hits) == 1, f"expected exactly one routing decision, got {hits}"
    return hits[0]


def _module_docstring_cites(module_name: str) -> set[str]:
    """The decision ids cited in ``harness/cli/<module>.py``'s module docstring."""
    path = _REPO_ROOT / "harness" / "cli" / f"{module_name}.py"
    docstring = ast.get_docstring(ast.parse(path.read_text())) or ""
    return set(_CITE_RE.findall(docstring))


def test_decision_table_pins() -> None:
    """The gate decision is D2 and the routing decision is D5 (AC-2).

    Pins the proposal's table so the sweep below tracks the right ids. A
    renumber fails here loudly rather than silently re-pointing the guard.
    """
    titles = _decision_titles(_PROPOSAL.read_text())
    assert _gate_decision(titles) == "D2"
    assert _routing_decision(titles) == "D5"


def test_gate_verb_docstrings_cite_the_gate_decision() -> None:
    """Each gate verb cites the gate decision and never the routing one (AC-1)."""
    titles = _decision_titles(_PROPOSAL.read_text())
    gate = _gate_decision(titles)
    routing = _routing_decision(titles)

    violations: list[str] = []
    for verb in _GATE_VERBS:
        cites = _module_docstring_cites(verb)
        if routing in cites:
            violations.append(
                f"{verb}.py: docstring cites the routing-discipline decision "
                f"{routing} for the gate — the gate is decision {gate}"
            )
        if gate not in cites:
            violations.append(
                f"{verb}.py: docstring does not cite the gate decision {gate}"
            )

    assert not violations, "gate verb docstrings misattribute the close gate:\n  " + (
        "\n  ".join(violations)
    )
