#!/usr/bin/env node
/**
 * The `refs/harness/*` namespace — how concurrent sessions tell each other what
 * they learned, without a service.
 *
 * A verdict binds to a tree, and the integration branch moves while the gate
 * runs. The landing posture (`specs/proposals/lifecycle-reset.md`) takes the
 * exponential out of landing by making the composite gate cover the tree as it
 * would land, and by letting sessions share three small facts through git refs
 * rather than through a lock server, a merge queue, or a CI job these repos do
 * not run:
 *
 *     refs/harness/gate/<tree>-green|-red   the gate's outcome over one tree
 *     refs/harness/claim/<ticket>-<bucket>  who is building a ticket, right now
 *     refs/harness/green/<integration>      the last integration commit known green
 *
 * **Why refs, measured.** Eight probes against a private repository with no
 * server-side configuration (proposal → *Measured*): a custom namespace works
 * (1); a ref may point straight at a **blob**, with no commit wrapper (2); an
 * ordinary `git fetch` never brings them along, so records cannot bloat a clone
 * (3); a second writer racing a create is rejected non-fast-forward, which is
 * first-writer-wins for free (4); `--force-with-lease` is **refused by
 * `hooks/git-push-guard.js`**, which killed the lease-stealing design and is why
 * a claim rotates by time bucket instead (5); a key nested beneath an existing
 * key is a directory/file conflict (6), so **every key here is flat** and a
 * branch name or ticket id carrying a `/` is percent-encoded into one component;
 * one `ls-remote` over the namespace costs about a second and transfers zero
 * objects (7), which is why the outcome lives in the ref *name* and not in a
 * body somebody would have to fetch.
 *
 * **Publishing a record never fails a run.** `scripts/gate-marker.js` states the
 * principle this follows — a gate that can fail for reasons unrelated to the
 * tree is not a gate — so `gate-publish` reports an unreachable remote on stdout
 * and exits zero. The record is a courtesy to the next session; the marker is
 * the authorisation, and it is local. Only a caller error (an oid this
 * repository does not have, a missing declaration) is non-zero.
 *
 * **What this is not.** Coordination, not enforcement. A claim is advisory: it
 * stops two unattended runs building one ticket, and stops nothing else. The
 * push guard and the gate marker are where landing is actually adjudicated.
 *
 * Subcommands:
 *
 *     harness-refs.js gate-publish --tree <oid> --outcome green|red
 *     harness-refs.js gate-list [--json]
 *     harness-refs.js claim --ticket <id>
 *     harness-refs.js green-advance --commit <oid>
 *     harness-refs.js green-read
 *
 * Every subcommand takes an optional `--remote <name>` (default `origin`) and an
 * optional `--repo <dir>` (default the working directory): this file ships from
 * the plugin root and is not materialized into a consumer repo, so it needs a way
 * to name the checkout it is acting on.
 *
 * Node standard library only, CommonJS, for the reasons `scripts/gate-marker.js`
 * records: `scripts/package.json` pins this directory's module type, and a
 * helper the gate path touches may not need a dependency to run.
 */
"use strict";

const path = require("node:path");
const { spawnSync } = require("node:child_process");

//: *A fact about the repository refused the operation* — mirrored from
//: `scripts/gate-marker.js` so a caller reading two of these scripts reads one
//: convention.
const EXIT_REFUSED = 2;

//: *Another writer holds it.* Distinct from a refusal because the caller acts on
//: it differently: a lost claim parks the run, a backwards pointer is ignored,
//: and neither is a bug to report.
const EXIT_CONTENDED = 3;

//: `EX_USAGE` from `sysexits.h`, as the sibling helper uses it.
const EXIT_USAGE = 64;

const NAMESPACE = "refs/harness";

//: How long one claim bucket lasts. A claim is never deleted and never forced —
//: it *expires* by falling out of the current bucket, which is what probe 5 left
//: after the force-push guard refused lease-stealing. An hour is long enough
//: that an ordinary build never loses its own claim mid-run and short enough
//: that a crashed run does not park a ticket for a day.
const DEFAULT_CLAIM_TTL_SECONDS = 3600;
const CLAIM_TTL_ENV = "HARNESS_CLAIM_TTL_SECONDS";

