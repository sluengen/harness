#!/usr/bin/env node
// guidance:hook-guidance-freshness@0.1.0
/**
 * Guidance freshness (PostToolUse: Write|Edit).
 * Two modes, auto-detected:
 *   - In the guidance SOURCE repo (registry.yaml present): when a distributable
 *     file is edited, check its header version still matches registry.yaml and
 *     remind to bump the version + CHANGELOG. A header/registry mismatch is a
 *     concrete drift warning (the edit is invisible downstream otherwise).
 *   - In a CONSUMING repo (.guidance-lock.yaml present): when an installed
 *     guidance file is edited, warn that it creates a local divergence and the
 *     fix belongs upstream, pulled via /update-guidance.
 * Advisory, never blocks. Debounced per session.
 */
"use strict";

const fs = require("fs");
const path = require("path");
const os = require("os");

const TTL_MS = 4 * 60 * 60 * 1000;
const DRIFT_DEBOUNCE = path.join(os.tmpdir(), "guidance-freshness-drift");
const GENERIC_DEBOUNCE = path.join(os.tmpdir(), "guidance-freshness-generic");
const DIST = /^(skills|agents|commands|templates|process|hooks|settings)\//;

function recently(f) { try { return Date.now() - fs.statSync(f).mtimeMs < TTL_MS; } catch { return false; } }
function mark(f) { try { fs.writeFileSync(f, String(Date.now())); } catch {} }
function read(p) { try { return fs.readFileSync(p, "utf8"); } catch { return ""; } }

function rel(cwd, file) { return file.startsWith(cwd) ? file.slice(cwd.length + 1) : file; }
function headerVersion(content) { const m = content.match(/guidance:[\w-]+@([\d.]+)/); return m ? m[1] : null; }
function registryVersion(reg, relPath) {
  const m = reg.match(new RegExp(relPath.replace(/[.*+?^${}()|[\]\\/]/g, "\\$&") + ":\\s*\\{[^}]*version:\\s*([\\d.]+)"));
  return m ? m[1] : null;
}

function main() {
  const input = JSON.parse(fs.readFileSync(0, "utf8"));
  if (input.tool_name !== "Write" && input.tool_name !== "Edit") return done();
  const cwd = process.cwd();
  const relPath = rel(cwd, (input.tool_input && input.tool_input.file_path) || "");
  if (!DIST.test(relPath)) return done();

  const registry = read(path.join(cwd, "registry.yaml"));
  const lock = read(path.join(cwd, ".guidance-lock.yaml"));

  // SOURCE repo
  if (registry) {
    const fileVer = headerVersion(read(path.join(cwd, relPath)));
    const regVer = registryVersion(registry, relPath);
    if (fileVer && regVer && fileVer !== regVer && !recently(DRIFT_DEBOUNCE)) {
      mark(DRIFT_DEBOUNCE);
      return done(`[GUIDANCE-FRESHNESS] ${relPath} header says @${fileVer} but registry.yaml says ` +
        `@${regVer}. Make them match — downstream /update-guidance keys off the version.`);
    }
    if (!recently(GENERIC_DEBOUNCE)) {
      mark(GENERIC_DEBOUNCE);
      return done(`[GUIDANCE-FRESHNESS] You edited a distributable (${relPath}). Before finishing: ` +
        `bump its version in both the file header and registry.yaml, and note it in CHANGELOG.md. ` +
        `An edit without a version bump is invisible to repos that installed it.`);
    }
    return done();
  }

  // CONSUMING repo
  if (lock && new RegExp("\\b" + relPath.replace(/[.*+?^${}()|[\]\\/]/g, "\\$&") + ":").test(lock)) {
    if (!recently(GENERIC_DEBOUNCE)) {
      mark(GENERIC_DEBOUNCE);
      return done(`[GUIDANCE-FRESHNESS] ${relPath} is installed guidance (tracked in .guidance-lock.yaml). ` +
        `Editing it here creates a local divergence that /update-guidance will flag forever. If this is a ` +
        `real fix, make it upstream in the guidance source, bump the version, then /update-guidance.`);
    }
  }
  done();
}

function done(additionalContext) {
  const out = { continue: true };
  if (additionalContext) out.additionalContext = additionalContext;
  process.stdout.write(JSON.stringify(out));
}

try { main(); } catch { process.stdout.write(JSON.stringify({ continue: true })); }
