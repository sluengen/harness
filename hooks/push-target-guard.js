#!/usr/bin/env node
/**
 * Push-target advisory (PreToolUse: Bash).
 *
 * Warns when a `git push` names a branch this repository declared under
 * `branches:` in `harness.yaml`, and lets it through. Advisory only — it has no
 * refusal to reach.
 *
 * **What it used to be, and why it is not that any more.** Until #621 this hook
 * refused such a push unless a fresh gate marker covered the pushed tree. ADR
 * 0022 retires that: point 3 forbids a plugin-shipped executable from reading a
 * verdict — whether a gate passed, a review happened, a tree was certified —
 * because finding a verdict is step one of the chain that produced the marker,
 * the tree resolution, three parsers and 3,110 lines of hooks. Point 4 then asks
 * what a guard here is *for*, and answers advisory: a push aimed at the wrong
 * branch is neither unrecoverable nor silent. The operator sees the push in the
 * transcript, and the integration branch is revertible at this repo's stage.
 *
 * That change is what shrank the file from 1,143 lines to this. The asymmetry
 * ADR 0022 point 4 names is the whole reason: **a refusal must not be
 * bypassable and therefore grows a parser** — deciding a push target from a raw
 * command string reliably needs a POSIX shell lexer, which is what the deleted
 * `git-push-guard.js` was. **An advisory tolerates false negatives and stays
 * small.**
 *
 * **The false negatives, named rather than discovered.** Each costs one
 * un-warned push, which the operator still sees:
 *
 *   - `git push` with no refspec — the target comes from upstream tracking
 *     configuration, not from the command line, so there is nothing here to read.
 *   - A push inside a command substitution, a heredoc, or behind a shell
 *     variable — this reads tokens, it does not evaluate them.
 *   - `git -C <elsewhere> push` — the declaration read is this working
 *     directory's, so a push aimed at another repository is compared against the
 *     wrong `harness.yaml`. It warns or stays silent on the wrong basis; either
 *     way it refuses nothing.
 *
 * **What it reads** (ADR 0022 point 3, in full): the intercepted tool call, the
 * working directory git resolves for it, and the branch names `harness.yaml`
 * declares. No marker, no ref state, no verdict.
 */
"use strict";

//: The names assumed protected when a repository declares no `branches:` at all.
//: Kept from the refusing guard, and still exported, for a coupling rather than
//: for conservatism: ``workflow-guard.js`` hardcodes the same vocabulary — the
//: two answer the same question about a branch name, and answering it
//: differently is how ``staging`` became a branch you could edit source on
//: directly and could not push to. It cannot import this set (that would give
//: the advisory hooks a sibling dependency the bundle keeps to exactly one), so
//: ``test_workflow_guard_hook`` derives its corpus from this export instead:
//: adding a name here is what makes that hook's list red.
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

/**
 * Fail open, loudly. See the identical helper in the other hooks (#303): the
 * approving payload still goes out, but stderr says this hook did not run, so a
 * silently-disarmed guard is distinguishable from a deliberate pass-through.
 * Built from hook-owned constants and `err.message` only — never the payload,
 * which carries untrusted text (law 6).
 *
 * Since this hook became advisory, failing open and deciding not to warn are the
 * same outcome. The notice is still worth writing: it distinguishes "nothing to
 * warn about" from "could not tell", and the second is the one that rots.
 */
function failOpen(reason, err) {
  const cause = err && err.message ? String(err.message) : String(err || "no detail");
  process.stderr.write(
    `[PUSH-TARGET-GUARD] fail-open: ${reason}: ${cause.replace(/\s+/g, " ").slice(0, 200)}\n`
  );
}

let codexRuntime = false;

function readStdin() {
  try {
    const input = JSON.parse(require("fs").readFileSync(0, "utf8"));
    codexRuntime = Object.prototype.hasOwnProperty.call(input, "turn_id");
    return input;
  }
  catch (err) { failOpen("could not parse the hook payload on stdin", err); return {}; }
}

/** The repository root for ``cwd``, or null when there is no repository.
 *
 * A fact about the tree in front of the hook, which point 3 permits. `require`
 * sits inside the function for the ESM reason every hook in this bundle shares
 * (#302): both `require` and `module` are undefined when a consuming repo
 * declares `"type": "module"` and `hooks/package.json` is missing.
 */
