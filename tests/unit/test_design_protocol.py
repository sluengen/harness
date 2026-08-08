"""Tests for the design engine protocol (#210, ADR 0007; rewired by #294).

The design verb talks to its engine over one narrow contract. Until #294 that
contract was ``review``'s: a single final ``SUBMIT: {"design_markdown": ...}``
line, which forced a whole Markdown document to be JSON-escaped onto one
physical line. This module pins the contract that replaced it — **a file** —
and the stdout fallback that catches a permission-config regression:

* AC-1 — the prompt names all five required Design sections, the absolute
  output path, the length target, and the fallback markers;
* AC-2 — the engine command grants write capability to **exactly** the design
  path and nothing else, and is no longer plan mode;
* AC-3 — the fallback parser recovers a marked block, **including one whose
  closing marker never arrived** (the salvage property that is the whole point
  of dropping JSON);
* AC-4 — ``normalize_design`` gives one blank-is-not-a-design rule for both
  channels;
* AC-5 — a failure's stdout excerpt stays bounded, whatever the engine emitted;
* AC-6 — the regression: the observed 31 KB payload survives both channels.

Nothing here spawns a real engine. The one property this suite structurally
cannot prove is that the *permission config actually works* — that is a claim
about the ``claude`` binary, not about the string we build. It was verified by
hand in the ``harness:dev`` container on 2026-08-02 (see ``build_design_cmd``'s
docstring for what was measured); these tests pin the shape that verification
found to be the working one, so a later edit away from it fails here.
"""

from __future__ import annotations

import json
from pathlib import Path

from harness.cli.design_protocol import (
    DESIGN_MODEL_DEFAULT,
    DESIGN_SECTIONS,
    DESIGN_TARGET_CHARS,
    FALLBACK_BEGIN_MARKER,
    FALLBACK_END_MARKER,
    STDOUT_EXCERPT_MAX_CHARS,
    DesignChannel,
    build_design_cmd,
    build_design_prompt,
    build_stdout_excerpt,
    carries_design_sections,
    normalize_design,
    parse_design_fallback,
)

TICKET_TITLE = "Add the widget cache"
TICKET_DESCRIPTION = "## Problem\n\nWidgets are refetched on every render.\n"
NONCE = "a1b2c3d4e5f6"
CHANNEL = DesignChannel(path=Path("/tmp/harness-design-" + NONCE + "/design.md"), nonce=NONCE)


def _prompt() -> str:
    return build_design_prompt(TICKET_TITLE, TICKET_DESCRIPTION, channel=CHANNEL)


def _settings(cmd: list[str]) -> dict[str, object]:
    """The permissions object the command hands the engine, parsed back."""
    payload = json.loads(cmd[cmd.index("--settings") + 1])
    assert isinstance(payload, dict)
    permissions = payload["permissions"]
    assert isinstance(permissions, dict)
    return permissions


# ---------------------------------------------------------------------------
# AC-1 — the prompt
# ---------------------------------------------------------------------------


def test_prompt_names_all_five_required_sections() -> None:
    prompt = _prompt()
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
    prompt = _prompt()
    assert len(DESIGN_SECTIONS) == 5
    for section in DESIGN_SECTIONS:
        assert f"### {section}" in prompt


def test_prompt_asks_for_behaviour_in_scenarios() -> None:
    """The Scenarios section is the ticket's 'Behaviour in scenarios'."""
    assert "Behaviour in scenarios" in _prompt()


def test_prompt_carries_the_ticket() -> None:
    prompt = _prompt()
    assert TICKET_TITLE in prompt
    assert TICKET_DESCRIPTION in prompt


def test_prompt_instructs_a_design_not_implement_posture() -> None:
    """The engine designs; it never implements (architect.md, ADR 0007).

    'Read-only' is deliberately **not** asserted any more: since #294 the engine
    holds one scoped write grant, so a prompt still calling itself read-only
    would be the overclaim #294 was filed against.
    """
    prompt = _prompt().lower()
    assert "do not implement" in prompt
    assert "do not edit" in prompt


