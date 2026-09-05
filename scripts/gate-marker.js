#!/usr/bin/env node
/**
 * The gate marker — the one artifact that says *the gate ran green over these
 * exact bytes*.
 *
 * `scripts/verify.sh` runs this on its success path. It computes the git **tree
 * object** of the working tree it was run in and writes
 *
 *     <git-common-dir>/harness/gate/<tree-oid>.json
 *
 * Two Claude Code hooks read that file from opposite sides of one equality:
 * `hooks/gate-evidence-guard.js` (Stop) asks *does a marker cover the tree this
 * turn is claiming is finished?*, and `hooks/push-target-guard.js` (PreToolUse)
 * asks *does a marker cover the tree this push carries?*. `skills/build/SKILL.md`
 * already makes those the same object — its ship step refuses to integrate
 * unless `git rev-parse HEAD^{tree}` equals the tree the gate ran over — so one
 * marker authorises both.
 *
 * **Why JavaScript.** ADR 0018. The two readers cannot be anything but
 * JavaScript — the host runs hooks under Node — so a writer in Python made one
 * agreement about a file path, a tree algorithm and one environment variable
 * span two languages. The convention is now written in the runtime its host
 * imposed, once. The three copies stay separate on purpose (a shared module's
 * own load failure would disarm both enforcement hooks at once, and
 * `test_hooks_fail_open_is_loud.py` / `test_hooks_module_type.py` scan
 * `hooks/*.js` non-recursively, so a `hooks/lib/` would be a hole in both);
 * `tests/unit/test_gate_marker_contract.py` holds them equivalent by executing
 * all three, and holds them textually independent so that equivalence cannot
 * collapse into a tautology.
 *
 * **Why a tree and not a session.** `verify.sh` has no access to a session
 * identifier, and enforcement will not be built on an undocumented one. Tree
 * identity is the stronger claim on the axis that matters anyway: session scope
 * answers *did someone run the gate recently in this conversation*, which a
 * session that edited three files after the run still satisfies; tree identity
 * answers *did the gate exit 0 over these exact bytes*, which no subsequent edit
 * can satisfy. What it gives up, stated plainly: a marker produced by an earlier
 * session over an identical tree is admitted.
 *
 * **Why the git directory and not the working tree.** `.harness/` is gitignored
 * *in this repo*. In a consuming repo without that rule, a marker written into
 * the working tree would be picked up by the very `git add -A` that computes the
 * tree, moving the oid away from the one just recorded — a marker that can never
 * match, i.e. a silent, permanent fail-closed wedge in exactly the repos that
 * skipped an install step. The git common directory cannot be tracked by
 * construction, is shared across every linked worktree automatically, needs no
 * `.gitignore` change anywhere, and disappears with the clone.
 *
 * **Why the filename carries the claim.** The decision predicate is
 * `exists(path)` plus its mtime. No hook parses the body, which is diagnostics.
 * That removes a class of parse-failure ambiguity from two enforcement paths,
 * and it is honest: anyone who can write the file can write valid JSON, so
 * parsing buys nothing.
 *
 * **What this is not.** Evidence plumbing, not an authority. Any process with
 * write access to the repository can create a marker by hand, and the hooks run
 * in the same trust domain as the agent they check. The authoritative controls
 * remain server-side branch protection and the gate output in CI.
 *
 * Subcommands:
 *
 *     node scripts/gate-marker.js preflight          # reject Git-visible nested worktrees
 *     node scripts/gate-marker.js run                # the gate's success path
 *     node scripts/gate-marker.js tree               # the tree oid of the current worktree
 *     node scripts/gate-marker.js path --tree <oid>  # where that tree's marker would live
 *     node scripts/gate-marker.js status             # {tree, marker, max_age_seconds}
 *
 * Node standard library only — no npm dependency, no transpiler, no TypeScript:
 * a gate that needs a dependency to run is a gate that can fail for reasons
 * unrelated to the tree. `scripts/package.json` pins this directory to CommonJS,
 * because Node resolves a `.js` file's module type from the nearest
 * `package.json` walking up, and in a consuming repo that walk otherwise
 * terminates at a root the harness does not control (#302's mechanism).
 */
// size: CLI dispatch and marker contract stay cohesive to avoid a shared hook dependency that could disable both enforcement hooks.
"use strict";

const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const crypto = require("node:crypto");
const { spawnSync } = require("node:child_process");

