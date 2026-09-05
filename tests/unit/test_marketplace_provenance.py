"""The repo that publishes the marketplace must declare where the plugin comes from.

**The occurrence this guard cites (#484).** The first performed consumer
migration (nano-erp, 2026-08-18) left a repo whose ``.claude/settings.json``
enables ``harness@harness`` and says nothing about the marketplace that name
resolves through. On a machine that had separately run ``/plugin marketplace add
sluengen/harness`` it worked; on a fresh clone it resolved to nothing — no
commands, no skills, and no enforcement hooks — with no error naming what was
missing. The failure is silent in exactly the fresh-clone case where enforcement
matters most.

**Why this shape, and not a check on ``commands/init.md``.** The ticket asked
for a test that the init command's *instructions name* the declaration. That is a
restatement pin on prose, and ADR 0017 D5 admits no such class. What is
admissible is class **(e)** tree-consistency, with class **(b)** supplying one
operand: two tracked, machine-readable artifacts must correspond. The harness
repo publishes a marketplace (``.claude-plugin/marketplace.json``) and its spine
names the GitHub repository that marketplace is fetched from
(``CLAUDE.md`` → ``github.repo``). The declaration in ``.claude/settings.json``
must agree with both. Nothing here reads what any sentence means.

**What this repo is, and is not.** It publishes the marketplace and declares
it; it does not *enable* the plugin, and ``.claude/settings.json`` carries no
``enabledPlugins``. ``.claude/hooks`` is a symlink to the plugin's own
``hooks/`` and that settings file wires those files directly, so enabling
``harness@harness`` here would register ``hooks/hooks.json`` on top of the same
five hooks and fire each of them twice. The declaration is the half that costs
nothing and the half a fresh clone needs, so this guard asserts the declaration
and claims nothing about an enablement.

**Where the teeth are.** :func:`provenance_findings` is one pure predicate and
every sample calls it, so a change to how the tree is judged changes what every
sample measures. The expected values are *derived* from the two manifests rather
than written down —
:func:`test_a_wholly_different_repo_passes_on_its_own_values` is what separates a
derivation from a hardcoded constant: it feeds a settings blob and manifests that
share nothing with this repo's and requires a clean result, so a predicate that
had simply memorised ``harness`` and ``sluengen/harness`` fails there.

The failure directions are sampled in both senses, because an exemption or a
match bounded from one side only is this repo's most-shipped defect: a missing
declaration, a right-name/wrong-repo pair, a wrong-name/right-repo pair, the
**unwrapped** source shape (the one the platform does not read), and a
non-GitHub source each produce a finding.

:func:`test_the_declaration_reaches_a_fresh_clone` closes the layer below all
of this: every check here reads the working tree, and a settings file that is
gitignored or never added passes them all while shipping nothing to the clone
this guard exists to protect.

:func:`test_the_tracked_settings_file_is_actually_read` is the anti-vacuity
spine. Without it, a reader that silently failed to reach
``.claude/settings.json`` — a moved file, a renamed key, a swallowed parse —
would report a clean tree forever. It splices the declaration back out of the
real file's own bytes and requires the finding to appear.
"""

from __future__ import annotations

import json
import re
from typing import Any

from tests._gitutil import tracked_files_under
from tests.unit._prose import REPO_ROOT

_SETTINGS = REPO_ROOT / ".claude" / "settings.json"
_MARKETPLACE = REPO_ROOT / ".claude-plugin" / "marketplace.json"
#: #537 moved the configuration map out of the spine's prose and into
#: ``harness.yaml``, so the declaration this module corresponds against lives
#: there now. The extractor still accepts a fenced block, because the repos this
#: plugin ships to have not migrated and their declaration is still in a spine.
_SPINE = REPO_ROOT / "harness.yaml"

#: The settings key Claude Code reads a repository's extra marketplaces from.
#: Measured against the shipped CLI (2.1.234), whose own settings schema
#: describes it as "Additional marketplaces to make available for this
#: repository. Typically used in repository .claude/settings.json to ensure team
#: members have required plugin sources."
DECLARATION_KEY = "extraKnownMarketplaces"

