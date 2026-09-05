#!/usr/bin/env node
/**
 * Test-lock guard (PreToolUse: Write|Edit, and Codex's apply_patch).
 *
 * Holds spine law 7 — *do not edit a test while implementing against it; the
 * fix lane may add one, never change one* — for the window a build declares by
 * writing `tests_locked: true` into `.harness/run.json`. Law 7 shipped at #537
 * as a sentence; instruction alone is measured not to hold it (over 79% of
 * observed agent cheating is editing the test directly), so P1's lowest-rung
 * rule buys a refusal here (D3).
 *
 * **Scope, stated rather than implied.** This matcher sees `Write`, `Edit` and
 * `apply_patch`. A test rewritten through `Bash` — `sed -i`, a heredoc, `git
 * checkout -- tests/` — is not seen, and extending to `Bash` would mean parsing
 * arbitrary shell, which `push-target-guard.js` measures at ~800 lines that
 * still refuse on ambiguity. The hook raises the cost of the cheapest and most
 * common cheat; the controls of record are the reviewer's explicit item per
 * test-file diff, the gate, and branch protection.
 *
 * **The refusal is a speed bump with a recorded escape, by design.** Releasing
 * the lock is one edit to a gitignored file — and that edit is exactly what
 * makes the bypass deliberate and reviewable instead of silent.
 *
 * **It never reads `stage`.** The run's stage vocabulary grows (T3 adds landing
 * stages); what this hook denies must not move when it does.
 */
"use strict";

const fs = require("fs");
const path = require("path");
const { execFileSync } = require("child_process");

const TAG = "[TEST-LOCK-GUARD]";

//: The lanes, spelled as `run.json` carries them. The permissive branch belongs
//: to `fix` alone, so anything not in this map takes the strict one: the fix
//: lane's allowance is a *named* exception, and an exception has to be named to
//: apply. A typo, a truncated write, or a lane invented later therefore locks.
const LANES = { fix: "fix", change: "change", feature: "feature" };

//: The one `run.json` shape this hook understands. A file claiming any other
//: version is treated as unreadable rather than guessed at.
const SUPPORTED_VERSION = 1;

let codexRuntime = false;

function readStdin() {
  try {
    const input = JSON.parse(fs.readFileSync(0, "utf8"));
    codexRuntime = Object.prototype.hasOwnProperty.call(input, "turn_id");
    return input;
  } catch (err) {
    failOpen("could not read its stdin payload", err);
    return null;
  }
}

/** The shared configuration reader, or null when it cannot be loaded.
 *
 * A load failure is not a decision input — in a correctly installed plugin it
 * cannot happen and there is no answer to act on — so it reports (#302). The
 * degradation is an inactive lock, which is the state of every repo that has
 * not adopted the run file, never a wider refusal.
 */
function loadConfig() {
  try {
    return require("../scripts/harness-config.js");
  } catch (err) {
    failOpen("could not load the shared configuration reader", err);
    return null;
  }
}

function git(dir, args) {
  try {
    return execFileSync("git", args, { cwd: dir, stdio: ["ignore", "pipe", "ignore"] })
      .toString()
      .trim();
  } catch {
    // A probe that cannot run is a decision input here — an edit outside any
    // repository is a legitimate allow, not a failure of this hook.
    return "";
  }
}

/** Every path this call would write, from either host's payload shape. */
function editedPaths(input) {
  const tool = input.tool_name || "";
  const ti = input.tool_input || {};
  if (tool === "Write" || tool === "Edit") return ti.file_path ? [ti.file_path] : [];
  if (tool !== "apply_patch" || typeof ti.command !== "string") return [];
  // The header enumerates the paths; git, never the header, decides whether
  // each one already exists.
  return Array.from(
    ti.command.matchAll(/^\*\*\* (?:Add|Update|Delete) File: (.+)$/gm),
    (match) => match[1]
  );
}

/** ``dir`` itself, or its nearest ancestor that exists.
 *
 * A `Write` creates the file **and its directory**, so the edited path's parent
 * is routinely a directory that is not there yet — and a `git` probe run in a
 * directory that does not exist fails, which would resolve no repository and
 * disarm the lock. Found by mutation: three lookalike controls passed against a
 * deliberately broken predicate because the hook never reached it.
 */
function existingAncestor(dir) {
  let current = path.resolve(dir);
  for (;;) {
    try {
      if (fs.statSync(current).isDirectory()) return current;
    } catch {
      // Not there — the loop below walks up. A decision input, not a failure.
    }
    const parent = path.dirname(current);
    if (parent === current) return current;
    current = parent;
  }
}

/** The run state at ``top``: an object, ``null`` for absent, ``false`` for unreadable. */
function runState(top) {
  const file = path.join(top, ".harness", "run.json");
  let raw;
  try {
    raw = fs.readFileSync(file, "utf8");
  } catch {
    // Absent is the common case — every session that is not a build — and is a
    // decision input, so it stays silent.
    return null;
  }
  try {
    const state = JSON.parse(raw);
    if (!state || typeof state !== "object" || Array.isArray(state)) return false;
    if (state.version !== SUPPORTED_VERSION) return false;
    return state;
  } catch {
    return false;
  }
}

