"""CAL-654 — every ``skills/`` path cited in distributed prose resolves.

The installed surface ships prose that points readers at skill files: most
load-bearingly, ``agents/dev.md`` and ``commands/start.md`` name
``skills/test-driven-development/SKILL.md`` and ``skills/code-quality/SKILL.md``
as the **mandatory pre-build reads**. A cite that resolves to nothing is worse
than no cite: it sends an agent in a consuming repo to a path that does not
exist.

This class has already bitten once. CAL-646 promoted the harness to the
guidance source but shipped the skills **flat** (``skills/<id>.md``), so the
``skills/<id>/SKILL.md`` cites in ``dev.md`` / ``start.md`` resolved to nothing;
CAL-658 migrated the tree to the Agent-Skills ``skills/<id>/SKILL.md`` shape and
repaired them. Nothing *prevented* the break, and nothing prevents the next one
— a new cite, or a future re-shaping of the tree, can re-break a mandatory read
silently.

This guard turns that into one structural check: it greps every git-tracked
file under the installed surface for a skill-file cite and fails if any does not
resolve to a real tracked file. It is the reference-resolution sibling of the
footprint / boundary guards (CAL-647/648, ``test_guidance_footprint``) and of
``test_retired_spec_cites`` (CAL-633).

Scope (the narrow resolvable-cite class only): a *skill cite* is a path of the
Agent-Skills shape ``skills/<id>/SKILL.md`` or the legacy flat ``skills/<id>.md``
— i.e. a ``skills/`` path ending in ``.md``. The ``.md`` terminus is what
separates a genuine file-path cite from prose that merely contains the substring
``skills/`` — e.g. the ``skills/agents/commands/process/templates`` directory
list in ``hooks/guidance-freshness.js``, or a ``<id>``-shaped placeholder. This
guard does **not** police prose that names a skill without citing its path.

Acceptance criteria (this ticket):

* **AC-1** — the guard fails when a distributed file cites a ``skills/...`` path
  that does not resolve to a real file. Proven by
  :func:`test_resolver_flags_a_nonexistent_skill_cite` and the regex
  ``_MATCH`` / ``_NO_MATCH`` boundary tests.
* **AC-2** — after the CAL-658 migration, every cited ``skills/<id>/SKILL.md``
  path resolves. Proven by :func:`test_every_distributed_skill_cite_resolves`,
  anchored non-vacuous by
  :func:`test_scanner_finds_the_mandatory_pre_build_reads`.
"""

from __future__ import annotations

import re

import pytest

from tests._gitutil import tracked_files_under
from tests.unit._prose import REPO_ROOT

#: The installed surface — the directories ``registry.yaml`` ships into a
#: consuming repo (the ``SURFACE_PREFIXES`` of ``test_guidance_footprint``).
#: These carry the distributed prose a skill cite can appear in.
SURFACE_DIRS = (
    "commands",
    "agents",
    "skills",
    "templates",
    "hooks",
    "process",
    "settings",
)

# A skill cite is a ``skills/`` path ending in ``.md``: the Agent-Skills
# ``skills/<id>/SKILL.md`` shape (D2; CAL-658) or the legacy flat
# ``skills/<id>.md`` (which a stale cite would still use, and which this guard
# must catch as non-resolving). ``[\w-]+`` is the skill id (kebab-case, no
# dots). The ``.md`` terminus + ``\b`` boundary is the discriminator: it
# excludes prose that contains ``skills/`` without citing a file — a
# slash-joined directory list (``skills/agents/commands/process/templates``, no
# ``.md``), a bare mention of the ``skills/`` directory, a ``<id>`` placeholder
# (``<`` is not in ``[\w-]``), or a longer extension (``.markdown`` — the ``\b``
# stops ``.md`` matching inside it).
_SKILL_CITE = re.compile(r"skills/[\w-]+(?:/SKILL)?\.md\b")


