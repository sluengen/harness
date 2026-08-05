"""The review engine protocol — pure engine-bug knowledge, no verb orchestration.

The ``review`` verb talks to a read-only CLI review engine (``claude`` or
``codex``) over one narrow contract: feed it :data:`_REVIEW_PROMPT` on stdin and
scan its stdout for a single ``SUBMIT: <json>`` line. Around that contract sits a
layer of *engine quirks* — knowledge of how a specific engine misbehaves — that
is empirically derived, pure, and separately tested, and that has nothing to do
with the verb's run resolution, ledger writes, spend breakers, gate evidence, or
tracker transitions.

This module is that layer, split out of ``harness.cli.review`` (CAL-1107) so the
engine-bug knowledge lives apart from the verb orchestration:

* the review **prompt** and the **SUBMIT** contract (:func:`scan_submit_line`);
* the **engine identity** (:data:`Engine`) and per-engine **command builder**
  (:func:`_build_cmd`);
* the three empirically-derived **failure detectors** — a Codex usage-limit that
  should fall back to Claude (:func:`is_codex_usage_limit`, CAL-702), and the two
  sandbox walls that mean the engine reviewed *nothing* and must surface as infra
  rather than a verdict (:func:`is_sandbox_init_failure`, CAL-866, and its exit-0
  masquerading-defer sibling :func:`is_sandbox_blocked_defer`, CAL-924).

Everything here is a pure function or a data/type definition: no I/O, no ledger,
no Typer. The verb (:mod:`harness.cli.review`) imports and re-exports these names,
so an engine quirk is a change *here*, not in the verb.
"""

from __future__ import annotations

import json
from typing import Any, Literal

from pydantic import BaseModel

from harness.cli._engine import Runner, RunResult
from harness.cli.design_protocol import design_content_hash
from harness.events.payloads import DESIGN_HASH_KEY, DESIGN_STATUS_KEY

# size: the review engine's protocol layer — one cohesive body of *pure* engine
# knowledge, split out of the verb in CAL-1107 and kept together because every
# part of it answers the same question (what does this engine's output mean?):
# the prompt and its design-context block, the SUBMIT scanner, the per-engine
# command builder, and the three empirically-derived failure detectors. (The
# per-ticket model-tier resolver was the fourth until #321 retired it: the model
# is now one configured value the verb reads off its already-loaded
# ``LoopBudget``, which is not engine knowledge and needs no home here.)
# Length here is overwhelmingly the *evidence*
# for the empirical parts — the captured stderr each detector matches, and why
# each match is narrow — which is the one thing that must not be trimmed, since
# without it a future reader cannot tell a real engine quirk from a guess.
# The module sat one line under the limit and #270 crossed it by adding the
# second SUBMIT sentinel and its discriminator.
# The extraction candidate, if it grows again, is the design gate
# (``DesignGate`` + ``resolve_design_gate``, ~110 lines): it is a *policy*
# decision about the ledger's design record, not engine-output knowledge, and it
# is the one part of this module that would read coherently on its own — the
# ``review_inherit`` / ``design_adopt`` precedent for lifting a decision out.
__all__ = [
    "DEFAULT_ENGINE",
    "DesignContextReason",
    "DesignGate",
    "Engine",
    "NO_DESIGN_REASON",
    "RunResult",
    "Runner",
    "Verdict",
    "MALFORMED_SUBMIT_SENTINEL",
    "NO_SUBMIT_SENTINEL",
    "build_review_prompt",
    "resolve_design_gate",
    "scan_submit_line",
    "is_codex_usage_limit",
    "is_sandbox_init_failure",
    "is_sandbox_blocked_defer",
]

