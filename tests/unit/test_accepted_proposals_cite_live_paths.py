"""An `accepted` proposal must not name a path the tracked tree no longer has.

**The occurrence this guard cites (#458).** `accepted` is the vocabulary's
*decided, still buildable* state, so an accepted proposal is a standing
instruction. ADR 0015 deleted the runtime and no proposal said so: nineteen files
still read `accepted`, and fourteen of them cited paths the teardown had removed
— `close-merge-in-throwaway-worktree` pointing at `harness/cli/close.py`,
`promotion-guard-instrument` at `harness/cli/_repo.py`, and so on. An agent
grounding a ticket against one of them inherits instructions targeting code that
is gone. This is the mechanical form of *accepted means still buildable*.

**Shape: one pure predicate, several callers.** :func:`dead_path_cites` takes
text and the tracked sets and returns the offending tokens. The corpus sweep and
every sample below call that same function, so a change to how production judges
a cite is a change to what every sample measures — ``craft.md`` → *Exercise the
production path, not merely a production constant*.

**Where the teeth are.** After #458's pass there are **zero** `accepted`
proposals, so the corpus sweep ranges over an empty set and proves nothing about
the predicate today; it is kept as forward regression protection for the next
proposal accepted, and it says so rather than dressing an empty sweep up as
coverage. The predicate's teeth are the paired samples:

* a dead cite in ordinary prose is flagged (the admission direction);
* a live cite in ordinary prose is not (the stale-exemption direction);
* a dead cite **inside** a supersession banner is not (the exemption works);
* a dead cite **outside** the banner, in a text that also carries one, still is
  (the exemption does not reach past its own paragraph).

The last two are the banner exemption's two directions. An allowlist bounded
from one side only is the defect this repo has shipped four times (#449, #453,
#455, #457) — ``craft.md`` → *ANY ALLOWLIST OR EXEMPTION NEEDS BOTH
DIRECTIONS*. The banner is not this predicate's only exemption, and review
found the other two bounded from the admitting side alone: a token outside the
repo-relative frame and a slash-bearing token that names no file each now have
a stale-direction sample, and the banner opener's line-start anchoring has one
of its own.

:func:`test_the_predicate_reads_real_proposal_text` is the paired splice that
keeps the corpus half honest while it is empty: it splices a dead cite into a
real tracked proposal and requires it flagged, so a reader that silently stopped
reaching the corpus fails rather than reporting a clean empty sweep.
"""

from __future__ import annotations

import re
from pathlib import Path

from tests._gitutil import tracked_files_under
from tests.unit.test_proposal_status_vocabulary import proposal_status

_REPO_ROOT = Path(__file__).resolve().parents[2]

#: Suffixes that make a backticked token a *source path* rather than prose. A
#: token with none of these and no trailing ``/`` — ``sluengen/harness``,
#: ``dev/staging`` — is a name that merely contains a slash, not a cite.
_SOURCE_SUFFIXES = (".py", ".md", ".sh", ".yaml", ".yml", ".json", ".toml", ".html")

#: Prefixes that put a token outside the repo-relative frame: a home path, an
#: absolute path, a shell variable, a placeholder. Comparing those against
#: ``git ls-files`` output would be the different-frames class in ``craft.md``.
#:
#: ``.`` is the deliberate over-exclusion, and it is a recorded gap rather than a
#: complete rule: it drops ``../decisions/0015-….md``-style relative cites, whose
#: frame is the citing file and not the repo root — and with them any cite of a
#: dotted tree such as ``.codex/`` or ``.github/``. Resolving relative cites
#: against each file's own directory would recover both, and is deliberately not
#: done here: no proposal currently backticks one, so the machinery would be
#: speculative. If a dotted-tree cite ever needs checking, that is the change to
#: make — not a narrower prefix list, which would start reporting every relative
#: cite as dead.
_FOREIGN_PREFIXES = ("~", "/", "$", "<", ".")

_BACKTICKED = re.compile(r"`([^`\n]+)`")

