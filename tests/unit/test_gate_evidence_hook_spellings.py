"""#490 — two properties of the Stop guard's *source* that its behavioural suite
cannot reach, and that a green tree therefore cannot show.

Both subjects are executable code (``hooks/gate-evidence-guard.js``), so both
guards are admitted under ADR 0017 D5 class **(a)** — the same footing as
``test_fixture_git_init_declares_its_branch.py``, which D5's own amendment
records as "suite hygiene admitted under (a) ... its subject is executable test
code". Neither guard asserts what any prose means.

**AC-2 — every ref probe uses the verifying spelling.** ``git rev-parse <name>``
falls back to interpreting ``<name>`` as a pathspec when it does not resolve as
a revision, and answers by echoing the path with exit 0. A caller that maps
non-zero to null therefore reads a *path string* as if it were an oid.
``test_a_tracked_path_spelling_a_ref_does_not_block_a_clean_session`` drives the
one site where that is reachable today; the other ref probes name ``HEAD``,
which always resolves, so no fixture can make them fall back. They are swept
anyway, and this guard is what holds the sweep: the ticket asks for an
enumeration over the file rather than a count, so that a *new* ref probe added
tomorrow is caught without anyone editing a list here.

The classifier is derived, not listed. The fallback fires only on an argument
that failed to resolve as a revision, so a call is a ref probe exactly when it
passes an argument that is not an option — a non-``-`` string literal, or a
variable. That splits the shipped file's eight sites into four option queries
(``--git-common-dir``, ``--is-inside-work-tree``, two ``--show-toplevel``) and
four ref probes (``ref``, ``HEAD^{tree}``, ``HEAD``, ``--abbrev-ref HEAD``).

**AC-4 — the spawn measure's premise, guarded where it is made.**
``test_gate_evidence_hook_scope.py`` bounds how many gits the hook spawns over a
large transcript by counting them through a ``PATH`` shim. A ``PATH`` shim
intercepts the **bare** program name and nothing else, so the measure rests
entirely on "the hook has exactly one subprocess site, spelled ``git``" — a
premise its own docstring states and nothing held. Measured at the #486 review:
a length-proportional git spawn spelled with an *absolute* path (251 real spawns
over the large fixture, 8.66s) is counted as **21 → 21** and passes, and the
ratio measure cannot see it either, because a per-line cost is linear while the
bound is on the size ratio. This guard fails on exactly that edit, and on a
second subprocess site added in any spelling :func:`spawn_sites` reads.

**An unrecognised spelling reddens rather than disappearing.** Each extractor
reads the spellings its subject uses today and would pass silently over
anything else — the fall-through `craft.md` names (*a guard over an enumerable
dimension must fail on an unclassified member*). Measured at review, staged
against this hook: a ref probe written ``['rev-parse', ref]`` left AC-2 green
where the same probe in double quotes reddened it, and a second, absolute-path
spawn reached through ``const runGit = spawnSync`` — or destructured off a
namespace import — left AC-4 green. Invisible, not judged. The two accounting
tests at the end of this module compare what each extractor matched against
every occurrence it could have missed, so the diff that brings a new spelling
is the diff that has to place it.

**Both operands are read from the index, never from disk** (#482). ``git
write-tree`` certifies the index and the gate marker is named after the tree it
produces, so a tree staging a different hook must not pass a guard about the
hook. :func:`tests._gitutil.indexed_text` is the reader.

**Comments are stripped before either extractor runs** (#457): the hook
documents its own ``rev-parse`` and ``spawnSync`` spellings in JSDoc, and a
corpus carrying its own description cannot measure it. The stripping is
deliberately conservative — block comments and whole-line ``//`` comments, the
two forms this file's documentation actually takes — and
:func:`test_stripping_removes_the_hooks_own_description_of_its_spellings` pins
that it is enough for this subject.
"""

from __future__ import annotations

import re

import pytest

from tests._gitutil import indexed_text, tracked_files_under
from tests.unit._prose import REPO_ROOT

