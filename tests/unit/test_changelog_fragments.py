"""#267 — per-change ``changelog.d/`` fragments remove the CHANGELOG conflict class.

Every ticket appended to ``CHANGELOG.md``'s ``[Unreleased]`` block, so two
concurrent runs conflicted there **by construction** — on a file whose correct
merge semantics are "keep both lines". Run ``01KYR7T7B5E3QDC3WP7ZGYHTGV`` paid
two full rebase → gate → re-review → close rounds for it, and the class went on
to refuse a close on two further ticks. A change now writes
``changelog.d/<ticket>.md`` instead; two runs touch two different files and
never conflict.

These tests are the executable form of the acceptance criteria:

* **AC-1 — two fragments on divergent branches merge clean.** The property the
  ticket exists for, on a real two-branch git fixture. It ships with its
  **negative control**: the identical fixture with both branches appending under
  ``## [Unreleased]`` in a shared ``CHANGELOG.md`` must *conflict*. Without the
  control the merge-clean assertion passes trivially on two unrelated filenames
  and proves nothing about the design.
* **AC-2 — the fold** assembles fragments into one grouped section and empties
  the consumed files. Asserted **byte-exactly**, which pins group order, id
  ordering within a group, and verbatim body preservation in one assertion
  rather than four loose substring checks.
* **AC-3 — the presence check fails** a change carrying neither a fragment nor
  an exemption, naming ``changelog.d/`` and the exemption form.
* **AC-4 — the exemption passes.** ``### None — <why>`` is a file in the diff,
  not a flag or a commit trailer, so the reviewer sees the claim.
* **Structural validation** is table-driven over malformed fragments.
* **The abstention arms** (base unresolvable, HEAD == base) must exit 0 *and*
  print a reason. They are the easiest thing here to leave untested, and a test
  that only checked the exit code would pass on a check that had silently
  stopped working.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT / "scripts"))

import changelog_fragments as cf  # noqa: E402

# ---------------------------------------------------------------------------
# Fixtures — real git repositories, never a simulation of one.
# ---------------------------------------------------------------------------


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args], cwd=repo, check=True, capture_output=True, text=True
    )


def _git_raw(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    """Like :func:`_git` but tolerates a non-zero exit (the conflict control)."""
    return subprocess.run(
        ["git", *args], cwd=repo, check=False, capture_output=True, text=True
    )


_ADDED_270 = (
    "### Added — the widget reads its own clock (#270)\n"
    "- One sentence of body, enough to be a real entry.\n"
)
_FIXED_271 = (
    "### Fixed — the sprocket no longer double-counts (#271)\n"
    "- One sentence of body, enough to be a real entry.\n"
)
_ADDED_272 = (
    "### Added — a second addition, lower id (#272)\n- Body.\n"
)
_NONE_273 = (
    "### None — a pure test-fixture change warrants no entry (#273)\n"
    "- Body explaining why.\n"
)

#: #287 — the ticket-less exemption class. Built from the module's own constant
#: rather than the literal, so renaming the prefix cannot leave these green
#: against a guard that no longer accepts them.
_NO_TICKET = f"{cf.NO_TICKET_PREFIX}assess-2026-08-01-code"
_NONE_NO_TICKET = (
    f"### None — an advisory assessment report, no shipped behaviour ({_NO_TICKET})\n"
    "- The findings live in the tracker; nothing in the product changed.\n"
)

_UNRELEASED_HEAD = "# Changelog\n\nSee `CHANGELOG-archive/2026.md`.\n\n## [Unreleased]\n\n"


def _repo_with_base(tmp_path: Path, *, name: str = "repo") -> Path:
    """A repo on ``dev`` carrying ``changelog.d/README.md`` and a CHANGELOG."""
    repo = tmp_path / name
    repo.mkdir()
    _git(repo.parent, "init", "-q", "-b", "dev", str(repo))
    _git(repo, "config", "user.email", "t@t")
    _git(repo, "config", "user.name", "t")
    (repo / cf.FRAGMENT_DIRNAME).mkdir()
    (repo / cf.FRAGMENT_DIRNAME / cf.README_NAME).write_text(
        "Fragment format: see RELEASING.md.\n", encoding="utf-8"
    )
    (repo / "CHANGELOG.md").write_text(_UNRELEASED_HEAD, encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "base")
    return repo


def _branch_writing(repo: Path, branch: str, relpath: str, text: str) -> None:
    """Branch off ``dev``, write ``relpath``, commit, return to ``dev``."""
    _git(repo, "checkout", "-q", "-b", branch, "dev")
    target = repo / relpath
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", f"{branch}: {relpath}")
    _git(repo, "checkout", "-q", "dev")


def _branch_appending_unreleased(repo: Path, branch: str, entry: str) -> None:
    """The pre-#267 shape: append an entry under ``## [Unreleased]``."""
    _git(repo, "checkout", "-q", "-b", branch, "dev")
    changelog = repo / "CHANGELOG.md"
    changelog.write_text(
        changelog.read_text(encoding="utf-8").replace(
            "## [Unreleased]\n\n", f"## [Unreleased]\n\n{entry}\n"
        ),
        encoding="utf-8",
    )
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", f"{branch}: changelog entry")
    _git(repo, "checkout", "-q", "dev")


