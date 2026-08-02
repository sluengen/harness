"""The design engine protocol — prompt, output channel, model default.

ADR 0007 adds a ``design`` stage to the run lifecycle (``start → design →
implement → review → (fix → review)* → close``): an engine studies the run's
worktree and ticket in a fresh, dedicated context and produces the change
spec's technical Design section, before the build session writes any code.

This module is that stage's **protocol layer**:

* the design **prompt** (:func:`build_design_prompt`) and the output channel it
  states;
* the **fallback parser** (:func:`parse_design_fallback`) and the shared
  blank-is-not-a-design rule (:func:`normalize_design`);
* the **engine invocation** (:func:`build_design_cmd`) and the model default
  (:data:`DESIGN_MODEL_DEFAULT`).

Everything here is a pure function or a data/type definition: no CLI, no
ledger, no tracker, no I/O. Allocating the channel is I/O and belongs to the
verb; this module only describes it (:class:`DesignChannel`).

**Why this is no longer ``review``'s protocol (#294).** Both engine verbs used
to share one wire format: a single final ``SUBMIT: <json>`` line. That fits
``review``, whose payload is small structured data — ``{"verdict": "pass",
"issues": []}``, a fixed shape under 100 characters. It does not fit ``design``,
whose payload is a 14–17 KB Markdown *document*: JSON-escaping it onto one
physical line leaves no structural landmark anywhere, so the model has to carry
"I still owe a ``}``" across thousands of output tokens. Measured on this
repo's own ledger before the change: ``design`` lost 12.5% of attempts to the
wire format (``malformed_submit`` 8, ``no_submit`` 2, of 80) against ``review``'s
0.24% (1 of 423) — same engine, same format, payloads three orders of magnitude
apart in size. One run lost 12m44s of Opus and a complete 31 KB design because
a single closing brace never arrived.

So the design's channel is **a file**, and there is no escaping, no bracket
depth, and no single-line constraint left to lose. ``review``'s SUBMIT contract
is deliberately untouched: it fits its payload.

Two deliberate differences from the review protocol, both from ADR 0007, are
unchanged by that:

* **Claude only.** ADR 0002 keeps the in-container engine unprivileged, where
  Codex's ``bwrap`` sandbox cannot start; design has no codex variant at all,
  so there is no ``Engine`` union and no per-engine branch to build.
* **Opus unconditionally.** The tier is a constant, not a per-ticket label.
  ``review_protocol.resolve_model_tier`` is dimension-generic and remains the
  seam a future tier label would hang off; it is deliberately not wired here.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import NamedTuple

__all__ = [
    "DESIGN_MODEL_DEFAULT",
    "DESIGN_OUT_FILENAME",
    "DESIGN_SECTIONS",
    "DESIGN_TARGET_CHARS",
    "DESIGN_TMP_PREFIX",
    "FALLBACK_BEGIN_MARKER",
    "FALLBACK_END_MARKER",
    "STDOUT_EXCERPT_MAX_CHARS",
    "DesignChannel",
    "build_design_cmd",
    "build_design_prompt",
    "build_stdout_excerpt",
    "design_content_hash",
    "normalize_design",
    "parse_design_fallback",
]

# The design engine's model. Opus for every run, per ADR 0007: the design
# stage's value is top-tier thinking in a context uncontaminated by the build
# session's orchestration state, so the tier is unconditional rather than
# label-gated. A cheaper tier stays an anticipated refinement, not a seam built
# on speculation.
DESIGN_MODEL_DEFAULT = "opus"

#: The file the engine writes its design to, inside a per-invocation directory
#: the verb allocates. The name is fixed so the prompt, the permission grant and
#: the read all name one thing.
DESIGN_OUT_FILENAME = "design.md"

#: Prefix of that directory, so a stray one left by a killed process is
#: identifiable as the design stage's.
DESIGN_TMP_PREFIX = "harness-design-"

# The length the prompt asks a design to stay under. Derived from the ledger
# rather than picked: the six most recent designs that landed measured 13,388 /
# 13,784 / 13,989 / 14,343 / 15,696 / 17,422 characters, and the run whose loss
# motivated #294 came back at 31,344 — roughly double every success, with eleven
# numbered subsections and a manual-gate checklist for a five-section block.
# 18,000 therefore sits above every observed success and well below the outlier,
# so it trims the tail without constraining a normal design.
#
# It is a **target stated to the engine**, never enforced on the result: rejecting
# or truncating an over-length design would reintroduce discard-on-violation,
# which is the exact failure class #294 removes. What makes it measurable instead
# is ``design_chars`` on the ledger event.
DESIGN_TARGET_CHARS = 18_000

# The fallback channel's markers (see ``build_design_prompt``). ``END-…``
# contains ``…`` as a substring, so the parser matches whole lines rather than
# prefixes — pinned by a test, because prefix matching would silently read every
# closing marker as an opening one.
FALLBACK_BEGIN_MARKER = "HARNESS-DESIGN"
FALLBACK_END_MARKER = "END-HARNESS-DESIGN"

# How much of the output a failed attempt quotes onto the ledger (#277).
#
# The ledger is an audit trail, not a log, and a real design runs 14–17 KB, so
# keeping the offending output whole would put a design-sized blob on every
# failed event. The **tail** is what carries the evidence now: a failure means
# neither channel delivered, and what the engine said instead of delivering is
# where it stopped talking. (#277 anchored a second window at the ``SUBMIT:``
# token to catch a payload that spanned lines — a JSON-specific failure this
# change removes by construction, along with the token to anchor on.)
STDOUT_EXCERPT_MAX_CHARS = 1_000

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


class DesignChannel(NamedTuple):
    """Where one design engine invocation puts its output.

    ``path`` is the absolute file the engine writes and the verb reads. It lies
    **outside** the run's worktree, so nothing the design stage does can leave
    an untracked file behind and trip ``close``'s ``dirty_worktree`` gate, and
    ``cwd=worktree_path`` stays what it was.

    ``nonce`` marks the stdout fallback's block. It is the allocated directory's
    own random suffix rather than a second random value: one source of
    randomness for the location and the markers means they cannot disagree about
    which invocation they belong to, and a block left over from another run
    cannot be adopted by this one.

    Both are allocated **by the verb**, never supplied by a flag, the ticket, or
    the environment — see the security note in :func:`build_design_cmd`.
    """

    path: Path
    nonce: str


# ---------------------------------------------------------------------------
# Design prompt
# ---------------------------------------------------------------------------

_PROMPT_TEMPLATE = """\
You are the architect for the ticket below. Study this worktree and produce its
technical design. You design; you do not implement — do not edit, create, or
delete any file in this worktree, and do not write code beyond short
illustrative snippets inside the design itself. The one file you may write is
the output file named below.

