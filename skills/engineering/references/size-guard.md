# Size-marker guard (reference implementation)

A ready-to-adopt test that enforces `engineering`'s size rule **mechanically**,
so an over-limit source file that carries no justification fails the suite
instead of waiting for a reviewer to remember it or the steward's next pass to
re-find it.

## The rule it enforces

`engineering` → *Structure* keeps a **500-line hard limit** as a *tripwire*, not
a prohibition (the review-time rule is spelled out in
[`specialized-verification.md`](specialized-verification.md) → *A file over the
hard limit is an auditable choice, not silent drift*): a file over the limit must carry, near its top, a language-native
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
   - `DECLARATIVE_GLOBS` / `DECLARATIVE_CEILING` — for a file that is long
     *because* it is declarative (schemas, type definitions, token maps —
     `engineering` → *Structure*, declarative files) prefer this over
     `EXEMPTIONS`: a raised ceiling
     still fires on runaway growth, where an exemption never fires again.
     `DECLARATIVE_GLOBS` names the globs; `DECLARATIVE_CEILING` is the ceiling
     they answer to instead of `HARD_LIMIT`, defaulting to 1.5x it. Leave
     `DECLARATIVE_GLOBS` empty (the shipped default) unless you have files that
     qualify.
   - `COMMENT_PREFIXES` — file suffix → the comment leader a `size:` marker
     takes in that language (`.py`/`.sh` → `#`, `.js`/`.ts` → `//`, `.css` →
     `/*`, `.html` → `<!--`). The marker is **keyed by file suffix**, so
     `# size:` cannot justify a `.js` file and `// size:` cannot justify a `.py`
     file — in neither is it a comment, so neither records a decision. One
     leader per suffix, so a language with two comment forms is mapped to the
     one its markers take: `.js`/`.ts` map to `//`, which is the form
     `engineering` names for them, so a `/* size: … */` block comment does not
     justify a `.js` file — change that entry to `/*` if your repo writes its
     markers that way. Adding a language is one entry here (SQL `".sql": "--"`,
     Lisp `".el": ";"`) and nothing else: this is the one mapping you extend,
     never the walker.
   - `SIZE_MARKER` — the **fallback** pattern, reached only by a suffix
     `COMMENT_PREFIXES` does not carry. It accepts any of the common comment
     leaders (`#`, `//`, `/* */`, `<!-- -->`), so an unmapped file is still
     measured, just loosely: the any-leader fallback is coverage, never a skip.
     A file you globbed is a file you meant to guard, so the error stays
     one-directional — reported loosely rather than silently unguarded. Map its
     suffix to tighten it.
3. Point `test_source_files_are_under_limit_or_justified` at your repo root —
   adjust the `parents[...]` index to your test's depth.

### Scope every source tree you have, not just the production one

`SOURCE_GLOBS` ships pointing at one production tree, and that is the shipped
*example*, not the recommended scope. A repo's test tree is source too, and it
is usually the larger one — so a guard scoped to production only leaves the
bigger half unchecked, and the omission is invisible precisely because the guard
is green.

Scope every tree that holds code, and give the test tree the raised
**declarative ceiling** rather than the hard limit — a test module's length is
substantially case enumeration against one surface's acceptance criteria, which
is *Structure*'s declarative-file argument, not accreted logic:

```
SOURCE_GLOBS: tuple[str, ...] = ("src/**/*.py", "scripts/**/*.py", "tests/**/*.py")
DECLARATIVE_GLOBS: tuple[str, ...] = ("tests/**/*.py",)
```

