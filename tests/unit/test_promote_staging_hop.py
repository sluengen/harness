"""CAL-1158 — the staging hop direct-pushes; the release hop stays PR-only.

ADR 0003 originally forbade direct target-branch pushes on **both** promotion
hops, which foreclosed the nightly ``dev → staging`` automation: a cron would
gate the candidate, open a PR into staging, and stop — waiting for a human to
merge a PR nobody reads. The 2026-07-17 amendment scopes that rule to the
**release** hop, on the distinction that **staging is derived and main is
decided**: nothing is judged at the staging hop (the gate *is* the decision), so
``promote pr`` lands it directly; ``staging → main`` still opens a PR, the single
human decision point.

These are the CLI-level behaviour tests over a real throw-away repo whose
``origin`` carries ``dev`` + ``staging`` + ``main``, so every push is real but
offline (``gh`` is stubbed — no GitHub call). The publication *mechanics* are
tested in ``test_promotion_pr.py``; this module tests which path ``promote pr``
takes for each hop:

* **AC-1** — a green ``dev → staging`` promotion pushes ``staging`` and opens no PR.
* **AC-2** — a red ``dev → staging`` gate does not push ``staging``.
* **AC-3** — a green ``staging → main`` promotion opens a PR and never pushes ``main``.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
from typer.testing import CliRunner

from harness.cli import app
from harness.cli import promote as promote_cli
from harness.promotion_pr import PullRequestOutcome

cli_runner = CliRunner()


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=cwd, check=True, capture_output=True, text=True
    ).stdout


@pytest.fixture(autouse=True)
def _allow_tmp_workspace(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Permit the tmp tree through the ``HARNESS_WORKSPACE_ROOTS`` gate (CAL-584)."""
    monkeypatch.setenv("HARNESS_WORKSPACE_ROOTS", str(tmp_path))


def _gate_config(script: str) -> str:
    """A minimal ``CONTEXT.md`` whose ``verify:`` gate runs ``script``."""
    return f"```yaml\ncommands:\n  verify: \"{script}\"\n```\n"


@pytest.fixture
def work(tmp_path: Path) -> Path:
    """A work repo whose ``origin`` (a local bare repo) carries the full topology.

    ``dev`` / ``staging`` / ``main`` all branch from one shared ``base`` commit —
    the three-tier ``dev → staging → main`` topology of ADR 0003 — so both hops are
    exercisable. The base carries a **green** ``verify:`` gate, so every branch
    inherits one and a promotion candidate off any hop gates green by default;
    :func:`_set_gate` overrides it per branch. (The gate is read from the *merged*
    worktree's CONTEXT.md, so a config on ``dev`` alone would leave a
    ``staging → main`` candidate ungated — it would land in ``opened``, not
    ``pr_ready``.) Left checked out on ``dev``.
    """
    origin = tmp_path / "origin.git"
    _git(tmp_path, "init", "--bare", "-b", "dev", str(origin))

    work = tmp_path / "work"
    work.mkdir()
    _git(work, "init", "-b", "dev")
    _git(work, "config", "user.email", "test@example.com")
    _git(work, "config", "user.name", "Test")
    _git(work, "remote", "add", "origin", str(origin))
    (work / ".gitignore").write_text(".harness/\n.worktrees/\n")
    (work / "README.md").write_text("base\n")
    (work / "CONTEXT.md").write_text(_gate_config("exit 0"))
    _git(work, "add", ".")
    _git(work, "commit", "-m", "base")
    _git(work, "push", "-u", "origin", "dev")
    for branch in ("staging", "main"):
        _git(work, "checkout", "-b", branch)
        _git(work, "push", "-u", "origin", branch)
    _git(work, "checkout", "dev")
    return work


def _set_gate(work: Path, branch: str, script: str) -> None:
    """Override ``branch``'s ``verify:`` gate to run ``script``, and push it.

    The candidate merges the source branch in, so the source's CONTEXT.md wins over
    the base copy the target still carries — that is how a red source gate reaches
    the merged candidate.
    """
    _git(work, "checkout", branch)
    (work / "CONTEXT.md").write_text(_gate_config(script))
    _git(work, "add", "CONTEXT.md")
    _git(work, "commit", "-m", f"configure the {branch} verify gate")
    _git(work, "push", "origin", branch)
    _git(work, "checkout", "dev")


def _advance(work: Path, branch: str, path: str, content: str, msg: str) -> None:
    """Commit ``content`` at ``path`` on ``branch`` and push it; return to ``dev``."""
    _git(work, "checkout", branch)
    target = work / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content)
    _git(work, "add", path)
    _git(work, "commit", "-m", msg)
    _git(work, "push", "origin", branch)
    _git(work, "checkout", "dev")


