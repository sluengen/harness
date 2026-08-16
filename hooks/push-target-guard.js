#!/usr/bin/env node
// guidance:hook-push-target-guard@0.1.0
/**
 * Push-target guard (PreToolUse: Bash) — #436.
 *
 * The sibling ``git-push-guard.js`` refuses a push that *rewrites* history. This
 * one refuses a push that *lands unverified work*: a ``git push`` whose **target**
 * is a protected branch is denied unless a gate marker covers the tree of the
 * commit being pushed.
 *
 * **The marker is the authorisation.** ``scripts/verify.sh`` writes
 * ``<git-common-dir>/harness/gate/<tree-oid>.json`` on green, named after the git
 * tree object it verified. ``commands/build.md`` already refuses to integrate
 * unless ``git rev-parse HEAD^{tree}`` equals the tree its gate ran over, so the
 * tree the gate covered and the tree a push carries are the same object by the
 * process's own rule. This hook checks that equality mechanically.
 *
 * **No command-based exemption, and none is needed.** ``/ship``, ``/routine`` and
 * ``/promote`` all push a tree the gate has already covered, so they authorise
 * themselves by the only evidence a hook can actually verify. A hook cannot see
 * which slash command is driving the session, and building enforcement on a
 * claim it cannot check would be theatre.
 *
 * **One shell parser, not two.** The lexer, wrapper resolution and substitution
 * detection are imported from ``git-push-guard.js``. A second naive parser would
 * be walked past by ``sh -c "git push origin HEAD:dev"`` — a push the force guard
 * catches and this one would not. The require is **lazy, inside main()**: a
 * top-level sibling require sits outside the try that owns the fail-open path, so
 * an ESM-root load failure would turn "approve loudly" into "crash before writing
 * stdout" (the contract #303 forbids).
 *
 * **Fail open or fail closed, split three ways.**
 *   1. The hook could not run (crash, unparseable stdin, failed require) — it has
 *      no opinion: pass through, loudly, on stderr.
 *   2. The hook ran but could not establish the facts (git unavailable, an
 *      unresolvable source, an ambiguous push directory, a shell expansion in a
 *      decision slot) — **deny**. Cheap-to-clear guards fail closed: one gate run
 *      clears a false deny, while a false allow is the irreversible act.
 *   3. The hook ran, established the facts, and found no evidence — **deny**. Not
 *      a fall-open at all; it is the decision the hook exists to make.
 *
 * **Deny, not ask.** Whether a hook ``ask`` overrides an existing
 * ``permissions.allow`` entry is not documented clearly enough to bet enforcement
 * on, and the settings file carries ``Bash(git push origin dev)``. Deny-over-allow
 * precedence is what the force-push guard already relies on in production, and an
 * enforcement decision must be deterministic in an unattended run.
 *
 * **Honest limit.** This is evidence plumbing, not an authority. It reads a file
 * any process with write access to the repository can create, and it runs in the
 * same trust domain as the agent it checks. The authoritative control is
 * server-side branch protection, which no client-side hook can be argued past.
 * What this buys is that the default path now requires the gate to have run over
 * the exact bytes being pushed, and that manufacturing the evidence is a
 * discrete, deliberate, transcript-visible act rather than a silent omission.
 * Note the residual: state 1 above disarms this guard entirely, and unlike the
 * force-push guard it has no ``permissions.deny`` glob behind it — nothing in
 * that block covers a push to ``dev`` by target.
 */
"use strict";

const fs = require("fs");
const path = require("path");
const { spawnSync } = require("child_process");

const TAG = "[PUSH-TARGET-GUARD]";

//: The freshness bound, mirrored from ``scripts/gate_marker.py``. Its purpose is
//: toolchain drift under an unchanged tree, not session scope. The equivalence
//: with the Python parser is measured by ``test_gate_marker_contract.py``.
const MAX_AGE_ENV = "HARNESS_GATE_MARKER_MAX_AGE_SECONDS";
const DEFAULT_MAX_AGE_SECONDS = 86400;

//: Where markers live under the git common directory.
const MARKER_SUBDIR = ["harness", "gate"];

//: Used when a repo declares no branches. Deliberately over-broad: a false deny
//: is recoverable in one command (run the gate), a false allow lands unverified
//: work on the integration branch of a repo that told the guidance nothing about
//: itself. Extends the vocabulary ``workflow-guard.js`` already hardcodes.
const FALLBACK_PROTECTED = [
  "main",
  "master",
  "dev",
  "develop",
  "trunk",
  "staging",
  "release",
  "production",
];

