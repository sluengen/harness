#!/usr/bin/env node
// guidance:hook-guidance-freshness@0.3.5
/**
 * Guidance freshness (PostToolUse: Write|Edit). Advisory, never blocks. Debounced.
 *
 * Everywhere: AGENTS.md/CLAUDE.md/GEMINI.md must stay byte-identical (one process doc
 * under three names) — flags a regeneration that updated one but not the others.
 *
 * In the guidance SOURCE repo (registry.yaml present):
 *   - Version drift: a distributable/meta file whose header no longer matches its
 *     registry version. JSON settings carry no header — the registry version is
 *     authoritative, so they get the generic bump reminder instead.
 *   - meta files (BOOTSTRAP.md, registry.yaml) are watched too, not just subdirs.
 *   - Leak guard: a universal prose file (skills/agents/commands/process/templates)
 *     containing a repo proper-noun — a ticket-ID-shaped token — which the
 *     universal/repo-specific rule forbids (AGENTS.md). What system-steward greps
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
const D_SELFVER = path.join(os.tmpdir(), "guidance-freshness-selfver");
const D_GENERIC = path.join(os.tmpdir(), "guidance-freshness-generic");
const D_LEAK = path.join(os.tmpdir(), "guidance-freshness-leak");
const D_ENTRY = path.join(os.tmpdir(), "guidance-freshness-entry");

const DIST = /^(skills|agents|commands|templates|process|hooks|settings)\//;
const META = /^(BOOTSTRAP\.md|registry\.yaml)$/;
const ENTRY = new Set(["AGENTS.md", "CLAUDE.md", "GEMINI.md"]);      // triplicated entry files — must match
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
// A path is managed by the source only if it appears as a key in registry.yaml
// (files: or meta:). A file under a surface dir but absent from the registry is
// repo-owned (e.g. a repo's own command it keeps under commands/) — not
// distributed guidance. (commands/harness.md used to be this example; CAL-764
// registered it, so it is now distributed guidance like any other command.)
function registryMember(reg, relPath) {
  return new RegExp("(^|\\n)\\s*" + relPath.replace(/[.*+?^${}()|[\]\\/]/g, "\\$&") + ":\\s*\\{").test(reg);
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

  // Entry-file triplication: AGENTS.md / CLAUDE.md / GEMINI.md are three copies of one
  // process doc and must stay byte-identical. Catch a regeneration that updated one but
  // not the others (the classic /update-guidance miss).
  if (ENTRY.has(relPath)) {
    const present = [...ENTRY].map((f) => read(path.join(cwd, f))).filter(Boolean);
    if (present.length >= 2 && present.some((c) => c !== present[0]) && !recently(D_ENTRY)) {
      mark(D_ENTRY);
      return done(
        "[GUIDANCE-FRESHNESS] AGENTS.md, CLAUDE.md, and GEMINI.md must be byte-identical " +
          "(three copies of one process doc) — they currently differ. If you are mid-regeneration " +
          "(e.g. /update-guidance just rewrote one), update the other two now; otherwise a " +
          "regeneration was skipped: re-derive all three from the process doc."
      );
    }
    return done();
  }

  const isDist = DIST.test(relPath), isMeta = META.test(relPath);
  if (!isDist && !isMeta) return done();

  const registry = read(path.join(cwd, "registry.yaml"));
  const lock = read(path.join(cwd, ".guidance-lock.yaml"));

  // SOURCE repo
  if (registry) {
    // Repo-owned files under a surface dir but excluded from the copy-list
    // (e.g. a repo-local command a consuming repo keeps under commands/) are not
    // distributed guidance — source-mode checks must not apply to them. (This was
    // commands/harness.md until CAL-764 registered it; the mechanism still guards
    // any genuinely repo-owned file.) Identify them without naming any repo fact:
    // a non-member that carries no `guidance:` header AND is not a `.json` is
    // repo-owned, so skip it. The `.json` carve-out matters because settings
    // JSON is the one *headerless* distributable type (the registry version is
    // authoritative) — a new, unregistered settings file must still draw the
    // register reminder. A non-member that carries a header is likewise a new
    // guidance file not yet registered — keep checking it. Meta files
    // (registry.yaml, BOOTSTRAP.md) are always checked (isDist is false for
    // them), so a malformed registry that drops its own meta entry can't silence
    // the reminder for the very file being broken.
    if (isDist && !registryMember(registry, relPath) &&
        !relPath.endsWith(".json") &&
        !headerVersion(read(path.join(cwd, relPath)))) return done();
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
      if (fileVer && regVer && fileVer !== regVer) {
        // registry.yaml is self-referential: its `# guidance:registry@` header
        // stamp and its own row in the `meta:` table both live in this one file,
        // so a one-sided bump is easy to miss. Give that case a DEDICATED debounce
        // marker (D_SELFVER) so an unrelated file's drift warning in the same
        // window can't mask it, and a message naming both spots + the guard.
        const self = relPath === "registry.yaml";
        const marker = self ? D_SELFVER : D_DRIFT;
        if (!recently(marker)) {
          mark(marker);
          return done(self
            ? `[GUIDANCE-FRESHNESS] registry.yaml carries its version in TWO places and they disagree: ` +
              `the \`# guidance:registry@${fileVer}\` header vs its \`meta:\` self-entry @${regVer}. ` +
              `Bump BOTH — test_registry_header_matches_meta_self_version enforces the parity.`
            : `[GUIDANCE-FRESHNESS] ${relPath} header says @${fileVer} but registry.yaml says @${regVer}. ` +
              `Make them match — /update-guidance and the integrity check key off the version.`);
        }
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