//: How far back a record's tree may sit in the integration branch's history and
//: still be current. Records are a cache with the same standing as the marker
//: directory, not a revived run ledger (ADR 0015).
const DEFAULT_RECORD_WINDOW = 200;
const RECORD_WINDOW_ENV = "HARNESS_RECORD_WINDOW";

//: A full object id, in either hash. `hooks/push-target-guard.js` already accepts
//: both when it validates a recomputed tree, and a namespace that accepted only
//: sha1 would refuse every record and every pointer advance in a repository
//: initialised with `--object-format=sha256` — silently, since a refused publish
//: is by design never an error.
const OID = /^([0-9a-f]{40}|[0-9a-f]{64})$/;
const OUTCOMES = new Set(["green", "red"]);

/** Percent-encode `value` into a single, flat ref component.
 *
 * Probe 6: a key nested beneath an existing key is a directory/file conflict, so
 * `release/1.0` may not become two components. The kept set is deliberately
 * narrow — letters, digits and `_` — because everything a ref name forbids or
 * treats specially (`/`, `.`, `~`, `^`, `:`, `?`, `*`, `[`, `\`, a space, a
 * control character) then encodes by construction rather than by a blacklist
 * somebody has to keep complete. Encoding `.` as well is what makes `..` and a
 * trailing `.lock` unreachable without a second rule.
 */
function encodeKey(value) {
  let out = "";
  for (const ch of String(value)) {
    if (/^[A-Za-z0-9_]$/.test(ch)) {
      out += ch;
      continue;
    }
    for (const byte of Buffer.from(ch, "utf8")) {
      out += `%${byte.toString(16).toUpperCase().padStart(2, "0")}`;
    }
  }
  return out;
}

function git(args, options) {
  const result = spawnSync("git", args, {
    cwd: (options && options.cwd) || process.cwd(),
    encoding: "utf8",
    input: options && options.input,
  });
  if (result.error || result.status === null) {
    return { ok: false, status: 1, stdout: "", stderr: String((result.error || {}).message || "") };
  }
  return {
    ok: result.status === 0,
    status: result.status,
    stdout: String(result.stdout || ""),
    stderr: String(result.stderr || ""),
  };
}

function gitOut(args, cwd) {
  const result = git(args, { cwd });
  return result.ok ? result.stdout.trim() : null;
}

class Refused extends Error {}

function refuse(message) {
  throw new Refused(message);
}

/** The shared configuration reader, required the way the sibling helper does.
 *
 * Unlike the hooks this is not fail-open: a script that cannot read which branch
 * is the integration branch would otherwise publish a green pointer for the
 * wrong one. */
function config() {
  try {
    return require(path.join(__dirname, "harness-config.js"));
  } catch (err) {
    refuse(`the shared configuration reader could not be loaded: ${err && err.message}`);
  }
  return null;
}

function integrationBranch(cwd) {
  const top = gitOut(["rev-parse", "--show-toplevel"], cwd);
  if (top === null) refuse("not inside a git work tree");
  const branches = config().declaredBranches(top);
  const name = branches && branches.integration;
  if (!name) refuse("no `branches.integration` is declared, so there is no branch to record");
  return name;
}

/** The ref the integration branch's history is read from.
 *
 * The remote-tracking ref first: it is what the *other* sessions have seen, and
 * a local branch that has not been pushed is this session's opinion alone. */
function integrationRef(cwd, remote, branch) {
  for (const candidate of [`refs/remotes/${remote}/${branch}`, `refs/heads/${branch}`]) {
    if (gitOut(["rev-parse", "--verify", "--quiet", candidate], cwd)) return candidate;
  }
  return null;
}

function positiveEnv(name, fallback) {
  const raw = process.env[name];
  if (!/^[0-9]+$/.test(String(raw))) return fallback;
  const value = Number.parseInt(raw, 10);
  return value > 0 ? value : fallback;
}

