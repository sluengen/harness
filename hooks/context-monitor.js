#!/usr/bin/env node
// guidance:hook-context-monitor@0.3.0
/**
 * Context monitor (PostToolUse).
 * Estimates context usage from the session transcript size and warns when it
 * runs high, so the agent commits and summarises before it loses state.
 * Heuristic (chars/4 ≈ tokens), advisory, never blocks. Debounced.
 *
 * Thresholds are a rough proxy, not an exact token count. Tune CONTEXT_BUDGET
 * if your model's window differs materially.
 */
"use strict";

const fs = require("fs");
const path = require("path");
const os = require("os");
const crypto = require("crypto");

const CONTEXT_BUDGET = 200000;       // approx token window
const WARN = 0.7, CRITICAL = 0.85;   // fractions of budget used
const EVERY = 5;                      // only check every N tool uses

/**
 * A temp-directory path scoped to the repository this hook is running in.
 *
 * `os.tmpdir()` is machine-global, so a fixed filename means two sessions in two
 * checkouts share one state file. That is worse here than for a plain debounce:
 * the state carries the last level *reported*, and the report is on a rising
 * edge, so the second session inherits a level it never reached, sees no rise,
 * and stays silent about a context that is already critical. Silence is the
 * failure mode, which is why nothing surfaced it. The digest of the working
 * directory is what makes the state per repository; hashed rather than embedded
 * so the name stays a fixed length and carries no path a listing would expose.
 */
function scopedState(name) {
  const key = crypto.createHash("sha256").update(process.cwd()).digest("hex").slice(0, 16);
  return path.join(os.tmpdir(), `${name}-${key}`);
}

const STATE = scopedState("guidance-context-monitor-state");

function loadState() {
  try { return JSON.parse(fs.readFileSync(STATE, "utf8")); } catch { return { n: 0, level: 0 }; }
}
function saveState(s) { try { fs.writeFileSync(STATE, JSON.stringify(s)); } catch { /* best-effort: advisory state cache, ignore write failures */ } }

function main() {
  const input = JSON.parse(fs.readFileSync(0, "utf8"));
  const transcript = input.transcript_path;
  const s = loadState();
  s.n = (s.n || 0) + 1;

  let size = 0;
  try { size = fs.statSync(transcript).size; } catch { /* no transcript — skip */ }
  if (!size) { saveState(s); return done(); }

  const usedFrac = (size / 4) / CONTEXT_BUDGET;   // chars/4 ≈ tokens
  const level = usedFrac >= CRITICAL ? 2 : usedFrac >= WARN ? 1 : 0;

  // Report on a rising edge immediately; otherwise only every EVERY calls.
  const rising = level > (s.level || 0);
  if (level === 0 || (!rising && s.n % EVERY !== 0)) { s.level = level; saveState(s); return done(); }
  s.level = level; saveState(s);

  const pct = Math.round(usedFrac * 100);
  if (level === 2) {
    return done(`[CONTEXT ~${pct}%] Critical: commit your work, write a short state summary, and ` +
      `stop or hand off. Past this point quality degrades and state can be lost.`);
  }
  return done(`[CONTEXT ~${pct}%] Getting full: finish and commit the current unit of work soon, ` +
    `and avoid starting a large new sub-task without committing first.`);
}

function done(additionalContext) {
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
    `[CONTEXT-MONITOR] fail-open: ${reason}: ${cause.replace(/\s+/g, " ").slice(0, 200)}\n`
  );
}

if (require.main === module) {
  try { main(); } catch (err) {
    failOpen("crashed before it could decide", err);
    process.stdout.write(JSON.stringify({ continue: true }));
  }
}

// The thresholds, exported so `test_context_monitor_hook` can size its fixtures
// from the shipped numbers rather than restating them — retuning the budget then
// moves every case with it instead of silently reclassifying one. The
// `require.main === module` guard above means importing for that introspection
// never runs the monitor, which would otherwise block reading stdin.
module.exports = { CONTEXT_BUDGET, WARN, CRITICAL, EVERY };