#: ``github:`` block, then its ``repo:`` member. Anchored to the nesting rather
#: than to a bare ``repo:`` because the spine's first block is *also* keyed
#: ``repo:`` — a naive scan reads the wrong one the moment that block gains a
#: same-line value. The value half tolerates the two spellings the *same* yaml
#: block already uses on sibling lines: a quoted scalar (every ``commands:``
#: value is quoted) and a trailing ``#`` comment (``stack.language``,
#: ``branches.release`` and both ``layers:`` members carry one). A bare ``\S+``
#: against an end anchor swallows the quotes into the repo name and matches
#: nothing at all past a comment, so either spelling reddens the gate over a
#: spine that is still correct; ``tests/unit/_prose.py``'s ``PROPOSAL_STATUS``
#: carries the same ``(?:#.*)?$`` tolerance on the same shape.
_SPINE_GITHUB_REPO = re.compile(
    r"^github:\s*$\n(?:^[ \t]+.*$\n)*?"
    r"^[ \t]+repo:[ \t]*['\"]?(?P<repo>[^\s'\"#]+)['\"]?[ \t]*(?:#.*)?$",
    re.MULTILINE,
)


def spine_github_repo(spine_text: str) -> str | None:
    """Return the ``github.repo`` the spine names, or ``None`` if it names none."""
    match = _SPINE_GITHUB_REPO.search(spine_text)
    return match.group("repo") if match else None


def provenance_findings(
    settings: Any, *, marketplace_name: str, expected_repo: str
) -> list[str]:
    """Return why ``settings`` fails to declare ``marketplace_name``'s source.

    Empty means the declaration is present and corresponds to both manifests.
    """
    if not isinstance(settings, dict):
        return ["settings are not a JSON object"]

    declared = settings.get(DECLARATION_KEY)
    if declared is None:
        return [f"no {DECLARATION_KEY} declaration"]
    if not isinstance(declared, dict):
        return [f"{DECLARATION_KEY} is not a JSON object"]

    entry = declared.get(marketplace_name)
    if entry is None:
        return [
            f"{DECLARATION_KEY} declares {sorted(declared)} "
            f"but not the published marketplace {marketplace_name!r}"
        ]
    if not isinstance(entry, dict):
        return [f"the {marketplace_name!r} entry is not a JSON object"]

    source = entry.get("source")
    if not isinstance(source, dict):
        return [
            f"the {marketplace_name!r} entry has no wrapped source object "
            "(the platform reads entry.source, not a bare source)"
        ]

    findings = []
    if source.get("source") != "github":
        findings.append(
            f"the {marketplace_name!r} source is {source.get('source')!r}, not 'github'"
        )
    if source.get("repo") != expected_repo:
        findings.append(
            f"the {marketplace_name!r} source names {source.get('repo')!r}, "
            f"but the spine names {expected_repo!r}"
        )
    return findings


def _published_marketplace_name() -> str:
    manifest = json.loads(_MARKETPLACE.read_text(encoding="utf-8"))
    name = manifest["name"]
    assert isinstance(name, str) and name, "marketplace.json declares no name"
    return name


def _expected_repo() -> str:
    repo = spine_github_repo(_SPINE.read_text(encoding="utf-8"))
    assert repo, "the spine names no github.repo to correspond with"
    return repo


def test_the_repo_declares_the_marketplace_it_publishes() -> None:
    """The tracked settings must point at the marketplace this repo is."""
    settings = json.loads(_SETTINGS.read_text(encoding="utf-8"))
    findings = provenance_findings(
        settings,
        marketplace_name=_published_marketplace_name(),
        expected_repo=_expected_repo(),
    )
    assert findings == [], (
        "a fresh clone cannot resolve this repo's own plugin: "
        + "; ".join(findings)
    )


