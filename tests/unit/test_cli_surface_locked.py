"""CLI command-surface lock — documented invocations must match the registered set.

CAL-603 (insight CODE-2-INSIGHT). ``test_docs_consistency.py`` checks that docs
are *present*; it does not check that the command surface the docs tell an agent
to invoke matches the surface the CLI actually *registers*. That gap is what let
the engine-era ``harness run <workflow>`` surface (SPEC §11) and the live intake
breakage (CAL-601) drift undetected — docs kept naming a command the CLI no
longer has.

Three locks:

* **Registered surface** — the Typer app registers exactly the as-built verb set
  (the three audited verbs plus the read/inspection and ops commands) and none of
  the retired engine commands (``run`` / ``validate`` / ``decisions`` /
  ``decision``).
* **Documented surface == registered** — the command surface *documented* in
  SPEC §11 and the agent-facing contract ``commands/harness.md`` is derived (not
  hard-coded) and compared against the registered set, so a doc that adds, drops,
  or renames a command relative to the CLI is caught.
* **Live-doc references** — no *live* doc names a retired CLI invocation
  (``harness run`` / ``harness validate``), a retired ``run <workflow>``
  subcommand (caught even across a multiline docker invocation), or a retired
  engine artefact (``harness.engine|nodes|dispatch|workflow`` module paths,
  ``workflows/*.yaml``). "Live" deliberately excludes retained historical
  reference: in ``SPEC.md`` only the sections its status banner declares current
  (§1–2, §4, §11) are scanned, and the dated-supersede-bannered specs under
  ``specs/`` are skipped entirely. The ``/harness run <ticket>`` *slash command*
  is the current canonical entrypoint and is explicitly allowlisted — it is not
  the retired ``harness run <workflow>`` CLI invocation.

The companion check in ``test_engine_retired.py`` asserts the retired *modules*
are unimportable; this asserts the retired *command surface* is absent from the
registered CLI and the live docs, and that the documented surface tracks the
registered one.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent.parent
SPEC = REPO_ROOT / "SPEC.md"
HARNESS_CONTRACT = REPO_ROOT / "commands" / "harness.md"


# --- Registered surface -------------------------------------------------------

#: The verb + read/ops command set the CLI is expected to register, as-built
#: (``harness/cli/__init__.py``). Adding a stray command or dropping a verb
#: should fail here, not silently drift from the documented contract.
EXPECTED_SURFACE = {
    "start",
    "review",
    "close",  # the three audited verbs
    "status",
    "logs",
    "events",
    "runs",  # read / inspection
    "cancel",
    "reclaim",
    "doctor",
    "version",
    "worktrees",
}

#: Retired engine-era commands. None may be registered or documented as live.
RETIRED_COMMANDS = {"run", "validate", "decisions", "decision"}


def _registered_surface() -> set[str]:
    """Every command and sub-app the Typer app registers."""
    from harness.cli import app

    names = {c.name for c in app.registered_commands if c.name is not None}
    names |= {g.name for g in app.registered_groups if g.name is not None}
    return names


def test_registered_surface_is_the_as_built_verb_set() -> None:
    """The registered CLI surface is exactly the as-built verb set."""
    assert _registered_surface() == EXPECTED_SURFACE


def test_no_retired_engine_command_registered() -> None:
    """The retired engine commands are not registered."""
    assert RETIRED_COMMANDS.isdisjoint(_registered_surface())


# --- CLI identity prose lock --------------------------------------------------
# CAL-634 (CODE-1 / CODE-3). The surface locks above guard command *names*; they
# never guarded the prose that describes what the tool *is*. The top-level
# ``--help`` banner (``harness/cli/__init__.py``) and the package docstring
# (``harness/__init__.py``) both still called the harness a "deterministic
# workflow execution engine/harness" — the retired engine model SPEC §1
# explicitly inverted ("a set of deterministic, audited verbs an agent calls —
# *not* a pipeline that drives agents"; the engine was deleted in CAL-574, §3
# banner). The ``--help`` banner is a public-contract surface (SPEC §1.5), so a
# user reading it was told the opposite of the current model. This locks the
# live identity prose to the verb model.

#: Retired deterministic-engine framing that must not describe the live tool.
_RETIRED_FRAMING = re.compile(r"workflow execution|\bengine\b", re.I)


def test_cli_help_banner_describes_the_verb_model() -> None:
    """The ``harness --help`` banner names the verb model, not the retired engine.

    Asserts on ``app.info.help`` — the exact source string Typer renders as the
    banner — so the check is not subject to terminal-width wrapping.
    """
    from harness.cli import app

    banner = app.info.help or ""
    assert not _RETIRED_FRAMING.search(banner), (
        f"`harness --help` banner still uses retired engine framing: {banner!r}. "
        "The engine was retired (CAL-574); describe the verb model (SPEC §1) "
        "instead — e.g. 'deterministic, audited verbs an agent calls'."
    )
    assert "verb" in banner.lower(), (
        f"`harness --help` banner should name the verb model: {banner!r}."
    )


def test_package_docstring_describes_the_verb_model() -> None:
    """The ``harness`` package docstring names the verb model, not the engine."""
    import harness

    doc = harness.__doc__ or ""
    assert not _RETIRED_FRAMING.search(doc), (
        f"`harness` package docstring still uses retired engine framing: {doc!r}. "
        "Describe the verb model (SPEC §1) — 'deterministic, audited verbs an "
        "agent calls'."
    )
    assert "verb" in doc.lower(), (
        f"`harness` package docstring should name the verb model: {doc!r}."
    )


# --- Documented surface == registered -----------------------------------------

#: A ``harness <verb>`` invocation that is **not** the ``/harness run`` slash
#: command (allowlisted via the negative lookbehind on ``/``). The ``\bharness``
#: boundary leaves ``~/bin/harness`` and prose like "the harness" alone.
_INVOCATION = re.compile(r"(?<!/)\bharness (\w+)")

#: A fenced code block's body — invocations are read from fences, not prose, so a
#: phrase like "the harness pipeline" is never mistaken for a ``pipeline`` verb.
_FENCE = re.compile(r"```[^\n]*\n(.*?)```", re.DOTALL)


def _verbs_in_fences(text: str) -> set[str]:
    return {v for block in _FENCE.findall(text) for v in _INVOCATION.findall(block)}


def _spec_command_surface_block() -> str:
    """The fenced body of SPEC §11's '### Command surface' subsection."""
    text = SPEC.read_text()
    section = text.index("## 11. CLI Design")
    header = text.index("### Command surface", section)
    open_fence = text.index("```", header)
    close_fence = text.index("```", open_fence + 3)
    return text[open_fence + 3 : close_fence]