# ---------------------------------------------------------------------------
# AC-1 — the property this ticket exists for, and its negative control.
# ---------------------------------------------------------------------------


def test_two_fragments_on_divergent_branches_merge_clean(tmp_path: Path) -> None:
    """Two runs writing two fragments merge with no conflict."""
    repo = _repo_with_base(tmp_path)
    _branch_writing(repo, "run-a", f"{cf.FRAGMENT_DIRNAME}/270.md", _ADDED_270)
    _branch_writing(repo, "run-b", f"{cf.FRAGMENT_DIRNAME}/271.md", _FIXED_271)

    _git(repo, "checkout", "-q", "run-a")
    merged = _git_raw(repo, "merge", "--no-edit", "run-b")

    assert merged.returncode == 0, (
        "Two fragments on divergent branches must merge clean — that is the "
        f"whole point of #267.\n{merged.stdout}\n{merged.stderr}"
    )
    assert (repo / cf.FRAGMENT_DIRNAME / "270.md").read_text() == _ADDED_270
    assert (repo / cf.FRAGMENT_DIRNAME / "271.md").read_text() == _FIXED_271


def test_shared_changelog_appends_conflict_the_negative_control(tmp_path: Path) -> None:
    """The pre-#267 shape *does* conflict — so the test above is not vacuous.

    Without this control, ``test_two_fragments_...`` passes on any two unrelated
    filenames and proves nothing about the design: it would stay green even if
    the fixture could not detect a conflict at all.
    """
    repo = _repo_with_base(tmp_path)
    _branch_appending_unreleased(repo, "run-a", _ADDED_270)
    _branch_appending_unreleased(repo, "run-b", _FIXED_271)

    _git(repo, "checkout", "-q", "run-a")
    merged = _git_raw(repo, "merge", "--no-edit", "run-b")

    assert merged.returncode != 0, (
        "The pre-#267 shape (both branches appending under ## [Unreleased]) must "
        "conflict. If it merges clean here, this fixture cannot detect a "
        "conflict and the merge-clean test above is vacuous."
    )
    assert "CHANGELOG.md" in merged.stdout + merged.stderr


# ---------------------------------------------------------------------------
# AC-2 — the fold.
# ---------------------------------------------------------------------------


def _seed_fragments(repo: Path, fragments: dict[str, str]) -> None:
    directory = repo / cf.FRAGMENT_DIRNAME
    directory.mkdir(exist_ok=True)
    (directory / cf.README_NAME).write_text("pointer\n", encoding="utf-8")
    for name, text in fragments.items():
        (directory / name).write_text(text, encoding="utf-8")


