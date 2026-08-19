"""The landing page's inventory must name exactly the surface the tracked tree carries.

**What this replaces (#482).** `docs/index.html` used to catalogue the guidance
surface out of `registry.yaml`, and `scripts/check_landing_page_guidance.py`
held the catalogue to it. ADR 0017 deleted the registry and that guard with it,
leaving the page's catalogue unguarded — the state D8 accepted "until a proper
rebuild against a post-v5 source". Measured on `dev` at `27db85b` by diffing the
old page's `data-guidance` tags against `git ls-files`, the drift the unguarded
interval accumulated ran in both directions at once: the page named four skills
the tree does not have (`code-quality`, `engineering-principles`,
`spec-driven-development`, `test-driven-development`), one deleted agent
(`researcher`) and three deleted commands (`ship`, `start`,
`update-guidance`), while omitting three skills (`engineering`,
`github-issues`, `infrastructure`) and four commands (`capture`, `digest`,
`init`, `promote`) that do exist. This guard is the replacement, re-established
on the source that survived — the tree itself.

**Admitted under ADR 0017 D5 class (e), tree-consistency.** Both operands are in
the tracked tree: the page's `data-unit` tags and the files under `skills/`,
`commands/`, `agents/`, `hooks/`. It asserts that they *correspond* — nothing
about what any sentence on the page means. The one existing class-(e) module,
`tests/unit/test_accepted_proposals_cite_live_paths.py`, is the shape this
follows: one pure predicate, paired samples in both directions, a floor on each
set the comparison consumes, and a paired splice proving the reader reaches real
page bytes.

**Both directions, because a catalogue rots both ways.** A page entry with no
file behind it is the stale direction — what the retired guard caught. A tracked
unit the page never names is the admitting direction, and it is the half a
one-sided check misses: it is how the page silently under-describes the product
as the surface grows. `craft.md` → *ANY ALLOWLIST OR EXEMPTION NEEDS BOTH
DIRECTIONS*. `inventory_difference` returns both, and the sweep asserts both are
empty.

**Why the tracked tree and not the working tree.** The page ships to readers who
never see this machine. A guard reading `Path.glob` passes on the checkout that
wrote the page even when the file was never added, which answers a question
nobody asked. Both operands here read the index — the tree side through
:func:`tests._gitutil.tracked_files_under`, the page side through
:func:`indexed_text` — which is the same thing `git write-tree` certifies and
the gate marker is named after.

**How this guard is proved, and the one thing that cannot use the usual
instrument.** The predicate half is mutation-proved by ``scripts/mutate.py``:
seven entries covering the admitting direction, the frame-per-kind comparison,
the closed ``KINDS`` set, the parser's quote spellings, each floor, and the
reader itself — all killed as predicted. The *page* half cannot be proved that
way, and the reason is this module's own fix: ``mutate.py`` edits **working**
files, so once the reader moved to the staged blob an unstaged page edit became
correctly invisible to it, and three entries that had killed cleanly turned into
unprovable survivors overnight. The page operand is proved by **staged probe**
instead — stage a page with a unit deleted, renamed, or invented, observe the
red, restore the index — which is how the drift this guard exists for would
actually arrive. If you harden this module further, check which of its operands
your instrument can still reach before reading a survivor as a gap.
"""

from __future__ import annotations

import re
import subprocess
import tempfile
from pathlib import Path

from tests._gitutil import tracked_files_under
from tests.unit._prose import REPO_ROOT

#: The page this guard reads, repo-relative.
PAGE_PATH = "docs/index.html"

#: The kinds of unit the page tags. Enumerable, and closed: a tag naming
#: anything else is a failure rather than a silent drop, so the diff that
#: introduces a fifth kind answers the coverage question in place
#: (``craft.md`` → *A guard over an enumerable dimension must fail on an
#: unclassified member*).
KINDS = ("skill", "command", "agent", "hook")

#: An inventory tag: ``data-unit="skill:engineering"``. Both quote styles are
#: admitted because both are legal HTML and a page edit may reach for either;
#: a parser that goes silent on a correct page is a defect, not strictness
#: (#484, #487). The name charset is what a tracked directory or file stem can
#: hold, so a malformed tag fails to parse rather than matching loosely.
_UNIT_TAG = re.compile(
    r"""data-unit=(?P<q>["'])(?P<kind>[a-z][a-z-]*):(?P<name>[A-Za-z0-9][A-Za-z0-9._-]*)(?P=q)"""
)