//: ``git push`` options that consume the following token, so an option argument
//: is never mistaken for the remote or a refspec.
const PUSH_OPTS_WITH_ARG = new Set(["-o", "--push-option", "--receive-pack", "--exec", "--repo"]);

//: Recursion bound, matching the sibling guard's pathological-nesting backstop.
const MAX_DEPTH = 16;

/**
 * Fail open, loudly. See the identical helper in the other hooks (#303): the
 * approving payload still goes out, but stderr says this hook did not run, so a
 * silently-disarmed guard is distinguishable from a deliberate pass-through. Built
 * from hook-owned constants and `err.message` only — never the payload, which carries
 * the very Bash command under inspection. Inlined per hook on purpose: a shared module
 * would be a load-time dependency whose own failure is the class being reported on.
 */
function failOpen(reason, err) {
  const cause = err && err.message ? String(err.message) : String(err || "no detail");
  process.stderr.write(`${TAG} fail-open: ${reason}: ${cause.replace(/\s+/g, " ").slice(0, 200)}\n`);
}

function readStdin() {
  try {
    return JSON.parse(fs.readFileSync(0, "utf8"));
  } catch (err) {
    failOpen("could not parse the hook payload on stdin", err);
    return {};
  }
}

/** Run git in ``dir`` and return its trimmed stdout, or null.
 *
 * Null means *git said no* — a ref that does not resolve, a directory that is
 * not a checkout, a git that could not be spawned at all. Every one of those is
 * a decision input for this guard (state 2 above closes), not an internal error,
 * so they collapse to one value deliberately rather than by accident. */
function git(dir, args) {
  try {
    const res = spawnSync("git", args, { cwd: dir, encoding: "utf8" });
    if (res.error || res.status !== 0) return null;
    return String(res.stdout).trim();
  } catch (err) {
    // A probe that cannot run is an input to the deny decision, not a crash:
    // this guard fails closed on facts it could not establish.
    void err;
    return null;
  }
}

/** The freshness bound, or the default. An unusable value reads as *unset*:
 * "never fresh" would wedge every push behind a gate run that can never satisfy
 * it, and "always fresh" would disarm the bound. Strict digits only, so this
 * agrees with Python's ``int()`` on the degenerate spellings. */
function maxAgeSeconds() {
  const raw = process.env[MAX_AGE_ENV];
  if (!/^[0-9]+$/.test(String(raw))) return DEFAULT_MAX_AGE_SECONDS;
  const value = Number.parseInt(raw, 10);
  return value > 0 ? value : DEFAULT_MAX_AGE_SECONDS;
}

/** Where ``tree``'s marker lives, or null outside a repository.
 *
 * The **common** directory, so a gate run in a detached gate worktree writes a
 * marker the build worktree can read — two worktrees at the same tree oid have
 * byte-identical content, so that visibility is correct, not merely convenient. */
function markerPath(tree, cwd) {
  const common = git(cwd, ["rev-parse", "--path-format=absolute", "--git-common-dir"]);
  if (common === null) return null;
  let real = common;
  try {
    real = fs.realpathSync(common);
  } catch (err) {
    // The common dir was reported but cannot be resolved; use it verbatim
    // rather than losing the answer. Deliberately not reported: a path that
    // does not resolve simply yields no marker, which the caller handles.
    void err;
  }
  return path.join(real, ...MARKER_SUBDIR, `${tree}.json`);
}

/** True iff a marker for ``tree`` exists in ``dir``'s repository and is fresh. */
function hasFreshMarker(tree, dir) {
  const marker = markerPath(tree, dir);
  if (marker === null) return false;
  try {
    return Date.now() - fs.statSync(marker).mtimeMs < maxAgeSeconds() * 1000;
  } catch (err) {
    // A missing marker is the decision this guard exists to make, not an error.
    void err;
    return false;
  }
}

/** Strip a matching pair of surrounding quotes. Written without quote
 * characters inside a regex on purpose — the repo's hook source scanners blank
 * string literals to count braces, and a lone quote inside a pattern throws
 * their offsets off. */
function stripQuotes(value) {
  const quotes = "\"'";
  if (value.length >= 2 && quotes.includes(value[0]) && value[0] === value[value.length - 1]) {
    return value.slice(1, -1);
  }
  return value;
}

/** A yaml scalar with its inline comment and quotes removed. */
function scalar(raw) {
  const hash = raw.indexOf("#");
  return stripQuotes((hash === -1 ? raw : raw.slice(0, hash)).trim());
}