/** Every `refs/harness/<kind>/…` the remote holds, as `{ suffix: oid }`.
 *
 * One `ls-remote`, which is the whole point of putting the outcome in the name
 * (probe 7). A remote that cannot be reached returns null rather than throwing:
 * every caller here treats "could not ask" as "nothing to act on". */
function listNamespace(kind, remote, cwd) {
  const result = git(["ls-remote", remote, `${NAMESPACE}/${kind}/*`], { cwd });
  if (!result.ok) return null;
  const found = new Map();
  for (const line of result.stdout.split("\n")) {
    const [oid, ref] = line.split("\t");
    if (!oid || !ref) continue;
    const prefix = `${NAMESPACE}/${kind}/`;
    if (!ref.startsWith(prefix)) continue;
    found.set(ref.slice(prefix.length), oid.trim());
  }
  return found;
}

/** Write `body` as a blob and return its oid — the record itself (probe 2). */
function writeBlob(body, cwd) {
  const result = git(["hash-object", "-w", "--stdin"], { cwd, input: body });
  if (!result.ok) refuse(`could not write the record blob: ${result.stderr.trim()}`);
  return result.stdout.trim();
}

/** Push `oid` to `ref` **without** a force in any spelling.
 *
 * Probe 4: a second writer racing a create is rejected non-fast-forward, which
 * is first-writer-wins with no lock and no lease. Probe 5: the force-push guard
 * refuses `--force-with-lease`, so there is no lease-stealing fallback to reach
 * for and none is wanted. */
function pushRef(oid, ref, remote, cwd) {
  return git(["push", remote, `${oid}:${ref}`], { cwd });
}

/** Delete records whose tree has left the integration branch's recent history.
 *
 * D5: pruning rides on a write that already happens, so no separate sweep exists
 * to be forgotten. The rule is coherent because a composite tree that *lands*
 * becomes an integration-branch tree — so what ages out is exactly the trees
 * that never landed.
 *
 * Every failure here is swallowed: a prune is housekeeping on somebody else's
 * behalf, and the publish it rides on may not fail for it. */
function pruneGateRecords(remote, cwd, keepTree) {
  const branch = integrationBranch(cwd);
  const ref = integrationRef(cwd, remote, branch);
  if (ref === null) return { pruned: [], reason: `no ref for the integration branch ${branch}` };
  const window = positiveEnv(RECORD_WINDOW_ENV, DEFAULT_RECORD_WINDOW);
  const history = gitOut(["log", "--format=%T", `-n`, String(window), ref], cwd);
  if (history === null) return { pruned: [], reason: "could not read the integration history" };
  const keep = new Set(history.split("\n").filter(Boolean));
  keep.add(keepTree);

  const present = listNamespace("gate", remote, cwd);
  if (present === null) return { pruned: [], reason: "could not list the records" };
  const doomed = [];
  for (const suffix of present.keys()) {
    const tree = suffix.replace(/-(green|red)$/, "");
    if (tree !== suffix && !keep.has(tree)) doomed.push(`${NAMESPACE}/gate/${suffix}`);
  }
  if (doomed.length === 0) return { pruned: [], reason: null };
  const result = git(["push", remote, "--delete", ...doomed], { cwd });
  return { pruned: result.ok ? doomed : [], reason: result.ok ? null : result.stderr.trim() };
}

/** Publish one record and prune the departed ones. Prints nothing.
 *
 * The record body is **deterministic** — the tree and the outcome, no timestamp
 * — so republishing the same outcome for the same tree is the same blob, which
 * git reports as up to date rather than as a rejected update. A record is a
 * statement about bytes, and a statement about bytes has no clock in it.
 */