def test_spec_command_surface_equals_registered() -> None:
    """SPEC §11's documented command surface matches the registered set exactly."""
    documented = set(_INVOCATION.findall(_spec_command_surface_block()))
    assert documented == _registered_surface()


def _real_options() -> dict[str, set[str]]:
    """Map every command (incl. ``worktrees list`` / ``worktrees cleanup``) to the
    set of ``--long`` options it actually exposes, via the live Typer/click app."""
    import click
    import typer.main

    from harness.cli import app

    cli = typer.main.get_command(app)
    sigs: dict[str, set[str]] = {}

    def longs(cmd: click.Command) -> set[str]:
        return {
            o
            for p in cmd.params
            if isinstance(p, click.Option)
            for o in p.opts
            if o.startswith("--")
        }

    for name, cmd in cli.commands.items():
        sub = getattr(cmd, "commands", None)
        if sub:
            for sn, sc in sub.items():
                sigs[f"{name} {sn}"] = longs(sc)
        else:
            sigs[name] = longs(cmd)
    return sigs


def _documented_options() -> dict[str, set[str]]:
    """Map each command documented in SPEC §11's command surface to the set of
    ``--long`` options that appear on its line."""
    sigs: dict[str, set[str]] = {}
    for line in _spec_command_surface_block().splitlines():
        m = re.match(r"harness (\w+(?: \w+)?)", line)
        if m is None:
            continue
        # Strip a trailing ``# comment`` so a ``--flag`` mentioned in prose there
        # is not counted as a documented option.
        sig = line.split("#", 1)[0]
        sigs[m.group(1)] = set(re.findall(r"--[\w-]+", sig))
    return sigs