/** The branch names declared under ``branches:`` in a repo's CONTEXT.md.
 *
 * A small line parser, the same shape ``guidance-freshness.js`` already uses for
 * ``registry.yaml``: the file is markdown with a fenced yaml block, so a real
 * yaml load would need a dependency this surface does not have. Every value
 * under the block counts — ``integration``, ``staging``, ``release`` and any key
 * a repo invents — because the question is which branches the repo treats as
 * shared, not which role it assigned them. */
function declaredBranches(contextFile) {
  let text;
  try {
    text = fs.readFileSync(contextFile, "utf8");
  } catch (err) {
    // No CONTEXT.md is the ordinary case in a repo that has not adopted the
    // guidance; the conservative fallback set applies and that is not an error.
    void err;
    return [];
  }
  const found = [];
  let indent = -1;
  for (const raw of text.split("\n")) {
    const line = raw.replace(/\t/g, "  ");
    const lead = line.length - line.trimStart().length;
    if (indent === -1) {
      if (/^branches:\s*$/.test(line.trim())) indent = lead;
      continue;
    }
    if (!line.trim()) continue;
    if (lead <= indent) break; // the block ended
    const match = /^\s*([A-Za-z_][A-Za-z0-9_-]*)\s*:\s*(.*)$/.exec(line);
    if (!match) continue;
    const value = scalar(match[2]);
    if (value) found.push(value);
  }
  return found;
}

