"""#302 — BOOTSTRAP must cover the Windows junction workaround and the header-less set.

Two documentation contracts, both guarded by **derivation** rather than by
matching fixed prose — a guard that asserts a sentence is a copy of that
sentence, and goes stale silently the moment the doc is reworded.

**The Windows problem (AC-4).** `BOOTSTRAP.md` step 3 tells the installer to
create `.claude/{agents,commands,hooks,skills}` as symlinks. On a Windows clone
without Developer Mode git forces ``core.symlinks=false`` and writes each as a
plain text file holding its target path, so nothing under `.claude/` resolves and
the whole guidance surface disappears with nothing logged. The per-clone fix is a
directory junction, and it has a second-order trap: git **descends into** a
junction where it would not follow a symlink, so a later ``git add .`` stages a
duplicate bundle under `.claude/` and replaces the symlinks Linux and CI read.
Both halves — the trailing-slash ignore rules and ``--skip-worktree`` — are
needed, so the guard requires **every** link named in step 3 to appear in all
three remedies. A fifth link added to step 3 without a Windows counterpart is
then a gate failure rather than a silent hole.

**The header-less set (AC-5).** Registry-managed `.json` files carry no
``guidance:`` header by design; their registry version is authoritative. That set
had exactly one member (`settings/*.json`) until `hooks/package.json` joined it,
and BOOTSTRAP names the exemption twice — step 2's no-clobber rule and step 7's
verification. The guard derives the set from `registry.yaml` by the same `.json`
suffix rule `hooks/guidance-freshness.js` and
`test_guidance_source.test_surface_headers_match_registry` already use, so a
*future* header-less entry also fails the gate until BOOTSTRAP exempts it. The
two sentences cannot drift apart from the registry, or from each other.

Acceptance criteria:

* **AC-4** — every `.claude/*` link step 3 declares is covered by the Windows
  block's junction, skip-worktree, and ignore-rule remedies, and the block
  explains the descend-into-a-junction mechanism the ignore rules exist for.
  :func:`test_every_declared_link_has_a_junction_line`,
  :func:`test_every_declared_link_has_a_skip_worktree_line`,
  :func:`test_every_declared_link_has_a_trailing_slash_ignore_rule`,
  :func:`test_the_windows_block_explains_why_git_descends_into_a_junction`.
* **AC-5** — every header-less registry file is exempted in both step 2 and
  step 7. :func:`test_step_2_no_clobber_exempts_every_headerless_file` and
  :func:`test_step_7_header_check_exempts_every_headerless_file`.
"""

from __future__ import annotations

import fnmatch
import re

from tests.unit._prose import REPO_ROOT

_BOOTSTRAP = REPO_ROOT / "BOOTSTRAP.md"
_REGISTRY = REPO_ROOT / "registry.yaml"

_TEXT = _BOOTSTRAP.read_text()

#: Step 3's own declaration, e.g. ``agents -> ../agents``. This is the source of
#: truth for which links exist — deriving from it is what makes a newly added
#: fifth link fail the Windows guard instead of slipping through.
_DECLARED_LINK = re.compile(r"`(\w+) -> \.\./\w+`")


def _declared_links() -> set[str]:
    links = set(_DECLARED_LINK.findall(_TEXT))
    assert links, (
        "no `<name> -> ../<name>` symlink declarations found in BOOTSTRAP.md — "
        "step 3 was reworded and this guard can no longer derive the link set, "
        "which would make every assertion below vacuously true."
    )
    return links


def _windows_block() -> str:
    """Step 3's Windows bullet, from its heading to the start of step 4."""
    start = _TEXT.find("On Windows without Developer Mode")
    assert start != -1, (
        "BOOTSTRAP.md step 3 no longer carries the Windows junction note — a "
        "Windows clone silently loses its entire .claude/ surface without it."
    )
    end = _TEXT.find("**4. Scaffold", start)
    assert end != -1, "could not find the end of step 3"
    return _TEXT[start:end]