def test_prompt_names_the_absolute_output_path() -> None:
    """The file is the contract: the engine cannot write a path it is not told."""
    assert str(CHANNEL.path) in _prompt()


def test_prompt_asks_for_a_silent_stdout() -> None:
    """The design leaves on the file channel, so stdout carries no payload."""
    assert "nothing" in _prompt().lower()


def test_prompt_states_the_length_target() -> None:
    """#294: the prompt had no ceiling, and the run that died was ~2x any success."""
    assert f"{DESIGN_TARGET_CHARS:,}" in _prompt()


def test_prompt_states_the_fallback_markers_with_this_nonce() -> None:
    """The fallback is only reachable if the engine is told the exact markers."""
    prompt = _prompt()
    assert f"{FALLBACK_BEGIN_MARKER} {NONCE}" in prompt
    assert f"{FALLBACK_END_MARKER} {NONCE}" in prompt


def test_prompt_states_no_json_contract() -> None:
    """The JSON SUBMIT contract is gone, not merely unused (#294)."""
    prompt = _prompt()
    assert "SUBMIT:" not in prompt
    assert "design_markdown" not in prompt


def test_the_prompts_own_fallback_example_parses_back() -> None:
    """The markers the prompt shows are the ones the parser accepts."""
    prompt = _prompt()
    block = (
        f"{FALLBACK_BEGIN_MARKER} {NONCE}\n"
        "### Data model\n\nNo change.\n"
        f"{FALLBACK_END_MARKER} {NONCE}\n"
    )
    assert f"{FALLBACK_BEGIN_MARKER} {NONCE}" in prompt
    assert parse_design_fallback(block, NONCE) == "### Data model\n\nNo change.\n"


# ---------------------------------------------------------------------------
# AC-2 — the engine command: write capability scoped to one path
# ---------------------------------------------------------------------------


def test_model_default_is_opus() -> None:
    """ADR 0007: the design tier is unconditional, not judged per ticket."""
    assert DESIGN_MODEL_DEFAULT == "opus"


def test_command_is_a_claude_subprocess_on_the_default_model() -> None:
    cmd = build_design_cmd(channel=CHANNEL)
    assert cmd[:2] == ["claude", "-p"]
    assert cmd[cmd.index("--model") + 1] == DESIGN_MODEL_DEFAULT
    assert "codex" not in cmd


def test_command_model_is_overridable_for_testing() -> None:
    cmd = build_design_cmd(model="sonnet", channel=CHANNEL)
    assert cmd[cmd.index("--model") + 1] == "sonnet"


def test_codex_command_uses_read_only_cli_owned_output_file() -> None:
    """Codex writes the final message itself; the model gets no write grant."""
    cmd = build_design_cmd(engine="codex", model=None, channel=CHANNEL)

    assert cmd == [
        "codex",
        "exec",
        "--sandbox",
        "read-only",
        "--ephemeral",
        "--output-last-message",
        str(CHANNEL.path),
        "-",
    ]
    assert "--add-dir" not in cmd
    assert "--settings" not in cmd


def test_codex_prompt_requests_only_the_final_markdown() -> None:
    prompt = build_design_prompt(
        "Add a thing", "## Problem\n\nNo thing.\n", channel=CHANNEL, engine="codex"
    )

    assert "Return only the Design section Markdown as your final response." in prompt
    assert str(CHANNEL.path) not in prompt
    assert FALLBACK_BEGIN_MARKER not in prompt
    assert FALLBACK_END_MARKER not in prompt


def test_explicit_claude_prompt_keeps_the_scoped_file_and_fallback_contract() -> None:
    prompt = build_design_prompt(
        "Add a thing", "## Problem\n\nNo thing.\n", channel=CHANNEL, engine="claude"
    )

    assert str(CHANNEL.path) in prompt
    assert f"{FALLBACK_BEGIN_MARKER} {NONCE}" in prompt
    assert f"{FALLBACK_END_MARKER} {NONCE}" in prompt


def test_command_is_no_longer_plan_mode() -> None:
    """Plan mode is what forced stdout to be the only channel (#294)."""
    assert "plan" not in build_design_cmd(channel=CHANNEL)