/** A ref name reduced to its branch name: ``refs/heads/dev`` becomes ``dev``. */
function branchName(ref) {
  return ref.replace(/^refs\/heads\//, "").replace(/^refs\/remotes\/[^/]+\//, "");
}

/** The set of branches a push must carry evidence to reach, resolved in ``dir``. */
function protectedBranches(dir) {
  const top = git(dir, ["rev-parse", "--show-toplevel"]);
  const declared = top === null ? [] : declaredBranches(path.join(top, "CONTEXT.md"));
  const names = declared.length ? declared : FALLBACK_PROTECTED;
  const set = new Set(names.map(branchName));
  const remoteHead = git(dir, ["symbolic-ref", "refs/remotes/origin/HEAD"]);
  if (remoteHead) set.add(branchName(remoteHead));
  return set;
}

/** Parse one command's tokens as a ``git push``, or return null.
 *
 * Returns ``{ dir, refspecs, isDelete, mirrors, movesAllRefs, tagsOnly }`` where ``dir``
 * is a ``git -C`` operand if one was given. A command substitution in the
 * sub-command slot is left to ``git-push-guard.js``, which already fails closed
 * on it — a second deny here would only re-deny a command already refused. */
function parsePush(rawTokens, parser) {
  const tokens = parser.resolveCommand(rawTokens);
  if (tokens.length === 0 || !parser.isGit(tokens[0])) return null;

  let i = 1;
  let dir = null;
  while (i < tokens.length) {
    const token = tokens[i];
    if (parser.GIT_GLOBAL_WITH_ARG.has(token)) {
      if (token === "-C") dir = tokens[i + 1];
      i += 2;
      continue;
    }
    if (token.startsWith("-")) {
      i += 1;
      continue;
    }
    break;
  }
  if (i >= tokens.length || tokens[i] !== "push") return null;

  const operands = [];
  let isDelete = false;
  let mirrors = false;
  let movesAllRefs = false;
  let tagsOnly = false;
  let sawDoubleDash = false;
  for (let j = i + 1; j < tokens.length; j++) {
    const token = tokens[j];
    if (!sawDoubleDash && token === "--") {
      sawDoubleDash = true;
      continue;
    }
    if (!sawDoubleDash && token.length > 1 && token.startsWith("-")) {
      if (PUSH_OPTS_WITH_ARG.has(token)) j += 1;
      if (token === "--delete" || /^-[A-Za-z]*d[A-Za-z]*$/.test(token)) isDelete = true;
      if (token === "--mirror") mirrors = true;
      if (token === "--mirror" || token === "--all") movesAllRefs = true;
      if (token === "--tags") tagsOnly = true;
      continue;
    }
    operands.push(token);
  }
  // git push [<repository> [<refspec>...]] — the first operand is always the
  // repository, so a refspec can never claim that slot.
  return { dir, refspecs: operands.slice(1), isDelete, mirrors, movesAllRefs, tagsOnly };
}

/** The directory a push actually runs in, given its ``git -C`` operand (or
 * null) and the directory the command has cd'd to (or null when that is itself
 * unknowable).
 *
 * ``git -C`` is **relative to the process's working directory**, so a relative
 * operand composes with the ``cd`` rather than replacing it. Resolving one
 * against the hook's own cwd instead is the same defect as ignoring the ``cd``,
 * one operand further along, and it fails in the dangerous direction: the hook's
 * cwd is usually the repo root, which usually *has* a marker, so a push from an
 * unverified worktree would be authorised by a tree nobody is pushing. A
 * relative operand with no known base stays null, which the caller denies. */
function resolveDir(operand, cwd) {
  if (operand === null) return cwd;
  if (path.isAbsolute(operand)) return operand;
  return cwd === null ? null : path.resolve(cwd, operand);
}

/** True iff ``token`` carries a shell expansion, so its value is not knowable
 * before the command runs.
 *
 * Command substitution and parameter expansion are the same problem in a
 * decision slot: ``git push origin HEAD:$T`` reads statically as a push to a
 * branch called ``$T``, which no protected set contains, while the shell hands
 * git whatever ``T`` holds. The sibling guard's helper covers ``$(…)`` and
 * backticks because those are what a *force* flag can hide behind; a target has
 * the wider exposure, so a bare ``$`` counts here too. */
function isUnreadable(token, parser) {
  return parser.hasCommandSubstitution(token) || token.includes("$");
}

/** Every ``git push`` reachable from ``command``, each with the directory it
 * would run in.
 *
 * The directory matters concretely: ``/build`` ships with
 * ``cd "$worktree_path" && git push origin HEAD:dev``, and resolving ``HEAD`` at
 * the session cwd reads the wrong branch — and could find a marker for a tree
 * nobody is pushing. So a ``cd`` preceding a push in the same lexed sequence
 * moves the directory, and a ``cd`` target carrying a command substitution makes
 * it unknowable (``dir: null``, which the caller denies). */
function pushesIn(command, startDir, parser, depth) {
  if (depth > MAX_DEPTH) return [];
  const found = [];
  const { commands, substitutions } = parser.lex(command);
  let dir = startDir;
  for (const { tokens } of commands) {
    const resolved = parser.resolveCommand(tokens);
    if (resolved.length && parser.basename(resolved[0]) === "cd") {
      const target = resolved.slice(1).find((t) => !t.startsWith("-"));
      if (target === undefined || parser.hasCommandSubstitution(target)) dir = null;
      else if (dir !== null) dir = path.resolve(dir, target);
      continue;
    }
    const push = parsePush(tokens, parser);
    if (push) found.push({ ...push, dir: resolveDir(push.dir, dir) });
    for (const script of parser.nestedScripts(tokens)) {
      found.push(...pushesIn(script, dir, parser, depth + 1));
    }
  }
  for (const body of substitutions) {
    found.push(...pushesIn(body, startDir, parser, depth + 1));
  }
  return found;
}

/** The ``{ source, target, isDelete }`` triples one push would move, or null
 * when a refspec carries a command substitution and cannot be read statically. */
function movements(push, dir, parser) {
  if (push.refspecs.length === 0) {
    if (push.tagsOnly) return []; // a tag is not a branch
    // ``--symbolic-full-name`` and not ``--abbrev-ref``: the abbreviated form of
    // an upstream is ``origin/dev``, which ``branchName`` cannot reduce (and must
    // not, or ``feature/x`` would reduce to ``x``). The full ref
    // ``refs/remotes/origin/dev`` it can, so a bare ``git push`` resolves to the
    // branch it will actually move rather than to a name no protected set holds.
    const upstream = git(dir, ["rev-parse", "--symbolic-full-name", "@{upstream}"]);
    const current = git(dir, ["rev-parse", "--abbrev-ref", "HEAD"]);
    const target = upstream !== null ? branchName(upstream) : current;
    if (target === null) return null;
    return [{ source: "HEAD", target, isDelete: push.isDelete }];
  }
  const moves = [];
  for (const raw of push.refspecs) {
    if (isUnreadable(raw, parser)) return null;
    const spec = raw.startsWith("+") ? raw.slice(1) : raw;
    const colon = spec.indexOf(":");
    if (colon === -1) {
      moves.push({ source: spec, target: branchName(spec), isDelete: push.isDelete });
      continue;
    }
    const source = spec.slice(0, colon);
    const target = spec.slice(colon + 1);
    // A ``:<name>`` refspec deletes ``<name>``, and so does ``<name>:`` (an
    // empty destination), so both arms report a delete rather than a move.
    moves.push({
      source,
      target: branchName(target || source),
      isDelete: push.isDelete || source === "" || target === "",
    });
  }
  return moves;
}

function deny(reason) {
  process.stdout.write(
    JSON.stringify({
      hookSpecificOutput: {
        hookEventName: "PreToolUse",
        permissionDecision: "deny",
        permissionDecisionReason: `${TAG} ${reason}`,
      },
    })
  );
}

/** Defer to the normal permission flow — do NOT pre-approve. */
function passThrough() {
  process.stdout.write(JSON.stringify({ continue: true }));
}

/** The refusal for a push this guard decided against, or null to allow it. */
function verdict(push, parser) {
  const dir = push.dir;
  if (dir === null) {
    return (
      "Blocked a push whose working directory cannot be resolved statically (a cd " +
      "target carrying a command substitution). The tree this push would carry is " +
      "unknowable, so there is nothing to verify. Run the push from a literal " +
      "directory, or with an explicit git -C <path>."
    );
  }
  if (git(dir, ["rev-parse", "--is-inside-work-tree"]) !== "true") return null;

  const guarded = protectedBranches(dir);
  const moves = movements(push, dir, parser);
  if (moves === null) {
    return (
      "Blocked a push whose refspec carries a shell expansion, or whose target " +
      "cannot be resolved. The branch it moves cannot be established before the " +
      "push runs, so there is nothing to check evidence against. Spell the " +
      "refspec literally."
    );
  }
  if (push.mirrors) {
    // Unconditional, and deliberately not conditioned on a protected branch
    // existing here. --mirror makes the remote match the local ref set, so a
    // protected branch this repo does **not** have is one --mirror deletes:
    // "no protected branch locally" is the most dangerous case, not the safe one.
    return (
      "Blocked a --mirror push. It makes the remote match this repository's refs " +
      "exactly, so it moves protected branches with no refspec naming them and " +
      "deletes any it does not hold locally. No gate evidence authorises that. " +
      "Push an explicit refspec."
    );
  }
  if (push.movesAllRefs) {
    // --all moves the local branches and nothing else, so a repo holding none of
    // the protected names has no protected target and a deny would be false.
    const anyProtected = [...guarded].some((name) => git(dir, ["rev-parse", "--verify", name]));
    if (anyProtected) {
      return (
        "Blocked a --all push. It moves every local branch, including protected " +
        "ones, with no refspec naming them — so there is no target to verify " +
        "and no tree to check. Push an explicit refspec."
      );
    }
  }
  for (const move of moves) {
    if (!guarded.has(move.target)) continue;
    if (move.isDelete) {
      return (
        `Blocked a delete of the protected branch ${JSON.stringify(move.target)}. ` +
        "No gate evidence authorises deleting a shared branch; a human must run it."
      );
    }
    const tree = git(dir, ["rev-parse", "--verify", `${move.source}^{tree}`]);
    if (tree === null) {
      return (
        `Blocked a push to the protected branch ${JSON.stringify(move.target)}: the ` +
        `source ${JSON.stringify(move.source)} does not resolve to a tree in ${dir}, ` +
        "so there is nothing to check evidence against."
      );
    }
    if (!hasFreshMarker(tree, dir)) {
      return (
        `Blocked a push to the protected branch ${JSON.stringify(move.target)}. No ` +
        `gate marker covers tree ${tree.slice(0, 12)} — the gate has not been run ` +
        `green over the exact bytes this push carries (looked for ` +
        `${markerPath(tree, dir)}). Run the repo verify gate in ${dir}, then push ` +
        "again. The gated tree is the authorisation; there is no exemption for a " +
        "particular command."
      );
    }
  }
  return null;
}

function main() {
  const input = readStdin();
  if ((input.tool_name || "") !== "Bash") return passThrough();
  const command = (input.tool_input && input.tool_input.command) || "";
  if (!command) return passThrough();

  // Lazy, inside main()'s try: a top-level sibling require sits outside the
  // fail-open path, turning an ESM-root load failure into a crash before stdout.
  const parser = require("./git-push-guard.js");

  const cwd = input.cwd || process.cwd();
  for (const push of pushesIn(command, cwd, parser, 0)) {
    const reason = verdict(push, parser);
    if (reason) return deny(reason);
  }
  passThrough();
}

if (require.main === module) {
  try {
    main();
  } catch (err) {
    // State 1: the hook could not run, so it has no opinion. Pass through, but
    // loudly — a disarmed enforcement hook must not look like a clean pass.
    failOpen("crashed before it could decide", err);
    process.stdout.write(JSON.stringify({ continue: true }));
  }
}

// Exported so ``test_gate_marker_contract.py`` can execute this hook's copy of
// the contract against the Python writer's. The path is computed in three
// languages and the freshness bound parsed in three, which is exactly the shape
// that drifts silently; an equivalence test that runs all three is what catches
// it. The ``require.main === module`` guard above means importing for that
// introspection never runs the hook.
module.exports = { markerPath, maxAgeSeconds, FALLBACK_PROTECTED };
