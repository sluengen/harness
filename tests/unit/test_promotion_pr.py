"""Promotion PR publication — push the gated branch and open the PR (CAL-1117).

The deterministic release-mechanics half of ``harness promote pr``: after a
promotion is ``pr_ready`` with fresh gate evidence, publish it by pushing **only**
the promotion branch and opening a PR into the target — with a title/body drawn
from deterministic facts (source/target, commit range, Linear IDs, changed specs,
gate evidence; ADR 0003 "PR authority"). This module is the analogue of
:mod:`harness.promotion_gate` (the gate executor) for the publish step:
:mod:`harness.promotion` stays git-merge-only, and the CLI (:mod:`harness.cli.promote`)
orchestrates.

The tests build a throw-away repo whose ``origin`` (a local bare repo) carries
``dev`` + ``staging``, so ``git push`` is real but offline; ``gh`` is stubbed so
no network call to GitHub happens.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from harness import promotion as mechanics
from harness import promotion_pr
from harness.promotion import PromotionMechanicsError


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=cwd, check=True, capture_output=True, text=True
    ).stdout


@pytest.fixture
def promoted(tmp_path: Path) -> dict[str, object]:
    """A repo with a real ``pr_ready`` promotion branch merged from ``dev`` → ``staging``.

    ``origin`` (a bare repo) carries ``dev`` + ``staging`` at a shared base. ``dev``
    then advances with a Linear-tagged commit touching a spec and a code file. A
    promotion branch is created from ``origin/staging`` and ``origin/dev`` merged
    into it — the same shape ``promote start`` produces — so the facts helpers have
    a real commit range to read. Returns the repo path, the promotion branch, and
    the gated (merge) SHA.
    """
    origin = tmp_path / "origin.git"
    _git(tmp_path, "init", "--bare", "-b", "dev", str(origin))

    work = tmp_path / "work"
    work.mkdir()
    _git(work, "init", "-b", "dev")
    _git(work, "config", "user.email", "test@example.com")
    _git(work, "config", "user.name", "Test")
    _git(work, "remote", "add", "origin", str(origin))
    (work / "README.md").write_text("base\n")
    _git(work, "add", ".")
    _git(work, "commit", "-m", "base")
    _git(work, "push", "-u", "origin", "dev")
    _git(work, "checkout", "-b", "staging")
    _git(work, "push", "-u", "origin", "staging")

    # dev advances: a Linear-tagged commit touching a spec + a code file.
    _git(work, "checkout", "dev")
    (work / "specs").mkdir()
    (work / "specs" / "feature.md").write_text("new feature spec\n")
    (work / "code.py").write_text("print('hi')\n")
    _git(work, "add", ".")
    _git(work, "commit", "-m", "CAL-9999: add feature spec and code")
    _git(work, "push", "origin", "dev")

    # Build the promotion branch off origin/staging, merge origin/dev into it.
    _git(work, "fetch", "origin")
    branch = "promote/2026-07-17-dev-to-staging"
    _git(work, "checkout", "-b", branch, "origin/staging")
    _git(work, "merge", "--no-ff", "origin/dev", "-m", "Merge origin/dev into promotion candidate")
    gated_sha = _git(work, "rev-parse", "HEAD").strip()
    _git(work, "checkout", "dev")
    return {"repo": work, "branch": branch, "gated_sha": gated_sha}


# --- AC-4: deterministic facts ------------------------------------------------


def test_collect_promotion_facts_reads_range_ids_and_specs(promoted: dict[str, object]) -> None:
    """The facts are read from the real commit range ``origin/<to>..gated_sha``:
    the feature commit subject, its Linear ID, and the changed spec path."""
    repo = Path(str(promoted["repo"]))
    facts = promotion_pr.collect_promotion_facts(
        repo,
        from_branch="dev",
        to_branch="staging",
        gated_sha=str(promoted["gated_sha"]),
    )
    assert facts.from_branch == "dev"
    assert facts.to_branch == "staging"
    assert any("CAL-9999" in s for s in facts.commit_subjects)
    assert facts.linear_ids == ("CAL-9999",)
    assert facts.changed_specs == ("specs/feature.md",)


def test_build_pr_title_names_the_endpoints() -> None:
    """The title is deterministic and names both endpoints."""
    facts = promotion_pr.PromotionFacts(
        from_branch="dev",
        to_branch="staging",
        gated_sha="abc1234",
        commit_subjects=("CAL-1: do a thing",),
        linear_ids=("CAL-1",),
        changed_specs=("specs/x.md",),
    )
    title = promotion_pr.build_pr_title(facts)
    assert "dev" in title
    assert "staging" in title


def test_build_pr_body_includes_every_deterministic_fact() -> None:
    """The body carries all five deterministic fact kinds: endpoints, gated SHA,
    commit subjects, Linear IDs, changed specs, and the gate evidence (AC-4)."""
    facts = promotion_pr.PromotionFacts(
        from_branch="dev",
        to_branch="staging",
        gated_sha="abc1234def",
        commit_subjects=("CAL-42: land the widget", "CAL-43: polish it"),
        linear_ids=("CAL-42", "CAL-43"),
        changed_specs=("specs/widget.md",),
    )
    body = promotion_pr.build_pr_body(facts, evidence="gate-ok\n1234 passed")
    assert "dev" in body and "staging" in body
    assert "abc1234def" in body
    assert "CAL-42: land the widget" in body
    assert "CAL-43: polish it" in body
    assert "CAL-42" in body and "CAL-43" in body
    assert "specs/widget.md" in body
    assert "gate-ok" in body


def test_build_pr_body_handles_empty_fact_lists() -> None:
    """A promotion with no feature commits/specs still renders a valid body (no
    crash on empty lists) — the sections degrade gracefully."""
    facts = promotion_pr.PromotionFacts(
        from_branch="dev",
        to_branch="staging",
        gated_sha="abc",
        commit_subjects=(),
        linear_ids=(),
        changed_specs=(),
    )
    body = promotion_pr.build_pr_body(facts, evidence=None)
    assert "dev" in body and "staging" in body
    assert "abc" in body


# --- AC-2 / AC-5: push only the promotion branch ------------------------------


def test_push_promotion_branch_pushes_only_that_branch(promoted: dict[str, object]) -> None:
    """The push publishes exactly the promotion branch to ``origin`` and never
    advances ``staging`` — the forbidden target-branch push of AC-2/AC-5."""
    repo = Path(str(promoted["repo"]))
    branch = str(promoted["branch"])

    # Record the target tips before the push so we can prove they do not move.
    staging_before = _git(repo, "rev-parse", "origin/staging").strip()
    dev_before = _git(repo, "rev-parse", "origin/dev").strip()

    promotion_pr.push_promotion_branch(repo, branch)

    # The promotion branch now exists on origin, at the gated SHA.
    pushed = _git(repo, "rev-parse", f"origin/{branch}").strip()
    assert pushed == str(promoted["gated_sha"])
    # The target branches are untouched — no direct push to staging/dev.
    assert _git(repo, "rev-parse", "origin/staging").strip() == staging_before
    assert _git(repo, "rev-parse", "origin/dev").strip() == dev_before


def test_push_promotion_branch_uses_explicit_single_ref_refspec(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The push argv names an explicit ``<branch>:<branch>`` refspec — never a bare
    ``git push`` that could advance a tracking branch, and never a target branch."""
    calls: list[tuple[str, ...]] = []

    def _fake(cwd: Path, *args: str, timeout: float | None = None):
        calls.append(args)
        return subprocess.CompletedProcess(args=["git"], returncode=0, stdout="", stderr="")

    monkeypatch.setattr(promotion_pr, "run_git", _fake)
    promotion_pr.push_promotion_branch(Path("/repo"), "promote/x")
    assert calls == [("push", "origin", "promote/x:promote/x")]


