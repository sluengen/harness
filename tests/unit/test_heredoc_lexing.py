"""#557 — a heredoc body is data, and neither Bash guard may read it as a command.

``hooks/git-push-guard.js``'s ``lex()`` is the one shell parser both Bash guards
run on: ``push-target-guard.js`` imports it by #436's decision rather than
growing a weaker twin. That sharing is what made this defect a pair. The lexer
had no notion of ``<<``, so a heredoc's *body lines* arrived as ordinary
commands, and any write whose content quoted a push was refused as if it were
that push. Both guards, one cause:

===========================  =========================================  ========
Hook                         Command                                    Before
===========================  =========================================  ========
``push-target-guard.js``     heredoc body quoting a push to ``dev``     REFUSED
``git-push-guard.js``        heredoc body quoting a force-push          REFUSED
===========================  =========================================  ========

The direction is fail-closed, so nothing unsafe shipped; what it refused was
authoring — documentation, specs, tickets and review reports that quote a push
command, in a repository whose subject *is* push discipline.

**The fix is asymmetric, because the shell is.** A **quoted** delimiter
(``<<'EOF'``, ``<<"EOF"``, ``<<\\EOF``) means the body undergoes no expansion at
all: inert data, skipped entirely. An **unquoted** delimiter (``<<EOF``) means
the body *is* expanded, so ``$(…)`` and backticks inside it really execute —
those are harvested into the lexer's ``substitutions`` and analysed recursively,
exactly as they are anywhere else. Skipping every body regardless of quoting was
the simpler diff and is rejected here: it would blind both guards to
``cat <<EOF`` … ``$(git push --force …)`` … ``EOF``, which is a live escape, and
:func:`test_an_unquoted_body_running_a_force_push_in_a_substitution_is_denied`
is the test that would go green under it.

Acceptance criteria:

* **AC-1 — the spellings are enumerated, not the shape.** A parser bug hides in
  the spelling nobody wrote a case for, so every form gets its own case rather
  than one case for a regex: :data:`SPELLINGS` carries ``<<EOF``, ``<<-EOF``,
  ``<<'EOF'``, ``<<"EOF"``, ``<<\\EOF``, ``<< EOF`` (space before the delimiter)
  and two heredocs on one line. :func:`test_every_spelling_lets_a_quoted_push_through`.
  The terminator is matched at line start, with leading tabs stripped **only**
  for the ``<<-`` form — the pair that proves the stripping is conditional is
  :func:`test_the_dash_form_strips_leading_tabs_from_its_terminator` against
  :func:`test_the_plain_form_does_not_strip_tabs_so_an_indented_terminator_never_ends_it`.

* **AC-2 — the subject's own corpus first.** The repo contains exactly one
  heredoc-family construct, and it is a trap rather than a heredoc: the
  here-string ``sh <<< "git push --force origin dev"`` in
  ``test_git_push_guard_hook.py``'s deny corpus. ``<<<`` must not lex as ``<<``
  with the delimiter ``<``, or it would start a body that never terminates.
  :func:`test_a_here_string_is_not_a_heredoc` pins it in both directions, and
  the deny corpora in the two sibling modules run unchanged in the same gate.
  The corpus is thin and this docstring says so rather than implying a sweep
  that did not happen.

* **AC-3 — both directions, per guard.** A kill table cannot see a false
  positive (LEDGER-511-F), which is precisely how a refusal this broad stayed
  invisible: the merge-path suite only ever asked whether bad input dies. Each
  guard therefore carries an allow *and* a deny over the new code path, and the
  existing controls stay red —
  :func:`test_a_real_push_to_a_protected_branch_is_still_denied` and
  :func:`test_a_real_force_push_is_still_denied`.

* **AC-4 — the unparseable is refused, not guessed.** An unterminated heredoc is
  a shell syntax error. The guard cannot know where the body ends, so it refuses
  rather than picking an interpretation:
  :func:`test_an_unterminated_heredoc_is_denied_by_both_guards`. That is the
  lexer's posture everywhere else — state 2 of the fail-open split, "ran but
  could not establish the facts, therefore deny".

The over-skip direction has its own case. A body consumed too greedily would
swallow the commands after it and blind the guard to a real push, which is the
one way this fix could turn a false *positive* into a false *negative*:
:func:`test_a_real_push_after_a_heredoc_body_is_still_seen`.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
TARGET_HOOK = REPO_ROOT / "hooks" / "push-target-guard.js"
FORCE_HOOK = REPO_ROOT / "hooks" / "git-push-guard.js"

#: A push to a branch the fixture repo protects. Body text only — never run.
PUSH = "git push origin HEAD:main"
#: A force-push, the sibling guard's subject. Body text only — never run.
FORCE = "git push --force origin main"


# --- fixture ------------------------------------------------------------------
#
# Its own copy rather than an import from a sibling test module: #467 removed
# exactly that coupling, and a ``test_*.py`` that another one imports has become
# a library.


def _node() -> str:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node not available")
    return node


def _git(root: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", *args], cwd=root, check=True, capture_output=True, text=True
    )
    return completed.stdout.strip()


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A repository on ``main`` with one commit, no marker and no declaration.

    No declaration file, so the conservative fallback protected set applies and
    ``main`` is protected; no marker, so a *real* push to it denies. Both halves
    matter: the allow cases below have to be allowed by the heredoc rule rather
    than by the guard having nothing to object to.
    """
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-q", "--initial-branch=main")
    _git(root, "config", "user.email", "t@example.com")
    _git(root, "config", "user.name", "t")
    (root / "a.txt").write_text("one\n")
    _git(root, "add", "a.txt")
    _git(root, "commit", "-q", "-m", "add a.txt")
    return root


