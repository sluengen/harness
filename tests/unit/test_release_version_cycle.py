"""The plugin's semver is raised at the *start* of a release cycle, not at the hop.

**The occurrence (#556).** Release 7.0.0 shipped on 2026-09-05 with both plugin
manifests still declaring ``6.0.1``. The cost is the consumer's update signal:
``claude plugins update harness`` compares the manifest's ``version`` and reports
"already at the latest version" over bytes that changed. The moment the bump was
owed at had no owner — the automated release hop opens a pull request whose head
is the integration branch itself and pushes nothing new, so there is no commit
slot a bump could be written in, and a bump authored onto the release branch by
hand makes ``scripts/promotion-step.sh``'s content-divergence pre-condition
non-empty from that night on. Moving the moment to *the first change to land on
the integration branch after a release* gives it an owner and gives the gate
something to check:

    A tree whose content differs from the release branch's must declare a plugin
    version strictly greater than the release branch's.

Content-first is what keeps that honest rather than merely strict. Where the index
tree **is** the release tree — the ``push: main`` CI run, or a builder who
reverted everything — the released version is the correct one and no bump is owed
(``RELEASE_TREE``); the unconditional inequality would go permanently red there.

**Admitted under ADR 0017 D5 as class (c), integrity of a shipped asset**, the
pure helpers under class (a). Both operands are machine-readable JSON. What the
correct *level* of a bump is — patch, minor, major — is a judgement about meaning,
governed by ``specs/architecture-principles.md``'s compatibility grammar and
reviewed, never measured here.

**Not asserted here, per law 1.** Equal versions across the two manifests is
``tests/unit/test_native_codex_plugin.py``'s; agreement with the two
``spine:generated`` markers is ``tests/unit/test_spine_template_parity.py``'s.

**Reading ``branches.release`` — the recorded choice (R9).**
``.claude/rules/scripts.md`` names three hand-rolled readers of this subject as
the source of #487, #488 and #510, and ``scripts/harness-config.js`` exists to end
that class — but it is a Node CommonJS module with no CLI, so Python cannot import
it, and spawning ``node -e`` would add a host binary to the gate's toolchain
preflight for one string. The call taken is the minimal anchored reader in
:func:`release_branch_from_config`, made safe by **refusing rather than
guessing**: one top-level ``branches:`` block, one ``release:`` key under it, a
value that survives :func:`validated_branch`, and a raise on anything else. A
silently mis-derived release branch is a bar the repo never declared, and
:func:`test_the_release_branch_is_read_rather_than_remembered` feeds it a config
whose answer differs from this repo's, so a constant cannot pass (#458).

**The membership question, answered in place (#491).** This module skips on a
*repository* fact — a ref this checkout does not hold — as well as the *host* fact
(``shutil.which("git")``) the toolchain rule was written for. That rule's purpose
is that the derived host-binary set stays exhaustive; a repository-fact skip adds
no host dependency and cannot make the preflight incomplete. What it shares with a
host skip is the harm — the suite silently running less than it claims — and that
is bounded by the fixture tests below, which exercise every branch of the
predicate on throwaway repositories and never skip. **The logic is proven on every
run; only the live assertion can be inert.** That is also R4's answer: a guard that
refuses once per cycle is otherwise indistinguishable from a broken one, and an
``/assess`` pass would read it as a deletion candidate.

**Bounds and residuals, stated rather than discovered later.** A pre-release
spelling (``7.1.0-rc1``) is legal semver and is **refused** loudly rather than
ordered by a rule this repo has never needed (R6). A remote-tracking ref can be
stale and no local operand can detect that the remote moved; the guard must not
fetch, because a gate reaching the network is neither deterministic nor
offline-runnable — so the bar is the **maximum** across every locally present ref
naming the release role, which cannot lower the bar relative to either operand
alone and so reduces false greens without closing the window (R2). Every message
names the refs tried.

**Why the index.** Every operand is read through it: the candidate via ``git show
:<path>``, the released version via ``git show <ref>:<path>``, the content check
via ``git diff --cached``. ``git write-tree`` certifies the index and the gate
marker is named after the tree it produces, so the index is the only operand that
answers "what will ship" (#482). **Unstaged work is invisible here**, which the
failure messages repeat.

**How this guard is proved.** The pure helpers live under ``tests/``, which
``scripts/mutate.py`` does not mutate, so they were killed by hand: the tuple
comparison swapped for a string comparison (``7.0.10 > 7.0.9`` dies) and ``>`` for
``>=`` (the ``EQUAL`` row dies). The live assertion reads the index and a ref, out
of ``mutate.py``'s reach (#490), so it is proved by **staged probe** — stage a
manifest whose version equals the release ref's, observe the red naming ``EQUAL``,
restore, re-derive ``git write-tree`` to prove the restore was byte-exact — with
the module green before and green again after, because a red that was already red
proves nothing.
"""