#: A trailing source location: ``:541`` or ``:517-530``.
_LOCATION_SUFFIX = re.compile(r":\d+(?:-\d+)?$")

#: The supersession banner's opening line, and nothing else. Both live house
#: styles are admitted — the blockquote form ``specs/retired/`` uses and the
#: italicised form the proposals carry — each pinned to the literal word plus an
#: ISO date, so ordinary prose *about* supersession cannot open an exemption.
#: Anchoring to line start is the counterfeited-delimiter remedy in ``craft.md``.
_BANNER_OPENER = re.compile(
    r"^\s*(?:>\s*)?\*{2,3}Superseded \d{4}-\d{2}-\d{2}\*\*",
)


def banner_line_numbers(text: str) -> set[int]:
    """Indices of the lines a supersession banner covers.

    The exemption is the banner's own **paragraph** — the opener line plus the
    non-blank lines continuing it — and stops at the first blank line. Scoping it
    to the whole file would exempt every cite in a superseded proposal, which is
    the over-reaching half this guard's fourth sample exists to catch.
    """
    covered: set[int] = set()
    in_banner = False
    for index, line in enumerate(text.splitlines()):
        if _BANNER_OPENER.match(line):
            in_banner = True
        elif not line.strip():
            in_banner = False
        if in_banner:
            covered.add(index)
    return covered


def dead_path_cites(text: str, tracked: set[str], tracked_dirs: set[str]) -> list[str]:
    """Backticked repo-relative path cites in ``text`` that the tree no longer has.

    ``tracked`` is the repo-relative posix path of every tracked file;
    ``tracked_dirs`` every directory prefix of those paths. A token ending in
    ``/`` is judged against the directories, everything else against the files.
    Cites inside a supersession banner are exempt — a banner exists precisely to
    name machinery that is gone.
    """
    exempt = banner_line_numbers(text)
    dead: list[str] = []
    for index, line in enumerate(text.splitlines()):
        if index in exempt:
            continue
        for raw in _BACKTICKED.findall(line):
            # A backticked span may be a command line rather than a bare path
            # (`bash scripts/verify.sh`). Judge each word, so the cite inside an
            # invocation is checked and the verb around it is not mistaken for
            # part of the path.
            for word in raw.split():
                token = _LOCATION_SUFFIX.sub("", word)
                if "/" not in token or token.startswith(_FOREIGN_PREFIXES):
                    continue
                if token.endswith("/"):
                    if token.rstrip("/") not in tracked_dirs:
                        dead.append(token)
                elif token.endswith(_SOURCE_SUFFIXES) and token not in tracked:
                    dead.append(token)
    return sorted(set(dead))


def _tracked_paths() -> set[str]:
    return {
        path.relative_to(_REPO_ROOT).as_posix()
        for path in tracked_files_under(".")
    }


def _tracked_dirs(tracked: set[str]) -> set[str]:
    dirs: set[str] = set()
    for rel in tracked:
        parent = Path(rel).parent
        while parent != Path("."):
            dirs.add(parent.as_posix())
            parent = parent.parent
    return dirs


def _accepted_proposals() -> list[Path]:
    return sorted(
        path
        for path in tracked_files_under("specs/proposals")
        if path.suffix == ".md" and proposal_status(path.read_text()) == "accepted"
    )


# ---------------------------------------------------------------------------
# The comparison sets the predicate consumes
# ---------------------------------------------------------------------------


def test_the_tracked_sets_are_live() -> None:
    """Floor on the sets the predicate compares *against*, not on its subjects.

    ``craft.md`` → *The empty comparison set*: a derivation that quietly yields
    ``[]`` here would make every sample and every sweep agree that nothing is
    dead, with no skip and no warning. Membership is pinned, never cardinality.
    """
    tracked = _tracked_paths()
    dirs = _tracked_dirs(tracked)
    assert "scripts/verify.sh" in tracked, (
        "the tracked-file derivation no longer contains the repo's own gate — "
        f"it yielded {len(tracked)} paths"
    )
    assert "specs/proposals" in dirs, (
        "the tracked-directory derivation no longer contains specs/proposals"
    )


