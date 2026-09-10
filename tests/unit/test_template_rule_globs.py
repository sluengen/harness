"""#643 — a rule template declares path-shaped globs, or it seeds a rule that binds nowhere.

A Claude Code path-scoped rule loads by the globs in its `paths:` frontmatter
and by nothing else. `nano-erp` hydrated with `layers.design_system: true` and
received `.claude/rules/design-system.md` still carrying the literal
`<ui-source-glob>/**`: the rule bound at `design/**` and never once loaded on
`frontend/src`, the surface it exists for. Two days and five UI commits passed
before a human went looking. Nothing went red, and the file's own preamble told
its reader the globs had been filled.

That is the failure this module refuses at the source. A template glob that is
not a path is a placeholder nobody substituted, and it ships to every consumer
that turns the layer on.

**Admitted under ADR 0017 D5 class (d), frontmatter.** The subject is the value
shape of a declared glob — whether `<ui-source-glob>/**` is a path — never what
any prose in the file means. `templates/rules/design-system.md`'s preamble
describes when the rule loads; this module has no predicate over that sentence,
because a guard over document meaning is what D5 refuses.

**Why the index and not the working tree.** `git write-tree` resolves the index
to the tree a commit would carry, so a guard reading `Path.read_text` certifies
bytes that may never be committed (#482). Both operands come from git: the
corpus from `git ls-files`, each file's text from `git show :<path>`.

**On the floors.** `templates/rules/` holds one file today. A check that asserts
only "no offenders" reads green the day that file is renamed, moved, or has its
frontmatter reshaped — the parser finds nothing and nothing is wrong with
nothing. Three floors close that: the corpus is non-empty, it contains the file
this module exists for, and every file in it yields at least one parsed glob.

**What this does not do.** It cannot tell a substituted `design/**` from an
unsubstituted one — both are path-shaped, and no mechanical check distinguishes
them. Substitution is guidance, verified by use. It says nothing about a
*seeded* rule in a consumer's tree either: that file is repo-owned and the
plugin cannot see it.
"""

from __future__ import annotations

import re

from tests._gitutil import indexed_text, tracked_files_under
from tests.unit._prose import REPO_ROOT

#: Where the plugin's rule templates live, relative to the repo root.
TEMPLATE_RULES = "templates/rules"

#: The template this module was written for. Floor B holds the corpus to it, so
#: an unrelated template cannot satisfy floor A on its behalf.
DESIGN_RULE = "templates/rules/design-system.md"

#: A glob's admissible characters. Excludes `<` and `>` (a placeholder), a comma
#: (a hand-rolled list), whitespace, and the yaml indicators `{`, `}`, `[`, `]`.
_PATH_CHARS = re.compile(r"^[A-Za-z0-9._*/-]+$")

#: A `paths:` sequence entry inside the frontmatter.
_ENTRY = re.compile(r"^\s+-\s+(.+?)\s*$")


def frontmatter_globs(text: str) -> list[tuple[int, str]]:
    """Return the `paths:` globs a rule file declares, as `(line number, glob)`.

    Line numbers are 1-based so a failure message names a location an editor can
    open. Quotes are stripped from the value, since `- "design/**"` and
    `- design/**` declare the same glob.

    The parser fails toward the empty list, and the per-file floor below turns
    that into RED. A reshaped frontmatter — a flow sequence, a renamed key, a
    lost delimiter — must not read as "no offenders found".
    """
    lines = text.split("\n")
    if not lines or lines[0].rstrip() != "---":
        return []
    try:
        closing = next(
            index for index, line in enumerate(lines[1:], start=1)
            if line.rstrip() == "---"
        )
    except StopIteration:
        return []

    globs: list[tuple[int, str]] = []
    in_paths = False
    for index in range(1, closing):
        line = lines[index]
        if not in_paths:
            if line.rstrip() == "paths:":
                in_paths = True
            continue
        entry = _ENTRY.match(line)
        if entry is None:
            break
        globs.append((index + 1, entry.group(1).strip().strip("\"'")))
    return globs


def is_path_shaped(glob: str) -> bool:
    """Whether a declared glob names somewhere a rule can actually bind.

    Four conditions, each closing a way a rule lies about its scope:

    1. non-empty — an empty entry binds nothing;
    2. path characters only — rejects `<ui-source-glob>/**` and a
       comma-separated list;
    3. relative, with no `..` segment — a rule's globs are repo-relative;
    4. at least one literal character survives removing `*` and `/` — rejects
       `**` and `/**`, which bind *everywhere*, the other direction of the same
       lie.
    """
    if not glob:
        return False
    if not _PATH_CHARS.match(glob):
        return False
    if glob.startswith("/"):
        return False
    if ".." in glob.split("/"):
        return False
    return bool(glob.replace("*", "").replace("/", ""))


def _corpus() -> list[str]:
    """The tracked `*.md` files under `templates/rules`, repo-relative."""
    return sorted(
        str(path.relative_to(REPO_ROOT))
        for path in tracked_files_under(TEMPLATE_RULES)
        if path.suffix == ".md"
    )


