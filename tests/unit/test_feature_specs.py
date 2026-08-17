"""CAL-661 — the harness's as-built record lives in ``specs/features/``.

With ``feature_specs`` on (``CONTEXT.md``, CAL-660), the harness dogfoods the
feature-spec surface it publishes: the as-built record of each current
verb-model subsystem is a ``specs/features/<feature>.md`` in the
``templates/feature.md`` shape, not a design doc under ``specs/``. This guard is
the executable form of the migration's acceptance criteria:

* **AC-1** — each subsystem this repo still has has a
  ``specs/features/<feature>.md`` in the feature-spec shape: the
  ``templates/feature.md`` frontmatter keys and a ``## Behaviour`` section (the
  canonical "how does it work?" answer).
* **AC-3** — the as-built record has no dangling links: every relative ``.md``
  link in it resolves to a file git tracks. A row that points the reader at a
  moved or never-created spec is worse than none.

The check is structural: a regression that deletes a feature spec, drops a
required section, or leaves a dangling link fails here.

**#435 removed the semantic-coverage half, and five of the six subjects.** Six
guards here tied the specs' prose to the code that implemented it — the
documented CLI surface against the registered Typer commands, the documented
flags against the registered options, ``verb-model.md``'s output keys against
the Pydantic models, the worktree path constants, the verdict and run-status
literals. ADR 0015 deletes that code, so each was measuring a spec against a
module that no longer exists; a comparison with one side missing is not a weaker
guard, it is no guard. Then the specs themselves followed: five records of
retired subsystems moved to ``specs/retired/`` under dated banners
(``tests/unit/test_v4_teardown.py`` holds that move), and ``SPEC.md`` — whose
index this module used to check for dangling links — went with the design it
described.

What is left is one record and the same structural rule over it.
``specs/features/guidance-system.md`` is the as-built record of the delivery
mechanism ADR 0015 explicitly keeps — the registry, the copy-in installer,
``/update-guidance`` and the freshness hook — and its ``last_updated`` currency
is what the CI checkout's ``fetch-depth: 0`` exists for.

Since #280 the module also measures one frontmatter **value**. ``last_updated``
was required to exist and never read, so all four records drifted to declaring a
currency that was false — the same unmeasured-claim family as #275, one file
over. The date guard below reads the value against git and is derived from the
tracked tree, so a fifth feature spec is covered on arrival.

**#463 re-frames that date check rather than loosening it.** The comparison read
its two operands in different frames: ``last_updated`` is a zoneless calendar day
typed by a writer, while git rendered the commit day in the *commit's own*
recorded offset. A ``+10:00`` commit made just past local midnight therefore
reported the following day, and the guard went red on a record that was accurate
— on ``dev`` and on the promotion candidate alike, the latter only more visibly
because the nightly runs at 14:10Z, inside the window where the frames disagree.
The fix is in :func:`tests._gitutil.last_commit_date`, which now reads a UTC day;
the rule here is unchanged, and the test below pins that it is.

**#446 removes a required key rather than adding a check for it.** ``tickets:``
compelled every record to list the tracker issues that shaped it — a
hand-maintained list duplicating what the record's own ``git log`` already holds,
and one that had gone four tickets stale before anyone read it. ADR 0014 already
settled this class here when it deleted the changelog-fragment system: *a record
that is compelled per-change, and that duplicates a record already being written,
is a tax rather than a control.* That ADR also names the near miss — the fragment
system's byte guard, "correctly identifying the second copy, then capping its
length rather than asking why it exists". A guard checking ``tickets:`` against
git would have been that same mistake one level up, so the key is deleted from
the schema and from ``templates/feature.md``, and the record points a reader at
``git log`` instead. Nothing asserts the key stays *absent*: a guard against its
return is the machinery this removes, and ADR 0014's own deletion added none.
"""

from __future__ import annotations

import os
import re
import subprocess
from datetime import date
from pathlib import Path

import pytest

from tests._gitutil import init_repo, last_commit_date, tracked_files_under
from tests.unit._prose import REPO_ROOT

_FEATURES_DIR = REPO_ROOT / "specs" / "features"

#: The subsystems this repo still has, each of which must carry a feature spec
#: (AC-1). The slug is the ``specs/features/<slug>.md`` basename.
#:
#: One entry since #435. The other four named the verb model, the run ledger,
#: the worktree lifecycle and the CLI surface — all deleted by ADR 0015, with
#: their records archived under ``specs/retired/``. Requiring a record for a
#: subsystem that no longer exists would be the mirror of the defect this list
#: exists to catch.
_EXPECTED_FEATURES = ("guidance-system",)