# The two ways the reviewer can fail to deliver a verdict, kept distinct so the
# verb can tag them apart in the ledger (#270), mirroring ``design_protocol``'s
# pair: the first says the engine never reached its contract, the second that it
# tried and emitted garbage. Reported as human sentinels because this module is
# pure and knows nothing of exit codes or ``reason`` tags — the verb maps them.
NO_SUBMIT_SENTINEL = "reviewer emitted no valid SUBMIT line"
MALFORMED_SUBMIT_SENTINEL = "reviewer emitted a malformed SUBMIT line"

# The verdicts the SUBMIT line may carry.  Anything else is treated as garbled.
_VALID_VERDICTS: frozenset[str] = frozenset({"pass", "fail", "defer"})

Verdict = Literal["pass", "fail", "defer"]

# The review engines.  Both are CLI subprocesses emitting the same ``SUBMIT:``
# contract — never the Agent SDK (CAL-701; architecture-principles "a review
# engine is a CLI subprocess").  ``claude`` is the default: it is available on
# the standard tier and auto-compacts, so the gate does not degrade to a false
# ``fail`` when the Codex tier is depleted.  ``codex`` stays opt-in for a
# cross-model second opinion.
Engine = Literal["claude", "codex"]
DEFAULT_ENGINE: Engine = "claude"


# :class:`RunResult` and :data:`Runner` describe the *driver's* contract, not this
# protocol's, so they live in :mod:`harness.cli._engine` alongside the one
# subprocess driver both engine verbs share (#211). They are imported above and
# re-exported here (``__all__``) so every existing ``review_protocol`` / ``review``
# import of them keeps resolving unchanged.


# ---------------------------------------------------------------------------
# Review prompt
# ---------------------------------------------------------------------------

_REVIEW_INTRO = """\
You are the reviewer. Review the implementation at the current git HEAD of this
worktree against the ticket's acceptance criteria and the repository's
engineering standards.
"""

# The design context block (#212, ADR 0007). Sits between the framing and the
# SUBMIT contract so the contract stays the *last* thing the engine reads, and
# states what the design is FOR: a second criterion the diff answers to, not a
# spec that outranks the ticket. A design that contradicts the ticket is itself
# a finding — the proposal's stated mitigation for "a bad design misleads worse
# than no design".
_DESIGN_CONTEXT_TEMPLATE = """
This run has a recorded technical design, produced by `harness design` before
the implementation was written. Review the diff against it as well as the
ticket: conformance to the design is a criterion, and an unexplained departure
from it is a finding. The design does not outrank the ticket — where the two
conflict, say so.

--- BEGIN DESIGN ---
{design_markdown}
--- END DESIGN ---
"""

_SUBMIT_CONTRACT = """
When you have finished, you MUST signal your verdict by emitting a single line
of the exact form:

SUBMIT: <json>

where <json> is a JSON object with these fields:
  - verdict: one of "pass", "fail", "defer"
  - issues: array of strings (empty on a clean pass; the blocking findings on a
    fail; the reason to defer on a defer)
  - commit_message: string (optional) — a suggested commit message on a pass
  - deferred_brief: string (optional) — a brief for the deferred follow-up

Emit exactly one SUBMIT line. Example:

SUBMIT: {"verdict": "pass", "issues": []}
"""

#: The prompt with no design context — the shape every review had before #212,
#: kept as a name because the verb and its tests import it.
_REVIEW_PROMPT = _REVIEW_INTRO + _SUBMIT_CONTRACT


def build_review_prompt(design_markdown: str | None = None) -> str:
    """The review prompt, with the run's design as context when there is one.

    Without a design this is byte-identical to the pre-#212 prompt, so a run
    whose design stage failed (ADR 0007 D4 degrades and records) reviews exactly
    as it always did. With one, the design is embedded **verbatim** between the
    framing and the ``SUBMIT`` contract — never summarised, since the point is
    that the engine reviews conformance to what was actually designed.
    """
    if design_markdown is None:
        return _REVIEW_PROMPT
    design_block = _DESIGN_CONTEXT_TEMPLATE.format(design_markdown=design_markdown)
    return _REVIEW_INTRO + design_block + _SUBMIT_CONTRACT