def test_push_promotion_branch_raises_on_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A non-zero push surfaces as ``PromotionMechanicsError`` (``push_failed``)."""

    def _fail(cwd: Path, *args: str, timeout: float | None = None):
        return subprocess.CompletedProcess(
            args=["git"], returncode=1, stdout="", stderr="rejected"
        )

    monkeypatch.setattr(promotion_pr, "run_git", _fail)
    with pytest.raises(PromotionMechanicsError) as exc_info:
        promotion_pr.push_promotion_branch(Path("/repo"), "promote/x")
    assert exc_info.value.reason == "push_failed"


def test_push_promotion_branch_raises_on_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A fired network timeout on the push is converted to ``push_failed`` — never a
    raw ``TimeoutExpired`` traceback (CAL-1004 convention)."""

    def _timeout(cwd: Path, *args: str, timeout: float | None = None):
        raise subprocess.TimeoutExpired(cmd="git push", timeout=timeout or 0)

    monkeypatch.setattr(promotion_pr, "run_git", _timeout)
    with pytest.raises(PromotionMechanicsError) as exc_info:
        promotion_pr.push_promotion_branch(Path("/repo"), "promote/x")
    assert exc_info.value.reason == "push_failed"


# --- AC-3: create the PR via gh -----------------------------------------------


