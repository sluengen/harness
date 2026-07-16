#!/usr/bin/env node
// guidance:hook-context-monitor@0.1.1
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

const CONTEXT_BUDGET = 200000;       // approx token window
const WARN = 0.7, CRITICAL = 0.85;   // fractions of budget used
const STATE = path.join(os.tmpdir(), "guidance-context-monitor-state");
const EVERY = 5;                      // only check every N tool uses

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

try { main(); } catch { process.stdout.write(JSON.stringify({ continue: true })); }
