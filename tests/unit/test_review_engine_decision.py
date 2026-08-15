"""CAL-925 — record the in-container review-engine decision: Claude, not Codex.

The `harness:dev` image runs Codex via its bundled `bwrap`, but the unprivileged
container blocks `CLONE_NEWUSER`, so a real `--engine codex` review fails
per-command and yields no usable verdict (CAL-866). The decision is **option (b)**:
formally accept Claude-only reviews in-container and document `--engine codex` as
a host-only / cross-model option — rather than loosening container privileges
(bubblewrap + a new user namespace / a looser seccomp profile) on a container
that reviews untrusted diffs.

That last clause is the part measurement later falsified. ADR 0013 (2026-08-04)
found the wall is the **seccomp profile alone**: `CAP_SYS_ADMIN` is neither
sufficient nor required, so the privilege bundle ADR 0002 declined to pay is not
what the fix costs. The *status* it records is still accurate — Codex does still
degrade in-container, because the targeted profile is #314 and has not shipped —
so what #315 corrected is the reason, not the claim.

This guards the recorded decision (ADR 0002 as amended), the docs that state its
contract, and the CONTEXT decisions index — the same shape as
`test_loop_substrate_decision.py` guards ADR 0001. The final section adds the
#315 invariant: a reader who meets the host-only claim anywhere in the normative
corpus also meets ADR 0013, enforced over a *derived* claim set rather than a
list, so the next consumer is covered without registering it.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
ADR = REPO_ROOT / "specs" / "decisions" / "0002-in-container-review-engine.md"
CORRECTION = REPO_ROOT / "specs" / "decisions" / "0013-codex-engines-in-container.md"
CONTEXT = REPO_ROOT / "CONTEXT.md"
README = REPO_ROOT / "README.md"
HARNESS_CMD = REPO_ROOT / "commands" / "harness" / "run.md"
REVIEWER = REPO_ROOT / "agents" / "reviewer.md"
VERB_MODEL = REPO_ROOT / "specs" / "features" / "verb-model.md"
ARCH_PRINCIPLES = REPO_ROOT / "specs" / "architecture-principles.md"


def _read(path: Path) -> str:
    assert path.exists(), f"expected file to exist: {path.relative_to(REPO_ROOT)}"
    return path.read_text(encoding="utf-8")


def _host_only(text: str) -> bool:
    low = text.lower()
    return "host-only" in low or "host only" in low


# --- The ADR records the decision -------------------------------------------


def test_adr_present() -> None:
    """The in-container review-engine decision is recorded as an ADR."""
    assert ADR.exists(), (
        "the in-container review-engine decision must be recorded in "
        "specs/decisions/0002-in-container-review-engine.md"
    )


def test_adr_chooses_claude_in_container_codex_host_only() -> None:
    """ADR records option (b): in-container engine is Claude; Codex is host-only."""
    text = _read(ADR)
    low = text.lower()
    assert "claude" in low, "ADR must name Claude as the in-container review engine"
    assert "in-container" in low or "in container" in low, (
        "ADR must frame the decision as the in-container engine"
    )
    assert "codex" in low, "ADR must name Codex (the rejected in-container engine)"
    assert _host_only(text), (
        "ADR must document --engine codex as a host-only / cross-model option"
    )


def test_adr_records_rejected_privilege_path_and_its_cost() -> None:
    """ADR records *why* (a) was rejected: privilege loosening on an untrusted-diff
    container is too costly."""
    low = _read(ADR).lower()
    assert "bubblewrap" in low or "bwrap" in low, (
        "ADR must name the bubblewrap/bwrap sandbox path it declines to enable"
    )
    assert "seccomp" in low or "cap_sys_admin" in low or "privilege" in low, (
        "ADR must name the privilege/seccomp loosening it rejects"
    )
    assert "untrusted" in low, (
        "ADR must record the security cost — the container reviews untrusted diffs"
    )


def test_adr_cites_the_ticket() -> None:
    """The ADR traces to the deciding ticket."""
    assert "CAL-925" in _read(ADR), "ADR must cite CAL-925"


# --- The three named docs state the contract --------------------------------


def test_harness_run_states_codex_host_only() -> None:
    """The selected run workflow states the active engine location contract."""
    text = _read(HARNESS_CMD)
    assert _host_only(text) and "codex" in text.lower(), (
        "commands/harness/run.md must document --engine codex as host-only"
    )


def test_reviewer_agent_does_not_duplicate_engine_history() -> None:
    """The concise reviewer role routes method and omits workflow engine history."""
    text = _read(REVIEWER)
    low = text.lower()
    assert "review-discipline" in low
    assert "host-only" not in low and "bwrap" not in low


def test_verb_model_states_codex_host_only() -> None:
    """specs/features/verb-model.md states the in-container engine is Claude."""
    text = _read(VERB_MODEL)
    low = text.lower()
    assert _host_only(text) and "codex" in low, (
        "verb-model.md must document the in-container engine as Claude and "
        "--engine codex as host-only"
    )


# --- CONTEXT decisions index names the ADR ----------------------------------


def test_context_index_names_adr_0002() -> None:
    """The CONTEXT.md decisions index lists ADR 0002 alongside 0001."""
    text = _read(CONTEXT)
    assert "0002" in text and "specs/decisions/" in text, (
        "CONTEXT.md decisions index must name ADR 0002"
    )


# --- The verb DESCRIPTIONS in README/CONTEXT name the real default (CAL-1193) --
# CAL-1189's review found README.md and CONTEXT.md described `review` as
# "run Codex" — but the default engine is Claude (`--engine codex` is host-only,
# above). These guard the verb-description prose against re-drifting to a
# Codex-default framing that misleads a public reader about how their review runs.


def _review_verb_bullet(text: str) -> str:
    """The `- **``review``**` verb-definition bullet, or '' if absent."""
    for line in text.splitlines():
        if "**`review`**" in line:
            return line
    return ""


def test_readme_review_verb_names_claude_default() -> None:
    """README's `review` verb bullet names Claude as the default engine, not Codex."""
    bullet = _review_verb_bullet(_read(README))
    assert bullet, "README.md must describe the `review` verb in a bold bullet"
    low = bullet.lower()
    assert "run codex" not in low, (
        "README `review` bullet says 'run Codex' — the default engine is Claude "
        "(`--engine codex` is host-only, ADR 0002)"
    )
    assert "claude" in low and "default" in low, (
        "README `review` bullet must name Claude as the default review engine"
    )