def test_fold_produces_the_expected_grouped_section(tmp_path: Path) -> None:
    """The released section is byte-exact: group order, id order, verbatim bodies."""
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "CHANGELOG.md").write_text(_UNRELEASED_HEAD, encoding="utf-8")
    _seed_fragments(
        repo,
        {"270.md": _ADDED_270, "271.md": _FIXED_271, "272.md": _ADDED_272},
    )

    section = cf.fold(repo, version="0.3.0", date="2026-08-01")

    assert section == (
        "## [0.3.0] — 2026-08-01\n"
        "\n"
        f"{_ADDED_272}"
        "\n"
        f"{_ADDED_270}"
        "\n"
        f"{_FIXED_271}"
    ), (
        "The fold's output must be total and deterministic: Added before Fixed "
        "(the fixed category order), ticket id descending within a group, and "
        "each body emitted verbatim."
    )


def test_fold_empties_the_consumed_fragments_and_keeps_the_readme(
    tmp_path: Path,
) -> None:
    """AC-2's second half — consumed fragments are deleted, ``README.md`` survives."""
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "CHANGELOG.md").write_text(_UNRELEASED_HEAD, encoding="utf-8")
    _seed_fragments(repo, {"270.md": _ADDED_270, "271.md": _FIXED_271})

    cf.fold(repo, version="0.3.0", date="2026-08-01")

    remaining = sorted(p.name for p in (repo / cf.FRAGMENT_DIRNAME).iterdir())
    assert remaining == [cf.README_NAME], (
        f"The fold must delete exactly the fragments it consumed; found {remaining}."
    )


def test_fold_writes_the_section_into_the_changelog_above_unreleased(
    tmp_path: Path,
) -> None:
    """The new section lands in ``CHANGELOG.md``; the pointer and window survive."""
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "CHANGELOG.md").write_text(_UNRELEASED_HEAD, encoding="utf-8")
    _seed_fragments(repo, {"270.md": _ADDED_270})

    cf.fold(repo, version="0.3.0", date="2026-08-01", write=True)

    text = (repo / "CHANGELOG.md").read_text(encoding="utf-8")
    assert "## [0.3.0] — 2026-08-01" in text
    assert "## [Unreleased]" in text, "the unreleased heading must survive the fold"
    assert "CHANGELOG-archive/2026.md" in text, "the archive pointer must survive"
    assert text.index("## [0.3.0]") > text.index("## [Unreleased]"), (
        "the released section goes below the [Unreleased] window, which stays at "
        "the top for the next cycle"
    )


def test_fold_refuses_to_delete_through_a_symlink(tmp_path: Path) -> None:
    """The deletion set is bounded to real direct children of ``changelog.d/``.

    ``fold`` is the one genuinely destructive operation here. The enumeration is
    non-recursive, so a *plain* file is a direct child by construction — but
    ``Path.resolve()`` follows symlinks, so a link planted in the directory
    would otherwise resolve outside it and be unlinked. The containment check is
    that defence, and this is the only test that exercises it (it survived
    mutation until this test existed).
    """
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "CHANGELOG.md").write_text(_UNRELEASED_HEAD, encoding="utf-8")
    _seed_fragments(repo, {"271.md": _FIXED_271})

    outside = tmp_path / "elsewhere.md"
    outside.write_text(_ADDED_270, encoding="utf-8")
    (repo / cf.FRAGMENT_DIRNAME / "270.md").symlink_to(outside)

    with pytest.raises(cf.FoldError, match="outside"):
        cf.fold(repo, version="0.3.0", date="2026-08-01")

    assert outside.exists(), (
        "the fold must not unlink a path that resolves outside changelog.d/ — "
        "a symlink planted in the directory must be refused, not followed"
    )


def test_fold_drops_exemptions_without_emitting_them(tmp_path: Path) -> None:
    """A ``### None`` fragment is consumed and deleted, but never rendered."""
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "CHANGELOG.md").write_text(_UNRELEASED_HEAD, encoding="utf-8")
    _seed_fragments(repo, {"270.md": _ADDED_270, "273.md": _NONE_273})

    section = cf.fold(repo, version="0.3.0", date="2026-08-01")

    assert "#273" not in section and "warrants no entry" not in section, (
        "an exemption records why no entry was warranted — emitting it into the "
        "released history would defeat its purpose"
    )
    assert "#270" in section
    assert not (repo / cf.FRAGMENT_DIRNAME / "273.md").exists(), (
        "the exemption is still consumed — leaving it behind would carry it into "
        "the next release window"
    )


