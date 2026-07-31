"""CLI command-surface lock — documented invocations must match the registered set.

CAL-603 (insight CODE-2-INSIGHT). ``test_docs_consistency.py`` checks that docs
are *present*; it does not check that the command surface the docs tell an agent
to invoke matches the surface the CLI actually *registers*. That gap is what let
the engine-era ``harness run <workflow>`` surface (SPEC §11) and the live intake
breakage (CAL-601) drift undetected — docs kept naming a command the CLI no
longer has.

Three locks:

* **Registered surface** — the Typer app registers exactly the as-built verb set
  (the audited lifecycle verbs plus the read/inspection and ops commands) and none of
  the retired engine commands (``run`` / ``validate`` / ``decisions`` /
  ``decision``).
* **Documented surface == registered** — the command surface *documented* in
  SPEC §11 and the agent-facing contract ``commands/harness.md`` is derived (not
  hard-coded) and compared against the registered set, so a doc that adds, drops,
  or renames a command relative to the CLI is caught.
* **Live-doc references** — no *live* doc names a retired CLI invocation
  (``harness run`` / ``harness validate``), a retired ``run <workflow>``
  subcommand (caught even across a multiline docker invocation), or a retired
  engine artefact (``harness.engine|nodes|dispatch|workflow`` module paths,
  ``workflows/*.yaml``). "Live" deliberately excludes retained historical
  reference: in ``SPEC.md`` only the sections its status banner declares current
  (§1–2, §4, §11) are scanned, and the dated-supersede-bannered specs under
  ``specs/`` are skipped entirely. The ``/harness run <ticket>`` *slash command*
  is the current canonical entrypoint and is explicitly allowlisted — it is not
  the retired ``harness run <workflow>`` CLI invocation.

The companion check in ``test_engine_retired.py`` asserts the retired *modules*
are unimportable; this asserts the retired *command surface* is absent from the
registered CLI and the live docs, and that the documented surface tracks the
registered one.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

from tests._cliutil import registered_command_surface
from tests._gitutil import tracked_py_sources

#: Resolved, matching ``tracked_py_sources``' resolved output — the allowlist
#: below and the ``relative_to(REPO_ROOT)`` parametrize IDs both compare against
#: it, and under a symlinked checkout an unresolved prefix would not match.
REPO_ROOT = Path(__file__).resolve().parents[2]
SPEC = REPO_ROOT / "SPEC.md"
README = REPO_ROOT / "README.md"
HARNESS_CONTRACT = REPO_ROOT / "commands" / "harness.md"
CLI_SURFACE_SPEC = REPO_ROOT / "specs" / "features" / "cli-surface.md"
CONTEXT = REPO_ROOT / "CONTEXT.md"
DOCKER_README = REPO_ROOT / "docker" / "README.md"
RUN_LEDGER_SPEC = REPO_ROOT / "specs" / "features" / "run-ledger.md"


# --- Live-doc corpus ----------------------------------------------------------
# The one set of documents that describe how to use the harness *right now*, and
# the live-text selection applied to each. Defined here — above every consumer —
# deliberately: it used to live two hundred lines *below* the subset-enumeration
# guard, and that ordering is the structural reason the two guards never shared
# it. The enumeration guard grew a narrower hand-list of its own instead, and
# README sat unguarded for a full assessment cycle (#249, #252). A corpus defined
# before its first consumer is a shared concept; one defined after is an
# invitation to re-derive a narrower set.


#: Docs that describe how to *use* the harness right now. Spec design history
#: under ``specs/`` is excluded — those files carry their own supersede banners
#: (enforced by ``test_docs_consistency.py``). ``SPEC.md`` is included but only
#: its live prefix is scanned (see ``_live_text``).
def _live_docs() -> list[Path]:
    docs = [
        REPO_ROOT / "README.md",
        REPO_ROOT / "CONTEXT.md",
        REPO_ROOT / "CLAUDE.md",
        SPEC,
        REPO_ROOT / "docker" / "README.md",
        REPO_ROOT / "docker" / "entrypoint.sh",
        REPO_ROOT / "docker" / "Dockerfile",
        REPO_ROOT / "docker" / "docker-compose.yml",
    ]
    docs += sorted((REPO_ROOT / "commands").glob("*.md"))
    docs += sorted((REPO_ROOT / "skills").glob("*.md"))
    # Design specs under specs/ are scanned too — but the deliberately-retained
    # engine specs carry a dated supersede banner and are skipped (the same rule
    # `test_docs_consistency.py` enforces). Non-superseded specs (the current
    # subsystem docs and the accepted proposal) describe the live system and
    # must not reference a retired surface.
    docs += [
        s
        for s in sorted((REPO_ROOT / "specs").glob("**/*.md"))
        if not _has_supersede_banner(s)
    ]
    return [d for d in docs if d.exists()]


#: Dated supersede banner near the top of a file — ``> **Superseded 2026-06-11**``
#: — the same recognition ``test_docs_consistency.py`` uses to mark a spec as
#: retained history. Only the first lines matter (an agent reads the lede).
_SUPERSEDE_BANNER = re.compile(r"^>\s*\*\*Superseded\s+\d{4}-\d{2}-\d{2}")
_BANNER_SCAN_LINES = 12


def _has_supersede_banner(path: Path) -> bool:
    head = path.read_text().splitlines()[:_BANNER_SCAN_LINES]
    return any(_SUPERSEDE_BANNER.match(line) for line in head)


#: SPEC.md is live only in the sections its own status banner declares current:
#: §1–2 (the model), §4 (modules), and §11 (CLI). §3 and §5–§10, §12–§14 are
#: retained engine history behind the §3 banner and are not scanned. (If another
#: section is promoted to current, add it here and to the banner together.)
_SPEC_LIVE_SECTIONS = (1, 2, 4, 11)


def _spec_section_text(num: int, full: str) -> str:
    """Body of SPEC section ``## <num>. …`` up to the next ``## <n>.`` heading."""
    start = re.search(rf"^## {num}\. ", full, re.M)
    if start is None:
        return ""
    rest = full[start.end() :]
    nxt = re.search(r"^## \d+\. ", rest, re.M)
    return rest[: nxt.start()] if nxt else rest