def test_documented_options_exist_on_the_command() -> None:
    """Every ``--option`` SPEC §11 documents is a real option on that command.

    Locks the *signatures*, not just the command names — a doc that invents or
    misattributes a flag (e.g. ``cancel --run-id``, which does not exist) is
    caught. Documenting a subset of a command's real options is fine.
    """
    real = _real_options()
    drift = {
        cmd: sorted(opts - real.get(cmd, set()))
        for cmd, opts in _documented_options().items()
        if opts - real.get(cmd, set())
    }
    assert not drift, (
        f"SPEC §11 documents options the CLI does not expose: {drift}. "
        "Correct the signature against `harness/cli/` (Typer params)."
    )


def test_contract_documents_only_registered_verbs() -> None:
    """Every ``harness <verb>`` the agent-facing contract invokes is registered.

    ``commands/harness.md`` documents a subset (the loop verbs) — the lock is
    that it never names a verb the CLI does not register (the CAL-601 failure
    mode), not that it enumerates the whole surface.
    """
    documented = _verbs_in_fences(HARNESS_CONTRACT.read_text())
    unknown = documented - _registered_surface()
    assert not unknown, (
        f"{HARNESS_CONTRACT.relative_to(REPO_ROOT)} documents `harness <verb>` "
        f"invocation(s) the CLI does not register: {sorted(unknown)}. Either the "
        "verb was removed/renamed or the doc drifted — reconcile against "
        "`harness/cli/__init__.py`."
    )


# --- Live-doc reference lock --------------------------------------------------

#: Docs that describe how to *use* the harness right now. Spec design history
#: under ``specs/`` is excluded — those files carry their own supersede banners
#: (enforced by ``test_docs_consistency.py``). ``SPEC.md`` is included but only
#: its live prefix is scanned (see ``_live_text``).
def _live_docs() -> list[Path]:
    docs = [
        REPO_ROOT / "README.md",
        REPO_ROOT / "CONTEXT.md",
        REPO_ROOT / "CLAUDE.md",
        SPEC,
        REPO_ROOT / "docker" / "README.md",
        REPO_ROOT / "docker" / "entrypoint.sh",
        REPO_ROOT / "docker" / "Dockerfile",
        REPO_ROOT / "docker" / "docker-compose.yml",
    ]
    docs += sorted((REPO_ROOT / "commands").glob("*.md"))
    docs += sorted((REPO_ROOT / "skills").glob("*.md"))
    # Design specs under specs/ are scanned too — but the deliberately-retained
    # engine specs carry a dated supersede banner and are skipped (the same rule
    # `test_docs_consistency.py` enforces). Non-superseded specs (the current
    # subsystem docs and the accepted proposal) describe the live system and
    # must not reference a retired surface.
    docs += [
        s
        for s in sorted((REPO_ROOT / "specs").glob("**/*.md"))
        if not _has_supersede_banner(s)
    ]
    return [d for d in docs if d.exists()]


#: Dated supersede banner near the top of a file — ``> **Superseded 2026-06-11**``
#: — the same recognition ``test_docs_consistency.py`` uses to mark a spec as
#: retained history. Only the first lines matter (an agent reads the lede).
_SUPERSEDE_BANNER = re.compile(r"^>\s*\*\*Superseded\s+\d{4}-\d{2}-\d{2}")
_BANNER_SCAN_LINES = 12


def _has_supersede_banner(path: Path) -> bool:
    head = path.read_text().splitlines()[:_BANNER_SCAN_LINES]
    return any(_SUPERSEDE_BANNER.match(line) for line in head)


#: The retired deterministic workflows the engine-era CLI ran as
#: ``harness <image> run <workflow>``. Caught as a standalone ``run <workflow>``
#: token so a *multiline* docker invocation — ``harness:dev \`` then ``run
#: steward …`` on the next line — is still flagged (the ``harness run`` form
#: alone misses it).
_RETIRED_WORKFLOWS = "build-codex|build|feature|steward|bugfix|release"