function publishGateRecord(options, cwd) {
  if (!OID.test(options.tree || "")) refuse("--tree must be a full object id (40 or 64 hex characters)");
  if (!OUTCOMES.has(options.outcome || "")) refuse("--outcome must be `green` or `red`");
  if (gitOut(["cat-file", "-t", options.tree], cwd) !== "tree") {
    refuse(`this repository has no tree object ${options.tree}`);
  }
  const ref = `${NAMESPACE}/gate/${options.tree}-${options.outcome}`;
  const blob = writeBlob(
    `${JSON.stringify({ tree: options.tree, outcome: options.outcome })}\n`,
    cwd
  );
  const pushed = pushRef(blob, ref, options.remote, cwd);
  if (!pushed.ok) {
    // An unreachable remote and a record another session already wrote are the
    // same non-event: the record is a courtesy to the next builder, so nothing
    // here may fail the run that produced the evidence it is sharing.
    return { published: false, ref, pruned: [], reason: pushed.stderr.trim().split("\n").pop() };
  }
  let pruned = { pruned: [], reason: null };
  try {
    pruned = pruneGateRecords(options.remote, cwd, options.tree);
  } catch (err) {
    pruned = { pruned: [], reason: String((err && err.message) || err) };
  }
  return { published: true, ref, pruned: pruned.pruned, reason: pruned.reason };
}

function gatePublish(options, cwd) {
  const result = publishGateRecord(options, cwd);
  if (!result.published) {
    process.stdout.write(`gate record: not published (${result.reason})\n`);
    return 0;
  }
  process.stdout.write(`gate record: ${result.ref}\n`);
  for (const ref of result.pruned) process.stdout.write(`pruned: ${ref}\n`);
  if (result.reason) process.stderr.write(`harness-refs: prune skipped (${result.reason})\n`);
  return 0;
}

function gateList(options, cwd) {
  const found = listNamespace("gate", options.remote, cwd);
  if (found === null) refuse(`could not read ${options.remote}`);
  const records = {};
  for (const suffix of [...found.keys()].sort()) {
    const match = /^([0-9a-f]{40}|[0-9a-f]{64})-(green|red)$/.exec(suffix);
    if (match) records[match[1]] = match[2];
  }
  if (options.json) {
    process.stdout.write(`${JSON.stringify(records)}\n`);
    return 0;
  }
  for (const [tree, outcome] of Object.entries(records)) {
    process.stdout.write(`${tree} ${outcome}\n`);
  }
  return 0;
}

function claim(options, cwd) {
  if (!options.ticket) refuse("--ticket is required");
  const ttl = positiveEnv(CLAIM_TTL_ENV, DEFAULT_CLAIM_TTL_SECONDS);
  //: `--now` names the instant the bucket is computed from. It exists because a
  //: tumbling window has a boundary, and a test that raced two claims against
  //: the wall clock passed or failed on which side of a second they landed —
  //: which is a flake, not a measurement. Safe to expose because a claim is
  //: **advisory coordination, not evidence**: a caller who lies about the time
  //: can only take a claim it could have taken by waiting, or fail to take one.
  //: Nothing that authorises a landing reads it. (ADR 0018's boundary is about
  //: the gate command, and this is not one.)
  const now = options.now === undefined ? Date.now() / 1000 : Number(options.now);
  if (!Number.isFinite(now)) refuse("--now must be an epoch in seconds");
  const bucket = Math.floor(now / ttl);
  const ref = `${NAMESPACE}/claim/${encodeKey(options.ticket)}-${bucket}`;
  const blob = writeBlob(
    `${JSON.stringify({ ticket: options.ticket, bucket, at: new Date().toISOString() })}\n`,
    cwd
  );
  const pushed = pushRef(blob, ref, options.remote, cwd);
  if (pushed.ok) {
    process.stdout.write(`claimed: ${ref}\n`);
    return 0;
  }
  process.stdout.write(`claim lost: ${ref}\n`);
  process.stderr.write(pushed.stderr.trim() ? `${pushed.stderr.trim()}\n` : "");
  return EXIT_CONTENDED;
}

function greenRef(cwd, remote) {
  return `${NAMESPACE}/green/${encodeKey(integrationBranch(cwd))}`;
}