def test_context_review_verb_points_to_current_engine_provenance() -> None:
    """Compact CONTEXT routes engine details to the active as-built record."""
    bullet = _review_verb_bullet(_read(CONTEXT))
    assert bullet, "CONTEXT.md must describe the `review` verb in a bold bullet"
    low = bullet.lower()
    assert "run codex" not in low, (
        "CONTEXT `review` bullet says 'run Codex' — the default engine is Claude "
        "(`--engine codex` is host-only, ADR 0002)"
    )
    assert "specs/features/verb-model.md" in bullet


# --- #315: every standing claim carries the correcting record (ADR 0013) -----
#
# ADR 0002 costed the in-container Codex fix as "`CAP_SYS_ADMIN`, `--privileged`,
# or a custom seccomp profile" and rejected that bundle as a standing security
# regression. Measurement (2026-08-04, ADR 0013) falsified the premise: the gate
# is the seccomp profile alone — `CAP_SYS_ADMIN` is neither sufficient
# (`pivot_root` still denied) nor required (`seccomp=unconfined` alone gives
# bwrap rc=0).
#
# What is corrected is the *cost*, not the *status*. Codex still degrades
# in-container today: the profile is #314 and has not landed. So this guard does
# not demand that any prose flip to "Codex works in-container" — it demands that
# a reader who meets the claim also meets its correction. That is why the guard
# keeps passing after #314 flips the prose: it requires a pointer, not a claim.
#
# The claim is also encoded in `harness/cli/doctor.py`'s remediation text. That
# is deliberately out of this corpus (markdown only) and owned by #316, which
# replaces the text with a probe and guards it behaviourally. The boundary is a
# decision, not an oversight.

