"""``AGENTS.md`` / ``CLAUDE.md`` / ``GEMINI.md`` are byte-identical to the process doc.

One derived process artifact under four names. ``process/harness.md`` is the
canonical file the registry ships; each tool auto-loads a different name (Claude
→ ``CLAUDE.md``, Gemini → ``GEMINI.md``, Codex → ``AGENTS.md``), and
``BOOTSTRAP.md`` step 3 requires all three to be **byte-identical copies**, not
shims — a goal-directed agent reads the file it is handed rather than following
a pointer to a second one.

**This module is the home of that rule.** It used to live in a module about the
unattended routine commands, as one assertion among that ticket's own guards
(``test_routine_commands.py::test_process_doc_mirrors_byte_identical``), and it
was the *only* enforcer of mirror parity in the repo. When #435 retired the
routine commands, deleting that module would have taken the rule with it —
silently, because drift produces no error anywhere else: a hand-edit to
``process/harness.md`` alone still reads correctly to every human opening it,
and the divergence reaches consuming repos on their next ``/update-guidance``.
It is re-homed here, in a module named for the rule and for nothing else, so
that retiring any single feature cannot take it away again.

The predicate is a function, and the live test and the synthetic controls all
call it. A parity guard that hard-codes ``a.read_text() == b.read_text()`` inline
is only ever exercised against a tree that already passes, so it proves the tree
is currently consistent and nothing about whether the comparison can see drift.
"""

from __future__ import annotations

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
PROCESS_DOC = REPO_ROOT / "process" / "harness.md"

#: The three entry files, by the name each tool auto-loads.
MIRROR_NAMES = ("AGENTS.md", "CLAUDE.md", "GEMINI.md")


def drifted_mirrors(canonical: Path, mirrors: list[Path]) -> list[str]:
    """Names of the mirrors that are not byte-identical to ``canonical``.

    A missing mirror counts as drifted: an entry file that does not exist is the
    most complete drift there is, and returning an empty list for it would make
    deleting ``GEMINI.md`` the cheapest way to satisfy this module.
    """
    expected = canonical.read_bytes()
    return [m.name for m in mirrors if not m.is_file() or m.read_bytes() != expected]


# ---------------------------------------------------------------------------
# The live rule.
# ---------------------------------------------------------------------------


def test_the_entry_files_are_byte_identical_to_the_process_doc() -> None:
    """The rule itself, over the real tree."""
    mirrors = [REPO_ROOT / name for name in MIRROR_NAMES]
    drifted = drifted_mirrors(PROCESS_DOC, mirrors)
    assert drifted == [], (
        f"{drifted} drifted from process/harness.md. AGENTS.md, CLAUDE.md and "
        f"GEMINI.md are byte-identical copies of the canonical process doc "
        f"(BOOTSTRAP.md step 3) — edit process/harness.md and copy it over all "
        f"three, never the other way round."
    )


def test_all_three_mirrors_are_named_and_substantial() -> None:
    """The floor under the rule above.

    ``drifted_mirrors`` over an empty mirror list returns ``[]``, so the live
    test passes on a repo with no entry files at all. This pins that there are
    three of them, that each is tracked, and that the canonical doc is a real
    process document rather than a stub someone reduced all four files to.
    """
    assert len(MIRROR_NAMES) == 3, MIRROR_NAMES
    for name in MIRROR_NAMES:
        assert (REPO_ROOT / name).is_file(), f"{name} is missing from the repo root."
    assert len(PROCESS_DOC.read_text()) > 2000, (
        "process/harness.md is implausibly short for the shared process doc — "
        "byte-parity across four near-empty files proves nothing."
    )


# ---------------------------------------------------------------------------
# Controls on the predicate: it must see drift, and must not invent it.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("edit", "label"),
    (
        (lambda text: text + "\n", "one appended newline"),
        (lambda text: text.replace("process", "Process", 1), "one changed character"),
        (lambda text: text[:-1], "one removed byte"),
        (lambda text: text.replace("\n", "\r\n"), "line endings rewritten"),
    ),
)
def test_the_predicate_catches_a_single_byte_of_drift(
    tmp_path: Path, edit: object, label: str
) -> None:
    """The positive control, at the smallest edit that must be caught.

    Every one of these is a plausible accident — an editor adding a trailing
    newline, a sed run touching one file, a checkout normalising line endings —
    and each is exactly the drift that reaches a consuming repo unnoticed.
    """
    canonical = tmp_path / "harness.md"
    canonical.write_text("# process\n\nthe process doc\n")
    clean = tmp_path / "AGENTS.md"
    clean.write_text(canonical.read_text())
    dirty = tmp_path / "CLAUDE.md"
    dirty.write_text(edit(canonical.read_text()))  # type: ignore[operator]

    assert drifted_mirrors(canonical, [clean, dirty]) == ["CLAUDE.md"], (
        f"the parity predicate did not see {label} — a guard that cannot see "
        f"drift is not a guard."
    )


def test_the_predicate_reports_a_missing_mirror_as_drift(tmp_path: Path) -> None:
    """Deleting an entry file is drift, not compliance."""
    canonical = tmp_path / "harness.md"
    canonical.write_text("# process\n")
    assert drifted_mirrors(canonical, [tmp_path / "GEMINI.md"]) == ["GEMINI.md"]


def test_the_predicate_passes_true_copies(tmp_path: Path) -> None:
    """The negative control — no false positive on genuine copies.

    Without this, ``return [m.name for m in mirrors]`` would satisfy every
    assertion above while failing the whole repo, and the fix a maintainer would
    reach for is deleting the guard.
    """
    canonical = tmp_path / "harness.md"
    canonical.write_text("# process\n\nthe process doc\n")
    copies = []
    for name in MIRROR_NAMES:
        mirror = tmp_path / name
        mirror.write_bytes(canonical.read_bytes())
        copies.append(mirror)
    assert drifted_mirrors(canonical, copies) == []
