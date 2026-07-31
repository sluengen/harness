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

import hashlib
import json

from pydantic import BaseModel, ValidationError

__all__ = [
    "DESIGN_MODEL_DEFAULT",
    "DESIGN_SECTIONS",
    "DesignResult",
    "MALFORMED_SUBMIT_SENTINEL",
    "NO_SUBMIT_SENTINEL",
    "SUBMIT_EXCERPT_BUDGET",
    "build_design_cmd",
    "build_design_prompt",
    "design_content_hash",
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

# How much of the unparseable output a failed parse keeps (#277).
#
# The ledger is an audit trail, not a log. A real design payload measured 14–17
# KB across three recorded runs (#271/#272/#273), so keeping the offending line
# whole would put a design-sized blob on every failed event. What actually
# diagnoses is far smaller: how the line *starts* (a code fence, a prose
# preamble) and where it *stopped* (a truncation, an unterminated string), which
# is why the window below keeps both ends and elides the middle rather than
# taking a prefix.
SUBMIT_EXCERPT_BUDGET = 400

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

    ``excerpt`` accompanies ``error`` and is ``None`` on success (#277): a
    bounded description of what would not parse. Without it a failure records
    only *that* the contract broke, which is why a 12.5% failure rate could
    accumulate over 72 attempts with nothing to diagnose from.
    """

    design_markdown: str | None = None
    error: str | None = None
    excerpt: str | None = None


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


def _describe(text: str, why: str) -> str:
    """One bounded, self-describing line about output that would not parse.

    Three facts, because each answers a different question the next reader has:
    *why* it failed, *how long* the payload really was (a 15 KB line elided to
    :data:`SUBMIT_EXCERPT_BUDGET` must still say it was 15 KB, or truncation and
    verbosity look identical), and a **head-and-tail window** onto the text.

    The text is untrusted engine output, so it is bounded here rather than at
    the caller — this is the only place that knows the budget, and every failure
    path routes through it.
    """
    if len(text) <= SUBMIT_EXCERPT_BUDGET:
        window = text
    else:
        half = SUBMIT_EXCERPT_BUDGET // 2
        elided = len(text) - 2 * half
        window = f"{text[:half]}[…{elided} chars elided…]{text[-half:]}"
    return f"{why} ({len(text)} chars): {window}"


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

    Either failure also carries an ``excerpt`` (#277) describing what would not
    parse — for a malformed line, the **last** one that failed, since the real
    submission is the final line and an earlier stray must not be the thing
    reported.
    """
    last_failure: str | None = None
    for line in stdout.splitlines():
        stripped = line.strip()
        if not stripped.startswith("SUBMIT:"):
            continue
        json_part = stripped[len("SUBMIT:") :].strip()
        try:
            payload = json.loads(json_part)
        except json.JSONDecodeError as exc:
            last_failure = _describe(json_part, f"the JSON did not parse ({exc})")
            continue
        if not isinstance(payload, dict):
            last_failure = _describe(
                json_part, f"the payload is a JSON {type(payload).__name__}, not an object"
            )
            continue
        try:
            submit = _Submit.model_validate(payload)
        except ValidationError:
            last_failure = _describe(
                json_part, "the payload carries no string `design_markdown` field"
            )
            continue
        design = submit.stripped_or_none()
        if design is None:
            last_failure = _describe(json_part, "`design_markdown` is blank")
            continue
        return DesignResult(design_markdown=design)

    if last_failure is not None:
        return DesignResult(error=MALFORMED_SUBMIT_SENTINEL, excerpt=last_failure)
    return DesignResult(
        error=NO_SUBMIT_SENTINEL,
        excerpt=_describe(stdout, "no `SUBMIT:` line anywhere in the engine's stdout"),
    )


# ---------------------------------------------------------------------------
# Content hash — the design's identity, shared by its writer and its verifier
# ---------------------------------------------------------------------------


def design_content_hash(design_markdown: str) -> str:
    """The design's content hash — sha256 of its UTF-8 bytes, hex-encoded.

    Two verbs depend on this being the *same* rule. ``design`` records it on the
    ledger event (the body itself stays off the ledger, ADR 0007), and ``review``
    recomputes it over the design the orchestrator hands back to authenticate
    that text against the recorded attempt (#212). A second inlined ``hashlib``
    call in either verb would let the writer and the verifier drift into
    permanently mismatching hashes, so the rule lives here — in the design
    stage's protocol layer, beside the rest of its contract — and both call it.
    """
    return hashlib.sha256(design_markdown.encode("utf-8")).hexdigest()


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