#: Frontmatter keys required by ``templates/feature.md``.
_REQUIRED_FRONTMATTER = ("feature", "status", "last_updated")


def _feature_path(slug: str) -> Path:
    return _FEATURES_DIR / f"{slug}.md"


def _tracked_feature_specs() -> set[Path]:
    return tracked_files_under("specs/features")


@pytest.mark.parametrize("slug", _EXPECTED_FEATURES)
def test_feature_spec_exists_and_is_tracked(slug: str) -> None:
    """Each current verb-model subsystem has a tracked feature spec (AC-1)."""
    path = _feature_path(slug)
    assert path.resolve() in _tracked_feature_specs(), (
        f"expected feature spec {path.relative_to(REPO_ROOT)} to exist and be "
        "git-tracked — AC-1 requires each current verb-model subsystem to carry "
        "a specs/features/<feature>.md as-built record"
    )


@pytest.mark.parametrize("slug", _EXPECTED_FEATURES)
def test_feature_spec_has_template_frontmatter(slug: str) -> None:
    """Each feature spec carries the ``templates/feature.md`` frontmatter keys."""
    text = _feature_path(slug).read_text(encoding="utf-8")
    fm_match = re.match(r"^---\n(.*?)\n---\n", text, re.DOTALL)
    assert fm_match, f"{slug}.md is missing the YAML frontmatter block"
    frontmatter = fm_match.group(1)
    for key in _REQUIRED_FRONTMATTER:
        assert re.search(rf"^{key}:", frontmatter, re.MULTILINE), (
            f"{slug}.md frontmatter is missing the required `{key}:` key "
            "(templates/feature.md shape)"
        )


@pytest.mark.parametrize("slug", _EXPECTED_FEATURES)
def test_feature_spec_has_behaviour_section(slug: str) -> None:
    """Each feature spec has the canonical ``## Behaviour`` section (AC-1)."""
    text = _feature_path(slug).read_text(encoding="utf-8")
    assert re.search(r"^## Behaviour\b", text, re.MULTILINE), (
        f"{slug}.md is missing the `## Behaviour` section — the canonical "
        "answer to 'how does it work?' (templates/feature.md)"
    )


# --- The `last_updated` value: a declared currency git can check (#280) ---


def _tracked_feature_spec_md() -> list[Path]:
    """Every tracked ``specs/features/*.md``, sorted.

    Derived from the tracked tree rather than from :data:`_EXPECTED_FEATURES`,
    so a newly added feature spec is governed by the date rule the moment it is
    committed, with no edit here (AC-3). The two subject sets answer different
    questions and deliberately stay separate: ``_EXPECTED_FEATURES`` encodes
    *these subsystems must each have a record* — a claim a derived set cannot
    make, because deriving it would let the record's absence satisfy it.
    """
    return sorted(p for p in tracked_files_under("specs/features") if p.suffix == ".md")


def _declared_last_updated(path: Path) -> date:
    """The ``last_updated`` value from ``path``'s frontmatter, as a date.

    Both failure modes assert rather than raise, so an uncustomized template
    copy (``last_updated: YYYY-MM-DD``) reports what is wrong with the file
    instead of surfacing a bare ``ValueError`` traceback.
    """
    text = path.read_text(encoding="utf-8")
    fm_match = re.match(r"^---\n(.*?)\n---\n", text, re.DOTALL)
    assert fm_match, f"{path.name} is missing the YAML frontmatter block"
    value_match = re.search(
        r"^last_updated:\s*(\S+)", fm_match.group(1), re.MULTILINE
    )
    assert value_match, (
        f"{path.name} frontmatter is missing the required `last_updated:` key "
        "(templates/feature.md shape)"
    )
    raw = value_match.group(1)
    try:
        return date.fromisoformat(raw)
    except ValueError:
        raise AssertionError(
            f"{path.name} declares `last_updated: {raw}`, which is not an "
            "ISO-8601 YYYY-MM-DD date — an uncustomized template copy or a "
            "typo. The value is read, not just required (#280)."
        ) from None


def _currency_is_current(declared: date, committed: date) -> bool:
    """Whether ``declared`` still holds against a content commit on ``committed``.

    The rule itself, in one place so the guard below and the frozen-record case
    (#463 AC-3) exercise the *same* comparison rather than two copies of it. The
    bound is ``>=`` and both operands are UTC days: :func:`last_commit_date` reads
    the commit side in UTC (#463), and ``last_updated`` is a zoneless calendar
    day. No upper bound — a date ahead of the last commit claims no false
    currency, and checking it would need a wall clock in a test.
    """
    return declared >= committed