def tagged_units(html: str) -> dict[str, set[str]]:
    """The units ``html`` declares, keyed by kind.

    Every kind in :data:`KINDS` is present in the result, empty where the page
    tagged none — so a caller comparing per kind cannot mistake "the page has no
    hooks section" for "hooks were not asked about".

    A tag naming a kind outside :data:`KINDS` raises. Dropping it would let a
    typo (``data-unit="skil:engineering"``) read as an omission from the
    ``skill`` set, which is a confusing failure, or — if the page also tagged it
    correctly elsewhere — as nothing at all.
    """
    found: dict[str, set[str]] = {kind: set() for kind in KINDS}
    for match in _UNIT_TAG.finditer(html):
        kind = match.group("kind")
        if kind not in found:
            raise AssertionError(
                f"{PAGE_PATH} tags a unit of unknown kind {kind!r} "
                f"(name {match.group('name')!r}); the kinds this guard knows are "
                f"{list(KINDS)}. Add the kind here with its tree derivation, or "
                f"fix the tag."
            )
        found[kind].add(match.group("name"))
    return found


def tree_units(*, repo_root: Path = REPO_ROOT) -> dict[str, set[str]]:
    """The surface the *tracked* tree carries, keyed by the same kinds.

    Each derivation names the unit the way the tree does — a ``skills/``
    directory name, a file stem elsewhere — so the page's tag is the tree's own
    identifier and the comparison needs no translation table to go stale.
    """
    skills = tracked_files_under("skills", repo_root=repo_root)
    commands = tracked_files_under("commands", repo_root=repo_root)
    agents = tracked_files_under("agents", repo_root=repo_root)
    hooks = tracked_files_under("hooks", repo_root=repo_root)
    return {
        "skill": {path.parent.name for path in skills if path.name == "SKILL.md"},
        "command": {path.stem for path in commands if path.suffix == ".md"},
        "agent": {path.stem for path in agents if path.suffix == ".md"},
        "hook": {path.stem for path in hooks if path.suffix == ".js"},
    }


def inventory_difference(
    page: dict[str, set[str]], tree: dict[str, set[str]]
) -> dict[str, dict[str, list[str]]]:
    """Per kind, what each side has that the other does not.

    Returns only the kinds that actually differ, each as
    ``{"on_page_only": [...], "in_tree_only": [...]}``. ``on_page_only`` is the
    stale direction (the page names something that is gone); ``in_tree_only`` is
    the admitting direction (the tree grew and the page did not).
    """
    differences: dict[str, dict[str, list[str]]] = {}
    for kind in KINDS:
        on_page_only = sorted(page.get(kind, set()) - tree.get(kind, set()))
        in_tree_only = sorted(tree.get(kind, set()) - page.get(kind, set()))
        if on_page_only or in_tree_only:
            differences[kind] = {
                "on_page_only": on_page_only,
                "in_tree_only": in_tree_only,
            }
    return differences


