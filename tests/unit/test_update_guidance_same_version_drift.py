"""#407 — equal-version source drift fails closed during ``/update-guidance``.

The updater uses versions to choose a source revision and hashes to distinguish
source changes from consumer edits. A source file changed without a version bump
must not look current or local, because accepting that state lets a consumer
advance ``source.ref`` without installing the fetched bytes.

**What this module asserts, after #459.** Three things:

* header⇄registry version parity for the two commands #407 changed, plus the
  registry's own self-entry — structural correspondence, untouched;
* ``commands/decision.md`` names no ledger — negative space over a subsystem ADR
  0015 deleted, untouched;
* **one tripwire** over the SOURCE DRIFT rule: its classification-table row, the
  refusal that follows the table, and step 3's apply-time consequence.

Five sentence-pin tests collapsed into that tripwire under #459 (ADR 0016), along
with ``test_decision_keeps_the_tracker_only_audit_trail``'s four positive
half-sentence regexes (``"audit trail is the tracker issue itself"``, ``"resolution
in the body"``, ``"label gone"``, ``"assignment cleared"``) — each a literal that
breaks on a benign rewording while saying nothing about whether the tracker is
still the audit trail. Its negative half survives, because a zero-membership
sweep never has to read meaning.

Occurrence the tripwire's polarity cites (``code-quality`` Part C): the pre-#459
row check asserted ``"stop" in row`` and a ``source hash != lock`` regex, but
took no position on the *contrast* with the ``current`` row's ``==``. The
classification is a comparison, so the operator that distinguishes SOURCE DRIFT
from *current* is the load-bearing token, and a row rewritten to ``==`` — the
inversion that makes drift look current, which is exactly the failure #407
closed — satisfied every pin. The ``craft.md`` class is *Operands in different
frames make a constant comparison*, one level up: the comparison **operator** is
the rule, so it is what has to be read.
"""

from __future__ import annotations

import re
from pathlib import Path

from tests.unit._prose import REPO_ROOT, update_guidance_between

UPDATE_GUIDANCE = REPO_ROOT / "commands" / "update-guidance.md"
DECISION = REPO_ROOT / "commands" / "decision.md"
REGISTRY = REPO_ROOT / "registry.yaml"

#: The state whose refusal this module owns. Its sibling module
#: ``test_update_guidance_lock_untracked_adoption`` owns the adoption rule in the
#: same step — two tripwires, two rule-homes, one file.
_DRIFT = "SOURCE DRIFT"


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _version(path: Path, guidance_id: str) -> str:
    match = re.search(rf"guidance:{re.escape(guidance_id)}@([\d.]+)", _text(path))
    assert match, f"{path} has no guidance:{guidance_id} version stamp"
    return match.group(1)


def _registry_version(path: str) -> str:
    match = re.search(
        rf"^\s*{re.escape(path)}:\s*\{{[^}}]*version:\s*([\d.]+)",
        _text(REGISTRY),
        re.MULTILINE,
    )
    assert match, f"registry.yaml has no row for {path}"
    return match.group(1)


def _as_tuple(version: str) -> tuple[int, ...]:
    return tuple(int(part) for part in version.split("."))


def _table_row(state: str) -> str:
    match = re.search(
        rf"^\| \*\*{re.escape(state)}\*\* \|(?P<row>.*)$",
        _text(UPDATE_GUIDANCE),
        re.MULTILINE,
    )
    assert match, f"classification table has no {state} row"
    return match.group("row")


def _units_naming(section: str, term: str) -> list[str]:
    """Paragraphs of ``section`` that name ``term``, whitespace collapsed."""
    return [
        " ".join(block.split())
        for block in section.split("\n\n")
        if term in block and block.strip()
    ]


def test_changed_commands_and_registry_carry_the_registered_versions() -> None:
    """The corrected commands publish coordinated, intentional version bumps.

    The property is **parity plus a floor**, not a frozen constant, for all three
    files. The registry half already worked that way, with the reasoning written
    out below; the two command halves were exact pins, and they failed the first
    time either file was legitimately edited again (#436 added a gate-before-push
    sentence to ``update-guidance``). An exact pin on a file that is expected to
    keep changing measures nothing about the property it was written for — it
    just makes every future editor delete a number — so both are brought onto the
    same shape the registry uses. What is preserved is what this module owns: a
    file's own header and its registry row agree, and neither has slipped below
    the version #407 published.
    """
    for path, guidance_id, registry_path, floor in (
        (DECISION, "decision", "commands/decision.md", (0, 3, 1)),
        (UPDATE_GUIDANCE, "update-guidance", "commands/update-guidance.md", (1, 0, 0)),
    ):
        version = _version(path, guidance_id)
        assert _as_tuple(version) >= floor, f"{registry_path} regressed to {version}"
        assert _registry_version(registry_path) == version, (
            f"{registry_path}'s header says {version} but its registry row does "
            "not — a version stamp and the registry must never disagree, or "
            "/update-guidance classifies the file wrongly"
        )

    # #407 bumped the registry to 0.5.131. Pinning that exact value would fail on
    # every later registry edit, so assert the floor it published rather than a
    # value that moves with unrelated work; the header/self-entry parity below is
    # the property this test actually owns.
    registry_version = _version(REGISTRY, "registry")
    assert _as_tuple(registry_version) >= (0, 5, 131), registry_version
    assert _registry_version("registry.yaml") == registry_version


