#!/usr/bin/env node
/**
 * Plugin version drift warning (SessionStart).
 *
 * A session runs the plugin version it loaded, and nothing after launch changes
 * that: a cloud session starts from an environment snapshot that skips its setup
 * script until the script is edited, and a local session keeps its version after
 * an on-disk update (#723). This hook compares the loaded manifest with the one
 * published on the marketplace's default branch and, when the loaded version is
 * behind, tells the session both versions and the remedy.
 *
 * Advisory only — never blocks. Every failure to read either version is an
 * answer, not a fault: the hook says nothing to the session and lets it start,
 * leaving a fail-open line on stderr where the published read failed. The read is
 * bounded by FETCH_TIMEOUT_MS, because session start waits on it, and goes through
 * the environment's declared proxy where there is one (#767).
 *
 * HARNESS_PUBLISHED_MANIFEST_URL overrides where the published manifest is read
 * from — the test seam, and how a fork points the check at itself.
 */
"use strict";

const PUBLISHED_MANIFEST_URL =
  "https://raw.githubusercontent.com/sluengen/harness/HEAD/.claude-plugin/plugin.json";
const FETCH_TIMEOUT_MS = 3000;

/**
 * Fail open, loudly (#303). Built from hook-owned constants and `err.message`
 * only, whitespace-collapsed and truncated so one failure is one line.
 * Inlined rather than shared, for the reason `prompt-guard.js` gives.
 */
function failOpen(reason, err) {
  const cause = err && err.message ? String(err.message) : String(err || "no detail");
  process.stderr.write(
    `[VERSION-DRIFT-GUARD] fail-open: ${reason}: ${cause.replace(/\s+/g, " ").slice(0, 200)}\n`
  );
}

let codexRuntime = false;

function readStdin() {
  try {
    const input = JSON.parse(require("fs").readFileSync(0, "utf8"));
    codexRuntime = Object.prototype.hasOwnProperty.call(input, "turn_id");
    return input;
  }
  catch (err) { failOpen("could not parse the hook payload on stdin", err); return null; }
}

/** `major.minor.patch` as three numbers, or null for anything else. */
function parseVersion(value) {
  const match = /^(\d+)\.(\d+)\.(\d+)(?:[-+].*)?$/.exec(typeof value === "string" ? value.trim() : "");
  return match ? match.slice(1, 4).map(Number) : null;
}

function isBehind(loaded, published) {
  for (let i = 0; i < 3; i++) {
    if (loaded[i] !== published[i]) return loaded[i] < published[i];
  }
  return false;
}

/** The version this session loaded: the manifest one directory above this hook. */
function loadedVersion(fs, path) {
  try {
    const manifest = path.join(__dirname, "..", ".claude-plugin", "plugin.json");
    return JSON.parse(fs.readFileSync(manifest, "utf8")).version;
  }
  catch { return null; }
}

/**
 * The proxy the environment declares for `url`'s scheme, or null.
 *
 * Node's `fetch` ignores these variables (measured on v24.19.0, #767), so a
 * container whose only egress is its declared proxy cannot read the published
 * manifest through it, and the hook stayed silent in exactly the cloud sessions
 * it exists to warn.
 */
function declaredProxy(url) {
  let scheme;
  try { scheme = new URL(url).protocol.slice(0, -1); }
  catch { return null; }
  const env = process.env;
  return env[`${scheme}_proxy`] || env[`${scheme.toUpperCase()}_PROXY`] ||
    env.all_proxy || env.ALL_PROXY || null;
}

/**
 * Read through `curl`, which honours the proxy and `no_proxy` natively, under the
 * same bound. Resolves to the body, null on a failed read, or `undefined` when
 * there is no `curl` to run, so the caller can fall back to `fetch`.
 */
