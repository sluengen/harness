"""Guard: ``docker/README.md`` records the host/container ``.venv`` clobber trap.

The host and an ``harness:dev`` container share ``<worktree>/.venv`` through the
bind mount but need **different platforms**, so whichever runs second overwrites
the other. The trap had been hit twice (tick #31, then the CAL-1140 run on
2026-07-17) while living only in one agent's memory — a fresh agent hits it cold
and burns a gate cycle rediscovering it (CAL-1152).

Same text-structural form as the documentation invariants in
``test_container_hardening.py`` (the ssh-agent key-scoping guidance) and
``test_doc_version_examples.py``: a trap that cost a gate cycle twice becomes a
permanent check, so the record cannot be quietly dropped.

The negative guard (AC-3) is the load-bearing one. ``harness review`` runs the
same image against the same cwd and is therefore a *suspect*, but has never been
observed clobbering the venv across ~30 ticks of fail→fix→re-gate. A doc that
over-claimed would teach a blanket ``rm -rf .venv`` after every review — cargo
cult built on an unproven cause — so the guard pins the honest scope, not just
the presence of prose.
"""

from __future__ import annotations

from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.parent
DOCKER_README = PROJECT_ROOT / "docker" / "README.md"


def _readme() -> str:
    return DOCKER_README.read_text()


# ---------------------------------------------------------------------------
# AC1 — the cause, the signature, the diagnostic, and the fix are all recorded
# ---------------------------------------------------------------------------


def test_readme_documents_the_venv_clobber_cause() -> None:
    """The doc names the shared bind-mounted venv and the platform collision."""
    readme = _readme()
    assert "pyvenv.cfg" in readme, (
        "docker/README.md must name pyvenv.cfg — it is the diagnostic surface "
        "that distinguishes a Linux-clobbered venv from a healthy host one."
    )
    assert "/usr/local/bin/python3" in readme, (
        "docker/README.md must name the dangling /usr/local/bin/python3 symlink "
        "— the tell-tale of a container venv left behind on an Apple Silicon host."
    )


def test_readme_documents_the_venv_clobber_signature() -> None:
    """The doc gives the precise, cheap-to-recognise failure signature.

    The count is what makes it recognisable: only the tests that spawn
    ``sys.executable`` as a subprocess fail, because the clobber can only bite a
    process started *after* it — pytest's own parent interpreter is already in
    memory. An agent seeing "5 failures, ~1880 passing" can match it instantly.
    """
    readme = _readme()
    assert "FileNotFoundError" in readme, (
        "docker/README.md must give the exact exception an agent will see."
    )
    assert "sys.executable" in readme, (
        "docker/README.md must explain that only subprocess-spawning tests fail; "
        "that is what makes the 5-failure signature recognisable rather than "
        "looking like a broad breakage."
    )


def test_readme_documents_the_venv_clobber_fix() -> None:
    """The doc gives the one-line fix: remove the venv and re-run the gate."""
    readme = _readme()
    assert "rm -rf" in readme and ".venv" in readme, (
        "docker/README.md must give the `rm -rf <worktree>/.venv` fix."
    )


# ---------------------------------------------------------------------------
# AC2 — the rule that prevents it
# ---------------------------------------------------------------------------


def test_readme_states_the_serialize_rule() -> None:
    """The doc states the preventative rule, not just the recovery."""
    readme = _readme().lower()
    assert "serial" in readme, (
        "docker/README.md must state the rule: never run a container against a "
        "worktree while a host gate runs there — serialize them."
    )


# ---------------------------------------------------------------------------
# AC3 — the claim is scoped honestly (the load-bearing guard)
# ---------------------------------------------------------------------------


def test_readme_scopes_the_review_claim_honestly() -> None:
    """``harness review`` is named as an unconfirmed suspect, not the cause.

    Both observations were of an ad-hoc, hand-run container probe. Recording
    ``harness review`` as the trigger would be inventing a cause the evidence
    does not support.
    """
    readme = _readme()
    assert "harness review" in readme, (
        "docker/README.md must address `harness review` explicitly — it runs the "
        "same image against the same cwd, so an agent will suspect it. Leaving "
        "it unmentioned invites the blanket `rm -rf .venv` this guard forbids."
    )
    lowered = readme.lower()
    assert "never been observed" in lowered or "not been observed" in lowered, (
        "docker/README.md must record that `harness review` has never been "
        "observed clobbering the venv — the honest scope of the claim."
    )


def test_readme_gives_no_blanket_rm_after_every_review_advice() -> None:
    """No cargo-cult ``rm -rf .venv`` after every review.

    The fix is keyed to the *signature*, not run prophylactically: an unproven
    cause must not become a ritual that hides the real trigger if it ever
    resurfaces.
    """
    lowered = _readme().lower()
    for phrasing in ("after every review", "after each review"):
        assert phrasing not in lowered, (
            f"docker/README.md must not advise removing the venv {phrasing!r}: "
            "`harness review` is an unconfirmed suspect, and a blanket ritual "
            "would mask the real trigger rather than fix it."
        )
