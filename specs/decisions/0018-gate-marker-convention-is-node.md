# ADR 0018 — The gate-marker convention is implemented once, in Node

- **Status:** Accepted
- **Date:** 2026-08-25
- **Source:** tickets #500 and #507; consumer migration follow-up #501.

## Context

The gate marker is one convention with three implementations: a writer invoked by `scripts/verify.sh`, and two readers — `hooks/gate-evidence-guard.js` (Stop) and `hooks/push-target-guard.js` (PreToolUse) — that decide from it. The two readers cannot be anything but JavaScript: Claude Code runs hooks under Node, and ADR 0017's predecessor work (#302) already had to fix their module type in place, because a mis-resolved hook is a silently disarmed enforcement control. The writer was Python for one reason only — `scripts/` is Python — and that made a single agreement about a file path, a tree algorithm and one environment variable span two languages.

The cost was paid continuously rather than once. `tests/unit/test_gate_marker_contract.py` exists solely because the path is computed in three places and the tree in two, and drift there is silent and total: a reader computing a slightly different path finds no marker ever and denies every time, and one computing a slightly different tree finds a marker covering something else. A repo hydrating the harness had to receive a Python file to run a gate whose enforcement half was JavaScript. And `scripts/mutate.py`'s gate lock reached the convention by importing the Python module, because a second Python parser of `HARNESS_GATE_MARKER_MAX_AGE_SECONDS` was not acceptable.

The divergence was not hypothetical. Measured at #500: the Python parser used `int()` and the two JavaScript parsers a digits-only regex, so `"+60"` and `" 60 "` produced 60 seconds on the writer's side and the 86400-second default on both readers'. No case in the equivalence test sampled either spelling, so the disagreement stood unobserved for as long as it existed.

## Decision

**The gate-marker convention is written in Node everywhere it appears. `scripts/gate-marker.js` is the one writer — CommonJS, Node standard library only, no npm dependency, no transpiler, no TypeScript, and no second maintained implementation. `scripts/gate_marker.py` is deleted.**

The principle boundary this draws, and the rule that decides for the next file:

**A contract with an implementation forced into a runtime by its host is implemented in that runtime everywhere.** The hooks are forced into Node by Claude Code, so the marker convention is Node end to end. Everything else under `scripts/` stays Python: its only host is the gate, which already runs `uv`, and Python is where this repo's lint, type-check and coverage instruments reach. The test for the next executable file is one question — *does any part of this contract already run inside a host-imposed runtime?* If yes, it joins that runtime beside the code that is already there. If no, it is Python. Neither answer may introduce a build step, a package manager, or a non-stdlib dependency; that constraint is what `hooks/` and `scripts/` already share and it is not relaxed here.

The module type is pinned by `scripts/package.json` (`{"type": "commonjs"}`), the same one-key mechanism and the same reasoning as `hooks/package.json`: Node resolves a `.js` file's type from the nearest `package.json` walking up, and in a consuming repo that walk otherwise terminates at a root the harness does not control.

### Marker-emission boundary (amended by #507 and #510)