def _spec_live_text(text: str) -> str:
    """The live sections of *text* read as SPEC content — a pure function of the
    text, so a doctored copy can be scanned through the *same* live-section
    selection the guard uses instead of a re-implementation of it (and without
    ever writing the doctored copy to disk)."""
    return "\n".join(_spec_section_text(n, text) for n in _SPEC_LIVE_SECTIONS)


def _live_text(path: Path) -> str:
    text = path.read_text()
    return _spec_live_text(text) if path == SPEC else text


# --- Registered surface -------------------------------------------------------

#: The verb + read/ops command set the CLI is expected to register, as-built
#: (``harness/cli/__init__.py``). Adding a stray command or dropping a verb
#: should fail here, not silently drift from the documented contract.
EXPECTED_SURFACE = {
    "start",
    "review",
    "close",
    "design",  # the four audited lifecycle verbs (design: #211, ADR 0007)
    "checkpoint",  # push the run branch mid-flight (CAL-738)
    "status",
    "logs",
    "events",
    "runs",  # read / inspection
    "cancel",
    "reclaim",
    "defer",  # triage: comment + label + assign operator + ledger event (CAL-1143, CAL-1167)
    "release",  # decision-sweep return write: body + label removal + unassign + ledger event (#193)
    "doctor",
    "version",
    "worktrees",
    "promote",  # the promotion lifecycle group (CAL-1113, ADR 0003)
}

#: The v1 ``harness promote`` subcommand set (ADR 0003). These are the real
#: orchestrator pause points — ``start`` opens the promotion, ``continue``
#: resumes after one bounded repair, ``status`` reads state, ``pr`` is the
#: success finalizer, ``escalate`` the non-success terminal path. There is
#: deliberately **no** ``verify`` command: gate execution lives *inside*
#: ``start`` / ``continue`` (a promotion cannot reach ``pr_ready`` without fresh
#: gate evidence), so a standalone ``verify`` would name a step that is never an
#: independent pause/resume point (CAL-1113 AC-3).
EXPECTED_PROMOTE_SUBCOMMANDS = {"start", "continue", "status", "pr", "escalate"}

#: Retired engine-era commands. None may be registered or documented as live.
RETIRED_COMMANDS = {"run", "validate", "decisions", "decision"}


def _registered_surface() -> set[str]:
    """Every command and sub-app the Typer app registers."""
    from harness.cli import app

    return registered_command_surface(app)


def test_registered_surface_is_the_as_built_verb_set() -> None:
    """The registered CLI surface is exactly the as-built verb set."""
    assert _registered_surface() == EXPECTED_SURFACE


def test_no_retired_engine_command_registered() -> None:
    """The retired engine commands are not registered."""
    assert RETIRED_COMMANDS.isdisjoint(_registered_surface())


def _promote_subcommands() -> set[str]:
    """Every subcommand the ``promote`` group registers, via the live app."""
    import typer.main

    from harness.cli import app

    cli = typer.main.get_command(app)
    promote = cli.commands["promote"]
    return set(getattr(promote, "commands", {}))


def test_promote_subcommand_surface_is_locked() -> None:
    """The ``promote`` group registers exactly the v1 subcommand set (AC-2).

    A drift — a renamed subcommand, a sixth command, or a re-introduced
    ``verify`` — fails here, so the promotion surface cannot change silently as
    its mechanics land across CAL-1114+.
    """
    assert _promote_subcommands() == EXPECTED_PROMOTE_SUBCOMMANDS


def test_promote_has_no_verify_subcommand() -> None:
    """There is no ``harness promote verify`` in v1 (ADR 0003 — gate execution
    lives inside ``start`` / ``continue``, so ``verify`` names no pause point)."""
    assert "verify" not in _promote_subcommands()


def test_cli_surface_spec_explains_no_verify_command() -> None:
    """The CLI-surface feature spec explains why v1 has no ``verify`` command (AC-3).

    A reader of the promotion surface must find the rationale in the as-built
    record, not only in the ADR: gate execution lives inside ``start`` /
    ``continue``, so a standalone ``verify`` would name no real pause point.
    """
    text = CLI_SURFACE_SPEC.read_text()
    assert "verify" in text and "promote" in text, (
        "cli-surface.md must discuss the promote surface and the verify question"
    )
    low = text.lower()
    # The rationale must tie the absence of `verify` to gate execution living
    # inside start/continue — the substance, not just the word "verify".
    assert "no separate `verify`" in text or "no `verify`" in text, (
        "cli-surface.md must state there is no separate `verify` command in v1"
    )
    assert "inside" in low and "start" in low and "continue" in low, (
        "cli-surface.md must explain that gate execution lives inside "
        "start/continue, which is why no standalone verify command exists (AC-3)"
    )


