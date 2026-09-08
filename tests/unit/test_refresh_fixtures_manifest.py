"""``tests/fixtures/refresh/MANIFEST.md`` must describe exactly what is on disk.

**What this protects (#592).** `init --refresh`'s runner-check rewrite is
prose an agent executes, not code -- ADR 0017 D5 admits no guard over what
that prose means, so the acceptance evidence for #592's rewrite rules is
direct use against a checked-in corpus of real consumer files, never a
scratch repo (`engineering` -> the migration-ships-with-the-change rule this
same ticket adds). A corpus is only as trustworthy as its provenance record:
if a fixture's bytes drift from what `MANIFEST.md` claims -- a stray edit, a
bad extraction, a copy-paste from the wrong commit -- every direct-use
transcript run against it is silently describing a different file than the
one reviewers can audit against the named source commit. This is the one
mechanically checkable part of the corpus (asset integrity, ADR 0017 D5 class
(d)); what `--refresh` *does* with these files is direct-use evidence, not a
guard's subject.

**Both directions.** A row with no file on disk is a manifest that documents
something that was never written or was since deleted; a file with no row is
an unprovenanced fixture nobody can audit. Either failure mode is silent
under a one-sided sweep (`craft.md` -> *ANY ALLOWLIST OR EXEMPTION NEEDS BOTH
DIRECTIONS*).

**Synthetic fixtures are exempt from the hash-matches-source claim** (there is
no source commit to derive them from) but not from the existence check: a
synthetic row still names a file, and that file must exist. A row is
synthetic when its manifest table records ``--`` in the *commit SHA* column --
the same marker this manifest uses for every hand-authored fixture.

**Read the tracked tree.** Both the manifest table and the fixture files it
describes are read through the git index (`tests._gitutil.indexed_text`,
`tests._gitutil.indexed_bytes`), never the working directory. This guard's
subject is the corpus's own integrity -- do the shipped bytes match what
`MANIFEST.md` claims -- not the gap between the working tree and what ships,
so it takes no carve-out from `.claude/rules/scripts.md`'s index-read rule.
"""

from __future__ import annotations

import hashlib
import re

from tests._gitutil import indexed_bytes, indexed_text, tracked_files_under
from tests.unit._prose import REPO_ROOT

FIXTURES_DIR = REPO_ROOT / "tests" / "fixtures" / "refresh"
FIXTURES_REL = "tests/fixtures/refresh"
MANIFEST_REL = f"{FIXTURES_REL}/MANIFEST.md"
MANIFEST_PATH = FIXTURES_DIR / "MANIFEST.md"

#: One provenance table row: ``| `path` | source repo | sha | source path | sha256 | bytes |``.
#: The source-repo and source-path columns are not needed by this guard and are
#: matched but not captured; only the four columns the assertions consume are.
_ROW = re.compile(
    r"^\|\s*`(?P<path>[^`]+)`\s*\|"  # fixture path
    r"\s*[^|]*\|"  # source repo (unused here)
    r"\s*(?P<sha>`[0-9a-f]{40}`|—)\s*\|"  # commit SHA, or the synthetic marker
    r"\s*[^|]*\|"  # source path (unused here)
    r"\s*`(?P<sha256>[0-9a-f]{64})`\s*\|"
    r"\s*(?P<bytes>\d+)\s*\|\s*$"
)


def manifest_rows(text: str) -> dict[str, tuple[bool, str, int]]:
    """Parse ``MANIFEST.md``'s provenance table.

    Maps each fixture path to ``(synthetic, sha256, byte_count)``. Raises if the
    table yields nothing at all -- an empty derived set would compare equal to
    an empty disk sweep and this guard would pass over both operands at once
    (`craft.md` -> *The empty comparison set*).
    """
    rows: dict[str, tuple[bool, str, int]] = {}
    for line in text.splitlines():
        match = _ROW.match(line)
        if match is None:
            continue
        rows[match.group("path")] = (
            match.group("sha") == "—",
            match.group("sha256"),
            int(match.group("bytes")),
        )
    if not rows:
        raise AssertionError(
            f"{MANIFEST_REL} yielded no provenance rows at all -- either the "
            f"table is empty or this guard's row pattern no longer matches it."
        )
    return rows


def fixture_files() -> set[str]:
    """Every tracked file under the fixture directory, relative to it.

    ``MANIFEST.md`` itself is excluded -- it is the record, not a fixture it
    describes. Enumerated from the git index, not the filesystem, so an
    untracked stray on disk cannot masquerade as a shipped fixture.
    """
    return {
        str(path.relative_to(FIXTURES_DIR))
        for path in tracked_files_under(FIXTURES_REL)
        if path != MANIFEST_PATH
    }


