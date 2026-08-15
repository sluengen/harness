"""#327 — the universal lifecycle is tracker-neutral, dispatching on ``tracker:``.

*Source:* SYSTEM-1 in ``assessments/2026-08-04-system.md``. The repo declares
``tracker: github``, yet the universal process, the lifecycle skill, ``/start``,
``/build``, ``/ship``, ``/propose`` and ``/assess`` still *required* Linear —
naming "the Linear issue", demanding ``LINEAR_API_KEY``, and (in ``/assess``)
branching on the **retired** ``layers.linear`` switch. ``registry.yaml`` also
seeded ``default_layers: { linear: true, ... }``, a layer the current context
template no longer has. A GitHub-backed consumer was therefore handed mutually
inconsistent execution instructions.

The fix is one switch and one protocol: ``CONTEXT.md`` ``tracker:`` is the only
guidance-level switch, the new ``tracker`` skill holds the backend-neutral
protocol, and the provider recipes stay backend-specific (``linear`` and the new
``github-issues``).

**Derived, not hand-listed.** The neutral surface is derived from the files
``registry.yaml`` actually distributes — the scope rule
``test_distributed_prose_no_repo_ids`` uses — minus a documented allowlist. The
ticket's own ``Where:`` named seven files; deriving the set is what makes the
guard cover the ones nobody enumerated. Every derived set carries a
**non-vacuity floor**, because an empty subject set passes every ban silently.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
REGISTRY = REPO_ROOT / "registry.yaml"
TRACKER_SKILL = REPO_ROOT / "skills" / "tracker" / "SKILL.md"
GITHUB_SKILL = REPO_ROOT / "skills" / "github-issues" / "SKILL.md"
LINEAR_SKILL = REPO_ROOT / "skills" / "linear" / "SKILL.md"
ASSESS = REPO_ROOT / "commands" / "assess.md"
FEATURE_TEMPLATE = REPO_ROOT / "templates" / "feature.md"
FEATURES_DIR = REPO_ROOT / "specs" / "features"

#: The five universal lifecycle commands the finding names. These are the
#: commands a consumer runs on every ticket, so a Linear-only step in any of
#: them is what makes the guidance unusable on a GitHub board.
LIFECYCLE_COMMANDS = ("start", "build", "ship", "propose", "assess")

#: Files exempt from the neutral-surface bans, each for a stated reason. This
#: is a *provider and repo-owned* list, not a known-gap list: these files are
#: correct as they are.
BAN_ALLOWLIST: dict[str, str] = {
    "skills/linear/SKILL.md": "the Linear provider recipe home — its whole job is Linear",
    "skills/github-issues/SKILL.md": "the GitHub provider recipe home",
    "skills/tracker/SKILL.md": "the protocol; it names both backends to dispatch between them",
    "commands/promote.md": "promotion escalation is Linear-coupled in code (#328), not prose",
    "templates/CONTEXT.template.md": "carries the backend-conditional env/tools keys themselves",
}


def _registered_surface() -> list[Path]:
    """Every prose file ``registry.yaml`` distributes, as repo-relative paths.

    The same scope rule ``test_distributed_prose_no_repo_ids`` applies: what the
    registry lists under ``files:`` is what a consumer actually receives.
    """
    entries = re.findall(r"^\s{2}([\w./-]+\.(?:md|json)):\s*\{", REGISTRY.read_text(), re.M)
    return [Path(e) for e in entries if e.endswith(".md")]


def test_every_allowlisted_file_is_still_registered() -> None:
    """The exemption list names files that exist and are actually distributed.

    An allowlist entry for a file the registry no longer carries is a silent
    dead key: it exempts nothing today, so nothing fails, and it sits there as a
    standing invitation to re-create the path it names and inherit the
    exemption. ``commands/harness.md`` was exactly that after #435 retired the
    command — the entry outlived its subject, and no assertion noticed.

    Checked against the registered surface rather than the filesystem, because
    exemption from a *distributed*-surface ban is only meaningful for a file the
    registry distributes.
    """
    registered = {p.as_posix() for p in _registered_surface()}
    stale = sorted(rel for rel in BAN_ALLOWLIST if rel not in registered)
    assert not stale, (
        f"BAN_ALLOWLIST exempts {stale}, which registry.yaml no longer "
        f"distributes. Drop the entry with the file — an exemption whose "
        f"subject is gone is a hole waiting for a path of that name to return."
    )


def _neutral_surface() -> list[Path]:
    """The registered surface minus the documented provider/repo-owned files."""
    return [p for p in _registered_surface() if p.as_posix() not in BAN_ALLOWLIST]


def _read(rel: Path) -> str:
    return (REPO_ROOT / rel).read_text()


# --- Floors: an empty subject set passes every ban below silently -------------


def test_the_registered_surface_is_non_empty() -> None:
    """FLOOR. If the registry parse breaks, every ban below goes vacuously green."""
    surface = _registered_surface()
    assert len(surface) >= 25, (
        f"only {len(surface)} registered prose files parsed out of registry.yaml — "
        "the bans below derive their subjects from this set, so a broken parse "
        "makes them all pass on an empty set (#327)."
    )


def test_the_neutral_surface_is_non_empty() -> None:
    """FLOOR. The allowlist must not swallow the whole surface."""
    neutral = _neutral_surface()
    assert len(neutral) >= 20, (
        f"only {len(neutral)} files remain after the allowlist — the neutral "
        "surface must be most of the distributed tree, not a rump (#327)."
    )


def test_the_lifecycle_commands_all_resolve() -> None:
    """FLOOR. The five named commands must exist to be checked at all."""
    for name in LIFECYCLE_COMMANDS:
        assert (REPO_ROOT / "commands" / f"{name}.md").exists(), (
            f"commands/{name}.md is missing — the lifecycle guards below would "
            "silently check nothing (#327)."
        )


def test_the_dispatch_rule_has_subjects() -> None:
    """FLOOR. The dispatch rule is vacuous unless files actually name a provider.

    A file with no provider reference passes the dispatch rule trivially, and
    correctly. This floor proves the rule is still being *applied* to real
    files rather than to none.
    """
    subjects = [p for p in _neutral_surface() if _PROVIDER_REF.search(_read(p))]
    assert len(subjects) >= 5, (
        f"only {len(subjects)} neutral-surface files reference a provider skill — "
        "the dispatch rule needs subjects to be a real constraint (#327)."
    )


# --- AC-1: the retired layer switch is gone from the distributed tree ---------

#: The seed the finding names, plus the prose form of the retired switch.
_RETIRED_LAYER = re.compile(r"layers\.linear|linear:\s*(?:true|false)")


def test_registry_seeds_no_linear_layer() -> None:
    """``default_layers`` no longer seeds the retired ``linear`` layer (#327)."""
    block = re.search(r"default_layers:\s*\{([^}]*)\}", REGISTRY.read_text())
    assert block, "registry.yaml must still declare profiles.harness.default_layers."
    assert "linear" not in block.group(1), (
        f"default_layers still seeds a linear layer ({block.group(1).strip()!r}) — "
        "the current context template has no such layer, so a new repo would be "
        "seeded with a switch nothing reads (#327 SYSTEM-1)."
    )


def test_no_retired_layer_switch_on_the_neutral_surface() -> None:
    """No distributed guidance file branches on the retired ``layers.linear``.

    The ban is on a *guidance* file telling an agent to read the retired switch.
    The engine that carried a back-compat fallback for a consumer whose
    ``CONTEXT.md`` predates ``tracker:`` is deleted (#435), so guidance is now
    the only place the switch could be read at all.
    """
    offenders = {
        p.as_posix(): _RETIRED_LAYER.search(_read(p)).group(0)  # type: ignore[union-attr]
        for p in _neutral_surface()
        if _RETIRED_LAYER.search(_read(p))
    }
    assert not offenders, (
        f"guidance file(s) still branch on the retired linear layer: {offenders}. "
        "`tracker:` is the only guidance-level switch (#327)."
    )


# --- AC-2: nothing on the neutral surface *requires* Linear -------------------

#: Tokens that assert Linear is *the* tracker rather than one backend.
BAN_TOKENS: tuple[str, ...] = ("Linear issue", "LINEAR_API_KEY", "Linear issues")


def test_ban_tokens_are_declared() -> None:
    """FLOOR. An empty token list bans nothing."""
    assert len(BAN_TOKENS) >= 3, "the Linear-requires bans must be declared (#327)."


def _unqualified_linear_lines(text: str) -> list[str]:
    """Lines naming a Linear-only artifact with **no backend qualifier on them**.

    The unit is the *line*, not the file. A whole-file containment test cannot
    tell ``Requires `LINEAR_API_KEY` in the environment`` (a flat requirement)
    from ``for a `tracker: linear` repo that is `LINEAR_API_KEY``` (the correct
    dispatch) — and ``BOOTSTRAP.md`` legitimately carries the latter. Banning
    the token file-wide would force the fix back out of the file.
    """
    return [
        line.strip()
        for line in text.splitlines()
        if any(tok in line for tok in BAN_TOKENS) and not _DISPATCH.search(line)
    ]


def test_no_neutral_file_requires_linear() -> None:
    """The neutral surface names no Linear-only artifact as an unqualified step."""
    offenders = {
        p.as_posix(): _unqualified_linear_lines(_read(p))
        for p in _neutral_surface()
        if _unqualified_linear_lines(_read(p))
    }
    counts = {k: len(v) for k, v in offenders.items()}
    first = {k: v[0][:90] for k, v in offenders.items()}
    assert not offenders, (
        f"file(s) still require Linear specifically: {counts}. "
        f"First offending line per file: {first}. "
        "A GitHub-backed consumer receives these same files, so a Linear-only "
        "step is a mutually inconsistent execution instruction (#327 SYSTEM-1)."
    )


def test_the_ban_can_fail() -> None:
    """POSITIVE CONTROL. The ban matches the real pre-#327 sentences.

    Built from the actual text that shipped before this change, so a predicate
    that stopped matching anything would be caught here rather than reading as
    a clean surface.
    """
    pre_327 = [
        "1. The Linear issue is the front door. Open it, move it to In Progress.",
        "Requires `LINEAR_API_KEY` in the environment.",
        "- Create a Linear issue per item in the breakdown (`linear`).",
    ]
    for sentence in pre_327:
        assert _unqualified_linear_lines(sentence), (
            f"the ban no longer matches the real pre-#327 sentence {sentence!r} — "
            "it would pass a surface that never changed (#327)."
        )


def test_the_ban_spares_conditional_prose() -> None:
    """NEGATIVE CONTROL. Backend-conditional prose is the *fix*, not the defect.

    The whole point is that naming Linear as one branch of a dispatch is
    correct. A ban that flagged these would force the fix out of the files.
    """
    correct = [
        "- **`tracker: linear`** — file through the `linear` skill's `issueCreate` recipe.",
        "Read `CONTEXT.md`'s `tracker:` field and use the matching provider recipe.",
        "`linear` -> the `linear` skill, `github` -> the `github-issues` skill.",
        # The real BOOTSTRAP.md sentence: a ban on the bare token flags this.
        "for a `tracker: linear` repo that is `LINEAR_API_KEY` -> `env.linear_token`",
    ]
    for sentence in correct:
        assert not _unqualified_linear_lines(sentence), (
            f"the ban flags correct backend-conditional prose {sentence!r} — it "
            "would forbid the dispatch this ticket exists to introduce (#327)."
        )


# --- AC-3: a file naming a provider must dispatch on the switch ---------------

#: A reference to either provider recipe skill.
_PROVIDER_REF = re.compile(r"`linear` skill|`github-issues` skill")
#: Reading the switch — the dispatch that makes a provider reference legitimate.
_DISPATCH = re.compile(r"`tracker:`|`tracker` skill|tracker:\s*(?:linear|github|none)")


def test_every_provider_reference_dispatches_on_the_switch() -> None:
    """A file may name a provider recipe only if it also reads ``tracker:``.

    This is the finding's core: the defect was not *mentioning* Linear, it was
    naming it with no switch to branch on, so a GitHub consumer had no path.
    """
    offenders = [
        p.as_posix()
        for p in _neutral_surface()
        if _PROVIDER_REF.search(_read(p)) and not _DISPATCH.search(_read(p))
    ]
    assert not offenders, (
        f"file(s) name a provider skill without dispatching on `tracker:`: "
        f"{offenders}. Name the switch and both branches, the way "
        "`commands/bug.md` does (#327)."
    )


def test_every_lifecycle_command_dispatches() -> None:
    """Each of the five lifecycle commands routes through the tracker protocol."""
    for name in LIFECYCLE_COMMANDS:
        text = (REPO_ROOT / "commands" / f"{name}.md").read_text()
        assert _DISPATCH.search(text), (
            f"commands/{name}.md must read `CONTEXT.md`'s `tracker:` field — it "
            "is run on every ticket, so a Linear-only step makes the whole "
            "lifecycle unusable on another backend (#327)."
        )
        assert "`tracker` skill" in text, (
            f"commands/{name}.md must route tracker operations through the "
            "`tracker` skill rather than re-encoding a provider's API (#327)."
        )


# --- AC-4: the protocol/provider split is MECE -------------------------------


def test_the_tracker_skill_exists_and_is_registered() -> None:
    assert TRACKER_SKILL.exists(), "skills/tracker/SKILL.md must exist (#327)."
    header = re.search(r"guidance:tracker@([\d.]+)", TRACKER_SKILL.read_text())
    assert header, "skills/tracker/SKILL.md must carry a `guidance:tracker@x.y.z` header."
    entry = re.search(
        r"skills/tracker/SKILL\.md:\s*\{[^}]*id:\s*tracker[^}]*\}", REGISTRY.read_text()
    )
    assert entry, "registry.yaml files: must list skills/tracker/SKILL.md (#327)."
    assert "harness" in entry.group(0), "the tracker skill must be in the `harness` profile."


def test_the_github_issues_skill_exists_and_is_registered() -> None:
    assert GITHUB_SKILL.exists(), "skills/github-issues/SKILL.md must exist (#327)."
    header = re.search(r"guidance:github-issues@([\d.]+)", GITHUB_SKILL.read_text())
    assert header, "skills/github-issues/SKILL.md must carry a version header."
    entry = re.search(
        r"skills/github-issues/SKILL\.md:\s*\{[^}]*id:\s*github-issues[^}]*\}",
        REGISTRY.read_text(),
    )
    assert entry, "registry.yaml files: must list skills/github-issues/SKILL.md (#327)."
    assert "harness" in entry.group(0), "the github-issues skill must be in `harness`."


def _embeds_provider_call(block: str) -> bool:
    """Does this code block carry a runnable provider API call, either backend?

    The **single** detector. The ban, the exemption check and the positive
    control all route through it — a control that re-implements the predicate
    proves nothing about the predicate, and a Linear-only degradation would
    survive undetected (which is exactly how the GitHub gap was left open).
    """
    return "api.linear.app" in block or bool(re.search(r"\bgh (issue|project) ", block))


def _fenced_blocks(text: str) -> list[str]:
    """The fenced code blocks in a markdown file — where a *call* actually lives.

    The unit is the fence, not the file. A protocol skill must be able to *name*
    ``api.linear.app`` in the sentence forbidding inline embeds; what it must not
    do is carry a runnable call. A whole-file containment test cannot tell those
    apart and would forbid the rule from stating itself.
    """
    return re.findall(r"```[^\n]*\n(.*?)```", text, re.S)


def test_the_tracker_skill_holds_no_provider_calls() -> None:
    """MECE. The protocol states policy; the provider skills hold the API calls."""
    blocks = _fenced_blocks(TRACKER_SKILL.read_text())
    offenders = [b.strip()[:80] for b in blocks if _embeds_provider_call(b)]
    assert not offenders, (
        f"skills/tracker/SKILL.md embeds provider call(s) in a code fence: "
        f"{offenders}. Recipes live in the `linear` / `github-issues` skills, or "
        "the split is not MECE (#327)."
    )


#: Files that may embed a provider call, each for a stated reason. These are the
#: **capture** commands, not the lifecycle: they already dispatch on ``tracker:``
#: correctly, and their inline recipes are pinned by their own guards — the
#: three-step GitHub filing path in ``test_bug_command.py`` closes the
#: item-add-no-status trap (tick #90), so relocating it would drop that lesson.
EMBED_EXEMPT: dict[str, str] = {}


def test_no_lifecycle_file_embeds_a_provider_call() -> None:
    """The lifecycle surface routes through `tracker`; it embeds neither backend.

    The pre-#327 guard banned ``api.linear.app`` only, so the same duplication
    was free to reappear on the GitHub side — and the `tracker` skill states
    that a guard fails when one appears. This is that guard, covering both
    backends, which is what makes the claim true.
    """
    offenders: dict[str, list[str]] = {}
    for path in _neutral_surface():
        if path.as_posix() in EMBED_EXEMPT:
            continue
        hits = [b.strip()[:60] for b in _fenced_blocks(_read(path)) if _embeds_provider_call(b)]
        if hits:
            offenders[path.as_posix()] = hits
    assert not offenders, (
        f"lifecycle file(s) embed a provider call: {offenders}. Route the "
        "operation through the `tracker` skill instead of re-encoding a "
        "backend's API — the duplication-drift class this split closes (#327)."
    )


def test_the_embed_ban_covers_both_backends() -> None:
    """POSITIVE CONTROL. The ban catches a GitHub embed, not only a Linear one.

    Guarding only ``api.linear.app`` is exactly how the gap this closes was
    left open, so the control asserts both halves fire.
    """
    linear_embed = "```bash\ncurl https://api.linear.app/graphql\n```\n"
    github_embed = "```bash\ngh project item-add 2 --owner x\n```\n"
    for sample, label in ((linear_embed, "linear"), (github_embed, "github")):
        assert any(_embeds_provider_call(b) for b in _fenced_blocks(sample)), (
            f"the embed ban misses a real {label} provider call (#327)."
        )


def test_the_embed_exemptions_are_real_and_still_needed() -> None:
    """The exemption list must not outlive its reason, or it hides a regression.

    Each exempt file must exist *and* still actually embed a call. When one is
    cleaned up, this fails until it is removed from the list — the same
    shrinking-allowlist discipline the Linear embed guard uses.
    """
    for rel, reason in EMBED_EXEMPT.items():
        path = REPO_ROOT / rel
        assert path.exists(), f"exempt file {rel} no longer exists — drop it (#327)."
        assert reason.strip(), f"exemption for {rel} must state a reason (#327)."
        embeds = any(_embeds_provider_call(b) for b in _fenced_blocks(path.read_text()))
        assert embeds, (
            f"{rel} no longer embeds a provider call — remove it from "
            "EMBED_EXEMPT so the ban covers it (#327)."
        )


def test_the_provider_call_detector_can_fail() -> None:
    """POSITIVE CONTROL. The fence-scoped detector matches a real embed.

    Without this, a broken fence regex reports every file clean — the vacuous
    pass this repo has recorded five times.
    """
    embedded = "text\n```bash\ngh project item-edit --id X\n```\n"
    assert _fenced_blocks(embedded), "the fence parser found no block at all (#327)."
    assert any(_embeds_provider_call(b) for b in _fenced_blocks(embedded)), (
        "the detector missed a real embedded `gh` call (#327)."
    )
    prose_only = "A command that re-encodes `api.linear.app` inline fails a guard.\n"
    assert not _fenced_blocks(prose_only), (
        "a prose mention outside any fence must not read as an embedded call (#327)."
    )


def test_each_provider_skill_holds_its_own_api() -> None:
    """The recipes did not evaporate in the split — each provider keeps its API."""
    assert "api.linear.app" in LINEAR_SKILL.read_text(), (
        "skills/linear/SKILL.md must keep the Linear GraphQL recipes (#327)."
    )
    assert re.search(r"gh (issue|project) ", GITHUB_SKILL.read_text()), (
        "skills/github-issues/SKILL.md must hold the `gh` recipes (#327)."
    )


def test_the_github_skill_closes_the_item_add_no_status_trap() -> None:
    """The tick #90 trap survives the move into the provider skill.

    An item added to the board without an explicit Status is invisible to
    ``work-discovery``'s Todo-scoped read, so the three-step create/add/set
    sequence is the load-bearing part of the GitHub recipe.
    """
    text = GITHUB_SKILL.read_text()
    for fragment in ("gh issue create", "gh project item-add", "gh project item-edit"):
        assert fragment in text, (
            f"skills/github-issues/SKILL.md must document `{fragment}` — the "
            "three-step filing path closes the item-add-no-status trap (#327)."
        )
    assert "single-select-option-id" in text, (
        "the GitHub recipe must set Status explicitly after item-add (tick #90)."
    )


# --- AC-5: the /assess degrade keys off the switch ---------------------------


def test_assess_degrades_on_tracker_none() -> None:
    """``/assess``'s no-tracker degrade reads ``tracker: none``, not the layer.

    This is the single clearest instance of the retired switch surviving as an
    *execution instruction* rather than as documentation.
    """
    text = ASSESS.read_text()
    assert "tracker: none" in text, (
        "commands/assess.md must key its no-tracker degrade off `tracker: none` (#327)."
    )
    assert "layers.linear" not in text, (
        "commands/assess.md must not consult the retired `layers.linear` switch (#327)."
    )


# --- AC-6: the as-built records carry a tracker-neutral ticket key ------------


def test_feature_template_uses_a_neutral_ticket_key() -> None:
    text = FEATURE_TEMPLATE.read_text()
    assert re.search(r"^tickets:", text, re.M), (
        "templates/feature.md frontmatter must use the neutral `tickets:` key (#327)."
    )
    assert not re.search(r"^linear:", text, re.M), (
        "templates/feature.md must not carry a Linear-specific `linear:` key (#327)."
    )


def test_shipped_feature_specs_migrated_to_the_neutral_key() -> None:
    """Every as-built record uses the neutral key.

    Their values already mixed Linear ids and ``#244``-style GitHub ids, which
    is exactly why the neutral name is the correct one.

    The floor was four records until #435 retired five of the six subsystems
    they described and archived their specs under ``specs/retired/``. It is one
    now, and one is the honest number: ``specs/features/`` holds exactly the
    records of what this repo still is, and the floor exists to catch a *derived
    set that evaluated to nothing*, not to assert a population.
    """
    records = sorted(FEATURES_DIR.glob("*.md"))
    assert len(records) >= 1, (
        f"FLOOR: only {len(records)} feature specs found — the migration check "
        "would pass on an empty set (#327)."
    )
    offenders = [p.name for p in records if re.search(r"^linear:", p.read_text(), re.M)]
    assert not offenders, (
        f"feature spec(s) still carry the Linear-specific frontmatter key: "
        f"{offenders}. Use `tickets:` (#327)."
    )
