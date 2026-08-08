"""Contract guard for the deterministic nightly ``dev → staging`` promotion."""

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "nightly-staging-promotion.yml"


def test_nightly_promotion_workflow_is_a_bounded_deterministic_staging_hop() -> None:
    """The scheduler gates a candidate and never contains an automated repair path."""
    assert WORKFLOW.is_file(), "the nightly dev-to-staging promotion workflow must exist (#378)"
    workflow = WORKFLOW.read_text(encoding="utf-8")

    assert 'cron: "0 14 * * *"' in workflow, "14:00 UTC is midnight in Australia/Brisbane"
    assert "workflow_dispatch:" in workflow
    assert "nightly-dev-to-staging" in workflow
    assert "cancel-in-progress: false" in workflow
    assert "contents: write" in workflow
    assert "fetch-depth: 0" in workflow
    assert "harness promote start --repo . --from dev --to staging" in workflow
    assert "git config user.name" in workflow and "git config user.email" in workflow
    assert 'if [ "$status" != "gate_pending" ]' in workflow
    assert 'cd "$worktree"' in workflow and "bash scripts/verify.sh" in workflow
    assert "harness promote continue --repo ." in workflow
    assert 'if [ "$status" != "pr_ready" ]' in workflow
    assert "harness promote pr --repo ." in workflow
    assert "git push" not in workflow
    assert "agent_may_fix" not in workflow