# ---------------------------------------------------------------------------
# The design gate (#212, ADR 0007 D3/D4) — pure decision, no ledger, no I/O
# ---------------------------------------------------------------------------

#: The run recorded no design attempt at all. Mirrors ``no_gate_evidence``:
#: silence is not a pass, and the refusal names the verb that satisfies it.
#: This is the *only* refusal the design stage produces — see
#: :func:`resolve_design_gate` for why a failure to supply the design itself is
#: a degradation rather than a second refusal.
NO_DESIGN_REASON = "no_design"

#: Why a review proceeded WITHOUT design context, when it did (AC-1, #247) —
#: recorded alongside ``design_context`` so "did the linkage stop working, and
#: why" is a ledger question, not a console-noise one. ``design_failed``: the
#: run's design attempt did not succeed (ADR 0007 D4). ``not_supplied``: no
#: ``--design-file`` was passed. ``unreadable``: a path was passed but could
#: not be read — see :data:`DESIGN_FILE_OUTSIDE_WORKSPACE_REASON` for the
#: subset of this now caught earlier, as a refusal. ``hash_mismatch``: a
#: readable file's content hash does not match the recorded ``design_hash``
#: (or none was recorded to check against).
DesignContextReason = Literal["design_failed", "not_supplied", "unreadable", "hash_mismatch"]


class DesignGate(BaseModel):
    """What the design stage's record says this review may do.

    One refusal (:data:`NO_DESIGN_REASON`), or a ``design_markdown`` to review
    against, or neither — proceed with no design context, which is what a
    recorded *failed* attempt earns. A ``warning`` may accompany the last case,
    and ``context_reason`` (AC-1, #247) always does, naming *why* no design
    reached the engine — absent only when ``design_markdown`` is set.
    """

    refusal_reason: str | None = None
    refusal_message: str | None = None
    design_markdown: str | None = None
    warning: str | None = None
    context_reason: DesignContextReason | None = None