def test_the_only_write_grant_is_the_design_path() -> None:
    """The scoped control that replaces plan mode's cooperative one.

    Measured, not assumed: a ``Write(...)`` rule is silently inert (the CLI
    matches only ``Edit(...)`` rules against file writes) and a bare filesystem
    path is read gitignore-style relative to the project, so the leading ``/``
    that makes it absolute is load-bearing. Both were established against the
    real binary; this asserts the shape that worked.
    """
    permissions = _settings(build_design_cmd(channel=CHANNEL))
    allow = permissions["allow"]
    assert isinstance(allow, list)
    edit_rules = [rule for rule in allow if rule.startswith("Edit(")]
    assert edit_rules == [f"Edit(/{CHANNEL.path})"]
    assert not [rule for rule in allow if rule.startswith("Write(")], (
        "a Write(...) rule grants nothing — the CLI matches Edit(...) rules "
        "against every file-writing tool and ignores Write(...) ones"
    )


def test_nothing_but_read_only_git_is_granted_on_the_shell() -> None:
    """Bash access stays what plan mode allowed: reading history, not changing it."""
    permissions = _settings(build_design_cmd(channel=CHANNEL))
    allow = permissions["allow"]
    assert isinstance(allow, list)
    bash_rules = sorted(rule for rule in allow if rule.startswith("Bash("))
    assert bash_rules == [
        "Bash(git diff:*)",
        "Bash(git log:*)",
        "Bash(git show:*)",
    ]


def test_unlisted_capability_is_refused_rather_than_prompted() -> None:
    """Under ``-p`` there is nobody to prompt, so 'ask' must mean 'refuse'."""
    permissions = _settings(build_design_cmd(channel=CHANNEL))
    assert permissions["defaultMode"] == "manual"


def test_the_mutating_and_network_tools_are_denied_outright() -> None:
    permissions = _settings(build_design_cmd(channel=CHANNEL))
    deny = permissions["deny"]
    assert isinstance(deny, list)
    for tool in ("NotebookEdit", "WebFetch", "WebSearch"):
        assert tool in deny
    assert "Edit" not in deny, (
        "denying Edit outright would deny the one grant the design needs — the "
        "allow rule above *is* an Edit rule"
    )


def test_the_grant_follows_the_channel_it_is_given() -> None:
    """A second run's path is a second run's grant — no fixed path anywhere."""
    other = DesignChannel(path=Path("/tmp/harness-design-zzz/design.md"), nonce="zzz")
    permissions = _settings(build_design_cmd(channel=other))
    allow = permissions["allow"]
    assert isinstance(allow, list)
    assert f"Edit(/{other.path})" in allow
    assert f"Edit(/{CHANNEL.path})" not in allow


def test_the_design_model_is_not_resolved_from_the_ticket() -> None:
    """The design model is a constant, not a per-ticket value (ADR 0007).

    What this asserted until #321 was that ``design_protocol`` had not imported
    ``review_protocol``'s per-ticket tier resolver. That resolver no longer
    exists anywhere, so the ``hasattr`` half would now pass for a reason with
    nothing to do with design — a vacuous guard, worse than none. What still has
    content is the command builder's own signature: it takes no ticket and no
    labels, so there is no channel by which a ticket could select the model.
    """
    import inspect

    from harness.cli import design_protocol

    parameters = inspect.signature(design_protocol.build_design_cmd).parameters
    assert not {"labels", "ticket", "issue"} & set(parameters), parameters


# ---------------------------------------------------------------------------
# AC-3 — the stdout fallback parser
# ---------------------------------------------------------------------------


def test_fallback_extracts_the_body_between_the_markers() -> None:
    stdout = (
        "some chatter\n"
        f"{FALLBACK_BEGIN_MARKER} {NONCE}\n"
        "### Data model\n\nNo change.\n"
        f"{FALLBACK_END_MARKER} {NONCE}\n"
        "trailing chatter\n"
    )
    assert parse_design_fallback(stdout, NONCE) == "### Data model\n\nNo change.\n"


