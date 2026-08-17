"""CAL-811 — registered universal prose carries no repo-specific ticket IDs.

The installed surface ships prose into *consuming* repos. That prose must name
no facts of the *source* repo — a ticket id like ``CAL-702`` is meaningless (and
faintly absurd) in a repo with its own tracker, and it violates the
universal/repo-specific boundary that ``guidance-coherence`` polices.

This already drifted live: ``commands/harness.md`` became a distributed surface
unit (CAL-764) while still carrying ``CAL-702`` and ``CAL-739`` in universal
prose, so the source-freshness hook warned on an otherwise normal edit of it
(``/assess system`` 2026-06-19, finding SYSTEM-1). The hook
(``hooks/guidance-freshness.js``) catches a leak only when a file *is edited*;
nothing pins the committed tree, so the next leak rides in silently until someone
happens to touch that file.

This guard turns the hook's per-edit warning into a standing check on the
committed tree. The leak definition is **not re-invented** — the
``TICKET`` regex and the ``STD`` allowlist are parsed straight out of
``hooks/guidance-freshness.js`` and reused here, so the guard can never drift
from the hook's detector semantics: a future change to the hook's allowlist
propagates automatically, and a parse failure trips :func:`test_detector_parsed_from_hook`
loudly rather than silently checking nothing.

Scope — *registered* universal prose: a git-tracked file under the universal
prose dirs (``skills/`` ``agents/`` ``commands/`` ``process/`` ``templates/`` —
the hook's ``PROSE`` set) that is a member of ``registry.yaml``'s ``files:``
block. A repo-owned file a repo keeps under those dirs but never registers is
*not* distributed guidance (the hook exempts it via its non-member early return),
so it is out of scope and may name its own repo's facts. Membership is decided by
the hook's own ``registryMember`` rule, mirrored here.

Acceptance criteria (CAL-811):

* **AC-3** — the guard scans current registered universal prose for
  ticket-ID-shaped repo facts using the ``guidance-freshness.js`` detector
  semantics. Proven by :func:`test_no_repo_ids_in_distributed_prose`, which fails
  against the original ``CAL-702`` / ``CAL-739`` leaks, anchored non-vacuous by
  :func:`test_sweep_covers_registered_prose` and the detector/membership pins.
* **AC-1/AC-2/AC-4** (no leak in ``commands/harness.md``; provenance moved to
  neutral wording; the hook no longer warns) follow from the same file being in
  scope and clean — the hook reuses this very detector, so an empty result here
  *is* a no-warn there.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from tests.unit._prose import REPO_ROOT, is_registered, registered_prose_files

_HOOK = REPO_ROOT / "hooks" / "guidance-freshness.js"
_REGISTRY = REPO_ROOT / "registry.yaml"


def _parse_literal(hook_src: str, name: str) -> tuple[str, str]:
    """Split the JS regex literal the hook binds to ``name`` into body and flags."""
    m = re.search(r"const " + name + r"\s*=\s*/(?P<body>.+?)/(?P<flags>[a-z]*);", hook_src)
    assert m, f"could not parse {name} out of guidance-freshness.js"
    return m.group("body"), m.group("flags")


def _parse_regex(hook_src: str, name: str) -> re.Pattern[str]:
    """Compile the JS regex literal the hook binds to ``name``.

    Each JS body the hook exposes for reuse (``\\b([A-Z]{2,5})-\\d+\\b``, and the
    two the ``#1234`` branch needs) is valid Python ``re`` syntax, so it is
    compiled as-is rather than transcribed — there is exactly one leak
    definition per shape, and it lives in the hook.

    Only the *body* crosses over. The flags do not, which is why
    :func:`test_hook_regexes_carry_only_the_g_flag` exists: see its docstring.
    """
    return re.compile(_parse_literal(hook_src, name)[0])


def _parse_std(hook_src: str) -> frozenset[str]:
    """Parse the hook's ``STD`` allowlist — the ``PREFIX-1234`` branch's exemptions."""
    std = re.search(r"const STD\s*=\s*new Set\(\[(?P<items>.*?)\]\)", hook_src, re.S)
    assert std, "could not parse STD out of guidance-freshness.js"
    return frozenset(re.findall(r'"([^"]+)"', std.group("items")))


_HOOK_SRC = _HOOK.read_text()
_TICKET = _parse_regex(_HOOK_SRC, "TICKET")
_STD = _parse_std(_HOOK_SRC)
#: The GitHub-shaped branch: a bare ``#1234``, swept over prose with fenced code
#: removed. Both come from the hook, for the same no-drift reason as ``TICKET``.
_HASH_TICKET = _parse_regex(_HOOK_SRC, "HASH_TICKET")
_CODE_FENCE = _parse_regex(_HOOK_SRC, "CODE_FENCE")


def _leaked_ids(text: str) -> list[str]:
    """Ticket-ID-shaped tokens that are repo facts, per the hook's detector.

    Mirrors ``leakedIds`` in the hook across both shapes. ``PREFIX-1234``: a
    match counts unless its alpha prefix (group 1) is an allow-listed
    standard/abbreviation (``RFC``, ``AC``, …), and it is swept over the whole
    file. ``#1234``: no allowlist — ``#`` prefixes nothing that is a standard's
    name — but fenced code is removed first, because ``#`` is live syntax inside
    code (a design token's hex value, a shell comment) where ``CAL-42`` is not.
    """
    prefixed = {m.group(0) for m in _TICKET.finditer(text) if m.group(1) not in _STD}
    hashed = {m.group(0) for m in _HASH_TICKET.finditer(_CODE_FENCE.sub("", text))}
    return sorted(prefixed | hashed)


def test_detector_parsed_from_hook() -> None:
    """The detector is the hook's own, and classifies leaks correctly.

    Pins the parse so the sweep is never silently neutered: the allowlist must be
    non-empty and a known standard must survive, while a real repo ticket id must
    be flagged. Anchors AC-3's "matching the detector semantics".
    """
    assert "AC" in _STD and "RFC" in _STD, "STD allowlist did not parse"
    assert _leaked_ids("the verb falls back once to Claude (CAL-702)") == ["CAL-702"]
    assert _leaked_ids("acceptance criterion AC-1 per RFC-2119") == []


def test_hash_detector_parsed_from_hook() -> None:
    """The ``#1234`` branch is the hook's own pattern, and its exclusions hold.

    Positive: a bare ``#1234`` in prose is a leak. The negatives each fail for a
    *different* reason, so no one mechanism can be removed without a red test: a
    hex colour and a heading anchor fall outside the **right** boundary, an HTML
    entity outside the **left** one, while an all-digit hex colour — which the
    shape alone *would* flag — is excluded only by the **fence strip**. The last
    two assertions are that pair: identical text, fenced and unfenced.
    """
    assert _leaked_ids("Measured in #1234: a real 1440 px capture.") == ["#1234"]
    # A single digit is a real issue id — every other positive here is 4+ digits,
    # so without this one the detector could quietly require two and stay green.
    assert _leaked_ids("closed by #7 last week") == ["#7"]
    assert _leaked_ids("the accent primitive is #2563eb throughout") == []
    assert _leaked_ids("see [step 1](#1-locate-the-source) for the fetch") == []
    assert _leaked_ids("an em dash written as &#8212; is not a ticket") == []
    assert _leaked_ids('```jsonc\n{ "value": "#123456" }\n```') == []
    assert _leaked_ids('{ "value": "#123456" }') == ["#123456"]


def test_code_fence_strip_applies_only_to_the_hash_branch() -> None:
    """Fenced code hides a ``#1234`` but never a ``PREFIX-1234``.

    The strip exists because ``#`` is code syntax; ``CAL-1109`` is a repo fact
    wherever it appears, so widening the sweep must not quietly narrow the branch
    that already worked. Inversion of the fence control above.
    """
    fenced = "```\nSee CAL-1109 for the origin, and #1234 too.\n```"
    assert _leaked_ids(fenced) == ["CAL-1109"]


def test_hook_regexes_carry_only_the_g_flag() -> None:
    """Every reused hook pattern must mean the same thing in both engines.

    :func:`_parse_regex` compiles the JS *body* and drops the flag string, so a
    flag is the one part of the definition that does not cross over. ``g`` is
    safe — it is JS bookkeeping that ``finditer``/``sub`` do unconditionally —
    but ``i``, ``m``, ``s`` and ``u`` all change what the pattern matches, and
    this side would ignore them in silence: the hook would start warning on a
    shape the standing sweep still cannot see. Fail here instead, where the
    message names the fix.
    """
    for name in ("TICKET", "HASH_TICKET", "CODE_FENCE"):
        flags = _parse_literal(_HOOK_SRC, name)[1]
        assert flags == "g", (
            f"{name} carries JS flags {flags!r}; only `g` mirrors into Python "
            "`re`. Express the flag in the pattern body instead, or teach "
            "_parse_regex to translate it — otherwise the hook and this sweep "
            "silently stop agreeing."
        )


def test_fence_strip_is_line_anchored_and_pairs_locally() -> None:
    """Only a line-initial ``` opens a fence, and a fence ends at the next one.

    Two ways the strip can swallow prose it was never meant to touch, both of
    which shorten the swept text and so report *fewer* offenders — the silent
    direction. First: prose that mentions a fence mid-sentence, which is live in
    ``templates/size-guard.md``; unanchored, it opens a fence that runs to the
    next real one. Second: a greedy body, which eats everything between a file's
    first and last fence. Each assertion carries a leak in the span at risk, so
    a strip that over-reaches loses it and the equality fails.
    """
    mentioned = (
        "the one ```python block below is the reference\n"
        "\nleak #1109 here\n\n"
        "```python\nx = 1\n```"
    )
    assert _leaked_ids(mentioned) == ["#1109"]

    between = "```\na\n```\nleak #1109 here\n```\nb\n```"
    assert _leaked_ids(between) == ["#1109"]

    # The strip still does its job on both a plain and an indented fence.
    assert _leaked_ids("```\nhex #123456\n```") == []
    assert _leaked_ids("  ```\n  hex #123456\n  ```") == []


def test_hash_exclusions_hold_over_real_registered_prose() -> None:
    """The real-input half of the two shape exclusions, over surviving subjects.

    The synthetic controls above prove the pattern; these prove the *sweep* runs
    it over files that actually carry a bare ``#`` and stays quiet. Both subjects
    survive this change — the design-token fragment keeps its hex colour and
    ``/update-guidance`` keeps its intra-document anchor — and each assertion
    names the token, so a subject that lost it fails loudly instead of going
    silently inert.

    The hex colour is asserted **twice, on purpose**: once over the whole file,
    and once over the single line carrying it. The real ``#2563eb`` sits inside
    a fenced block, so the whole-file assertion is satisfied by the fence strip
    and says nothing about the boundary — measured, dropping the letters from
    the right-hand class leaves it green. The line-scoped assertion is the one
    that exercises the boundary against real shipped text.
    """
    rels = {p.relative_to(REPO_ROOT).as_posix(): p for p in registered_prose_files()}

    tokens = rels["templates/design-system.md"].read_text()
    assert "#2563eb" in tokens, "the hex-colour subject no longer carries a colour"
    assert _leaked_ids(tokens) == []
    hex_line = next(ln for ln in tokens.splitlines() if "#2563eb" in ln)
    assert _leaked_ids(hex_line) == [], (
        "a hex colour must fall outside the right boundary, not only inside a fence"
    )

    anchors = rels["commands/update-guidance.md"].read_text()
    assert "(#1-locate-the-source-and-fetch-it)" in anchors, "the anchor subject moved"
    assert _leaked_ids(anchors) == []


def _hook_advisory(tmp_path: Path, prose_body: str) -> str:
    """Run the real hook over a fixture prose file; return its advisory text.

    The Python sweep reuses the hook's *patterns* but re-implements ``leakedIds``,
    so the widening is only half-proven until the hook itself is observed warning
    on the new shape. ``TMPDIR`` is isolated because the hook debounces its leak
    warning through a marker file for four hours.
    """
    node = shutil.which("node")
    if node is None:
        pytest.skip("node not available")

    fixture = tmp_path / "src-repo"
    (fixture / "commands").mkdir(parents=True)
    shutil.copytree(_HOOK.parent, fixture / "hooks")
    # A minimal source repo. What actually reaches the leak branch, measured
    # rather than assumed: a readable ``registry.yaml`` puts the hook in SOURCE
    # mode, the fixture's ``guidance:`` header keeps it clear of the
    # repo-owned-file early return (which needs a non-member with *no* header),
    # and the ``commands/`` prefix is what matches ``PROSE``. Registry
    # membership is *not* the gate here — de-registering this path leaves the
    # warning intact — so the entry is here to make the fixture a well-formed
    # source repo, not to satisfy the leak branch.
    (fixture / "registry.yaml").write_text(
        "files:\n  commands/sample.md: { id: sample, version: 0.1.0 }\n"
    )
    prose = fixture / "commands" / "sample.md"
    prose.write_text("<!-- guidance:sample@0.1.0 -->\n" + prose_body)

    marker_dir = tmp_path / "tmpdir"
    marker_dir.mkdir()
    proc = subprocess.run(
        [node, str(fixture / "hooks" / "guidance-freshness.js")],
        input=json.dumps(
            {"tool_name": "Write", "tool_input": {"file_path": str(prose)}}
        ),
        text=True,
        capture_output=True,
        timeout=30,
        cwd=fixture,
        env={"PATH": "/usr/bin:/bin:/usr/local/bin", "TMPDIR": str(marker_dir)},
    )
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout).get("additionalContext", "") or ""