def sha256_of(rel_path: str) -> tuple[str, int]:
    """The hex digest and byte count of the tracked blob at ``rel_path``."""
    data = indexed_bytes(f"{FIXTURES_REL}/{rel_path}")
    return hashlib.sha256(data).hexdigest(), len(data)


def test_the_manifest_and_the_fixture_tree_name_the_same_files() -> None:
    """Both directions: an undocumented file, and a documented absence.

    A fixture on disk with no manifest row is unprovenanced -- nobody can audit
    it against a source commit. A manifest row with no file on disk documents
    something that was never written or has since been deleted. Either is
    silent under a sweep that only checks one direction.
    """
    documented = set(manifest_rows(indexed_text(MANIFEST_REL)))
    on_disk = fixture_files()
    undocumented = sorted(on_disk - documented)
    missing = sorted(documented - on_disk)
    assert not undocumented and not missing, (
        f"tests/fixtures/refresh/ and MANIFEST.md have drifted apart. "
        f"On disk but undocumented: {undocumented}. "
        f"Documented but missing from disk: {missing}."
    )


def test_every_non_synthetic_fixture_matches_its_recorded_hash() -> None:
    """AC: a fixture's bytes are exactly what the manifest claims they are.

    Synthetic rows are skipped here -- there is no source commit for them to
    match -- but every real extraction is re-hashed and compared, so a fixture
    edited after extraction (by hand, by a bad copy, by drift) is caught
    before a direct-use transcript is ever run against it. At least one
    sourced (non-synthetic) row must exist, or this loop is vacuous over an
    all-synthetic manifest and would pass regardless of what the corpus is.
    """
    rows = manifest_rows(indexed_text(MANIFEST_REL))
    assert any(not synthetic for synthetic, _, _ in rows.values()), (
        f"{MANIFEST_REL} has no non-synthetic (sourced) rows at all -- this "
        f"loop would vacuously pass over an all-synthetic corpus"
    )
    mismatches: list[str] = []
    for rel_path, (synthetic, expected_sha256, expected_bytes) in rows.items():
        if synthetic:
            continue
        actual_sha256, actual_bytes = sha256_of(rel_path)
        if (actual_sha256, actual_bytes) != (expected_sha256, expected_bytes):
            mismatches.append(
                f"{rel_path}: manifest records sha256={expected_sha256} "
                f"({expected_bytes} bytes), disk has sha256={actual_sha256} "
                f"({actual_bytes} bytes)"
            )
    assert not mismatches, "fixture bytes have drifted from MANIFEST.md:\n" + "\n".join(
        mismatches
    )


def test_synthetic_fixtures_still_have_a_file_and_a_hash_recorded() -> None:
    """A synthetic row is exempt from the source-hash check, not from existence.

    Without this, a synthetic row could be a manifest entry pointing at
    nothing and the drift sweep above would never notice, because the hash
    check for synthetic rows is intentionally skipped.
    """
    rows = manifest_rows(indexed_text(MANIFEST_REL))
    synthetic = {path: row for path, row in rows.items() if row[0]}
    assert synthetic, "expected at least one synthetic fixture row -- found none"
    for rel_path, (_synthetic, recorded_sha256, recorded_bytes) in synthetic.items():
        assert rel_path in fixture_files(), f"{rel_path} has a synthetic row but no file on disk"
        actual_sha256, actual_bytes = sha256_of(rel_path)
        assert (actual_sha256, actual_bytes) == (recorded_sha256, recorded_bytes), (
            f"{rel_path}'s own recorded hash has drifted from disk: manifest says "
            f"sha256={recorded_sha256} ({recorded_bytes} bytes), disk has "
            f"sha256={actual_sha256} ({actual_bytes} bytes)"
        )


def test_row_parsing_rejects_a_malformed_sha256_column() -> None:
    """The regex's teeth: a truncated or non-hex digest must not silently parse.

    Without an anchor on the exact hex length, a truncated hash -- the shape a
    bad copy-paste produces -- would match a shorter run of hex characters and
    this guard would compare against a hash nobody intended.
    """
    truncated = (
        "| `x` | repo | `" + "a" * 40 + "` | path | `" + "b" * 63 + "` | 10 |"
    )
    assert _ROW.match(truncated) is None, "a 63-character hash column must not match"


def test_row_parsing_reads_both_synthetic_and_sourced_rows() -> None:
    """Paired splice: one synthetic row, one sourced row, both parsed correctly."""
    sourced = (
        "| `a/b.txt` | `/x` | `" + "1" * 40 + "` | `p` | `" + "2" * 64 + "` | 5 |"
    )
    synthetic = "| `c/d.txt` | — | — | — | `" + "3" * 64 + "` | 7 |"
    rows = manifest_rows(sourced + "\n" + synthetic)
    assert rows["a/b.txt"] == (False, "2" * 64, 5)
    assert rows["c/d.txt"] == (True, "3" * 64, 7)