def test_the_tracked_settings_file_is_actually_read() -> None:
    """Paired splice on the real bytes: clean before, a finding after.

    Both halves are asserted here on purpose. A one-sided splice would pass while
    the settings were failing for some *other* reason, which is the state this
    guard was written in — so the difference, not the finding, is the evidence.
    """
    name = _published_marketplace_name()
    expected = _expected_repo()

    intact = json.loads(_SETTINGS.read_text(encoding="utf-8"))
    assert (
        provenance_findings(intact, marketplace_name=name, expected_repo=expected) == []
    )

    spliced = json.loads(_SETTINGS.read_text(encoding="utf-8"))
    removed = spliced.get(DECLARATION_KEY, {}).pop(name, None)
    assert removed is not None, "nothing was spliced out — the reader missed the key"

    assert provenance_findings(
        spliced, marketplace_name=name, expected_repo=expected
    ), "removing the declaration from the real settings changed nothing"


def test_a_wholly_different_repo_passes_on_its_own_values() -> None:
    """The predicate is a function of its inputs, not of this repo's constants."""
    settings = {
        DECLARATION_KEY: {
            "otherplace": {"source": {"source": "github", "repo": "someone/elsewhere"}}
        }
    }
    assert (
        provenance_findings(
            settings, marketplace_name="otherplace", expected_repo="someone/elsewhere"
        )
        == []
    )


def test_the_same_blob_fails_against_this_repos_values() -> None:
    """The other direction of the derivation: right shape, wrong subject."""
    settings = {
        DECLARATION_KEY: {
            "otherplace": {"source": {"source": "github", "repo": "someone/elsewhere"}}
        }
    }
    assert provenance_findings(
        settings, marketplace_name="harness", expected_repo="sluengen/harness"
    )


def test_a_missing_declaration_is_a_finding() -> None:
    """The nano-erp shape: the plugin enabled, its origin undeclared."""
    settings = {"enabledPlugins": {"harness@harness": True}}
    assert provenance_findings(
        settings, marketplace_name="harness", expected_repo="sluengen/harness"
    )


def test_the_right_name_pointing_at_the_wrong_repo_is_a_finding() -> None:
    settings = {
        DECLARATION_KEY: {
            "harness": {"source": {"source": "github", "repo": "someone/fork"}}
        }
    }
    assert provenance_findings(
        settings, marketplace_name="harness", expected_repo="sluengen/harness"
    )


def test_the_right_repo_under_the_wrong_name_is_a_finding() -> None:
    """The name is the key the enablement resolves through; a synonym is not it."""
    settings = {
        DECLARATION_KEY: {
            "harness-plugin": {
                "source": {"source": "github", "repo": "sluengen/harness"}
            }
        }
    }
    assert provenance_findings(
        settings, marketplace_name="harness", expected_repo="sluengen/harness"
    )


def test_an_unwrapped_source_is_a_finding() -> None:
    """The shape the platform does not read — measured, not assumed.

    The entry value wraps its source: the CLI builds its own official-marketplace
    fallback as ``{source: {source: "github", repo: ...}}`` and reads
    ``entry.autoUpdate`` off the same object, and ``known_marketplaces.json``
    stores that wrapper on disk. A bare source object is a plausible-looking
    file that silently declares nothing.
    """
    settings = {DECLARATION_KEY: {"harness": {"source": "github", "repo": "sluengen/harness"}}}
    assert provenance_findings(
        settings, marketplace_name="harness", expected_repo="sluengen/harness"
    )


def test_a_non_github_source_is_a_finding() -> None:
    """The source *type* is checked on its own, not incidentally.

    This sample names the right repository under the wrong source type, so the
    repo comparison is satisfied and only the type check can catch it. A sample
    that also got the repo wrong would pass with the type check deleted.
    """
    settings = {
        DECLARATION_KEY: {
            "harness": {
                "source": {
                    "source": "git",
                    "url": "git@example.com:sluengen/harness.git",
                    "repo": "sluengen/harness",
                }
            }
        }
    }
    assert provenance_findings(
        settings, marketplace_name="harness", expected_repo="sluengen/harness"
    )