def test_fallback_recovers_a_body_whose_end_marker_never_arrived() -> None:
    """The salvage property — the whole reason JSON was the wrong container.

    #294's motivating run lost 31 KB of Opus because one closing brace did not
    arrive. Here the equivalent loss — a missing closing marker — costs nothing.
    """
    stdout = f"{FALLBACK_BEGIN_MARKER} {NONCE}\n### Data model\n\nNo change.\n"
    assert parse_design_fallback(stdout, NONCE) == "### Data model\n\nNo change.\n"


def test_fallback_is_none_when_no_start_marker_appears() -> None:
    assert parse_design_fallback("I thought about it and gave up.\n", NONCE) is None


def test_fallback_ignores_a_block_bearing_a_different_nonce() -> None:
    """The nonce is per-invocation, so a stale block cannot be adopted."""
    stdout = f"{FALLBACK_BEGIN_MARKER} deadbeef\n### Data model\n"
    assert parse_design_fallback(stdout, NONCE) is None


def test_fallback_takes_the_last_marked_block() -> None:
    """The contract asks for one block at the end; earlier ones are reasoning."""
    stdout = (
        f"{FALLBACK_BEGIN_MARKER} {NONCE}\nfirst draft\n"
        f"{FALLBACK_END_MARKER} {NONCE}\n"
        f"{FALLBACK_BEGIN_MARKER} {NONCE}\nfinal\n"
        f"{FALLBACK_END_MARKER} {NONCE}\n"
    )
    assert parse_design_fallback(stdout, NONCE) == "final\n"


def test_fallback_is_none_for_a_marked_but_empty_block() -> None:
    stdout = f"{FALLBACK_BEGIN_MARKER} {NONCE}\n   \n{FALLBACK_END_MARKER} {NONCE}\n"
    assert parse_design_fallback(stdout, NONCE) is None


def test_fallback_markers_are_matched_whole_not_by_prefix() -> None:
    """``END-HARNESS-DESIGN`` contains the begin marker; equality, not prefix."""
    assert FALLBACK_BEGIN_MARKER in FALLBACK_END_MARKER
    stdout = f"{FALLBACK_END_MARKER} {NONCE}\nnot a design\n"
    assert parse_design_fallback(stdout, NONCE) is None


def test_fallback_tolerates_an_indented_marker() -> None:
    stdout = f"  {FALLBACK_BEGIN_MARKER} {NONCE}\nbody\n  {FALLBACK_END_MARKER} {NONCE}\n"
    assert parse_design_fallback(stdout, NONCE) == "body\n"


# ---------------------------------------------------------------------------
# AC-4 — one blank-is-not-a-design rule, shared by both channels
# ---------------------------------------------------------------------------


def test_normalize_maps_blank_and_missing_to_none() -> None:
    """An engine that delivered whitespace did not design; both channels agree."""
    for blank in (None, "", "   ", "\n\n\t\n"):
        assert normalize_design(blank) is None


def test_normalize_keeps_a_real_design_intact_but_trimmed() -> None:
    assert normalize_design("\n### Data model\n\nNo change.\n\n") == (
        "### Data model\n\nNo change."
    )


# ---------------------------------------------------------------------------
# AC-5 — the failure excerpt stays bounded
# ---------------------------------------------------------------------------


def test_excerpt_quotes_the_end_of_stdout() -> None:
    """What the engine said instead of delivering is at the end."""
    stdout = "### Data model\nlots of design\nLet me know if you want changes.\n"
    assert build_stdout_excerpt(stdout) == stdout


def test_excerpt_is_bounded_for_any_stdout_size() -> None:
    """The change's one measurable criterion — the ledger is not a log."""
    for size in (1, 500, 2_000, 20_000, 200_000):
        excerpt = build_stdout_excerpt("x" * size)
        assert excerpt is not None
        assert len(excerpt) <= STDOUT_EXCERPT_MAX_CHARS, f"{size} -> {len(excerpt)}"


def test_excerpt_keeps_the_tail_when_it_truncates() -> None:
    excerpt = build_stdout_excerpt("HEADMARK" + "x" * 40_000 + "TAILMARK")
    assert excerpt is not None
    assert excerpt.endswith("TAILMARK")
    assert "HEADMARK" not in excerpt