def test_hook_itself_warns_on_the_hash_shape(tmp_path: Path) -> None:
    """The hook's own leak warning names a ``#1234``, and stays off a fenced hex.

    Binds the JS side of the widening to the Python side: the two halves share
    the patterns by parse, but each runs its own matcher, so this is what stops
    the hook from silently keeping the narrow behaviour the sweep left behind.

    Three cases, because each half of the contract needs its own killer on this
    side of the language boundary: the new shape warns, a fenced hex does not,
    and — the inversion — a fenced ``PREFIX-1234`` still does. The last is the
    JS twin of :func:`test_code_fence_strip_applies_only_to_the_hash_branch`,
    which only ever measured the Python mirror; without it the hook could take
    the fence strip onto the branch that already worked and nothing would fail.
    """
    leaked = _hook_advisory(tmp_path / "leak", "Measured in #1234: a real capture.\n")
    assert "repo-specific ID(s)" in leaked and "#1234" in leaked

    fenced = _hook_advisory(
        tmp_path / "clean", '```jsonc\n{ "value": "#123456" }\n```\n'
    )
    assert "repo-specific ID(s)" not in fenced and "#123456" not in fenced

    fenced_prefix = _hook_advisory(
        tmp_path / "prefix", "```\nSee CAL-1109 for the origin.\n```\n"
    )
    assert "repo-specific ID(s)" in fenced_prefix and "CAL-1109" in fenced_prefix