#: The subject, repo-relative — the spelling ``git show :<path>`` wants.
HOOK_PATH = "hooks/gate-evidence-guard.js"

_BLOCK_COMMENT = re.compile(r"/\*.*?\*/", re.DOTALL)
_LINE_COMMENT = re.compile(r"^[ \t]*//.*$", re.MULTILINE)

#: A ``["rev-parse", ...]`` argument array. Bounded by ``[^]]`` so it cannot run
#: past its own closing bracket into the next call.
_REV_PARSE_CALL = re.compile(r'\[\s*"rev-parse"\s*(?P<rest>[^\]]*)\]')

#: One element of such an array: a double-quoted literal, or a bare identifier.
_ELEMENT = re.compile(r'"(?P<literal>[^"]*)"|(?P<name>[A-Za-z_$][\w$]*)')

#: Every way node spells "start a child process". The scope rule (#467): a shape
#: is only guarded once every spelling it can take is enumerated, not just the
#: one in front of you.
_SPAWN_NAMES = (
    "spawn",
    "spawnSync",
    "exec",
    "execSync",
    "execFile",
    "execFileSync",
    "fork",
)

#: ``require("child_process")``, under either module id.
_REQUIRE_CP = r'require\(\s*"(?:node:)?child_process"\s*\)'

#: A destructuring import off it: ``const { spawnSync, exec: run } = require(...)``.
_CP_DESTRUCTURED = re.compile(r"\{(?P<inner>[^}]*)\}\s*=\s*" + _REQUIRE_CP)

#: A namespace import off it: ``const cp = require(...)``.
_CP_NAMESPACE = re.compile(
    r"(?:const|let|var)\s+(?P<name>[A-Za-z_$][\w$]*)\s*=\s*" + _REQUIRE_CP
)

_IDENTIFIER = re.compile(r"[A-Za-z_$][\w$]*")

#: The first argument of a call, or nothing when it takes none.
_FIRST_ARG = r'\s*\(\s*(?P<first>"[^"]*"|[A-Za-z_$][\w$]*)?'


def strip_comments(source: str) -> str:
    """``source`` with block comments and whole-line ``//`` comments removed."""
    return _LINE_COMMENT.sub("", _BLOCK_COMMENT.sub("", source))


def rev_parse_sites(source: str) -> list[dict[str, object]]:
    """Every ``rev-parse`` argument array in ``source``, classified.

    ``probes_a_ref`` is true when the call passes an argument that is not an
    option — a literal not starting with ``-``, or an identifier standing for
    one. Those are the arguments git tries to resolve as a revision, and so the
    only ones that can fall back to a pathspec. ``verified`` is true when
    ``--verify`` is among the literals.
    """
    sites = []
    for call in _REV_PARSE_CALL.finditer(strip_comments(source)):
        literals, probes = [], False
        for element in _ELEMENT.finditer(call.group("rest")):
            literal = element.group("literal")
            if literal is None:
                probes = True  # a variable: whatever it holds, git resolves it
                continue
            literals.append(literal)
            if not literal.startswith("-"):
                probes = True
        sites.append(
            {
                "args": literals,
                "probes_a_ref": probes,
                "verified": "--verify" in literals,
                "text": call.group(0),
            }
        )
    return sites