def test_create_pull_request_invokes_gh_and_returns_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """PR creation shells out to ``gh pr create`` with the base/head/title/body and
    returns the URL ``gh`` prints (AC-3)."""
    captured: dict[str, object] = {}

    def _fake_run(argv, *, cwd, check, capture_output, text, timeout=None):
        captured["argv"] = argv
        captured["cwd"] = cwd
        return subprocess.CompletedProcess(
            args=argv,
            returncode=0,
            stdout="https://github.com/o/r/pull/7\n",
            stderr="",
        )

    monkeypatch.setattr(promotion_pr.subprocess, "run", _fake_run)
    outcome = promotion_pr.create_pull_request(
        Path("/repo"), base="staging", head="promote/x", title="T", body="B"
    )
    assert outcome.url == "https://github.com/o/r/pull/7"
    argv = captured["argv"]
    assert argv[0] == "gh"
    assert "pr" in argv and "create" in argv
    assert "--base" in argv and "staging" in argv
    assert "--head" in argv and "promote/x" in argv
    assert captured["cwd"] == Path("/repo")


def test_create_pull_request_raises_on_gh_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A non-zero ``gh`` exit surfaces as ``PromotionMechanicsError``
    (``pr_create_failed``) — the CLI reports it structurally, never a traceback."""

    def _fake_run(argv, *, cwd, check, capture_output, text, timeout=None):
        return subprocess.CompletedProcess(
            args=argv, returncode=1, stdout="", stderr="gh: not authenticated"
        )

    monkeypatch.setattr(promotion_pr.subprocess, "run", _fake_run)
    with pytest.raises(PromotionMechanicsError) as exc_info:
        promotion_pr.create_pull_request(
            Path("/repo"), base="staging", head="promote/x", title="T", body="B"
        )
    assert exc_info.value.reason == "pr_create_failed"


def test_create_pull_request_raises_when_gh_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When ``gh`` is not installed, PR creation fails cleanly as
    ``pr_create_failed`` rather than leaking a ``FileNotFoundError``."""

    def _fake_run(argv, *, cwd, check, capture_output, text, timeout=None):
        raise FileNotFoundError("gh")

    monkeypatch.setattr(promotion_pr.subprocess, "run", _fake_run)
    with pytest.raises(PromotionMechanicsError) as exc_info:
        promotion_pr.create_pull_request(
            Path("/repo"), base="staging", head="promote/x", title="T", body="B"
        )
    assert exc_info.value.reason == "pr_create_failed"


def test_module_imports_do_not_pull_in_typer() -> None:
    """The publication half is CLI-agnostic like :mod:`harness.promotion` — it owns
    git + gh only, so an orchestrator can import it without the Typer app."""
    assert not hasattr(promotion_pr, "typer")
    # Sanity: the merge mechanics module is a sibling, not a parent.
    assert mechanics.__name__ == "harness.promotion"
