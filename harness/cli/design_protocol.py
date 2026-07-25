"""The design engine protocol — prompt, SUBMIT contract, model default.

ADR 0007 adds a ``design`` stage to the run lifecycle (``start → design →
implement → review → (fix → review)* → close``): a read-only engine studies the
run's worktree and ticket in a fresh, dedicated context and produces the change
spec's technical Design section, before the build session writes any code.

This module is that stage's **protocol layer** — the sibling of
:mod:`harness.cli.review_protocol`, and built the same way (#210):

* the design **prompt** (:func:`build_design_prompt`) and the **SUBMIT**
  contract it states;
* the SUBMIT **parser** (:func:`parse_design_submit`) and its result type
  (:class:`DesignResult`);
* the **engine invocation** (:func:`build_design_cmd`) and the model default
  (:data:`DESIGN_MODEL_DEFAULT`).

Everything here is a pure function or a data/type definition: no CLI, no
ledger, no tracker, no I/O. The module is inert until the ``design`` verb
consumes it (breakdown item 2).

Two deliberate differences from the review protocol, both from ADR 0007:

* **Claude only.** ADR 0002 keeps the in-container engine unprivileged, where
  Codex's ``bwrap`` sandbox cannot start; design has no codex variant at all,
  so there is no ``Engine`` union and no per-engine branch to build.
* **Opus unconditionally.** The tier is a constant, not a per-ticket label.
  ``review_protocol.resolve_model_tier`` is dimension-generic and remains the
  seam a future tier label would hang off; it is deliberately not wired here.

The two protocols are kept separate rather than sharing a scanner: their SUBMIT
payloads carry different fields and their failure handling differs (a review
records a ``fail`` verdict on garbled output; a design has no verdict to
record, only a distinguishable error). Entangling them to save a loop would
couple two contracts that are free to move apart.
"""

from __future__ import annotations

import json

from pydantic import BaseModel, ValidationError

__all__ = [
    "DESIGN_MODEL_DEFAULT",
    "DESIGN_SECTIONS",
    "DesignResult",
    "MALFORMED_SUBMIT_SENTINEL",
    "NO_SUBMIT_SENTINEL",
    "build_design_cmd",
    "build_design_prompt",
    "parse_design_submit",
]

# The design engine's model. Opus for every run, per ADR 0007: the design
# stage's value is top-tier thinking in a context uncontaminated by the build
# session's orchestration state, so the tier is unconditional rather than
# label-gated. A cheaper tier stays an anticipated refinement, not a seam built
# on speculation.
DESIGN_MODEL_DEFAULT = "opus"

# The two ways a design engine can fail to deliver a design. They are kept
# **distinct** because they mean different things to the operator reading the
# ledger: the first says the engine never reached its contract (it timed out,
# rambled, or refused), the second says it tried and emitted garbage. ADR 0007
# degrades and records either way — the build proceeds — so the recorded reason
# is the only evidence of which happened.
NO_SUBMIT_SENTINEL = "design engine emitted no SUBMIT line"
MALFORMED_SUBMIT_SENTINEL = "design engine emitted a malformed SUBMIT line"

# The sections a design must carry, in order. Three come from
# ``templates/change.md``'s Design block — the artifact is that block, not a
# new artifact class (ADR 0007) — and Security and Test strategy from the
# ``architecture`` skill's "what a design produces". Single-sourced here and
# rendered into the prompt, so the list cannot drift from what is asked for.
DESIGN_SECTIONS: tuple[str, ...] = (
    "Data model",
    "Interface / contract",
    "Scenarios",
    "Security",
    "Test strategy",
)

_SECTION_BRIEFS: dict[str, str] = {
    "Data model": (
        "Entities, fields, relationships, and invariants that change. Note any "
        "migration."
    ),
    "Interface / contract": (
        "Endpoints, commands, or component contracts: request/response shapes, "
        "status and error cases, auth rules."
    ),
    "Scenarios": (
        "Behaviour in scenarios where it is non-obvious or edge cases are easy "
        "to forget, as GIVEN {precondition} WHEN {action} THEN {outcome}."
    ),
    "Security": (
        "The trust boundaries this change touches, the validation at each, and "
        "what data is exposed to whom."
    ),
    "Test strategy": (
        "What to test, the key edge cases, and the integration points — enough "
        "that an implementer can write the first failing test from it."
    ),
}


# ---------------------------------------------------------------------------
# Design prompt
# ---------------------------------------------------------------------------

_PROMPT_TEMPLATE = """\
You are the architect for the ticket below. Study this worktree read-only and
produce its technical design. You design; you do not implement — do not edit,
create, or delete any file, and do not write code beyond short illustrative
snippets inside the design itself.

Ticket: {ticket_title}

{ticket_description}

Produce the change spec's Design section as Markdown, with exactly these
sections, in this order:

{section_brief}

Design to the current scope: simple, proven patterns, grounded in what this
worktree actually contains. Leave room to extend; do not design the extension.
Where you had a real choice, say which alternative you rejected and why.

When you have finished, you MUST emit a single final line of the exact form:

SUBMIT: <json>

where <json> is a JSON object with one field:
  - design_markdown: string — the Design section as Markdown, containing the
    sections listed above

Emit exactly one SUBMIT line. Example:

{submit_example}
"""