`gate-marker.js` exposes no direct successful write command. Its public `run`
subcommand accepts no operands and resolves its gate command only from
`commands.verify` in `CLAUDE.md`; it consults legacy `CONTEXT.md` only when
`CLAUDE.md` is absent, then uses `bash scripts/verify.sh` only when neither
spine exists. A present spine with a missing, empty, duplicate, malformed, or
unreadable selected field is infrastructure (exit 3), not a fallback. Three
spellings are refused rather than read: a value opening with a yaml indicator
(`|`, `>`, `&`, `*`, `{`, `[`), whose line-reader answer is the indicator
character itself; a value that opens with a quote without being one whole
enclosing quoted scalar — unterminated, or carrying content after its close —
which a reader stripping "one surrounding pair" turns into a fragment `sh`
re-tokenises into a *different* command that can exit 0 and mint a marker for a
tree whose declared gate never ran (#510, third review cycle); and the one-line
flow mapping `commands: {verify: …}`, which is **deliberately unread**. Quoting
is recognised only where yaml recognises it, at the first character of the
value, so an apostrophe inside a plain scalar (`verify: echo it's fine # x`) is
ordinary text and its trailing comment is still a comment. The sibling
`branches:` reader parses that flow spelling
and this one will not: a second flow parser buys a fragment where an explicit
exit 3 is the safe answer, and every hydrated spine writes the block form. The
runner launches that checked-in declaration through fixed `sh -c`, with
`HARNESS_GATE_MARKER_RUNNER=1`, and forwards its output and exit status. It
refuses to run at all when it finds that variable already set: the child is now
an arbitrary declared command, and one that delegates back to `run` — directly,
or through an `npm run verify` that wraps the public entry — would re-run the
gate at every level and let an inner level emit a marker for the tree while the
outer stages were still running. `verify.sh`'s check on the same variable was
that guard only while the sole launchable child was `verify.sh`. Only after a
measured zero exit does its non-exported emitter write the tree-named marker
and record `exit: 0` in the diagnostic payload.

**Exit 3 is narrower than this record first stated, and the widening is
deliberate (#510, second review cycle).** It covers a gate declaration this
runner could not *resolve* — an unreadable spine, or a selected field missing,
empty, duplicate or malformed — plus an absent legacy `scripts/verify.sh` in a
repo with no spine, plus the re-entry refusal above. It does **not** cover a
declared command the shell cannot launch: under `sh -c` the runner never
observes that failure, because the shell reports it as its own 127 and that
status is forwarded like any other non-zero result. Mapping 127 back to 3 was
considered and rejected: a consumer's own gate can legitimately exit 127 from an
inner command, and conflating the two would classify a genuinely red tree as
broken infrastructure — the one direction this exit code exists to keep apart. A
red stage still preserves its own non-zero exit and produces no evidence.

The public `scripts/verify.sh` delegates to that runner. Its internal-mode path
retains the consumer's shell-compatible verification stages and does not write a
marker. `write` is retired with usage exit 64. Query operations
(`preflight`, `tree`, `path`, and `status`) remain public. This narrows the
supported interface without claiming cryptographic attestation: a process able
to modify the checkout can rewrite `commands.verify` or the old shell path, so
it remains in the same local trust domain; CI and server-side branch protection
remain authoritative. Callers cannot choose a command by an operand or an
environment variable.

#501 is downstream adoption work only. It refreshes consumer wiring to this
contract and does not redefine the marker interface.

## Alternatives rejected

- **Keep the Python writer and add a Node one.** Two maintained writers is exactly the drift the equivalence test exists to catch, doubled, and the convention would then have four implementations of the freshness parse.
- **TypeScript.** Needs a transpiler and an install step in every consuming repo, for a file whose entire job is to run before anything else can be trusted. A gate that needs a dependency to run is a gate that can fail for reasons unrelated to the tree.
- **Move the hooks to Python.** Not available: the host runs hooks under Node.
- **One shared module `require`d by the writer and both hooks.** Collapses the equivalence test into a tautology, and re-opens two structural objections that predate this record: `tests/unit/test_hooks_fail_open_is_loud.py` and `tests/unit/test_hooks_module_type.py` scan `hooks/*.js` non-recursively, so a `lib/` subdirectory is a silent hole in both; and a shared module's own load failure disarms both enforcement hooks at once. Three copies held by an executing equivalence test add no failure mode of their own.
- **A `.cjs` extension instead of a manifest.** On the merits this is the better answer for a brand-new file with no installed callers: the extension is authoritative regardless of any manifest, needs no `scripts/package.json`, and has no directory-wide side effect anywhere. It is rejected here for one reason and no other — **the ticket fixes the name `.js` verbatim, in its approach and in its acceptance criteria, and a verbatim criterion is an operator decision already taken.** The reason the hooks did not take `.cjs` — their `.js` paths were already wired into every installed `.claude/settings.json` — does not apply to a new file, so it is not available as a supporting argument here. #510 reconsidered this alternative under the condition recorded here and retained the shipped name: a rename would add migration work outside that ticket.

## Consequences

- **127 statements leave the `--cov=scripts` measurement** — the deleted module's own count, from coverage's parser. Measured at the shipping tree, the gate reports **86.75%** (720 of 830 statements), comfortably above the floor. The 82% floor does not move: the floor is a ratchet and rises with coverage, so a fall inside it changes nothing, and lowering it to chase the new number would convert a ratchet into a target.
- **Nothing replaces that line-coverage assurance, and this record does not pretend otherwise.** No JavaScript coverage instrument exists in this repo and adding one would need the npm dependency this decision refuses. The writer joins `hooks/*.js` — this repo's existing body of production JavaScript — as executable code held by enumerated behavioural tests rather than by a coverage number. What is genuinely lost is the *unwritten-case* signal: a branch nobody wrote a case for used to appear as a missed line and now appears as nothing. Two things stand in for it, both weaker than coverage on breadth and stronger on depth. The port carries every case the deleted Python module asserted, enumerated one by one in `tests/unit/test_gate_marker_js.py`'s docstring rather than left to a reader's memory; and `scripts/mutate.py` mutates by literal text substitution over any named file, so those cases are mutation-provable — an instrument line coverage never was.
- **`node` becomes a hard precondition of `scripts/mutate.py run`**, not only of the test suite. It already was in practice — the gate lock requires a marker, and only a gate run that could execute node produces one — and the port makes it direct. A missing node now surfaces as `RunnerUnavailableError` (exit 3, infrastructure) rather than as a refusal about the tree, because a refusal is a fact about the tree and a host without node says nothing about the tree. `mutate check` stays node-free.
- **`scripts/mutate.py` may now spawn one binary that is not its own interpreter**, and the widening is stated as a shape rather than as a name. The module's safety invariant is that nothing in it reaches the tree through an external tool — restoration reads from backups, never `git checkout`, which is the revert that cost #163 forty minutes of finished work. Permitting the *binary* `node` would not protect that, because `node -e` runs anything. The guard therefore permits exactly one three-element argv: the literal `node`, a module-level name resolved from its own assignment to something built from the literal `gate-marker.js`, and the literal `status`, which is read-only by construction. There is no list to go stale, and the only widening direction left is a deliberate edit to the guard.
- **The gate's toolchain probes move above its nested-worktree preflight**, because the preflight is now itself a node invocation and a broken node must be reported as a broken node rather than as a nested worktree. The wrapper also splits its diagnostic on the helper's exit code — exactly 2 is the helper reporting a fact about the repository, anything else is a helper that could not run. A developer-visible consequence: a checkout without a runnable node stops at exit 97 before the preflight instead of after it.
- **A consuming repo receives a JavaScript gate helper plus a `scripts/package.json`.** The manifest can affect every immediate module-bearing source in `scripts/`: `*.js`, `*.mjs`, `*.cjs`, `*.ts`, `*.mts`, and `*.cts`, not only ESM JavaScript siblings. #510 changes hydration to a closed-world predicate: flat managed assets are permitted only when each such source is the recognised managed helper and the manifest is absent or CommonJS. Any other source or incompatible manifest retains every gate asset and names each blocker. This repo takes the flat form because its sole module-bearing source is the managed helper and it has no root `package.json`.
- **The equivalence test survives the language convergence but loses its out-of-family oracle.** With all three copies in one language, "all three agree" can be satisfied by all three being wrong, so each equivalence now carries an independently constructed expected value beside it — a marker path built from the literal constant this design pins, and a hand-written table of freshness answers. A further assertion holds the three textually independent: no literal `require` in any of them resolves to another — resolved through Node's file and index arms, so the extensionless spelling counts — and none names anything outside Node's own `builtinModules`. It reads literal specifiers only; a computed one is beyond what a predicate over text can decide.
- **The internal-mode variable is inherited by everything the gate starts, and it is now read back.** `run` sets `HARNESS_GATE_MARKER_RUNNER=1` on the declared gate's whole environment, so every descendant of that gate carries it — a test suite included — and the re-entry refusal above therefore refuses *any* nested public `run` beneath a running gate, not only a gate that calls the runner on purpose. Measured in this repository when the refusal landed: 57 tests that drive `run` as a public entry failed under `bash scripts/verify.sh` while passing under a bare `pytest`. The remedy is one fixture in `tests/conftest.py` that drops the inherited variable, so the suite means the same thing however it is launched; a consumer whose gate builds a sub-project that runs its own gate is in the same position with the same remedy. No opt-out is offered: an environment variable that switched this check off would be exactly the per-invocation control over the runner that the boundary above exists to refuse.
- **The hydration predicate is held by a documentation guard, and that is a recorded exception to ADR 0017 D5 (#510).** D5 admits a guard that asserts code behaviour, a spine property, asset integrity, frontmatter compliance, or tree-consistency; `tests/unit/test_gate_marker_module_type.py`'s suffix and polarity guards read `commands/init.md` and assert what that document *says*, which is none of the five, and "restatement agreement" is named in D5 as a class that dies. The exception is taken for one reason: the manifest's blast radius — which suffixes `scripts/package.json` retypes — is the whole of #510's second problem, and the procedure that decides it is prose in this repo and code in no repo, so the alternative is no mechanical hold at all. The consequence is stated rather than implied: **#510's AC-5 and AC-6 are discharged by a documentation guard, not by behavioural coverage.** It is recorded here rather than by amending D5 because D5 argues its own class (e) was added *as a class* "rather than left as a recorded exception because an exception in prose is precedent-shaped"; keeping this one inside the ADR that owns the hydration contract is what bounds it to that contract. It retires when hydration becomes executable — the moment an agent-run procedure is replaced by a program, the predicate falls under D5 class (a) and these guards are rewritten to execute it.
- **One behaviour deliberately departs from the writer being replaced.** Python's `prune` documented itself as best-effort and was not: it sorted markers by `Path.stat().st_mtime`, so a marker unlinked by a concurrent gate run in another worktree between the sort and the loop raised — and because the prune runs *after* the marker is written, that race turned a green gate red with the evidence already on disk. The Node prune skips a file that has vanished. This is a fix, not a port, and it is recorded here so it is not mistaken for one.