def test_the_spine_repo_is_read_from_the_github_block() -> None:
    """Derivation again, one level down: a different spine yields its own answer.

    The decoy is load-bearing and is written to discriminate. ``repo:`` is not a
    key unique to the ``github:`` block — the spine's own first block is keyed
    that way, and a tracker or mirror block can carry a same-line coordinate — so
    a scan that took the first ``repo:`` value it saw would return a neighbour's.
    The block below puts exactly that value in front of the real one.
    """
    spine = (
        "```yaml\n"
        "repo:\n"
        "  name: elsewhere\n"
        "tracker: github\n"
        "mirror:\n"
        "  repo: someone/wrong\n"
        "github:\n"
        "  repo: someone/elsewhere\n"
        "  project: someone/9\n"
        "```\n"
    )
    assert spine_github_repo(spine) == "someone/elsewhere"


def test_a_trailing_comment_does_not_swallow_the_repo_line() -> None:
    r"""A spelling the guarded block already uses on sibling lines of its own.

    ``stack.language``, ``commands.bootstrap``, ``branches.release`` and both
    ``layers:`` members each carry a trailing ``#`` comment in this repo's own
    spine. Under ``\S+`` and an
    end anchor the same spelling on ``repo:`` matches nothing, :func:`_expected_repo`
    raises, and the gate goes red over a spine that is still correct — a red the
    reviewer reproduced by splicing exactly that comment into ``CLAUDE.md``. The
    value differs from this repo's, so a parser that memorised the answer fails
    here too.
    """
    spine = (
        "```yaml\n"
        "github:\n"
        "  repo: someone/elsewhere   # the canonical remote\n"
        "  project: someone/9\n"
        "```\n"
    )
    assert spine_github_repo(spine) == "someone/elsewhere"


def test_a_quoted_repo_value_is_read_without_its_quotes() -> None:
    """The block's other spelling: every ``commands:`` value in it is quoted.

    Unquoting is not cosmetic. The captured value is compared against the
    settings' ``repo``, so quotes carried into the capture report a mismatch
    between two strings a reader can see are equal.
    """
    spine = '```yaml\ngithub:\n  repo: "someone/elsewhere"\n```\n'
    assert spine_github_repo(spine) == "someone/elsewhere"


def test_a_github_block_whose_repo_line_carries_no_value_yields_none() -> None:
    """The admitting direction of the tolerance above, which nothing else samples.

    Unquoting and comment-stripping each loosen what may follow ``repo:``, and a
    loosening bounded from one side only is this repo's most-shipped defect. An
    empty capture would be a repo name no settings file can equal, so the guard
    would report a *mismatch* where the truth is that the spine names nothing —
    and the comment spelling is the sharper of the two, because the comment is
    exactly what would stand in for the missing value.
    """
    assert spine_github_repo("```yaml\ngithub:\n  repo:\n  project: someone/9\n```\n") is None
    assert spine_github_repo("```yaml\ngithub:\n  repo:   # to be filled in\n```\n") is None


def test_a_spine_naming_no_github_repo_yields_none() -> None:
    """A ``tracker: none`` repo has no coordinate, and must not fabricate one."""
    spine = "```yaml\nrepo:\n  name: elsewhere\ntracker: none\n```\n"
    assert spine_github_repo(spine) is None


def test_the_live_spine_still_parses() -> None:
    """The parser is pinned against the real spine, not only synthetic text."""
    assert spine_github_repo(_SPINE.read_text(encoding="utf-8")) == "sluengen/harness"


def test_the_declaration_reaches_a_fresh_clone() -> None:
    """The settings file must be in the index, not merely on this disk.

    Reading the working tree answers a question nobody asked. The bug this guard
    exists for *is* the fresh clone: a `.claude/settings.json` that is gitignored
    or simply never added satisfies every check above on the machine that wrote
    it and ships nothing to anyone else — the same silent degradation, one layer
    down. Class (e) asks that both operands live in the tracked tree, so this
    asserts the operand does.
    """
    assert _SETTINGS.resolve() in tracked_files_under(".claude", repo_root=REPO_ROOT), (
        f"{_SETTINGS} is not tracked — a clone would not receive the declaration"
    )