def _decision(hook: Path, command: str, cwd: Path) -> str | None:
    payload = {"tool_name": "Bash", "cwd": str(cwd), "tool_input": {"command": command}}
    proc = subprocess.run(
        [_node(), str(hook)],
        input=json.dumps(payload),
        text=True,
        capture_output=True,
        cwd=cwd,
        timeout=30,
    )
    assert proc.returncode == 0, f"hook errored (rc={proc.returncode}): {proc.stderr}"
    assert proc.stdout.strip(), f"hook produced no output for {command!r}"
    out = json.loads(proc.stdout)
    return out.get("hookSpecificOutput", {}).get("permissionDecision")


def _denied(hook: Path, command: str, cwd: Path) -> bool:
    return _decision(hook, command, cwd) == "deny"


# --- AC-1: every spelling ------------------------------------------------------

#: ``(id, command)`` per heredoc spelling, each writing a file whose body spells
#: a push to the protected branch. Every one of these is a legitimate write and
#: must be allowed. Held as literal commands rather than built from a template,
#: because a template would encode the very ``<<``-and-delimiter shape under test
#: and agree with the parser about what a spelling is.
SPELLINGS = [
    ("unquoted", f"cat > note.txt <<EOF\n{PUSH}\nEOF\n"),
    ("dash_form", f"cat > note.txt <<-EOF\n\t{PUSH}\n\tEOF\n"),
    ("single_quoted", f"cat > note.txt <<'EOF'\n{PUSH}\nEOF\n"),
    ("double_quoted", f'cat > note.txt <<"EOF"\n{PUSH}\nEOF\n'),
    ("backslash_quoted", f"cat > note.txt <<\\EOF\n{PUSH}\nEOF\n"),
    ("space_before_delimiter", f"cat > note.txt << EOF\n{PUSH}\nEOF\n"),
    ("two_on_one_line", f"cat <<A <<B\n{PUSH}\nA\n{PUSH}\nB\n"),
    ("fd_prefixed", f"cat 0<<EOF\n{PUSH}\nEOF\n"),
]


@pytest.mark.parametrize("command", [c for _, c in SPELLINGS], ids=[i for i, _ in SPELLINGS])
def test_every_spelling_lets_a_quoted_push_through(command: str, repo: Path) -> None:
    """Writing a file whose body quotes a push is authoring, not pushing."""
    assert not _denied(TARGET_HOOK, command, repo), f"refused a heredoc write: {command!r}"


@pytest.mark.parametrize("command", [c for _, c in SPELLINGS], ids=[i for i, _ in SPELLINGS])
def test_every_spelling_lets_a_quoted_force_push_through(command: str, repo: Path) -> None:
    """The same spellings against the sibling guard: both share the one lexer."""
    force = command.replace(PUSH, FORCE)
    assert not _denied(FORCE_HOOK, force, repo), f"refused a heredoc write: {force!r}"