# --- CLI identity prose lock --------------------------------------------------
# CAL-634 (CODE-1 / CODE-3). The surface locks above guard command *names*; they
# never guarded the prose that describes what the tool *is*. The top-level
# ``--help`` banner (``harness/cli/__init__.py``) and the package docstring
# (``harness/__init__.py``) both still called the harness a "deterministic
# workflow execution engine/harness" — the retired engine model SPEC §1
# explicitly inverted ("a set of deterministic, audited verbs an agent calls —
# *not* a pipeline that drives agents"; the engine was deleted in CAL-574, §3
# banner). The ``--help`` banner is a public-contract surface (SPEC §1.5), so a
# user reading it was told the opposite of the current model. This locks the
# live identity prose to the verb model.

#: Retired deterministic-engine framing that must not describe the live tool.
_RETIRED_FRAMING = re.compile(r"workflow execution|\bengine\b", re.I)


def test_cli_help_banner_describes_the_verb_model() -> None:
    """The ``harness --help`` banner names the verb model, not the retired engine.

    Asserts on ``app.info.help`` — the exact source string Typer renders as the
    banner — so the check is not subject to terminal-width wrapping.
    """
    from harness.cli import app

    banner = app.info.help or ""
    assert not _RETIRED_FRAMING.search(banner), (
        f"`harness --help` banner still uses retired engine framing: {banner!r}. "
        "The engine was retired (CAL-574); describe the verb model (SPEC §1) "
        "instead — e.g. 'deterministic, audited verbs an agent calls'."
    )
    assert "verb" in banner.lower(), (
        f"`harness --help` banner should name the verb model: {banner!r}."
    )


def test_package_docstring_describes_the_verb_model() -> None:
    """The ``harness`` package docstring names the verb model, not the engine."""
    import harness

    doc = harness.__doc__ or ""
    assert not _RETIRED_FRAMING.search(doc), (
        f"`harness` package docstring still uses retired engine framing: {doc!r}. "
        "Describe the verb model (SPEC §1) — 'deterministic, audited verbs an "
        "agent calls'."
    )
    assert "verb" in doc.lower(), (
        f"`harness` package docstring should name the verb model: {doc!r}."
    )


# --- Documented surface == registered -----------------------------------------

#: A ``harness <verb>`` invocation that is **not** the ``/harness run`` slash
#: command (allowlisted via the negative lookbehind on ``/``). The ``\bharness``
#: boundary leaves ``~/bin/harness`` and prose like "the harness" alone.
_INVOCATION = re.compile(r"(?<!/)\bharness (\w+)")

#: A fenced code block's body — invocations are read from fences, not prose, so a
#: phrase like "the harness pipeline" is never mistaken for a ``pipeline`` verb.
_FENCE = re.compile(r"```[^\n]*\n(.*?)```", re.DOTALL)


def _verbs_in_fences(text: str) -> set[str]:
    return {v for block in _FENCE.findall(text) for v in _INVOCATION.findall(block)}


def _spec_command_surface_block() -> str:
    """The fenced body of SPEC §11's '### Command surface' subsection."""
    text = SPEC.read_text()
    section = text.index("## 11. CLI Design")
    header = text.index("### Command surface", section)
    open_fence = text.index("```", header)
    close_fence = text.index("```", open_fence + 3)
    return text[open_fence + 3 : close_fence]


def test_spec_command_surface_equals_registered() -> None:
    """SPEC §11's documented command surface matches the registered set exactly."""
    documented = set(_INVOCATION.findall(_spec_command_surface_block()))
    assert documented == _registered_surface()


def _spec_section_41() -> str:
    """The body of SPEC §4.1 (``harness.cli`` — the verb surface), up to §4.2."""
    text = SPEC.read_text()
    start = text.index("### 4.1 ")
    end = text.index("### 4.2 ", start)
    return text[start:end]


#: The audited lifecycle verbs are named inline in §4.1 by design (§4.2–§4.4
#: detail each), so they are excluded from the ops-enumeration invariant below.
#: ``design`` joined them in #211 (ADR 0007) — it is a run-bound, ledger-backed
#: lifecycle verb, not an ops command, so a section naming the audited set is
#: still naming the audited set and not drifting into a subset enumeration.
_AUDITED_VERBS = {"start", "design", "review", "close"}


def test_spec_41_does_not_partially_enumerate_the_command_surface() -> None:
    """SPEC §4.1 must not hand-list a *subset* of the registered ops commands.

    §11 is the single guarded source of the command surface
    (``test_spec_command_surface_equals_registered``). §4.1 once kept a *second*,
    unguarded prose list of the same set — it named ``cancel`` among the ops
    commands but omitted the registered siblings ``reclaim`` / ``checkpoint``
    (CAL-746), and drifted silently because only §11 was locked. The fix made
    §4.1 defer the exact set to §11 (CAL-747). This lock holds that: the ops
    commands §4.1 enumerates are *all* of them or *none* (a deferral) — never a
    misleading proper subset that goes stale the next time a verb is added.
    """
    registered = _registered_surface()
    named = {t for t in re.findall(r"`(\w+)`", _spec_section_41()) if t in registered}
    ops_named = named - _AUDITED_VERBS
    ops_registered = registered - _AUDITED_VERBS
    assert ops_named in (set(), ops_registered), (
        "SPEC §4.1 enumerates a proper subset of the registered ops commands: "
        f"names {sorted(ops_named)} but the registered ops set is "
        f"{sorted(ops_registered)} (missing {sorted(ops_registered - ops_named)}). "
        "Defer the exact list to §11 — the single guarded source of truth — "
        "instead of keeping a parallel hand-list that drifts (CAL-746 / CAL-747)."
    )