@pytest.mark.parametrize(
    "path", _tracked_feature_spec_md(), ids=lambda p: p.name
)
def test_feature_spec_last_updated_is_not_behind_its_last_commit(
    path: Path,
) -> None:
    """A feature spec's declared currency is not older than its content (AC-2).

    ``feature_specs: true`` makes these records the contract (``CLAUDE.md``:
    *"Read the relevant as-built record before changing behaviour… It is the
    contract"*), so a frozen date is worse than no date — it actively asserts a
    currency that is false. Requiring the key without reading its value let all
    four drift; ``run-ledger.md`` alone absorbed seven changes while its date sat
    still.

    The bound is ``>=``, so a spec edited and dated today passes on the commit
    that lands it. No upper bound is asserted: a date ahead of the last commit
    claims no false currency, and checking it would need a wall clock in a test.
    """
    committed = last_commit_date(path)
    if committed is None:
        pytest.skip(
            f"git reports no commit for {path.name} — a staged-but-uncommitted "
            "spec. Nothing to compare a declared date against. A truncated "
            "history is *not* this case: it raises ShallowHistoryError, so a "
            "shallow tree goes red and named rather than silently skipping "
            "(#326)."
        )
    declared = _declared_last_updated(path)
    assert _currency_is_current(declared, committed), (
        f"specs/features/{path.name} declares last_updated: {declared} but its "
        f"last content commit is {committed}. The as-built record is the "
        "contract (feature_specs: true) — a frozen date asserts a currency that "
        f"is false. Set last_updated to the day this edit commits (>= {committed})."
    )


def test_the_last_updated_guard_covers_every_expected_feature_spec() -> None:
    """The date guard's derived subject set is not silently empty.

    A parametrized guard over a derived set passes vacuously when the set
    evaluates to nothing — a wrong pathspec, or tests run outside a checkout —
    and a vacuous pass here reads exactly like a currency it never measured.
    The floor is the records AC-1 already requires; it is a subset check, not
    equality, because the set is meant to grow.
    """
    covered = {p.stem for p in _tracked_feature_spec_md()}
    assert set(_EXPECTED_FEATURES) <= covered, (
        "the last_updated guard derives its subjects from the tracked tree, and "
        f"that set ({sorted(covered)}) is missing expected feature specs "
        f"{sorted(set(_EXPECTED_FEATURES) - covered)} — the guard would pass "
        "without measuring them"
    )


def test_a_record_dated_the_day_of_its_commit_is_current() -> None:
    """The bound is ``>=``, so the same day passes — the boundary itself (#463).

    This is the ordinary case the rule exists to permit: a record dated the day
    its own edit commits. Nothing else in the suite feeds the rule an *equal*
    pair — the parametrized guard's one subject sits a day ahead of its last
    commit, and the frozen-record case below sits a week behind — so tightening
    the bound to ``>`` survived the whole suite when review mutated it, while it
    would red every record dated on the day it shipped.

    Only the permissive direction is asserted here, deliberately: an assertion
    that some pair is *not* current would become a second killer of a widening
    to ``True``, which is the property the frozen-record case below is the sole
    witness for.
    """
    same_day = date(2026, 3, 4)
    assert _currency_is_current(same_day, same_day), (
        "a record declaring the day of its own last commit reads as stale — the "
        "bound is >=, and the same-day case is what a writer types"
    )


def _commit_spec(repo: Path, body: str, declared: str, stamp: str) -> Path:
    """Write ``spec.md`` in ``repo`` with ``declared`` currency and commit it.

    A local helper rather than a sibling-test import: the two lines of git it
    needs are cheaper here than another cross-module test dependency (#467
    tracks the missing neutral home for shared test helpers).
    """
    spec = repo / "spec.md"
    spec.write_text(
        f"---\nfeature: x\nstatus: implemented\nlast_updated: {declared}\n---\n\n"
        f"## Behaviour\n\n{body}\n",
        encoding="utf-8",
    )
    identity = ["-c", "user.email=t@example.com", "-c", "user.name=Test"]
    subprocess.run(
        ["git", *identity, "add", "spec.md"],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", *identity, "commit", "-q", "-m", "edit spec"],
        cwd=repo,
        check=True,
        capture_output=True,
        env={**os.environ, "GIT_AUTHOR_DATE": stamp, "GIT_COMMITTER_DATE": stamp},
    )
    return spec