# size: past `engineering`'s 300-line soft ceiling and past its 500-line hard
# limit, whose rule is justify near the top or ticket — recorded rather than
# drifted into. The module is one predicate — `release_cycle_verdict` and the pure
# helpers it composes — plus the acceptance matrix that is the only thing proving
# it on a run where the live assertion has nothing to say (R4). Eight verdict kinds
# each owe a fixture, four failing messages owe a distinguishability control, and
# the anchored config reader owes both directions of its refusal; the reasoning
# beside each names what it is the exclusive killer for, which is what a later
# assessment reads to decide whether a row still earns its place. Splitting the
# matrix out would put it in a different file from the predicate it measures, which
# is the trade `tests/unit/test_spine_template_parity.py` already refused. The
# design for #556 targeted 200 lines and named 250 as the point at which the
# instrument is the finding; that target is not reachable against the contract the
# same design specifies, and the gap is reported to the reviewer rather than closed
# by deleting the reasoning.

from __future__ import annotations

import json
import re
import shutil
import subprocess
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

import pytest

from tests._gitutil import indexed_text
from tests.unit._prose import REPO_ROOT

#: The updater-facing manifest. The one operand; see *Not asserted here* above.
MANIFEST_PATH = ".claude-plugin/plugin.json"

#: The sibling files a bump must move with it, named in the ``EQUAL`` message so
#: a builder is not led through three separate red tests to discover them (R3).
BUMP_SIBLINGS = (
    ".codex-plugin/plugin.json",
    "the `spine:generated` marker in AGENTS.md and templates/spine.md",
)

#: ``X.Y.Z`` with no leading zeros, no pre-release, no build metadata.
SEMVER_RE = re.compile(r"(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)")

#: A branch name safe to hand to a ``git`` argv. Anchored with ``fullmatch``: a
#: head-anchored pattern asks "does it *open* like a branch name", and ``-x``
#: reaching a git argv is read as a flag (#510).
BRANCH_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._/-]*")

Semver = tuple[int, int, int]


class SemverError(ValueError):
    """A version string this guard cannot order."""


class BranchNameError(ValueError):
    """A release-branch name that must not reach a ``git`` argv."""


class ConfigError(ValueError):
    """``harness.yaml`` did not declare the release branch in a shape this reads."""


def parse_semver(text: object) -> Semver:
    """``(major, minor, patch)`` for an ``X.Y.Z`` string; raises otherwise.

    The tuple is the point. Comparing the strings orders ``7.0.9`` above
    ``7.0.10``, which is a silent mis-order in exactly the direction a long-lived
    patch series reaches.
    """
    if not isinstance(text, str) or SEMVER_RE.fullmatch(text) is None:
        raise SemverError(f"not an X.Y.Z version this guard can order: {text!r}")
    major, minor, patch = text.split(".")
    return int(major), int(minor), int(patch)


def validated_branch(name: object) -> str:
    """``name``, or raise before it can reach a ``git`` argv.

    ``harness.yaml`` is tracked and reviewed, so this is a boundary check rather
    than a trust judgement: a *malformed* value becomes a git option (``-x``) or
    a traversal in a ``<ref>:<path>`` spelling (``..``). Never falls back to a
    default branch name — a guessed release branch is a bar the repo never
    declared.
    """
    if not isinstance(name, str) or BRANCH_RE.fullmatch(name) is None or ".." in name:
        raise BranchNameError(f"not a branch name this guard will hand to git: {name!r}")
    return name


_BRANCHES_BLOCK = re.compile(r"^branches:[ \t]*(?:#.*)?$", re.MULTILINE)
_RELEASE_KEY = re.compile(r"[ \t]+release:[ \t]*(?P<value>[^\s#]+)[ \t]*(?:#.*)?")