def _child_process_names(source: str) -> tuple[dict[str, str], set[str]]:
    r"""What this source calls the child-process spawners: local names bound
    directly off ``child_process``, and names bound to the module itself.

    One of *three* mechanisms, and the mutation table is what sorted out which
    does what — two drafts of this docstring credited the wrong one, because
    over the shipped hook the first two are **independently sufficient** and so
    neither mutation could kill on its own (the double-anchoring #458 names).

    ``pattern.exec(line)`` — ``RegExp.prototype.exec``, which the hook uses
    twice — must not read as a subprocess, or the guard reddens on correct
    code, which is a defect rather than strictness (#484, #487). Two things
    keep it out, and the corpus now isolates each: this function never binds
    ``exec`` at all unless the source imports it, and the ``(?<![.\w$])``
    lookbehind in :func:`spawn_sites` refuses the dotted call even when it is
    imported. The shipped hook imports only ``spawnSync``, so *there* the
    import check is what does the work; a hook that legitimately used
    ``child_process.exec`` and a regex would rest on the lookbehind instead.

    The third mechanism runs the other way. The lookbehind would also hide
    ``cp.execSync(...)`` — the qualified spelling #467 was about — so
    :func:`spawn_sites` matches that through explicit namespace patterns, off a
    receiver known to be ``child_process``.
    """
    local_to_imported: dict[str, str] = {}
    for binding in _CP_DESTRUCTURED.finditer(source):
        for part in binding.group("inner").split(","):
            names = _IDENTIFIER.findall(part)
            if not names:
                continue
            imported, local = names[0], names[-1]  # ``{ exec: run }`` -> run is local
            if imported in _SPAWN_NAMES:
                local_to_imported[local] = imported
    namespaces = {match.group("name") for match in _CP_NAMESPACE.finditer(source)}
    return local_to_imported, namespaces


def spawn_sites(source: str) -> list[dict[str, str | None]]:
    """Every child-process invocation in ``source``, with its first argument.

    The first argument is what a ``PATH`` shim can and cannot intercept: the
    bare literal ``"git"`` resolves through ``PATH``; an absolute path, or a
    variable holding one, does not. ``fn`` reports the *imported* name, so an
    alias cannot disguise which spawner ran.
    """
    source = strip_comments(source)
    local_to_imported, namespaces = _child_process_names(source)

    patterns = []
    for local, imported in local_to_imported.items():
        # The lookbehind is what keeps ``pattern.exec(line)`` out: an unqualified
        # call only. Qualified spellings are matched below, off a receiver that
        # is known to be child_process, so nothing legitimate is lost.
        patterns.append((imported, re.compile(r"(?<![.\w$])" + re.escape(local) + _FIRST_ARG)))
    qualified = sorted(namespaces) + [_REQUIRE_CP]
    for receiver in qualified:
        prefix = receiver if receiver is _REQUIRE_CP else re.escape(receiver)
        for name in _SPAWN_NAMES:
            patterns.append(
                (name, re.compile(prefix + r"\s*\.\s*" + re.escape(name) + _FIRST_ARG))
            )

    found: list[tuple[int, dict[str, str | None]]] = []
    for imported, pattern in patterns:
        for call in pattern.finditer(source):
            found.append((call.start(), {"fn": imported, "first": call.group("first")}))
    return [site for _, site in sorted(found, key=lambda pair: pair[0])]


@pytest.fixture(scope="module")
def hook_source() -> str:
    return indexed_text(HOOK_PATH)


# --- the corpus is real, and it was actually read -----------------------------


def test_the_hook_is_tracked() -> None:
    """A guard over an untracked file passes on the machine that wrote it and
    says nothing about a fresh clone (#484). ``indexed_text`` would raise on an
    untracked path, but it would raise as a *harness error*; this says so as a
    failure with a reason."""
    tracked = {
        path.relative_to(REPO_ROOT).as_posix() for path in tracked_files_under("hooks")
    }
    assert HOOK_PATH in tracked, (
        f"{HOOK_PATH} is not tracked by git, so nothing this module reads ships "
        f"to a consumer. Tracked under hooks/: {sorted(tracked)}"
    )


def test_the_hook_carries_both_kinds_of_rev_parse_call(hook_source: str) -> None:
    """The floor, in both directions (#467, #486). ``every ref probe is
    verified`` is constant-true over a corpus with no ref probes in it, and the
    classifier is indistinguishable from ``return False`` over a corpus with no
    option queries. Neither operand may be empty."""
    sites = rev_parse_sites(hook_source)
    probes = [site for site in sites if site["probes_a_ref"]]
    queries = [site for site in sites if not site["probes_a_ref"]]

    assert probes, (
        "no rev-parse call in the hook was classified as probing a ref, so the "
        "verifying-spelling assertion below is vacuous"
    )
    assert queries, (
        "every rev-parse call was classified as a ref probe, so the classifier "
        "is not discriminating and would pass a corpus it never read correctly"
    )


