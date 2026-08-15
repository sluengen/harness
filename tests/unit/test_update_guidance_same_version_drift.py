"""#407 — equal-version source drift fails closed during ``/update-guidance``.

The updater uses versions to choose a source revision and hashes to distinguish
source changes from consumer edits. A source file changed without a version bump
must not look current or local, because accepting that state lets a consumer
advance ``source.ref`` without installing the fetched bytes.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
UPDATE_GUIDANCE = REPO_ROOT / "commands" / "update-guidance.md"
DECISION = REPO_ROOT / "commands" / "decision.md"
REGISTRY = REPO_ROOT / "registry.yaml"


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


def _section(start: str, end: str) -> str:
    text = _text(UPDATE_GUIDANCE)
    return text[text.index(start) : text.index(end)]


def test_changed_commands_and_registry_carry_the_registered_versions() -> None:
    """The corrected commands publish coordinated, intentional version bumps."""
    assert _version(DECISION, "decision") == "0.2.0"
    assert _registry_version("commands/decision.md") == "0.2.0"
    assert _version(UPDATE_GUIDANCE, "update-guidance") == "1.0.0"
    assert _registry_version("commands/update-guidance.md") == "1.0.0"

    # #407 bumped the registry to 0.5.131. Pinning that exact value would fail on
    # every later registry edit, so assert the floor it published rather than a
    # value that moves with unrelated work; the header/self-entry parity below is
    # the property this test actually owns.
    registry_version = _version(REGISTRY, "registry")
    assert _as_tuple(registry_version) >= (0, 5, 131), registry_version
    assert _registry_version("registry.yaml") == registry_version


def test_decision_keeps_the_tracker_only_audit_trail() -> None:
    """The version bump preserves #338's tracker-only audit decision."""
    text = " ".join(_text(DECISION).lower().split())
    assert re.search(r"audit trail is the tracker issue itself", text)
    assert re.search(r"resolution in the body", text)
    assert re.search(r"label gone", text)
    assert re.search(r"assignment cleared", text)
    assert re.search(r"not a ledger event", text)


def test_current_requires_equal_versions_and_both_hash_matches() -> None:
    """Current means source and consumer bytes both match the locked bytes."""
    row = _table_row("current").lower()
    assert "source version == lock version" in row
    assert re.search(r"source hash (?:==|matches) lock", row)
    assert re.search(r"(?:on-disk|disk) hash (?:==|matches) lock", row)


def test_equal_version_source_hash_mismatch_is_source_drift() -> None:
    """The new state takes precedence regardless of the consumer's disk state."""
    row = _table_row("SOURCE DRIFT").lower()
    assert "source version == lock version" in row
    assert re.search(r"source hash (?:!=|differs from) lock", row)
    assert re.search(r"regardless of (?:the )?(?:on-disk|disk|consumer)", row)
    assert "stop" in row


def test_source_drift_stops_before_apply_and_requires_source_repair() -> None:
    """Source drift is repaired at source and cannot enter conflict resolution."""
    classification = _section("### 2.", "### 3.")
    apply = _section("### 3.", "### 4.")
    contract = f"{classification}\n{apply}".lower()

    assert re.search(r"source drift.{0,120}stop.{0,80}before.{0,40}apply", contract, re.S)
    assert re.search(r"name.{0,40}(?:affected )?file", contract, re.S)
    assert re.search(r"source hash.{0,80}lock(?:ed)? hash", contract, re.S)
    assert re.search(r"repair.{0,80}source file.{0,80}registry version", contract, re.S)
    assert re.search(r"source drift.{0,160}(?:not|never).{0,40}conflict", contract, re.S)
    assert re.search(
        r"source drift.{0,200}(?:cannot|never|do not).{0,80}(?:accept|overwrite)",
        contract,
        re.S,
    )


def test_source_drift_leaves_consumer_and_lock_untouched() -> None:
    """The refusal mutates neither installed guidance nor lock metadata."""
    apply = _section("### 3.", "### 5.").lower()
    assert re.search(
        r"source drift.{0,220}leave.{0,100}(?:installed|on-disk|consumer).{0,80}unchanged",
        apply,
        re.S,
    )
    assert re.search(
        r"source drift.{0,260}(?:lock entr(?:y|ies)|\.guidance-lock\.yaml).{0,100}unchanged",
        apply,
        re.S,
    )
    assert re.search(
        r"source\.ref.{0,100}(?:not advance|unchanged|untouched)",
        apply,
        re.S,
    )


def test_existing_non_drift_classifications_keep_their_semantics() -> None:
    """Valid source states still pull, preserve local edits, or conflict."""
    pull = _table_row("PULL").lower()
    local = _table_row("LOCAL").lower()
    conflict = _table_row("CONFLICT").lower()

    assert "source version > lock version" in pull
    assert re.search(r"(?:on-disk|disk) hash (?:==|matches) lock", pull)
    assert "copy" in pull and "update the lock" in pull

    assert "source version == lock version" in local
    assert re.search(r"source hash (?:==|matches) lock", local)
    assert re.search(r"(?:on-disk|disk) hash (?:!=|differs from) lock", local)
    assert "leave" in local

    assert "source version > lock version" in conflict
    assert re.search(r"(?:on-disk|disk) hash (?:!=|differs from) lock", conflict)
    assert "3-way diff" in conflict and "choose" in conflict