def release_branch_from_config(text: str) -> str:
    """``branches.release`` as ``harness.yaml`` declares it.

    Minimal and refusing, per the recorded choice in this module's docstring. The
    block is anchored at column zero, so a nested ``branches:`` cannot claim it;
    the key is required to be indented, so a top-level ``release:`` elsewhere
    cannot; and both must occur exactly once, so an ambiguous file raises rather
    than resolving to whichever copy this happened to read first. A value the
    reader cannot recognise — quoted, listed, or empty — fails
    :func:`validated_branch` rather than being unwrapped on a guess.
    """
    blocks = list(_BRANCHES_BLOCK.finditer(text))
    if len(blocks) != 1:
        raise ConfigError(f"expected exactly one top-level `branches:` block, found {len(blocks)}")
    values: list[str] = []
    for line in text[blocks[0].end() :].splitlines():
        if line.strip() and not line[:1].isspace():
            break
        found = _RELEASE_KEY.fullmatch(line)
        if found is not None:
            values.append(found.group("value"))
    if len(values) != 1:
        raise ConfigError(f"expected exactly one `release:` key under `branches:`, found {values}")
    return validated_branch(values[0])


class Kind(Enum):
    """Every outcome this guard distinguishes. Assert on these, never on message text."""

    AHEAD = "ahead"
    RELEASE_TREE = "release-tree"
    EQUAL = "equal"
    BEHIND = "behind"
    UNREADABLE_CANDIDATE = "unreadable-candidate"
    UNREADABLE_RELEASE = "unreadable-release"
    NO_RELEASE_REF = "no-release-ref"
    NO_RELEASE_MANIFEST = "no-release-manifest"


#: The two kinds that satisfy the rule, and the two that mean this checkout holds
#: nothing to compare against. Everything else fails.
PASSING = frozenset({Kind.AHEAD, Kind.RELEASE_TREE})
SKIPPING = frozenset({Kind.NO_RELEASE_REF, Kind.NO_RELEASE_MANIFEST})


def _cap(text: str | None) -> str:
    """A version as written, repr'd and capped — it may be bytes from a foreign ref.

    ``repr`` is what stops a pathological value injecting newlines that forge
    extra message lines in gate output.
    """
    return "(absent)" if text is None else repr(text[:64])


@dataclass(frozen=True)
class Verdict:
    """One answer, with every operand that produced it."""

    kind: Kind
    candidate: str | None = None
    released: str | None = None
    ref: str | None = None
    refs_tried: tuple[str, ...] = ()

    def message(self) -> str:
        """Rendered per kind. Two different failures must never compare equal.

        The *two identically-failed runs compare equal* class (#466): a report
        naming one cause for several is a report an operator cannot act on. Each
        message names both version strings, the ref that supplied the released
        one, and which operand came from the index.
        """
        got, had = _cap(self.candidate), _cap(self.released)
        ref = self.ref or "(none)"
        tried = ", ".join(self.refs_tried) or "(none)"
        index_note = "Both operands are read from the git INDEX — stage the change."
        if self.kind is Kind.AHEAD:
            return f"{MANIFEST_PATH} declares {got}, ahead of {ref}'s {had}."
        if self.kind is Kind.RELEASE_TREE:
            return (
                f"the index tree equals {ref}'s, so {MANIFEST_PATH}'s {got} is correctly "
                f"the released version ({had}) and no bump is owed."
            )
        if self.kind is Kind.EQUAL:
            return (
                f"{MANIFEST_PATH} declares {got} and {ref} already carries {had}, while this "
                f"tree's content differs from {ref}'s. This is the first change of a new "
                f"release cycle: raise the version to at least {self.next_patch()} in "
                f"{MANIFEST_PATH}, {BUMP_SIBLINGS[0]}, and {BUMP_SIBLINGS[1]}. Minor or major "
                f"instead where specs/architecture-principles.md's compatibility grammar says "
                f"so. {index_note}"
            )
        if self.kind is Kind.BEHIND:
            return (
                f"{MANIFEST_PATH} declares {got} while {ref} carries {had}, so this tree would "
                f"publish a version older than the one that shipped. The version is only ever "
                f"raised, never lowered — check whether a reconcile dropped the bump, or "
                f"whether {ref} moved backwards. {index_note}"
            )
        if self.kind is Kind.UNREADABLE_CANDIDATE:
            return (
                f"{MANIFEST_PATH} at the index declares {got}, which is not an X.Y.Z version "
                f"this guard can order against {ref}'s {had}. {index_note}"
            )
        if self.kind is Kind.UNREADABLE_RELEASE:
            return (
                f"{ref} carries {MANIFEST_PATH} but its version reads {had}, which is not an "
                f"X.Y.Z version this guard can order against the index's {got}. Refs tried: "
                f"{tried}."
            )
        if self.kind is Kind.NO_RELEASE_REF:
            return (
                f"no ref naming the release role exists in this checkout, so there is nothing "
                f"to compare against. Refs tried: {tried}."
            )
        return (
            f"a release ref exists but none carries {MANIFEST_PATH}, so there is no released "
            f"version to compare against. Refs tried: {tried}."
        )

    def next_patch(self) -> str:
        """The smallest version that would satisfy the rule. Arithmetic a builder acts on."""
        major, minor, patch = parse_semver(self.released)
        return f"{major}.{minor}.{patch + 1}"