def _start(work: Path, *args: str) -> object:
    return cli_runner.invoke(app, ["promote", "start", "--repo", str(work), *args])


def _pr(work: Path, promotion_id: str) -> object:
    return cli_runner.invoke(
        app, ["promote", "pr", "--promotion-id", promotion_id, "--repo", str(work)]
    )


def _fail_if_called(*args: object, **kwargs: object) -> PullRequestOutcome:
    """A ``create_pull_request`` stub that fails the test if the PR path is taken."""
    raise AssertionError("the staging hop must not open a PR (AC-1)")


# --- AC-1: a green staging hop lands directly, with no PR ---------------------


def test_green_staging_promotion_pushes_staging_and_opens_no_pr(
    work: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AC-1 — a gate-green ``dev → staging`` promotion advances ``staging`` itself
    to the gated SHA and opens **no** PR, reaching the terminal ``promoted`` state.

    This is the whole point of the amendment: the nightly promotion completes
    without a human, so ``create_pull_request`` must never be called.
    """
    _advance(work, "dev", "feature.txt", "shipped\n", "CAL-1158: add feature on dev")
    started = json.loads(_start(work, "--from", "dev", "--to", "staging").output)
    assert started["status"] == "pr_ready", started
    gated_sha = str(started["gated_sha"])

    monkeypatch.setattr(promote_cli, "create_pull_request", _fail_if_called)

    result = _pr(work, str(started["promotion_id"]))
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)

    # The promotion landed: staging now *is* the gated candidate, and no PR exists.
    assert payload["status"] == "promoted"
    assert payload["pr_url"] is None
    _git(work, "fetch", "origin")
    assert _git(work, "rev-parse", "origin/staging").strip() == gated_sha


# --- AC-2: a red gate never pushes staging -----------------------------------


def test_red_gate_staging_promotion_does_not_push_staging(
    work: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AC-2 — a failing gate must not advance ``staging``.

    The red gate never reaches ``pr_ready``, so ``promote pr`` is refused by the
    existing PR gate and the target branch stays exactly where it was. Direct-push
    authority is bounded by the gate, not merely by the caller's good behaviour.
    """
    _set_gate(work, "dev", "exit 1")
    _advance(work, "dev", "feature.txt", "broken\n", "CAL-1158: add failing feature")
    staging_before = _git(work, "rev-parse", "origin/staging").strip()

    started = json.loads(_start(work, "--from", "dev", "--to", "staging").output)
    assert started["status"] != "pr_ready", started
    assert started["gated_sha"] is None

    monkeypatch.setattr(promote_cli, "create_pull_request", _fail_if_called)
    result = _pr(work, str(started["promotion_id"]))

    assert result.exit_code == 2, result.output
    assert json.loads(result.output)["reason"] == "gate_not_satisfied"
    _git(work, "fetch", "origin")
    assert _git(work, "rev-parse", "origin/staging").strip() == staging_before


# --- AC-3: the release hop still opens a PR and never pushes main -------------


def test_green_main_promotion_opens_a_pr_and_never_pushes_main(
    work: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AC-3 — a green ``staging → main`` promotion still opens a PR into ``main``
    and leaves ``main`` untouched: the rule is *scoped*, not deleted.

    ``main`` is the single human decision point, so the release hop must behave
    exactly as it did before the amendment.
    """
    _advance(work, "staging", "feature.txt", "candidate\n", "CAL-1158: stage a feature")
    main_before = _git(work, "rev-parse", "origin/main").strip()

    started = json.loads(_start(work, "--from", "staging", "--to", "main").output)
    assert started["status"] == "pr_ready", started
    branch = str(started["promotion_branch"])

    captured: dict[str, object] = {}

    def _fake_create(repo_root: Path, *, base: str, head: str, title: str, body: str):
        captured.update(base=base, head=head)
        return PullRequestOutcome(url="https://github.com/o/r/pull/99")

    monkeypatch.setattr(promote_cli, "create_pull_request", _fake_create)

    result = _pr(work, str(started["promotion_id"]))
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)

    # The PR opened into main from the promotion branch — the unchanged behaviour.
    assert payload["status"] == "pr_opened"
    assert payload["pr_url"] == "https://github.com/o/r/pull/99"
    assert captured["base"] == "main"
    assert captured["head"] == branch

    # main did not move; the promotion branch was published for the PR to target.
    _git(work, "fetch", "origin")
    assert _git(work, "rev-parse", "origin/main").strip() == main_before
    assert f"origin/{branch}" in _git(work, "branch", "-r")