_SUBMIT_EXAMPLE = 'SUBMIT: {"design_markdown": "### Data model\\n\\nNo change.\\n..."}'


def build_design_prompt(ticket_title: str, ticket_description: str) -> str:
    """Build the design engine's prompt for one ticket.

    The prompt states three things the engine cannot infer: the **posture**
    (read-only, design-not-implement), the **shape** of the output (the five
    :data:`DESIGN_SECTIONS`, rendered from the single list above), and the
    **contract** (one final ``SUBMIT: <json>`` line carrying
    ``design_markdown``). The ticket is interpolated verbatim — it is the spec
    the design answers to.

    The ticket text is untrusted input read from the tracker, which is why the
    engine runs read-only (:func:`build_design_cmd`): a prompt-injection
    attempt inside a ticket body reaches an engine with no capability to edit
    the host, and its only channel back is one parsed string.
    """
    section_brief = "\n\n".join(
        f"### {section}\n{_SECTION_BRIEFS[section]}" for section in DESIGN_SECTIONS
    )
    return _PROMPT_TEMPLATE.format(
        ticket_title=ticket_title,
        ticket_description=ticket_description,
        section_brief=section_brief,
        submit_example=_SUBMIT_EXAMPLE,
    )


# ---------------------------------------------------------------------------
# SUBMIT-line parser
# ---------------------------------------------------------------------------


class DesignResult(BaseModel):
    """The outcome of one design engine run, as parsed from its stdout.

    Exactly one of the two fields is set: ``design_markdown`` on success,
    ``error`` on either failure. The verb records whichever it gets — ADR 0007
    enforces that a design was *attempted and recorded*, not that it succeeded,
    so a failure here is data, never an exception.
    """

    design_markdown: str | None = None
    error: str | None = None


class _Submit(BaseModel):
    """Internal validation of the SUBMIT line's JSON payload."""

    design_markdown: str

    def stripped_or_none(self) -> str | None:
        """The design, or ``None`` when it is blank.

        An engine that emits a well-formed SUBMIT line carrying whitespace has
        claimed success without designing anything; treating that as a success
        would put an empty Design section on the ticket.
        """
        return self.design_markdown if self.design_markdown.strip() else None


def parse_design_submit(stdout: str) -> DesignResult:
    """Parse the first valid ``SUBMIT: <json>`` line out of engine stdout.

    Three distinct outcomes, so the ledger can say which happened:

    * a valid line — :attr:`DesignResult.design_markdown` carries the design,
      ``error`` is ``None``;
    * **no** ``SUBMIT:`` line at all — :data:`NO_SUBMIT_SENTINEL`;
    * a ``SUBMIT:`` line that does not parse, is not an object, lacks
      ``design_markdown``, carries a non-string there, or carries only
      whitespace — :data:`MALFORMED_SUBMIT_SENTINEL`.

    Scanning mirrors the review parser: later lines are still tried after a bad
    one, so a stray ``SUBMIT:`` inside the engine's reasoning cannot mask the
    real submission at the end. Malformed is reported only when no valid line
    was found anywhere.
    """
    saw_submit_line = False
    for line in stdout.splitlines():
        stripped = line.strip()
        if not stripped.startswith("SUBMIT:"):
            continue
        saw_submit_line = True
        json_part = stripped[len("SUBMIT:") :].strip()
        try:
            payload = json.loads(json_part)
        except json.JSONDecodeError:
            continue
        if not isinstance(payload, dict):
            continue
        try:
            submit = _Submit.model_validate(payload)
        except ValidationError:
            continue
        design = submit.stripped_or_none()
        if design is None:
            continue
        return DesignResult(design_markdown=design)

    error = MALFORMED_SUBMIT_SENTINEL if saw_submit_line else NO_SUBMIT_SENTINEL
    return DesignResult(error=error)


# ---------------------------------------------------------------------------
# Engine command builder
# ---------------------------------------------------------------------------


def build_design_cmd(*, model: str = DESIGN_MODEL_DEFAULT) -> list[str]:
    """Build the design engine invocation — ``claude -p`` in **plan** mode.

    Read-only by construction: plan mode may read files and run read-only git,
    but carries no edit, write, or bypass capability, so the untrusted ticket
    body and worktree contents the engine reads cannot mutate the host. Its
    only output channel is the SUBMIT line :func:`parse_design_submit` reads.

    Claude is the only engine (ADR 0002 / 0007) — there is no codex variant to
    select. ``model`` defaults to :data:`DESIGN_MODEL_DEFAULT` and is passed on
    every run; the parameter exists for a host-side override in testing, not
    for per-ticket tier resolution, which ADR 0007 leaves unbuilt.
    """
    return ["claude", "-p", "--permission-mode", "plan", "--model", model]