//: Bumped when the payload shape changes. The hooks do not read it — they do not
//: read the body at all — so this is for a human reading a marker, and for a
//: future writer that needs to tell two shapes apart.
const SCHEMA = 1;

//: Recorded in the payload so a marker names what produced it.
const WRITER = "gate-marker.js@0.1.0";

//: The freshness bound, in seconds. Its purpose is **toolchain drift under an
//: unchanged tree** — the venv is not in the tree, `uv.lock` is — not session
//: scope. A day is long enough that an ordinary attended session never re-runs
//: the gate for age alone, and short enough that a marker from last week does
//: not license a claim about a toolchain that has since moved.
const DEFAULT_MAX_AGE_SECONDS = 86400;
const MAX_AGE_ENV = "HARNESS_GATE_MARKER_MAX_AGE_SECONDS";

//: How many markers survive a prune. The directory is a cache, not a ledger:
//: ADR 0015 retired the run ledger and this change does not revive it.
const KEEP = 50;

//: Where the markers live, relative to the git common directory.
const MARKER_SUBDIR = ["harness", "gate"];

//: *A fact about the repository refused the operation* — git failed, there is no
//: repository, a nested worktree is visible, an ignore query was indeterminate.
//: `scripts/verify.sh` keys its diagnostic on this exact code, so a usage error
//: must not share it: conflating the two is how an operator gets told "a nested
//: worktree is visible" about a typo (#487 — a diagnostic is a measured claim).
const EXIT_REFUSED = 2;

//: `EX_USAGE` from `sysexits.h`. Anything else non-zero means the helper could
//: not run at all, and the wrapper in `verify.sh` treats it that way — so this
//: design does not depend on which code Node picks for an uncaught exception.
const EXIT_USAGE = 64;

//: A failure to *resolve* the gate this runner may launch is infrastructure,
//: neither a repository refusal nor a red verification stage.  Kept distinct so
//: callers can report the missing runner rather than a false claim about the
//: tree.  Deliberately **not** the code for a declared command the shell could
//: not launch: `sh -c` reports that as its own 127, and a consumer's gate can
//: legitimately exit 127 from an inner command, so mapping it here would
//: misclassify a genuinely red tree as infrastructure (#510).
const EXIT_RUNNER_UNAVAILABLE = 3;

//: Set on the declared gate's environment, and read back here.  `verify.sh`
//: reads it to take its internal path, which used to be the *only* recursion
//: guard: the sole launchable child was that one script.  The child is now an
//: arbitrary declared command, so the runner reads its own variable too.
const RUNNER_ENV = "HARNESS_GATE_MARKER_RUNNER";

/** A git invocation this program needs did not succeed.
 *
 * Raised rather than degraded to a default: a gate that cannot compute the tree
 * it verified must say so, not quietly record the wrong one. */
class GitError extends Error {}

/** Run `git <args>` in `cwd` and return its trimmed stdout.
 *
 * `spawnSync` with an argument vector, never `exec`/`execSync` and never a
 * template string: one operand of this program (a registered worktree path) is
 * chosen by whoever created the worktree, and a shell would read it. `argv[0]`
 * is the literal `git`, resolved off `PATH` exactly as every other caller in
 * this repo does. */
function git(args, cwd, env) {
  const res = spawnSync("git", args, {
    cwd: String(cwd),
    encoding: "utf8",
    env: env || process.env,
  });
  if (res.error) {
    throw new GitError(`git ${args.join(" ")} could not be run in ${cwd}: ${res.error.message}`);
  }
  if (res.status !== 0) {
    throw new GitError(
      `git ${args.join(" ")} failed in ${cwd} (exit ${res.status}): ` +
        String(res.stderr || "").trim()
    );
  }
  return String(res.stdout).trim();
}

/** Run a git predicate whose non-zero status can be an ordinary answer.
 *
 * `spawnSync` rather than `execFileSync` precisely for that: `check-ignore`
 * answers "not ignored" with exit 1, and `execFileSync` would throw on it. A
 * spawn failure and a signal death both surface as a null status, which the
 * caller must treat as indeterminate rather than as either answer. */
function gitStatus(args, cwd) {
  const res = spawnSync("git", args, { cwd: String(cwd), encoding: "utf8", env: process.env });
  if (res.error) return { status: null, stderr: res.error.message };
  return { status: res.status, stderr: String(res.stderr || "").trim() };
}

/** `p` with symlinks resolved, falling back to a plain resolve when it is absent.
 *
 * The fallback is what makes this the equivalent of Python's non-strict
 * `Path.resolve()`: a registered worktree whose directory has been deleted is
 * still a path this program has to reason about. */
