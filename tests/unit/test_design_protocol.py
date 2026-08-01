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
    _EXCERPT_ELISION,
    DESIGN_MODEL_DEFAULT,
    DESIGN_SECTIONS,
    MALFORMED_SUBMIT_SENTINEL,
    NO_SUBMIT_SENTINEL,
    SUBMIT_EXCERPT_MAX_CHARS,
    SUBMIT_EXCERPT_WINDOW_CHARS,
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
# AC-4 — a failed parse quotes what would not parse (#277)
#
# The failure is silent by design (ADR 0007 D4 degrades and the run ships), so
# the ledger event is the only evidence a later reader gets. Recording *that*
# the contract broke let 72 attempts accumulate at a 12.5% failure rate with
# nothing to diagnose from; these pin what is recorded instead.
#
# Two windows, not one, because the three candidate causes item 3 must choose
# among show up in different places: a payload spanning lines shows at the
# START of the payload, a truncation and a designed-but-never-submitted run
# both show at the END of stdout.
# ---------------------------------------------------------------------------


def test_success_records_neither_field() -> None:
    """The ``ok`` shape stays exactly as pinned since #211."""
    result = parse_design_submit('SUBMIT: {"design_markdown": "### Data model"}')
    assert result.error is None
    assert result.submit_excerpt is None
    assert result.stdout_chars is None


def test_malformed_submit_quotes_from_the_submit_token() -> None:
    """A payload spanning lines is only visible from the payload's start."""
    stdout = "thought about it\nSUBMIT: {\n  " + '"design_markdown": "### Data model"\n}\n'
    result = parse_design_submit(stdout)
    assert result.error == MALFORMED_SUBMIT_SENTINEL
    assert result.submit_excerpt is not None
    assert result.submit_excerpt.startswith("SUBMIT: {")
    assert "thought about it" not in result.submit_excerpt


def test_no_submit_quotes_the_end_of_stdout() -> None:
    """What the engine said instead of submitting is at the end."""
    stdout = "### Data model\nlots of design\nLet me know if you want changes.\n"
    result = parse_design_submit(stdout)
    assert result.error == NO_SUBMIT_SENTINEL
    assert result.submit_excerpt is not None
    assert result.submit_excerpt.endswith("Let me know if you want changes.\n")


def test_failure_records_the_true_stdout_length() -> None:
    """A 17 KB stdout elided to a window must still say it was 17 KB."""
    stdout = "SUBMIT: {" + "x" * 17_000
    result = parse_design_submit(stdout)
    assert result.stdout_chars == len(stdout)


def test_excerpt_is_bounded_for_any_stdout_size() -> None:
    """The change's one measurable criterion — the ledger is not a log."""
    for size in (0, 1, 500, 2_000, 20_000, 200_000):
        stdout = "SUBMIT: {" + "x" * size
        excerpt = parse_design_submit(stdout).submit_excerpt
        assert excerpt is not None
        assert len(excerpt) <= SUBMIT_EXCERPT_MAX_CHARS, f"{size} -> {len(excerpt)}"


def test_a_long_failure_keeps_both_ends_and_marks_the_elision() -> None:
    stdout = "SUBMIT: {HEADMARK" + "x" * (4 * SUBMIT_EXCERPT_WINDOW_CHARS) + "TAILMARK"
    excerpt = parse_design_submit(stdout).submit_excerpt
    assert excerpt is not None
    assert "HEADMARK" in excerpt, "the payload's start says whether it spans lines"
    assert "TAILMARK" in excerpt, "the end says whether it was truncated"
    assert _EXCERPT_ELISION in excerpt
    assert len(excerpt) == SUBMIT_EXCERPT_MAX_CHARS


def test_a_short_failure_is_contiguous_with_no_elision_marker() -> None:
    """Eliding nothing would be a lie about the evidence."""
    stdout = 'SUBMIT: {"design_markdown": "### Data mod'
    excerpt = parse_design_submit(stdout).submit_excerpt
    assert excerpt == stdout
    assert _EXCERPT_ELISION not in excerpt


def test_empty_stdout_records_the_zero_and_no_excerpt() -> None:
    """Zero reads as 'the engine emitted nothing', an empty string would not."""
    result = parse_design_submit("")
    assert result.error == NO_SUBMIT_SENTINEL
    assert result.stdout_chars == 0
    assert result.submit_excerpt is None


def test_the_excerpt_anchors_on_the_last_submit_token() -> None:
    """The contract asks for a final line; earlier ones are reasoning."""
    stdout = 'SUBMIT: {"early": 1}\nSUBMIT: {"design_markdown": UNIQUEMARK}\n'
    excerpt = parse_design_submit(stdout).submit_excerpt
    assert excerpt is not None
    assert "UNIQUEMARK" in excerpt
    assert '"early"' not in excerpt