#: The record that corrects ADR 0002's premise. Matched by number so both
#: "ADR 0013" and a relative link to `0013-codex-engines-in-container.md` count.
CORRECTION_ADR = "0013"
_CORRECTION_RE = re.compile(r"\b0013\b")

#: Trees that record what was believed or shipped at a moment, not what is
#: currently asserted. A proposal is the argument that *produced* the
#: correction; a changelog entry records what shipped. Neither is a standing
#: claim, so neither is corrected.
_HISTORICAL = (
    "specs/proposals",
    "specs/retired",
    "assessments",
    "changelog.d",
    "CHANGELOG.md",
    "CHANGELOG-archive",
    "tests",
)

#: A decision record amended at the top reads under that amendment throughout,
#: so the pointer need not be stapled to every paragraph of one.
_DECISIONS = "specs/decisions"
_HEADER_SCAN_LINES = 40

_FENCE_RE = re.compile(r"^\s*```")
_HEADING_RE = re.compile(r"^#{1,6} ")
#: Asserts *where* Codex can run, as opposed to merely mentioning it.
_LOCATION_RE = re.compile(r"host[-\s]only|host[-\s]side|in[-\s]container|in container")


def _rel(path: Path) -> str:
    return path.relative_to(REPO_ROOT).as_posix()


def normative_markdown() -> list[Path]:
    """Every markdown file that makes a *standing* assertion.

    Derived by walking the tree, never by listing filenames, so a consumer added
    later is covered without registering it anywhere.
    """
    out: list[Path] = []
    for path in sorted(REPO_ROOT.rglob("*.md")):
        rel = _rel(path)
        if any(part.startswith(".") for part in path.relative_to(REPO_ROOT).parts):
            continue
        if any(rel == h or rel.startswith(f"{h}/") for h in _HISTORICAL):
            continue
        out.append(path)
    return out


def claim_paragraphs(text: str) -> list[str]:
    """Blank-line-delimited paragraphs, with fenced blocks removed first.

    A sample command inside a fence (``commands/harness.md``'s
    ``--engine codex   # cross-model review — host-only``) is not a standing
    assertion; the prose it points at is, and that prose carries the pointer.
    """
    kept: list[str] = []
    in_fence = False
    for line in text.splitlines():
        if _FENCE_RE.match(line):
            in_fence = not in_fence
            continue
        if not in_fence:
            kept.append(line)
    return [p.strip() for p in "\n".join(kept).split("\n\n") if p.strip()]


def is_claim(paragraph: str) -> bool:
    """True when the paragraph asserts where Codex can and cannot run.

    A standalone heading is excluded. It labels the section that makes the
    assertion rather than making it, and the body directly under it is itself a
    site — so the reader still meets the correction, without a citation wedged
    into a title.
    """
    if _HEADING_RE.match(paragraph) and len(paragraph.splitlines()) == 1:
        return False
    low = paragraph.lower()
    return "codex" in low and bool(_LOCATION_RE.search(low))


def is_corrected(paragraph: str, header: str) -> bool:
    """True when the correcting record is reachable from where the reader stands."""
    return bool(_CORRECTION_RE.search(paragraph) or _CORRECTION_RE.search(header))


def _record_header(path: Path) -> str:
    """The header region of a decision record; '' for anything else."""
    if not _rel(path).startswith(f"{_DECISIONS}/"):
        return ""
    return "\n".join(path.read_text(encoding="utf-8").splitlines()[:_HEADER_SCAN_LINES])


def claim_sites() -> list[tuple[Path, str]]:
    """Every (file, paragraph) asserting Codex's container location."""
    sites: list[tuple[Path, str]] = []
    for path in normative_markdown():
        text = path.read_text(encoding="utf-8")
        for paragraph in claim_paragraphs(text):
            if is_claim(paragraph):
                sites.append((path, paragraph))
    return sites