# --- Cross-section surface-enumeration lock (CAL-810) -------------------------
# §11 is the single guarded source of the command surface
# (``test_spec_command_surface_equals_registered``). §4.1 once kept a *second*,
# unguarded prose list and drifted (CAL-746/CAL-747); the test above locks §4.1.
# §1 principle 5 had the same drift one section over — it hand-listed the verb
# surface as ``start / review / close / status / events / cancel``, a proper
# subset that omits ``checkpoint``/``reclaim``/``logs``/``runs``/``worktrees``/…
# and goes stale the next time a verb is added (CAL-810). Rather than lock each
# section by hand, this locks *every* live SPEC section against the enumeration
# idiom itself: a ``/``-joined run of backtick command names that presents itself
# as the verb surface. Two refinements keep it precise:
#
# * The ``/`` separator (not "and"/commas) is what marks a deliberate *list*, so
#   ``the `runs` table and the `events` table`` is left alone.
# * A real verb-surface list anchors on the audited verbs — you cannot enumerate
#   "the verbs" and omit ``start``/``design``/``review``/``close``. Requiring an audited-verb
#   anchor leaves alone the ledger ``\`runs\` / \`events\``` tables pair (§4),
#   whose names merely double as commands but name no audited verb.
#
# So the lock fires on a slash-list that names an audited verb *and* an ops
# command yet is a proper subset of the registered surface — exactly the §1
# drift — and a complete list (not a subset) is left alone.
#
# The audited set alone used to be left alone too, and that exemption was sound
# while the set was frozen at three: a set that never changes cannot drift. ADR
# 0007 falsified the premise — ``design`` joined the lifecycle, #211 extended
# ``_AUDITED_VERBS`` for *anchoring* without re-deriving the exemption, and the
# guard went green over the very class it exists to catch (SPEC §11 kept a
# three-verb list until #226). So the audited set is now a *second* guarded set
# under the same rule: a list claiming it must not name a proper subset of it.
# The rule this encodes, one layer up: a guard's exemption must be re-derived
# when its premise changes — which is why neither clause hardcodes a cardinality.

#: A ``/``-joined run of two or more backtick-wrapped tokens — the verb-surface
#: enumeration idiom (`` `a` / `b` / `c` ``). Captured whole so the member tokens
#: can be read out; prose joined by "and"/commas is deliberately not matched.
_SLASH_LIST = re.compile(r"`\w+`(?:\s*/\s*`\w+`)+")


def _surface_slash_lists(text: str) -> list[set[str]]:
    """Every ``/``-joined backtick run in *text*, as the set of registered
    command names it contains (runs naming no registered command are dropped)."""
    registered = _registered_surface()
    runs: list[set[str]] = []
    for run in _SLASH_LIST.findall(text):
        names = {t for t in re.findall(r"`(\w+)`", run) if t in registered}
        if names:
            runs.append(names)
    return runs


def _is_subset_surface_enumeration(names: set[str], registered: set[str]) -> bool:
    """True when a slash-list *claims* a guarded command set yet names a proper
    subset of it. Two claims, one rule:

    * **the command surface** — the list anchors on an audited verb *and* pulls
      in an ops command (spanning both categories is how a list claims the whole
      surface), yet ``names != registered``. The §1 drift CAL-810 locks out.
    * **the audited set** — the list names *two or more* audited verbs, yet
      ``names & _AUDITED_VERBS != _AUDITED_VERBS`` (#226).

    Neither clause hardcodes a cardinality: both compare against the live set, so
    a fifth audited verb re-arms the rule with no edit here. The one literal is
    the ``>= 2`` threshold, and it states *more than one member of the audited
    set appears in the list*: a single audited verb beside a non-audited token is
    a **reference**, not an enumeration (``the gate runs inside `start` /
    `continue```), which is the exemption that survives.

    ``names ⊆ registered`` by construction in ``_surface_slash_lists`` and
    ``audited ⊆ _AUDITED_VERBS`` by construction here, so both ``!=``
    comparisons are proper-subset tests.
    """
    ops = registered - _AUDITED_VERBS
    audited = names & _AUDITED_VERBS
    claims_surface = bool(audited) and bool(names & ops)
    claims_audited_set = len(audited) >= 2
    return (claims_surface and names != registered) or (
        claims_audited_set and audited != _AUDITED_VERBS
    )


def _subset_enumeration_offenders(text: str) -> list[list[str]]:
    """Every slash-list in *text* that names a proper subset of a guarded set,
    as sorted name lists. The live guard and its regression tests share this one
    scan path — a regression test that re-implemented the scan could go green
    while the guard's own path stayed narrow."""
    registered = _registered_surface()
    return [
        sorted(names)
        for names in _surface_slash_lists(text)
        if _is_subset_surface_enumeration(names, registered)
    ]