def test_empty_stdout_has_no_excerpt() -> None:
    """``None`` reads as 'the engine emitted nothing'; ``''`` would not."""
    assert build_stdout_excerpt("") is None


# ---------------------------------------------------------------------------
# AC-6 — the regression: the payload that killed the JSON contract
# ---------------------------------------------------------------------------


def _hostile_design() -> str:
    """A design shaped like the one #294's run lost: big, braced, quoted, blank-lined."""
    block = (
        '### Data model\n\nA `{"key": "value"}` literal, a closing } alone,\n'
        'an unbalanced { and a "quoted" phrase.\n\n'
        "```json\n{\n  \"nested\": {\"deeper\": [1, 2]}\n}\n```\n\n"
    )
    design = block * 200
    assert len(design) > 30_000, "the regression must exceed the payload that failed"
    return design


def test_a_31kb_braced_design_survives_the_fallback_channel() -> None:
    """The JSON contract could not carry this; the marked block carries it whole."""
    design = _hostile_design()
    stdout = (
        f"{FALLBACK_BEGIN_MARKER} {NONCE}\n{design}{FALLBACK_END_MARKER} {NONCE}\n"
    )
    assert parse_design_fallback(stdout, NONCE) == design


def test_a_31kb_braced_design_survives_a_lost_end_marker() -> None:
    """The exact failure #294 observed, now costing nothing."""
    design = _hostile_design()
    stdout = f"{FALLBACK_BEGIN_MARKER} {NONCE}\n{design}"
    assert parse_design_fallback(stdout, NONCE) == design


# ---------------------------------------------------------------------------
# AC-7 — the Codex channel's structural floor
# ---------------------------------------------------------------------------
#
# Claude's file exists only if the model deliberately wrote to the one path it
# was granted, so the file existing *is* the signal that a design was produced.
# Codex has no such signal: ``--output-last-message`` is written by the CLI on
# every completed turn, so a refusal or a clarifying question lands in the same
# file a design would.  :func:`carries_design_sections` is what stands in for
# the missing signal — the floor below which a final message is not a design.
#
# The floor is **one** recognized section heading, not all five, and that
# threshold is load-bearing in both directions: a real design may legitimately
# omit a section (``_DESIGN`` in ``test_cli_design.py`` carries two), while
# ordinary prose carries none.  The pair of tests below pin it from each side,
# so raising the threshold to two or lowering it to zero fails here.


def test_one_recognized_section_heading_is_enough() -> None:
    """The floor is one, pinned from below: raising it to two fails here."""
    assert carries_design_sections("### Data model\n\nNo change.\n") is True


def test_prose_carrying_no_section_heading_is_not_a_design() -> None:
    """The case the floor exists for: Codex answering instead of designing."""
    text = (
        "The ticket description is empty, so there is nothing to design against. "
        "Tell me what behaviour you want and I will produce the design section."
    )
    assert carries_design_sections(text) is False


def test_every_declared_section_name_is_recognized() -> None:
    """Derived from ``DESIGN_SECTIONS`` — the list the prompt itself is built from.

    Derived rather than listed so a sixth section added to the prompt cannot
    ship with the recognizer silently blind to it.  The floor assertion below
    is the one from #168: a derivation that dies returns an empty set and
    ``all()`` over nothing is vacuously green.
    """
    assert len(DESIGN_SECTIONS) >= 5
    assert "Data model" in DESIGN_SECTIONS
    assert all(carries_design_sections(f"## {name}\n\nBody.\n") for name in DESIGN_SECTIONS)


def test_a_bold_line_counts_as_a_section_heading() -> None:
    """A real observed shape: models emit ``**Data model**`` as often as ``### ``."""
    assert carries_design_sections("**Interface / contract**\n\nOne new flag.\n") is True


def test_a_section_name_in_running_prose_is_not_a_heading() -> None:
    """The narrowing's control: the name must be the whole line, not a mention.

    Without this a refusal that says "I need the data model first" would read as
    a design.  Mutation-checked: dropping the whole-line anchor from the pattern
    turns this green→red.
    """
    text = "I cannot produce this until you tell me what the data model should be."
    assert carries_design_sections(text) is False