#: Retired surface references that must not appear in a live doc:
#: the bare ``harness run/validate`` CLI invocation (not the ``/harness run``
#: slash command), a retired ``run <workflow>`` subcommand, a retired engine
#: module path, or a retired workflow YAML file.
_RETIRED_REFERENCE = re.compile(
    # ``harness run <anything>`` as the CLI invocation — an *arbitrary* workflow
    # name (the retired CLI accepted any), a ``<placeholder>``, or a ``--flag``.
    # The lookahead requires a real argument token after ``run`` so the English
    # noun "a harness run." (followed by punctuation) and annotations like
    # "`harness run` (legacy)" are left alone; the ``\s`` after ``run`` keeps the
    # live ``harness runs`` read command (no space before ``s``) out of scope.
    r"(?<!/)\bharness run(?=\s+[<\w-])"
    r"|(?<!/)\bharness validate\b"  # retired `harness validate`
    rf"|\brun (?:{_RETIRED_WORKFLOWS})\b"  # bare `run <workflow>` across a multiline
    #                                        docker invocation (no `harness ` on the
    #                                        same line); restricted to the known
    #                                        workflow names so `docker run` / `uv run`
    #                                        are not swept up.
    r"|\bharness\.(?:engine|nodes|dispatch|workflow)\b"  # retired engine modules
    r"|\bworkflows/[A-Za-z0-9_-]+\.yaml\b"  # retired workflow YAML file
)

#: SPEC.md is live only in the sections its own status banner declares current:
#: §1–2 (the model), §4 (modules), and §11 (CLI). §3 and §5–§10, §12–§14 are
#: retained engine history behind the §3 banner and are not scanned. (If another
#: section is promoted to current, add it here and to the banner together.)
_SPEC_LIVE_SECTIONS = (1, 2, 4, 11)


def _spec_section_text(num: int, full: str) -> str:
    """Body of SPEC section ``## <num>. …`` up to the next ``## <n>.`` heading."""
    start = re.search(rf"^## {num}\. ", full, re.M)
    if start is None:
        return ""
    rest = full[start.end() :]
    nxt = re.search(r"^## \d+\. ", rest, re.M)
    return rest[: nxt.start()] if nxt else rest


def _live_text(path: Path) -> str:
    text = path.read_text()
    if path == SPEC:
        return "\n".join(_spec_section_text(n, text) for n in _SPEC_LIVE_SECTIONS)
    return text


@pytest.mark.parametrize(
    "doc", _live_docs(), ids=lambda p: str(p.relative_to(REPO_ROOT))
)
def test_live_docs_have_no_retired_surface_reference(doc: Path) -> None:
    """No live doc references a retired CLI invocation or engine artefact.

    The ``/harness run <ticket>`` slash command is the current canonical
    entrypoint and is allowlisted; this fires only on the bare CLI form and on
    retired engine module / workflow-YAML references.
    """
    hits = [m.group(0) for m in _RETIRED_REFERENCE.finditer(_live_text(doc))]
    assert not hits, (
        f"{doc.relative_to(REPO_ROOT)} references retired surface "
        f"{sorted(set(hits))!r}. The deterministic engine was retired (CAL-574); "
        "the CLI no longer registers `run`/`validate` and the engine modules / "
        "`workflows/*.yaml` are gone. Rewrite to the as-built verb surface "
        "(`harness start/review/close`) or, for the slash command, `/harness run`."
    )


@pytest.mark.parametrize(
    "text, flagged",
    [
        # Retired CLI invocations — flagged. The name is arbitrary: the retired
        # `run <workflow>` accepted any workflow name, not a fixed list.
        ("harness run <workflow>", True),
        ("harness run feature --linear=CAL-1", True),
        ("harness run custom-workflow --foo", True),
        ("harness run --help", True),
        ("harness validate workflow.yaml", True),
        ("    harness:dev \\\n      run steward --domain=architecture", True),
        ("import harness.engine.runner", True),
        ("see workflows/feature.yaml for the inputs block", True),
        # Live / legitimate — not flagged.
        ("/harness run CAL-42", False),  # the slash command (current entrypoint)
        ("a deterministic harness run. That role is dissolved.", False),  # noun
        ("| `pending` | `harness run` (legacy) | …", False),  # historical annotation
        ("harness runs --failed", False),  # the live `runs` read command
        ("docker run --rm harness:dev start CAL-1", False),  # plain `docker run`
        ("uv run harness start CAL-1", False),  # `uv run`, then the live verb
    ],
)
def test_retired_reference_detection(text: str, flagged: bool) -> None:
    """The detector flags retired invocations (any workflow name) without
    catching the slash command, the English noun, or live `runs`/`docker run`."""
    assert bool(_RETIRED_REFERENCE.search(text)) is flagged


# --- Python module-docstring lock (CAL-699) -----------------------------------

