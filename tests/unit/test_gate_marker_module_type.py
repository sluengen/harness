"""#500 — the gate-marker helper must parse as CommonJS in an ESM consumer repo.

Admission (ADR 0017 D5): class (a) — a shipped program executed under a
consumer-shaped root, plus class (d)/(e) over the one-key manifest that makes it
load.

The #302 mechanism, applied to a second directory. Node resolves a ``.js`` file's
module type from the **nearest** ``package.json`` walking up from the file. The
harness ships ``scripts/gate-marker.js`` as bare ``.js``, and ``skills/init/SKILL.md``
copies it into a consuming repo's ``scripts/``, so without a manifest that walk
terminates at *that repo's root* — a root the harness does not control. Where it
declares ``"type": "module"`` (any modern TS/Vite/ESM repo), Node parses the
helper as ESM and it dies at its first ``require``.

That failure is **loud** here, which is what makes the manifest a correctness fix
rather than a silent-disarm fix: every operation of this CLI has an observable on
its success path, a load failure is an uncaught error before ``main()`` runs, and
neither of ``scripts/verify.sh``'s two invocations of it can fail quietly. The
preflight is wrapped in ``|| _preflight_status=$?`` — deliberately, so ``set -e``
never sees it — and any non-zero status that wrapper captures leaves the gate at
the reserved exit 97; the ``write`` on the success path is unguarded, so there
``set -e`` ends the gate before it prints its success line. There is no path on
which a mis-typed module produces a marker or a green gate. #302's own subject
was the opposite — ``prompt-guard.js`` exited 0 with an approving payload having
scanned nothing — and the distinction is worth stating because it is what makes
this the cheaper of the two problems, not because it makes it acceptable: a gate
that cannot run is a gate.

**Why ``.js`` with a manifest and not ``.cjs``.** On the merits ``.cjs`` is the
better answer for a file with no installed callers: the extension is
authoritative regardless of any manifest and has no directory-wide side effect
anywhere. It is rejected because the ticket names ``.js`` verbatim, and the
rejection is recorded with its reason in ADR 0018 rather than left as folklore.
The side effect the manifest defers — in a consumer whose ``scripts/`` already
holds ESM ``.js`` siblings, this manifest retypes *their* files — belongs to
#501, which owns hydration.

Both operands below are the **git index**, deliberately: the subject is what a
fresh clone and a hydrating consumer receive, and a guard over the working file
passes on the machine that wrote it (#484). That puts this module outside
``scripts/mutate.py``'s reach — its mutations are proved by staged probe (#490).

"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from tests._gitutil import indexed_text

MANIFEST = "scripts/package.json"
HELPER = "scripts/gate-marker.js"


def _node() -> str:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node not available")
    return node


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=repo, check=True, capture_output=True, text=True
    ).stdout.strip()


def _esm_consumer(tmp_path: Path) -> Path:
    """A repository whose root declares ESM, carrying the two shipped files.

    Written out of the index rather than hand-authored, so deleting or retyping
    the real manifest propagates here and the positive case goes red instead of
    quietly testing a stand-in.
    """
    fixture = tmp_path / "consumer"
    (fixture / "scripts").mkdir(parents=True)
    (fixture / "package.json").write_text(json.dumps({"type": "module"}) + "\n")
    for relative in (HELPER, MANIFEST):
        (fixture / relative).write_text(indexed_text(relative), encoding="utf-8")
    _git(fixture, "init", "-q", "--initial-branch=main")
    _git(fixture, "config", "user.email", "t@example.com")
    _git(fixture, "config", "user.name", "t")
    _git(fixture, "add", "-A")
    _git(fixture, "commit", "-q", "-m", "consumer")
    return fixture


def _run_tree(fixture: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [_node(), HELPER, "tree"],
        cwd=fixture,
        capture_output=True,
        text=True,
        timeout=60,
    )


def test_the_manifest_declares_commonjs() -> None:
    """Parsed, not string-matched, so a ``"type": "module"`` typo fails here."""
    assert json.loads(indexed_text(MANIFEST))["type"] == "commonjs"


def test_the_helper_answers_under_an_esm_root(tmp_path: Path) -> None:
    """The behaviour, not the load: an answer, not merely an exit status.

    Asserting exit 0 alone would be satisfied by a helper that printed nothing,
    so the observable is the tree oid the consumer's gate would record.
    """
    proc = _run_tree(_esm_consumer(tmp_path))

    assert proc.returncode == 0, (
        f"the helper did not run in a consumer repo whose root package.json "
        f'declares "type": "module": {proc.stderr.strip()!r}'
    )
    assert len(proc.stdout.strip()) == 40, (
        f"the helper exited 0 without printing a tree oid: {proc.stdout!r}"
    )


def test_removing_the_manifest_breaks_the_helper_loudly(tmp_path: Path) -> None:
    """What binds the case above to the shipped manifest.

    Without this, the positive case would also pass in a repo that has no ESM
    root at all and would prove nothing. Loudness is asserted as well as failure,
    and stderr is where the loudness has to land: a module-type load failure is
    an uncaught error, so it exits 1, and ``verify.sh``'s wrapper reserves exit
    2 for a refusal the helper itself reported and routes everything else to
    *the gate-marker helper could not run … exited 1*. The wrapper can therefore
    say only that the helper exited non-zero, which is why stderr is asserted
    rather than the exit status alone: stderr is where the cause appears at all,
    as Node's ``require is not defined`` ReferenceError.
    """
    fixture = _esm_consumer(tmp_path)
    (fixture / MANIFEST).unlink()

    proc = _run_tree(fixture)

    assert proc.returncode != 0, (
        "the helper still ran with scripts/package.json removed, so the fixture "
        "is not exercising module resolution and the positive case proves nothing"
    )
    assert proc.stderr.strip(), "the helper failed to load and said nothing about it"
    assert proc.stdout.strip() == "", (
        f"the helper printed an answer it could not have computed: {proc.stdout!r}"
    )
