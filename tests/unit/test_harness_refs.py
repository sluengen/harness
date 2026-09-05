"""#539 — the ``refs/harness/*`` namespace: gate records, claims, the green pointer.

The landing posture takes the exponential out of landing by having sessions share
what they learned through git refs rather than through a service. Three record
kinds, one script, and every key **flat** — probe 6 of the proposal recorded a
directory/file conflict the moment a key nested beneath an existing one, so a
branch name or ticket id that carries a ``/`` is percent-encoded into a single
path component instead of becoming two.

What each test here is for:

* **AC-2** — a record published from one clone is read by another in **one**
  ``ls-remote`` with **no object transfer**, and publishing prunes a record whose
  tree has left the integration branch's recent history while leaving the ones
  that have not. The object-transfer claim carries a control that must differ (a
  real fetch of the same refs), because "no objects arrived" and "nothing
  happened at all" compare equal otherwise.
* **AC-3** — two concurrent claim creates yield exactly one winner, and a
  **rotated** bucket admits a new one. The rotation is measured by letting a real
  clock pass a real (tiny) TTL rather than by injecting a "now", because a
  per-invocation source for the current time is one more thing that decides an
  outcome from outside the tree.
* **AC-6** (the ref half) — the green pointer names a commit and only ever moves
  forward; the landing behaviour that advances it is measured in
  ``test_land_script.py``.

A publish that cannot reach the remote **exits zero**. The record is a courtesy
to the next session, and `scripts/gate-marker.js` already states the principle
this follows: a gate that can fail for reasons unrelated to the tree is not a
gate. An unreachable remote is a fact about the network, never about the bytes.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from tests.unit._prose import REPO_ROOT

REFS = REPO_ROOT / "scripts" / "harness-refs.js"


def _node() -> str:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node not available")
    return node


def _git(repo: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", *args], cwd=repo, check=True, capture_output=True, text=True
    )
    return completed.stdout.strip()


def _cli(
    repo: Path, *args: str, env: dict[str, str] | None = None, path_prefix: Path | None = None
) -> subprocess.CompletedProcess[str]:
    environ = {**os.environ, **(env or {})}
    if path_prefix is not None:
        environ["PATH"] = f"{path_prefix}{os.pathsep}{environ['PATH']}"
    return subprocess.run(
        [_node(), str(REFS), *args],
        cwd=repo,
        capture_output=True,
        text=True,
        timeout=60,
        env=environ,
    )


def _ok(repo: Path, *args: str, **kwargs: object) -> str:
    proc = _cli(repo, *args, **kwargs)  # type: ignore[arg-type]
    assert proc.returncode == 0, f"harness-refs.js {args} failed: {proc.stderr.strip()}"
    return proc.stdout.strip()


def _commit(repo: Path, name: str, body: str) -> str:
    (repo / name).write_text(body, encoding="utf-8")
    _git(repo, "add", name)
    _git(repo, "commit", "-q", "-m", f"add {name}")
    return _git(repo, "rev-parse", "HEAD")


def _declare(repo: Path, integration: str = "dev") -> None:
    (repo / "harness.yaml").write_text(
        f"branches:\n  integration: {integration}\n  release: main\n", encoding="utf-8"
    )


@pytest.fixture
def remote(tmp_path: Path) -> Path:
    bare = tmp_path / "origin.git"
    subprocess.run(["git", "init", "-q", "--bare", str(bare)], check=True)
    return bare


@pytest.fixture
def alpha(tmp_path: Path, remote: Path) -> Path:
    """A clone with two commits on ``dev`` and the integration branch declared."""
    root = tmp_path / "alpha"
    root.mkdir()
    _git(root, "init", "-q", "--initial-branch=dev")
    _git(root, "config", "user.email", "t@example.com")
    _git(root, "config", "user.name", "t")
    _git(root, "remote", "add", "origin", str(remote))
    _declare(root)
    _commit(root, "a.txt", "one\n")
    _commit(root, "b.txt", "two\n")
    _git(root, "push", "-q", "origin", "dev")
    return root


def _clone(tmp_path: Path, remote: Path, name: str) -> Path:
    """A clone over the **real** transport, which is what makes objects countable.

    ``git clone`` of a filesystem path hardlinks the whole object store, so an
    ordinary local clone starts out holding every object the remote has — the
    record blob included, before any fetch. A corpus built that way cannot see an
    object transfer at all, and the no-transfer claim would measure clean against
    a ``gate-list`` that fetched the world. ``--no-local`` forces the pack
    negotiation a real clone does; measured here before it was relied on.
    """
    root = tmp_path / name
    subprocess.run(["git", "clone", "-q", "--no-local", str(remote), str(root)], check=True)
    _git(root, "config", "user.email", "t@example.com")
    _git(root, "config", "user.name", "t")
    _declare(root)
    return root


def _objects(repo: Path) -> int:
    """Loose plus packed objects, as ``git count-objects`` reports them."""
    reported = _git(repo, "count-objects", "-v").splitlines()
    fields = dict(line.split(": ", 1) for line in reported if ": " in line)
    return int(fields["count"]) + int(fields["in-pack"])


# --- AC-2: a record crosses between clones, and costs no objects --------------


def test_a_record_published_from_one_clone_is_read_by_another(
    tmp_path: Path, remote: Path, alpha: Path
) -> None:
    tree = _git(alpha, "rev-parse", "HEAD^{tree}")
    _ok(alpha, "gate-publish", "--tree", tree, "--outcome", "green")

    beta = _clone(tmp_path, remote, "beta")
    listed = _ok(beta, "gate-list")
    assert f"{tree} green" in listed.splitlines(), f"beta did not read alpha's record: {listed!r}"


def test_reading_the_records_transfers_no_objects_but_fetching_them_does(
    tmp_path: Path, remote: Path, alpha: Path
) -> None:
    """The claim is *no object transfer*, and it needs a control that must differ.

    "Zero objects arrived" is the same measurement as "the command did nothing",
    so the fetch below is the control: the same refs, pulled the ordinary way,
    move objects. Without it this test passes against a ``gate-list`` that
    contacts no remote at all.
    """
    tree = _git(alpha, "rev-parse", "HEAD^{tree}")
    _ok(alpha, "gate-publish", "--tree", tree, "--outcome", "red")

    beta = _clone(tmp_path, remote, "beta")
    before = _objects(beta)
    assert f"{tree} red" in _ok(beta, "gate-list").splitlines()
    after_list = _objects(beta)
    assert after_list == before, (
        f"reading the records moved objects into the clone: {before} -> {after_list}"
    )

    _git(beta, "fetch", "-q", "origin", "+refs/harness/*:refs/harness/*")
    assert _objects(beta) > after_list, (
        "the control did not move: if fetching the same refs transfers nothing "
        "either, the measurement above says nothing about ls-remote"
    )


def test_reading_the_records_is_one_ls_remote(tmp_path: Path, remote: Path, alpha: Path) -> None:
    """One round trip, counted — probe 7 measured ~1.0s for exactly one."""
    tree = _git(alpha, "rev-parse", "HEAD^{tree}")
    _ok(alpha, "gate-publish", "--tree", tree, "--outcome", "green")
    beta = _clone(tmp_path, remote, "beta")

    shim_dir = tmp_path / "shim"
    shim_dir.mkdir()
    tally = tmp_path / "ls-remote.count"
    real = shutil.which("git")
    assert real is not None
    (shim_dir / "git").write_text(
        "#!/usr/bin/env sh\n"
        'for a in "$@"; do\n'
        f'  if [ "$a" = "ls-remote" ]; then printf x >> "{tally}"; break; fi\n'
        "done\n"
        f'exec {real} "$@"\n',
        encoding="utf-8",
    )
    (shim_dir / "git").chmod(0o755)

    listed = _ok(beta, "gate-list", path_prefix=shim_dir)
    assert f"{tree} green" in listed.splitlines()
    calls = len(tally.read_text()) if tally.exists() else 0
    assert calls == 1, f"expected exactly one ls-remote, counted {calls}"


def test_publishing_prunes_a_departed_record_and_keeps_a_current_one(
    tmp_path: Path, remote: Path, alpha: Path
) -> None:
    """A record whose tree left the integration branch's recent history goes.

    A composite tree that *lands* becomes an integration-branch tree, so the
    records that age out are exactly the ones that never landed. The orphan
    below is the departed case and the branch tree is the control that must
    survive — a prune that deleted everything would satisfy a one-sided check.
    """
    current = _git(alpha, "rev-parse", "HEAD^{tree}")
    _ok(alpha, "gate-publish", "--tree", current, "--outcome", "green")

    _git(alpha, "checkout", "-q", "--orphan", "sidetrack")
    _git(alpha, "rm", "-q", "-rf", ".")
    (alpha / "z.txt").write_text("gone\n", encoding="utf-8")
    _git(alpha, "add", "z.txt")
    _git(alpha, "commit", "-q", "-m", "orphan")
    departed = _git(alpha, "rev-parse", "HEAD^{tree}")
    _ok(alpha, "gate-publish", "--tree", departed, "--outcome", "red")
    _git(alpha, "checkout", "-q", "dev")

    listed = _ok(alpha, "gate-list").splitlines()
    assert f"{departed} red" in listed and f"{current} green" in listed

    fresh = _commit(alpha, "c.txt", "three\n")
    _git(alpha, "push", "-q", "origin", "dev")
    newest = _git(alpha, "rev-parse", f"{fresh}^{{tree}}")
    _ok(alpha, "gate-publish", "--tree", newest, "--outcome", "green")

    after = _ok(alpha, "gate-list").splitlines()
    assert f"{departed} red" not in after, f"the departed record survived the prune: {after}"
    assert f"{current} green" in after, f"the prune took a record still in history: {after}"
    assert f"{newest} green" in after


def test_a_publish_to_an_unreachable_remote_does_not_fail(alpha: Path, tmp_path: Path) -> None:
    """A network fact is never a statement about the tree.

    The gate is green either way; a publish that exited non-zero would let an
    offline session's *sharing* redden its own verified result.
    """
    _git(alpha, "remote", "set-url", "origin", str(tmp_path / "does-not-exist.git"))
    tree = _git(alpha, "rev-parse", "HEAD^{tree}")
    proc = _cli(alpha, "gate-publish", "--tree", tree, "--outcome", "green")
    assert proc.returncode == 0, proc.stderr
    assert "not published" in proc.stdout, proc.stdout


# --- AC-3: claims are created, never forced ----------------------------------


def test_two_concurrent_claims_yield_one_winner(tmp_path: Path, remote: Path, alpha: Path) -> None:
    """Both claims computed from one instant, so the bucket is not the variable.

    Sequential, and this says so: a genuinely simultaneous race is not
    reproducible, and asserting one would be a claim the instrument cannot make.
    What is measured is that the *second* create is refused, which is the
    property — first-writer-wins comes from git rejecting a non-fast-forward,
    not from timing.
    """
    beta = _clone(tmp_path, remote, "beta")
    first = _cli(alpha, "claim", "--ticket", "539", "--now", "1757000000")
    second = _cli(beta, "claim", "--ticket", "539", "--now", "1757000000")
    outcomes = sorted([first.returncode, second.returncode])
    assert outcomes == [0, 3], (
        "exactly one create wins and the loser reports contention (exit 3): "
        f"alpha={first.returncode} {first.stdout.strip()} {first.stderr.strip()} / "
        f"beta={second.returncode} {second.stdout.strip()} {second.stderr.strip()}"
    )


def test_a_rotated_bucket_admits_a_new_claim(tmp_path: Path, remote: Path, alpha: Path) -> None:
    """The clock is advanced, not waited out — a tumbling window has a boundary.

    Against the wall clock this passed or failed on which side of a second the
    first two claims landed. The loser inside the *same* bucket is the control:
    without it a claim verb that simply always succeeded would pass the rotation
    half on its own.
    """
    env = {"HARNESS_CLAIM_TTL_SECONDS": "3600"}
    inside = "1757000000"
    later = str(1757000000 + 3600)
    assert _cli(alpha, "claim", "--ticket", "539", "--now", inside, env=env).returncode == 0
    assert _cli(alpha, "claim", "--ticket", "539", "--now", inside, env=env).returncode == 3
    rotated = _cli(alpha, "claim", "--ticket", "539", "--now", later, env=env)
    assert rotated.returncode == 0, (
        f"a rotated bucket must admit a new claim: {rotated.stdout} {rotated.stderr}"
    )


def test_a_claim_never_forces(tmp_path: Path, remote: Path, alpha: Path) -> None:
    """The force-push guard killed lease-stealing (probe 5); nothing may reach for it."""
    shim_dir = tmp_path / "shim"
    shim_dir.mkdir()
    seen = tmp_path / "args.log"
    real = shutil.which("git")
    assert real is not None
    (shim_dir / "git").write_text(
        '#!/usr/bin/env sh\nprintf "%s\\n" "$*" >> "' + str(seen) + '"\nexec ' + real + ' "$@"\n',
        encoding="utf-8",
    )
    (shim_dir / "git").chmod(0o755)
    beta = _clone(tmp_path, remote, "beta")
    _cli(alpha, "claim", "--ticket", "539", path_prefix=shim_dir)
    _cli(beta, "claim", "--ticket", "539", path_prefix=shim_dir)
    text = seen.read_text() if seen.exists() else ""
    assert "--force" not in text and "--force-with-lease" not in text, text
    assert "push" in text, "the shim never saw a push, so it observed nothing"


def test_a_ticket_id_with_a_slash_stays_one_ref_component(alpha: Path) -> None:
    """Probe 6: every key stays flat, so a nested id cannot make a D/F conflict."""
    assert _cli(alpha, "claim", "--ticket", "team/42").returncode == 0
    assert _cli(alpha, "claim", "--ticket", "team").returncode == 0, (
        "a claim on `team` must not collide with one on `team/42`"
    )
    refs = _git(alpha, "ls-remote", "origin", "refs/harness/claim/*")
    assert "refs/harness/claim/team%2F42-" in refs, refs
    assert not any(
        line.split("\t")[1].count("/") != 3 for line in refs.splitlines()
    ), f"a claim ref grew a path component: {refs}"


# --- AC-6 (ref half): the green pointer ---------------------------------------


def test_the_green_pointer_names_a_commit_and_only_moves_forward(alpha: Path) -> None:
    first = _git(alpha, "rev-parse", "HEAD")
    _ok(alpha, "green-advance", "--commit", first)
    assert _ok(alpha, "green-read") == first

    ahead = _commit(alpha, "c.txt", "three\n")
    _git(alpha, "push", "-q", "origin", "dev")
    _ok(alpha, "green-advance", "--commit", ahead)
    assert _ok(alpha, "green-read") == ahead

    behind = _cli(alpha, "green-advance", "--commit", first)
    assert behind.returncode != 0, "the pointer moved backwards"
    assert _ok(alpha, "green-read") == ahead


def test_the_pointer_key_encodes_a_branch_name_into_one_component(
    tmp_path: Path, remote: Path
) -> None:
    root = tmp_path / "slashy"
    root.mkdir()
    _git(root, "init", "-q", "--initial-branch=release/1.0")
    _git(root, "config", "user.email", "t@example.com")
    _git(root, "config", "user.name", "t")
    _git(root, "remote", "add", "origin", str(remote))
    _declare(root, integration="release/1.0")
    _commit(root, "a.txt", "one\n")
    _git(root, "push", "-q", "origin", "release/1.0")

    head = _git(root, "rev-parse", "HEAD")
    _ok(root, "green-advance", "--commit", head)
    refs = _git(root, "ls-remote", "origin", "refs/harness/green/*")
    assert "refs/harness/green/release%2F1%2E0" in refs, refs
    assert _ok(root, "green-read") == head


def test_the_records_report_themselves_as_json_when_asked(alpha: Path) -> None:
    """One machine-readable shape, so the landing script parses no prose."""
    tree = _git(alpha, "rev-parse", "HEAD^{tree}")
    _ok(alpha, "gate-publish", "--tree", tree, "--outcome", "green")
    payload = json.loads(_ok(alpha, "gate-list", "--json"))
    assert payload == {tree: "green"}, payload


def test_the_repo_operand_names_the_checkout(tmp_path: Path, remote: Path, alpha: Path) -> None:
    """It ships from the plugin root, so it needs a way to say which checkout.

    Run from a directory that is not a repository at all: without ``--repo`` this
    is the refusal, so a version that quietly used the process's own working
    directory could not pass both halves.
    """
    elsewhere = tmp_path / "not-a-repo"
    elsewhere.mkdir()
    assert _cli(elsewhere, "gate-list").returncode != 0
    tree = _git(alpha, "rev-parse", "HEAD^{tree}")
    _ok(alpha, "gate-publish", "--tree", tree, "--outcome", "green")
    listed = _ok(elsewhere, "gate-list", "--repo", str(alpha))
    assert f"{tree} green" in listed.splitlines(), listed
