"""Tests for the design engine protocol (#210, ADR 0007).

The design verb (breakdown item 2) talks to a read-only engine over one narrow
contract: feed it :func:`build_design_prompt` and scan stdout for a single
``SUBMIT: {"design_markdown": ...}`` line. This module pins that contract:

* AC-1 — the prompt names all five required Design sections and the SUBMIT
  contract;
* AC-2 — the parser gives a *distinct* outcome for a valid submit, a missing
  submit line, and a malformed one;
* AC-3 — the model default is ``opus``, with no label resolution wired.
"""

from __future__ import annotations

import json

from harness.cli.design_protocol import (
    DESIGN_MODEL_DEFAULT,
    DESIGN_SECTIONS,
    MALFORMED_SUBMIT_SENTINEL,
    NO_SUBMIT_SENTINEL,
    SUBMIT_EXCERPT_BUDGET,
    build_design_cmd,
    build_design_prompt,
    parse_design_submit,
)

TICKET_TITLE = "Add the widget cache"
TICKET_DESCRIPTION = "## Problem\n\nWidgets are refetched on every render.\n"


# ---------------------------------------------------------------------------
# AC-1 — the prompt
# ---------------------------------------------------------------------------


def test_prompt_names_all_five_required_sections() -> None:
    prompt = build_design_prompt(TICKET_TITLE, TICKET_DESCRIPTION)
    for section in (
        "Data model",
        "Interface / contract",
        "Scenarios",
        "Security",
        "Test strategy",
    ):
        assert section in prompt, f"prompt omits the {section!r} section"


def test_declared_sections_match_the_prompt() -> None:
    """DESIGN_SECTIONS is the single list, not a second copy that can drift."""
    prompt = build_design_prompt(TICKET_TITLE, TICKET_DESCRIPTION)
    assert len(DESIGN_SECTIONS) == 5
    for section in DESIGN_SECTIONS:
        assert f"### {section}" in prompt


def test_prompt_asks_for_behaviour_in_scenarios() -> None:
    """The Scenarios section is the ticket's 'Behaviour in scenarios'."""
    prompt = build_design_prompt(TICKET_TITLE, TICKET_DESCRIPTION)
    assert "Behaviour in scenarios" in prompt


def test_prompt_states_the_submit_contract() -> None:
    prompt = build_design_prompt(TICKET_TITLE, TICKET_DESCRIPTION)
    assert "SUBMIT: <json>" in prompt
    assert "design_markdown" in prompt
    assert "exactly one SUBMIT line" in prompt


def test_prompt_carries_the_ticket() -> None:
    prompt = build_design_prompt(TICKET_TITLE, TICKET_DESCRIPTION)
    assert TICKET_TITLE in prompt
    assert TICKET_DESCRIPTION in prompt


def test_prompt_instructs_a_read_only_design_posture() -> None:
    """The engine designs; it never edits (architect.md, ADR 0007)."""
    prompt = build_design_prompt(TICKET_TITLE, TICKET_DESCRIPTION).lower()
    assert "read-only" in prompt
    assert "do not implement" in prompt


def test_prompt_example_submit_line_parses_back() -> None:
    """The example the prompt shows is itself a valid SUBMIT line."""
    prompt = build_design_prompt(TICKET_TITLE, TICKET_DESCRIPTION)
    example = next(
        line for line in prompt.splitlines() if line.strip().startswith("SUBMIT: {")
    )
    result = parse_design_submit(example)
    assert result.error is None
    assert result.design_markdown


# ---------------------------------------------------------------------------
# AC-2 — the parser's three distinct outcomes
# ---------------------------------------------------------------------------


def test_valid_submit_returns_the_design() -> None:
    markdown = "### Data model\n\nNo change.\n"
    stdout = "thinking...\n" + f"SUBMIT: {json.dumps({'design_markdown': markdown})}\n"
    result = parse_design_submit(stdout)
    assert result.design_markdown == markdown
    assert result.error is None


def test_missing_submit_line_is_its_own_outcome() -> None:
    result = parse_design_submit("I thought about it and gave up.\n")
    assert result.design_markdown is None
    assert result.error == NO_SUBMIT_SENTINEL


def test_malformed_json_is_distinct_from_a_missing_line() -> None:
    result = parse_design_submit("SUBMIT: {not json at all\n")
    assert result.design_markdown is None
    assert result.error == MALFORMED_SUBMIT_SENTINEL
    assert result.error != NO_SUBMIT_SENTINEL


def test_submit_line_missing_the_field_is_malformed() -> None:
    result = parse_design_submit('SUBMIT: {"verdict": "pass"}\n')
    assert result.error == MALFORMED_SUBMIT_SENTINEL


def test_submit_line_with_a_non_string_field_is_malformed() -> None:
    result = parse_design_submit('SUBMIT: {"design_markdown": 42}\n')
    assert result.error == MALFORMED_SUBMIT_SENTINEL


def test_submit_line_carrying_a_json_array_is_malformed() -> None:
    result = parse_design_submit('SUBMIT: ["design_markdown"]\n')
    assert result.error == MALFORMED_SUBMIT_SENTINEL


def test_empty_design_is_malformed_not_a_success() -> None:
    """An engine claiming success with nothing in it did not design."""
    result = parse_design_submit('SUBMIT: {"design_markdown": "   "}\n')
    assert result.design_markdown is None
    assert result.error == MALFORMED_SUBMIT_SENTINEL