@pytest.mark.parametrize(
    "fragments",
    [
        pytest.param({}, id="empty-directory"),
        pytest.param({"273.md": _NONE_273}, id="only-an-exemption"),
    ],
)
def test_fold_refuses_when_there_is_nothing_to_release(
    tmp_path: Path, fragments: dict[str, str]
) -> None:
    """An empty fold is a mistake, not an empty section silently written."""
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "CHANGELOG.md").write_text(_UNRELEASED_HEAD, encoding="utf-8")
    _seed_fragments(repo, fragments)

    with pytest.raises(cf.FoldError, match="no releasable fragments"):
        cf.fold(repo, version="0.3.0", date="2026-08-01")


# ---------------------------------------------------------------------------
# AC-3 / AC-4 — the presence check on a real merge-base diff.
# ---------------------------------------------------------------------------


def _feature_branch_touching_code(repo: Path) -> None:
    _git(repo, "checkout", "-q", "-b", "run-a", "dev")
    (repo / "harness").mkdir(exist_ok=True)
    (repo / "harness" / "widget.py").write_text("x = 1\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "code change")


def test_require_fails_a_change_with_neither_fragment_nor_exemption(
    tmp_path: Path,
) -> None:
    """AC-3 — and the message must name both the path shape and the way out."""
    repo = _repo_with_base(tmp_path)
    _feature_branch_touching_code(repo)

    result = cf.require(repo, base="dev")

    assert result.exit_code != 0, (
        "a change touching code with no changelog fragment must fail the gate"
    )
    assert f"{cf.FRAGMENT_DIRNAME}/<ticket>.md" in result.message, (
        "the failure must name the path to create, not just complain"
    )
    assert "### None" in result.message, (
        "the failure must name the exemption form — otherwise an author with a "
        "genuinely entry-less change has no way past the gate but to fake an entry"
    )


def test_require_passes_a_change_carrying_a_fragment(tmp_path: Path) -> None:
    repo = _repo_with_base(tmp_path)
    _feature_branch_touching_code(repo)
    (repo / cf.FRAGMENT_DIRNAME / "270.md").write_text(_ADDED_270, encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "fragment")

    assert cf.require(repo, base="dev").exit_code == 0


def test_require_passes_a_change_carrying_an_exemption(tmp_path: Path) -> None:
    """AC-4 — the no-entry-needed path still ships."""
    repo = _repo_with_base(tmp_path)
    _feature_branch_touching_code(repo)
    (repo / cf.FRAGMENT_DIRNAME / "273.md").write_text(_NONE_273, encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "exemption")

    assert cf.require(repo, base="dev").exit_code == 0


def _feature_branch_touching(repo: Path, relpaths: list[str]) -> None:
    """A branch off ``dev`` whose commit touches exactly ``relpaths``."""
    _git(repo, "checkout", "-q", "-b", "run-ticketless", "dev")
    for relpath in relpaths:
        target = repo / relpath
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("body\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "a change with no ticket")


@pytest.mark.parametrize(
    "paths",
    [
        pytest.param(
            ["assessments/2026-08-01-code.md", "assessments/LOG.md"],
            id="assess-report",
        ),
        pytest.param(
            [
                "specs/proposals/persistent-runtime-host.md",
                "specs/decisions/0012-persistent-runtime-host.md",
            ],
            id="propose-output",
        ),
    ],
)
def test_require_states_the_exemption_for_a_ticketless_change(
    tmp_path: Path, paths: list[str]
) -> None:
    """#287 — a commit class with no ticket by design gets a *stated* path.

    Both observed instances, one test. The `/assess` report is the one the
    ticket was filed for; the `/propose` output is the second instance, and it
    is the reason the fix is stem-shaped rather than scoped to ``assessments/``
    — nothing here is keyed on a directory.

    Both guards are exercised, in the order ``scripts/verify.sh`` runs them
    (``check`` then ``require``), because the two fail this class in different
    places and neither alone reproduces it. ``check`` is the one that actually
    blocks an author who *does* write the file — it rejects the filename — while
    ``require``'s presence test is path-shape-only and has always accepted a
    ``no-ticket-*.md`` without validating the stem. So a green ``require`` here
    proves nothing on its own; the gate still fails one line earlier.

    The assertion that carries the rest of the ticket is ``not result.abstained``.
    Before this change the only way either arm reached exit 0 was the empty-diff
    abstention — i.e. by being gated at a moment where the guard could see
    nothing — which is precisely the accident #287 exists to replace.
    """
    repo = _repo_with_base(tmp_path)
    _feature_branch_touching(repo, paths)
    (repo / cf.FRAGMENT_DIRNAME / f"{_NO_TICKET}.md").write_text(
        _NONE_NO_TICKET, encoding="utf-8"
    )
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "no-ticket exemption")

    assert cf.check(repo) == [], (
        "`check` runs first in scripts/verify.sh, so it is what actually blocks "
        "an author who writes the no-ticket fragment — a green `require` behind "
        "a red `check` still leaves the gate red"
    )

    result = cf.require(repo, base="dev")

    assert result.exit_code == 0, (
        "a ticket-less change carrying a no-ticket exemption must pass the gate "
        f"before it is pushed; got {result.message!r}"
    )
    assert not result.abstained, (
        "it must pass by a stated reason, not by the empty-diff abstention — "
        "an abstention here is the accidental path the ticket exists to remove"
    )
    assert _NO_TICKET in result.message, (
        "the stated reason must name the fragment that earned it, so a reviewer "
        f"can find the claim; got {result.message!r}"
    )


def test_require_passes_a_release_fold_that_edits_the_changelog(
    tmp_path: Path,
) -> None:
    """The release fold *is* the record, so touching ``CHANGELOG.md`` satisfies it."""
    repo = _repo_with_base(tmp_path)
    _git(repo, "checkout", "-q", "-b", "release", "dev")
    changelog = repo / "CHANGELOG.md"
    changelog.write_text(
        changelog.read_text(encoding="utf-8") + "\n## [0.3.0] — 2026-08-01\n",
        encoding="utf-8",
    )
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "release fold")

    assert cf.require(repo, base="dev").exit_code == 0


