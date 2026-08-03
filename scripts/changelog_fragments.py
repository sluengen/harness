#!/usr/bin/env python3
"""Per-change CHANGELOG fragments — the conflict class, removed at its source (#267).

Every ticket appended its entry to ``CHANGELOG.md``'s ``## [Unreleased]`` block,
so two concurrent runs conflicted there **by construction**: the same insertion
point, on a file whose correct merge semantics are "keep both lines". Run
``01KYR7T7B5E3QDC3WP7ZGYHTGV`` paid two full rebase → gate → re-review → close
rounds for it and the class went on to refuse a close on two further ticks.

A change now writes ``changelog.d/<ticket>.md``. Two runs touch two different
files, so there is nothing to conflict over, and the release folds the fragments
into ``CHANGELOG.md``'s released history.

``merge=union`` was rejected on direct evidence: in that same run both sessions
independently folded the *same* entries, which union merge duplicates silently
rather than resolves.

Three subcommands, one module, because the filename rule, the heading grammar
and the category set are format knowledge all three need:

* ``check`` — structural, base-independent, always meaningful. Every fragment
  parses.
* ``require`` — presence, diff-scoped against the merge base. **Abstains** where
  the base cannot be resolved rather than guessing.
* ``fold`` — assembles the fragments into a released section and deletes them.

``check`` and ``require`` are two guards, cause and symptom, because neither
subsumes the other: ``require`` is the direct check but must abstain on a
shallow CI checkout or a detached ``promote`` worktree, where the merge base is
unknowable. The base-independent half that actually holds the line is the
**ratchet** in :mod:`tests.unit.test_changelog_rotation` — ``CHANGELOG.md`` no
longer changes between releases, so its bounds moved from a headroom budget to
may-not-grow, and a direct append to ``[Unreleased]`` trips the gate wherever it
runs.

Stdlib only, plus one deliberate reuse: :func:`harness.branch_config.integration_branch`
already parses ``CONTEXT.md``'s ``branches.integration``, and a second regex over
that file would be a fresh drift source.

This is app, not distributed guidance (``specs/architecture-principles.md``), so
it carries no ``registry.yaml`` entry. Runs from ``scripts/verify.sh``.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

#: ``scripts/*.py`` -> ``parent.parent`` is the repo (or worktree) root.
REPO_ROOT = Path(__file__).resolve().parent.parent

#: The fragment directory, relative to the repo root.
FRAGMENT_DIRNAME = "changelog.d"

#: The one name in the directory that is not a fragment. A directory needs a
#: tracked file to exist in git at all, and that file is the format pointer.
README_NAME = "README.md"

#: "Keep a Changelog" categories, in the order the fold emits them. Closed set:
#: an unknown category word is a typo, and silently emitting it would put a
#: heading nobody greps for into the released history.
CATEGORIES = ("Added", "Changed", "Deprecated", "Removed", "Fixed", "Security")

#: The exemption category. ``### None — <why no entry is warranted> (#id)``
#: records the claim **as a file in the diff**, so a reviewer sees it, rather
#: than as a flag or a commit trailer that only the gate ever reads.
NONE_CATEGORY = "None"

#: A GitHub issue number (``270``) or a legacy Linear key (``CAL-1204``).
_TICKET = re.compile(r"^(?:\d+|[A-Z]{2,5}-\d+)$")

#: The reserved stem prefix for a change that has **no ticket by design** (#287).
#: Two such classes are known — an ``/assess`` report, whose no-merge-gate rule
#: ``commands/assess.md`` step 3 already states, and a ``/propose`` output. Both
#: previously reached exit 0 only via the empty-diff abstention, i.e. by being
#: gated at a moment the guard could see nothing; that is an accident, not a path.
NO_TICKET_PREFIX = "no-ticket-"

#: ``no-ticket-<slug>``: a lowercase slug, so the class is **disjoint** from
#: :data:`_TICKET` by construction — that admits only digits or an uppercase
#: Linear key. A malformed ticket stem (``27O.md``, ``cal-1204.md``) therefore
#: still matches neither and is still rejected. The charset admits no ``/``,
#: ``.`` or ``..``, so widening the stem class cannot smuggle a path into the
#: set :func:`fold` deletes.
_NO_TICKET_STEM = re.compile(rf"^{NO_TICKET_PREFIX}[a-z0-9]+(?:-[a-z0-9]+)*$")


def is_no_ticket_stem(stem: str) -> bool:
    """Is ``stem`` the reserved no-ticket exemption form (#287)?"""
    return _NO_TICKET_STEM.match(stem) is not None

#: ``### <Category> — <summary> (<#270|CAL-1204>)``. The em dash is the
#: separator the existing entries already use.
_HEADING = re.compile(r"^### (?P<category>\w+) — (?P<summary>.*?)\s*\((?P<id>#?[\w-]+)\)\s*$")


class FoldError(Exception):
    """The fold was asked to release nothing, or to write an unreadable file."""


@dataclass(frozen=True)
class Fragment:
    """One parsed ``changelog.d/<ticket>.md``."""

    path: Path
    ticket: str
    category: str
    body: str
    text: str

    @property
    def releasable(self) -> bool:
        """Exemptions are consumed by the fold but never emitted."""
        return self.category != NONE_CATEGORY


@dataclass(frozen=True)
class RequireResult:
    """The outcome of a presence check, including *why* it abstained."""

    exit_code: int
    message: str
    abstained: bool = False


# ---------------------------------------------------------------------------
# Enumeration and parsing.
# ---------------------------------------------------------------------------


def fragment_dir(repo_root: Path) -> Path:
    return repo_root / FRAGMENT_DIRNAME


def fragment_paths(repo_root: Path) -> list[Path]:
    """Every fragment file, sorted. Non-recursive, and ``README.md`` excluded.

    Non-recursive deliberately: :func:`fold` deletes exactly what this returns,
    so a nested directory must not be able to smuggle a path into that set.
    """
    directory = fragment_dir(repo_root)
    if not directory.is_dir():
        return []
    return sorted(
        p
        for p in directory.iterdir()
        if p.is_file() and p.name != README_NAME and p.suffix == ".md"
    )


def _parse(path: Path) -> tuple[Fragment | None, list[str]]:
    """Parse one fragment, or explain every way it is malformed."""
    problems: list[str] = []
    stem = path.stem
    no_ticket = is_no_ticket_stem(stem)
    if not _TICKET.match(stem) and not no_ticket:
        problems.append(
            f"{path.name}: filename must be <ticket>.md — a GitHub issue number "
            "(270.md) or a legacy Linear key (CAL-1204.md) — or, for a change "
            f"with no ticket by design, {NO_TICKET_PREFIX}<slug>.md carrying "
            "only '### None'."
        )

    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    if not lines or not lines[0].startswith("### "):
        problems.append(
            f"{path.name}: must open with an H3 heading "
            "'### <Category> — <summary> (#<ticket>)'."
        )
        return None, problems

    match = _HEADING.match(lines[0])
    if match is None:
        problems.append(
            f"{path.name}: heading {lines[0]!r} does not match "
            "'### <Category> — <summary> (#<ticket>)'."
        )
        return None, problems

    category = match.group("category")
    if category not in CATEGORIES and category != NONE_CATEGORY:
        problems.append(
            f"{path.name}: category {category!r} is not one of "
            f"{', '.join((*CATEGORIES, NONE_CATEGORY))}."
        )
    elif no_ticket and category != NONE_CATEGORY:
        # The invariant that keeps this class out of released history, and the
        # reason `fold` needs no change: a no-ticket fragment is never
        # `releasable`, so `_sort_key`'s `int(...)` never sees a non-numeric
        # stem and no entry is ever emitted naming an id that is not an issue.
        problems.append(
            f"{path.name}: {NO_TICKET_PREFIX}*.md may carry only "
            f"'### {NONE_CATEGORY} — <why>'; a releasable entry needs a "
            "ticket-named fragment."
        )

    raw_id = match.group("id")
    if no_ticket and raw_id.startswith("#"):
        # `#` means "GitHub issue". A no-ticket fragment names none, so writing
        # `(#no-ticket-…)` would invent an issue reference; the id goes bare,
        # exactly as a legacy `(CAL-1204)` does.
        problems.append(
            f"{path.name}: heading id {raw_id!r} — a {NO_TICKET_PREFIX}fragment "
            "names no issue; write the id without '#'."
        )

    heading_id = raw_id.lstrip("#")
    if heading_id != stem:
        problems.append(
            f"{path.name}: heading names ticket {heading_id!r} but the filename "
            f"says {stem!r} — one of the two is a copy-paste."
        )

    body = "\n".join(lines[1:]).strip("\n")
    if not body:
        problems.append(f"{path.name}: has a heading but no body.")
    for line in lines[1:]:
        if line.startswith("## "):
            problems.append(
                f"{path.name}: body contains an H2 line ({line!r}). The fold owns "
                "H2 — an injected one would split the released section."
            )
            break

    if problems:
        return None, problems
    return (
        Fragment(path=path, ticket=stem, category=category, body=body, text=text),
        [],
    )


def fragments(repo_root: Path) -> list[Fragment]:
    """Every well-formed fragment. Raises nothing — use :func:`check` for that."""
    out: list[Fragment] = []
    for path in fragment_paths(repo_root):
        fragment, _ = _parse(path)
        if fragment is not None:
            out.append(fragment)
    return out


def check(repo_root: Path) -> list[str]:
    """Every structural problem across the fragment directory."""
    problems: list[str] = []
    for path in fragment_paths(repo_root):
        _, found = _parse(path)
        problems.extend(found)
    return problems


# ---------------------------------------------------------------------------
# The fold.
# ---------------------------------------------------------------------------


def _sort_key(fragment: Fragment) -> tuple[int, int, str]:
    """Category order, then ticket id descending (newest first)."""
    category_rank = CATEGORIES.index(fragment.category)
    numeric = fragment.ticket.rpartition("-")[2]
    return (category_rank, -int(numeric) if numeric.isdigit() else 0, fragment.ticket)


def fold(
    repo_root: Path, *, version: str, date: str, write: bool = False
) -> str:
    """Assemble the fragments into one released section and delete them.

    Returns the section text. With ``write=True`` it is also inserted into
    ``CHANGELOG.md`` below the ``[Unreleased]`` window, which stays at the top
    for the next cycle.
    """
    parsed = fragments(repo_root)
    releasable = sorted(
        (f for f in parsed if f.releasable), key=_sort_key
    )
    if not releasable:
        raise FoldError(
            f"no releasable fragments in {FRAGMENT_DIRNAME}/ — nothing to fold "
            "into a release section."
        )

    section = f"## [{version}] — {date}\n\n" + "\n".join(
        f.text if f.text.endswith("\n") else f.text + "\n" for f in releasable
    )

    if write:
        _insert_section(repo_root / "CHANGELOG.md", section)

    directory = fragment_dir(repo_root).resolve()
    for fragment in parsed:
        target = fragment.path.resolve()
        # Bounded by construction: exactly the paths the (non-recursive)
        # enumeration returned, each asserted a direct child of the fragment
        # directory, unlinked one at a time. Never a shell glob, never rmtree,
        # never a followed symlink.
        if target.parent != directory:
            raise FoldError(f"refusing to delete {target} — outside {directory}")
        target.unlink()

    return section


def _insert_section(changelog: Path, section: str) -> None:
    """Insert ``section`` after the ``[Unreleased]`` window."""
    text = changelog.read_text(encoding="utf-8")
    marker = "## [Unreleased]"
    index = text.find(marker)
    if index == -1:
        raise FoldError(f"{changelog} has no '{marker}' heading to insert below.")
    nxt = text.find("\n## ", index + len(marker))
    at = len(text) if nxt == -1 else nxt + 1
    changelog.write_text(
        text[:at].rstrip("\n") + "\n\n" + section.rstrip("\n") + "\n" + text[at:],
        encoding="utf-8",
    )


# ---------------------------------------------------------------------------
# The presence check.
# ---------------------------------------------------------------------------


def _git(repo_root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603  # list form, no shell, repo-controlled refs
        ["git", *args],  # noqa: S607  # git resolved from PATH, as everywhere else
        cwd=repo_root,
        check=False,
        capture_output=True,
        text=True,
    )


def _default_base(repo_root: Path) -> str:
    """``origin/<integration>`` from CONTEXT.md, falling back to ``origin/dev``."""
    try:
        from harness.branch_config import integration_branch
    except ImportError:  # pragma: no cover - harness always importable in-repo
        return "origin/dev"
    return f"origin/{integration_branch(repo_root) or 'dev'}"


def require(repo_root: Path, *, base: str | None = None) -> RequireResult:
    """Does this change carry a changelog fragment (or an exemption)?

    Abstains — exit 0 with a printed reason — where the answer is unknowable:
    an unresolvable base ref (a shallow ``actions/checkout`` fetch, a detached
    ``promote`` worktree) or an empty diff (HEAD *is* the integration branch).
    Abstaining loudly is the honest option; guessing would either wave changes
    through silently or fail the gate for an environment's sake.
    """
    ref = base or _default_base(repo_root)

    resolved = _git(repo_root, "rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}")
    if resolved.returncode != 0:
        return RequireResult(
            0,
            f"changelog fragment check abstained: base ref {ref!r} does not "
            "resolve here (shallow checkout or detached worktree).",
            abstained=True,
        )

    merge_base = _git(repo_root, "merge-base", "HEAD", ref)
    if merge_base.returncode != 0:
        return RequireResult(
            0,
            f"changelog fragment check abstained: no merge base between HEAD and "
            f"{ref!r}.",
            abstained=True,
        )

    diff = _git(
        repo_root, "diff", "--name-only", merge_base.stdout.strip(), "HEAD"
    )
    if diff.returncode != 0:
        return RequireResult(
            0,
            f"changelog fragment check abstained: could not diff against {ref!r}.",
            abstained=True,
        )

    changed = [line for line in diff.stdout.splitlines() if line.strip()]
    if not changed:
        return RequireResult(
            0,
            f"changelog fragment check abstained: no change against {ref!r} — HEAD "
            "carries no commits beyond it (the integration branch itself, or a "
            "run branch whose work is not committed yet).",
            abstained=True,
        )

    carried = [
        p
        for p in changed
        if p.startswith(f"{FRAGMENT_DIRNAME}/")
        and p.endswith(".md")
        and not p.endswith(f"/{README_NAME}")
    ]
    if carried:
        # Presence detection is unchanged — only the stated *reason* is new
        # (#287). A ticket-shaped stem is the stronger claim, so a diff carrying
        # both says the plain thing; the ticket-less wording is reserved for the
        # case that previously had no honest way past this guard at all.
        no_ticket = [p for p in carried if is_no_ticket_stem(Path(p).stem)]
        if no_ticket and len(no_ticket) == len(carried):
            names = ", ".join(sorted(Path(p).name for p in no_ticket))
            return RequireResult(
                0,
                f"changelog fragment present: {names} — a ticket-less change, "
                "exempt by the no-ticket fragment it carries.",
            )
        return RequireResult(0, "changelog fragment present.")
    if "CHANGELOG.md" in changed:
        # The release fold is itself the record.
        return RequireResult(0, "CHANGELOG.md edited directly (release fold).")

    return RequireResult(
        1,
        f"this change touches {len(changed)} file(s) but adds no changelog "
        f"fragment. Add {FRAGMENT_DIRNAME}/<ticket>.md carrying "
        "'### <Category> — <summary> (#<ticket>)' and a body. If the change "
        f"genuinely warrants no entry, record that as "
        f"'### {NONE_CATEGORY} — <why> (#<ticket>)' in the same place — the "
        "exemption is a file in the diff so a reviewer sees the claim. If it "
        "has no ticket at all — an /assess report, a /propose output — name the "
        f"file {FRAGMENT_DIRNAME}/{NO_TICKET_PREFIX}<slug>.md and give it the "
        f"same '### {NONE_CATEGORY} — <why> ({NO_TICKET_PREFIX}<slug>)' heading.",
    )


# ---------------------------------------------------------------------------
# CLI.
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("check", help="validate every fragment's structure")
    require_parser = sub.add_parser(
        "require", help="fail if this change carries no fragment"
    )
    require_parser.add_argument("--base", default=None)
    fold_parser = sub.add_parser("fold", help="assemble fragments into CHANGELOG.md")
    fold_parser.add_argument("--version", required=True)
    fold_parser.add_argument("--date", required=True)

    args = parser.parse_args(argv)
    root = args.repo_root.resolve()

    if args.command == "check":
        problems = check(root)
        for problem in problems:
            print(f"changelog fragment: {problem}", file=sys.stderr)
        if problems:
            print(
                f"{len(problems)} malformed fragment(s) in {FRAGMENT_DIRNAME}/ — see "
                "RELEASING.md for the format.",
                file=sys.stderr,
            )
            return 1
        return 0

    if args.command == "require":
        result = require(root, base=args.base)
        stream = sys.stderr if result.exit_code else sys.stdout
        print(result.message, file=stream)
        return result.exit_code

    try:
        section = fold(root, version=args.version, date=args.date, write=True)
    except FoldError as exc:
        print(f"changelog fold: {exc}", file=sys.stderr)
        return 1
    print(section)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