# ---------------------------------------------------------------------------
# The paired samples — the guard's teeth
# ---------------------------------------------------------------------------

_TRACKED_SAMPLE = {"scripts/verify.sh", "specs/proposals/design-verb.md"}
_TRACKED_DIRS_SAMPLE = {"scripts", "specs", "specs/proposals"}


def test_a_dead_cite_in_ordinary_prose_is_flagged() -> None:
    """Admission direction: the predicate reports a path the tree does not have."""
    sample = "The close verb merges in a throwaway worktree (`harness/cli/close.py:541`)."
    assert dead_path_cites(sample, _TRACKED_SAMPLE, _TRACKED_DIRS_SAMPLE) == [
        "harness/cli/close.py"
    ]


def test_a_live_cite_inside_an_invocation_is_not_flagged() -> None:
    """A backticked command line is judged word by word, not as one token.

    `bash scripts/verify.sh` is a live cite wearing a verb. Judging the span
    whole makes it unresolvable and reports the repo's own gate as deleted —
    measured on #458's first run, where it was one of two false positives.
    """
    sample = "Run `bash scripts/verify.sh` and then `bash scripts/missing.sh`."
    assert dead_path_cites(sample, _TRACKED_SAMPLE, _TRACKED_DIRS_SAMPLE) == [
        "scripts/missing.sh"
    ]


def test_a_live_cite_in_ordinary_prose_is_not_flagged() -> None:
    """Stale-exemption direction: a path the tree still has must not be reported."""
    sample = "The gate is `scripts/verify.sh`, and the proposals live in `specs/proposals/`."
    assert dead_path_cites(sample, _TRACKED_SAMPLE, _TRACKED_DIRS_SAMPLE) == []


def test_a_dead_cite_inside_a_banner_is_exempt() -> None:
    """The exemption works: a banner names dead machinery, that is its whole job."""
    sample = (
        "# Proposal: close-merge-in-throwaway-worktree\n"
        "\n"
        "***Superseded 2026-08-15** by ADR 0015 — the `harness/cli/close.py` this\n"
        "proposes was retired before it was built.*\n"
    )
    assert dead_path_cites(sample, _TRACKED_SAMPLE, _TRACKED_DIRS_SAMPLE) == []


def test_a_dead_cite_outside_the_banner_is_still_flagged() -> None:
    """The exemption's other direction: it does not reach past its own paragraph.

    Same file, same dead token, one carrying a banner — so the only difference
    between this sample and the one above is *where* the cite sits. An exemption
    bounded only from the admitting side would swallow this too, and would read
    exactly as green.
    """
    sample = (
        "# Proposal: close-merge-in-throwaway-worktree\n"
        "\n"
        "***Superseded 2026-08-15** by ADR 0015 — kept for the audit.*\n"
        "\n"
        "## Recommendation\n"
        "\n"
        "Move the merge into `harness/cli/close.py` behind a throwaway worktree.\n"
    )
    assert dead_path_cites(sample, _TRACKED_SAMPLE, _TRACKED_DIRS_SAMPLE) == [
        "harness/cli/close.py"
    ]


def test_a_token_outside_the_repo_relative_frame_is_not_a_cite() -> None:
    """The stale direction of the ``_FOREIGN_PREFIXES`` exemption.

    A home path, an absolute path, a shell variable and a placeholder are not
    repo-relative, so judging them against ``git ls-files`` output would be the
    different-frames class in ``craft.md``. Added at review: emptying the tuple
    ran **live** against the whole suite and killed nothing, so the exemption
    was bounded from the admitting side only. One sample per prefix, so
    dropping any single one of them is what fails.
    """
    sample = (
        "See `../decisions/0015-x.md`, `/etc/hosts.py`, `$HOME/y.py` and `<repo>/z.py`."
    )
    assert dead_path_cites(sample, _TRACKED_SAMPLE, _TRACKED_DIRS_SAMPLE) == []