def _site_id(site: tuple[Path, str]) -> str:
    path, paragraph = site
    return f"{_rel(path)}:{paragraph.splitlines()[0][:60]}"


# --- AC-1: the derived enforcement -------------------------------------------


@pytest.mark.parametrize("site", claim_sites(), ids=_site_id)
def test_every_claim_site_carries_the_correction(site: tuple[Path, str]) -> None:
    """A reader who meets the host-only claim also meets ADR 0013."""
    path, paragraph = site
    assert is_corrected(paragraph, _record_header(path)), (
        f"{_rel(path)} asserts where Codex can run without naming the record "
        f"that corrected the reason (ADR {CORRECTION_ADR}).\n\n"
        f"  {paragraph.splitlines()[0][:100]}\n\n"
        f"Name ADR {CORRECTION_ADR} in this paragraph — or, for a decision "
        f"record, in its header region (first {_HEADER_SCAN_LINES} lines). "
        "The claim itself stays: Codex really does still degrade in-container "
        "until the seccomp profile (#314) lands. What must not stand alone is "
        "ADR 0002's *reason* — a capability grant it does not in fact cost."
    )


# --- The derivation itself, so a narrowed predicate cannot report green ------


def test_claim_derivation_finds_the_known_sites() -> None:
    """The search reaches every file the correction was known to touch.

    This pins the *derivation*, not the enforcement set — enforcement stays
    whatever the search returns, so a new consumer is covered with no code
    change. What this forbids is the failure a derived guard is prone to: a
    predicate narrowed until it matches nothing and passes vacuously.
    """
    found = {_rel(path) for path, _ in claim_sites()}
    expected = {
        "CONTEXT.md",
        "README.md",
        "commands/harness/run.md",
        "specs/features/verb-model.md",
        "specs/decisions/0002-in-container-review-engine.md",
    }
    assert expected <= found, (
        "the claim-site derivation stopped reaching known consumers: "
        f"{sorted(expected - found)}. A predicate that matches less than the "
        "corpus it was written for is not a guard."
    )


def test_the_predicate_can_actually_fail() -> None:
    """The measuring half: an uncorrected claim is detected, a corrected one is not.

    Runs the real predicates over synthetic prose, so it proves the guard can
    fail without depending on any repo file staying wrong.
    """
    uncorrected = "In-container, `--engine codex` is host-only and degrades."
    assert is_claim(uncorrected)
    assert not is_corrected(uncorrected, "")

    corrected = f"{uncorrected} See ADR {CORRECTION_ADR} for why."
    assert is_claim(corrected)
    assert is_corrected(corrected, "")

    # Satisfied by a decision record's header region rather than the paragraph.
    assert is_corrected(uncorrected, f"# ADR {CORRECTION_ADR} — amended")


def test_the_predicate_discriminates_claims_from_mentions() -> None:
    """Negative control: naming Codex is not asserting where it runs.

    `commands/build.md` describes `--engine codex` as a cross-model second
    opinion — true, and no location claim. A derivation that flagged it would
    be over-broad, not thorough.
    """
    mention = (
        "**`--engine codex`** — the review runs the `codex` CLI in a read-only "
        "sandbox (a cross-model second opinion), with a documented fallback."
    )
    assert not is_claim(mention)

    # ...and a location claim that never names Codex is somebody else's concern.
    assert not is_claim("a host-only path like `/tmp` never resolves there")


def test_a_heading_is_not_a_claim_site_but_its_body_is() -> None:
    """The exclusion is narrow: only the standalone title line is spared."""
    heading = "## Review engine — Claude in-container, Codex host-only"
    assert not is_claim(heading)

    body = (
        "`harness review` selects the engine with `--engine claude|codex`. "
        "In-container the engine is Claude; `--engine codex` is host-only."
    )
    assert is_claim(body), (
        "excluding headings must not exempt the prose under them — that is "
        "where the assertion actually reaches the reader"
    )