def test_the_dash_form_strips_leading_tabs_from_its_terminator(repo: Path) -> None:
    """``<<-`` strips leading tabs, so a tab-indented terminator does end it.

    Paired with the plain-form test below: together they prove the stripping is
    conditional on the form rather than done unconditionally.
    """
    command = f"cat > note.txt <<-EOF\n\t{PUSH}\n\tEOF\necho done\n"
    assert not _denied(TARGET_HOOK, command, repo)


def test_the_plain_form_does_not_strip_tabs_so_an_indented_terminator_never_ends_it(
    repo: Path,
) -> None:
    """``<<EOF`` matches its terminator at line start only.

    A tab-indented ``EOF`` is body text, so this heredoc is unterminated — a
    shell syntax error — and AC-4 refuses it. If the implementation stripped
    tabs for the plain form too, this would be a terminated heredoc and allowed,
    which is what makes this the plain-form half of the pair.
    """
    command = f"cat > note.txt <<EOF\n\t{PUSH}\n\tEOF\n"
    assert _denied(TARGET_HOOK, command, repo)


def test_a_line_merely_containing_the_delimiter_is_not_the_terminator(repo: Path) -> None:
    """The terminator is the whole line, not a substring of one."""
    command = f"cat > note.txt <<EOF\nEOF is how it ends\nEOFX\n{PUSH}\nEOF\n"
    assert not _denied(TARGET_HOOK, command, repo)


# --- AC-2: the corpus, and the here-string trap --------------------------------


def test_a_here_string_is_not_a_heredoc(repo: Path) -> None:
    """``<<<`` is a here-string; reading it as ``<<`` + delimiter ``<`` is wrong.

    The repo's own corpus carries exactly one heredoc-family construct and this
    is it. Mis-lexed as a heredoc, ``<<<`` would open a body that never
    terminates and AC-4 would refuse the whole command — so these allows are
    what prove the two constructs stayed distinct.

    The corpus item itself is the last assertion: a bare shell fed a here-string
    runs a script the guard cannot read, so the force guard fails closed on it,
    and must keep failing closed for *that* reason.

    ``push-target-guard.js`` is deliberately not asserted here. It never calls
    ``isBareShellFedExternally``, so ``sh <<< "<a push>"`` passes it today — a
    pre-existing bypass of the *target* guard that this ticket did not introduce
    and does not change. Pinning today's allow would freeze the hole; it is
    filed separately instead.
    """
    assert not _denied(TARGET_HOOK, 'grep foo <<< "some text"', repo)
    assert not _denied(FORCE_HOOK, 'grep foo <<< "some text"', repo)
    assert not _denied(TARGET_HOOK, f'cat <<< "{PUSH}"', repo)
    assert not _denied(FORCE_HOOK, f'cat <<< "{FORCE}"', repo)
    assert _denied(FORCE_HOOK, f'sh <<< "{FORCE}"', repo)


def test_a_bare_shell_fed_a_heredoc_still_fails_closed(repo: Path) -> None:
    """``sh <<EOF`` runs an unreadable script; skipping the body does not excuse it.

    ``isBareShellFedExternally`` reads the redirect operator off the *command
    line*, not the body, so the heredoc rule leaves it intact.
    """
    assert _denied(FORCE_HOOK, f"sh <<EOF\n{FORCE}\nEOF\n", repo)


# --- AC-3: both directions, per guard ------------------------------------------


def test_a_quoted_body_spelling_a_push_is_allowed(repo: Path) -> None:
    """The allow direction for the target guard — the defect this ticket is."""
    assert not _denied(TARGET_HOOK, f"cat > d.md <<'EOF'\n{PUSH}\nEOF\n", repo)


def test_an_unquoted_body_running_a_push_in_a_substitution_is_denied(repo: Path) -> None:
    """The deny direction: an unquoted body expands, so ``$(…)`` in it executes."""
    assert _denied(TARGET_HOOK, f"cat > d.md <<EOF\n$({PUSH})\nEOF\n", repo)


def test_an_unquoted_body_spelling_a_bare_push_is_allowed(repo: Path) -> None:
    """Bare text in an unquoted heredoc is still data — only expansions run."""
    assert not _denied(TARGET_HOOK, f"cat > d.md <<EOF\n{PUSH}\nEOF\n", repo)