def _git(repo_root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    """One git invocation. An argv list with ``cwd``; never ``shell=True``."""
    return subprocess.run(
        ["git", *args], cwd=repo_root, capture_output=True, text=True, check=False
    )


def _ref_exists(repo_root: Path, ref: str) -> bool:
    """``--verify --quiet`` is required.

    A bare ``git rev-parse <name>`` exits 0 printing the name back for a ref that
    does not exist, so the cheaper spelling reports every ref as present
    (``tests/unit/test_gate_evidence_hook.py:880-885`` records the same trap).
    """
    return _git(repo_root, "rev-parse", "--verify", "--quiet", ref).returncode == 0


def _declared_version(manifest_text: str | None) -> str | None:
    """The ``version`` a manifest declares, as written; ``None`` where there is none.

    Every malformed shape — non-JSON bytes from a foreign ref, a non-object, a
    missing key — becomes a named refusal upstream rather than an exception
    trace. ``json.loads`` only; never ``eval``.
    """
    if manifest_text is None:
        return None
    try:
        payload = json.loads(manifest_text)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict) or "version" not in payload:
        return None
    version = payload["version"]
    return version if isinstance(version, str) else repr(version)


def _manifest_at(repo_root: Path, spec: str) -> str | None:
    """``git show <spec>``, or ``None`` where the path does not exist there."""
    shown = _git(repo_root, "show", spec)
    return shown.stdout if shown.returncode == 0 else None


def release_cycle_verdict(
    repo_root: Path, *, release_branch: str, remote: str = "origin"
) -> Verdict:
    """Does this tree satisfy the start-of-cycle rule?

    ``remote`` is a literal default rather than configuration, matching
    ``scripts/harness-refs.js``'s documented default; it is named in every
    message, so a divergent setup is visible rather than silent.
    """
    name = validated_branch(release_branch)
    refs = (f"refs/remotes/{remote}/{name}", f"refs/heads/{name}")
    candidate_raw = _declared_version(_manifest_at(repo_root, f":{MANIFEST_PATH}"))

    existing = tuple(ref for ref in refs if _ref_exists(repo_root, ref))
    if not existing:
        return Verdict(Kind.NO_RELEASE_REF, candidate=candidate_raw, refs_tried=refs)

    carried = tuple(
        (ref, _declared_version(text))
        for ref in existing
        if (text := _manifest_at(repo_root, f"{ref}:{MANIFEST_PATH}")) is not None
    )
    if not carried:
        return Verdict(Kind.NO_RELEASE_MANIFEST, candidate=candidate_raw, refs_tried=refs)

    parsed: list[tuple[str, str, Semver]] = []
    for ref, raw in carried:
        try:
            parsed.append((ref, raw or "", parse_semver(raw)))
        except SemverError:
            continue
    if not parsed:
        ref, raw = carried[0]
        return Verdict(
            Kind.UNREADABLE_RELEASE,
            candidate=candidate_raw,
            released=raw,
            ref=ref,
            refs_tried=refs,
        )

    # ``max`` returns the first maximal element, so a tie is resolved by the order
    # the refs are tried and the remote-tracking ref wins it.
    ref, released_raw, released = max(parsed, key=lambda entry: entry[2])
    context = {
        "candidate": candidate_raw,
        "released": released_raw,
        "ref": ref,
        "refs_tried": refs,
    }

    content = _git(repo_root, "diff", "--quiet", "--cached", ref)
    if content.returncode == 0:
        return Verdict(Kind.RELEASE_TREE, **context)
    if content.returncode != 1:
        raise AssertionError(
            f"`git diff --quiet --cached {ref}` exited {content.returncode}: "
            f"{content.stderr.strip()!r}. A git failure is not a verdict."
        )

    try:
        candidate = parse_semver(candidate_raw)
    except SemverError:
        return Verdict(Kind.UNREADABLE_CANDIDATE, **context)

    if candidate > released:
        return Verdict(Kind.AHEAD, **context)
    if candidate == released:
        return Verdict(Kind.EQUAL, **context)
    return Verdict(Kind.BEHIND, **context)