function canonical(p) {
  try {
    return fs.realpathSync(p);
  } catch (err) {
    void err;
    return path.resolve(p);
  }
}

/** The git directory shared by every worktree of this repository.
 *
 * `--path-format=absolute` is the spelling `skills/worktree-isolation` already
 * uses; without it a linked worktree answers with a relative path whose meaning
 * depends on the caller's cwd. The `realpathSync`-with-fallback spelling is the
 * hooks' own, so all three implementations agree by construction rather than by
 * luck. */
function gitCommonDir(cwd) {
  const common = git(["rev-parse", "--path-format=absolute", "--git-common-dir"], cwd);
  let real = common;
  try {
    real = fs.realpathSync(common);
  } catch (err) {
    // Reported but unresolvable: use it verbatim rather than losing the answer.
    void err;
  }
  return real;
}

/** The directory holding this repository's gate markers. */
function markerDir(cwd) {
  return path.join(gitCommonDir(cwd), ...MARKER_SUBDIR);
}

/** Where the marker for `tree` lives. The filename is the whole claim. */
function markerPath(tree, cwd) {
  return path.join(markerDir(cwd), `${tree}.json`);
}

//: The counter, not just pid+ms: two calls inside one millisecond would
//: otherwise name the same scratch index. The random suffix is on top of it, so
//: the name is unpredictable as well as unique.
let scratchIndexSerial = 0;

/** The git tree object of `cwd`'s working tree, including uncommitted work.
 *
 * Computed against a **temporary index**, so the gate stages nothing as a side
 * effect. `git add -A` honours `.gitignore`, so `gate.log`, `.evidence/`,
 * `.harness/` and the venv are excluded exactly as they are excluded from any
 * commit — which is what keeps a marker from going stale the moment the gate
 * writes its own log.
 *
 * The temporary index lives in the marker directory rather than `TMPDIR`: the
 * git directory is guaranteed to exist wherever this can run at all, its write
 * access already implies total control of the repository, and the location
 * cannot affect the resulting oid. git must create the file itself — an empty
 * file is not a valid index — so nothing here pre-creates it, and it is removed
 * in a `finally`.
 *
 * Side effect worth naming: this writes blobs and trees into the object database
 * (loose, gc-able). `skills/build/SKILL.md` already does the same thing in the
 * *real* index when it computes `certified_tree`. */
function currentTree(cwd) {
  const dir = markerDir(cwd);
  fs.mkdirSync(dir, { recursive: true });
  scratchIndexSerial += 1;
  const suffix = crypto.randomBytes(6).toString("hex");
  const index = path.join(
    dir,
    `.index-${process.pid}-${Date.now()}-${scratchIndexSerial}-${suffix}`
  );
  const env = Object.assign({}, process.env, { GIT_INDEX_FILE: index });
  try {
    try {
      git(["read-tree", "HEAD"], cwd, env);
    } catch (err) {
      // No commits yet: start from an empty index rather than failing the gate
      // on a repository that simply has no history.
      void err;
      git(["read-tree", "--empty"], cwd, env);
    }
    git(["add", "-A"], cwd, env);
    return git(["write-tree"], cwd, env);
  } finally {
    try {
      fs.rmSync(index, { force: true });
    } catch (err) {
      // Best-effort cleanup of a scratch index. A leftover is *not* swept by the
      // prune below — that globs `*.json` and this is named `.index-…` — so
      // `tests/unit/test_gate_marker_js.py::test_the_scratch_index_is_removed`
      // is what keeps one from accumulating unnoticed.
      void err;
    }
  }
}

/** Refuse registered nested worktrees that Git can sweep into the root.
 *
 * Deliberately before anything that materialises a tree: the `git add -A` in
 * :func:`currentTree` is the operation that would absorb a visible nested
 * worktree, and `currentTree`'s first act is to create the marker directory, so
 * that directory's absence after a refusal is the observable that orders them.
 *
 * Only other registered worktrees strictly beneath this checkout are relevant;
 * siblings and parents cannot be descendants of its index. The descendant test
 * is `path.relative`, **never** `candidate.startsWith(root)`: a sibling worktree
 * at `<root>-other` shares the prefix and is not below it, and this repo's own
 * worktree naming (`harness`, `harness-work-500`) produces exactly that shape.
 *
 * Untrusted path data gets two defences, both inherited from the Python original
 * it replaces: the framing is `-z` porcelain and the split is on NUL, never on
 * lines (a worktree path may contain one); and the path reaches git after a
 * `--` separator, so a leading `-` cannot be read as an option. */