# --- the abstention arms ----------------------------------------------------


def test_require_abstains_with_a_reason_when_head_is_the_base(tmp_path: Path) -> None:
    """On the integration branch there is no change to require an entry for."""
    repo = _repo_with_base(tmp_path)

    result = cf.require(repo, base="dev")

    assert result.exit_code == 0
    assert result.abstained, "HEAD == base must be an abstention, not a silent pass"
    assert "no change" in result.message.lower(), (
        f"the abstention must print why; got {result.message!r}"
    )


def test_require_abstains_with_a_reason_when_the_base_does_not_resolve(
    tmp_path: Path,
) -> None:
    """A shallow CI checkout or a detached promote worktree must not hard-fail."""
    repo = _repo_with_base(tmp_path)
    _feature_branch_touching_code(repo)

    result = cf.require(repo, base="origin/does-not-exist")

    assert result.exit_code == 0
    assert result.abstained
    assert "origin/does-not-exist" in result.message, (
        "the abstention must name the ref it could not resolve, or a "
        "misconfigured base is indistinguishable from a clean run"
    )


# ---------------------------------------------------------------------------
# Structural validation — table-driven over the ways a fragment goes wrong.
# ---------------------------------------------------------------------------


_GOOD = _ADDED_270


@pytest.mark.parametrize(
    ("name", "text", "needle"),
    [
        pytest.param("270.md", _GOOD, None, id="valid-control"),
        pytest.param(
            "not-a-ticket.md", _GOOD, "filename", id="filename-not-a-ticket-id"
        ),
        pytest.param(
            "270.md",
            "### Fix — wrong category word (#270)\n- Body.\n",
            "category",
            id="category-outside-the-closed-set",
        ),
        pytest.param(
            "270.md",
            "### Added — id disagrees with the filename (#271)\n- Body.\n",
            "271",
            id="id-mismatch-between-filename-and-heading",
        ),
        pytest.param(
            "270.md",
            "### Added — a heading and nothing else (#270)\n",
            "body",
            id="empty-body",
        ),
        pytest.param(
            "270.md",
            "### Added — smuggles a heading (#270)\n- Body.\n\n## [Injected]\n",
            "##",
            id="h2-in-body-would-split-the-released-section",
        ),
        pytest.param(
            "270.md", "- No heading at all.\n", "heading", id="no-h3-heading"
        ),
        pytest.param("CAL-1204.md", _GOOD.replace("#270", "CAL-1204"), None,
                     id="valid-legacy-linear-key"),
        # --- #287, the no-ticket exemption class -----------------------------
        pytest.param(
            f"{_NO_TICKET}.md", _NONE_NO_TICKET, None, id="valid-no-ticket-control"
        ),
        pytest.param(
            f"{_NO_TICKET}.md",
            f"### Added — a releasable entry on a no-ticket stem ({_NO_TICKET})\n"
            "- Body.\n",
            # Not the bare word "only": the *filename* message also contains it
            # ("carrying only '### None'"), so a loose needle would pass on the
            # wrong violation and prove nothing about the category rule.
            "may carry only",
            id="no-ticket-may-not-carry-a-releasable-category",
        ),
        pytest.param(
            f"{_NO_TICKET}.md",
            _NONE_NO_TICKET.replace(f"({_NO_TICKET})", f"(#{_NO_TICKET})"),
            "without '#'",
            id="no-ticket-heading-id-may-not-name-an-issue",
        ),
        pytest.param(
            f"{cf.NO_TICKET_PREFIX}Assess.md",
            _NONE_NO_TICKET.replace(_NO_TICKET, f"{cf.NO_TICKET_PREFIX}Assess"),
            "filename",
            id="no-ticket-slug-must-be-lowercase",
        ),
        # AC-3 — widening the stem class must not loosen the ticket class. Both
        # are near-misses of a *valid* stem above, so a guard that had silently
        # started accepting anything would fail here rather than pass quietly.
        pytest.param(
            "27O.md", _GOOD.replace("#270", "27O"), "filename", id="ticket-typo-letter-O"
        ),
        pytest.param(
            "cal-1204.md",
            _GOOD.replace("#270", "cal-1204"),
            "filename",
            id="ticket-key-must-stay-uppercase",
        ),
    ],
)
def test_check_validates_fragment_structure(
    tmp_path: Path, name: str, text: str, needle: str | None
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _seed_fragments(repo, {name: text})

    problems = cf.check(repo)

    if needle is None:
        assert problems == [], f"a well-formed fragment must pass; got {problems}"
    else:
        assert problems, f"{name} / {text!r} must be rejected"
        joined = "\n".join(problems)
        assert name in joined, "the problem must name the offending path"
        assert needle in joined, (
            f"the problem must explain the violation (expected {needle!r} in "
            f"{joined!r})"
        )


def test_check_ignores_the_readme_pointer(tmp_path: Path) -> None:
    """A directory needs a tracked file to exist in git; it is not a fragment."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _seed_fragments(repo, {})

    assert cf.check(repo) == []


def test_check_passes_on_the_real_repository() -> None:
    """The live ``changelog.d/`` is well-formed — this is what the gate runs."""
    assert cf.check(_REPO_ROOT) == []


def test_a_resumed_run_overwrites_rather_than_duplicating(tmp_path: Path) -> None:
    """The filename is the primary key, so re-writing is idempotent by construction."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _seed_fragments(repo, {"270.md": _ADDED_270})
    (repo / cf.FRAGMENT_DIRNAME / "270.md").write_text(
        _ADDED_270.replace("a real entry.", "a real entry, revised."),
        encoding="utf-8",
    )

    fragments = cf.fragments(repo)

    assert [f.ticket for f in fragments] == ["270"], (
        "a resumed run rewrites the same path — the filename is the primary key, "
        "so there can be no second fragment for the ticket to duplicate it"
    )
    assert "revised" in fragments[0].body, "the rewrite must win, not the original"