# ---------------------------------------------------------------------------
# T1 / T2 — the ordering, and what the parser refuses
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("higher", "lower"),
    [("7.0.10", "7.0.9"), ("7.10.0", "7.9.0"), ("10.0.0", "9.0.0")],
)
def test_versions_are_ordered_numerically_not_lexically(higher: str, lower: str) -> None:
    """All three positions, because a string comparison passes the one-digit cases.

    Observed RED at #556: against a first implementation returning the string,
    ``assert '7.0.10' > '7.0.9'`` failed — the two-digit boundary is where a
    lexical order and a numeric one part company, and one case would not
    distinguish the implementations.
    """
    assert parse_semver(higher) > parse_semver(lower)


@pytest.mark.parametrize(
    "value", ["7.0", "7.0.0.1", "v7.0.0", "7.1.0-rc1", "07.0.0", "", None, 7]
)
def test_the_parser_refuses_what_it_cannot_order(value: object) -> None:
    """Refusing loudly beats mis-ordering silently; the input is named either way."""
    with pytest.raises(SemverError, match=re.escape(repr(value))):
        parse_semver(value)


# ---------------------------------------------------------------------------
# The release-branch reader, and the argv boundary
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("config", "expected"),
    [
        # #458: an answer that differs from this repo's `main`, so a reader
        # returning a constant cannot pass against production data alone.
        ("repo:\n  name: x\nbranches:\n  release: production\n  integration: t\n", "production"),
        # The spelling this repo's own `harness.yaml` carries. A reader going red
        # or silent on a legal spelling of its subject is a defect (#484, #487).
        ("branches:\n  integration: dev\n  release: main   # ADR 0003 as amended\n", "main"),
    ],
)
def test_the_release_branch_is_read_rather_than_remembered(config: str, expected: str) -> None:
    """The bar comes from ``harness.yaml``, never from a literal ``main`` here."""
    assert release_branch_from_config(config) == expected


@pytest.mark.parametrize(
    "config",
    [
        "repo:\n  name: x\n",
        "branches:\n  integration: dev\n",
        "branches:\n  integration: dev\n  release: main\nbranches:\n  release: other\n",
        "branches:\n  release: one\n  release: two\n",
        'branches:\n  release: "main"\n',
        "branches:\n  release:\n    - main\n",
        "branches:\n  release: -delete\n",
        "branches:\n  release: ../etc\n",
        "release: main\n",
    ],
)
def test_the_release_branch_reader_refuses_rather_than_guesses(config: str) -> None:
    """Absent, ambiguous, quoted, listed, or unsafe — each raises.

    A partial reader returning a best guess would hold the gate against a bar the
    repo never declared, and a green run cannot show that (#490).
    """
    with pytest.raises((ConfigError, BranchNameError)):
        release_branch_from_config(config)


def test_an_unsafe_branch_name_never_reaches_a_git_argv(tmp_path: Path) -> None:
    """Asserted on the verdict entry point, not only on the validator, because that
    is where an unvalidated name would be spent."""
    with pytest.raises(BranchNameError):
        release_cycle_verdict(tmp_path, release_branch="--upload-pack=touch /tmp/x")


# ---------------------------------------------------------------------------
# T3 — every verdict kind, on throwaway repositories
# ---------------------------------------------------------------------------

#: The fixtures' release role, and their versions, are deliberately nothing this
#: repository carries: a helper with ``main`` or ``7.0.0`` baked in anywhere would
#: pass the live assertion below and fail here (T6, #458). The independence is
#: structural — it is the choice of names and numbers, not a comment.
FIXTURE_RELEASE = "shipped"