def resolve_design_gate(
    event: dict[str, Any] | None, supplied_design: str | None
) -> DesignGate:
    """Decide the design gate from the run's latest ``design`` event.

    ``event`` is that event's payload (``None`` when the run has none), and
    ``supplied_design`` the text read from ``--design-file`` — ``None`` only
    when no path was given, and the empty string when one was given but could
    not be read, so an unreadable file is reported rather than passed over as
    though nothing was supplied.

    Five outcomes, each recorded on the returned :class:`DesignGate` as
    ``context_reason`` (:data:`DesignContextReason`, AC-1 #247) when no design
    reaches the engine — a ``None`` reason means the last outcome, the design
    applied:

    * **no event** → refuse :data:`NO_DESIGN_REASON`. The design stage runs on
      every run (ADR 0007 D1), so its absence means it was skipped.
    * **a ``failed`` event** → proceed with no context, reason
      ``"design_failed"``. D4 is explicit that the check is *attempted and
      recorded*, not *succeeded*; there is no design to review against, and
      any text supplied for one is ignored, since no recorded hash could
      authenticate it.
    * **an ``ok`` event + no text supplied** → proceed with no context, reason
      ``"not_supplied"``.
    * **an ``ok`` event + text that could not be read** (the empty-string
      sentinel) → proceed with no context, reason ``"unreadable"``.
    * **an ``ok`` event + text that does not match the recorded hash** (or the
      event recorded none to check against) → proceed with no context, reason
      ``"hash_mismatch"``.
    * **an ``ok`` event + text whose hash matches** → that design becomes the
      context the engine reviews against; ``context_reason`` stays ``None``.

    **Enforcement refuses; context degrades.** The two halves of ADR 0007's
    review linkage have deliberately different postures. Enforcement keys on the
    ledger alone — the flag can neither satisfy nor bypass it — so it refuses.
    Context is enrichment: the safe outcome, never feeding a wrong or unverified
    design to the engine, is fully achieved by *dropping* it, so refusing there
    would add a wedge (a stale file left on disk failing an otherwise shippable
    run) and buy nothing. That is the degrade-and-record posture the rest of the
    verb takes for non-load-bearing steps.

    **What is warned about, and what is merely recorded.** A ``warning`` is set
    only when something is *wrong* — text was supplied and could not be matched
    to the record. Simply not supplying a design is a normal state (an
    orchestrator that has not adopted the flag), and warning on it would put a
    line on every review until every caller does, which trains readers to ignore
    the warning that matters. That case is instead recorded on the ``review``
    event (``design_context``), so whether a review actually saw the design is
    auditable from the ledger rather than from console noise.
    """
    if event is None:
        return DesignGate(
            refusal_reason=NO_DESIGN_REASON,
            refusal_message=(
                "this run has no recorded design attempt. ADR 0007 makes the "
                "design stage part of every run (start → design → implement → "
                "review → close); run `harness design --run-id <id>` and review "
                "again. No engine was invoked and no verdict was recorded — "
                "silence is not a pass. A design attempt that *failed* also "
                "satisfies this check, so an engine flake never wedges the run."
            ),
        )
    if event.get(DESIGN_STATUS_KEY) != "ok":
        return DesignGate(context_reason="design_failed")
    if supplied_design is None:
        return DesignGate(context_reason="not_supplied")
    if supplied_design == "":
        return DesignGate(
            context_reason="unreadable",
            warning=(
                "the file passed to --design-file could not be read (it does "
                "not exist, or is not accessible from this workspace). "
                "Reviewing against the ticket alone rather than against an "
                "unverified design — pass the `design_markdown` from this "
                "run's `harness design` output, staged inside the repo tree."
            ),
        )
    recorded_hash = event.get(DESIGN_HASH_KEY)
    if not recorded_hash or design_content_hash(supplied_design) != recorded_hash:
        return DesignGate(
            context_reason="hash_mismatch",
            warning=(
                "the design supplied with --design-file is not the one this run "
                "recorded: its content hash does not match the design event's "
                "design_hash. Reviewing against the ticket alone rather than "
                "against an unverified design — pass the `design_markdown` "
                "from this run's `harness design` output, or re-run "
                "`harness design`."
            ),
        )
    return DesignGate(design_markdown=supplied_design)


# ---------------------------------------------------------------------------
# SUBMIT-line scanner
# ---------------------------------------------------------------------------


class _Parsed(BaseModel):
    """Internal parse result of the SUBMIT line.

    ``submit_failure`` (#270) is ``None`` exactly when a verdict parsed, else the
    sentinel naming which protocol failure occurred — so the verb branches on
    structure, not on string-matching ``issues[0]``, and a reviewer whose genuine
    finding is worded like a sentinel stays a ``fail``.
    """

    verdict: Verdict
    issues: list[str]
    commit_message: str | None = None
    deferred_brief: str | None = None
    submit_failure: str | None = None