function toplevel(cwd) {
  // The `require` sits outside the `try` deliberately, exactly as
  // `test-lock-guard.js`'s `git()` helper does. A `try` body that loads a module
  // is a failure of the hook's own machinery and owes a `failOpen`; this probe
  // is not that. It is a decision input — a push issued outside any repository
  // is a legitimate silence, not a disarmed guard — and `test_hooks_fail_open_is_loud`
  // draws that line by the shape of the `try`, so the shape has to be right.
  const { execFileSync } = require("child_process");
  try {
    const top = execFileSync("git", ["rev-parse", "--show-toplevel"], {
      cwd,
      encoding: "utf8",
      stdio: ["ignore", "pipe", "ignore"],
    }).trim();
    return top || null;
  }
  catch { return null; }
}

/** The branch names this repository declared, or the fallback set.
 *
 * The one shared reader (`scripts/harness-config.js`), not a fourth hand-rolled
 * parser — #487, #488 and #510 were each a bug in one of three copies.
 */
function declaredBranches(top) {
  if (top === null) return FALLBACK_PROTECTED;
  try {
    const config = require("path").join(__dirname, "..", "scripts", "harness-config.js");
    const declared = Object.values(require(config).declaredBranches(top));
    return declared.length ? declared : FALLBACK_PROTECTED;
  }
  catch (err) {
    failOpen("could not read the branch declaration", err);
    return FALLBACK_PROTECTED;
  }
}

/** The branch names ``command`` appears to push to.
 *
 * A token scan, deliberately. Everything after a `push` token preceded by a
 * `git`-shaped token is treated as a candidate operand: strip a leading `+`
 * (the force spelling of a refspec), take the segment after the last `:` (the
 * destination half of `src:dst`), and strip a `refs/heads/` prefix. Options and
 * the remote name fall out on their own — they match no declared branch.
 */
function targets(command) {
  const tokens = String(command).split(/\s+/).filter(Boolean);
  const found = [];
  for (let i = 0; i < tokens.length; i += 1) {
    if (tokens[i] !== "push") continue;
    if (!tokens.slice(0, i).some((t) => t === "git" || t.endsWith("/git"))) continue;
    for (const operand of tokens.slice(i + 1)) {
      if (operand.startsWith("-")) continue;
      const dst = operand.replace(/^\+/, "").split(":").pop();
      found.push(dst.replace(/^refs\/heads\//, ""));
    }
  }
  return found;
}

function main() {
  const input = readStdin();
  const codex = codexRuntime;
  if ((input.tool_name || "") !== "Bash") return done(null, codex);

  const command = (input.tool_input || {}).command;
  if (!command) return done(null, codex);

  const named = targets(command);
  if (!named.length) return done(null, codex);

  // Resolved once, after a push target is in hand: a repository probe and a
  // config read on every Bash call would be a cost this hook has no reason to
  // spend, and the answer cannot change between operands.
  const declared = declaredBranches(toplevel(input.cwd || process.cwd()));
  const hit = named.find((name) => declared.includes(name));
  if (!hit) return done(null, codex);

  done(
    `[PUSH-TARGET-GUARD] This pushes to '${hit}', a branch this repo declares under ` +
    `'branches:'. Land there only with the gate run and read over this tree and the ` +
    `review passed on it (spine law 3). Carry on if that is where this belongs.`,
    codex
  );
}

function done(additionalContext, codex) {
  if (codex) {
    if (!additionalContext) return;
    process.stdout.write(JSON.stringify({
      hookSpecificOutput: {
        hookEventName: "PreToolUse",
        additionalContext,
      },
    }));
    return;
  }
  const out = { continue: true };
  if (additionalContext) out.additionalContext = additionalContext;
  process.stdout.write(JSON.stringify(out));
}

// The `require.main === module` guard is what lets a test import this file to
// read `FALLBACK_PROTECTED` or drive `targets` without the hook running and
// writing its pass-through object onto the test's stdout. Kept from the refusing
// guard for exactly that reason: `test_workflow_guard_hook` reads the fallback
// set off this module, and without the guard it reads the JSON too.
if (require.main === module) {
  try {
    main();
  } catch (err) {
    // The hook could not run, so it has no opinion. Pass through, but loudly —
    // a disarmed guard must not look like a clean pass (#303).
    failOpen("crashed before it could decide", err);
    if (!codexRuntime) process.stdout.write(JSON.stringify({ continue: true }));
  }
}

// Exported for two readers. `FALLBACK_PROTECTED` is the corpus
// `test_workflow_guard_hook` holds the sibling advisory's branch alternation
// against — the two hooks answer the same question about a branch name, and
// answering it differently is how `staging` became a branch you could edit
// source on directly and could not push to. `targets` and `declaredBranches` are
// exported so this hook's own tests drive the production predicates rather than
// re-implementing them and agreeing with themselves (#462).
module.exports = {
  FALLBACK_PROTECTED,
  targets,
  declaredBranches,
};