def test_first_valid_submit_wins_past_a_malformed_one() -> None:
    stdout = 'SUBMIT: {oops\nSUBMIT: {"design_markdown": "### Data model\\nok"}\n'
    result = parse_design_submit(stdout)
    assert result.error is None
    assert result.design_markdown == "### Data model\nok"


def test_submit_line_is_recognized_when_indented() -> None:
    result = parse_design_submit('    SUBMIT: {"design_markdown": "### Data model"}')
    assert result.error is None
    assert result.design_markdown == "### Data model"


def test_empty_stdout_is_the_missing_line_outcome() -> None:
    assert parse_design_submit("").error == NO_SUBMIT_SENTINEL


# ---------------------------------------------------------------------------
# AC-3 — the model default
# ---------------------------------------------------------------------------


def test_model_default_is_opus() -> None:
    assert DESIGN_MODEL_DEFAULT == "opus"


def test_command_is_a_read_only_claude_subprocess_on_the_default_model() -> None:
    cmd = build_design_cmd()
    assert cmd[:2] == ["claude", "-p"]
    assert "--permission-mode" in cmd
    assert cmd[cmd.index("--permission-mode") + 1] == "plan"
    assert cmd[cmd.index("--model") + 1] == DESIGN_MODEL_DEFAULT
    assert "codex" not in cmd


def test_command_model_is_overridable_for_testing() -> None:
    cmd = build_design_cmd(model="sonnet")
    assert cmd[cmd.index("--model") + 1] == "sonnet"


def test_no_label_tier_resolution_is_wired() -> None:
    """ADR 0007: a ``design:<tier>`` label is an anticipated seam, not built."""
    import inspect

    from harness.cli import design_protocol

    assert not hasattr(design_protocol, "resolve_model_tier")
    # The command builder reads no ticket labels: the tier is a constant here,
    # not resolved per ticket. Wiring one is breakdown work, not this ticket.
    assert "labels" not in inspect.signature(design_protocol.build_design_cmd).parameters


# ---------------------------------------------------------------------------
# AC-4 — a failed parse records a bounded excerpt of what would not parse (#277)
# ---------------------------------------------------------------------------


def test_malformed_submit_records_the_offending_payload() -> None:
    """The excerpt is the diagnosis: without it a failure is a tally mark."""
    result = parse_design_submit('SUBMIT: {"design_markdown": "### Data mod\n')
    assert result.error == MALFORMED_SUBMIT_SENTINEL
    assert result.excerpt is not None
    assert '"design_markdown": "### Data mod' in result.excerpt


def test_malformed_submit_excerpt_names_why_the_payload_failed() -> None:
    """Which malformation it was is the whole point of capturing it."""
    result = parse_design_submit('SUBMIT: {"design_markdown": 42}\n')
    assert result.excerpt is not None
    assert "design_markdown" in result.excerpt
    # The four malformations are distinguishable from the excerpt alone.
    assert parse_design_submit("SUBMIT: {not json\n").excerpt != result.excerpt
    assert parse_design_submit('SUBMIT: ["a"]\n').excerpt != result.excerpt
    assert parse_design_submit('SUBMIT: {"design_markdown": " "}\n').excerpt != result.excerpt


def test_no_submit_excerpt_carries_what_the_engine_said_instead() -> None:
    result = parse_design_submit("I studied the worktree but ran out of room.\n")
    assert result.error == NO_SUBMIT_SENTINEL
    assert result.excerpt is not None
    assert "ran out of room" in result.excerpt


def test_excerpt_reports_the_unparseable_payloads_true_length() -> None:
    """A 15 KB payload elided to 400 chars must still say it was 15 KB."""
    payload = '{"design_markdown": "' + "x" * 15_000
    result = parse_design_submit(f"SUBMIT: {payload}\n")
    assert result.excerpt is not None
    assert str(len(payload)) in result.excerpt


def test_excerpt_is_bounded_far_below_a_real_design_payload() -> None:
    """The ledger is an audit trail, not a log — #271/#272/#273 ran 14–17 KB."""
    result = parse_design_submit('SUBMIT: {"design_markdown": "' + "x" * 20_000 + "\n")
    assert result.excerpt is not None
    assert len(result.excerpt) < 2 * SUBMIT_EXCERPT_BUDGET


def test_excerpt_keeps_both_ends_of_an_elided_payload() -> None:
    """The head says how the line starts, the tail says where it stopped."""
    payload = '{"design_markdown": "HEADMARK' + "x" * 5_000 + "TAILMARK"
    result = parse_design_submit(f"SUBMIT: {payload}\n")
    assert result.excerpt is not None
    assert "HEADMARK" in result.excerpt
    assert "TAILMARK" in result.excerpt


def test_a_valid_submit_records_no_excerpt() -> None:
    result = parse_design_submit('SUBMIT: {"design_markdown": "### Data model"}')
    assert result.error is None
    assert result.excerpt is None


def test_excerpt_describes_the_last_failing_submit_line() -> None:
    """The real submission is the final line; an earlier stray must not mask it."""
    stdout = 'SUBMIT: {"stray": 1}\nSUBMIT: {"design_markdown": UNIQUEMARK}\n'
    result = parse_design_submit(stdout)
    assert result.excerpt is not None
    assert "UNIQUEMARK" in result.excerpt