@pytest.mark.parametrize(
    "doc", _live_docs(), ids=lambda p: str(p.relative_to(REPO_ROOT))
)
def test_no_live_doc_handlists_a_command_subset(doc: Path) -> None:
    """No live doc enumerates a *proper subset* of a guarded command set.

    AC for CAL-810: §11 is the single guarded source of the command set; any
    other live section that slash-lists the verbs (as §1 principle 5 did) drifts
    the moment a verb is added. Extended in #226 to the audited lifecycle as a
    second guarded set, once ADR 0007 made that set mutable: the *complete*
    audited set is allowed, a proper subset of it is not. Widened in #249 from
    SPEC alone to a two-doc opt-in tuple, and in #252 from that tuple to the
    whole ``_live_docs()`` corpus — the same set the retired-surface guard below
    already scanned. A doc live enough to be held to "names no retired command"
    is live enough to be held to "carries no stale command list", and the opt-in
    tuple's per-doc default-off is exactly how README sat unguarded for a full
    assessment cycle. Adding a doc under ``specs/``, ``commands/`` or ``skills/``
    now arms this guard over it with no edit here.

    A complete list and §11's fenced surface are allowed; the ledger ``runs`` /
    ``events`` tables pair names no audited verb and is allowed; a lone audited
    verb beside a non-registered token is a reference, not an enumeration, and is
    allowed. A proper subset of either guarded set is not.
    """
    offenders = _subset_enumeration_offenders(_live_text(doc))
    assert not offenders, (
        f"{doc.relative_to(REPO_ROOT)} hand-lists a proper subset of a guarded "
        f"command set: {offenders}. The guarded sets are the registered command "
        f"surface ({sorted(_registered_surface())}) and the audited lifecycle "
        f"verbs ({sorted(_AUDITED_VERBS)}); §11 is the single guarded source of "
        "the command set (`test_spec_command_surface_equals_registered`). Name "
        "the command categories and defer the exact set to §11, or name the "
        "audited lifecycle in full — do not repeat a slash-list that goes stale "
        "the next time a verb is added (CAL-810, #226, #249). If this is not a "
        "claim about a guarded set at all — event types, `promote` subcommands, "
        "a two-verb handoff — join the names with commas rather than `/`: the "
        "slash-list idiom is reserved for naming a guarded set in full (#252)."
    )


@pytest.mark.parametrize(
    "text, flagged",
    [
        # The §1 drift — a proper subset that pulls in ops commands.
        ("`start` / `review` / `close` / `status` / `events` / `cancel`", True),
        ("`start` / `status`", True),
        # The audited set minus a verb — the shape ADR 0007 made possible and
        # #211 left exempt. `design` is missing, so it is a proper subset (#226).
        ("`start` / `review` / `close`", True),
        # A non-command member does not launder the omitted verb: `implement` is
        # filtered out, leaving the same three-verb proper subset.
        ("`start` / `implement` / `review` / `close`", True),
        # The two-verb pair — documents the coarse `>= 2` threshold explicitly
        # rather than leaving it to be discovered.
        ("the `review` / `close` handoff", True),
        # Allowed — the full four-verb audited set, ADR 0007's lifecycle (#211).
        ("`start` / `design` / `review` / `close`", False),
        # Allowed — the correct lifecycle string; `implement` filters out and
        # what remains is exactly the audited set.
        ("`start` / `design` / `implement` / `review` / `close`", False),
        # Allowed — one audited verb beside a non-registered token (`continue`
        # is a `promote` subcommand, not a top-level name), so this is a
        # reference, not an enumeration. Real §11 text; the preserved exemption.
        ("the gate runs inside `start` / `continue`", False),
        # Allowed — the ledger tables pair (§4) names no audited verb, so it is
        # not read as a verb-surface enumeration even though both names double as
        # commands.
        ("the `runs` / `events` tables are the whole audit trail", False),
        # Allowed — non-command slash-lists (refusal reasons, verdicts).
        ("`no_run` / `dirty_worktree` / `no_passing_review`", False),
        ("`pass` / `fail` / `defer`", False),
        # Allowed — a lone command reference is not an enumeration.
        ("the `runs` ledger row", False),
        # Allowed — "and"/comma prose is not the slash-list idiom.
        ("the `runs` table and the `events` table", False),
    ],
)
def test_surface_slash_list_detection(text: str, flagged: bool) -> None:
    """The slash-list detector flags a proper-subset verb enumeration that
    anchors on an audited verb and pulls in an ops command, but leaves the
    audited set, the ledger tables pair, non-command lists, lone references,
    and "and"/comma prose alone."""
    registered = _registered_surface()
    hit = any(
        _is_subset_surface_enumeration(names, registered)
        for names in _surface_slash_lists(text)
    )
    assert hit is flagged


#: The exact sentence SPEC §11 carried before #226 — a three-verb slash-list that
#: omits `design`. Injected into a real SPEC copy below so the regression exercises
#: the live document and the live scan path, not a synthetic string.
_STALE_AUDITED_LIST = "The verbs (`start` / `review` / `close`) also take `--json`.\n"


def _inject_into_section(text: str, heading: str, line: str) -> str:
    """*text* with *line* inserted just after the given ``## <n>. `` heading."""
    match = re.search(rf"^{re.escape(heading)}.*$", text, re.M)
    assert match, f"SPEC has no {heading!r} heading — the injection point moved"
    return text[: match.end() + 1] + line + text[match.end() + 1 :]