# --- AC-2: every ref probe uses the verifying spelling ------------------------


def test_every_ref_probing_rev_parse_is_verified(hook_source: str) -> None:
    """#490 AC-2. Bare ``rev-parse <ref>`` answers a *path* with exit 0 where the
    ref does not resolve and a tracked file of that name exists, which a caller
    mapping non-zero to null reads as a real answer. ``--verify`` refuses to
    answer anything that is not a single revision."""
    unverified = [
        site["text"]
        for site in rev_parse_sites(hook_source)
        if site["probes_a_ref"] and not site["verified"]
    ]

    assert unverified == [], (
        "these rev-parse calls in "
        f"{HOOK_PATH} resolve a ref without --verify, so each answers with the "
        "argument itself when it names a tracked path rather than a revision: "
        f"{unverified}"
    )


# --- AC-4: the spawn measure's premise ----------------------------------------


def test_the_hook_spawns_through_exactly_one_interceptable_site(hook_source: str) -> None:
    """#490 AC-4. ``test_gate_evidence_hook_scope.py``'s spawn bound is measured
    through a ``PATH`` shim, which sees the bare program name and nothing else.
    A second site, or this one respelled with an absolute path, is uncounted —
    measured at 21 → 21 against 251 real spawns.

    If the hook legitimately needs another subprocess, this failing is the
    prompt to re-measure that bound, not to widen this."""
    sites = spawn_sites(hook_source)

    assert len(sites) == 1, (
        f"{HOOK_PATH} has {len(sites)} child-process call sites, and the spawn "
        f"bound in test_gate_evidence_hook_scope.py counts only what a PATH shim "
        f"intercepts: {sites}"
    )
    assert sites[0] == {"fn": "spawnSync", "first": '"git"'}, (
        "the hook's subprocess site is no longer the bare, PATH-resolved "
        f'spawnSync("git", ...) the spawn bound counts: {sites[0]}'
    )


# --- the extractors are pinned to derivations, not to today's answers ---------
#
# Fed only the production file, a classifier and a hardcoded constant are
# indistinguishable (#458). Every case below has an answer that *differs* from
# the shipped hook's, so an extractor that quietly stopped deriving fails here
# while the three assertions above stay green.


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        pytest.param(
            'git(d, ["rev-parse", ref]);',
            [{"probes_a_ref": True, "verified": False}],
            id="a-variable-is-a-ref-probe",
        ),
        pytest.param(
            'git(d, ["rev-parse", "--verify", "--quiet", ref]);',
            [{"probes_a_ref": True, "verified": True}],
            id="the-fixed-spelling",
        ),
        pytest.param(
            'git(d, ["rev-parse", "--show-toplevel"]);',
            [{"probes_a_ref": False, "verified": False}],
            id="an-option-query-carries-no-revision",
        ),
        pytest.param(
            'git(d, ["rev-parse", "--abbrev-ref", "HEAD"]);',
            [{"probes_a_ref": True, "verified": False}],
            id="an-option-plus-a-revision-is-still-a-probe",
        ),
        pytest.param(
            'git(d, ["rev-parse", "HEAD^{tree}"]);',
            [{"probes_a_ref": True, "verified": False}],
            id="a-revision-expression-is-a-probe",
        ),
        pytest.param(
            'if (x) { for (;;) { const t = ok ? git(d, ["rev-parse", b]) : null; } }',
            [{"probes_a_ref": True, "verified": False}],
            id="nested-in-a-block-and-a-ternary",
        ),
        pytest.param(
            'a(["rev-parse", "--verify", x]); b(["rev-parse", y]);',
            [
                {"probes_a_ref": True, "verified": True},
                {"probes_a_ref": True, "verified": False},
            ],
            id="two-sites-on-one-line-do-not-merge",
        ),
        pytest.param(
            '/* git(d, ["rev-parse", ref]) is the old spelling */\n'
            'git(d, ["rev-parse", "--verify", ref]);',
            [{"probes_a_ref": True, "verified": True}],
            id="a-comment-describing-the-old-spelling-is-not-a-site",
        ),
    ],
)
def test_the_rev_parse_classifier_derives_its_answer(
    source: str, expected: list[dict[str, bool]]
) -> None:
    found = [
        {"probes_a_ref": site["probes_a_ref"], "verified": site["verified"]}
        for site in rev_parse_sites(source)
    ]
    assert found == expected


