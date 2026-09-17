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
 * arbitrary shell, which the deleted `git-push-guard.js` measured at 971 lines
 * that still refused on ambiguity. The hook raises the cost of the cheapest and
 * most common cheat; what stands behind it is the reviewer's explicit item per
 * test-file diff and the declared gate. Whatever a repository runs server-side
 * is its own and is not claimed here (ADR 0022 point 2).
 *
 * **A move or a rename is an edit**, and it reaches here as whatever path the
 * tool names: `Write` names the destination, and an `apply_patch` header naming
 * a governed path under `Add`, `Update` or `Delete` is refused like any other
 * edit to it. A rename through `Bash` is invisible for the reason above, and
 * `specs/harness-assumptions.md` records that gap with the test that would
 * retire it.
 *
 * **Past `engineering`'s 300-line soft limit, deliberately.** #659 replaced one
 * prefix test with a declared-roots-times-declared-globs predicate; the added
 * length is that predicate and the reasons each half of it refuses what it
 * refuses, which is the part a reader needs most in a file that blocks work.
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

//: The governed set is **declared roots times declared basename globs** (#659).
//: `paths.tests` carries the roots, comma-separated; the optional
//: `paths.test_files` carries basename globs that narrow which files under them
//: are governed. Absent globs govern everything under a root, which is the rule
//: this hook shipped with and is what keeps an existing consumer's refusals
//: exactly where they were.

/** The roots ``paths.tests`` declares, each a posix prefix ending in one slash.
 *
 * An entry that is empty after normalising is dropped: ``tests/, `` declares one
 * root, not two. **What makes that safe is the trailing slash, not this filter**
 * — an undropped empty entry becomes ``"/"``, and no repo-relative path starts
 * with a slash, so it matches nothing. Mutation says so: removing the filter
 * alone kills no test, because it cannot. The filter is here to keep a root
 * nobody declared out of the set; the catastrophic value is ``""``, which
 * ``startsWith`` admits for every path in the tree, and the append is what the
 * set is never allowed to lose.
 */
function testRoots(raw) {
  if (typeof raw !== "string") return [];
  const roots = [];
  for (const entry of raw.split(",")) {
    const normalised = entry.trim().replace(/\\/g, "/").replace(/^\.\//, "").replace(/\/+$/, "");
    if (normalised) roots.push(normalised + "/");
  }
  return roots;
}

/** The basename matchers ``paths.test_files`` declares.
 *
 * ``null`` — not declared: every file under a root is governed, the shipped rule.
 * ``false`` — declared and unusable: govern nothing, and say so.
 * ``RegExp[]`` — the declared set, each anchored at **both** ends.
 *
 * ``*`` is the only metacharacter and every other character is a literal, ``.``
 * included. Anchoring at both ends is load-bearing: head-anchored, ``*.test.ts``
 * also matches ``foo.test.ts.snap``, and a snapshot file is not a test.
 *
 * An entry carrying ``/`` is a **path** glob, which this matcher does not
 * implement, and it is refused whole rather than silently never matching. The
 * fallback direction is the decision: widening to blanket root coverage would
 * refuse every production edit under a declared source root on a typo.
 */
function testFileGlobs(raw) {
  if (raw === undefined || raw === null) return null;
  if (typeof raw !== "string") return false;
  const entries = raw.split(",").map((entry) => entry.trim()).filter((entry) => entry !== "");
  if (!entries.length) return false;
  const globs = [];
  for (const entry of entries) {
    if (entry.includes("/")) return false;
    const pattern = entry.replace(/[.*+?^${}()|[\]\\]/g, "\\$&").replace(/\\\*/g, "[^/]*");
    globs.push(new RegExp("^" + pattern + "$"));
  }
  return globs;
}

/** Is ``rel`` in the governed set? Pure over its three arguments. */
function governs(rel, roots, globs) {
  let underAny = false;
  for (const root of roots) {
    if (rel === root.slice(0, -1) || rel.startsWith(root)) {
      underAny = true;
      break;
    }
  }
  if (!underAny) return false;
  if (globs === null) return true;
  const slash = rel.lastIndexOf("/");
  const base = slash === -1 ? rel : rel.slice(slash + 1);
  return globs.some((glob) => glob.test(base));
}

/** ``{roots, globs}`` for the repo at ``top``, or null to leave the lock inactive.
 *
 * **The reader was already loud and this hook was deaf.** ``declaredPaths``
 * reports every source it cannot parse, and the call here used to pass no
 * reporter, so a declaration the reader refused — a yaml sequence under
 * ``tests:``, an unhydrated ``{tests/}`` placeholder — was indistinguishable
 * from a repo that declares nothing (#659, #302).
 *
 * The disabling is what stops being silent. No part of the lock survives an
 * unreadable declaration: the reader refuses that map whole, and a guessed test
 * root is the false-deny factory ``declaredPaths``' own docstring refuses.
 * Failing **closed** is not available to a ``PreToolUse`` deny — it would refuse
 * the edit to ``harness.yaml`` that clears it.
 */
function governedSet(config, top) {
  if (!config) return null;
  // Latched: the reader walks up to four sources and may report more than once,
  // and this hook's notices are one line by convention.
  let unreadable = null;
  const declared = config.declaredPaths(top, (source) => {
    if (unreadable === null) unreadable = path.basename(source);
  });
  if (unreadable !== null) {
    failOpen("could not read the paths declaration, so the test lock is inactive", unreadable);
    return null;
  }
  const roots = testRoots(declared && declared.tests);
  if (!roots.length) return null;
  const globs = testFileGlobs(declared && declared.test_files);
  if (globs === false) {
    failOpen(
      "could not use the declared paths.test_files globs, so the test lock is inactive",
      "basename globs only, and none may contain a slash"
    );
    return null;
  }
  return { roots, globs };
}

/** The repo-relative posix path of ``file``, or null when it is outside ``top``. */
function relativeTo(top, dir, file) {
  const abs = path.resolve(dir, file);
  const rel = path.relative(top, abs).split(path.sep).join("/");
  if (!rel || rel === ".." || rel.startsWith("../") || path.isAbsolute(rel)) return null;
  return rel;
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
//: into a model's context, so the only untrusted bytes that reach it are the
//: edited path itself, reduced to path characters and truncated before it is
//: quoted (law 6). The reduction is what makes that safe — not the path's
//: provenance, which is the payload's.
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

  const governed = governedSet(loadConfig(), top);
  if (!governed) return null;

  const lane = LANES[state.lane];
  const base = typeof state.base_commit === "string" ? state.base_commit : "";

  for (const file of files) {
    const rel = relativeTo(top, dir, file);
    if (rel === null || !governs(rel, governed.roots, governed.globs)) continue;
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
