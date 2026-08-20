#!/usr/bin/env node
/**
 * Workflow guard (PreToolUse: Write|Edit).
 * Advisory warning when editing source code on the default branch or outside a
 * git worktree — i.e. likely off-pipeline work that should be on a task branch.
 * Never blocks. Debounced once per session.
 */
"use strict";

const fs = require("fs");
const path = require("path");
const os = require("os");
const crypto = require("crypto");
const { execSync } = require("child_process");

/**
 * A temp-directory path scoped to the repository this hook is running in.
 *
 * The advisory hooks keep their debounce and threshold state in `os.tmpdir()`,
 * which is machine-global: a fixed filename means two sessions in two checkouts
 * share one marker, and the second session's warning is suppressed by the
 * first's — silently, for the TTL, most often under the unattended concurrency
 * this guidance encourages. The digest of the working directory is what makes
 * the state per repository rather than per machine. Hashed rather than embedded
 * so the name stays a fixed length and carries no path a temp-directory listing
 * would expose.
 */
function scopedState(name) {
  const key = crypto.createHash("sha256").update(process.cwd()).digest("hex").slice(0, 16);
  return path.join(os.tmpdir(), `${name}-${key}`);
}

const DEBOUNCE = scopedState("guidance-workflow-guard-warned");
const TTL_MS = 4 * 60 * 60 * 1000;
// Paths that are not "source" — editing these off-branch is fine. The trailing
// `/\.md$/` covers every markdown file, so naming CONTEXT.md and README.md
// ahead of it was two patterns that could never fire; `test_workflow_guard_hook`
// measures all three paths behaviourally.
const NON_SOURCE = [/(^|\/)\.guidance-lock\.yaml$/, /\.md$/];
// The branches other people build on. This is `push-target-guard.js`'s
// `FALLBACK_PROTECTED`, and deliberately the same set: the two hooks answer the
// same question about a branch name — is this one shared — and answering it
// differently is how `staging` became a branch you could edit source on
// directly and could not push to. The set cannot be imported (that would make
// this hook depend on a sibling, which the bundle keeps to exactly one), so
// `test_workflow_guard_hook` derives its corpus from the export instead: adding
// a name there is what makes this list red.
const SHARED_BRANCH = /^(main|master|dev|develop|trunk|staging|release|production)$/;

function recentlyWarned() {
  try { return Date.now() - fs.statSync(DEBOUNCE).mtimeMs < TTL_MS; } catch { return false; }
}
function markWarned() { try { fs.writeFileSync(DEBOUNCE, String(Date.now())); } catch { /* best-effort: advisory debounce marker, ignore write failures */ } }
function git(cmd) { try { return execSync(`git ${cmd}`, { stdio: ["ignore", "pipe", "ignore"] }).toString().trim(); } catch { return ""; } }

function editedPaths(input) {
  const tool = input.tool_name || "";
  const ti = input.tool_input || {};
  if (tool === "Write" || tool === "Edit") return ti.file_path ? [ti.file_path] : [];
  if (tool !== "apply_patch" || typeof ti.command !== "string") return [];
  return Array.from(
    ti.command.matchAll(/^\*\*\* (?:Add|Update|Delete) File: (.+)$/gm),
    (match) => match[1]
  );
}

let codexRuntime = false;

function readStdin() {
  const input = JSON.parse(fs.readFileSync(0, "utf8"));
  codexRuntime = Object.prototype.hasOwnProperty.call(input, "turn_id");
  return input;
}

function main() {
  const input = readStdin();
  const tool = input.tool_name || "";
  const codex = codexRuntime;
  if (tool !== "Write" && tool !== "Edit" && tool !== "apply_patch") return done(null, codex);

  const files = editedPaths(input);
  if (!files.length || files.every((file) => NON_SOURCE.some((p) => p.test(file)))) {
    return done(null, codex);
  }
  if (recentlyWarned()) return done(null, codex);

  const branch = git("rev-parse --abbrev-ref HEAD");
  const isWorktree = git("rev-parse --is-inside-work-tree") === "true" &&
    git("rev-parse --git-common-dir") !== git("rev-parse --git-dir");
  const onDefault = SHARED_BRANCH.test(branch);

  if (onDefault || !isWorktree) {
    markWarned();
    const why = onDefault ? `you are on '${branch}'` : "you are not in a task worktree";
    return done(
      `[WORKFLOW-GUARD] Editing source while ${why}. Per 'worktree-isolation', task work belongs ` +
      `on a feature branch in its own worktree, not on the default branch. If this is a deliberate ` +
      `quick fix, carry on; otherwise branch first.`,
      codex
    );
  }
  done(null, codex);
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
  process.stderr.write(
    `[WORKFLOW-GUARD] fail-open: ${reason}: ${cause.replace(/\s+/g, " ").slice(0, 200)}\n`
  );
}

try { main(); } catch (err) {
  failOpen("crashed before it could decide", err);
  if (!codexRuntime) process.stdout.write(JSON.stringify({ continue: true }));
}
