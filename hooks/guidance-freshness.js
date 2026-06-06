#!/usr/bin/env node
// guidance:hook-guidance-freshness@0.2.0
/**
 * Guidance freshness (PostToolUse: Write|Edit). Advisory, never blocks. Debounced.
 *
 * In the guidance SOURCE repo (registry.yaml present):
 *   - Version drift: a distributable/meta file whose header no longer matches its
 *     registry version. JSON settings carry no header — the registry version is
 *     authoritative, so they get the generic bump reminder instead.
 *   - meta files (BOOTSTRAP.md, registry.yaml) are watched too, not just subdirs.
 *   - Leak guard: a universal prose file (skills/agents/commands/process/templates)
 *     containing a repo proper-noun — a ticket-ID-shaped token — which the
 *     universal/repo-specific rule forbids (AGENTS.md). What harness-steward greps
 *     for, surfaced inline.
 * In a CONSUMING repo (.guidance-lock.yaml present): editing installed guidance
 *   creates a local divergence; fix it upstream and /update-guidance.
 */
"use strict";

const fs = require("fs");
const path = require("path");
const os = require("os");

const TTL_MS = 4 * 60 * 60 * 1000;
const D_DRIFT = path.join(os.tmpdir(), "guidance-freshness-drift");
const D_GENERIC = path.join(os.tmpdir(), "guidance-freshness-generic");
const D_LEAK = path.join(os.tmpdir(), "guidance-freshness-leak");

const DIST = /^(skills|agents|commands|templates|process|hooks|settings)\//;
const META = /^(BOOTSTRAP\.md|registry\.yaml)$/;
const PROSE = /^(skills|agents|commands|process|templates)\//;       // universal prose — leak-checked
// Ticket-ID shape (e.g. CAL-42), excluding obvious standards refs.
const TICKET = /\b([A-Z]{2,5})-\d+\b/g;
// Standards/abbreviations that share the ticket-ID shape but are not repo facts.
// AC = acceptance criteria (AC-1, AC-2) used in templates/change.md.
const STD = new Set(["RFC", "ISO", "SCA", "CVE", "UTF", "SHA", "HTTP", "ADR", "AES", "ID", "UUID", "AC"]);

function recently(f) { try { return Date.now() - fs.statSync(f).mtimeMs < TTL_MS; } catch { return false; } }
function mark(f) { try { fs.writeFileSync(f, String(Date.now())); } catch {} }
function read(p) { try { return fs.readFileSync(p, "utf8"); } catch { return ""; } }
function rel(cwd, file) { return file.startsWith(cwd) ? file.slice(cwd.length + 1) : file; }
function headerVersion(c) { const m = c.match(/guidance:[\w-]+@([\d.]+)/); return m ? m[1] : null; }
function registryVersion(reg, relPath) {
  const m = reg.match(new RegExp(relPath.replace(/[.*+?^${}()|[\]\\/]/g, "\\$&") + ":\\s*\\{[^}]*version:\\s*([\\d.]+)"));
  return m ? m[1] : null;
}
function leakedIds(content) {
  const hits = new Set();
  for (const m of content.matchAll(TICKET)) if (!STD.has(m[1])) hits.add(m[0]);
  return [...hits];
}

function main() {
  const input = JSON.parse(fs.readFileSync(0, "utf8"));
  if (input.tool_name !== "Write" && input.tool_name !== "Edit") return done();
  const cwd = process.cwd();
  const relPath = rel(cwd, (input.tool_input && input.tool_input.file_path) || "");
  const isDist = DIST.test(relPath), isMeta = META.test(relPath);
  if (!isDist && !isMeta) return done();

  const registry = read(path.join(cwd, "registry.yaml"));
  const lock = read(path.join(cwd, ".guidance-lock.yaml"));

  // SOURCE repo
  if (registry) {
    // Leak guard on universal prose files.
    if (PROSE.test(relPath)) {
      const ids = leakedIds(read(path.join(cwd, relPath)));
      if (ids.length && !recently(D_LEAK)) {
        mark(D_LEAK);
        return done(`[GUIDANCE-FRESHNESS] ${relPath} contains repo-specific ID(s): ${ids.join(", ")}. ` +
          `Universal guidance must name no repo facts (AGENTS.md) — use <issue-id>/<team-key> placeholders ` +
          `or move it to a repo's CONTEXT.md.`);
      }
    }
    // Version drift — JSON settings have no header, so the registry version is authoritative.
    if (!relPath.endsWith(".json")) {
      const fileVer = headerVersion(read(path.join(cwd, relPath)));
      const regVer = registryVersion(registry, relPath);
      if (fileVer && regVer && fileVer !== regVer && !recently(D_DRIFT)) {
        mark(D_DRIFT);
        return done(`[GUIDANCE-FRESHNESS] ${relPath} header says @${fileVer} but registry.yaml says @${regVer}. ` +
          `Make them match — /update-guidance and the integrity check key off the version.`);
      }
    }
    if (!recently(D_GENERIC)) {
      mark(D_GENERIC);
      const where = relPath.endsWith(".json")
        ? "bump its version in registry.yaml (JSON carries no header) and note it in CHANGELOG.md"
        : isMeta
          ? "bump its version in both the file header and the registry `meta:` block, and note it in CHANGELOG.md"
          : "bump its version in both the file header and registry.yaml, and note it in CHANGELOG.md";
      return done(`[GUIDANCE-FRESHNESS] You edited a version-stamped file (${relPath}). Before finishing: ${where}. ` +
        `An un-bumped edit is invisible to repos that installed it.`);
    }
    return done();
  }

  // CONSUMING repo
  if (lock && new RegExp("\\b" + relPath.replace(/[.*+?^${}()|[\]\\/]/g, "\\$&") + ":").test(lock)) {
    if (!recently(D_GENERIC)) {
      mark(D_GENERIC);
      return done(`[GUIDANCE-FRESHNESS] ${relPath} is installed guidance (tracked in .guidance-lock.yaml). ` +
        `Editing it here creates a local divergence /update-guidance will flag forever. Fix it upstream, ` +
        `bump the version, then /update-guidance.`);
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
