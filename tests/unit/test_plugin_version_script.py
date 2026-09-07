"""#589 — ``scripts/plugin-version.js``: the plugin's version bump gets an owner.

``claude plugins update`` compares the manifest **version string** and nothing
else; the ``gitCommitSha`` it records is never consulted for this plugin. So a
cycle that ships content without moving the version does not under-report — it
delivers nothing, and the consumer is told it is current. #556 gave the bump to
the builder and enforced it with a 713-line guard; #588 deleted both and left
the bump with no owner. This script is the owner: ``/build`` step 1 runs it in
the new worktree, so the raise lands inside the tree the gate certifies and the
reviewer reads (law 3).

Three properties are load-bearing here and are measured rather than described.

* **A repo that is not a plugin source is left alone.** ``/build`` step 1 is
  *shipped guidance* — calibrate, nano-erp and lab-book run it too, and each
  carries an ``AGENTS.md`` ``spine:generated`` marker naming the harness version
  that hydrated it. A writer that raised every marker it found would silently
  rewrite three repos' record of which guidance they run. Membership is earned by
  **positive identification** — a ``.claude-plugin/plugin.json`` is present, and a
  marker is a home only where the name it carries equals that manifest's ``name``
  — never by absence. :func:`test_a_repo_with_no_plugin_manifest_is_left_alone`
  and :func:`test_a_marker_naming_another_plugin_is_not_a_home` are that pin.

* **A declared release ref that will not resolve refuses; it never skips.** The
  deleted guard reported ``NO_RELEASE_REF`` and skipped on every ``push: dev``,
  so it enforced nothing exactly where it mattered. The two exit-0 no-ops here —
  ``no-plugin-manifest`` and ``no-release-branch`` — are the cases where the
  obligation *cannot exist*, not cases where it applies and was waived, and both
  print a payload rather than staying silent.

* **The homes are rewritten by substring, never reserialized.**
  ``.codex-plugin/plugin.json`` carries ``keywords`` and ``defaultPrompt`` as
  single-line arrays that ``JSON.stringify(…, null, 2)`` reflows, turning a
  three-character change into a fifteen-line diff in every cycle's first review
  forever. :func:`test_a_raise_changes_only_the_version_substring` is that
  mutant's exclusive killer.

**Why the fixtures name a plugin this repo has never published.** Every version
here is ``1.x.y`` and every plugin is ``acme``, so a hardcoded ``harness`` or a
hardcoded ``8`` is indistinguishable from nothing at all (#458 — pin the
derivation, never the derived answer). The release branch is ``prod`` for the
same reason: AC-3 asks that the role be *read* from ``harness.yaml``, and a
fixture declaring ``main`` would pass against a constant.

**Why the working tree.** These read fixture working trees rather than the index,
which is the opposite of this repo's guard rule (`.claude/rules/scripts.md` →
*Evidence*). That rule governs a **guard** claiming a property of what ships; the
subject here is a **writer**, whose operand must be the bytes it is about to
modify — reading the index and writing the working tree is exactly how the two
diverge. The shipping-tree claim is still held, downstream and unchanged, by
``test_spine_template_parity.py`` and ``test_native_codex_plugin.py``, which read
the index at gate time over the committed bump.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from tests.unit._prose import REPO_ROOT

SCRIPT = REPO_ROOT / "scripts" / "plugin-version.js"

#: The four homes, repo-relative, in the order the script reports them.
HOMES = (
    ".claude-plugin/plugin.json",
    ".codex-plugin/plugin.json",
    "AGENTS.md",
    "templates/spine.md",
)


def _node() -> str:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node not available")
    return node


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=repo, check=True, capture_output=True, text=True
    ).stdout.strip()


def _run(repo: Path, *args: str) -> tuple[int, dict[str, object], str]:
    """Spawn the production script and return ``(exit, payload, stderr)``."""
    proc = subprocess.run(
        [_node(), str(SCRIPT), *args],
        cwd=repo,
        capture_output=True,
        text=True,
        timeout=60,
    )
    payload: dict[str, object] = {}
    if proc.stdout.strip():
        payload = json.loads(proc.stdout)
    return proc.returncode, payload, proc.stderr


# --- fixture construction -----------------------------------------------------


def _claude_manifest(name: str, version: str) -> str:
    return json.dumps({"name": name, "version": version}, indent=2) + "\n"


def _codex_manifest(name: str, version: str) -> str:
    """Deliberately *not* what ``json.dumps`` would produce.

    The single-line arrays and the key order are the production file's shape
    (`.codex-plugin/plugin.json`). A reserializing writer reflows them, and
    :func:`test_a_raise_changes_only_the_version_substring` is what sees it.
    """
    return (
        "{\n"
        f'  "name": "{name}",\n'
        f'  "version": "{version}",\n'
        '  "description": "a fixture plugin",\n'
        '  "keywords": ["one", "two", "three"],\n'
        '  "skills": "./skills/",\n'
        '  "interface": {\n'
        '    "displayName": "Acme",\n'
        '    "defaultPrompt": ["do a thing", "do another thing"]\n'
        "  }\n"
        "}\n"
    )


def _spine(
    name: str, version: str, *, prose: bool = False, quoted: bool = False
) -> str:
    """A spine carrying the generated marker, optionally with a decoy above it.

    ``prose`` adds the bare-word mention ``AGENTS.md:3`` carries. ``quoted`` adds a
    sentence quoting a **whole marker inline**, which is the shape
    ``skills/init/references/refresh.md:33`` already carries and the one the
    pattern's line anchors actually defend against — the bare mention has no
    ``<!--`` and no unanchored pattern would touch it.
    """
    lead = ""
    if prose:
        lead += "This document mentions spine:generated in ordinary prose.\n\n"
    if quoted:
        lead += (
            f"The block opens with <!-- spine:generated:begin {name}@0.9.9 --> and "
            "closes with the matching end marker.\n\n"
        )
    return (
        "# How work happens here\n\n"
        f"{lead}"
        f"<!-- spine:generated:begin {name}@{version} -->\n\n"
        "## Principles\n\nDo less.\n\n"
        "<!-- spine:generated:end -->\n\n"
        "## This repo\n\nA fixture.\n"
    )


def _write_homes(root: Path, name: str, version: str, *, prose: bool = False) -> None:
    (root / ".claude-plugin").mkdir(exist_ok=True)
    (root / ".codex-plugin").mkdir(exist_ok=True)
    (root / "templates").mkdir(exist_ok=True)
    (root / ".claude-plugin" / "plugin.json").write_text(
        _claude_manifest(name, version), encoding="utf-8"
    )
    (root / ".codex-plugin" / "plugin.json").write_text(
        _codex_manifest(name, version), encoding="utf-8"
    )
    (root / "AGENTS.md").write_text(_spine(name, version, prose=prose), encoding="utf-8")
    (root / "templates" / "spine.md").write_text(
        _spine(name, version), encoding="utf-8"
    )


def _versions(root: Path) -> dict[str, str]:
    """What each home currently carries, read back off disk."""
    out: dict[str, str] = {}
    out[HOMES[0]] = json.loads((root / HOMES[0]).read_text(encoding="utf-8"))["version"]
    out[HOMES[1]] = json.loads((root / HOMES[1]).read_text(encoding="utf-8"))["version"]
    for home in HOMES[2:]:
        text = (root / home).read_text(encoding="utf-8")
        marker = [ln for ln in text.splitlines() if "spine:generated:begin" in ln]
        assert len(marker) == 1, f"{home} carries {len(marker)} begin markers"
        out[home] = marker[0].split("@", 1)[1].split(" ", 1)[0].removesuffix("-->")
    return out


def _snapshot(root: Path) -> dict[str, str]:
    return {home: (root / home).read_text(encoding="utf-8") for home in HOMES}


def _make_repo(
    tmp_path: Path,
    *,
    homes: str = "1.2.3",
    release: str | None = "1.2.3",
    name: str = "acme",
    release_role: str = "prod",
    declare_release: bool = True,
    prose: bool = False,
) -> Path:
    """A plugin source on ``main`` with a real ``origin`` carrying the release role.

    ``release`` is the version the release branch carries; ``None`` means the
    release branch is never created, so the declared ref cannot resolve.
    """
    bare = tmp_path / "origin.git"
    subprocess.run(["git", "init", "-q", "--bare", str(bare)], check=True)
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-q", "--initial-branch=main")
    _git(root, "config", "user.email", "t@example.com")
    _git(root, "config", "user.name", "t")
    _git(root, "remote", "add", "origin", str(bare))
    branches = "branches:\n  integration: main\n"
    if declare_release:
        branches += f"  release: {release_role}\n"
    (root / "harness.yaml").write_text(branches, encoding="utf-8")

    #: The release version is committed first so the release branch is a real
    #: ancestor-bearing history rather than a synthetic ref.
    _write_homes(root, name, release if release is not None else homes, prose=prose)
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "base")
    if release is not None:
        _git(root, "push", "-q", "origin", f"main:{release_role}")

    if homes != (release if release is not None else homes):
        _write_homes(root, name, homes, prose=prose)
        _git(root, "add", "-A")
        _git(root, "commit", "-q", "-m", "integration")
    _git(root, "push", "-q", "origin", "main")
    return root


# --- AC-1: the raise ----------------------------------------------------------


def test_matching_versions_raise_the_minor_across_all_four_homes(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path, homes="1.2.3", release="1.2.3")

    code, payload, err = _run(repo)

    assert code == 0, f"exit {code}, stderr={err}, payload={payload}"
    assert payload["bumped"] is True, payload
    assert payload["case"] == "raised", payload
    assert payload["from"] == "1.2.3" and payload["to"] == "1.3.0", payload
    assert _versions(repo) == dict.fromkeys(HOMES, "1.3.0"), _versions(repo)


def test_the_raise_zeroes_the_patch_rather_than_carrying_it(tmp_path: Path) -> None:
    """``[major, minor + 1, 0]`` — ``minor + 1`` alone is the natural wrong write."""
    repo = _make_repo(tmp_path, homes="1.2.7", release="1.2.7")

    code, payload, err = _run(repo)

    assert code == 0, f"exit {code}, stderr={err}, payload={payload}"
    assert payload["to"] == "1.3.0", payload
    assert _versions(repo) == dict.fromkeys(HOMES, "1.3.0"), _versions(repo)


def test_a_raise_reports_every_home_it_wrote(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path, homes="1.2.3", release="1.2.3")

    _, payload, _ = _run(repo)

    assert payload["homes"] == list(HOMES), payload


# --- AC-2: one bump per cycle -------------------------------------------------


def test_an_integration_version_already_ahead_writes_nothing(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path, homes="1.3.0", release="1.2.3")
    before = _snapshot(repo)

    code, payload, err = _run(repo)

    assert code == 0, f"exit {code}, stderr={err}, payload={payload}"
    assert payload["bumped"] is False, payload
    assert payload["case"] == "already-ahead", payload
    assert _snapshot(repo) == before, "an already-ahead run wrote to a home"


def test_a_second_run_in_one_cycle_is_a_no_op(tmp_path: Path) -> None:
    """The ``/build`` resume path: invoking twice raises once."""
    repo = _make_repo(tmp_path, homes="1.2.3", release="1.2.3")
    first_code, first, _ = _run(repo)
    assert first_code == 0 and first["case"] == "raised", first
    after_first = _snapshot(repo)

    code, payload, err = _run(repo)

    assert code == 0, f"exit {code}, stderr={err}, payload={payload}"
    assert payload["case"] == "already-ahead", payload
    assert _snapshot(repo) == after_first, "the second run wrote to a home"


# --- AC-3: the release role is read, never hardcoded --------------------------


def test_the_release_role_comes_from_the_declared_configuration(tmp_path: Path) -> None:
    """The fixture declares ``prod``, and ``main`` is the integration branch.

    A script that read ``main`` as the release role would compare the branch
    against itself and always find them equal — so it would *raise*, which is the
    same answer this test expects for the right reason. The discriminator is the
    reported ref: it must name the declared role.
    """
    repo = _make_repo(tmp_path, homes="1.2.3", release="1.2.3", release_role="prod")

    code, payload, err = _run(repo)

    assert code == 0, f"exit {code}, stderr={err}, payload={payload}"
    release = payload["release"]
    assert isinstance(release, dict), payload
    assert release["ref"] == "refs/remotes/origin/prod", payload
    assert release["version"] == "1.2.3", payload


def test_an_undeclared_release_role_is_a_reported_no_op(tmp_path: Path) -> None:
    """No release branch means the obligation cannot exist, not that it is waived."""
    repo = _make_repo(tmp_path, homes="1.2.3", release="1.2.3", declare_release=False)
    before = _snapshot(repo)

    code, payload, err = _run(repo)

    assert code == 0, f"exit {code}, stderr={err}, payload={payload}"
    assert payload["bumped"] is False and payload["case"] == "no-release-branch", payload
    assert _snapshot(repo) == before


# --- AC-4: refusals, never a silent skip --------------------------------------


def test_an_unresolvable_release_ref_refuses_and_names_it(tmp_path: Path) -> None:
    """The ``NO_RELEASE_REF`` pin: the deleted guard skipped here and enforced nothing."""
    repo = _make_repo(tmp_path, homes="1.2.3", release=None)
    before = _snapshot(repo)

    code, payload, err = _run(repo)

    assert code == 2, f"exit {code}, stderr={err}, payload={payload}"
    assert payload["case"] == "release-unresolvable", payload
    assert payload["ref"] == "refs/remotes/origin/prod", payload
    assert _snapshot(repo) == before


def test_a_release_branch_off_an_unrelated_history_is_a_topology_refusal(
    tmp_path: Path,
) -> None:
    """Release ahead over content the integration history does not contain."""
    repo = _make_repo(tmp_path, homes="1.2.3", release="1.2.3")
    #: An orphan release carrying a higher version — `promotion-step.sh`'s own
    #: content-divergence condition, and a genuine fault.
    _git(repo, "checkout", "-q", "--orphan", "elsewhere")
    _write_homes(repo, "acme", "2.0.0")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "unrelated")
    _git(repo, "push", "-q", "-f", "origin", "elsewhere:prod")
    _git(repo, "checkout", "-q", "main")
    before = _snapshot(repo)

    code, payload, err = _run(repo)

    assert code == 2, f"exit {code}, stderr={err}, payload={payload}"
    assert payload["case"] == "release-ahead", payload
    assert _snapshot(repo) == before


def test_a_release_that_already_contains_this_head_is_a_stale_base(
    tmp_path: Path,
) -> None:
    """The same version relation as the test above, and a different answer.

    ``land.js done`` withholds the green pointer after a contended landing by
    design, and a landing can skip ``done`` outright (#557) — either leaves the
    pointer behind the commit that carried the bump. A worktree cut from that
    pointer after a promotion reads a higher release version over its own base.
    That is a rebase, not a topology fault, and this pair is what proves the
    discriminator is **ancestry** rather than the version comparison.
    """
    repo = _make_repo(tmp_path, homes="1.2.3", release="1.2.3")
    head = _git(repo, "rev-parse", "HEAD")
    _git(repo, "checkout", "-q", "-b", "later")
    _write_homes(repo, "acme", "1.3.0")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "the release that overtook this base")
    _git(repo, "push", "-q", "-f", "origin", "later:prod")
    _git(repo, "checkout", "-q", "main")
    assert _git(repo, "rev-parse", "HEAD") == head
    before = _snapshot(repo)

    code, payload, err = _run(repo)

    assert code == 2, f"exit {code}, stderr={err}, payload={payload}"
    assert payload["case"] == "stale-base", payload
    assert "next" in payload, payload
    assert _snapshot(repo) == before


def test_an_unreadable_release_manifest_refuses(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path, homes="1.2.3", release="1.2.3")
    _git(repo, "checkout", "-q", "-b", "broken")
    (repo / ".claude-plugin" / "plugin.json").write_text("{ not json", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "broken manifest")
    _git(repo, "push", "-q", "-f", "origin", "broken:prod")
    _git(repo, "checkout", "-q", "--", ".")
    _git(repo, "checkout", "-q", "main")
    before = _snapshot(repo)

    code, payload, err = _run(repo)

    assert code == 2, f"exit {code}, stderr={err}, payload={payload}"
    assert payload["case"] == "release-manifest-unreadable", payload
    assert _snapshot(repo) == before


def test_homes_that_disagree_refuse_and_report_every_value(tmp_path: Path) -> None:
    """A partial prior write leaves no single version to raise."""
    repo = _make_repo(tmp_path, homes="1.2.3", release="1.2.3")
    (repo / HOMES[0]).write_text(_claude_manifest("acme", "1.3.0"), encoding="utf-8")
    before = _snapshot(repo)

    code, payload, err = _run(repo)

    assert code == 2, f"exit {code}, stderr={err}, payload={payload}"
    assert payload["case"] == "homes-disagree", payload
    assert payload["carried"] == {
        HOMES[0]: "1.3.0",
        HOMES[1]: "1.2.3",
        HOMES[2]: "1.2.3",
        HOMES[3]: "1.2.3",
    }, payload
    assert _snapshot(repo) == before


def test_a_version_outside_the_grammar_refuses_and_names_the_home(
    tmp_path: Path,
) -> None:
    """``X.Y.Z``, digits only. A prerelease needs SemVer precedence nobody specified."""
    repo = _make_repo(tmp_path, homes="1.2.3", release="1.2.3")
    (repo / HOMES[0]).write_text(
        _claude_manifest("acme", "1.2.3-rc.1"), encoding="utf-8"
    )
    before = _snapshot(repo)

    code, payload, err = _run(repo)

    assert code == 2, f"exit {code}, stderr={err}, payload={payload}"
    assert payload["case"] == "unreadable-version", payload
    assert payload["home"] == HOMES[0], payload
    assert _snapshot(repo) == before


def test_a_home_with_two_version_sites_refuses_rather_than_guessing(
    tmp_path: Path,
) -> None:
    repo = _make_repo(tmp_path, homes="1.2.3", release="1.2.3")
    (repo / HOMES[0]).write_text(
        json.dumps(
            {"name": "acme", "version": "1.2.3", "nested": {"version": "1.2.3"}},
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    before = _snapshot(repo)

    code, payload, err = _run(repo)

    assert code == 2, f"exit {code}, stderr={err}, payload={payload}"
    assert payload["case"] == "home-unwritable", payload
    assert payload["home"] == HOMES[0] and payload["found"] == 2, payload
    assert _snapshot(repo) == before


# --- the consuming repos: membership is earned, never assumed -----------------


def test_a_repo_with_no_plugin_manifest_is_left_alone(tmp_path: Path) -> None:
    """The highest-severity case here.

    ``/build`` step 1 is shipped guidance and runs in calibrate, nano-erp and
    lab-book, each of which carries an ``AGENTS.md`` marker naming the harness
    version that hydrated it. A writer that raised every marker it found would
    rewrite three repos' record of which guidance they run, silently, on their
    next build.
    """
    repo = _make_repo(tmp_path, homes="1.2.3", release="1.2.3")
    shutil.rmtree(repo / ".claude-plugin")
    before = (repo / "AGENTS.md").read_text(encoding="utf-8")

    code, payload, err = _run(repo)

    assert code == 0, f"exit {code}, stderr={err}, payload={payload}"
    assert payload["bumped"] is False, payload
    assert payload["case"] == "no-plugin-manifest", payload
    assert (repo / "AGENTS.md").read_text(encoding="utf-8") == before, (
        "a consuming repo's spine marker was rewritten"
    )


def test_a_marker_naming_another_plugin_is_not_a_home(tmp_path: Path) -> None:
    """Membership is a name equality against the manifest, not the marker's shape."""
    repo = _make_repo(tmp_path, homes="1.2.3", release="1.2.3")
    foreign = _spine("otherthing", "1.2.3")
    (repo / "AGENTS.md").write_text(foreign, encoding="utf-8")

    code, payload, err = _run(repo)

    assert code == 0, f"exit {code}, stderr={err}, payload={payload}"
    assert payload["case"] == "raised", payload
    assert (repo / "AGENTS.md").read_text(encoding="utf-8") == foreign, (
        "a marker naming another plugin was rewritten"
    )
    assert "AGENTS.md" not in payload["homes"], payload
    #: The homes it *does* own still moved.
    assert json.loads((repo / HOMES[0]).read_text(encoding="utf-8"))["version"] == "1.3.0"


# --- how the bytes are written ------------------------------------------------


def test_a_raise_changes_only_the_version_substring(tmp_path: Path) -> None:
    """Exclusive killer for a reserializing implementation.

    ``.codex-plugin/plugin.json`` carries single-line arrays that
    ``JSON.stringify(…, null, 2)`` reflows. The formatting is not cosmetic: the
    noise lands in the first review of every cycle, forever.
    """
    repo = _make_repo(tmp_path, homes="1.2.3", release="1.2.3")
    before = _snapshot(repo)

    code, _, err = _run(repo)
    assert code == 0, err

    for home in HOMES:
        after = (repo / home).read_text(encoding="utf-8")
        assert after == before[home].replace("1.2.3", "1.3.0"), (
            f"{home} changed by more than its version substring"
        )


def test_a_marker_keeps_its_own_spacing(tmp_path: Path) -> None:
    """A parser must accept every legal spelling its subject contains (#484, #487)."""
    repo = _make_repo(tmp_path, homes="1.2.3", release="1.2.3")
    spaced = (repo / "AGENTS.md").read_text(encoding="utf-8").replace(
        "<!-- spine:generated:begin acme@1.2.3 -->",
        "<!--  spine:generated:begin   acme@1.2.3  -->",
    )
    (repo / "AGENTS.md").write_text(spaced, encoding="utf-8")

    code, payload, err = _run(repo)

    assert code == 0, f"exit {code}, stderr={err}, payload={payload}"
    assert (repo / "AGENTS.md").read_text(encoding="utf-8") == spaced.replace(
        "acme@1.2.3", "acme@1.3.0"
    )


def test_prose_mentioning_the_marker_is_not_rewritten(tmp_path: Path) -> None:
    """``AGENTS.md:3`` names ``spine:generated`` in an ordinary sentence.

    The parity guard already carries a sample for this shape; an unanchored
    pattern would rewrite the sentence instead of the marker.
    """
    repo = _make_repo(tmp_path, homes="1.2.3", release="1.2.3", prose=True)

    code, payload, err = _run(repo)

    assert code == 0, f"exit {code}, stderr={err}, payload={payload}"
    text = (repo / "AGENTS.md").read_text(encoding="utf-8")
    assert "mentions spine:generated in ordinary prose" in text, text
    assert "<!-- spine:generated:begin acme@1.3.0 -->" in text, text


def test_a_marker_quoted_inside_a_sentence_is_not_a_second_site(
    tmp_path: Path,
) -> None:
    """The control for the pattern's line anchors, and it was missing.

    A mutation dropping ``^`` and ``$`` from the marker pattern survived a first
    table, and the diagnosis was a **false mechanism claim** rather than a weak
    guard (#490): the comment cited ``AGENTS.md:3``, which mentions
    ``spine:generated`` as a bare word with no ``<!--``, so no unanchored pattern
    would ever have touched it. The shape that *is* at risk is a whole marker
    quoted mid-sentence — ``skills/init/references/refresh.md:33`` carries one
    today, and a home is one sentence away from carrying one.

    Unanchored, the quoted marker is a second site, the home refuses as
    ``home-unwritable``, and no version moves at all. Anchored, the sentence is
    prose and only the real marker is rewritten — including its version, which
    differs from the decoy's so a writer that picked the wrong site cannot pass.
    """
    repo = _make_repo(tmp_path, homes="1.2.3", release="1.2.3")
    spine = _spine("acme", "1.2.3", quoted=True)
    (repo / "AGENTS.md").write_text(spine, encoding="utf-8")

    code, payload, err = _run(repo)

    assert code == 0, f"exit {code}, stderr={err}, payload={payload}"
    assert payload["case"] == "raised", payload
    assert (repo / "AGENTS.md").read_text(encoding="utf-8") == spine.replace(
        "acme@1.2.3", "acme@1.3.0"
    ), "the quoted marker and the real one were not told apart"
    #: The decoy is untouched: an implementation that rewrote the first site it
    #: found would have moved this one instead.
    assert "acme@0.9.9" in (repo / "AGENTS.md").read_text(encoding="utf-8")


def test_a_raise_touches_no_file_outside_the_reported_homes(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path, homes="1.2.3", release="1.2.3")

    code, payload, err = _run(repo)
    assert code == 0, err

    #: ``XY <path>``, split on the first run of whitespace rather than at a fixed
    #: offset: :func:`_git` strips its output, so the first line has already lost
    #: the leading space an unmodified-index entry carries and a fixed cut takes a
    #: character of the path with it.
    dirty = sorted(
        line.split(maxsplit=1)[1]
        for line in _git(repo, "status", "--porcelain").splitlines()
    )
    assert dirty == sorted(payload["homes"]), (dirty, payload)


# --- usage --------------------------------------------------------------------


def test_an_unknown_flag_is_a_usage_error(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path, homes="1.2.3", release="1.2.3")

    code, payload, err = _run(repo, "--nonesuch")

    assert code == 64, f"exit {code}, stderr={err}, payload={payload}"
    assert "usage:" in err, err


def test_the_repo_flag_names_the_checkout_rather_than_the_cwd(tmp_path: Path) -> None:
    """The script ships from the plugin root and is not materialized into a repo.

    `.claude/rules/scripts.md` fixes that convention for this set, so the
    checkout it edits is named rather than inferred.
    """
    repo = _make_repo(tmp_path, homes="1.2.3", release="1.2.3")
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()

    proc = subprocess.run(
        [_node(), str(SCRIPT), "--repo", str(repo)],
        cwd=elsewhere,
        capture_output=True,
        text=True,
        timeout=60,
    )

    assert proc.returncode == 0, proc.stderr
    assert json.loads(proc.stdout)["case"] == "raised", proc.stdout
    assert _versions(repo) == dict.fromkeys(HOMES, "1.3.0"), _versions(repo)
