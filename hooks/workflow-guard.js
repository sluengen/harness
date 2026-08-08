#!/usr/bin/env node
// guidance:hook-workflow-guard@0.2.0
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
const { execSync } = require("child_process");

const DEBOUNCE = path.join(os.tmpdir(), "guidance-workflow-guard-warned");
const TTL_MS = 4 * 60 * 60 * 1000;
// Paths that are not "source" — editing these off-branch is fine.
const NON_SOURCE = [/(^|\/)\.guidance-lock\.yaml$/, /(^|\/)CONTEXT\.md$/, /(^|\/)README\.md$/, /\.md$/];

function recentlyWarned() {
  try { return Date.now() - fs.statSync(DEBOUNCE).mtimeMs < TTL_MS; } catch { return false; }
}
function markWarned() { try { fs.writeFileSync(DEBOUNCE, String(Date.now())); } catch { /* best-effort: advisory debounce marker, ignore write failures */ } }
function git(cmd) { try { return execSync(`git ${cmd}`, { stdio: ["ignore", "pipe", "ignore"] }).toString().trim(); } catch { return ""; } }

function main() {
  const input = JSON.parse(fs.readFileSync(0, "utf8"));
  const tool = input.tool_name || "";
  if (tool !== "Write" && tool !== "Edit") return done();

  const file = (input.tool_input && input.tool_input.file_path) || "";
  if (!file || NON_SOURCE.some((p) => p.test(file))) return done();
  if (recentlyWarned()) return done();

  const branch = git("rev-parse --abbrev-ref HEAD");
  const isWorktree = git("rev-parse --is-inside-work-tree") === "true" &&
    git("rev-parse --git-common-dir") !== git("rev-parse --git-dir");
  const onDefault = /^(main|master|dev|develop|trunk)$/.test(branch);

  if (onDefault || !isWorktree) {
    markWarned();
    const why = onDefault ? `you are on '${branch}'` : "you are not in a task worktree";
    return done(
      `[WORKFLOW-GUARD] Editing source while ${why}. Per 'worktree-isolation', task work belongs ` +
      `on a feature branch in its own worktree, not on the default branch. If this is a deliberate ` +
      `quick fix, carry on; otherwise branch first.`
    );
  }
  done();
}

function done(additionalContext) {
  const out = { continue: true };
  if (additionalContext) out.additionalContext = additionalContext;
  process.stdout.write(JSON.stringify(out));
}

/**
 * Fail open, loudly. See the identical helper in the other four hooks (#303): the
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
  process.stdout.write(JSON.stringify({ continue: true }));
}
