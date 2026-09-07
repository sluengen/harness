"""#573 — bash is the oracle for the shared shell lexer, not an author's belief.

``hooks/git-push-guard.js`` carries the one POSIX shell lexer both Bash guards
run on: ``push-target-guard.js`` imports ``lex()`` from it by #436's decision
rather than growing a weaker twin. The module's own header calls its coverage
"inherently a moving target", and every suite that scores it — this module's six
siblings — **pins a verdict its author believed correct**. Nothing compared a
guard's reading of a command against the shell's.

What that cost, measured rather than asserted. ``harvestSubstitutions`` has two
independent trigger arms, ``$(…)`` and a backtick, because both expand inside an
unquoted heredoc body. Deleting the backtick arm turns a backtick force-push in
an unquoted body from **deny** into **allow in both guards** — fail-open in a
fail-closed guard — while **253 tests across all six push-guard suites stay
green**. A whole class of defect was invisible to every test in the tree.

The mechanism here is a differential. Each **shape** is a literal shell template
with two holes, instantiated twice:

* the **oracle** instantiation — payload ``echo <marker>``, run under a real
  ``bash -c`` in a disposable directory that is not a git repository. The shape
  executes its payload iff the marker comes back.
* the **guard** instantiation — payload a real push, handed to every hook
  ``hooks.json`` registers against ``Bash``, and never executed.

**The corpus records no expected verdict.** The only failure is
:func:`test_a_shape_bash_executes_is_not_allowed_by_both_guards`: a shape bash
executes that every registered guard allows.

Only the fail-open direction is scored. Over-refusal is a real property and it
already has six allow corpora; folding it into this predicate would make a
failure ambiguous about which of two things went wrong.

**This harness is allowed to find something.** If it goes red on an unmutated
tree, that is a live fail-open in a shipped guard and an andon pull (P4) — not
an in-scope repair. ``hooks/`` is a protected area: record the shape, hold the
ticket, and let the operator decide. Do not edit the guard to make this green.

Why the corpus is not generated
-------------------------------

:mod:`tests.unit.test_heredoc_lexing`'s ``SPELLINGS`` comment refuses a template
because "a template would encode the very ``<<``-and-delimiter shape under test
and agree with the parser about what a spelling is". There the template's
*parameter* was the shell structure, so the generator was a model of shell
syntax and a spelling neither it nor the parser knew was invisible to both.

Here the parameter is the **payload**. Every shape's shell structure is written
out once, in full, as a literal; there is no cartesian product over structure
anywhere in this module, and building one is prohibited for exactly that reason.
The deeper protection is that a shape's structure is scored by *bash*, not by
us: an incomplete enumeration stays a real limit (see the bound below), but
nothing in the corpus is judged by a model of the shell.

Acceptance criteria (#573)
--------------------------

* **AC-1 — the oracle is bash, not a verdict.** Executability is established by
  running the shape and observing the marker. A shape that cannot be measured is
  **UNUSABLE** and fails hard; a shape bash declines to execute is **INERT** and
  satisfies the predicate vacuously. The two are never conflated —
  :func:`test_the_oracle_separates_executing_shapes_from_inert_ones` is what
  stops the whole module being vacuous when everything reads one way (#466/#484:
  two identically-failed runs compare equal).
* **AC-2 — one template, two instantiations.** The payload is the only thing
  that differs, held there mechanically by
  :func:`test_each_shape_has_exactly_one_payload_hole_and_one_sentinel_hole`,
  :func:`test_the_two_instantiations_differ_only_in_the_payload_span` and
  :func:`test_shape_ids_are_unique`.
* **AC-3 — the fail-open predicate fires.** Proved by mutation, not by a RED:
  these are characterisation tests over an arm that works. See *Mutation
  evidence* below.
* **AC-5 — the corpus is bounded**, and
  :func:`test_the_corpus_stays_within_its_subprocess_budget` refuses growth past
  the bound without a decision.

The bound, and what it costs
----------------------------

Twelve shapes. **This module proves nothing about a shape outside them.** Named
exclusions, each for a reason rather than by omission:

* every non-heredoc expansion site (``echo `git push -f …```, a pipe into
  ``sh``) — already carried by the siblings' deny corpora; a copy here would be
  a second copy of the same claim (P2);
* shapes bash itself refuses to run (an unpaired backtick, an unterminated
  delimiter) — the fail-open predicate has no subject where nothing executes,
  and #557's AC-4 owns their refusal;
* the over-refusal direction entirely, per the docstring above;
* generated or fuzzed shapes — a generator is a model of shell structure, which
  is the objection this module escapes by writing structure out literally, and
  its nondeterminism would break ``mutate.py``'s observable rule.

**What it costs.** Two different numbers, kept apart deliberately, because
conflating them is how this paragraph was wrong the first time it was written.

*The ceiling*, derived and asserted by
:func:`test_the_corpus_stays_within_its_subprocess_budget`: each shape costs one
``bash`` (its classification) plus, if it executes, one ``node`` per registered
guard; the two instrument controls cost one ``bash`` each and the two guard
controls one ``node`` per guard. With 12 shapes and 2 guards that is
``12*(1+2) + 2 + 2*2`` = **42**, and :data:`SPAWN_BUDGET` is set to exactly that
so *any* growth is a decision rather than something that fits under slack.

*The measured cost*, counted by putting counting shims for ``bash`` and ``node``
on ``PATH`` and running the module serially — identical on three consecutive
runs: **36 spawns, 14 bash + 22 node**. It sits under the ceiling because only 9
of the 12 shapes execute, so the other three never reach their guard runs. (A
shape classified UNUSABLE spends one extra ``bash -n`` to say why, which is a
failure path and is not in this figure.)

*Neither figure is every subprocess*, and saying otherwise is how the paragraph
above was wrong the first time. ``git`` is outside both: the ``repo`` fixture
spends five calls building the fixture, and each guard run spends more inside
its own node process, for **85 git spawns on a green run** against the 36 above,
shimmed identically. They are not bounded directly because they are not
independent — every one is downstream of a fixture built once or of a guard run
the arithmetic already counts, so holding the node runs down holds them down.

Serially (``-n0 -p no:cacheprovider``) the module is **2.26 s**, median of three
on darwin/arm64 at #573. The node spawns dominate — ``push-target-guard.js``
runs git internally. All three fixtures are module-scoped, so the corpus is
classified once and the fixture repo built once **per xdist worker** rather than
per case; under ``-n auto`` each worker gets its own, so the figures above are
per worker. The module adds no ``scripts/`` coverage and therefore cannot move
the 82% floor in either direction.

Mutation evidence
-----------------

Every test here was green the moment it was born, because the arms it covers
work. They are **characterisation** tests, the same standing as
``test_push_target_guard_hook.py``'s whitelist floors, and their evidence is the
mutation table rather than a RED. The entries run at #573 are recorded on the
ticket; the one that matters for this module's keep is an entry the *differential
alone* catches, because an entry killed equally by the hand-written pair in
:mod:`tests.unit.test_heredoc_lexing` would make this a second copy (P2).

Containment
-----------

The harness executes constructed shell, so containment is structural rather than
a matter of discipline: :func:`_run_oracle` takes **no payload parameter** — it
renders from :data:`ORACLE_PAYLOAD` itself, so no call site *could* hand push
text to bash — it re-checks the rendered script for ``git``/``push`` before
spawning, runs ``bash --noprofile --norc`` with a scrubbed environment and
``stdin`` closed in a fresh directory that is not a git repository, and asserts
that directory is still empty afterwards. The push text exists only in the guard
instantiation, which is JSON on a hook's stdin.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tests.unit._bash_guards import registered_bash_guards  # noqa: E402

# --- the observation, and why it cannot be faked by copying -------------------
#
# The quoted-body shapes copy their payload *text* to stdout without running it.
# A marker that is a substring of the payload text would therefore appear with
# nothing executed, and every inert shape would read as executing.
#
# The seam is whitespace and nothing else — no quote or escape character enters
# the payload, which keeps AC-2's "only the payload differs" claim clean. `echo`
# joins its arguments with a single space, so *running* the payload prints one
# space and *copying* its text prints three.
#
# The nonce is fixed, not random: `mutate.py` refuses a nondeterministic
# observable, and a flaky corpus is worse than a narrow one.

NONCE = "9f2c"
#: Present in stdout only if the payload actually ran.
MARKER = f"HARNESSRAN {NONCE}"
#: Present in stdout only if the script ran to completion.
SENTINEL = f"HARNESSEND {NONCE}"
#: The oracle payload. Three spaces — see the seam above.
ORACLE_PAYLOAD = f"echo HARNESSRAN   {NONCE}"
#: The completion probe, appended to every shape by the same substitution.
SENTINEL_ECHO = f"echo HARNESSEND   {NONCE}"
#: The guard payload: denied by ``git-push-guard.js`` for ``--force`` and by
#: ``push-target-guard.js`` for ``HEAD:main`` into a marker-free fixture repo.
#: Never executed.
GUARD_PAYLOAD = "git push --force origin HEAD:main"

#: The module's whole subprocess ceiling (AC-5), set to exactly today's value so
#: any growth is a decision rather than something that fits under slack. Derived
#: in :func:`test_the_corpus_stays_within_its_subprocess_budget`; the measured
#: cost is lower and is recorded in the module docstring.
SPAWN_BUDGET = 42
#: Instrument controls that spawn bash without going through a shape.
_BASH_CONTROLS = 2
#: Guard-side control tests, each paying one node spawn per registered guard.
_GUARD_CONTROLS = 2


@dataclass(frozen=True)
class Shape:
    """One shell structure, written out literally, with two holes.

    ``template`` carries exactly one ``PAYLOAD`` and one ``SENTINEL``. ``why``
    names the lexer code path where bash and the lexer could plausibly disagree
    — a shape earns its place by naming one, so the corpus stays reviewable.
    """

    id: str
    template: str
    why: str


SHAPES: list[Shape] = [
    Shape(
        "unquoted_heredoc_paren_sub",
        "cat <<EOF\n$(PAYLOAD)\nEOF\nSENTINEL\n",
        "harvestSubstitutions' $( arm — the only measured arm; the positive "
        "control on known-good ground",
    ),
    Shape(
        "unquoted_heredoc_backtick",
        "cat <<EOF\n`PAYLOAD`\nEOF\nSENTINEL\n",
        "harvestSubstitutions' backtick arm — the unmeasured arm #573 exists for",
    ),
    Shape(
        "quoted_heredoc_backtick",
        "cat <<'EOF'\n`PAYLOAD`\nEOF\nSENTINEL\n",
        "the quoted/unquoted asymmetry, backtick side: expects INERT",
    ),
    Shape(
        "unquoted_heredoc_param_default",
        "cat <<EOF\n${x:-$(PAYLOAD)}\nEOF\nSENTINEL\n",
        "harvestSubstitutions' claim that ${…} is deliberately not skipped as a "
        "unit — stated in its docstring, measured nowhere",
    ),
    Shape(
        "unquoted_heredoc_double_quoted_backtick",
        'cat <<EOF\nnote: "see `PAYLOAD`"\nEOF\nSENTINEL\n',
        "the claim that the body walk honours the backslash and nothing else — a "
        "quote-aware regression falls open here",
    ),
    Shape(
        "unquoted_heredoc_single_quoted_paren_sub",
        "cat <<EOF\nnote: '$(PAYLOAD)'\nEOF\nSENTINEL\n",
        "the same claim on the other quote character — a corpus is blind to any "
        "dimension its fixtures hold constant (#463)",
    ),
    Shape(
        "unquoted_heredoc_sub_spanning_two_lines",
        "cat <<EOF\n$(PAYLOAD\n)\nEOF\nSENTINEL\n",
        "consumeHeredocBodies' 'joined before harvesting, never line by line'",
    ),
    Shape(
        "two_heredocs_payload_in_the_second",
        "cat <<A <<B\nplain text\nA\n$(PAYLOAD)\nB\nSENTINEL\n",
        "the pending-queue ordering; harvesting only the first body is fail-open",
    ),
    Shape(
        "dash_form_heredoc_tab_indented_sub",
        "cat <<-EOF\n\t$(PAYLOAD)\n\tEOF\nSENTINEL\n",
        "the <<- tab-strip path feeding the harvest",
    ),
    Shape(
        "escaped_substitution_in_unquoted_body",
        "cat <<EOF\n\\$(PAYLOAD)\nEOF\nSENTINEL\n",
        "the harvest's backslash arm: expects INERT",
    ),
    Shape(
        "process_substitution_in_unquoted_body",
        "cat <<EOF\n<(PAYLOAD)\nEOF\nSENTINEL\n",
        "the shape a reader calls a hole and bash calls data — a body expands "
        "parameters, command substitution and arithmetic, and nothing else",
    ),
    Shape(
        "here_string_substitution",
        'cat <<< "$(PAYLOAD)"\nSENTINEL\n',
        "the three-character <<< skip in lex() feeding the double-quote "
        "substitution arm",
    ),
]


def _render(template: str, payload: str) -> str:
    """Instantiate ``template``. ``str.replace``, never ``str.format``.

    The templates contain ``{`` and ``}`` — a format string would have to escape
    the very braces under test.
    """
    return template.replace("SENTINEL", SENTINEL_ECHO).replace("PAYLOAD", payload)


# --- the oracle ---------------------------------------------------------------


@dataclass(frozen=True)
class Outcome:
    """A three-valued reading, never a boolean.

    ``usable`` false means the shape could not be measured — a defect in the
    corpus. It must never read as "bash declined to execute this", which is
    ``usable and not executed``.
    """

    usable: bool
    executed: bool
    reason: str


#: Invoked bare, never resolved through ``shutil.which`` and never skipped on.
#:
#: The gate is itself ``bash scripts/verify.sh``, so bash is a precondition of
#: the gate running at all rather than a tool it could verify a tree without.
#: Resolving it and skipping would model it as optional — and would make this
#: module a skip site declaring a host dependency the preflight does not probe,
#: which ``test_verify_toolchain_preflight.py`` refuses in both directions.
#: ``test_promotion_step_script.py`` runs a real bash the same way.
BASH = "bash"


def _node() -> str:
    found = shutil.which("node")
    if found is None:
        pytest.skip("node not available")
    return found


def _run_oracle(shape: Shape, scratch: Path) -> Outcome:
    """Run ``shape``'s oracle instantiation and classify what happened.

    Takes no payload parameter **by design**: it renders from
    :data:`ORACLE_PAYLOAD` itself, so there is no call site that could hand the
    push text to a shell.
    """
    script = _render(shape.template, ORACLE_PAYLOAD)

    # Fail closed if a future template ever inlines a push in its *structure*.
    assert "git" not in script and "push" not in script, (
        f"{shape.id}: the oracle instantiation must never contain a git command; "
        "push text belongs only in the guard instantiation"
    )

    home = scratch / "home"
    home.mkdir(exist_ok=True)
    work = scratch / "work"
    work.mkdir(exist_ok=True)

    try:
        proc = subprocess.run(
            [BASH, "--noprofile", "--norc", "-c", script],
            cwd=str(work),
            capture_output=True,
            text=True,
            timeout=10,
            stdin=subprocess.DEVNULL,
            env={"PATH": os.environ.get("PATH", ""), "HOME": str(home), "LC_ALL": "C"},
        )
    except subprocess.TimeoutExpired:
        return Outcome(False, False, "bash did not complete within 10s")

    leftovers = sorted(p.name for p in work.iterdir())
    assert not leftovers, (
        f"{shape.id}: the oracle instantiation wrote {leftovers} — every shape "
        "must sink to stdout, and a redirect in a template is a containment defect"
    )

    tail = proc.stderr[-400:]
    if proc.returncode < 0:
        return Outcome(False, False, f"bash died on a signal ({proc.returncode})")
    if SENTINEL not in proc.stdout:
        syntax = subprocess.run(
            [BASH, "-n", "-c", script], capture_output=True, text=True, timeout=10
        )
        why = "a syntax error" if syntax.returncode != 0 else "an early exit"
        return Outcome(
            False,
            False,
            f"the shape did not run to completion ({why}); "
            f"exit={proc.returncode} stderr={tail!r}",
        )
    if MARKER in proc.stdout:
        return Outcome(True, True, "bash executes the payload")
    return Outcome(True, False, "bash does not execute the payload here")


def _verdicts(command: str, repo: Path) -> dict[str, str | None]:
    """Each registered ``Bash`` guard's decision on ``command``, by filename."""
    payload = json.dumps(
        {"tool_name": "Bash", "cwd": str(repo), "tool_input": {"command": command}}
    )
    out: dict[str, str | None] = {}
    for script in registered_bash_guards():
        proc = subprocess.run(
            [_node(), str(script)],
            input=payload,
            cwd=str(repo),
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert proc.returncode == 0, (
            f"{script.name} must never exit non-zero: {proc.stderr}"
        )
        assert proc.stdout.strip(), f"{script.name} produced no output for {command!r}"
        decoded = json.loads(proc.stdout)
        out[script.name] = decoded.get("hookSpecificOutput", {}).get(
            "permissionDecision"
        )
    return out


# --- fixtures -----------------------------------------------------------------


@pytest.fixture(scope="module")
def oracle_dir(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A disposable directory that is **not** a git repository.

    Module-scoped: no shape writes to it (``_run_oracle`` asserts as much after
    every run), so sharing it costs nothing and saves a directory per case.
    """
    return tmp_path_factory.mktemp("oracle")


@pytest.fixture(scope="module")
def outcomes(oracle_dir: Path) -> dict[str, Outcome]:
    """The whole corpus classified **once**, by shape id.

    Module-scoped because the classification is the expensive half and both its
    readers — the anti-vacuity floor and the parametrized predicate — need the
    same answer. Running it per case ran every shape's oracle twice per session,
    which is over-processing (P2) and, worse, made the module's real spawn count
    diverge from the ceiling its own budget test asserts.

    Sharing is safe: :func:`_run_oracle` writes nothing that survives it (it
    asserts the work directory is empty afterwards) and the classification is a
    pure function of the shape and this host's bash. Under ``-n auto`` each
    xdist worker gets its own ``tmp_path_factory`` basetemp and so builds its
    own copy — per worker, not per case.
    """
    return {s.id: _run_oracle(s, oracle_dir) for s in SHAPES}


@pytest.fixture(scope="module")
def repo(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A repository on ``main`` with one commit, no marker and no declaration.

    The conservative fallback protected set applies and no marker covers the
    tree, so a *real* push to ``main`` from here denies — which is what makes an
    **allow** reading meaningful rather than an artefact of a permissive fixture.
    :func:`test_the_guard_payload_alone_is_denied_by_both_guards` pins that.

    Module-scoped and shared: the guards only read it, and no test here writes
    to it. Function scope would cost five git spawns per case.

    Its own copy rather than an import from a sibling test module: #467 removed
    exactly that coupling, and a ``test_*.py`` another one imports has become a
    library. The registration derivation *is* shared — see
    :mod:`tests.unit._bash_guards` for why that one is different.
    """
    root = tmp_path_factory.mktemp("repo")

    def git(*args: str) -> None:
        subprocess.run(["git", *args], cwd=root, check=True, capture_output=True)

    git("init", "-q", "--initial-branch=main")
    git("config", "user.email", "t@example.com")
    git("config", "user.name", "t")
    (root / "a.txt").write_text("one\n")
    git("add", "a.txt")
    git("commit", "-q", "-m", "first")
    return root


# --- AC-2: one template, two instantiations -----------------------------------


def test_each_shape_has_exactly_one_payload_hole_and_one_sentinel_hole() -> None:
    for shape in SHAPES:
        assert shape.template.count("PAYLOAD") == 1, shape.id
        assert shape.template.count("SENTINEL") == 1, shape.id


def test_shape_ids_are_unique() -> None:
    """A duplicate id silently renames a parametrize case.

    Which would falsify a mutation table's node-id prediction, and ``mutate.py``
    compares the observed failure set to the prediction by equality.
    """
    ids = [s.id for s in SHAPES]
    assert len(ids) == len(set(ids)), sorted(ids)


def test_the_two_instantiations_differ_only_in_the_payload_span() -> None:
    """AC-2, mechanically: the same string modulo one span."""
    for shape in SHAPES:
        oracle = _render(shape.template, ORACLE_PAYLOAD).replace(ORACLE_PAYLOAD, "\0")
        guard = _render(shape.template, GUARD_PAYLOAD).replace(GUARD_PAYLOAD, "\0")
        assert oracle == guard, shape.id


# --- AC-1: the instrument -----------------------------------------------------


def test_no_template_can_produce_the_observations_without_running_them() -> None:
    """The whitespace seam, proved rather than argued.

    A quoted body copies its payload text to stdout. If the marker were a
    substring of that text, every inert shape would read as executing. This also
    self-defends: collapse the seam and ``ORACLE_PAYLOAD`` starts containing
    ``MARKER`` and this goes red immediately.
    """
    for shape in SHAPES:
        rendered = _render(shape.template, ORACLE_PAYLOAD)
        assert MARKER not in rendered, shape.id
        assert SENTINEL not in rendered, shape.id


def test_the_oracle_payload_prints_the_marker_when_it_runs(oracle_dir: Path) -> None:
    """The instrument's positive control — expected values are allowed here.

    The subject is the instrument, not a guard.
    """
    proc = subprocess.run(
        [BASH, "--noprofile", "--norc", "-c", ORACLE_PAYLOAD],
        cwd=str(oracle_dir),
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert proc.stdout.strip() == MARKER


def test_copying_the_oracle_payload_text_does_not_print_the_marker(
    oracle_dir: Path,
) -> None:
    """The instrument's negative control: the seam survives a verbatim copy."""
    script = _render("cat <<'EOF'\nPAYLOAD\nEOF\nSENTINEL\n", ORACLE_PAYLOAD)
    proc = subprocess.run(
        [BASH, "--noprofile", "--norc", "-c", script],
        cwd=str(oracle_dir),
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert SENTINEL in proc.stdout, "the control script did not run to completion"
    assert MARKER not in proc.stdout


def test_the_oracle_separates_executing_shapes_from_inert_ones(
    outcomes: dict[str, Outcome],
) -> None:
    """The anti-vacuity floor — the most important test in this module.

    If bash were broken, misconfigured, or the corpus all read one way, every
    parametrized case below would skip and the harness would be green while
    measuring nothing. Two identically-failed runs compare equal (#466/#484), so
    this carries the control that must differ: **both classes non-empty, and
    nothing unusable.**

    It deliberately does not name which shapes belong to which class — that
    would be expected verdicts arriving by another route.
    """
    table = "\n".join(
        f"  {i:44s} usable={o.usable!s:5s} executed={o.executed!s:5s} {o.reason}"
        for i, o in outcomes.items()
    )
    unusable = [i for i, o in outcomes.items() if not o.usable]
    assert not unusable, f"shapes that could not be measured: {unusable}\n{table}"
    ran = [i for i, o in outcomes.items() if o.executed]
    inert = [i for i, o in outcomes.items() if not o.executed]
    assert ran, f"no shape executed — the oracle is not measuring anything\n{table}"
    assert inert, (
        "every shape executed — the corpus holds no inert control, so an "
        f"always-true oracle would look identical\n{table}"
    )


# --- the guard side's controls ------------------------------------------------


def test_the_guard_payload_alone_is_denied_by_both_guards(repo: Path) -> None:
    """Payload potency, and the fixture's protection, in one assertion.

    Without this every ``allow`` reading below could be an artefact of a payload
    nothing objects to or a fixture nothing protects (#538: a control that never
    reaches the predicate is vacuous).
    """
    verdicts = _verdicts(GUARD_PAYLOAD, repo)
    assert verdicts, "no hook is registered against Bash"
    assert all(v == "deny" for v in verdicts.values()), verdicts


def test_an_ordinary_command_is_allowed_by_every_guard(repo: Path) -> None:
    """The guards are not simply denying everything."""
    verdicts = _verdicts("git status --short", repo)
    assert all(v != "deny" for v in verdicts.values()), verdicts


# --- AC-3: the predicate ------------------------------------------------------


@pytest.mark.parametrize("shape", SHAPES, ids=lambda s: s.id)
def test_a_shape_bash_executes_is_not_allowed_by_both_guards(
    shape: Shape, outcomes: dict[str, Outcome], repo: Path
) -> None:
    """The differential. Bash decides what runs; the guards must not allow it.

    A characterisation test — see *Mutation evidence* in the module docstring.
    If this goes red on an unmutated tree it has found a live fail-open: record
    the shape and hold the ticket. ``hooks/`` is a protected area.
    """
    outcome = outcomes[shape.id]
    assert outcome.usable, (
        f"{shape.id}: {outcome.reason}. A shape that cannot be measured is a "
        "defect in this corpus, not a shape bash declines to execute."
    )
    if not outcome.executed:
        # Deliberately not a `pytest.skip`. `test_verify_toolchain_preflight.py`
        # refuses a skip **positionally** — in a function that resolves no
        # binary — and an implication whose antecedent is false is the compliant
        # encoding of the same thing.
        #
        # The residual, stated rather than argued away: this does not make the
        # suite host-independent. Whether a shape executes is a fact about *this
        # host's* bash, so a different bash runs a different amount of this
        # module either way — the `return` removes the undeclared skip site, not
        # the variance, and unlike a skip it does not surface in the report at
        # all. `test_the_oracle_separates_executing_shapes_from_inert_ones` is
        # an **aggregate** floor: it catches the corpus collapsing to one class,
        # and it cannot see a *single* shape flipping to inert — through a
        # template typo or a future bash — and quietly ceasing to test anything.
        # Closing that would need a per-shape expected-executability field,
        # which is the expected verdict AC-1 exists to refuse. The floor is the
        # strongest control compatible with AC-1, and it is not a total one.
        return

    command = _render(shape.template, GUARD_PAYLOAD)
    verdicts = _verdicts(command, repo)
    assert "deny" in verdicts.values(), (
        f"{shape.id}: bash runs the payload in this shape and every registered "
        f"Bash guard allowed it — a fail-open in a fail-closed guard.\n"
        f"  targets: {shape.why}\n"
        f"  command: {command!r}\n"
        f"  verdicts: {verdicts}"
    )


# --- AC-5: the bound ----------------------------------------------------------


def test_the_corpus_stays_within_its_subprocess_budget() -> None:
    """Refuses corpus growth past the bound without a decision.

    A ceiling over **the whole module's bash and node spawns**, not over the
    parametrized predicate alone — the earlier version counted only the shapes
    and so sat below the module's real cost, which is the direction that lets
    growth through. All four sources are in the arithmetic below: a
    classification per shape, a guard run per executing shape per guard, the two
    instrument controls, and the two guard-side controls. It is not a ceiling
    over every subprocess — the module's git spawns outnumber these, and the
    module docstring records why they are held by this bound rather than beside
    it.

    The observed cost is lower than this, because only the executing shapes
    reach their guard runs; the measured figure and how it was taken are in the
    module docstring. What is asserted here is the bound, per law 2.
    """
    guards = len(registered_bash_guards())
    ceiling = (
        len(SHAPES) * (1 + guards) + _BASH_CONTROLS + _GUARD_CONTROLS * guards
    )
    assert ceiling <= SPAWN_BUDGET, (
        f"{len(SHAPES)} shapes x (1 bash + {guards} guards) + {_BASH_CONTROLS} "
        f"bash controls + {_GUARD_CONTROLS} x {guards} guard controls = "
        f"{ceiling} spawns, over the {SPAWN_BUDGET} budget. Raising the budget "
        "is a decision about gate wall-clock, not a formality."
    )