def test_a_frozen_date_is_still_caught_after_the_utc_fix(tmp_path: Path) -> None:
    """The #280 defect this guard exists for still fires (#463 AC-3).

    Reading the commit day in UTC narrows *when* the two operands can disagree;
    it must not narrow *what the guard measures*. The original defect's shape,
    re-tested verbatim: a record whose ``last_updated`` sits still while later
    commits change the file underneath it — ``run-ledger.md`` absorbed seven such
    changes before #280 read the value at all.

    Both commits are stamped ``+00:00``, so the fix under test cannot be what
    makes this pass or fail: the frames agree at a zero offset, leaving the
    staleness itself as the only thing measured.

    It calls :func:`_currency_is_current` — the *same* comparison the guard above
    calls, not a copy of it — because a re-derived ``declared >= committed``
    written here would keep passing while the rule it claims to protect was
    widened to ``True``. This is the only case that fails on that widening: the
    parametrized guard runs over a tree whose records are current, where a rule
    that always passes and the real rule are indistinguishable.
    """
    init_repo(tmp_path)
    _commit_spec(tmp_path, "first", "2026-03-04", "2026-03-04T12:00:00+00:00")
    spec = _commit_spec(
        tmp_path, "changed, date left frozen", "2026-03-04", "2026-03-11T12:00:00+00:00"
    )

    declared = _declared_last_updated(spec)
    committed = last_commit_date("spec.md", repo_root=tmp_path)

    assert committed == date(2026, 3, 11), "the fixture's later commit did not land"
    assert not _currency_is_current(declared, committed), (
        f"a record declaring {declared} against a {committed} commit no longer "
        "reads as stale — the UTC fix widened the guard instead of re-framing it"
    )


def test_an_uncustomized_template_date_fails_with_a_readable_message(
    tmp_path: Path,
) -> None:
    """``last_updated: YYYY-MM-DD`` asserts, rather than raising ``ValueError``.

    The literal placeholder is what a spec copied from ``templates/feature.md``
    carries, so it is the most likely malformed value in practice. A bare
    ``ValueError`` traceback would not say which file or what is wrong with it.
    """
    spec = tmp_path / "placeholder.md"
    spec.write_text(
        "---\nfeature: x\nstatus: implemented\nlast_updated: YYYY-MM-DD\n"
        "---\n\n## Behaviour\n",
        encoding="utf-8",
    )
    with pytest.raises(AssertionError, match="not an ISO-8601"):
        _declared_last_updated(spec)


def test_a_missing_last_updated_key_fails_with_a_readable_message(
    tmp_path: Path,
) -> None:
    """A frontmatter block with no ``last_updated:`` line names the missing key."""
    spec = tmp_path / "keyless.md"
    spec.write_text(
        "---\nfeature: x\nstatus: implemented\n---\n\n"
        "## Behaviour\n",
        encoding="utf-8",
    )
    with pytest.raises(AssertionError, match="missing the required"):
        _declared_last_updated(spec)


#: A relative markdown link target ending in ``.md`` — e.g. ``](specs/x.md)``
#: or ``](specs/features/y.md#anchor)``. Absolute (``http``) links are skipped.
_MD_LINK = re.compile(r"\]\((?!https?://)([^)#]+\.md)(?:#[^)]*)?\)")


def test_no_dangling_links_in_the_as_built_record() -> None:
    """Relative ``.md`` links in the **live** as-built record resolve (AC-3).

    Covers ``specs/features/`` — the as-built record, which a reader is expected
    to follow. Each link is resolved relative to the file that contains it, so a
    doc moved to a deeper directory whose relative links were not re-based
    against the new depth is caught (the CAL-661 review surfaced exactly this in
    the re-homed banners).

    ``specs/retired/`` is **out of scope**, and that is a decision rather than an
    oversight. A retired spec is a frozen record of how something worked; its
    links rot the moment the tree moves past it, and the only way to keep them
    resolving is to keep editing frozen history — which corrupts the record this
    guard exists alongside. #435 made the choice concrete: retiring the
    ``/harness`` command namespace left seven retired engine docs pointing at
    ``commands/harness.md``, all of them accurate about their own era. The same
    historical-by-category exemption ``specs/retired/`` already carries in the
    retirement sweeps applies here.
    """
    records = {p for p in tracked_files_under("specs/features") if p.suffix == ".md"}
    assert records, (
        "no tracked specs/features/*.md — this guard resolves links inside a "
        "derived set, so an empty set is a vacuous pass that reads like a clean "
        "record"
    )
    dangling: list[str] = []
    for path in sorted(records):
        for target in _MD_LINK.findall(path.read_text(encoding="utf-8")):
            if not (path.parent / target).resolve().exists():
                dangling.append(f"{path.relative_to(REPO_ROOT)} -> {target}")
    assert not dangling, f"dangling relative .md links in the migrated specs: {dangling}"
