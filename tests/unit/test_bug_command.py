"""#200 — `commands/bug.md`, files a `kind: bug` adjustment straight to Todo.

*Source:* ``specs/proposals/bug-and-tweak-capture-commands.md`` (accepted
2026-07-24), breakdown item 2. Depends on item 1 (``templates/adjustment.md``,
#199, already shipped). The proposal's contract for this command: thin over
the shared template, no escape hatch (a bug is unambiguous — the fix direction
is "make it match"), and the GitHub filing path must explicitly set
Status=Todo after ``gh project item-add`` — closing the item-add-no-status
trap (tick #90) where a filed item lands with Status unset and
``work-discovery``'s Todo-scoped read never sees it.

This guard pins the command's shape: it exists, carries a matching registered
version, names the shared template, has no escape hatch, and delegates filing
and explicit Todo placement to the tracker skill's provider-neutral ``create``
operation. Provider commands belong only in their provider skills.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent.parent
COMMAND = REPO_ROOT / "commands" / "bug.md"
REGISTRY = REPO_ROOT / "registry.yaml"


def test_command_exists_with_version_header() -> None:
    assert COMMAND.exists(), "commands/bug.md must exist (#200)."
    text = COMMAND.read_text()
    assert re.search(r"guidance:bug@[\d.]+", text), (
        "commands/bug.md must carry a `guidance:bug@x.y.z` version header."
    )


def test_registered_in_harness_profile_with_matching_version() -> None:
    header_version = re.search(r"guidance:bug@([\d.]+)", COMMAND.read_text()).group(1)
    entry = re.search(
        r"commands/bug\.md:\s*\{[^}]*id:\s*bug[^}]*\}", REGISTRY.read_text()
    )
    assert entry, "registry.yaml files: must list commands/bug.md with id: bug (#200)."
    assert "harness" in entry.group(0), "the entry must be in the `harness` profile."
    registry_version = re.search(r"version:\s*([\d.]+)", entry.group(0)).group(1)
    assert registry_version == header_version, (
        f"commands/bug.md header version {header_version!r} must match "
        f"registry.yaml's {registry_version!r}."
    )


def test_usage_line_names_the_bare_command() -> None:
    text = COMMAND.read_text()
    assert re.search(r"^Usage:\s*`/bug", text, re.MULTILINE), (
        "commands/bug.md must document `Usage: /bug ...`."
    )


def test_fills_the_shared_adjustment_template_as_kind_bug() -> None:
    text = COMMAND.read_text()
    assert "templates/adjustment.md" in text, (
        "commands/bug.md must fill the shared templates/adjustment.md (#200)."
    )
    assert re.search(r"kind:\s*bug", text), (
        "commands/bug.md must fill the template with `kind: bug`."
    )


def test_has_no_escape_hatch_step() -> None:
    """Only `/tweak` carries the "should we?" escape hatch (#201) — a named
    step, headed the same way `templates/adjustment.md` heads its own
    (`**Escape hatch (...)`). `/bug` may still contrast itself against
    `/propose` in framing prose (the same way `/propose` itself contrasts
    against `/start`), but it must not carry that named step."""
    text = COMMAND.read_text()
    assert not re.search(r"\*\*Escape hatch", text), (
        "commands/bug.md must not carry an escape-hatch step — a bug is "
        "unambiguous and has no such step, unlike /tweak."
    )


def test_delegates_filing_and_todo_placement_to_tracker_create() -> None:
    text = COMMAND.read_text()
    assert "tracker.create" in text and "Todo" in text, (
        "commands/bug.md must delegate filing and explicit Todo placement to "
        "the tracker skill's provider-neutral create operation."
    )


def test_contains_no_provider_recipe() -> None:
    text = COMMAND.read_text()
    forbidden = ("gh issue", "gh project", "issueCreate", "issueUpdate", "api.linear.app")
    offenders = [token for token in forbidden if token in text]
    assert not offenders, (
        f"commands/bug.md inlines provider recipe tokens {offenders!r}; provider "
        "commands belong only in the selected provider skill."
    )


def test_reports_the_created_ticket_and_next_step() -> None:
    text = COMMAND.read_text()
    assert re.search(r"/start|/harness run", text), (
        "commands/bug.md must point at the next step (`/start` or "
        "`/harness run`) once the ticket is filed."
    )