def test_fenced_samples_are_not_claim_sites() -> None:
    """A sample command is not a standing assertion."""
    text = (
        "Real prose about the engine.\n\n"
        "```bash\n"
        "harness review --engine codex   # cross-model review — host-only\n"
        "```\n\n"
        "More prose.\n"
    )
    assert not any(is_claim(p) for p in claim_paragraphs(text))


def test_historical_records_are_out_of_corpus() -> None:
    """The argument that produced the correction is not steered by it."""
    corpus = {_rel(p) for p in normative_markdown()}
    proposal = "specs/proposals/codex-engines-and-the-container-sandbox.md"
    assert (REPO_ROOT / proposal).exists(), "expected the accepted proposal on disk"
    assert proposal not in corpus, (
        "the proposal states the claim repeatedly by design — it is the record "
        "of the argument, not a standing assertion to correct"
    )
    assert "CONTEXT.md" in corpus, "the corpus must still reach normative files"


# --- AC-2: ADR 0002 carries the measurement and resolves to ADR 0013 ---------


def test_adr_0002_carries_the_amendment_and_measurement() -> None:
    """ADR 0002 records what was measured, not just that it was."""
    text = _read(ADR)
    head = "\n".join(text.splitlines()[:_HEADER_SCAN_LINES])
    assert re.search(r">\s*\*\*Amended 2026-08-04", head), (
        "ADR 0002 must carry a dated amendment block in its header region, in "
        "the shape ADR 0007 uses for its #294 amendment"
    )
    low = text.lower()
    assert "pivot_root" in low, "the amendment must name the pivot_root denial"
    assert "seccomp=unconfined" in low, (
        "the amendment must record the config that measured bwrap rc=0"
    )
    assert "sys_admin" in low and "rc=0" in low, (
        "the amendment must show CAP_SYS_ADMIN measured insufficient against "
        "the config that worked"
    )
    assert not re.search(r"^- \*\*Status:\*\* Accepted$", text, re.M), (
        "ADR 0002's Status line must record that its premise was amended"
    )


def test_adr_0002_link_to_the_correction_resolves() -> None:
    """AC-2 says *resolvable*, so resolve it — a dead relative link passes a
    substring check and fails a reader."""
    targets = re.findall(r"\]\(([^)]*0013[^)]*)\)", _read(ADR))
    assert targets, "ADR 0002 must link to ADR 0013, not merely name it"
    for target in targets:
        resolved = (ADR.parent / target.split("#")[0]).resolve()
        assert resolved.exists(), f"ADR 0002 links to a missing file: {target}"
        assert resolved == CORRECTION.resolve()


# --- The one named consumer the derivation does not reach --------------------


def _review_engine_section() -> str:
    """Body of the '**Why Claude is the default' paragraph's principle section."""
    text = _read(ARCH_PRINCIPLES)
    marker = "### Review engine"
    start = text.index(marker)
    rest = text[start + len(marker) :]
    end = re.search(r"\n#{1,3} ", rest)
    return rest[: end.start()] if end else rest


def test_review_engine_principle_names_the_correction() -> None:
    """`specs/architecture-principles.md` asserts *availability*, not location, so
    the derived guard cannot reach it — it is corrected directly and pinned here.

    The defect is positional: the sentence offering `--engine codex` as an
    available opt-in is the misleading one, so a whole-section containment check
    would pass on the exact defect it is meant to catch.
    """
    section = _review_engine_section()
    assert CORRECTION_ADR in section, (
        "the Review engine principle must name ADR 0013 — it records the "
        "cross-model option as available without saying it is unreachable "
        "through the wrapper, which is the only path that runs"
    )
    opt_in = [s for s in section.split(".") if "opt-in" in s]
    assert opt_in, "the principle must still describe --engine codex as opt-in"
    assert any(_CORRECTION_RE.search(s) or "wrapper" in s.lower() for s in opt_in), (
        "the sentence offering --engine codex as an opt-in must itself carry "
        "the reachability qualification; a pointer elsewhere in the section "
        "does not reach the reader standing at the claim"
    )