def test_a_stale_audited_slash_list_in_a_live_section_is_caught() -> None:
    """A slash-list claiming the audited verbs while omitting one fails the gate.

    AC for #226. The exemption at the top of this block ("the audited set alone
    … left alone") was sound while the audited set was frozen at three: a set
    that never changes cannot drift. ADR 0007 made it mutable, and #211 extended
    ``_AUDITED_VERBS`` with ``design`` for anchoring without re-deriving the
    exemption — leaving the guard green over exactly the class it exists to
    catch. This pins the re-derivation.

    Asserting *equality* with the injected offender, not merely a non-empty
    result, is what keeps this non-vacuous: it proves the hit is the injection
    rather than a pre-existing one, and it fails loudly if the real SPEC
    regresses to a stale list of its own.
    """
    doctored = _inject_into_section(SPEC.read_text(), "## 4. ", _STALE_AUDITED_LIST)
    assert _subset_enumeration_offenders(_spec_live_text(doctored)) == [
        ["close", "review", "start"]
    ]


def test_a_stale_audited_slash_list_in_a_retained_section_is_not_scanned() -> None:
    """The same injection into retained engine history (§3) is not scanned.

    The scoping control for the test above: it proves the catch comes from the
    predicate widening rather than from the live-section selection quietly
    growing, which this ticket does not touch.
    """
    doctored = _inject_into_section(SPEC.read_text(), "## 3. ", _STALE_AUDITED_LIST)
    assert not _subset_enumeration_offenders(_spec_live_text(doctored))


#: One doc per newly-covered class, injected into below. A root doc (README), a
#: `docker/` doc, a `specs/features/` as-built record, and a `commands/` contract
#: — each a class the #252 widening brought in, and the first three each carried
#: a real offender before it.
_INJECTION_PROBES = (README, CONTEXT, DOCKER_README, CLI_SURFACE_SPEC, HARNESS_CONTRACT)


@pytest.mark.parametrize(
    "doc", _INJECTION_PROBES, ids=lambda p: str(p.relative_to(REPO_ROOT))
)
def test_a_stale_audited_slash_list_in_a_live_doc_is_caught(doc: Path) -> None:
    """The widening is non-vacuous: each newly-covered class catches a stale list.

    A parametrized all-clean assertion goes green when the corpus *shrinks* —
    narrowing deletes cases rather than failing them. So proving today's docs are
    clean proves nothing about the scan; injecting the offending idiom is what
    proves the guard actually travels each doc. #249 pinned this for README
    alone; #252 owes the same proof for every class it brought in.

    Two properties are load-bearing. The probe goes through ``_live_text(doc)``,
    the guard's *own* path, so it cannot pass while the guard's path diverges
    (identity for every doc here, section-scoped only for SPEC). And it asserts
    **equality** with the injected offender rather than a non-empty result —
    which proves both that the hit is the injection and that the doc is clean
    today; ``assert offenders`` would pass on a pre-existing offender and
    silently stop testing the injection.
    """
    doctored = _live_text(doc) + "\n" + _STALE_AUDITED_LIST
    assert _subset_enumeration_offenders(doctored) == [["close", "review", "start"]]


def test_enumeration_guard_covers_the_whole_live_doc_corpus() -> None:
    """The enumeration guard's corpus is ``_live_docs()`` — the floor, pinned.

    The failure mode this closes is the one #249 hit and #252 generalizes:
    narrowing the parametrize source deletes cases instead of failing them, so
    the suite stays green while coverage silently collapses. Reverting to the old
    ``(SPEC, README)`` opt-in would drop ~53 cases and nothing else would notice.

    Membership of representative docs is asserted rather than
    ``set(_live_docs()) == set(_live_docs())``, which is tautological once the
    decorator reads the same expression. Every doc named here actually carried an
    offender before this change, so the floor is evidence-backed.
    """
    corpus = set(_live_docs())
    for doc in _INJECTION_PROBES:
        assert doc in corpus, (
            f"{doc.relative_to(REPO_ROOT)} dropped out of the live-doc corpus — "
            "the enumeration and retired-surface guards both parametrize over "
            "`_live_docs()`, so a doc leaving it silently deletes its cases "
            "rather than failing them (#252)."
        )
    for doc in (CONTEXT, DOCKER_README, CLI_SURFACE_SPEC, RUN_LEDGER_SPEC):
        assert doc in corpus


def _real_options() -> dict[str, set[str]]:
    """Map every command (incl. ``worktrees list`` / ``worktrees cleanup``) to the
    set of ``--long`` options it actually exposes, via the live Typer/click app."""
    import click
    import typer.main

    from harness.cli import app

    cli = typer.main.get_command(app)
    sigs: dict[str, set[str]] = {}

    def longs(cmd: click.Command) -> set[str]:
        return {
            o
            for p in cmd.params
            if isinstance(p, click.Option)
            for o in p.opts
            if o.startswith("--")
        }

    for name, cmd in cli.commands.items():
        sub = getattr(cmd, "commands", None)
        if sub:
            for sn, sc in sub.items():
                sigs[f"{name} {sn}"] = longs(sc)
        else:
            sigs[name] = longs(cmd)
    return sigs


def _documented_options() -> dict[str, set[str]]:
    """Map each command documented in SPEC §11's command surface to the set of
    ``--long`` options that appear on its line."""
    sigs: dict[str, set[str]] = {}
    for line in _spec_command_surface_block().splitlines():
        m = re.match(r"harness (\w+(?: \w+)?)", line)
        if m is None:
            continue
        # Strip a trailing ``# comment`` so a ``--flag`` mentioned in prose there
        # is not counted as a documented option.
        sig = line.split("#", 1)[0]
        sigs[m.group(1)] = set(re.findall(r"--[\w-]+", sig))
    return sigs