def test_registry_member_rule() -> None:
    """The membership predicate matches a registered command, not a non-entry.

    ``commands/harness.md`` was this anchor until #435 retired it; ``/routine``
    is the registered command that replaced its unattended half, so the anchor
    moves rather than being dropped. A made-up path must not register, or the
    sweep would silently widen.
    """
    registry_src = _REGISTRY.read_text()
    assert is_registered("commands/routine.md", registry_src)
    assert not is_registered("commands/does-not-exist.md", registry_src)


def test_sweep_covers_registered_prose() -> None:
    """The sweep is non-vacuous: it sees real registered prose, incl. the target.

    Guards against a collector that finds nothing (registry-path mismatch, wrong
    root), which would make the leak sweep pass without checking anything.
    """
    rels = {p.relative_to(REPO_ROOT).as_posix() for p in registered_prose_files()}
    assert "commands/routine.md" in rels
    assert any(r.startswith("skills/") for r in rels), "no registered skill prose found"


def test_no_repo_ids_in_distributed_prose() -> None:
    """No registered universal prose file carries a repo-specific ticket id (AC-3)."""
    violations: list[str] = []
    for path in registered_prose_files():
        ids = _leaked_ids(path.read_text())
        if ids:
            rel = path.relative_to(REPO_ROOT).as_posix()
            violations.append(f"{rel}: {', '.join(ids)}")

    assert not violations, (
        "registered universal prose names repo-specific ticket id(s) — universal "
        "guidance must name no repo facts; use neutral decision/proposal wording "
        "or move provenance to tests/assessments/changelog (CAL-811):\n  "
        + "\n  ".join(violations)
    )