def _run(repo: Path, *args: str) -> None:
    done = subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, check=False)
    assert done.returncode == 0, f"git {args}: {done.stderr.strip()}"


def _manifest(version: object) -> dict[str, object]:
    return {"name": "harness", "version": version}


def _write(repo: Path, payload: dict[str, object]) -> None:
    path = repo / MANIFEST_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _released_repo(
    tmp_path: Path,
    payload: dict[str, object] | None,
    *,
    branch: str = FIXTURE_RELEASE,
    remote_ref: bool = True,
) -> Path:
    """A repo whose release ref carries ``payload``; ``None`` carries no manifest."""
    repo = tmp_path / "fixture"
    repo.mkdir()
    _run(repo, "init", "-q", "-b", branch)
    _run(repo, "config", "user.email", "t@example.com")
    _run(repo, "config", "user.name", "t")
    (repo / "README.md").write_text("released content\n", encoding="utf-8")
    _run(repo, "add", "README.md")
    if payload is not None:
        _write(repo, payload)
        _run(repo, "add", MANIFEST_PATH)
    _run(repo, "commit", "-q", "-m", "release")
    if remote_ref:
        _run(repo, "update-ref", f"refs/remotes/origin/{FIXTURE_RELEASE}", "HEAD")
    return repo


def _stage(repo: Path, payload: dict[str, object] | None = None, *, diverge: bool = True) -> None:
    if diverge:
        (repo / "CHANGED.md").write_text("content the release does not carry\n", encoding="utf-8")
        _run(repo, "add", "CHANGED.md")
    if payload is not None:
        _write(repo, payload)
        _run(repo, "add", MANIFEST_PATH)


def _verdict(repo: Path) -> Verdict:
    return release_cycle_verdict(repo, release_branch=FIXTURE_RELEASE)


@pytest.mark.parametrize(
    ("candidate", "expected"),
    [
        ("2.3.4", Kind.EQUAL),
        ("2.3.5", Kind.AHEAD),
        ("2.3.10", Kind.AHEAD),
        ("2.3.3", Kind.BEHIND),
    ],
)
def test_a_diverging_tree_is_judged_against_the_released_version(
    tmp_path: Path, candidate: str, expected: Kind
) -> None:
    """The rule itself. ``2.3.10`` kills a lexical comparison at the integration
    level, not only at the unit — the two implementations agree on every other row."""
    repo = _released_repo(tmp_path, _manifest("2.3.4"))
    _stage(repo, _manifest(candidate))

    assert _verdict(repo).kind is expected


def test_a_tree_that_is_the_release_tree_owes_no_bump(tmp_path: Path) -> None:
    """R5 / D4: the index tree equals the release ref's, with the versions equal and
    the release branch checked out — the shape the ``push: main`` CI run has. Removing
    this escape hatch would make that run permanently red."""
    repo = _released_repo(tmp_path, _manifest("2.3.4"))

    assert _verdict(repo).kind is Kind.RELEASE_TREE


def test_no_ref_naming_the_release_role_is_a_skip(tmp_path: Path) -> None:
    """R1: a checkout that never fetched the release ref at all — the shape any
    consumer repo is in before it names a ``branches.release``, and the shape this
    repo's own ``push: dev`` CI run was in before #580 gave its checkout
    ``fetch-depth: 0``. A verdict here would be a claim made against an operand
    this checkout does not have."""
    repo = _released_repo(tmp_path, _manifest("2.3.4"), branch="other", remote_ref=False)
    _stage(repo, _manifest("2.3.4"))
    verdict = _verdict(repo)

    assert verdict.kind is Kind.NO_RELEASE_REF
    assert verdict.refs_tried, "a skip that names no ref is a skip nobody can diagnose"


def test_a_release_ref_with_no_manifest_is_a_skip(tmp_path: Path) -> None:
    """A repo adopting the plugin before it published one."""
    repo = _released_repo(tmp_path, None)
    _stage(repo, _manifest("2.3.4"))

    assert _verdict(repo).kind is Kind.NO_RELEASE_MANIFEST


def test_an_unorderable_released_version_is_named_not_assumed(tmp_path: Path) -> None:
    """A release ref whose manifest cannot be ordered must not read as "no release"."""
    repo = _released_repo(tmp_path, _manifest("seven"))
    _stage(repo, _manifest("2.3.5"))

    assert _verdict(repo).kind is Kind.UNREADABLE_RELEASE