def _headerless_registry_files() -> set[str]:
    """Registry ``files:`` entries carrying no ``guidance:`` header.

    The discriminator is the ``.json`` suffix — the same rule
    ``hooks/guidance-freshness.js`` applies at its source-mode branch and
    ``test_guidance_source`` applies when checking header/registry parity.
    Reusing it here means the three cannot disagree about what is header-less.
    """
    files_block = _REGISTRY.read_text().split("files:", 1)[1].split("\nmeta:", 1)[0]
    paths = {
        m.group(1)
        for m in re.finditer(r"^\s{2}(\S+):\s*\{", files_block, re.MULTILINE)
    }
    headerless = {p for p in paths if p.endswith(".json")}
    assert headerless, "no header-less (.json) registry files found — the parse broke"
    return headerless


def _exemption_tokens(sentence: str) -> list[str]:
    """The backticked path patterns an exemption sentence names."""
    return re.findall(r"`([^`]+)`", sentence)


def _is_exempted(path: str, tokens: list[str]) -> bool:
    """True iff some token covers ``path`` — ``settings/*.json`` covers a glob."""
    return any(fnmatch.fnmatch(path, token) for token in tokens)


# --- AC-4 ---------------------------------------------------------------------


def test_every_declared_link_has_a_junction_line() -> None:
    block = _windows_block()
    for link in sorted(_declared_links()):
        assert re.search(rf"mklink /J .*\\{link}\b", block), (
            f"the Windows block gives no `mklink /J` line for .claude/{link} — "
            "on a Windows clone that link stays a dead text file and everything "
            "under it silently disappears."
        )


def test_every_declared_link_has_a_skip_worktree_line() -> None:
    block = _windows_block()
    for link in sorted(_declared_links()):
        assert re.search(rf"skip-worktree .*\.claude/{link}\b", block), (
            f"the Windows block gives no `--skip-worktree` line for "
            f".claude/{link} — the junction then reads as a modification of the "
            "committed symlink, and the first `git commit -a` converts the repo."
        )


def test_every_declared_link_has_a_trailing_slash_ignore_rule() -> None:
    block = _windows_block()
    for link in sorted(_declared_links()):
        assert f"`.claude/{link}/`" in block, (
            f"the Windows block names no trailing-slash ignore rule "
            f"`.claude/{link}/` — without it `git add .` stages the junction's "
            "contents, replacing the symlink Linux and CI depend on. The "
            "trailing slash is what keeps the rule off the tracked symlink."
        )


def test_the_windows_block_explains_why_git_descends_into_a_junction() -> None:
    """Keyed on the mechanism, not a sentence, so a reword does not break it.

    The ignore rules look like a committed-mode violation to anyone applying
    step 6's audit literally. The block has to say *why* they are not, or the
    next reader narrows them away and reintroduces the trap.
    """
    block = _windows_block().lower()
    assert "descend" in block and "junction" in block and "symlink" in block, (
        "the Windows block no longer explains that git descends into a junction "
        "but not a symlink — that mechanism is the whole reason the ignore rules "
        "and --skip-worktree are both required."
    )


# --- AC-5 ---------------------------------------------------------------------


def _sentence_containing(marker: str) -> str:
    idx = _TEXT.find(marker)
    assert idx != -1, f"BOOTSTRAP.md no longer contains {marker!r}"
    start = _TEXT.rfind("**Exception", 0, idx)
    if start == -1 or idx - start > 400:
        start = max(_TEXT.rfind("\n", 0, idx), 0)
    end = _TEXT.find("\n", idx)
    return _TEXT[start : end if end != -1 else len(_TEXT)]


def test_step_2_no_clobber_exempts_every_headerless_file() -> None:
    sentence = _sentence_containing("carry no header by design")
    tokens = _exemption_tokens(sentence)
    for path in sorted(_headerless_registry_files()):
        assert _is_exempted(path, tokens), (
            f"step 2's no-clobber exception does not cover {path}, which carries "
            "no `guidance:` header — the installer would treat an existing copy "
            f"as a repo-owned collision and stop. Named there: {tokens}"
        )


def test_step_7_header_check_exempts_every_headerless_file() -> None:
    sentence = _sentence_containing("still carries its `guidance:` header")
    tokens = _exemption_tokens(sentence)
    for path in sorted(_headerless_registry_files()):
        assert _is_exempted(path, tokens), (
            f"step 7's header verification does not exempt {path}, which carries "
            "no `guidance:` header by design — a correct install would fail "
            f"verification. Named there: {tokens}"
        )