#: What the shipped hook's import line looks like. Every synthetic case below
#: carries an import, because without one there is nothing to call and the
#: extractor correctly reports nothing — as the first draft of these cases
#: discovered.
_DESTRUCTURED = 'const { spawnSync } = require("child_process");\n'


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        pytest.param(
            _DESTRUCTURED + 'spawnSync("git", args, opts);',
            [{"fn": "spawnSync", "first": '"git"'}],
            id="todays-spelling",
        ),
        pytest.param(
            _DESTRUCTURED + 'spawnSync("/usr/bin/git", args, opts);',
            [{"fn": "spawnSync", "first": '"/usr/bin/git"'}],
            id="the-absolute-path-a-PATH-shim-cannot-intercept",
        ),
        pytest.param(
            _DESTRUCTURED + "spawnSync(GIT_BIN, args);",
            [{"fn": "spawnSync", "first": "GIT_BIN"}],
            id="a-variable-hides-which-binary-runs",
        ),
        pytest.param(
            'const { spawnSync, execFileSync } = require("child_process");\n'
            'spawnSync("git", a);\nexecFileSync("git", b);',
            [
                {"fn": "spawnSync", "first": '"git"'},
                {"fn": "execFileSync", "first": '"git"'},
            ],
            id="a-second-site-added-beside-the-first",
        ),
        pytest.param(
            'const cp = require("node:child_process");\ncp.execSync(cmd);',
            [{"fn": "execSync", "first": "cmd"}],
            id="the-qualified-spelling-off-a-namespace-import",
        ),
        pytest.param(
            'require("child_process").execFileSync("git", a);',
            [{"fn": "execFileSync", "first": '"git"'}],
            id="called-straight-off-the-require",
        ),
        pytest.param(
            'const { exec: run } = require("child_process");\nrun("git status");',
            [{"fn": "exec", "first": '"git status"'}],
            id="an-alias-still-reports-the-imported-name",
        ),
        pytest.param(
            _DESTRUCTURED + "const m = pattern.exec(line);\nconst n = re.exec(trimmed);",
            [],
            id="RegExp-prototype-exec-is-not-a-subprocess",
        ),
        pytest.param(
            'const { exec } = require("child_process");\nconst m = pattern.exec(line);',
            [],
            id="RegExp-exec-in-a-source-that-also-imports-exec",
        ),
        pytest.param(
            _DESTRUCTURED,
            [],
            id="importing-it-is-not-calling-it",
        ),
        pytest.param(
            'spawnSync("git", args);',
            [],
            id="a-spawner-name-with-no-child-process-import-is-some-other-function",
        ),
    ],
)
def test_the_spawn_extractor_derives_its_answer(
    source: str, expected: list[dict[str, str | None]]
) -> None:
    assert spawn_sites(source) == expected


def test_the_hook_really_does_call_exec_on_a_regexp(hook_source: str) -> None:
    """The false positive this extractor was rewritten to stop having, pinned to
    the subject rather than to the synthetic case above. The shipped hook calls
    ``RegExp.prototype.exec``; a name-matching extractor counted those as
    subprocesses and reddened AC-4 against a correct file."""
    stripped = strip_comments(hook_source)
    assert re.search(r"[A-Za-z_$][\w$]*\s*\.\s*exec\s*\(", stripped), (
        "the hook no longer calls .exec() on anything, so the discrimination "
        "test_the_spawn_extractor_derives_its_answer pins is no longer exercised "
        "by the real subject"
    )