/** Move the green pointer to ``commit``. Prints nothing. */
function advanceGreenPointer(options, cwd) {
  if (!OID.test(options.commit || "")) refuse("--commit must be a full object id (40 or 64 hex characters)");
  if (gitOut(["cat-file", "-t", options.commit], cwd) !== "commit") {
    refuse(`this repository has no commit object ${options.commit}`);
  }
  const ref = greenRef(cwd, options.remote);
  const pushed = pushRef(options.commit, ref, options.remote, cwd);
  // Not forced, ever: a pointer that cannot fast-forward is one another session
  // already advanced past, and overwriting it would name an *older* tree as the
  // last known-good base for every worktree created next.
  return { advanced: pushed.ok, ref, reason: pushed.ok ? null : pushed.stderr.trim() };
}

function greenAdvance(options, cwd) {
  const result = advanceGreenPointer(options, cwd);
  if (result.advanced) {
    process.stdout.write(`${options.commit}\n`);
    return 0;
  }
  process.stderr.write(`harness-refs: the green pointer did not advance: ${result.reason}\n`);
  return EXIT_CONTENDED;
}

function greenRead(options, cwd) {
  const found = listNamespace("green", options.remote, cwd);
  if (found === null) refuse(`could not read ${options.remote}`);
  const suffix = encodeKey(integrationBranch(cwd));
  const oid = found.get(suffix);
  if (!oid) return 0;
  process.stdout.write(`${oid}\n`);
  return 0;
}

function parse(argv) {
  const options = { remote: "origin", json: false };
  for (let i = 0; i < argv.length; i += 1) {
    const token = argv[i];
    if (token === "--json") {
      options.json = true;
      continue;
    }
    const match = /^--(tree|outcome|remote|ticket|commit|repo|now)$/.exec(token);
    if (!match) return null;
    i += 1;
    if (i >= argv.length) return null;
    options[match[1]] = argv[i];
  }
  return options;
}

const VERBS = {
  "gate-publish": gatePublish,
  "gate-list": gateList,
  claim,
  "green-advance": greenAdvance,
  "green-read": greenRead,
};

function usage(message) {
  process.stderr.write(
    `harness-refs: ${message}\n` +
      "usage: harness-refs.js <gate-publish|gate-list|claim|green-advance|green-read> [options]\n"
  );
  return EXIT_USAGE;
}

function main(argv) {
  const verb = argv[0];
  if (!verb || !Object.prototype.hasOwnProperty.call(VERBS, verb)) {
    return usage(verb ? `unknown subcommand ${JSON.stringify(verb)}` : "no subcommand given");
  }
  const options = parse(argv.slice(1));
  if (options === null) return usage("unreadable options");
  try {
    return VERBS[verb](options, options.repo || process.cwd());
  } catch (err) {
    if (err instanceof Refused) {
      process.stderr.write(`harness-refs: ${err.message}\n`);
      return EXIT_REFUSED;
    }
    throw err;
  }
}

if (require.main === module) {
  process.exitCode = main(process.argv.slice(2));
}

/** Publish a green or red record for ``tree``; true iff the remote took it.
 *
 * The in-process entry point `scripts/land.js` uses, so a landing does not spawn
 * a second node to write one ref. Same body as the CLI verb and the same
 * promise: a remote that refused is `false`, never a throw, because a record is
 * a courtesy to the next session and may not fail the run that produced the
 * evidence it is sharing.
 */
function publishGate(options, cwd) {
  try {
    return publishGateRecord(Object.assign({ remote: "origin" }, options), cwd).published;
  } catch (err) {
    process.stderr.write(`harness-refs: ${(err && err.message) || err}\n`);
    return false;
  }
}

/** Advance the green pointer to ``commit``; true iff it moved. */
function advanceGreen(options, cwd) {
  try {
    return advanceGreenPointer(Object.assign({ remote: "origin" }, options), cwd).advanced;
  } catch (err) {
    process.stderr.write(`harness-refs: ${(err && err.message) || err}\n`);
    return false;
  }
}

module.exports = {
  EXIT_REFUSED,
  EXIT_CONTENDED,
  EXIT_USAGE,
  NAMESPACE,
  encodeKey,
  publishGate,
  advanceGreen,
  main,
};