function preflight(cwd) {
  const root = canonical(git(["rev-parse", "--show-toplevel"], cwd));
  const listing = git(["worktree", "list", "--porcelain", "-z"], cwd);
  for (const field of listing.split("\0")) {
    if (!field.startsWith("worktree ")) continue;
    const candidate = canonical(field.slice("worktree ".length));
    const relative = path.relative(root, candidate);
    if (relative === "" || relative.startsWith("..") || path.isAbsolute(relative)) continue;
    if (!fs.existsSync(candidate)) continue;
    const ignored = gitStatus(["check-ignore", "--quiet", "--", candidate], root);
    if (ignored.status === 0) continue;
    if (ignored.status !== 1) {
      // Fail closed on what cannot be established: an infrastructure error is
      // not evidence that the descendant is safe.
      throw new GitError(
        `git check-ignore failed for registered nested worktree ${candidate} ` +
          `(exit ${ignored.status}): ${ignored.stderr}`
      );
    }
    throw new GitError(
      `registered nested worktree is visible to git: ${candidate}; ignore its ` +
        "parent (normally .worktrees/ or .claude/worktrees/) before running the gate"
    );
  }
}

/** The freshness bound `env` asks for, or the default.
 *
 * Three implementations parse this variable, so the degenerate cases need one
 * agreed answer. An unusable value reads as *unset*: reading it as "never fresh"
 * would wedge every session behind a gate run that can never satisfy it, and
 * reading it as "always fresh" would disarm the bound silently. Strict digits
 * only — the hooks' spelling, character for character. */
function maxAgeSeconds(env) {
  const raw = (env === undefined || env === null ? process.env : env)[MAX_AGE_ENV];
  if (!/^[0-9]+$/.test(String(raw))) return DEFAULT_MAX_AGE_SECONDS;
  const value = Number.parseInt(raw, 10);
  return value > 0 ? value : DEFAULT_MAX_AGE_SECONDS;
}

/** Drop markers past `maxAge`, then all but the `keep` newest.
 *
 * **A declared departure from the Python writer this replaces, not a port.**
 * That one documented itself as best-effort and was not: it sorted by
 * `p.stat().st_mtime`, so a marker unlinked by a concurrent gate run in another
 * worktree between the sort and the loop raised — and because the prune runs
 * *after* the marker is written, that race turned a green gate red with the
 * evidence already on disk. This repo runs many worktrees at once. Here every
 * `statSync` and every removal is wrapped, and a file that has vanished is
 * skipped rather than fatal. `now` is in seconds, to match the mtimes it is
 * compared against. */
function prune(directory, options) {
  const settings = options || {};
  const maxAge = settings.maxAge === undefined ? DEFAULT_MAX_AGE_SECONDS : settings.maxAge;
  const keep = settings.keep === undefined ? KEEP : settings.keep;
  const moment = settings.now === undefined ? Date.now() / 1000 : settings.now;
  let names;
  try {
    names = fs.readdirSync(directory);
  } catch (err) {
    // No directory means nothing to prune, which is not a failure of the write
    // that just succeeded.
    void err;
    return;
  }
  const markers = [];
  for (const name of names) {
    if (!name.endsWith(".json")) continue;
    const full = path.join(directory, name);
    try {
      markers.push({ full, mtime: fs.statSync(full).mtimeMs / 1000 });
    } catch (err) {
      // Vanished between the listing and the stat — the race above.
      void err;
    }
  }
  markers.sort((a, b) => b.mtime - a.mtime);
  markers.forEach((marker, index) => {
    if (moment - marker.mtime > maxAge || index >= keep) {
      try {
        fs.rmSync(marker.full, { force: true });
      } catch (err) {
        void err;
      }
    }
  });
}

/** `HEAD`'s commit, or the empty string in a repository with no commits. */
function headOf(cwd) {
  try {
    return git(["rev-parse", "HEAD"], cwd);
  } catch (err) {
    void err;
    return "";
  }
}

/** The checked-out branch, or the empty string when git cannot say. */
function branchOf(cwd) {
  try {
    return git(["rev-parse", "--abbrev-ref", "HEAD"], cwd);
  } catch (err) {
    void err;
    return "";
  }
}