def test_a_quoted_body_spelling_a_force_push_is_allowed(repo: Path) -> None:
    """The allow direction for the force guard."""
    assert not _denied(FORCE_HOOK, f"cat > d.md <<'EOF'\n{FORCE}\nEOF\n", repo)


def test_an_unquoted_body_running_a_force_push_in_a_substitution_is_denied(
    repo: Path,
) -> None:
    """The escape that rules out skipping every body regardless of quoting."""
    assert _denied(FORCE_HOOK, f"cat > d.md <<EOF\n$({FORCE})\nEOF\n", repo)


def test_an_unquoted_body_spelling_a_bare_force_push_is_allowed(repo: Path) -> None:
    assert not _denied(FORCE_HOOK, f"cat > d.md <<EOF\n{FORCE}\nEOF\n", repo)


#: The three spellings that quote a delimiter. Parametrised over the body-inert
#: assertion rather than tested once, because the ``quoted`` flag is the fix's
#: core claim and the spelling corpus above only proves each spelling's *word*
#: parses. Review of the first cycle measured the gap directly: flipping
#: ``quoted`` to ``false`` in the double-quote or backslash arm of
#: ``captureHeredocDelimiter`` changed no test outcome.
QUOTED_DELIMITERS = [
    ("single", "<<'EOF'"),
    ("double", '<<"EOF"'),
    ("backslash", "<<\\EOF"),
]


@pytest.mark.parametrize(
    "delimiter", [d for _, d in QUOTED_DELIMITERS], ids=[i for i, _ in QUOTED_DELIMITERS]
)
def test_a_quoted_body_does_not_expand_so_a_substitution_in_it_is_data(
    delimiter: str, repo: Path
) -> None:
    """The asymmetry's other half: ``$(…)`` inside a *quoted* body never runs."""
    assert not _denied(FORCE_HOOK, f"cat > d.md {delimiter}\n$({FORCE})\nEOF\n", repo)
    assert not _denied(TARGET_HOOK, f"cat > d.md {delimiter}\n$({PUSH})\nEOF\n", repo)


# --- arithmetic expansion is not command substitution, and vice versa ---------
#
# ``$((…))`` had to be told apart from ``$(…)`` so a left shift would not read as
# a heredoc operator. Getting that classifier wrong in the *other* direction is
# worse than the bug it prevents: a body bash would run as commands, taken for
# arithmetic, is a force push nobody analyses. Bash opens arithmetic only when
# the paren after ``$(`` is closed by the **final** ``)``; when an inner paren
# closes early it re-parses the whole construct as command substitution and runs
# it. Verified on this host:
#
#     $ echo $((echo A) && (echo B))   ->  A B
#     $ echo $((echo A); (echo B))     ->  A B
#     $ echo $((echo A) | (cat))       ->  A
#     $ echo $((echo A))               ->  syntax error (genuinely arithmetic)

RUNS_AS_COMMANDS = [
    ("and_list", "(%s) && (true)"),
    ("semicolon_list", "(%s); (true)"),
    ("pipeline", "(%s) | (cat)"),
]


@pytest.mark.parametrize(
    "shape", [s for _, s in RUNS_AS_COMMANDS], ids=[i for i, _ in RUNS_AS_COMMANDS]
)
def test_a_dollar_paren_body_bash_runs_as_commands_is_not_treated_as_arithmetic(
    shape: str, repo: Path
) -> None:
    """An early-closing inner paren makes it command substitution, and it runs."""
    assert _denied(FORCE_HOOK, "echo $(" + shape % FORCE + ")", repo)
    assert _denied(TARGET_HOOK, "echo $(" + shape % PUSH + ")", repo)


def test_genuine_arithmetic_in_dollar_paren_is_still_not_a_heredoc(repo: Path) -> None:
    """The half that must keep working: a shift is arithmetic, not a redirect."""
    for command in ("echo $((1 << 2))", "echo $(( (1+2) << 3 ))"):
        assert not _denied(FORCE_HOOK, command, repo)
        assert not _denied(TARGET_HOOK, command, repo)


ARITHMETIC_COMMANDS = [
    ("bare", "(( 1 << 2 ))"),
    ("in_an_if", "if (( 1 << 2 )); then echo hi; fi"),
    ("assignment", "(( x = 1 << 3 ))"),
]