Ticket: {ticket_title}

{ticket_description}

Produce the change spec's Design section as Markdown, with exactly these
sections, in this order:

{section_brief}

Design to the current scope: simple, proven patterns, grounded in what this
worktree actually contains. Leave room to extend; do not design the extension.
Where you had a real choice, say which alternative you rejected and why.

Aim to keep the whole Design section under about {target_chars:,} characters.
Prefer density over completeness: a design an implementer can act on beats an
exhaustive one.

When you have finished, write the Design section — and nothing else — to this
absolute path:

{out_path}

Write nothing to stdout: the file is how the design is collected.

Only if writing that file is refused, emit the Design section on stdout instead,
between these two marker lines, each alone on its own line:

{begin_marker} {nonce}
{end_marker} {nonce}
"""


def build_design_prompt(
    ticket_title: str, ticket_description: str, *, channel: DesignChannel
) -> str:
    """Build the design engine's prompt for one ticket.

    The prompt states four things the engine cannot infer: the **posture**
    (design, not implement), the **shape** of the output (the five
    :data:`DESIGN_SECTIONS`, rendered from the single list above), its **size**
    (:data:`DESIGN_TARGET_CHARS`), and the **channel** — write the section to
    ``channel.path`` and keep stdout silent, falling back to a marked block on
    stdout only if that write is refused. The ticket is interpolated verbatim —
    it is the spec the design answers to.

    The fallback exists for one failure this repo's test suite structurally
    cannot catch: no test spawns a real ``claude``, so a permission-config
    regression — a CLI upgrade changing how rules are matched, say — would take
    the stage from working to producing nothing at all, with no failing test
    anywhere. With the fallback, that regression degrades to "the design still
    arrived, on the wrong channel", which the verb records as
    ``channel='stdout'`` and warns about. It is a detector as much as a
    fallback.

    The ticket text is untrusted input read from the tracker. What bounds the
    damage an injection attempt inside it can do is the engine's capability —
    see :func:`build_design_cmd` for what that is and what it is not.
    """
    section_brief = "\n\n".join(
        f"### {section}\n{_SECTION_BRIEFS[section]}" for section in DESIGN_SECTIONS
    )
    return _PROMPT_TEMPLATE.format(
        ticket_title=ticket_title,
        ticket_description=ticket_description,
        section_brief=section_brief,
        target_chars=DESIGN_TARGET_CHARS,
        out_path=channel.path,
        begin_marker=FALLBACK_BEGIN_MARKER,
        end_marker=FALLBACK_END_MARKER,
        nonce=channel.nonce,
    )


# ---------------------------------------------------------------------------
# Collecting the design
# ---------------------------------------------------------------------------


def normalize_design(text: str | None) -> str | None:
    """The design, or ``None`` when there is not one.

    One rule for both channels: an engine that delivered whitespace — an empty
    file, or a marked block with nothing in it — claimed success without
    designing anything, and treating that as a success would put an empty Design
    section on the ticket.
    """
    if text is None:
        return None
    stripped = text.strip()
    return stripped or None


def parse_design_fallback(stdout: str, nonce: str) -> str | None:
    """Recover a design from the stdout fallback's marked block, or ``None``.

    Scans for the **last** ``{begin} {nonce}`` line — the contract asks for one
    block at the end, so an earlier one is the engine quoting its instructions —
    and returns everything after it, up to the matching end marker or, when that
    marker never arrived, to the end of stdout.

    **That truncation-tolerance is the point.** Under the JSON contract this
    replaces, an engine that produced a whole design and then dropped its final
    character discarded the entire payload; here the same loss costs nothing.
    Nothing can be recovered from a *killed* engine this way — a timeout raises
    before any output is parsed — so tolerating a missing end marker admits an
    incomplete design only in the case where the alternative was no design.

    Markers are matched as whole stripped lines, not prefixes:
    :data:`FALLBACK_END_MARKER` contains :data:`FALLBACK_BEGIN_MARKER`, so
    prefix matching would read every closing marker as an opening one.
    """
    begin = f"{FALLBACK_BEGIN_MARKER} {nonce}"
    end = f"{FALLBACK_END_MARKER} {nonce}"
    lines = stdout.splitlines(keepends=True)
    starts = [i for i, line in enumerate(lines) if line.strip() == begin]
    if not starts:
        return None
    body = lines[starts[-1] + 1 :]
    for i, line in enumerate(body):
        if line.strip() == end:
            body = body[:i]
            break
    text = "".join(body)
    # Emptiness is decided by the shared rule, but the body is returned as the
    # engine wrote it — trimming is the caller's single normalization step, so
    # both channels reach it in the same state.
    return text if normalize_design(text) is not None else None


def build_stdout_excerpt(stdout: str) -> str | None:
    """A bounded quote of the tail of engine output, or ``None`` if it emitted none.

    Called only when neither channel delivered a design, where the useful
    evidence is what the engine said instead of delivering — which is where it
    stopped. The text is untrusted engine output; bounding it is this function's
    job, so no caller has to remember to do it.
    """
    if not stdout:
        return None
    return stdout[-STDOUT_EXCERPT_MAX_CHARS:]


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


def _permission_settings(channel: DesignChannel) -> str:
    """The inline settings object granting write capability to one path.

    Three details are load-bearing and each was established against the real
    ``claude`` binary in the ``harness:dev`` container (2026-08-02), not inferred:

    * the rule is ``Edit(...)``, **not** ``Write(...)``. A ``Write(...)`` rule is
      silently inert — the CLI matches only ``Edit`` rules against file writes,
      and says so on stderr — so granting ``Write`` would deny the design its
      channel while looking correct.
    * the path carries a **leading slash of its own**. Permission-rule paths are
      gitignore-style and read relative to the project unless prefixed ``//``, so
      ``Edit(/{absolute path})`` is what names a filesystem-absolute file.
    * ``defaultMode`` is ``manual``: under ``-p`` there is nobody to prompt, so
      anything not explicitly allowed is refused rather than asked about.

    ``Edit`` is therefore absent from ``deny`` — denying it outright would deny
    the one grant this exists to make. The three read-only ``git`` allows keep
    the history access plan mode used to give; ``Read``/``Glob``/``Grep`` need no
    rule.
    """
    return json.dumps(
        {
            "permissions": {
                "defaultMode": "manual",
                "allow": [
                    f"Edit(/{channel.path})",
                    "Bash(git log:*)",
                    "Bash(git diff:*)",
                    "Bash(git show:*)",
                ],
                "deny": ["NotebookEdit", "WebFetch", "WebSearch"],
            }
        },
        separators=(",", ":"),
    )


def build_design_cmd(
    *, model: str = DESIGN_MODEL_DEFAULT, channel: DesignChannel
) -> list[str]:
    """Build the design engine invocation — ``claude -p`` scoped to one writable file.

    **This replaced plan mode (#294), and it is the narrower of the two.** Plan
    mode is a cooperative, mode-level restriction: the container's bind mount at
    ``/workspace`` is read-write and the engine's ``cwd`` is the worktree, so
    nothing in the filesystem stopped a write — the mode did. What runs now
    refuses every capability by default and grants exactly one rule-level
    exception: edit ``channel.path``, a single absolute file outside the
    worktree. Measured in the container: the design path was written, a probe
    write into the worktree was refused, and ``git status --porcelain`` came back
    empty.

    Be precise about what that is. It is an **agent-layer control, not a
    filesystem boundary** — the mount is still read-write, and this configures
    the engine rather than confining it. The docstring this replaced claimed the
    engine "carries no edit, write, or bypass capability", which was the kind of
    overclaim #294 was filed against; the honest statement is that one path is
    writable by configuration and nothing else is.

    ``--add-dir`` names the output directory as an accessible working directory.
    Measured on the same run: the ``Edit`` grant alone is sufficient in claude
    2.1.220, so this is defence-in-depth against a future CLI that also enforces
    the working-directory boundary for writes — not the thing that makes the
    write work.

    The path is **verb-allocated and flagless**, which is what makes the grant
    safe to hand an engine reading untrusted ticket text: there is no input —
    no flag, no ticket field, no environment variable — that can steer it at a
    file the caller did not intend.

    Claude is the only engine (ADR 0002 / 0007) — there is no codex variant to
    select. ``model`` defaults to :data:`DESIGN_MODEL_DEFAULT` and is passed on
    every run; the parameter exists for a host-side override in testing, not
    for per-ticket tier resolution, which ADR 0007 leaves unbuilt.
    """
    return [
        "claude",
        "-p",
        "--model",
        model,
        "--add-dir",
        str(channel.path.parent),
        "--settings",
        _permission_settings(channel),
    ]