def test_the_corpus_is_not_empty() -> None:
    """Floor A: the directory this module reads still holds rule templates.

    Without it, deleting or moving `templates/rules/` turns every assertion
    below green by giving them nothing to read.
    """
    corpus = _corpus()
    assert corpus, (
        f"No tracked *.md under {TEMPLATE_RULES}/. Either the rule templates "
        "moved and this guard did not follow them, or the plugin ships no rule "
        "template — and the assertions below would pass on an empty corpus."
    )


def test_the_corpus_contains_the_design_rule() -> None:
    """Floor B: the template #643 was filed about is still the one measured.

    Floor A alone is satisfied by any template. This holds the corpus to the
    file whose placeholder glob shipped to a consumer.
    """
    corpus = _corpus()
    assert DESIGN_RULE in corpus, (
        f"{DESIGN_RULE} is not tracked. `/harness:hydrate` step 5 copies it to "
        f"seed the design layer's rule; the corpus is {corpus}."
    )


def test_every_template_declares_at_least_one_glob() -> None:
    """Per-file floor: the parser reached each file's `paths:` frontmatter.

    A rule template whose frontmatter this parser cannot read yields no globs,
    and "no globs" is indistinguishable from "no bad globs" to the subject
    assertion. This is what makes that one mean something.
    """
    for relative in _corpus():
        globs = frontmatter_globs(indexed_text(relative))
        assert globs, (
            f"{relative} declares no `paths:` globs this guard can read. A "
            "path-scoped rule loads by its globs and nothing else, so a rule "
            "template with none seeds a rule that binds nowhere — and an "
            "unreadable frontmatter hides every check below."
        )


def test_every_declared_glob_is_path_shaped() -> None:
    """The subject: no template ships a glob a hydration failed to fill.

    A hydration that cannot fill a glob omits the line. Emitting the
    placeholder produces a file whose preamble says it is loaded and which
    never loads — the #643 failure, in the tree that ships it.
    """
    offenders = [
        f"{relative}:{line} declares {glob!r}"
        for relative in _corpus()
        for line, glob in frontmatter_globs(indexed_text(relative))
        if not is_path_shaped(glob)
    ]
    assert not offenders, (
        "A rule template declares a glob that is not a path:\n  "
        + "\n  ".join(offenders)
        + "\nA hydration that cannot fill a glob omits the line rather than "
        "seeding a placeholder: a rule bound to `<ui-source-glob>/**` loads "
        "nowhere, and its own preamble tells the reader it is loaded."
    )


#: Globs the predicate must reject, each a way a rule can bind wrongly or
#: nowhere. The first two are the literal placeholders this ticket removes.
REJECTED = (
    "<ui-source-glob>/**",
    "<design-directory>/**",
    "",
    "**",
    "/**",
    "*/**",
    "../ui/**",
    "frontend/src, packages/ui",
    "frontend src/**",
    "{design}/**",
    "[a-z]/**",
)

#: Legitimate globs that must stay accepted. A kill table cannot see a false
#: positive (#511), so the predicate carries controls in both directions: a
#: predicate that rejected everything would satisfy REJECTED alone.
ACCEPTED = (
    "design/**",
    "docs/**",
    "src/**",
    "frontend/src/**",
    "packages/ui/**",
    "skills/design-system/assets/**",
    "docs/*.md",
    ".claude/rules/**",
)


def test_the_predicate_rejects_every_shape_that_binds_wrongly() -> None:
    survivors = [glob for glob in REJECTED if is_path_shaped(glob)]
    assert not survivors, (
        f"is_path_shaped accepted globs that bind nowhere or everywhere: {survivors}"
    )


def test_the_predicate_accepts_every_legitimate_glob() -> None:
    refused = [glob for glob in ACCEPTED if not is_path_shaped(glob)]
    assert not refused, (
        f"is_path_shaped refused globs a real rule declares: {refused}. A "
        "predicate that refuses correct input turns this guard into a "
        "false-positive machine, and the kill table above cannot see that."
    )


def test_the_parser_reads_the_globs_a_rule_template_actually_declares() -> None:
    """Pin the derivation, not the derived answer.

    Synthetic input whose answer differs from the shipped template's, so a
    parser replaced by a hardcoded constant fails here rather than passing on
    the one file the corpus happens to hold.
    """
    text = (
        "---\n"
        "paths:\n"
        '  - "alpha/**"\n'
        "  - beta/src/**\n"
        "description: A rule.\n"
        "---\n"
        "\n"
        "# Body\n"
        "  - not/a/glob/**\n"
    )
    assert frontmatter_globs(text) == [(3, "alpha/**"), (4, "beta/src/**")], (
        "The parser must read both entries, strip quotes from the quoted one, "
        "stop at the next frontmatter key, and never reach into the body."
    )


def test_the_parser_yields_nothing_when_the_frontmatter_is_unreadable() -> None:
    """The parser fails toward the per-file floor, never toward a silent pass."""
    unreadable = (
        "# No frontmatter at all\n",
        "---\npaths: [alpha/**, beta/**]\ndescription: flow sequence.\n---\n",
        "---\nglobs:\n  - alpha/**\n---\n",
        "---\npaths:\n  - alpha/**\n",
    )
    for text in unreadable:
        assert frontmatter_globs(text) == [], (
            "An unreadable frontmatter must yield no globs, so the per-file "
            f"floor turns it RED rather than the subject reading green: {text!r}"
        )