@pytest.mark.parametrize(
    "command", [c for _, c in ARITHMETIC_COMMANDS], ids=[i for i, _ in ARITHMETIC_COMMANDS]
)
def test_a_word_boundary_double_paren_is_an_arithmetic_command(
    command: str, repo: Path
) -> None:
    """``(( … ))`` is arithmetic too, and its ``<<`` is a shift, not a heredoc."""
    assert not _denied(FORCE_HOOK, command, repo)
    assert not _denied(TARGET_HOOK, command, repo)


def test_a_double_paren_subshell_group_still_runs_its_commands(repo: Path) -> None:
    """``((cmd) && (cmd))`` is nested subshells, not arithmetic — bash runs both."""
    assert _denied(FORCE_HOOK, f"(({FORCE}) && (true))", repo)
    assert _denied(TARGET_HOOK, f"(({PUSH}) && (true))", repo)


#: The shapes that defeated the paren-counting classifier across two review
#: cycles. A quoted ``(`` inflates a naive depth count, so the naive close lands
#: on the final character and a command list reads as arithmetic — while bash,
#: which honours the quotes, runs it. Verified: ``bash -c 'echo $(("(" ) ; echo
#: RAN )'`` prints ``RAN``. Kept as the deny-direction pair to the allow cases in
#: ``NO_HEREDOC``, so a future attempt to reintroduce a classifier has to face
#: both halves at once.
QUOTED_PAREN_ESCAPES = [
    ("double_quoted", 'echo $(("(" ) ; %s )'),
    ("single_quoted", "echo $(('(' ) ; %s )"),
    ("backslash", "echo $((\\( ) ; %s )"),
    ("piped", 'echo $(("(" ) | %s )'),
    ("nested", 'echo $(((\"(\" ) ) ; %s )'),
    ("word_boundary_double_paren", '(("(" ) ; %s )'),
]


@pytest.mark.parametrize(
    "shape",
    [s for _, s in QUOTED_PAREN_ESCAPES],
    ids=[i for i, _ in QUOTED_PAREN_ESCAPES],
)
def test_a_quoted_paren_does_not_hide_a_command_list(shape: str, repo: Path) -> None:
    """Bash runs these; both guards must still see the push inside them."""
    assert _denied(FORCE_HOOK, shape % FORCE, repo)
    assert _denied(TARGET_HOOK, shape % PUSH, repo)


# --- AC-3 controls: the guards still refuse the real thing ---------------------


def test_a_real_push_to_a_protected_branch_is_still_denied(repo: Path) -> None:
    assert _denied(TARGET_HOOK, PUSH, repo)


def test_a_real_force_push_is_still_denied(repo: Path) -> None:
    assert _denied(FORCE_HOOK, FORCE, repo)


def test_a_real_push_after_a_heredoc_body_is_still_seen(repo: Path) -> None:
    """Over-skipping would turn this false positive into a false negative.

    A body consumed past its terminator swallows the commands after it. This is
    the one way the fix could make the guard *weaker* than it was, so it is
    pinned for both spellings of the delimiter.
    """
    assert _denied(TARGET_HOOK, f"cat > d.md <<'EOF'\nhello\nEOF\n{PUSH}\n", repo)
    assert _denied(TARGET_HOOK, f"cat > d.md <<EOF\nhello\nEOF\n{PUSH}\n", repo)
    assert _denied(FORCE_HOOK, f"cat > d.md <<'EOF'\nhello\nEOF\n{FORCE}\n", repo)


def test_a_push_on_the_same_line_as_the_heredoc_operator_is_still_seen(
    repo: Path,
) -> None:
    """The body starts at the next newline; the rest of *this* line is command."""
    assert _denied(TARGET_HOOK, f"cat > d.md <<'EOF' && {PUSH}\nhello\nEOF\n", repo)


# --- AC-4: the unparseable is refused ------------------------------------------


