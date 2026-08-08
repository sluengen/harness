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

So the design's primary channel is **a file**, and there is no escaping, no
bracket depth, and no single-line constraint left to lose. Claude receives a
scoped grant to its verb-owned file; Codex stays read-only while its CLI writes
the final message to that file. ``review``'s SUBMIT contract is deliberately
untouched: it fits its payload.

Two deliberate differences from the review protocol remain. Design returns
Markdown rather than a ``SUBMIT:`` verdict, and its engine channels are not
interchangeable: Claude alone retains the nonce-marked stdout recovery detector;
Codex accepts only the CLI-owned ``--output-last-message`` file. Claude defaults
to Opus; Codex records no model when it uses its own configured default.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Literal, NamedTuple

from harness.cli.design_sections import (
    DESIGN_SECTIONS,
    carries_design_sections,
    render_section_briefs,
)

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
    "DesignEngine",
    "build_design_cmd",
    "build_design_prompt",
    "build_stdout_excerpt",
    "carries_design_sections",
    "design_content_hash",
    "normalize_design",
    "parse_design_fallback",
]

DesignEngine = Literal["claude", "codex"]

# The Claude design engine's model. Codex uses its configured default unless the
# caller explicitly supplies a model.
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

class DesignChannel(NamedTuple):
    """Where one design engine invocation puts its output.

    ``path`` is the absolute file the verb reads. Claude writes it through its
    scoped grant; for Codex, the CLI writes the model's final message there. It
    lies **outside** the run's worktree, so the stage leaves no untracked file
    behind to trip ``close``'s ``dirty_worktree`` gate.

    ``nonce`` marks Claude's stdout fallback block; Codex never consumes that
    channel. It is the allocated directory's own random suffix rather than a
    second random value, so the location and markers cannot disagree about
    which Claude invocation they belong to.

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
illustrative snippets inside the design itself.

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

{delivery}
"""

_CLAUDE_DELIVERY_TEMPLATE = """\
The one file you may write is the output file named below.

When you have finished, write the Design section — and nothing else — to this
absolute path:

{out_path}

Write nothing to stdout: the file is how the design is collected.

Only if writing that file is refused, emit the Design section on stdout instead,
between these two marker lines, each alone on its own line:

{begin_marker} {nonce}
{end_marker} {nonce}
"""

_CODEX_DELIVERY = """\
Return only the Design section Markdown as your final response. Do not wrap it
in a code fence and do not include commentary before or after it. The Codex CLI
collects that final response; do not write any file yourself.
"""


def build_design_prompt(
    ticket_title: str,
    ticket_description: str,
    *,
    channel: DesignChannel,
    engine: DesignEngine = "claude",
) -> str:
    """Build the design engine's prompt for one ticket.

    The prompt states four things the engine cannot infer: the **posture**
    (design, not implement), the **shape** of the output (the five
    :data:`DESIGN_SECTIONS`, rendered from the single list above), its **size**
    (:data:`DESIGN_TARGET_CHARS`), and the engine-specific **channel**. Claude
    writes ``channel.path`` and has a nonce-marked stdout fallback; Codex returns
    only the Markdown as its final response for the CLI to collect. The ticket
    is interpolated verbatim — it is the spec the design answers to.

    Claude's fallback exists for one failure this repo's test suite structurally
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
    section_brief = render_section_briefs()
    delivery = (
        _CLAUDE_DELIVERY_TEMPLATE.format(
            out_path=channel.path,
            begin_marker=FALLBACK_BEGIN_MARKER,
            end_marker=FALLBACK_END_MARKER,
            nonce=channel.nonce,
        )
        if engine == "claude"
        else _CODEX_DELIVERY
    )
    return _PROMPT_TEMPLATE.format(
        ticket_title=ticket_title,
        ticket_description=ticket_description,
        section_brief=section_brief,
        target_chars=DESIGN_TARGET_CHARS,
        delivery=delivery,
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
    *,
    model: str | None = DESIGN_MODEL_DEFAULT,
    channel: DesignChannel,
    engine: DesignEngine = "claude",
) -> list[str]:
    """Build a read-contained design engine invocation.

    The two engines reach the same file through different security boundaries.
    Claude replaced plan mode in #294: it refuses capabilities by default and
    receives exactly one rule-level exception to edit ``channel.path``. Codex
    runs with ``--sandbox read-only`` and receives no model-writable path; its
    CLI owns ``--output-last-message`` and writes the final response after the
    turn.

    Claude's grant is an **agent-layer control, not a filesystem boundary** —
    the mount is still read-write, and the settings configure the engine rather
    than confining it. Codex's model sandbox is a separate boundary and remains
    read-only even though the parent CLI can write its owned output file.

    For Claude, ``--add-dir`` names the output directory as an accessible working directory.
    Measured on the same run: the ``Edit`` grant alone is sufficient in claude
    2.1.220, so this is defence-in-depth against a future CLI that also enforces
    the working-directory boundary for writes — not the thing that makes the
    write work.

    The path is **verb-allocated and flagless**, which is what makes the grant
    safe to hand an engine reading untrusted ticket text: there is no input —
    no flag, no ticket field, no environment variable — that can steer it at a
    file the caller did not intend.

    Claude defaults ``model`` to :data:`DESIGN_MODEL_DEFAULT`. Codex omits the
    model flag when ``model`` is ``None``, preserving its configured default and
    avoiding invented Claude/Opus provenance.
    """
    if engine == "codex":
        cmd = [
            "codex",
            "exec",
            "--sandbox",
            "read-only",
            "--ephemeral",
            "--output-last-message",
            str(channel.path),
        ]
        if model is not None:
            cmd.extend(["--model", model])
        return [*cmd, "-"]

    cmd = [
        "claude",
        "-p",
    ]
    if model is not None:
        cmd.extend(["--model", model])
    return [
        *cmd,
        "--add-dir",
        str(channel.path.parent),
        "--settings",
        _permission_settings(channel),
    ]