def indexed_text(path: str, *, repo_root: Path = REPO_ROOT) -> str:
    """The bytes git has **staged** for ``path``.

    Not ``Path.read_text``. ``git write-tree`` certifies the index, the gate
    marker is named after the tree that write-tree produces, and a review
    verdict binds to that same oid — so the index is the only operand that
    answers "what will ship". Reading the working file instead certifies bytes
    that may never be committed: measured at review, a tree staging a page with
    a skill deleted, with the correct page restored on disk unstaged, passed
    this module 12/12 while `git write-tree` reported an oid whose page was
    wrong.

    This is the same choice :func:`tests._gitutil.tracked_files_under` makes for
    the other operand, so both halves of the comparison now read the index and
    the module docstring's claim about it is true of every derivation here.
    """
    completed = subprocess.run(
        ["git", "show", f":{path}"],
        cwd=repo_root,
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout


def _page_text() -> str:
    return indexed_text(PAGE_PATH)


# ---------------------------------------------------------------------------
# Floors — on the page operand and on the tree operand, one each
# ---------------------------------------------------------------------------


def test_the_page_is_tracked() -> None:
    """The subject must be in the index, not merely on this disk.

    The page is published from the repository. A guard that read the working
    tree would certify a file the machine that wrote it can see and a fresh
    clone cannot — passing on the only host where the question is moot (#484).
    """
    tracked = {
        path.relative_to(REPO_ROOT).as_posix() for path in tracked_files_under("docs")
    }
    assert PAGE_PATH in tracked, (
        f"{PAGE_PATH} is not tracked by git, so nothing this guard reads reaches "
        f"a reader of the published page. Tracked under docs/: {sorted(tracked)}"
    )


def test_the_reader_follows_the_index_not_the_disk() -> None:
    """The operand is the staged blob, and this is the sample that says so.

    ``CLAUDE.md`` → *a guard asserts a property of the tracked tree, never the
    working directory*. :func:`test_the_page_is_tracked` does not reach this: it
    asserts the page's **path** is in the index and says nothing about the bytes
    read. Measured at review, before this test existed, a tree that staged a page
    with `skill:linear` deleted — with the correct page restored on disk, unstaged
    — passed this module 12/12 while `git write-tree` reported an oid whose page
    was wrong. That is the whole failure mode, and it is exactly the shape the
    module docstring claims not to have.

    The two contents differ in the direction that matters: the disk file carries
    a unit the staged one does not, so a reader that took the working tree would
    return the *superset* and read as more correct rather than less.
    """
    with tempfile.TemporaryDirectory() as raw:
        repo = Path(raw)
        subprocess.run(
            ["git", "init", "-q", "-b", "main"], cwd=repo, check=True
        )
        page = repo / "page.html"
        staged = '<li data-unit="skill:engineering"></li>\n'
        page.write_text(staged, encoding="utf-8")
        subprocess.run(["git", "add", "page.html"], cwd=repo, check=True)

        on_disk = staged + '<li data-unit="skill:linear"></li>\n'
        page.write_text(on_disk, encoding="utf-8")

        assert indexed_text("page.html", repo_root=repo) == staged, (
            "the reader returned something other than the staged blob"
        )
        assert page.read_text(encoding="utf-8") != staged, (
            "the fixture failed to diverge — this sample would pass either way"
        )
        assert tagged_units(indexed_text("page.html", repo_root=repo))["skill"] == {
            "engineering"
        }, "the parser read the working file's extra unit, not the staged one"


def test_the_tree_inventories_are_live() -> None:
    """Floor on the set the comparison consumes.

    ``craft.md`` → *The empty comparison set*: if ``tree_units`` derived to four
    empty sets, every page tag would report as stale and the sweep would fail —
    loudly, but for the wrong reason and pointing at the page. Worse, if the
    *page* were also emptied the sweep would go green over nothing at all.
    Membership is pinned rather than cardinality, so this floor cannot be
    satisfied by a count that a rename would silently keep whole.
    """
    tree = tree_units()
    anchors = {
        "skill": "engineering",
        "command": "build",
        "agent": "reviewer",
        "hook": "gate-evidence-guard",
    }
    for kind, anchor in anchors.items():
        assert anchor in tree[kind], (
            f"the {kind} derivation no longer contains {anchor!r} — it yielded "
            f"{sorted(tree[kind])}. Either that unit was renamed (update this "
            f"anchor in the same change) or the derivation stopped reading the tree."
        )


def test_the_page_declares_units_of_every_kind() -> None:
    """Floor on the *other* operand — the one a page rewrite can empty.

    ``craft.md`` → *Floor both measured operands*: the sweep below compares two
    derived sets, and flooring only the tree half leaves a parser that stopped
    matching indistinguishable from a page that legitimately lists nothing.
    Anchored by name for the same reason as above.
    """
    page = tagged_units(_page_text())
    anchors = {
        "skill": "engineering",
        "command": "build",
        "agent": "reviewer",
        "hook": "gate-evidence-guard",
    }
    for kind, anchor in anchors.items():
        assert anchor in page[kind], (
            f"the page declares no {kind} named {anchor!r} — parsed {sorted(page[kind])}. "
            f"Either the inventory dropped it or the `data-unit` tags stopped parsing."
        )


def test_the_parser_reads_the_real_page() -> None:
    """Paired splice: prove the reader reaches real page bytes.

    ``craft.md`` → *A prose mutation needs a paired splice to prove it was live*.
    The samples below all run over synthetic strings; nothing else here would
    notice a reader that had stopped resolving the page at all. Splicing a tag
    the parser is known to catch into the real text, and requiring it caught
    *there*, separates "the page parsed clean" from "the page was never read".
    """
    real = _page_text()
    spliced = "a-unit-this-repo-never-had"
    before = tagged_units(real)
    after = tagged_units(f'{real}\n<li data-unit="skill:{spliced}"></li>\n')
    assert "engineering" in before["skill"], (
        "the real page text yielded no units at all, so the splice assertions "
        "below would pass over an empty string — they prove only that the parser "
        "can parse a tag appended to whatever it was given. Measured: without "
        "this line, replacing the page reader with `return \"\"` left this test "
        "green (#482 mutation entry B6)."
    )
    assert spliced not in before["skill"], (
        "the splice token must not already be on the page, or its appearance "
        "afterwards proves nothing about the reader"
    )
    assert spliced in after["skill"], (
        "a tag spliced into the real page text was not parsed — the reader is "
        "not reaching real page bytes, and a clean sweep would be "
        "indistinguishable from a sweep that read nothing"
    )


# ---------------------------------------------------------------------------
# The predicate's teeth — paired samples, both directions
# ---------------------------------------------------------------------------

_TREE_SAMPLE = {
    "skill": {"engineering", "review-discipline"},
    "command": {"build", "routine"},
    "agent": {"reviewer"},
    "hook": {"gate-evidence-guard"},
}


def test_a_page_entry_with_no_file_behind_it_is_reported() -> None:
    """The stale direction — the job the deleted registry guard did.

    This is the shape that actually rotted: `test-driven-development` sat in the
    page's skill catalogue for the whole unguarded interval after v5 merged the
    skill away.
    """
    page = tagged_units('<li data-unit="skill:test-driven-development"></li>')
    assert inventory_difference(page, _TREE_SAMPLE)["skill"]["on_page_only"] == [
        "test-driven-development"
    ]


def test_a_tracked_unit_the_page_never_names_is_reported() -> None:
    """The admitting direction — the half a one-sided check cannot see.

    A page that lists a strict subset of the tree is wrong in the direction that
    grows over time, and every entry it *does* carry resolves. A stale-only
    sweep reads that as green forever.
    """
    page = tagged_units('<li data-unit="skill:engineering"></li>')
    assert inventory_difference(page, _TREE_SAMPLE)["skill"]["in_tree_only"] == [
        "review-discipline"
    ]


def test_an_agreeing_inventory_reports_nothing() -> None:
    """The passing direction, over every kind at once.

    Without this, a predicate that reported everything as a difference would
    satisfy both samples above and still be useless.
    """
    html = "".join(
        f'<li data-unit="{kind}:{name}"></li>'
        for kind, names in _TREE_SAMPLE.items()
        for name in names
    )
    assert inventory_difference(tagged_units(html), _TREE_SAMPLE) == {}


def test_a_difference_in_one_kind_does_not_mask_another() -> None:
    """Each kind is compared in its own frame.

    A predicate that pooled all four inventories into one set would let a
    command named like a skill cover for a missing skill, and would report a
    genuine difference under the wrong heading.
    """
    html = '<li data-unit="skill:engineering"></li><li data-unit="command:build"></li>'
    difference = inventory_difference(tagged_units(html), _TREE_SAMPLE)
    assert difference["skill"]["in_tree_only"] == ["review-discipline"]
    assert difference["command"]["in_tree_only"] == ["routine"]
    assert "agent" in difference and "hook" in difference


def test_a_unit_tagged_under_the_wrong_kind_is_reported() -> None:
    """Each kind is its own comparison frame, and this is what says so.

    ``craft.md`` → *A comparison whose operands live in different frames is
    constant*. `engineering` is a real skill, so a page tagging it as a
    *command* names nothing that exists in the command frame. A predicate that
    pooled the four inventories into one set would resolve it against the skills
    and report no difference at all.

    Measured: before this sample, replacing the per-kind difference with a
    pooled one survived the whole suite — the two samples that were supposed to
    cover it both happened to assert values the pooling left unchanged (#482
    mutation entry B5).
    """
    page = tagged_units('<li data-unit="command:engineering"></li>')
    assert inventory_difference(page, _TREE_SAMPLE)["command"]["on_page_only"] == [
        "engineering"
    ]


def test_both_quote_styles_parse() -> None:
    """A legal spelling the page may contain must not read as nothing.

    #484 and #487 are the same defect twice: a guard whose pattern admitted one
    spelling of its subject went silent on another that was equally correct. A
    single-quoted attribute is valid HTML, so it parses here.
    """
    assert tagged_units("<li data-unit='skill:engineering'></li>")["skill"] == {
        "engineering"
    }


def test_a_tag_of_unknown_kind_fails_loudly() -> None:
    """An unclassified member is a failure, never a silent drop.

    ``craft.md`` → *A guard over an enumerable dimension must fail on an
    unclassified member*. A mistyped kind would otherwise vanish, and the unit it
    named would be reported as missing from the page it is actually on.
    """
    try:
        tagged_units('<li data-unit="skil:engineering"></li>')
    except AssertionError as exc:
        assert "skil" in str(exc)
    else:
        raise AssertionError("a tag of unknown kind was accepted silently")


# ---------------------------------------------------------------------------
# The sweep — AC-2, over the real page and the real tree
# ---------------------------------------------------------------------------


def test_the_page_inventory_matches_the_tree() -> None:
    """AC-2: the published catalogue names exactly the surface the tree carries."""
    difference = inventory_difference(tagged_units(_page_text()), tree_units())
    assert not difference, (
        f"{PAGE_PATH}'s inventory has drifted from the tracked tree. "
        f"`on_page_only` names units the page advertises that no longer exist; "
        f"`in_tree_only` names units the tree carries that the page never "
        f"mentions. Both are wrong: {difference}"
    )