#: Commands that register a ``--run-id`` option: the four audited verbs where
#: it overrides CWD-based run resolution, plus the three read commands where
#: it aliases the positional ``RUN_ID`` (#245). Equality (not a subset check)
#: locks both directions — a dropped alias and an unintended new one both fail.
EXPECTED_RUN_ID_COMMANDS = {
    "design", "review", "close", "checkpoint",  # verbs
    "status", "logs", "events",  # read commands
}


def test_run_id_flag_surface_is_locked() -> None:
    """Exactly the expected commands register ``--run-id`` (#245 AC-4)."""
    actual = {cmd for cmd, opts in _real_options().items() if "--run-id" in opts}
    assert actual == EXPECTED_RUN_ID_COMMANDS


def test_documented_options_exist_on_the_command() -> None:
    """Every ``--option`` SPEC §11 documents is a real option on that command.

    Locks the *signatures*, not just the command names — a doc that invents or
    misattributes a flag (e.g. ``cancel --run-id``, which does not exist) is
    caught. Documenting a subset of a command's real options is fine.
    """
    real = _real_options()
    drift = {
        cmd: sorted(opts - real.get(cmd, set()))
        for cmd, opts in _documented_options().items()
        if opts - real.get(cmd, set())
    }
    assert not drift, (
        f"SPEC §11 documents options the CLI does not expose: {drift}. "
        "Correct the signature against `harness/cli/` (Typer params)."
    )


def test_contract_documents_only_registered_verbs() -> None:
    """Every ``harness <verb>`` the agent-facing contract invokes is registered.

    ``commands/harness.md`` documents a subset (the loop verbs) — the lock is
    that it never names a verb the CLI does not register (the CAL-601 failure
    mode), not that it enumerates the whole surface.
    """
    documented = _verbs_in_fences(HARNESS_CONTRACT.read_text())
    unknown = documented - _registered_surface()
    assert not unknown, (
        f"{HARNESS_CONTRACT.relative_to(REPO_ROOT)} documents `harness <verb>` "
        f"invocation(s) the CLI does not register: {sorted(unknown)}. Either the "
        "verb was removed/renamed or the doc drifted — reconcile against "
        "`harness/cli/__init__.py`."
    )


# --- Live-doc reference lock --------------------------------------------------
# The corpus itself (``_live_docs`` and the live-text selection) lives at the top
# of this module — it is shared with the subset-enumeration guard (#252).

#: The retired deterministic workflows the engine-era CLI ran as
#: ``harness <image> run <workflow>``. Caught as a standalone ``run <workflow>``
#: token so a *multiline* docker invocation — ``harness:dev \`` then ``run
#: steward …`` on the next line — is still flagged (the ``harness run`` form
#: alone misses it).
_RETIRED_WORKFLOWS = "build-codex|build|feature|steward|bugfix|release"

#: Retired surface references that must not appear in a live doc:
#: the bare ``harness run/validate`` CLI invocation (not the ``/harness run``
#: slash command), a retired ``run <workflow>`` subcommand, a retired engine
#: module path, or a retired workflow YAML file.
_RETIRED_REFERENCE = re.compile(
    # ``harness run <anything>`` as the CLI invocation — an *arbitrary* workflow
    # name (the retired CLI accepted any), a ``<placeholder>``, or a ``--flag``.
    # The lookahead requires a real argument token after ``run`` so the English
    # noun "a harness run." (followed by punctuation) and annotations like
    # "`harness run` (legacy)" are left alone; the ``\s`` after ``run`` keeps the
    # live ``harness runs`` read command (no space before ``s``) out of scope.
    r"(?<!/)\bharness run(?=\s+[<\w-])"
    r"|(?<!/)\bharness validate\b"  # retired `harness validate`
    rf"|\brun (?:{_RETIRED_WORKFLOWS})\b"  # bare `run <workflow>` across a multiline
    #                                        docker invocation (no `harness ` on the
    #                                        same line); restricted to the known
    #                                        workflow names so `docker run` / `uv run`
    #                                        are not swept up.
    r"|\bharness\.(?:engine|nodes|dispatch|workflow)\b"  # retired engine modules
    r"|\bworkflows/[A-Za-z0-9_-]+\.yaml\b"  # retired workflow YAML file
)

@pytest.mark.parametrize(
    "doc", _live_docs(), ids=lambda p: str(p.relative_to(REPO_ROOT))
)
def test_live_docs_have_no_retired_surface_reference(doc: Path) -> None:
    """No live doc references a retired CLI invocation or engine artefact.

    The ``/harness run <ticket>`` slash command is the current canonical
    entrypoint and is allowlisted; this fires only on the bare CLI form and on
    retired engine module / workflow-YAML references.
    """
    hits = [m.group(0) for m in _RETIRED_REFERENCE.finditer(_live_text(doc))]
    assert not hits, (
        f"{doc.relative_to(REPO_ROOT)} references retired surface "
        f"{sorted(set(hits))!r}. The deterministic engine was retired (CAL-574); "
        "the CLI no longer registers `run`/`validate` and the engine modules / "
        "`workflows/*.yaml` are gone. Rewrite to the as-built verb surface "
        "(`harness start/review/close`) or, for the slash command, `/harness run`."
    )