def scan_submit_line(stdout: str) -> _Parsed:
    """Scan codex stdout for the first valid ``SUBMIT: <json>`` line.

    A line is valid when it starts with ``SUBMIT:`` (after stripping), the JSON
    after the prefix parses to an object, and ``verdict`` is one of
    ``pass``/``fail``/``defer``.  Anything else yields a ``fail`` carrying a
    sentinel issue **and** ``submit_failure`` set to that sentinel, which is how
    the verb tells "produced no verdict" from "rejected the diff" (#270).

    Which sentinel: :data:`MALFORMED_SUBMIT_SENTINEL` when a ``SUBMIT:`` line
    was seen but none parsed, else :data:`NO_SUBMIT_SENTINEL`. (``design``
    classified this failure first and this parser mirrored it; since #294 gave
    ``design`` a file as its output channel, this is the only ``SUBMIT`` parser
    left and there is nothing left to mirror.)  Scanning does not stop at the first
    bad line — a stray ``SUBMIT:`` in the engine's reasoning must not mask the
    real submission at the end — so malformed is reported only when no valid line
    was found anywhere.
    """
    saw_submit_line = False
    for line in stdout.splitlines():
        stripped = line.strip()
        if not stripped.startswith("SUBMIT:"):
            continue
        saw_submit_line = True
        json_part = stripped[len("SUBMIT:"):].strip()
        try:
            payload = json.loads(json_part)
        except json.JSONDecodeError:
            continue
        if not isinstance(payload, dict):
            continue
        verdict = payload.get("verdict")
        if verdict not in _VALID_VERDICTS:
            continue
        raw_issues = payload.get("issues", [])
        issues = [str(i) for i in raw_issues] if isinstance(raw_issues, list) else []
        commit_message = payload.get("commit_message")
        deferred_brief = payload.get("deferred_brief")
        return _Parsed(
            verdict=verdict,
            issues=issues,
            commit_message=commit_message if isinstance(commit_message, str) else None,
            deferred_brief=deferred_brief if isinstance(deferred_brief, str) else None,
        )

    # No parseable SUBMIT line — report which failure it was, on both the legacy
    # ``issues`` shape and the ``submit_failure`` discriminator the verb reads.
    sentinel = MALFORMED_SUBMIT_SENTINEL if saw_submit_line else NO_SUBMIT_SENTINEL
    return _Parsed(verdict="fail", issues=[sentinel], submit_failure=sentinel)


# ---------------------------------------------------------------------------
# Engine command builder — the per-engine read-only CLI invocation.
# ---------------------------------------------------------------------------


def _build_cmd(engine: Engine, *, model: str | None = None) -> list[str]:
    """Build the review invocation for ``engine`` — a CLI subprocess (CAL-701).

    Both engines are headless CLIs fed the review prompt on **stdin** and scanned
    for a single ``SUBMIT: <json>`` line; neither uses the Agent SDK.  Both run
    **read-only**: the diff under review and the ticket are untrusted prompt
    content, so a read-only posture stops prompt-injection from mutating the host.

    * ``claude`` — ``claude -p`` headless in **plan** permission mode (read-only:
      it may read files / run read-only git, but carries no edit/write/bypass
      capability). ``model``, when given, is appended as ``--model <alias>``
      (#321): the repo's configured ``loop.review_model``, or an explicit
      ``--model`` override.
    * ``codex`` — ``codex exec`` under the ``--sandbox read-only`` sandbox
      (matching the published ``commands/build.md`` Codex-engine guidance), reading
      the prompt from ``-`` (stdin).  This replaces the earlier
      ``--dangerously-bypass-approvals-and-sandbox`` full-access invocation.
      ``model`` is ignored here — the alias is a claude-only control signal;
      the codex command is unaffected by it.
    """
    if engine == "claude":
        cmd = ["claude", "-p", "--permission-mode", "plan"]
        if model is not None:
            cmd += ["--model", model]
        return cmd
    return [
        "codex",
        "exec",
        "--sandbox",
        "read-only",
        "--ephemeral",
        "-",
    ]


# ---------------------------------------------------------------------------
# Codex usage-limit detection (CAL-702)
# ---------------------------------------------------------------------------

# The stable phrase ``codex exec`` prints to **stderr** when the tier is
# exhausted, captured empirically (CAL-702, 2026-06-15). The full real line was:
#
#   ERROR: You've hit your usage limit. Upgrade to Pro (https://chatgpt.com/
#   explore/pro), visit https://chatgpt.com/codex/settings/usage to purchase
#   more credits or try again at Jun 18th, 2026 8:18 PM.
#
# The URLs and the reset date vary run-to-run; the lowercased phrase below is the
# invariant core. On a usage limit stdout is empty and the process exits 1.
_CODEX_USAGE_LIMIT_MARKER = "you've hit your usage limit"