function curlBody(url, proxy) {
  return new Promise((resolve) => {
    const seconds = String(FETCH_TIMEOUT_MS / 1000);
    require("child_process").execFile(
      "curl",
      ["--silent", "--show-error", "--fail", "--max-time", seconds, "--proxy", proxy, url],
      { timeout: FETCH_TIMEOUT_MS + 500, encoding: "utf8" },
      (err, stdout, stderr) => {
        if (err && err.code === "ENOENT") return resolve(undefined);
        // curl's own message, never `err.message`: that repeats the command line,
        // and a proxy URL can carry credentials.
        if (err) {
          failOpen("could not read the published version through the declared proxy",
            String(stderr || "").trim() || `curl exited ${err.code}`);
          return resolve(null);
        }
        resolve(stdout);
      }
    );
  });
}

async function fetchBody(url) {
  if (typeof fetch !== "function") { failOpen("could not read the published version", "no fetch"); return null; }
  try {
    const response = await fetch(url, { signal: AbortSignal.timeout(FETCH_TIMEOUT_MS) });
    if (!response.ok) { failOpen("could not read the published version", `HTTP ${response.status}`); return null; }
    return await response.text();
  }
  catch (err) { failOpen("could not read the published version", err); return null; }
}

/**
 * The published version, or null on any failure within the timeout. A failure
 * leaves one fail-open line on stderr, so a silent session is diagnosable.
 */
async function publishedVersion(url) {
  const proxy = declaredProxy(url);
  let body = proxy ? await curlBody(url, proxy) : undefined;
  if (body === undefined) body = await fetchBody(url);
  if (body === null) return null;
  try { return JSON.parse(body).version; }
  catch (err) { failOpen("the published manifest is not JSON", err); return null; }
}

async function main() {
  const input = readStdin();
  if (input === null) return done(null);

  const fs = require("fs");
  const path = require("path");
  const loaded = parseVersion(loadedVersion(fs, path));
  if (!loaded) return done(null);

  const url = process.env.HARNESS_PUBLISHED_MANIFEST_URL || PUBLISHED_MANIFEST_URL;
  const published = parseVersion(await publishedVersion(url));
  if (!published || !isBehind(loaded, published)) return done(null);

  const have = loaded.join(".");
  const want = published.join(".");
  done(
    `[VERSION-DRIFT-GUARD] This session loaded the harness plugin at ${have}, but ${want} ` +
    `is published. The skills, agents and hooks in this session follow the ${have} ` +
    `contract, and a session keeps the version it loaded. In a cloud environment the ` +
    `plugin comes from the environment's setup script, and a cached environment skips ` +
    `that script until it is edited: edit the setup script to rebuild the environment, ` +
    `then start a new session. Locally, update the plugin and restart the session. ` +
    `Say so to the operator before relying on anything the newer version changed.`,
    `harness plugin ${have} is behind the published ${want} — ` +
      `rebuild the cloud environment (edit its setup script) or update the plugin and restart.`
  );
}

/**
 * Deliver the warning, or the host's own empty answer.
 *
 * The model's copy goes inside `hookSpecificOutput`, the position Claude Code
 * honours (#688); `systemMessage` is the line the user sees. The empty case is
 * per host, as for the sibling advisories: Codex's native answer is an empty
 * stdout, Claude Code's a pass-through object.
 */
function done(additionalContext, systemMessage) {
  if (additionalContext) {
    process.stdout.write(JSON.stringify({
      systemMessage,
      hookSpecificOutput: {
        hookEventName: "SessionStart",
        additionalContext,
      },
    }));
    return;
  }
  if (codexRuntime) return;
  process.stdout.write(JSON.stringify({ continue: true }));
}

function crashed(err) {
  failOpen("crashed before it could decide", err);
  if (!codexRuntime) process.stdout.write(JSON.stringify({ continue: true }));
}

// Every hook wraps main() the same way (#303 AC-5). main() is async, so a
// rejection is routed to the same notice as a synchronous throw.
try { main().catch(crashed); } catch (err) {
  failOpen("crashed before it could decide", err);
  if (!codexRuntime) process.stdout.write(JSON.stringify({ continue: true }));
}