def test_stripping_removes_the_hooks_own_description_of_its_spellings(
    hook_source: str,
) -> None:
    """The #457 trap, measured on this subject rather than assumed: the hook's
    JSDoc discusses both spellings this module counts, so an extractor reading
    the raw file would count its documentation. This pins that the two extractors
    see strictly fewer candidates after stripping than before — and that what is
    removed is comment text, by checking a phrase only the prose carries."""
    stripped = strip_comments(hook_source)

    assert "rev-parse`` answered null" in hook_source, (
        "the hook no longer documents its rev-parse spellings in prose, so this "
        "guard is pinning a trap the subject cannot fall into any more"
    )
    assert "rev-parse`` answered null" not in stripped, "block comments survived stripping"
    assert len(stripped) < len(hook_source)


# --- nothing in the subject falls through the extractors ----------------------


#: A ``rev-parse`` argv token under any of JavaScript's three string quotes.
_QUOTED_REV_PARSE = re.compile(r"""["'`]rev-parse["'`]""")


def test_no_quoted_rev_parse_token_escapes_the_classifier(hook_source: str) -> None:
    """Every ``rev-parse`` token left after stripping belongs to a call
    :func:`rev_parse_sites` matched.

    One that does not is a call in a spelling :data:`_REV_PARSE_CALL` cannot read
    — measured: ``git(d, ['rev-parse', 'refs/heads/x'])`` staged into the hook
    left :func:`test_every_ref_probing_rev_parse_is_verified` green, where the
    same probe in double quotes failed it. An unread ref probe is precisely what
    the verifying sweep then misses, so it reddens here instead.
    """
    stripped = strip_comments(hook_source)
    tokens = len(_QUOTED_REV_PARSE.findall(stripped))
    matched = sum(
        len(_QUOTED_REV_PARSE.findall(str(site["text"]))) for site in rev_parse_sites(hook_source)
    )

    assert tokens > 0, (
        "no rev-parse token survives stripping, so this test accounts for nothing "
        f"and the sweep over {HOOK_PATH} has no subject"
    )
    assert matched == tokens, (
        f"{HOOK_PATH} carries {tokens} rev-parse tokens and rev_parse_sites read "
        f"{matched} of them: the rest are spelled in a way it cannot see, and an "
        "unread ref probe is exactly what the verifying sweep above cannot judge"
    )


def test_no_child_process_use_escapes_the_spawn_extractor(hook_source: str) -> None:
    """Every name bound off ``child_process`` is mentioned once for its binding
    and once per call :func:`spawn_sites` matched — nothing else.

    An alias (``const runGit = spawnSync``) and a second ``require`` are both
    uses a ``PATH``-shim bound cannot see, and measured at review neither
    reddened :func:`test_the_hook_spawns_through_exactly_one_interceptable_site`
    on its own: the extractor simply did not report them. Counting mentions
    against what it accounted for is what makes them loud.
    """
    stripped = strip_comments(hook_source)
    local_to_imported, namespaces = _child_process_names(stripped)
    sites = spawn_sites(hook_source)
    names = sorted(local_to_imported) + sorted(namespaces)

    assert stripped.count("child_process") == 1, (
        f"{HOOK_PATH} reaches child_process "
        f"{stripped.count('child_process')} times; the accounting below reads one "
        "import, and a second one is a subprocess path the spawn bound was never "
        "measured against"
    )
    assert names, "nothing is bound off child_process, so the extractor read nothing"

    mentions = sum(
        len(re.findall(r"(?<![.\w$])" + re.escape(name) + r"(?![\w$])", stripped))
        for name in names
    )
    assert mentions == len(names) + len(sites), (
        f"the names bound off child_process ({names}) are mentioned {mentions} "
        f"times, and the extractor accounts for {len(names)} bindings plus "
        f"{len(sites)} calls: the surplus is a use it did not read — an alias, a "
        "re-export, or a call in a spelling spawn_sites cannot see"
    )