/** ``paths.tests`` as a posix prefix ending in one slash, or null. */
function testRoot(config, top) {
  if (!config) return null;
  const declared = config.declaredPaths(top);
  const raw = declared && declared.tests;
  if (typeof raw !== "string" || !raw.trim()) return null;
  const normalised = raw.trim().replace(/\\/g, "/").replace(/^\.\//, "").replace(/\/+$/, "");
  return normalised ? normalised + "/" : null;
}

/** The repo-relative posix path of ``file``, or null when it is outside ``top``. */
function relativeTo(top, dir, file) {
  const abs = path.resolve(dir, file);
  const rel = path.relative(top, abs).split(path.sep).join("/");
  if (!rel || rel === ".." || rel.startsWith("../") || path.isAbsolute(rel)) return null;
  return rel;
}

function underRoot(rel, root) {
  return rel === root.slice(0, -1) || rel.startsWith(root);
}

/** Does ``rel`` exist in the tree the run branched from? */
function inBaseTree(dir, base, rel) {
  try {
    execFileSync("git", ["cat-file", "-e", `${base}^{tree}:${rel}`], {
      cwd: dir,
      stdio: ["ignore", "ignore", "ignore"],
    });
    return true;
  } catch {
    return false;
  }
}

//: One repo-relative path, constrained to characters a path may carry and cut
//: short. `run.json` is model-writable text and the reason is injected back
//: into a model's context, so the only untrusted bytes that reach it are a path
//: this hook itself derived from git (law 6).
function safePath(rel) {
  return rel.replace(/[^A-Za-z0-9._/-]/g, "?").slice(0, 120);
}

function refusal(rel) {
  return (
    `Refused an edit to a test file while this run's tests are locked: ${safePath(rel)}. ` +
    "Law 7 — do not edit a test while implementing against it. Over 79% of measured " +
    "cheating is editing the test directly, and instruction alone does not stop it, " +
    "which is why a hook holds this rather than a sentence. Legitimate escape: if the " +
    "test itself is wrong, stop and return the run to its tests stage — set " +
    '"stage": "tests" and "tests_locked": false in .harness/run.json, record on the ' +
    "ticket what changed and why, and expect the reviewer to require an explicit " +
    "justification for the test diff. In the fix lane a NEW test file is allowed; one " +
    "already in the run's base commit is not."
  );
}

/** The path this call must be refused for, or null to allow it. */
function verdict(input) {
  const tool = input.tool_name || "";
  if (tool !== "Write" && tool !== "Edit" && tool !== "apply_patch") return null;

  const files = editedPaths(input);
  if (!files.length) return null;

  const first = files[0];
  const dir = existingAncestor(
    path.isAbsolute(first)
      ? path.dirname(first)
      : (typeof input.cwd === "string" && input.cwd) || process.cwd()
  );

  // The repository is resolved from the *edited file's* directory, not from
  // this process's, so a locked run in one worktree never reaches another
  // worktree of the same repo — concurrency is the norm here (law 5).
  const top = git(dir, ["rev-parse", "--show-toplevel"]);
  if (!top) return null;

  const state = runState(top);
  if (state === null) return null;
  if (state === false) {
    failOpen("could not read the run state, so the test lock is inactive", "malformed run.json");
    return null;
  }
  if (state.tests_locked !== true) return null;

  const root = testRoot(loadConfig(), top);
  if (!root) return null;

  const lane = LANES[state.lane];
  const base = typeof state.base_commit === "string" ? state.base_commit : "";

  for (const file of files) {
    const rel = relativeTo(top, dir, file);
    if (rel === null || !underRoot(rel, root)) continue;
    if (lane !== "fix") return rel;
    // The fix lane may add a test. "New" is absence from the tree the run
    // branched from — not from the filesystem, which would deny the author's
    // own second edit to a file it just created, and not from the index, which
    // flips the moment the run stages for review.
    if (!base || inBaseTree(top, base, rel)) return rel;
  }
  return null;
}

function main() {
  const input = readStdin();
  if (input === null) return done(null);
  const rel = verdict(input);
  return done(rel);
}

function done(rel) {
  if (rel !== null) {
    process.stdout.write(
      JSON.stringify({
        hookSpecificOutput: {
          hookEventName: "PreToolUse",
          permissionDecision: "deny",
          permissionDecisionReason: `${TAG} ${refusal(rel)}`,
        },
      })
    );
    return;
  }
  // Defer to the normal permission flow — do NOT pre-approve.
  if (codexRuntime) return;
  process.stdout.write(JSON.stringify({ continue: true }));
}

/**
 * Fail open, loudly. See the identical helper in every other hook (#303): the
 * approving payload still goes out, but stderr says this hook did not run, so a
 * disarmed hook is distinguishable from a clean pass-through. Built from hook-owned
 * constants and `err.message` only — never the payload, which is untrusted text.
 * Inlined per hook: a shared module would be a load-time dependency whose own failure
 * is the class being reported on.
 */
function failOpen(reason, err) {
  const cause = err && err.message ? String(err.message) : String(err || "no detail");
  process.stderr.write(`${TAG} fail-open: ${reason}: ${cause.replace(/\s+/g, " ").slice(0, 200)}\n`);
}

try { main(); } catch (err) {
  failOpen("crashed before it could decide", err);
  if (!codexRuntime) process.stdout.write(JSON.stringify({ continue: true }));
}