#: Retired CLI *command* references — the subset of ``_RETIRED_REFERENCE`` that
#: names a command the CLI no longer registers (``harness run <arg>`` /
#: ``harness validate`` / a bare ``run <workflow>``). The full doc-scan rule also
#: flags retired engine *module paths* (``harness.nodes|engine|…``) and
#: ``workflows/*.yaml``; that part is deliberately omitted here because a Python
#: module docstring legitimately *narrates provenance* — e.g. ``harness/worktree
#: .py`` documents that it was "re-homed from the retired ``harness.nodes``
#: package (CAL-574)". A live CLI command *name*, by contrast, has no business
#: appearing in a docstring as if it were current (the ``harness validate`` line
#: that survived in ``test_cli_query.py`` is exactly this drift). So source
#: docstrings are held only to the narrower CLI-name rule.
_RETIRED_CLI_REFERENCE = re.compile(
    r"(?<!/)\bharness run(?=\s+[<\w-])"  # `harness run <arg>` CLI invocation
    r"|(?<!/)\bharness validate\b"  # retired `harness validate`
    rf"|\brun (?:{_RETIRED_WORKFLOWS})\b"  # bare `run <workflow>`
)

#: Python sources whose module docstring legitimately *documents* the retired
#: CLI surface as its subject — this guard names ``harness run`` / ``harness
#: validate`` precisely to lock them out. Excluded in the same spirit as the
#: supersede-bannered specs skipped by ``_live_docs()``.
_RETIRED_CLI_DOCSTRING_ALLOWLIST = {
    REPO_ROOT / "tests" / "unit" / "test_cli_surface_locked.py",
}


def _py_sources() -> list[Path]:
    """Python files under ``harness/`` and ``tests/`` whose *module docstring*
    is held to the retired-CLI-name rule (the allowlist removed)."""
    files: list[Path] = []
    for base in ("harness", "tests"):
        files += sorted((REPO_ROOT / base).rglob("*.py"))
    return [p for p in files if p not in _RETIRED_CLI_DOCSTRING_ALLOWLIST]


def _module_docstring(path: Path) -> str:
    """The module-level docstring only — not the full source. Scanning only the
    docstring keeps this guard's own retired-pattern *constants* (data in the
    body) from being read as if they were prose."""
    try:
        return ast.get_docstring(ast.parse(path.read_text())) or ""
    except SyntaxError:  # pragma: no cover - all repo sources parse
        return ""


@pytest.mark.parametrize(
    "src", _py_sources(), ids=lambda p: str(p.relative_to(REPO_ROOT))
)
def test_py_docstrings_have_no_retired_cli_reference(src: Path) -> None:
    """No Python module docstring names a retired CLI command as if it were live.

    ``_live_docs()`` scans ``.md``/``.sh`` only, so a retired command name in a
    Python docstring went uncaught (CAL-699 — ``test_cli_query.py`` kept naming
    the retired ``harness validate``). This closes that gap for source docstrings
    while leaving legitimate engine-module *provenance* notes alone.
    """
    hits = [m.group(0) for m in _RETIRED_CLI_REFERENCE.finditer(_module_docstring(src))]
    assert not hits, (
        f"{src.relative_to(REPO_ROOT)} module docstring names retired CLI "
        f"surface {sorted(set(hits))!r}. `run`/`validate` were retired with the "
        "deterministic engine (CAL-574); rewrite to the as-built verbs "
        "(`harness start/review/close`) or drop the stale reference."
    )


@pytest.mark.parametrize(
    "text, flagged",
    [
        # Retired CLI command names — flagged.
        ("harness validate workflow.yaml", True),
        ("harness run feature --linear=CAL-1", True),
        ("    run steward --domain=architecture", True),
        # Legitimate in a source docstring — NOT flagged. Engine-module
        # provenance and workflow-walking history are narration, not a live
        # command name; the slash command and live `runs` stay clear too.
        ("re-homed from the retired harness.nodes package (CAL-574)", False),
        ("import harness.engine.runner", False),
        ("the YAML-walking engine (engine.runner|executor|loop|retry)", False),
        ("/harness run CAL-42", False),
        ("a deterministic harness run. That role is dissolved.", False),
        ("harness runs --failed", False),
    ],
)
def test_retired_cli_reference_detection(text: str, flagged: bool) -> None:
    """The CLI-name detector flags retired *commands* but leaves engine-module
    provenance, the slash command, the English noun, and live `runs` alone."""
    assert bool(_RETIRED_CLI_REFERENCE.search(text)) is flagged