def test_a_slash_bearing_name_is_not_a_path_cite() -> None:
    """The stale direction of the ``_SOURCE_SUFFIXES`` gate, same measurement.

    ``sluengen/harness`` and ``dev/staging`` contain a slash and name no file.
    Dropping the suffix requirement makes every slash-bearing word a cite and
    reports both as dead; before this sample that edit survived the suite,
    while the admitting direction was already held by the first sample above.
    """
    sample = "The repo is `sluengen/harness` and the promotion hop is `dev/staging`."
    assert dead_path_cites(sample, _TRACKED_SAMPLE, _TRACKED_DIRS_SAMPLE) == []


def test_prose_mentioning_a_banner_does_not_open_an_exemption() -> None:
    """The opener is anchored to line start, and this is what says so.

    ``craft.md`` → *A paired delimiter can be counterfeited by prose that
    mentions it*. The anchoring is deliberately redundant — :func:`re.match` at
    the call site and ``^`` in the pattern — and review measured that dropping
    either one **alone** changes nothing observable, which is why no
    single-edit mutation can reach it. Dropping both does counterfeit the
    banner and swallows the cite on the same line; this sample is what turns
    that widening into a red instead of a silent one.
    """
    sample = (
        "A cite on a line that merely mentions ***Superseded 2026-08-15** in "
        "passing* is `harness/cli/close.py`."
    )
    assert banner_line_numbers(sample) == set()
    assert dead_path_cites(sample, _TRACKED_SAMPLE, _TRACKED_DIRS_SAMPLE) == [
        "harness/cli/close.py"
    ]


def test_the_predicate_reads_real_proposal_text() -> None:
    """Paired splice: prove the corpus reader reaches real proposal bytes.

    ``craft.md`` → *A prose mutation needs a paired splice to prove it was live*.
    While the sweep below covers an empty set, nothing else here would notice a
    reader that had stopped resolving the corpus at all. This splices a token the
    predicate is known to catch into a real tracked proposal and requires it
    caught **there**, so "the sweep found nothing" is distinguishable from "the
    sweep read nothing".
    """
    tracked = _tracked_paths()
    dirs = _tracked_dirs(tracked)
    real = (_REPO_ROOT / "specs/proposals/design-verb.md").read_text()
    spliced = "harness/cli/a-path-this-repo-never-had.py"
    before = dead_path_cites(real, tracked, dirs)
    after = dead_path_cites(f"{real}\n\nSee `{spliced}`.\n", tracked, dirs)
    assert spliced not in before, (
        "the splice token must not already be in the file, or its appearance "
        "afterwards proves nothing about the reader"
    )
    assert spliced in after, (
        "a dead cite spliced into a real tracked proposal was not reported — the "
        "predicate is not reaching real corpus text, and an empty corpus sweep "
        "would be indistinguishable from a working one"
    )


# ---------------------------------------------------------------------------
# The corpus sweep — forward regression protection, empty today
# ---------------------------------------------------------------------------


def test_no_accepted_proposal_cites_a_dead_path() -> None:
    """AC-2, over whatever proposals currently read `accepted`.

    **This sweep may cover zero proposals.** #458 advanced all nineteen to
    `shipped` or `superseded`, so on the shipping tree its subject set is empty
    and it asserts nothing about the predicate — the samples above are what
    measure that. It is kept because the next proposal accepted is the one this
    check exists for, and it fails the day that proposal cites something gone.
    No floor asserts the subject set is non-empty: here empty is the intended
    state, and a floor demanding otherwise would be permanently red.
    """
    tracked = _tracked_paths()
    dirs = _tracked_dirs(tracked)
    subjects = _accepted_proposals()
    offenders = {
        path.relative_to(_REPO_ROOT).as_posix(): dead
        for path in subjects
        if (dead := dead_path_cites(path.read_text(), tracked, dirs))
    }
    assert not offenders, (
        f"these `accepted` proposals cite paths absent from the tracked tree, so "
        f"they read as standing instructions to build deleted machinery. Advance "
        f"the status and add a dated supersession banner, or fix the cite "
        f"(covered {len(subjects)} accepted proposals): {offenders}"
    )