def _skill_cites_in(text: str) -> list[tuple[int, str]]:
    """Return ``(line_number, cited_path)`` for each skill-file cite in ``text``."""
    cites: list[tuple[int, str]] = []
    for line_no, line in enumerate(text.splitlines(), start=1):
        for match in _SKILL_CITE.finditer(line):
            cites.append((line_no, match.group(0)))
    return cites


# The regex boundary contract, pinned by example. ``match`` cases are genuine
# skill-file cites the guard MUST extract (and then resolve); ``no-match`` cases
# are prose that contains ``skills/`` but cites no file and must NOT be flagged.
_MATCH = [
    "read skills/test-driven-development/SKILL.md before you write code",
    "open `skills/code-quality/SKILL.md` first",
    "skills/architecture/SKILL.md,",          # trailing comma — \b still ends it
    "see skills/design-system.md",            # legacy flat shape — a stale cite
]
_NO_MATCH = [
    "a universal prose file (skills/agents/commands/process/templates)",  # dir list
    "the skills/ directory",                  # bare directory mention
    "skills/<id>/SKILL.md is the shape",      # placeholder — < is not a path char
    "skills/foo.markdown notes",              # longer extension — \b guards .md
    "the design-system skill",                # names a skill, cites no path
]


@pytest.mark.parametrize("sample", _MATCH)
def test_skill_cite_regex_matches_genuine_cites(sample: str) -> None:
    assert _SKILL_CITE.search(sample), f"{sample!r} should be read as a skill-file cite"


@pytest.mark.parametrize("sample", _NO_MATCH)
def test_skill_cite_regex_ignores_non_path_prose(sample: str) -> None:
    assert not _SKILL_CITE.search(sample), f"{sample!r} must not be read as a cite"


def test_resolver_flags_a_nonexistent_skill_cite() -> None:
    """The resolution check fails a cite whose path is not a tracked file (AC-1).

    Pins the mechanism the sweep relies on: a cite resolves only if its path is
    in the git-tracked set. A made-up skill id must therefore *not* resolve,
    while the two mandatory pre-build reads must.
    """
    tracked = tracked_files_under(".")
    missing = (REPO_ROOT / "skills/does-not-exist/SKILL.md").resolve()
    present = (REPO_ROOT / "skills/code-quality/SKILL.md").resolve()
    assert missing not in tracked, "a non-existent skill cite must not resolve"
    assert present in tracked, "an existing skill cite must resolve"


def test_scanner_finds_the_mandatory_pre_build_reads() -> None:
    """Anchor the sweep non-vacuous: the known mandatory reads are seen (AC-2).

    Guards against a scanner that silently extracts nothing, which would make
    the resolution sweep pass without checking anything.
    """
    found: set[str] = set()
    for name in ("agents/dev.md", "commands/start.md"):
        for _, cite in _skill_cites_in((REPO_ROOT / name).read_text()):
            found.add(cite)
    assert "skills/test-driven-development/SKILL.md" in found
    assert "skills/code-quality/SKILL.md" in found


def test_every_distributed_skill_cite_resolves() -> None:
    """Every skill cite in the installed surface resolves to a tracked file (AC-2).

    Sweeps git-tracked files under the surface dirs; a cite resolves only if its
    path is in the tracked set (committed tree, per ``tests/_gitutil``).
    """
    tracked = tracked_files_under(".")
    violations: list[str] = []
    for surface_dir in SURFACE_DIRS:
        for path in sorted(tracked_files_under(surface_dir)):
            for line_no, cite in _skill_cites_in(path.read_text()):
                if (REPO_ROOT / cite).resolve() not in tracked:
                    rel = path.relative_to(REPO_ROOT).as_posix()
                    violations.append(f"{rel}:{line_no}: {cite}")

    assert not violations, (
        "distributed prose cites a skills/ path that does not resolve to a real "
        "file (a mandatory read pointing at nothing — see CAL-654):\n  "
        + "\n  ".join(violations)
    )