/** Record a measured successful gate completion over `cwd`'s current tree.
 *
 * Called only on green. The body is diagnostics for a human; the *filename* is
 * the claim the hooks read. */
function emitSuccessfulMarker(cwd, measuredExit, gate) {
  if (measuredExit !== 0) {
    throw new Error("gate-marker: refusing to emit evidence for a non-zero gate result");
  }
  const tree = currentTree(cwd);
  const target = markerPath(tree, cwd);
  fs.mkdirSync(path.dirname(target), { recursive: true });
  const payload = {
    schema: SCHEMA,
    tree,
    head: headOf(cwd),
    branch: branchOf(cwd),
    worktree: canonical(git(["rev-parse", "--show-toplevel"], cwd)),
    gate,
    exit: measuredExit,
    finished_at: new Date().toISOString().replace(/\.\d{3}Z$/, "Z"),
    epoch: Math.floor(Date.now() / 1000),
    host: os.hostname(),
    writer: WRITER,
  };
  fs.writeFileSync(target, `${JSON.stringify(payload, null, 2)}\n`, "utf8");
  prune(path.dirname(target), { maxAge: maxAgeSeconds(), keep: KEEP });
  return target;
}

/** A trusted spine does not declare a usable ``commands.verify`` field. */
class GateDeclarationError extends Error {}

//: The shared configuration reader (#537). This helper carried the third of the
//: repo's three hand-rolled spine readers; the scalar layer it hardened at #510
//: — quoting recognised only at a value's first character, a ``#`` opening a
//: comment only after whitespace, yaml indicators refused rather than returned —
//: is now the one every caller gets.
//:
//: Required from ``__dirname`` and nothing else. This file is **materialized into
//: a consumer repo** by ``/harness:init``, which places the reader beside it, so
//: a sibling path is the checked-in one in both layouts.
//:
//: **There is deliberately no override for this path.** ADR 0018's boundary is
//: that no *per-invocation* source may decide the gate command: an operand, argv,
//: or an environment variable. A variable naming the directory the reader is
//: loaded from is such a source — a process that set it could supply a module
//: returning any command at all and mint a green marker for a gate that never
//: ran, without needing write access to the tree and without leaving a trace in
//: it. Rewriting the checked-in reader is the same local trust domain as
//: rewriting ``verify.sh``; setting a variable is not.
//:
//: Unlike the hooks, a failure here is **not** fail-open: the gate command is what
//: decides green, so a helper that cannot resolve it must refuse rather than guess.
function configReader() {
  try {
    return require(path.join(__dirname, "harness-config.js"));
  } catch (err) {
    throw new GateDeclarationError(
      `the shared configuration reader could not be loaded: ${err && err.message}`
    );
  }
}

/** Run ``read`` against the shared reader, restating its refusal as this
 * helper's own.
 *
 * ``GateDeclarationError`` is the marker helper's public contract — the CLI maps
 * it to the exit code reserved for a fact about the repository, and callers
 * catch it by class. The shared reader has no business knowing that, so it
 * raises its own and the translation happens here, once.
 */
function fromConfig(read) {
  const config = configReader();
  try {
    return read(config);
  } catch (err) {
    if (err instanceof config.ConfigDeclarationError) throw new GateDeclarationError(err.message);
    throw err;
  }
}

/** Return the one ``commands.verify`` scalar a spine declares. */
function declaredVerify(text, source) {
  return fromConfig((config) => config.declaredVerify(text, source));
}

/** Read the selected configuration source, then the fixed legacy gate. */
function gateCommand(cwd) {
  return fromConfig((config) => config.gateCommand(cwd));
}

/** Run the one trusted gate whose green result may produce a marker.
 *
 * The command is fixed by the checked-in spine rather than by an operand or
 * environment variable.  A fixed ``sh -c`` entry preserves commands such as
 * ``npm run verify`` while keeping per-invocation callers unable to mint
 * success for an arbitrary process.
 */