(An excerpt to edit in your copy — the one ```python block below is the
reference artifact, and this template ships exactly one of those on purpose so
what a consuming repo executes is unambiguous.)

A raised ceiling is the right instrument here and an `EXEMPTIONS` entry is the
wrong one: the ceiling still fires when a test module runs away, where an
exemption never fires again.

Expect the first run to go red on files that have been over the line for a long
time. That is the guard working — each one takes a one-line `size:` marker, in
that file's own comment syntax, recording the cohesion argument, or a split. The deliverable is that each
becomes an auditable choice; a marker is cheap, and the value is that the *next*
one cannot be silent.

Derive which trees you scan rather than trusting this list to stay current — a
hand-written set of guarded subjects falls behind the repo silently, and the
guard then reads green because it never checked, not because nothing violated
it. A companion test asserting that every tree holding source answers to some
ceiling costs a few lines and closes that blind spot for good.

A repo without a test suite falls back to reviewer enforcement — degraded, but no
worse than having no mechanical check at all. Marker *substance* stays reviewer
judgment (a good marker names the cohesion argument and what splitting would
scatter); no test can score that, and this one does not try.

```python
"""Size-marker guard — copy into your repo's test suite and edit the config.

Enforces `engineering`'s size rule mechanically: a source file over the hard limit
must carry a top-of-file ``size: <reason>`` justification, written in that
language's own comment syntax (COMMENT_PREFIXES), or this test fails.
The tripwire's job is to force the cohesion argument to be written down, not to
forbid the size, so a justified over-limit file passes.
"""

from __future__ import annotations

import re
from pathlib import Path

# --- config: edit these for your repo ---------------------------------------
# Source globs (relative to the repo root) this guard scans.
SOURCE_GLOBS: tuple[str, ...] = ("src/**/*.py",)
# The hard line limit above which a file must justify its size.
HARD_LIMIT: int = 500
# Repo-relative POSIX paths exempt from the limit — files long by nature, not by
# accreted logic (generated schemas, declarative data; `engineering` Structure).
# Keep this empty unless a file genuinely qualifies.
EXEMPTIONS: frozenset[str] = frozenset()
# Globs (relative to the repo root, same dialect as SOURCE_GLOBS) whose files are
# declarative by nature — schemas, type definitions, token maps (`engineering`
# Structure). These answer to DECLARATIVE_CEILING instead of HARD_LIMIT, still
# subject to the marker rule. Prefer this over EXEMPTIONS for a file that is
# long *because* it is declarative: the raised ceiling still fires on runaway
# growth, an exemption never fires again.
DECLARATIVE_GLOBS: tuple[str, ...] = ()
# The raised ceiling declarative-glob files answer to. Defaults to 1.5x the
# hard limit (`engineering` Structure); a repo may set its own number.
DECLARATIVE_CEILING: int = HARD_LIMIT * 3 // 2

# The comment leader a ``size:`` marker takes in each language, keyed by file
# suffix. This is the one mapping to extend: another language is one entry here
# (SQL ``".sql": "--"``, Lisp ``".el": ";"``), never a change to the walker.
# Keying by suffix is what stops ``# size:`` from justifying a ``.js`` file and
# ``// size:`` from justifying a ``.py`` file — in neither is it a comment, so
# neither records a decision. One leader per suffix: a language with two comment
# forms is mapped to the one its markers take, so ``.js``/``.ts`` map to ``//``
# (the form `engineering` names for them) and a ``/* size: */`` block comment does
# not justify a ``.js`` file. Change the entry if your repo writes them that way.
COMMENT_PREFIXES: dict[str, str] = {
    ".py": "#",
    ".sh": "#",
    ".js": "//",
    ".ts": "//",
    ".css": "/*",
    ".html": "<!--",
}

# The marker's tail, shared by both patterns below so they cannot drift apart:
# ``size:`` followed by a non-empty reason **on the marker's own line**. The run
# between them is ``[ \t]``, not ``\s``, and the line bound is load-bearing: the
# pattern is searched over the whole file text and ``\s`` matches a newline, so
# the wider class let the *next line's* first character stand in for the reason
# — which every real file supplies. That made the empty-marker rule pass on
# every multi-line file while still failing single-line samples: green in the
# suite, unfailable in the tree.
# It keys on the explicit ``size:`` marker, not an incidental ticket cite: a bare
# issue-key reference is design provenance, not a size decision, and must not
# satisfy it.
MARKER_TAIL = r".*\bsize:[ \t]*\S"
# The fallback marker, used only for a suffix COMMENT_PREFIXES does not carry:
# any of the common comment leaders — ``#`` (Python, shell, YAML), ``//`` and
# ``/* */`` (C, JS, TS, Go, Rust, CSS), ``<!-- -->`` (HTML, XML, Markdown).
# An unmapped suffix falls back here rather than being skipped, deliberately:
# you globbed the file, so it is a file you meant to guard. The error stays
# one-directional — reported loosely, never silently unguarded — and no language
# loses coverage it had before the mapping existed. Map its suffix to tighten it.
SIZE_MARKER = re.compile(r"(?:#|//|/\*|<!--)" + MARKER_TAIL)


def marker_for(
    suffix: str,
    prefixes: dict[str, str] = COMMENT_PREFIXES,
    fallback: re.Pattern[str] = SIZE_MARKER,
) -> re.Pattern[str]:
    """The marker pattern a file with this suffix must carry to justify itself."""
    prefix = prefixes.get(suffix)
    if prefix is None:
        return fallback
    return re.compile(re.escape(prefix) + MARKER_TAIL)


def find_offenders(
    root: Path | str,
    *,
    globs: tuple[str, ...] = SOURCE_GLOBS,
    limit: int = HARD_LIMIT,
    exemptions: frozenset[str] = EXEMPTIONS,
    declarative_globs: tuple[str, ...] = DECLARATIVE_GLOBS,
    declarative_ceiling: int = DECLARATIVE_CEILING,
    comment_prefixes: dict[str, str] = COMMENT_PREFIXES,
    marker: re.Pattern[str] = SIZE_MARKER,
) -> list[str]:
    """Return repo-relative paths of over-limit source files lacking a marker."""
    root = Path(root)
    declarative = {
        p.relative_to(root).as_posix()
        for g in declarative_globs
        for p in root.glob(g)
        if p.is_file()
    }
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
            ceiling = declarative_ceiling if rel in declarative else limit
            text = path.read_text(encoding="utf-8")
            pattern = marker_for(path.suffix, comment_prefixes, marker)
            if len(text.splitlines()) > ceiling and not pattern.search(text):
                offenders.append(rel)
    return offenders


def test_source_files_are_under_limit_or_justified() -> None:
    """Every over-limit source file records a ``size:`` decision in its own syntax."""
    # Point this at your repo root — adjust parents[...] to your test's depth.
    repo_root = Path(__file__).resolve().parents[2]
    offenders = find_offenders(repo_root)
    assert not offenders, (
        f"these files exceed their line limit ({HARD_LIMIT}; {DECLARATIVE_CEILING} "
        "for declarative globs) with no `size: <reason>` justification in the "
        "comment syntax COMMENT_PREFIXES gives their suffix — add a one-line "
        "marker recording why the file may exceed the limit, or split "
        "it:\n" + "\n".join(f"  - {p}" for p in offenders)
    )
```
