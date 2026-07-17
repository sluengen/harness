<!-- guidance:template-size-guard@0.1.0 -->
# Size-marker guard (reference implementation)

A ready-to-adopt test that enforces `code-quality`'s size rule **mechanically**,
so an over-limit source file that carries no justification fails the suite
instead of waiting for a reviewer to remember it or the steward's next pass to
re-find it.

## The rule it enforces

`code-quality` Part C keeps a **500-line hard limit** as a *tripwire*, not a
prohibition: a file over the limit must carry, near its top, a language-native
`# size: <reason>` justification comment. The reviewer rejects an over-limit
file with none. The tripwire's value is *when it fires* — it forces the cohesion
argument to be written down; a justified file passes. Line count is a weak proxy
for cohesion but a good tripwire: language-agnostic, zero-tooling, cheap to
check, so the rule travels to any repo in any language.

This guard is the *measuring test* the rule needs. It keys on the explicit
`size:` marker, **not** an incidental ticket cite — a long file that merely
mentions an issue key for unrelated provenance is not a size decision, and must
not pass. To justify via a tracking ticket, name it in the reason:
`# size: kept whole; split tracked in <your-issue-key>`.

## Adopt it

1. Copy the code block below into your test suite (e.g.
   `tests/unit/test_source_file_size.py`).
2. Edit the config constants for your repo:
   - `SOURCE_GLOBS` — the source globs to scan (relative to the repo root).
   - `HARD_LIMIT` — the line ceiling (the shared default is `500`).
   - `EXEMPTIONS` — repo-relative POSIX paths that are long by nature, not by
     accreted logic (generated schemas, declarative data). Keep it empty unless
     a file genuinely qualifies; a wrong entry either exempts real logic or
     fails a schema file spuriously.
   - `SIZE_MARKER` — the marker regex. The default recognizes the common comment
     leaders (`#`, `//`, `/* */`, `<!-- -->`), so most repos leave it alone; edit
     it for another comment syntax (SQL `--`, Lisp `;`).
3. Point `test_source_files_are_under_limit_or_justified` at your repo root —
   adjust the `parents[...]` index to your test's depth.

A repo without a test suite falls back to reviewer enforcement — degraded, but no
worse than having no mechanical check at all. Marker *substance* stays reviewer
judgment (a good marker names the cohesion argument and what splitting would
scatter); no test can score that, and this one does not try.

```python
"""Size-marker guard — copy into your repo's test suite and edit the config.

Enforces the code-quality rule mechanically: a source file over the hard limit
must carry a top-of-file ``# size: <reason>`` justification, or this test fails.
The tripwire's job is to force the cohesion argument to be written down, not to
forbid the size, so a justified over-limit file passes.
"""

from __future__ import annotations

import re
from pathlib import Path

# --- config: edit these for your repo ---------------------------------------
# Source globs (relative to the repo root) this guard scans.
SOURCE_GLOBS: tuple[str, ...] = ("harness/**/*.py",)
# The hard line limit above which a file must justify its size.
HARD_LIMIT: int = 500
# Repo-relative POSIX paths exempt from the limit — files long by nature, not by
# accreted logic (generated schemas, declarative data; code-quality Part B).
# Keep this empty unless a file genuinely qualifies.
EXEMPTIONS: frozenset[str] = frozenset()

# The marker: a comment carrying ``size:`` followed by a non-empty reason. The
# default recognizes the common comment leaders — ``#`` (Python, shell, YAML),
# ``//`` and ``/* */`` (C, JS, TS, Go, Rust, CSS), ``<!-- -->`` (HTML, XML,
# Markdown). For another comment syntax (SQL ``--``, Lisp ``;``) edit this regex.
# It keys on the explicit ``size:`` marker, not an incidental ticket cite: a bare
# issue-key reference is design provenance, not a size decision, and must not
# satisfy it.
SIZE_MARKER = re.compile(r"(?:#|//|/\*|<!--).*\bsize:\s*\S")


def find_offenders(
    root: Path | str,
    *,
    globs: tuple[str, ...] = SOURCE_GLOBS,
    limit: int = HARD_LIMIT,
    exemptions: frozenset[str] = EXEMPTIONS,
    marker: re.Pattern[str] = SIZE_MARKER,
) -> list[str]:
    """Return repo-relative paths of over-limit source files lacking a marker."""
    root = Path(root)
    offenders: list[str] = []
    seen: set[Path] = set()
    for glob in globs:
        for path in sorted(root.glob(glob)):
            if not path.is_file() or path in seen:
                continue
            seen.add(path)
            rel = path.relative_to(root).as_posix()
            if rel in exemptions:
                continue
            text = path.read_text(encoding="utf-8")
            if len(text.splitlines()) > limit and not marker.search(text):
                offenders.append(rel)
    return offenders


def test_source_files_are_under_limit_or_justified() -> None:
    """Every over-limit source file records a ``# size:`` decision."""
    # Point this at your repo root — adjust parents[...] to your test's depth.
    repo_root = Path(__file__).resolve().parents[2]
    offenders = find_offenders(repo_root)
    assert not offenders, (
        f"these files exceed the {HARD_LIMIT}-line limit with no `# size: "
        "<reason>` justification — add a one-line marker recording why the file "
        "may exceed the limit, or split it:\n" + "\n".join(f"  - {p}" for p in offenders)
    )
```