def test_an_unorderable_candidate_version_is_named_not_assumed(tmp_path: Path) -> None:
    """A manifest with no ``version`` key at the index. Distinct from the above:
    collapsing the two would tell a builder to look at the wrong file."""
    repo = _released_repo(tmp_path, _manifest("2.3.4"))
    _stage(repo, {"name": "harness"})

    assert _verdict(repo).kind is Kind.UNREADABLE_CANDIDATE


def test_a_local_release_branch_alone_is_still_a_release(tmp_path: Path) -> None:
    """D3, the silent direction: a checkout holding only ``refs/heads/<release>`` —
    a release made and not pushed. Reading the remote-tracking ref alone reports
    ``NO_RELEASE_REF`` and **skips**, which is a false green rather than a red."""
    repo = _released_repo(tmp_path, _manifest("2.3.4"), remote_ref=False)
    _stage(repo, _manifest("2.3.4"))

    assert _verdict(repo).kind is Kind.EQUAL


def test_the_bar_is_the_highest_release_ref_not_the_remote_one(tmp_path: Path) -> None:
    """D3, the loud direction: the remote-tracking ref is one release stale.

    Reading it alone gives ``2.3.4`` as the bar and certifies ``2.3.5`` as
    ``AHEAD`` — the first change of a new cycle sailing through with no bump,
    which is exactly the window the rule exists for. The maximum across the refs
    the repository holds cannot *lower* the bar relative to either operand alone.
    """
    repo = _released_repo(tmp_path, _manifest("2.3.4"))
    _write(repo, _manifest("2.4.0"))
    _run(repo, "add", MANIFEST_PATH)
    _run(repo, "commit", "-q", "-m", "the release the remote-tracking ref has not seen")
    _stage(repo, _manifest("2.3.5"))
    verdict = _verdict(repo)

    assert verdict.kind is Kind.BEHIND
    assert verdict.ref == f"refs/heads/{FIXTURE_RELEASE}", verdict.message()


# ---------------------------------------------------------------------------
# T4 — the failing messages are distinguishable
# ---------------------------------------------------------------------------


def test_each_failing_verdict_renders_its_own_message() -> None:
    """#466 — two identically-failed runs compare equal.

    Asserted on the rendered text being *distinct* and *complete*, never on a
    pinned substring of any one message: pinning wording is the #511 shape and
    refuses a legitimate reword.
    """
    common = {"candidate": "2.3.4", "released": "2.3.9", "ref": "refs/heads/shipped"}
    failing = [Verdict(kind, **common) for kind in Kind if kind not in PASSING | SKIPPING]
    rendered = [verdict.message() for verdict in failing]

    assert len(failing) == 4, [verdict.kind for verdict in failing]
    assert len(set(rendered)) == len(rendered), rendered
    for verdict, text in zip(failing, rendered, strict=True):
        assert "2.3.4" in text and "2.3.9" in text, (verdict.kind, text)
        assert "refs/heads/shipped" in text, (verdict.kind, text)


def test_the_first_change_of_a_cycle_is_told_which_version_to_raise_to() -> None:
    """R3: the bump touches four files and each is found by a separate red test, so
    the message that fires first enumerates them and does the arithmetic."""
    verdict = Verdict(Kind.EQUAL, candidate="2.3.9", released="2.3.9", ref="refs/heads/shipped")

    assert verdict.next_patch() == "2.3.10"
    assert "2.3.10" in verdict.message()


# ---------------------------------------------------------------------------
# T5 — the live assertion, over this repository
# ---------------------------------------------------------------------------


def test_this_tree_declares_a_version_ahead_of_the_release_it_differs_from() -> None:
    """The rule, over the tree that ships.

    ``NO_RELEASE_REF`` and ``NO_RELEASE_MANIFEST`` skip: this checkout holds no
    operand, which is a fact about the checkout and not about the tree. Every
    other kind fails with the rendered message.
    """
    if shutil.which("git") is None:
        pytest.skip("git is not resolvable off PATH, so no operand can be read")
    branch = release_branch_from_config(indexed_text("harness.yaml"))
    verdict = release_cycle_verdict(REPO_ROOT, release_branch=branch)
    if verdict.kind in SKIPPING:
        pytest.skip(verdict.message())

    assert verdict.kind in PASSING, verdict.message()