function runGate(cwd) {
  // A declared gate that reaches this verb again would re-run the whole gate at
  // every level and — worse — an inner level that exits zero writes a marker for
  // the tree while the outer stages are still running, minting evidence for a
  // tree its own gate then reports red. `verify.sh`'s check on the same variable
  // covered this only while the sole launchable child was `verify.sh`.
  if (process.env[RUNNER_ENV] === "1") {
    process.stderr.write(
      "gate-marker: the declared gate delegated back to `gate-marker.js run`; " +
        "refusing to re-enter the runner. Point commands.verify at the " +
        "verification stages themselves, never at this runner.\n"
    );
    return EXIT_RUNNER_UNAVAILABLE;
  }
  let gate;
  try {
    gate = gateCommand(cwd);
  } catch (err) {
    process.stderr.write(`gate-marker: ${err.message}\n`);
    return EXIT_RUNNER_UNAVAILABLE;
  }
  const legacyGate = path.join(cwd, "scripts", "verify.sh");
  if (gate.legacy && !fs.existsSync(legacyGate)) {
    process.stderr.write(`gate-marker: could not launch fixed gate: ${legacyGate} does not exist\n`);
    return EXIT_RUNNER_UNAVAILABLE;
  }
  const result = spawnSync("sh", ["-c", gate.command], {
    cwd: String(cwd),
    encoding: "utf8",
    env: Object.assign({}, process.env, { [RUNNER_ENV]: "1" }),
  });
  if (result.stdout) process.stdout.write(String(result.stdout));
  if (result.stderr) process.stderr.write(String(result.stderr));
  if (result.error || result.status === null) {
    const reason = result.error ? result.error.message : "terminated without an exit status";
    process.stderr.write(`gate-marker: could not launch declared gate: ${reason}\n`);
    return EXIT_RUNNER_UNAVAILABLE;
  }
  if (result.status !== 0) return result.status;

  const target = emitSuccessfulMarker(cwd, result.status, gate.command);
  process.stdout.write(`gate marker: ${path.basename(target, ".json")} -> ${target}\n`);
  return 0;
}

function usage(message) {
  process.stderr.write(
    `gate-marker: usage: ${message}\n` +
      "  gate-marker.js preflight | run | tree | path --tree <oid> | status\n"
  );
  return EXIT_USAGE;
}

/** The `--tree <oid>` operand, in either spelling argparse accepted. */
function treeArgument(argv) {
  if (argv[0] === "--tree" && argv[1] !== undefined) return argv[1];
  if (argv[0] !== undefined && argv[0].startsWith("--tree=")) {
    return argv[0].slice("--tree=".length);
  }
  return null;
}

function main(argv) {
  const cwd = process.cwd();
  const command = argv[0];
  if (command === undefined) return usage("a subcommand is required");
  try {
    if (command === "preflight") {
      preflight(cwd);
    } else if (command === "run") {
      if (argv.length !== 1) return usage("run accepts no operands");
      return runGate(cwd);
    } else if (command === "write") {
      return usage("write is retired; run the canonical verification gate instead");
    } else if (command === "tree") {
      process.stdout.write(`${currentTree(cwd)}\n`);
    } else if (command === "path") {
      const tree = treeArgument(argv.slice(1));
      if (tree === null || tree === "") return usage("path requires --tree <oid>");
      process.stdout.write(`${markerPath(tree, cwd)}\n`);
    } else if (command === "status") {
      // Three facts and no verdict. `scripts/mutate.py`'s gate lock composes
      // them into its own three refusal messages, which is where the
      // absent/stale distinction already lives — and reading the bound from here
      // is what keeps the freshness variable from growing a fourth parser.
      const tree = currentTree(cwd);
      process.stdout.write(
        `${JSON.stringify({
          tree,
          marker: markerPath(tree, cwd),
          max_age_seconds: maxAgeSeconds(),
        })}\n`
      );
    } else {
      return usage(`unknown subcommand: ${command}`);
    }
  } catch (err) {
    if (err instanceof GitError) {
      process.stderr.write(`gate-marker: ${err.message}\n`);
      return EXIT_REFUSED;
    }
    throw err;
  }
  return 0;
}

if (require.main === module) {
  process.exitCode = main(process.argv.slice(2));
}

// Exported so `tests/unit/test_gate_marker_contract.py` can execute this copy of
// the contract beside the two hook copies, and so the behavioural tests can
// reach `prune` and the constants directly. The `require.main === module` guard
// above means importing for that introspection never runs the CLI. The three
// implementations are held equivalent by execution and textually independent by
// assertion; a shared module would turn that equivalence into `assert x == x`.
module.exports = {
  declaredVerify,
  GateDeclarationError,
  markerPath,
  markerDir,
  maxAgeSeconds,
  currentTree,
  preflight,
  prune,
  main,
  GitError,
  SCHEMA,
  WRITER,
  KEEP,
  MAX_AGE_ENV,
  DEFAULT_MAX_AGE_SECONDS,
  MARKER_SUBDIR,
  EXIT_RUNNER_UNAVAILABLE,
};
