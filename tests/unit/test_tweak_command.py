"""#201 — `commands/tweak.md`, files a `kind: tweak` adjustment straight to
Todo, with an escape hatch to `/propose`.

*Source:* ``specs/proposals/bug-and-tweak-capture-commands.md`` (accepted
2026-07-24), breakdown item 3. Depends on item 1 (``templates/adjustment.md``,
#199, already shipped). The proposal's contract for this command: thin over
the shared template, same as `/bug` (#200) except for the one axis a tweak
carries that a bug does not — "should we?" A tweak whose direction is clear
files straight to Todo; a tweak that carries a real decision or would spawn
more than one change is not a tweak — the command stops and points at
`/propose` instead (no bespoke confirm gate). The GitHub filing path must
still explicitly set Status=Todo after ``gh project item-add`` — the
item-add-no-status trap (tick #90).

This guard pins the command's shape: it exists, carries a matching registered
version, names the shared template with `kind: tweak`, carries the named
escape-hatch step, and documents both tracker backends' filing steps.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent.parent
COMMAND = REPO_ROOT / "commands" / "tweak.md"
REGISTRY = REPO_ROOT / "registry.yaml"


def test_command_exists_with_version_header() -> None:
    assert COMMAND.exists(), "commands/tweak.md must exist (#201)."
    text = COMMAND.read_text()
    assert re.search(r"guidance:tweak@[\d.]+", text), (
        "commands/tweak.md must carry a `guidance:tweak@x.y.z` version header."
    )


def test_registered_in_harness_profile_with_matching_version() -> None:
    header_version = re.search(r"guidance:tweak@([\d.]+)", COMMAND.read_text()).group(1)
    entry = re.search(
        r"commands/tweak\.md:\s*\{[^}]*id:\s*tweak[^}]*\}", REGISTRY.read_text()
    )
    assert entry, "registry.yaml files: must list commands/tweak.md with id: tweak (#201)."
    assert "harness" in entry.group(0), "the entry must be in the `harness` profile."
    registry_version = re.search(r"version:\s*([\d.]+)", entry.group(0)).group(1)
    assert registry_version == header_version, (
        f"commands/tweak.md header version {header_version!r} must match "
        f"registry.yaml's {registry_version!r}."
    )


def test_usage_line_names_the_bare_command() -> None:
    text = COMMAND.read_text()
    assert re.search(r"^Usage:\s*`/tweak", text, re.MULTILINE), (
        "commands/tweak.md must document `Usage: /tweak ...`."
    )


def test_fills_the_shared_adjustment_template_as_kind_tweak() -> None:
    text = COMMAND.read_text()
    assert "templates/adjustment.md" in text, (
        "commands/tweak.md must fill the shared templates/adjustment.md (#201)."
    )
    assert re.search(r"kind:\s*tweak", text), (
        "commands/tweak.md must fill the template with `kind: tweak`."
    )


def test_has_the_named_escape_hatch_step() -> None:
    """Unlike `/bug` (#200, no escape hatch), `/tweak` carries the named
    "should we?" escape hatch — headed the same way `templates/adjustment.md`
    heads its own (`**Escape hatch (...)`) — that stops and points at
    `/propose` when the tweak carries a real decision or spawns more than one
    change."""
    text = COMMAND.read_text()
    assert re.search(r"\*\*Escape hatch", text), (
        "commands/tweak.md must carry a named escape-hatch step, unlike /bug."
    )
    assert "/propose" in text, (
        "commands/tweak.md's escape hatch must point at /propose."
    )


def test_documents_github_filing_closing_the_item_add_no_status_trap() -> None:
    text = COMMAND.read_text()
    assert "gh issue create" in text, (
        "commands/tweak.md must document the github create step."
    )
    assert "gh project item-add" in text, (
        "commands/tweak.md must document the github add-to-board step."
    )
    assert "gh project item-edit" in text and "single-select-option-id" in text, (
        "commands/tweak.md must document explicitly setting Status=Todo via "
        "`gh project item-edit --single-select-option-id`, closing the "
        "item-add-no-status trap (tick #90)."
    )


def test_documents_linear_filing_path() -> None:
    text = COMMAND.read_text()
    assert "linear" in text.lower(), (
        "commands/tweak.md must document the `tracker: linear` filing path "
        "too (the command is tracker-neutral)."
    )


def test_reports_the_created_ticket_and_next_step() -> None:
    text = COMMAND.read_text()
    assert re.search(r"/start|/harness run", text), (
        "commands/tweak.md must point at the next step (`/start` or "
        "`/harness run`) once the ticket is filed."
    )