@pytest.mark.parametrize(
    "text, flagged",
    [
        # Retired CLI invocations — flagged. The name is arbitrary: the retired
        # `run <workflow>` accepted any workflow name, not a fixed list.
        ("harness run <workflow>", True),
        ("harness run feature --linear=CAL-1", True),
        ("harness run custom-workflow --foo", True),
        ("harness run --help", True),
        ("harness validate workflow.yaml", True),
        ("    harness:dev \\\n      run steward --domain=architecture", True),
        ("import harness.engine.runner", True),
        ("see workflows/feature.yaml for the inputs block", True),
        # Live / legitimate — not flagged.
        ("/harness run CAL-42", False),  # the slash command (current entrypoint)
        ("a deterministic harness run. That role is dissolved.", False),  # noun
        ("| `pending` | `harness run` (legacy) | …", False),  # historical annotation
        ("harness runs --failed", False),  # the live `runs` read command
        ("docker run --rm harness:dev start CAL-1", False),  # plain `docker run`
        ("uv run harness start CAL-1", False),  # `uv run`, then the live verb
    ],
)
def test_retired_reference_detection(text: str, flagged: bool) -> None:
    """The detector flags retired invocations (any workflow name) without
    catching the slash command, the English noun, or live `runs`/`docker run`."""
    assert bool(_RETIRED_REFERENCE.search(text)) is flagged


# --- Python module-docstring lock (CAL-699) -----------------------------------

#: Retired CLI *command* references — the subset of ``_RETIRED_REFERENCE`` that
#: names a command the CLI no longer registers (``harness run <arg>`` /
#: ``harness validate`` / a bare ``run <workflow>``). The full doc-scan rule also
#: flags retired engine *module paths* (``harness.nodes|engine|…``) and
#: ``workflows/*.yaml``; that part is deliberately omitted here because a Python
#: module docstring legitimately *narrates provenance* — e.g. ``harness/worktree
#: .py`` documents that it was "re-homed from the retired ``harness.nodes``
#: package (CAL-574)". A live CLI command *name*, by contrast, has no business
#: appearing in a docstring as if it were current (the ``harness validate`` line
#: that survived in ``test_cli_query.py`` is exactly this drift). So source
#: docstrings are held only to the narrower CLI-name rule.
_RETIRED_CLI_REFERENCE = re.compile(
    r"(?<!/)\bharness run(?=\s+[<\w-])"  # `harness run <arg>` CLI invocation
    r"|(?<!/)\bharness validate\b"  # retired `harness validate`
    rf"|\brun (?:{_RETIRED_WORKFLOWS})\b"  # bare `run <workflow>`
)

#: Python sources whose module docstring legitimately *documents* the retired
#: CLI surface as its subject — this guard names ``harness run`` / ``harness
#: validate`` precisely to lock them out. Excluded in the same spirit as the
#: supersede-bannered specs skipped by ``_live_docs()``.
_RETIRED_CLI_DOCSTRING_ALLOWLIST = {
    REPO_ROOT / "tests" / "unit" / "test_cli_surface_locked.py",
}


def _py_sources() -> list[Path]:
    """Python files under ``harness/`` and ``tests/`` whose *module docstring*
    is held to the retired-CLI-name rule (the allowlist removed)."""
    files = tracked_py_sources("harness", "tests")
    return [p for p in files if p not in _RETIRED_CLI_DOCSTRING_ALLOWLIST]


def _module_docstring(path: Path) -> str:
    """The module-level docstring only — not the full source. Scanning only the
    docstring keeps this guard's own retired-pattern *constants* (data in the
    body) from being read as if they were prose."""
    try:
        return ast.get_docstring(ast.parse(path.read_text())) or ""
    except SyntaxError:  # pragma: no cover - all repo sources parse
        return ""


@pytest.mark.parametrize(
    "src", _py_sources(), ids=lambda p: str(p.relative_to(REPO_ROOT))
)
def test_py_docstrings_have_no_retired_cli_reference(src: Path) -> None:
    """No Python module docstring names a retired CLI command as if it were live.

    ``_live_docs()`` scans ``.md``/``.sh`` only, so a retired command name in a
    Python docstring went uncaught (CAL-699 — ``test_cli_query.py`` kept naming
    the retired ``harness validate``). This closes that gap for source docstrings
    while leaving legitimate engine-module *provenance* notes alone.
    """
    hits = [m.group(0) for m in _RETIRED_CLI_REFERENCE.finditer(_module_docstring(src))]
    assert not hits, (
        f"{src.relative_to(REPO_ROOT)} module docstring names retired CLI "
        f"surface {sorted(set(hits))!r}. `run`/`validate` were retired with the "
        "deterministic engine (CAL-574); rewrite to the as-built verbs "
        "(`harness start/review/close`) or drop the stale reference."
    )


@pytest.mark.parametrize(
    "text, flagged",
    [
        # Retired CLI command names — flagged.
        ("harness validate workflow.yaml", True),
        ("harness run feature --linear=CAL-1", True),
        ("    run steward --domain=architecture", True),
        # Legitimate in a source docstring — NOT flagged. Engine-module
        # provenance and workflow-walking history are narration, not a live
        # command name; the slash command and live `runs` stay clear too.
        ("re-homed from the retired harness.nodes package (CAL-574)", False),
        ("import harness.engine.runner", False),
        ("the YAML-walking engine (engine.runner|executor|loop|retry)", False),
        ("/harness run CAL-42", False),
        ("a deterministic harness run. That role is dissolved.", False),
        ("harness runs --failed", False),
    ],
)
def test_retired_cli_reference_detection(text: str, flagged: bool) -> None:
    """The CLI-name detector flags retired *commands* but leaves engine-module
    provenance, the slash command, the English noun, and live `runs` alone."""
    assert bool(_RETIRED_CLI_REFERENCE.search(text)) is flagged