def test_decision_keeps_the_tracker_only_audit_trail() -> None:
    """The version bump preserves #338's tracker-only audit decision.

    Only the negative half survives #459. #338's "not a ledger event" clause went
    with the ledger (ADR 0015 / #435), and the decision it recorded — the tracker
    issue *is* the audit trail — is now asserted the one way a tree-reader can
    assert it honestly: the command must not name a second, off-tracker record.
    A zero-membership sweep never has to read meaning; the four half-sentence
    literals that stood beside it did, and broke on any rewording.
    """
    text = " ".join(_text(DECISION).lower().split())
    assert "ledger" not in text, (
        "commands/decision.md must not name a ledger — ADR 0015 retired it, and "
        "the tracker issue is the whole audit trail (#338)."
    )


#: The refusal, anchored to the state it is about. SOURCE DRIFT is repaired at
#: source; it is *not* offered to the operator as a CONFLICT to accept.
_REFUSES_ACCEPTANCE = re.compile(
    r"\b(?:not|never|do not|cannot)\b(?:\W+\w+){0,8}?\W+(?:accept|overwrite|conflict)\w*\b",
    re.IGNORECASE,
)


def test_source_drift_fails_closed() -> None:
    """The one tripwire: drift is classified, refused, and applies nothing.

    Three windows, one rule. Each is anchored — the pre-#459 form searched
    whole multi-step slices with ``re.DOTALL`` gap regexes, which match across
    unrelated steps:

    * **the classification row.** Its condition cell must compare the source hash
      to the lock with ``!=``, and its action cell must be ``stop``. The
      comparison operator is the polarity here: rewritten to ``==`` the row
      *is* the ``current`` row, drift reads as up-to-date, and every term pin
      the old form carried still passed.
    * **the refusal that follows the table.** A paragraph naming SOURCE DRIFT
      must carry a negation anchored to accepting, overwriting, or reclassifying
      it as a CONFLICT. Without it the state is named and then handled like any
      other divergence, which is the behaviour #407 closed.
    * **step 3.** A paragraph naming SOURCE DRIFT must leave the installed files,
      the lock, and ``source.ref`` unchanged. Advancing ``source.ref`` over
      un-installed bytes is the concrete corruption the whole rule exists to
      prevent, so it is asserted by name.
    """
    condition, action = (cell.strip() for cell in _table_row(_DRIFT).split("|")[:2])
    assert re.search(r"source hash\s*(?:!=|differs from)\s*lock", condition, re.I), (
        f"the {_DRIFT} row's condition no longer compares the source hash to the "
        f"lock with an inequality: {condition!r}. With '==' this row is the "
        "`current` row, and a source file changed without a version bump reads as "
        "up to date."
    )
    assert "stop" in action.lower(), (
        f"the {_DRIFT} row's action is {action!r}, not a stop — the whole state "
        "exists so the update halts before installing anything (#407)."
    )

    classification = update_guidance_between("### 2.", "### 3.")
    refusals = [u for u in _units_naming(classification, _DRIFT) if _REFUSES_ACCEPTANCE.search(u)]
    assert refusals, (
        f"step 2 names {_DRIFT} but never refuses it: no paragraph says it is not "
        "a CONFLICT and must not be accepted or overwritten. Named without the "
        "refusal, the state is just another divergence the operator can confirm "
        "past — which is how a consumer advances source.ref over bytes it never "
        "installed (#407)."
    )

    apply_step = update_guidance_between("### 3.", "### 4.")
    consequences = [u for u in _units_naming(apply_step, _DRIFT) if "unchanged" in u.lower()]
    assert consequences, (
        f"step 3 does not state that {_DRIFT} leaves the installed files and the "
        "lock unchanged. A refusal that still applies the clean pulls has not "
        "failed closed (#407)."
    )
    assert any("source.ref" in u for u in consequences), (
        f"step 3's {_DRIFT} refusal does not name `source.ref`. That marker is "
        "what claims the whole source tree was installed cleanly; advancing it "
        "over drifted bytes is the exact corruption this state prevents."
    )