def is_codex_usage_limit(stderr: str, returncode: int) -> bool:
    """True iff a Codex run failed *specifically* because the tier is exhausted.

    Matches narrowly — the stable usage-limit phrase (case-insensitive) on a
    non-zero exit — so an ordinary Codex failure does NOT trigger fallback.
    Errors are never swallowed: a real review failure stays a visible ``fail``;
    only a verified quota wall degrades gracefully to the Claude engine.
    """
    if returncode == 0:
        return False
    return _CODEX_USAGE_LIMIT_MARKER in stderr.lower()


# ---------------------------------------------------------------------------
# Review-engine sandbox/init-failure detection (CAL-866)
# ---------------------------------------------------------------------------

# The stable phrase **bwrap** prints to stderr when it cannot create a user
# namespace — e.g. ``codex exec --sandbox read-only`` running inside a
# non-privileged Docker container whose seccomp profile blocks ``CLONE_NEWUSER``.
# The real captured line was:
#
#   bwrap: No permissions to create a new namespace
#
# This is an *environment* failure: the engine never got far enough to review
# anything.  Lowercased invariant core below; the ``bwrap:`` prefix is dropped so
# the match survives a differently-prefixed wrapper, while staying specific
# enough that an ordinary failure mentioning "namespace" does not match.
_SANDBOX_INIT_MARKER = "no permissions to create a new namespace"


def is_sandbox_init_failure(stderr: str, returncode: int) -> bool:
    """True iff a review engine failed because its sandbox could not initialize.

    Mirrors :func:`is_codex_usage_limit`: a narrow stderr match (the stable
    bwrap namespace phrase, case-insensitive) on a non-zero exit.  Such a failure
    is *infra*, not a code-review verdict — the engine never reviewed the diff —
    so the verb surfaces it distinctly (a dedicated exit + ``reason``) instead of
    letting it fall through to a recorded ``fail``.  The narrowness keeps an
    ordinary review failure a visible ``fail``: a clean exit, or a failure
    without the marker, returns ``False``.
    """
    if returncode == 0:
        return False
    return _SANDBOX_INIT_MARKER in stderr.lower()


def is_sandbox_blocked_defer(verdict: str, issues: list[str], engine: Engine) -> bool:
    """True iff a Codex ``defer`` is really a sandbox-blocked non-review (CAL-924).

    :func:`is_sandbox_init_failure` catches the case where ``codex exec`` itself
    exits non-zero with the bwrap marker on **stderr**.  It MISSES the subtler
    case seen in the CAL-906 dogfood: ``codex exec`` exits **0**, but every
    read-only command it shells out to inspect the diff is killed by bwrap, so
    Codex reviews nothing yet emits a well-formed
    ``SUBMIT: {"verdict": "defer", ...}`` whose reasoning is "I could not run any
    command (bwrap: no permissions to create a new namespace)".  That reads as a
    normal, shippable ``defer`` though no review happened.

    This detector reads the OTHER channel: the same bwrap marker
    (:data:`_SANDBOX_INIT_MARKER`, case-insensitive) inside the reviewer's own
    reasoning — the parsed ``issues``.  It is deliberately narrow:

    * only a ``defer`` — a blocked review cannot ``pass`` or ``fail`` without
      inspecting the diff, so pass/fail are left untouched;
    * only the ``codex`` engine — ``claude`` runs in plan mode, never bwrap, so a
      Claude ``defer`` that merely quotes the phrase is never swallowed.

    A genuine, well-founded defer (a real out-of-scope finding, no marker) stays
    a recorded ``defer``.  (Honest limit: a codex review that genuinely inspects
    the diff yet quotes the exact bwrap phrase in its finding would be caught —
    an acceptably rare shape, weighed against a review that never ran silently
    shipping.)
    """
    if engine != "codex" or verdict != "defer":
        return False
    return _SANDBOX_INIT_MARKER in " ".join(issues).lower()
