"""Guard: the credential contract the wrapper is responsible for (CAL-941, #170).

**Retargeted by #305 — the deliberate contract change AC-3 anticipates.** Until
then every test here was a *text* guard over ``docker/harness-wrapper.sh``:
``assert "expiresAt" in text``, ``assert "gh auth token" in text``. #305 moved that
logic into ``harness.hostenv``, so those assertions would now be asserting the
presence of exactly what AC-2 requires to be absent. A text guard over shell that no
longer holds the logic cannot survive the port in its old form.

Where each assertion went:

- ``expiresAt`` is read → ``test_hostenv_credentials.py::test_parse_credential_store_*``
- a stale token triggers a refresh →
  ``test_hostenv_credentials.py::test_a_stale_credential_is_refreshed_and_the_fresh_value_read_back``
- the refresh is bounded →
  ``test_hostenv_credentials.py::test_a_failed_or_hung_refresh_leaves_the_stale_token_usable``
- the ``gh auth token`` fallback → ``test_hostenv_credentials.py::test_gh_is_the_last_resort_*``
- the ``|| true`` grep guard (#171) →
  ``test_hostenv_credentials.py::test_a_dotenv_missing_the_key_yields_an_empty_value_not_an_abort``
- ``-e CLAUDE_CODE_OAUTH_EXPIRES_AT`` and ``-e GITHUB_TOKEN`` → **stay here**, but
  retargeted again by #307: the shim no longer owns the ``docker run`` argv either.
  It execs ``harness.hostenv.client``, and the argv is built by
  ``harness.hostenv.spawn.build_docker_argv``. So these tests now assert over the
  **constructed argv** rather than over shell text — a behavioural assertion where
  there used to be a substring search, which is strictly the stronger form. The
  properties are unchanged; only the thing they are read off has moved.

**What was genuinely lost, named rather than quietly dropped:** the old
``test_env_credential_grep_is_guarded_against_a_missing_key`` executed a guarded and
an unguarded ``grep`` under ``set -euo pipefail`` and proved the ``|| true`` was what
prevented the abort. There is no shell code left to prove that about. The property it
protected — a ``.env`` missing a key must not stop resolution — is now structural in
the parser and is covered behaviourally above, but the adversarial *shell* proof has
no successor and is not claimed to have one.

What remains here is the credential-forwarding contract itself, wherever it is
implemented — the one thing that must hold across both ports.
"""

from __future__ import annotations

import re
from pathlib import Path

from harness.hostenv import spawn
from harness.hostenv.client import FORWARDED_ENV_NAMES

PROJECT_ROOT = Path(__file__).parent.parent.parent
DOCKER_WRAPPER = PROJECT_ROOT / "docker" / "harness-wrapper.sh"


def _wrapper() -> str:
    return DOCKER_WRAPPER.read_text()


def _docker_run_block() -> str:
    """The verb container's real ``docker run`` argv, rendered for substring reads.

    Built rather than parsed out of the wrapper (#307): construction moved into
    ``harness.hostenv.spawn``, so this reads the argv the container is actually
    given. ``FORWARDED_ENV_NAMES`` is passed rather than a literal list, so a
    credential silently dropped from the forwarding set fails here too.
    """
    argv = spawn.build_docker_argv(
        repo=Path("/work/repo"),
        argv=["status", "R1"],
        image="harness:dev",
        env_names=FORWARDED_ENV_NAMES,
        home=Path("/home/op"),
        git_identity={},
    )
    return " ".join(argv)


def test_wrapper_forwards_the_token_and_its_expiry_into_the_container() -> None:
    """Both are forwarded so ``harness doctor`` can flag a stale token, rather than
    the staleness surfacing as a false ``review`` failure (CAL-941)."""
    block = _docker_run_block()

    assert "-e CLAUDE_CODE_OAUTH_TOKEN" in block
    assert "-e CLAUDE_CODE_OAUTH_EXPIRES_AT" in block


def test_wrapper_forwards_the_tracker_credentials() -> None:
    """A ``tracker: github`` repo authenticates in-container exactly as a
    ``tracker: linear`` one does (CAL-1105)."""
    block = _docker_run_block()

    assert "-e GITHUB_TOKEN" in block
    assert "-e LINEAR_API_KEY" in block


def test_secrets_cross_by_name_never_as_a_key_value_pair() -> None:
    """``-e SECRET`` inherits the value from the environment; ``-e SECRET=value``
    puts it in the container's argv, where ``ps`` can read it.

    This is the one property of the forwarding that is a security boundary rather
    than a convenience, and the port must not have relaxed it.
    """
    block = _docker_run_block()

    for secret in ("CLAUDE_CODE_OAUTH_TOKEN", "GITHUB_TOKEN", "LINEAR_API_KEY"):
        assert not re.search(rf"-e\s+{secret}=", block), (
            f"{secret} must be forwarded by name (`-e {secret}`), never as "
            f"`-e {secret}=value` — the latter puts the credential in the "
            f"container's argv where `ps` can read it"
        )


def test_the_commit_identity_still_reaches_the_container() -> None:
    """Resolution moved to ``harness.hostenv``; forwarding did not.

    These values are non-secret, so the ``-e K=V`` form is correct here — and it also
    keeps a default in reach for the degraded path where no identity was resolved,
    which is what the empty ``git_identity`` above exercises.
    """
    block = _docker_run_block()

    for key in ("GIT_AUTHOR_NAME", "GIT_AUTHOR_EMAIL", "GIT_COMMITTER_NAME", "GIT_COMMITTER_EMAIL"):
        assert f"-e {key}=" in block, f"{key} must still be forwarded"

    assert "Harness" in block and "harness@local" in block, (
        "the degraded path must still forward a usable identity default"
    )


def test_wrapper_no_longer_claims_it_always_fetches_fresh() -> None:
    """The stale note that *claimed* per-invocation freshness (the original bug)."""
    text = _wrapper()

    assert "fetches\na fresh token on every invocation" not in text
    assert "fetches a fresh token on every invocation" not in text
