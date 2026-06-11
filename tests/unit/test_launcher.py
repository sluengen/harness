"""Unit tests for :mod:`harness.launcher` — the host launcher / narrow control
socket (CAL-579).

The launcher's whole purpose is the load-bearing property from
``specs/hermes-orchestration.md`` §Runtime topology: *the caller never specifies
the mount, the image, the privilege, or the env* — it says "run verb X on repo
Y" and the launcher constructs the ``docker run`` server-side. These tests
exercise that construction (``build_verb_argv``) and the request dispatch in
isolation, with no real docker: the runner is injected.

Coverage maps to the ticket's acceptance criteria:

* AC-2 — a caller cannot influence the verb container's mounts, image,
  privilege, or env (``test_*caller*`` + the argv-shape assertions).
* AC-3 — mounts are restricted to ``HARNESS_WORKSPACE_ROOTS`` (``test_repo_*``).
* AC-4 — the verb container is a one-shot sibling, removed on exit
  (``test_argv_is_one_shot_*``).
* AC-5 — only the named verb operations are exposed (``test_*unknown*`` +
  ``test_operations_surface_is_exactly``).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from harness.launcher import (
    INJECTED_ENV,
    OPERATIONS,
    ControlServer,
    LauncherError,
    RunResult,
    build_verb_argv,
)
from harness.workspace import WORKSPACE_ROOTS_ENV

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """An allowed repo directory under a workspace root."""
    r = tmp_path / "work" / "repo"
    r.mkdir(parents=True)
    return r


@pytest.fixture
def roots(tmp_path: Path) -> list[Path]:
    """The configured allowlist: ``tmp_path/work``."""
    return [(tmp_path / "work").resolve()]


def _argv(op: str, params: dict[str, str], roots: list[Path], **kw: object) -> list[str]:
    image = str(kw.get("image", "harness:dev"))
    host_env = kw.get("host_env", {})
    assert isinstance(host_env, dict)
    return build_verb_argv(
        {"op": op, "params": params},
        image=image,
        roots=roots,
        host_env=host_env,
    )


# ---------------------------------------------------------------------------
# The operation surface (AC-5)
# ---------------------------------------------------------------------------


def test_operations_surface_is_exactly_the_named_verbs() -> None:
    assert (
        frozenset({"start", "review", "close", "status", "events", "cancel", "decision"})
        == OPERATIONS
    )


@pytest.mark.parametrize("op", ["run", "exec", "build", "commit", "shell", "", "RUN"])
def test_unknown_operation_is_rejected(op: str, repo: Path, roots: list[Path]) -> None:
    with pytest.raises(LauncherError) as excinfo:
        _argv(op, {"repo": str(repo), "run_id": "R1"}, roots)
    assert excinfo.value.reason == "unknown_operation"


@pytest.mark.parametrize("op", sorted(OPERATIONS))
def test_every_named_operation_builds_an_argv(op: str, repo: Path, roots: list[Path]) -> None:
    # Pass only the keys each op accepts (a superset would be rejected), so use
    # the op's own required set via ``_params_for``.
    argv = build_verb_argv(
        {"op": op, "params": _params_for(op, repo)},
        image="harness:dev",
        roots=roots,
        host_env={},
    )
    assert argv[:3] == ["docker", "run", "--rm"]
    # The harness verb name is the first token after the image.
    assert op in argv


def _params_for(op: str, repo: Path) -> dict[str, str]:
    base = {"repo": str(repo)}
    if op == "start":
        return {**base, "ticket": "CAL-1"}
    if op == "decision":
        return {**base, "run_id": "R1", "value": "approve"}
    if op == "close":
        return {**base, "run_id": "R1", "ticket": "CAL-1"}
    return {**base, "run_id": "R1"}


# ---------------------------------------------------------------------------
# One-shot sibling lifecycle (AC-4)
# ---------------------------------------------------------------------------


def test_argv_is_one_shot_and_unprivileged(repo: Path, roots: list[Path]) -> None:
    argv = _argv("start", {"repo": str(repo), "ticket": "CAL-1"}, roots)
    # `docker run --rm` => a one-shot sibling removed on exit.
    assert argv[0] == "docker"
    assert argv[1] == "run"
    assert "--rm" in argv
    # No privilege escalation, no nested daemon, no host-root mount.
    assert "--privileged" not in argv
    assert "--privileged=true" not in argv
    assert not any(tok.startswith("/:") or tok == "/:/host" for tok in argv)
    assert "/var/run/docker.sock" not in " ".join(argv)


def test_argv_mounts_repo_at_identical_path(repo: Path, roots: list[Path]) -> None:
    argv = _argv("start", {"repo": str(repo), "ticket": "CAL-1"}, roots)
    resolved = str(repo.resolve())
    # Path equivalence: the bind source and target are the same absolute path.
    assert "-v" in argv
    v_idx = argv.index("-v")
    assert argv[v_idx + 1] == f"{resolved}:{resolved}"
    # Working dir is that same path, and the verb's own allowlist is scoped to it.
    w_idx = argv.index("-w")
    assert argv[w_idx + 1] == resolved
    assert f"{WORKSPACE_ROOTS_ENV}={resolved}" in argv


# ---------------------------------------------------------------------------
# The caller cannot influence mount / image / privilege / env (AC-2)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "rogue",
    [
        {"privileged": "true"},
        {"volumes": "/:/host"},
        {"mounts": "/etc:/etc"},
        {"image": "evil:latest"},
        {"env": "AWS_SECRET=1"},
        {"network": "host"},
        {"entrypoint": "/bin/sh"},
        {"user": "0:0"},
    ],
)
def test_rogue_params_are_rejected(rogue: dict[str, str], repo: Path, roots: list[Path]) -> None:
    params = {"repo": str(repo), "ticket": "CAL-1", **rogue}
    with pytest.raises(LauncherError) as excinfo:
        _argv("start", params, roots)
    assert excinfo.value.reason == "bad_params"


# ---------------------------------------------------------------------------
# Launcher-controlled credential mounts (review codex + close ssh push)
# ---------------------------------------------------------------------------


def test_verb_container_mounts_launcher_credentials(
    repo: Path, roots: list[Path], tmp_path: Path
) -> None:
    # The launcher mounts its own ~/.codex (review's codex auth) and ~/.ssh
    # (close's push) into every verb container — the same surface the
    # ~/bin/harness wrapper supplies, so launcher-spawned verbs can authenticate.
    home = tmp_path / "home"
    home.mkdir()
    argv = build_verb_argv(
        {"op": "review", "params": {"repo": str(repo), "run_id": "R1"}},
        image="harness:dev",
        roots=roots,
        host_env={},
        home=home,
    )
    assert f"{home / '.codex'}:/root/.codex" in argv
    assert f"{home / '.ssh'}:/root/.ssh:ro" in argv
    # The repo mount is still first, so the path-equivalence assertions hold.
    assert argv[argv.index("-v") + 1] == f"{repo.resolve()}:{repo.resolve()}"


def test_credentials_come_from_launcher_home_not_a_caller_param(
    repo: Path, roots: list[Path], tmp_path: Path
) -> None:
    # There is no param through which a caller can change the credential mount;
    # supplying one is a bad_params refusal, and the mount tracks the launcher's
    # home regardless.
    home = tmp_path / "home"
    home.mkdir()
    with pytest.raises(LauncherError) as excinfo:
        build_verb_argv(
            {"op": "review", "params": {"repo": str(repo), "run_id": "R1", "codex": "/evil"}},
            image="harness:dev",
            roots=roots,
            host_env={},
            home=home,
        )
    assert excinfo.value.reason == "bad_params"


def test_ssh_agent_forwarded_when_socket_available(
    repo: Path, roots: list[Path], tmp_path: Path
) -> None:
    home = tmp_path / "home"
    home.mkdir()
    argv = build_verb_argv(
        {"op": "close", "params": {"repo": str(repo), "run_id": "R1", "ticket": "CAL-1"}},
        image="harness:dev",
        roots=roots,
        host_env={},
        home=home,
        ssh_auth_sock="/run/host-services/ssh-auth.sock",
    )
    assert "/run/host-services/ssh-auth.sock:/ssh-agent" in argv
    assert "SSH_AUTH_SOCK=/ssh-agent" in argv


def test_ssh_agent_absent_when_no_socket(
    repo: Path, roots: list[Path], tmp_path: Path
) -> None:
    home = tmp_path / "home"
    home.mkdir()
    argv = build_verb_argv(
        {"op": "close", "params": {"repo": str(repo), "run_id": "R1", "ticket": "CAL-1"}},
        image="harness:dev",
        roots=roots,
        host_env={},
        home=home,
        ssh_auth_sock=None,
    )
    assert not any("ssh-agent" in tok for tok in argv)
    assert "SSH_AUTH_SOCK=/ssh-agent" not in argv


def test_caller_image_string_never_reaches_argv(repo: Path, roots: list[Path]) -> None:
    # Even though `image` is rejected as a param, prove the constructed image is
    # the launcher's, not anything the caller could smuggle.
    argv = _argv("start", {"repo": str(repo), "ticket": "CAL-1"}, roots, image="harness:pinned")
    assert "harness:pinned" in argv
    assert "evil:latest" not in argv


def test_caller_controlled_tokens_only_appear_after_the_image(
    repo: Path, roots: list[Path]
) -> None:
    # A ticket string that *looks* like a docker flag must not be interpreted as
    # one: everything the caller supplies lands after the image, i.e. as args to
    # the harness verb, never as `docker run` options.
    argv = _argv("start", {"repo": str(repo), "ticket": "--privileged"}, roots, image="harness:dev")
    image_idx = argv.index("harness:dev")
    assert "--privileged" in argv[image_idx + 1 :]
    assert "--privileged" not in argv[: image_idx + 1]


def test_caller_cannot_set_env_no_env_param(repo: Path, roots: list[Path]) -> None:
    # There is no env param; a caller attempt to add one is rejected outright.
    with pytest.raises(LauncherError) as excinfo:
        _argv("start", {"repo": str(repo), "ticket": "CAL-1", "SECRET": "x"}, roots)
    assert excinfo.value.reason == "bad_params"


def test_launcher_injects_scoped_credentials_from_its_own_env(
    repo: Path, roots: list[Path]
) -> None:
    # The launcher injects per-run secrets by *name* (value pulled from the
    # launcher's own environment by docker), so the secret never lands in argv.
    host_env = dict.fromkeys(INJECTED_ENV, "secret-value")
    argv = _argv("start", {"repo": str(repo), "ticket": "CAL-1"}, roots, host_env=host_env)
    for name in INJECTED_ENV:
        assert "-e" in argv
        assert name in argv
        # `-e NAME` form, not `-e NAME=value` — the secret value is not in argv.
        assert "secret-value" not in " ".join(argv)


def test_injected_credentials_absent_when_not_in_launcher_env(
    repo: Path, roots: list[Path]
) -> None:
    argv = _argv("start", {"repo": str(repo), "ticket": "CAL-1"}, roots, host_env={})
    for name in INJECTED_ENV:
        assert name not in argv


# ---------------------------------------------------------------------------
# Mount restricted to HARNESS_WORKSPACE_ROOTS (AC-3)
# ---------------------------------------------------------------------------


def test_repo_outside_allowlist_is_rejected(tmp_path: Path, roots: list[Path]) -> None:
    outside = tmp_path / "elsewhere"
    outside.mkdir()
    with pytest.raises(LauncherError) as excinfo:
        _argv("start", {"repo": str(outside), "ticket": "CAL-1"}, roots)
    assert excinfo.value.reason == "repo_not_allowed"


def test_repo_root_filesystem_is_rejected(roots: list[Path]) -> None:
    with pytest.raises(LauncherError) as excinfo:
        _argv("start", {"repo": "/", "ticket": "CAL-1"}, roots)
    assert excinfo.value.reason == "repo_not_allowed"


def test_repo_empty_allowlist_fails_closed(repo: Path) -> None:
    with pytest.raises(LauncherError) as excinfo:
        _argv("start", {"repo": str(repo), "ticket": "CAL-1"}, [])
    assert excinfo.value.reason == "repo_not_allowed"


def test_repo_with_colon_is_rejected_no_mount_injection(tmp_path: Path) -> None:
    # A ``:`` is a legal path char that passes ``resolve()`` + the allowlist, but
    # it is the ``-v src:dst[:opts]`` separator. A path like ``…/r:/etc:cached``
    # would let the caller inject the mount *destination* into ``docker run -v``.
    # It must be rejected (the load-bearing "caller never specifies the mount").
    root = tmp_path / "work"
    evil = root / "r:" / "etc:cached"
    evil.mkdir(parents=True)
    roots = [root.resolve()]
    with pytest.raises(LauncherError) as excinfo:
        _argv("start", {"repo": str(evil), "ticket": "CAL-1"}, roots)
    assert excinfo.value.reason == "repo_not_allowed"


def test_no_argv_token_carries_a_caller_injected_mount_destination(tmp_path: Path) -> None:
    # Defence-in-depth assertion of the property itself: for any accepted repo,
    # the only ``:`` in the whole argv is the single one inside the ``-v`` bind
    # spec, and it splits that spec into two identical halves (src == dst). No
    # caller value can add a second ``:``-delimited field.
    root = tmp_path / "work"
    repo = root / "repo"
    repo.mkdir(parents=True)
    argv = _argv("start", {"repo": str(repo), "ticket": "CAL-1"}, [root.resolve()])
    v_idx = argv.index("-v")
    bind = argv[v_idx + 1]
    assert bind.count(":") == 1
    src, dst = bind.split(":")
    assert src == dst == str(repo.resolve())


def test_repo_dotdot_escape_is_rejected(tmp_path: Path, roots: list[Path]) -> None:
    escaping = tmp_path / "work" / "repo" / ".." / ".." / "secret"
    (tmp_path / "secret").mkdir()
    with pytest.raises(LauncherError) as excinfo:
        _argv("start", {"repo": str(escaping), "ticket": "CAL-1"}, roots)
    assert excinfo.value.reason == "repo_not_allowed"


# ---------------------------------------------------------------------------
# Required / typed params
# ---------------------------------------------------------------------------


def test_missing_required_param_is_rejected(repo: Path, roots: list[Path]) -> None:
    with pytest.raises(LauncherError) as excinfo:
        _argv("start", {"repo": str(repo)}, roots)  # no ticket
    assert excinfo.value.reason == "bad_params"


def test_non_string_param_is_rejected(repo: Path, roots: list[Path]) -> None:
    with pytest.raises(LauncherError) as excinfo:
        build_verb_argv(
            {"op": "start", "params": {"repo": str(repo), "ticket": ["CAL-1"]}},
            image="harness:dev",
            roots=roots,
            host_env={},
        )
    assert excinfo.value.reason == "bad_params"


def test_params_must_be_an_object(repo: Path, roots: list[Path]) -> None:
    with pytest.raises(LauncherError) as excinfo:
        build_verb_argv(
            {"op": "start", "params": "not-an-object"},
            image="harness:dev",
            roots=roots,
            host_env={},
        )
    assert excinfo.value.reason == "bad_params"


# ---------------------------------------------------------------------------
# Per-op verb command mapping
# ---------------------------------------------------------------------------


def test_start_maps_to_start_verb_with_repo_and_base(repo: Path, roots: list[Path]) -> None:
    argv = _argv("start", {"repo": str(repo), "ticket": "CAL-1", "base": "dev"}, roots)
    resolved = str(repo.resolve())
    tail = argv[argv.index("harness:dev") + 1 :]
    assert tail == ["start", "CAL-1", "--repo", resolved, "--base", "dev"]


def test_review_maps_to_review_verb_bound_to_run(repo: Path, roots: list[Path]) -> None:
    # AC-1: review is spawnable through the narrow socket as a one-shot sibling,
    # bound to the run by --run-id (the run's worktree HEAD is what it reviews).
    argv = _argv("review", {"repo": str(repo), "run_id": "R1"}, roots)
    resolved = str(repo.resolve())
    tail = argv[argv.index("harness:dev") + 1 :]
    assert tail == ["review", "--run-id", "R1", "--repo", resolved]


def test_close_maps_to_close_verb_with_ticket_and_run(repo: Path, roots: list[Path]) -> None:
    # AC-1: close is spawnable through the narrow socket; the gate runs inside
    # the verb container, not in the caller.
    argv = _argv("close", {"repo": str(repo), "run_id": "R1", "ticket": "CAL-1"}, roots)
    resolved = str(repo.resolve())
    tail = argv[argv.index("harness:dev") + 1 :]
    assert tail == ["close", "CAL-1", "--run-id", "R1", "--repo", resolved]


def test_close_requires_ticket_param(repo: Path, roots: list[Path]) -> None:
    # close needs the ticket id (the Linear Done transition targets it); omitting
    # it is a bad_params refusal before any container launch.
    with pytest.raises(LauncherError) as excinfo:
        _argv("close", {"repo": str(repo), "run_id": "R1"}, roots)
    assert excinfo.value.reason == "bad_params"


def test_status_maps_to_status_json(repo: Path, roots: list[Path]) -> None:
    argv = _argv("status", {"repo": str(repo), "run_id": "R1"}, roots)
    tail = argv[argv.index("harness:dev") + 1 :]
    assert tail == ["status", "R1", "--json"]


def test_cancel_maps_to_cancel(repo: Path, roots: list[Path]) -> None:
    argv = _argv("cancel", {"repo": str(repo), "run_id": "R1"}, roots)
    tail = argv[argv.index("harness:dev") + 1 :]
    assert tail == ["cancel", "R1"]


def test_decision_maps_to_decision_verb(repo: Path, roots: list[Path]) -> None:
    argv = _argv("decision", {"repo": str(repo), "run_id": "R1", "value": "approve"}, roots)
    tail = argv[argv.index("harness:dev") + 1 :]
    assert tail == ["decision", "R1", "approve"]


# ---------------------------------------------------------------------------
# ControlServer.dispatch — request → response with an injected runner
# ---------------------------------------------------------------------------


class _RecordingRunner:
    """A fake docker runner: records the argv and returns canned output."""

    def __init__(self, stdout: str = '{"run_id": "R1"}', exit_code: int = 0) -> None:
        self.calls: list[list[str]] = []
        self._stdout = stdout
        self._exit = exit_code

    def __call__(self, argv: list[str]) -> RunResult:
        self.calls.append(argv)
        return RunResult(exit_code=self._exit, stdout=self._stdout)


def _server(repo_root: Path, runner: _RecordingRunner) -> ControlServer:
    return ControlServer(
        runner=runner,
        image="harness:dev",
        roots=[repo_root.parent.resolve()],
        host_env={},
    )


def test_dispatch_runs_the_constructed_argv_and_returns_stdout(repo: Path) -> None:
    runner = _RecordingRunner()
    server = _server(repo, runner)
    resp = server.dispatch({"op": "start", "params": {"repo": str(repo), "ticket": "CAL-1"}})
    assert resp["ok"] is True
    assert resp["exit_code"] == 0
    assert resp["stdout"] == '{"run_id": "R1"}'
    assert runner.calls and runner.calls[0][:3] == ["docker", "run", "--rm"]


def test_dispatch_rejection_does_not_invoke_runner(repo: Path) -> None:
    runner = _RecordingRunner()
    server = _server(repo, runner)
    resp = server.dispatch({"op": "exec", "params": {"repo": str(repo)}})
    assert resp["ok"] is False
    assert resp["reason"] == "unknown_operation"
    assert runner.calls == []


def test_process_line_round_trips_json(repo: Path) -> None:
    runner = _RecordingRunner()
    server = _server(repo, runner)
    import json

    request = {"op": "status", "params": {"repo": str(repo), "run_id": "R1"}}
    raw = (json.dumps(request) + "\n").encode()
    out = server.process_line(raw)
    assert out.endswith(b"\n")
    parsed = json.loads(out)
    assert parsed["ok"] is True


def test_process_line_rejects_non_json(repo: Path) -> None:
    runner = _RecordingRunner()
    server = _server(repo, runner)
    import json

    out = server.process_line(b"this is not json\n")
    parsed = json.loads(out)
    assert parsed["ok"] is False
    assert parsed["reason"] == "bad_request"
    assert runner.calls == []