UNTERMINATED = [
    ("no_terminator_at_all", "cat > note.txt <<EOF\nsome text\n"),
    ("quoted_no_terminator", "cat > note.txt <<'EOF'\nsome text\n"),
    ("second_of_two_unterminated", "cat <<A <<B\nbody\nA\nbody\n"),
    ("terminator_indented_for_plain_form", "cat > note.txt <<EOF\nbody\n\tEOF\n"),
    # ``<<`` with no delimiter word after it. Measured against bash: a genuine
    # syntax error, `syntax error near unexpected token 'newline'`, exit 2 —
    # nothing runs, and the guard refuses in kind.
    ("no_delimiter_word", "cat > note.txt <<\n"),
]


@pytest.mark.parametrize(
    "command", [c for _, c in UNTERMINATED], ids=[i for i, _ in UNTERMINATED]
)
def test_an_unterminated_heredoc_is_denied_by_both_guards(
    command: str, repo: Path
) -> None:
    """A shell syntax error is not an invitation to guess where the body ends."""
    assert _denied(TARGET_HOOK, command, repo), f"target guard allowed: {command!r}"
    assert _denied(FORCE_HOOK, command, repo), f"force guard allowed: {command!r}"


def test_the_unterminated_refusal_says_why(repo: Path) -> None:
    """The reason names the heredoc, so the operator can spell it correctly.

    Asserted on the reason rather than the decision because an unterminated
    heredoc denies under several other rules too once the body leaks back into
    the command stream; a decision-only check would pass with the heredoc arm
    deleted entirely.
    """
    payload = {
        "tool_name": "Bash",
        "cwd": str(repo),
        "tool_input": {"command": "cat > note.txt <<EOF\nsome text\n"},
    }
    proc = subprocess.run(
        [_node(), str(TARGET_HOOK)],
        input=json.dumps(payload),
        text=True,
        capture_output=True,
        cwd=repo,
        timeout=30,
    )
    reason = json.loads(proc.stdout)["hookSpecificOutput"]["permissionDecisionReason"]
    assert "heredoc" in reason.lower()


# --- the ordinary corpus is untouched ------------------------------------------


NO_HEREDOC = [
    ("plain_echo_of_push_text", f"echo '{PUSH}'"),
    ("a_less_than_redirect", "sort < input.txt"),
    ("a_shift_operator_in_text", "echo 'x << 2'"),
    ("commit_message_naming_a_push", "git commit -m 'document the push rule'"),
    # ``$((…))`` is arithmetic expansion and its ``<<`` is a left shift, not a
    # redirection. These are allowed for a structural reason rather than by
    # being recognised as arithmetic: **a heredoc opens a body only when a
    # newline follows the operator**, and none of these has one. Two review
    # cycles were spent on a classifier that tried to tell arithmetic from a
    # command list by counting parens, and both failed the same way — it was
    # quote-blind where bash is quote-aware, so a command list read as
    # arithmetic and the force push inside it went unanalysed. The classifier is
    # gone; a body that cannot exist needs no classifying.
    ("an_arithmetic_shift", "echo $((1 << 2))"),
    ("an_arithmetic_shift_with_spaces", "echo $(( 1 << 2 ))"),
    ("a_substitution_inside_arithmetic", "echo $(( $(date +%s) << 2 ))"),
    ("a_nested_arithmetic_group", "echo $(( (1+2) << 3 ))"),
    # The quoted-paren shapes that defeated the classifier. Each is a command
    # list bash really runs; with no classifier there is nothing to fool, and
    # the deny-direction half of this pair is
    # ``test_a_quoted_paren_does_not_hide_a_command_list``.
    ("a_quoted_open_paren", 'echo $(("(" ) ; true )'),
    ("a_single_quoted_open_paren", "echo $(('(' ) ; true )"),
    ("a_backslash_open_paren", "echo $((\\( ) ; true )"),
    # No newline after the operator, so no body can begin. Bash agrees: it warns
    # (`here-document delimited by end-of-file`) and runs with an empty body,
    # exit 0 — nothing is hidden and nothing is guessed at, so there is nothing
    # for AC-4 to refuse.
    ("operator_then_end_of_input", "cat > note.txt <<EOF"),
    ("operator_alone", "cat <<EOF"),
]


@pytest.mark.parametrize(
    "command", [c for _, c in NO_HEREDOC], ids=[i for i, _ in NO_HEREDOC]
)
def test_commands_without_a_heredoc_are_unaffected(command: str, repo: Path) -> None:
    assert not _denied(TARGET_HOOK, command, repo)
    assert not _denied(FORCE_HOOK, command, repo)
