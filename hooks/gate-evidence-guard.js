#!/usr/bin/env node
// guidance:hook-gate-evidence-guard@0.2.0
/**
 * Gate-evidence guard (Stop) — #436.
 *
 * Blocks the end of a turn that claims the work is finished when no gate marker
 * covers the worktree current tree. ``scripts/verify.sh`` writes that marker on
 * green, named after the git tree object it verified, so the question this hook
 * asks is not *did someone run a gate lately* but *did the gate exit 0 over
 * these exact bytes*. No later edit can satisfy the second one.
 *
 * **Prose may be the trigger; prose may never be the evidence.** A regex over
 * model output is exactly what this mechanism exists not to depend on, so it is
 * a narrowing filter and nothing more. The evidence half is a content hash and a
 * file. The filter can only fail one way — a reworded claim escapes the nudge —
 * and that is acceptable because the irreversible act is guarded separately and
 * mechanically: to actually land the work the model must push, and
 * ``push-target-guard.js`` refuses that on the command, not on the words. This
 * hook catches the honest agent that forgot; that one catches the agent that did
 * not.
 *
 * A purely state-based trigger (block whenever a task branch has ungated work)
 * was rejected. It false-blocks on every ordinary conversational turn in a task
 * worktree and, worse, on the TDD RED phase — the agent writes a failing test,
 * reports it, and is told to run a gate that cannot go green. That converts a
 * required workflow into a wasted gate run every time, which is how a hook gets
 * uninstalled.
 *
 * **One block, never a wedge.** Honouring ``stop_hook_active`` means this can
 * force exactly one additional turn per stop-chain. That is the ceiling of a
 * Stop hook rather than a shortcoming: one that re-blocked unconditionally would
 * wedge the session forever when the gate is genuinely red and the model cannot
 * fix it. What the design buys is that the instruction and the model response to
 * it are both in the transcript, so a silent omission becomes a recorded refusal.
 *
 * **Fails open on everything it cannot establish.** Where the push guard closes
 * on an incomplete opinion, this one opens, and the reason is recoverability: a
 * push guard that denies on ambiguity costs one command to clear, while a Stop
 * hook that blocks because it could not read git wedges the session in a loop
 * the model has no way to exit. Cheap-to-clear guards fail closed; hard-to-clear
 * ones fail open.
 *
 * **The reason is injected into the model context**, so it is built exclusively
 * from hook-owned constants plus a tree oid and a filesystem path. It never
 * carries the trigger text — neither the payload message nor the transcript:
 * both are model- and user-authored, and echoing one back through the channel
 * added to report on it is how an injection gets a second reading.
 *
 * **The trigger text comes from the payload, not the transcript.** The host sends
 * the turn's message as a top-level ``last_assistant_message``; the transcript
 * does not contain that turn yet when a Stop hook runs, so reading the trigger
 * from there yields the previous turn or nothing at all. See ``triggerText``.
 *
 * **Scope: the worktrees this session worked in** (#439). The payload ``cwd`` is
 * evaluated first and by its existing rules, then the derived candidates. The
 * decision is
 *
 *     block ⟺ ∃ w ∈ (W ∩ S) : ungated(w)
 *
 * where ``W`` is ``git worktree list --porcelain`` for this repository and ``S``
 * is the set of top-level ``cwd`` values this session's transcript records. ``S``
 * is a **selector**, never a source of paths: it can only choose among members of
 * ``W``, so its influence is bounded above by "check every worktree of this repo"
 * and below by "check none" — which was v1's behaviour. Every string that reaches
 * ``spawnSync``, ``currentTree`` or the injected ``reason`` is one git printed;
 * the transcript value is a set-membership key and is then discarded.
 *
 * That is the same rule as ever, not an exception to it: what is read is a
 * host-written structured field on a host-written envelope, per physical line
 * via ``JSON.parse`` and top-level own-property only — never a regex over
 * transcript bytes, never ``tool_input.command``, never message content.
 *
 * v1 stated the opposite limitation, and its grounding was wrong: the payload
 * ``cwd`` is **not** fixed at launch (it tracks the main session's shell across
 * Bash calls, and a sub-agent's ``cd`` never propagates back), so ``/build``
 * driven from the repo root left the guard installed and inert for the shape it
 * exists to catch. Enumerating ``git worktree list`` and blocking on any task
 * worktree with ungated work is still rejected as a **source** of candidates —
 * one stale worktree from a finished ticket would block every future session in
 * the repo. It returns only as a membership filter, and the intersection is what
 * removes the permanence: a stale worktree has to be in *this* session's
 * transcript to be reached at all.
 *
 * **Honest limit.** Evidence plumbing, not an authority. The marker is a file
 * any process with write access can create, and this hook runs in the same trust
 * domain as the agent it checks. The authoritative controls remain server-side
 * branch protection and the gate output in CI.
 */
"use strict";

const fs = require("fs");
const path = require("path");
const { spawnSync } = require("child_process");

const TAG = "[GATE-EVIDENCE-GUARD]";

//: The freshness bound, mirrored from ``scripts/gate_marker.py``. Its purpose is
//: toolchain drift under an unchanged tree, not session scope. The equivalence
//: with the Python parser is measured by ``test_gate_marker_contract.py``.
const MAX_AGE_ENV = "HARNESS_GATE_MARKER_MAX_AGE_SECONDS";
const DEFAULT_MAX_AGE_SECONDS = 86400;

//: Where markers live under the git common directory.
const MARKER_SUBDIR = ["harness", "gate"];

//: Used when a repo declares no branches, matching ``push-target-guard.js``. A
//: session on one of these is not building, so it is never blocked.
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

//: The claim-pattern set. Small, anchored to this process own vocabulary, and
//: applied to the message of **this** turn only — a claim earlier in the
//: conversation is not a claim about this turn. False positives cost one gate
//: run; false negatives cost the nudge, which the push guard backs up.
const CLAIM_PATTERNS = [
  /\bdone\b/i,
  /\bcompleted?\b/i,
  /ready (for review|to ship|to merge)/i,
  /all (the )?tests pass/i,
  /(gate|verification) (is |was )?green/i,
  /\bship(ped|ping)?\b/i,
  /\bPASS\b/,
  /acceptance criteria (are |all )?met/i,
];

//: Recursion is not involved here, but a transcript can be large; only the tail
//: is ever needed, so the scan walks backwards and stops at the first assistant
//: entry it finds.

//: Ceilings on work, not windows on the file. A byte or line window silently
//: narrows the candidate set as sessions grow, and a hook that quietly stopped
//: firing looks exactly like a hook that allows. These count *distinct values*
//: and *tree computations* instead, both sit well above measured reality (largest
//: observed distinct-cwd set: 10; largest observed set of live non-detached
//: same-repo worktrees in one session: 4), and both drop the oldest-visited
//: first, which is the least likely to be the current work.
const MAX_DISTINCT_CWDS = 32;
const MAX_DERIVED_CHECKED = 4;

//: The reported path is git's, but a worktree path is chosen by whoever created
//: the worktree — in an unattended run, the agent. Collapsing whitespace removes
//: the newline-injection shape and the bound keeps the reason readable.
const MAX_REPORTED_PATH = 200;

/**
 * Fail open, loudly. See the identical helper in the other hooks (#303): the
 * approving payload still goes out, but stderr says this hook did not run, so a
 * silently-disarmed guard is distinguishable from a deliberate pass-through. Built
 * from hook-owned constants and `err.message` only — never the payload, which carries
 * transcript text this hook must not repeat. Inlined per hook on purpose: a shared
 * module would be a load-time dependency whose own failure is the class being
 * reported on.
 */
function failOpen(reason, err) {
  const cause = err && err.message ? String(err.message) : String(err || "no detail");
  process.stderr.write(`${TAG} fail-open: ${reason}: ${cause.replace(/\s+/g, " ").slice(0, 200)}\n`);
}

function readStdin() {
  try {
    return JSON.parse(fs.readFileSync(0, "utf8"));
  } catch (err) {
    failOpen("could not parse the hook payload on stdin", err);
    return {};
  }
}

/** Run git in ``dir`` and return its trimmed stdout, or null when git said no.
 *
 * Null covers a ref that does not resolve, a directory that is not a checkout,
 * and a git that could not be spawned. Every one of those leaves this hook with
 * an incomplete opinion, and an incomplete opinion allows. */
function git(dir, args, env) {
  try {
    const res = spawnSync("git", args, {
      cwd: dir,
      encoding: "utf8",
      env: env || process.env,
    });
    if (res.error || res.status !== 0) return null;
    return String(res.stdout).trim();
  } catch (err) {
    // A probe that cannot run leaves the hook without an opinion, and a Stop
    // hook without an opinion allows rather than wedging the session.
    void err;
    return null;
  }
}

/** The freshness bound, or the default. An unusable value reads as *unset*:
 * "never fresh" would block every claim behind a gate run that can never satisfy
 * it, and "always fresh" would disarm the bound. Strict digits only, so this
 * agrees with Python ``int()`` on the degenerate spellings. */
function maxAgeSeconds() {
  const raw = process.env[MAX_AGE_ENV];
  if (!/^[0-9]+$/.test(String(raw))) return DEFAULT_MAX_AGE_SECONDS;
  const value = Number.parseInt(raw, 10);
  return value > 0 ? value : DEFAULT_MAX_AGE_SECONDS;
}

/** The directory holding this repository gate markers, or null. */
function markerDir(cwd) {
  const common = git(cwd, ["rev-parse", "--path-format=absolute", "--git-common-dir"]);
  if (common === null) return null;
  let real = common;
  try {
    real = fs.realpathSync(common);
  } catch (err) {
    // Reported but unresolvable: use it verbatim rather than losing the answer.
    void err;
  }
  return path.join(real, ...MARKER_SUBDIR);
}

/** Where ``tree`` marker lives, or null outside a repository. The **common**
 * directory, so a gate run in a detached gate worktree writes a marker the build
 * worktree can read. */
function markerPath(tree, cwd) {
  const dir = markerDir(cwd);
  return dir === null ? null : path.join(dir, `${tree}.json`);
}

/** True iff a fresh marker for ``tree`` exists in ``cwd`` repository. */
function hasFreshMarker(tree, cwd) {
  const marker = markerPath(tree, cwd);
  if (marker === null) return false;
  try {
    return Date.now() - fs.statSync(marker).mtimeMs < maxAgeSeconds() * 1000;
  } catch (err) {
    // A missing marker is the decision this guard exists to make, not an error.
    void err;
    return false;
  }
}

/** The git tree object of ``cwd`` working tree, including uncommitted work.
 *
 * Computed against a **temporary index** so a Stop hook — which runs on every
 * candidate stop — never stages the session work behind its back. ``git add -A``
 * honours ``.gitignore``, so the gate own log and the venv are excluded exactly
 * as they are excluded from any commit. The scratch index lives beside the
 * markers rather than in TMPDIR: the git directory is guaranteed to exist
 * wherever this can run at all, and the location cannot affect the oid.
 *
 * Mirrors ``scripts/gate_marker.py``; the equivalence is measured by
 * ``test_gate_marker_contract.py``, because drift between the writer tree and
 * the reader tree would be silent and total. */
let scratchIndexSerial = 0;

function currentTree(cwd) {
  const dir = markerDir(cwd);
  if (dir === null) return null;
  try {
    fs.mkdirSync(dir, { recursive: true });
  } catch (err) {
    // Cannot create the scratch home: no opinion, which allows.
    void err;
    return null;
  }
  // The counter, not just pid+ms: this is now called up to five times per
  // process (#439), and two calls inside one millisecond would otherwise name
  // the same scratch index.
  scratchIndexSerial += 1;
  const index = path.join(dir, `.index-${process.pid}-${Date.now()}-${scratchIndexSerial}`);
  const env = Object.assign({}, process.env, { GIT_INDEX_FILE: index });
  try {
    if (git(cwd, ["read-tree", "HEAD"], env) === null) {
      // No commits yet: start from an empty index rather than having no opinion
      // about a repository that simply has no history.
      if (git(cwd, ["read-tree", "--empty"], env) === null) return null;
    }
    if (git(cwd, ["add", "-A"], env) === null) return null;
    return git(cwd, ["write-tree"], env);
  } finally {
    try {
      fs.unlinkSync(index);
    } catch (err) {
      // Best-effort cleanup of a scratch index; a leftover is pruned with the
      // markers and is never read by anything.
      void err;
    }
  }
}

/** Strip a matching pair of surrounding quotes. Written without quote
 * characters inside a regex on purpose — the repo hook source scanners blank
 * string literals to count braces, and a lone quote inside a pattern throws
 * their offsets off. */
function stripQuotes(value) {
  const quotes = "\"'";
  if (value.length >= 2 && quotes.includes(value[0]) && value[0] === value[value.length - 1]) {
    return value.slice(1, -1);
  }
  return value;
}

/** A yaml scalar with its inline comment and quotes removed. */
function scalar(raw) {
  const hash = raw.indexOf("#");
  return stripQuotes((hash === -1 ? raw : raw.slice(0, hash)).trim());
}

/** The ``branches:`` map declared in a repo CONTEXT.md, as plain key/value.
 *
 * A small line parser, the same shape ``guidance-freshness.js`` already uses for
 * ``registry.yaml``: the file is markdown with a fenced yaml block, so a real
 * yaml load would need a dependency this surface does not have. */
function declaredBranches(contextFile) {
  let text;
  try {
    text = fs.readFileSync(contextFile, "utf8");
  } catch (err) {
    // No CONTEXT.md is the ordinary case in a repo that has not adopted the
    // guidance; the conservative fallback applies and that is not an error.
    void err;
    return {};
  }
  const found = {};
  let indent = -1;
  for (const raw of text.split("\n")) {
    const line = raw.replace(/\t/g, "  ");
    const lead = line.length - line.trimStart().length;
    if (indent === -1) {
      if (/^branches:\s*$/.test(line.trim())) indent = lead;
      continue;
    }
    if (!line.trim()) continue;
    if (lead <= indent) break; // the block ended
    const match = /^\s*([A-Za-z_][A-Za-z0-9_-]*)\s*:\s*(.*)$/.exec(line);
    if (!match) continue;
    const value = scalar(match[2]);
    if (value) found[match[1]] = value;
  }
  return found;
}

/** A ref name reduced to its branch name. */
function branchName(ref) {
  return ref.replace(/^refs\/heads\//, "").replace(/^refs\/remotes\/[^/]+\//, "");
}

/** The branches whose sessions are not builds, resolved in ``cwd``. */
function protectedBranches(declared, cwd) {
  const names = Object.values(declared);
  const set = new Set((names.length ? names : FALLBACK_PROTECTED).map(branchName));
  const remoteHead = git(cwd, ["symbolic-ref", "refs/remotes/origin/HEAD"]);
  if (remoteHead) set.add(branchName(remoteHead));
  return set;
}

/** The text of a transcript content field, which the host spells two ways. */
function textOf(content) {
  if (typeof content === "string") return content;
  if (!Array.isArray(content)) return "";
  return content
    .filter((block) => block && typeof block.text === "string")
    .map((block) => block.text)
    .join("\n");
}

/** The last assistant message in a JSONL transcript, or null.
 *
 * Null means the trigger cannot be established — a missing, unreadable or
 * assistant-less transcript — which allows. Walks backwards and stops at the
 * first assistant entry, so a long transcript costs one pass over its tail. */
function lastAssistantText(transcriptPath) {
  if (!transcriptPath) return null;
  let raw;
  try {
    raw = fs.readFileSync(transcriptPath, "utf8");
  } catch (err) {
    // A rotated or compacted transcript is ordinary; the hook simply has no
    // trigger to read and allows.
    void err;
    return null;
  }
  const lines = raw.split("\n");
  for (let i = lines.length - 1; i >= 0; i--) {
    const line = lines[i].trim();
    if (!line) continue;
    let entry;
    try {
      entry = JSON.parse(line);
    } catch (err) {
      // A transcript being written concurrently ends in a partial line. Skip it
      // rather than treating the whole file as unreadable.
      void err;
      continue;
    }
    const message = entry && entry.message;
    const role = (message && message.role) || (entry && entry.type);
    if (role !== "assistant") continue;
    return textOf(message && message.content);
  }
  return null;
}

/** The text of the turn being stopped, or null when it cannot be established.
 *
 * The host hands it over directly, as the top-level ``last_assistant_message``,
 * and that is the only source that works. **At Stop time the transcript does not
 * yet contain the turn being stopped** — the host appends the assistant message
 * to the JSONL after the hook returns. Measured live against Claude Code 2.1.220
 * with a snapshot hook that copied the transcript at the instant this one ran:
 * zero assistant entries. A trigger read from there reads the *previous* turn, or
 * nothing at all, so it can never fire on the claim it exists to catch.
 *
 * ``lastAssistantText`` stays behind it as a fallback rather than being deleted:
 * a host that sends no such field still has a transcript, and that read is proven
 * against that shape. What it may no longer be is the primary source.
 *
 * A present-but-empty field counts as absent — a field the host declared and did
 * not fill is not a statement that the turn said nothing. A present field that
 * simply does not *match* is the answer, though, not a reason to go looking in
 * the previous turn: falling back there would resurrect a stale claim and block
 * an ordinary turn that followed one. */
function triggerText(input) {
  const direct = input && input.last_assistant_message;
  if (typeof direct === "string" && direct !== "") return direct;
  return lastAssistantText(input && input.transcript_path);
}

/** True iff ``text`` reads as a claim that the work is finished. */
function claimsCompletion(text) {
  return typeof text === "string" && CLAIM_PATTERNS.some((pattern) => pattern.test(text));
}

/** True iff this session has produced something a completion claim would cover:
 * uncommitted work, or commits ahead of the integration branch. */
function hasWorkToClaim(cwd, tree, declared) {
  const headTree = git(cwd, ["rev-parse", "HEAD^{tree}"]);
  if (headTree === null || headTree !== tree) return true;
  const integration = declared.integration;
  if (!integration) return false;
  const head = git(cwd, ["rev-parse", "HEAD"]);
  const tip = git(cwd, ["rev-parse", `refs/heads/${integration}`]);
  if (head === null || tip === null) return false;
  return head !== tip;
}

/** ``dir`` resolved through symlinks, or null when it does not resolve.
 *
 * macOS spells the same directory two ways (``/tmp`` and ``/private/tmp``), and
 * both spellings appear in real transcripts, so every path on both sides of the
 * membership test is normalized before it is compared. A path that does not
 * resolve is a deleted directory, which is a fact rather than an error. */
function resolved(dir) {
  try {
    return fs.realpathSync(dir);
  } catch (err) {
    // A directory that is gone cannot be a candidate and cannot be a worktree.
    void err;
    return null;
  }
}

/** Every worktree of ``dir``'s repository, from ``git worktree list --porcelain``.
 *
 * One spawn, and it answers four questions at once that a per-candidate probe
 * would need four of: is this directory a worktree of *this* repository, what is
 * its root (so a cwd inside it normalizes), what branch is it on, and is it
 * detached or stale. Git failing yields ``[]`` — an incomplete opinion allows.
 *
 * Porcelain is blank-line-delimited blocks: ``worktree <path>``, ``HEAD <oid>``,
 * ``branch refs/heads/<name>``, plus bare or key-value attribute lines. */
function worktreesOf(dir) {
  const out = git(dir, ["worktree", "list", "--porcelain"]);
  if (out === null) return [];
  const found = [];
  let current = null;
  for (const raw of out.split("\n")) {
    const line = raw.trim();
    if (line.startsWith("worktree ")) {
      current = {
        path: line.slice("worktree ".length),
        branch: null,
        detached: false,
        bare: false,
        prunable: false,
      };
      found.push(current);
      continue;
    }
    if (current === null) continue;
    if (line.startsWith("branch ")) current.branch = branchName(line.slice("branch ".length));
    else if (line === "detached") current.detached = true;
    else if (line === "bare") current.bare = true;
    else if (line.startsWith("prunable")) current.prunable = true;
  }
  const live = [];
  for (const worktree of found) {
    const real = resolved(worktree.path);
    if (real === null) continue; // the directory is gone; git prints it prunable
    worktree.path = real;
    live.push(worktree);
  }
  return live;
}

/** The distinct top-level ``cwd`` values in a transcript, most-recent first.
 *
 * **The only thing read out of the transcript, and it is read structurally.**
 * Each *physical line* is parsed with ``JSON.parse`` and only the resulting
 * object's own top-level ``cwd`` is taken, and only when it is a non-empty
 * string. A tool result's text is a JSON string value nested under
 * ``message.content``; JSON escapes newlines, so untrusted content cannot
 * introduce a physical line of its own and therefore cannot present a top-level
 * key. A regex over the file's bytes would have neither property.
 *
 * Walks backwards and stops at ``MAX_DISTINCT_CWDS`` distinct values, so the
 * values it drops are the oldest-visited. A missing, rotated or compacted
 * transcript yields ``[]``, which is v1's behaviour. */
function sessionCwds(transcriptPath) {
  if (!transcriptPath) return [];
  let raw;
  try {
    raw = fs.readFileSync(transcriptPath, "utf8");
  } catch (err) {
    // No transcript is ordinary; there is simply nothing to select with.
    void err;
    return [];
  }
  const lines = raw.split("\n");
  const seen = new Set();
  const found = [];
  for (let i = lines.length - 1; i >= 0 && found.length < MAX_DISTINCT_CWDS; i--) {
    const line = lines[i].trim();
    if (!line) continue;
    let entry;
    try {
      entry = JSON.parse(line);
    } catch (err) {
      // A transcript being written concurrently ends in a partial line, and a
      // line this hook cannot parse is a line it has no opinion about.
      void err;
      continue;
    }
    if (entry === null || typeof entry !== "object" || Array.isArray(entry)) continue;
    if (!Object.prototype.hasOwnProperty.call(entry, "cwd")) continue;
    const value = entry.cwd;
    if (typeof value !== "string" || value === "") continue;
    if (seen.has(value)) continue;
    seen.add(value);
    found.push(value);
  }
  return found;
}

/** The **longest** worktree in ``universe`` that contains ``dir``, or null.
 *
 * Longest, not first, and that is load-bearing: this repo's worktrees live at
 * ``<root>/.worktrees/<id>``, *inside* the root worktree's path. A first match
 * maps every one of them to the root, the root is skipped as protected, and the
 * hook is silently inert in its own default layout. */
function containingWorktree(dir, universe) {
  let best = null;
  for (const worktree of universe) {
    if (dir !== worktree.path && !dir.startsWith(worktree.path + path.sep)) continue;
    if (best === null || worktree.path.length > best.path.length) best = worktree;
  }
  return best;
}

/** The directories to ask about, in order, lazily.
 *
 * The payload ``cwd`` is always first and always evaluated, which preserves v1
 * exactly — when the session is inside the build worktree, nothing else is
 * consulted and no #436 test changes meaning. Derived candidates follow in
 * most-recently-visited order, and only when the first did not block, so the
 * transcript is not even read on the ordinary path.
 *
 * The detached and protected-branch filters here apply to derived candidates
 * only. The payload ``cwd`` keeps its existing rules: it is where the session
 * *is* — a directory it chose and can act in — while a derived candidate is a
 * place it *visited*, and a ``--detach`` checkout is an artifact of the gate that
 * nobody claims work in. Filtering at admission rather than in ``verdictFor``
 * also keeps a skipped worktree from spending the ``MAX_DERIVED_CHECKED``
 * budget on a directory that could never block. */
function* candidates(input, sessionCwd) {
  yield { dir: sessionCwd, derived: false };

  let anchor = null;
  if (git(sessionCwd, ["rev-parse", "--is-inside-work-tree"]) === "true") anchor = sessionCwd;
  else if (process.env.CLAUDE_PROJECT_DIR) anchor = process.env.CLAUDE_PROJECT_DIR;
  if (anchor === null) return; // no anchor, so no notion of "this repository"

  const universe = worktreesOf(anchor);
  if (universe.length === 0) return;

  const top = git(sessionCwd, ["rev-parse", "--show-toplevel"]);
  const sessionTop = top === null ? null : resolved(top) || top;
  const declared = sessionTop === null ? {} : declaredBranches(path.join(sessionTop, "CONTEXT.md"));
  const skip = protectedBranches(declared, anchor);

  let checked = 0;
  const yielded = new Set();
  for (const value of sessionCwds(input && input.transcript_path)) {
    if (checked >= MAX_DERIVED_CHECKED) return;
    const real = resolved(value);
    if (real === null) continue;
    const worktree = containingWorktree(real, universe);
    if (worktree === null) continue; // not a worktree of this repository
    if (worktree.bare || worktree.prunable || worktree.detached) continue;
    if (worktree.branch !== null && skip.has(worktree.branch)) continue;
    if (worktree.path === sessionTop) continue; // already evaluated, as the cwd
    if (yielded.has(worktree.path)) continue;
    yielded.add(worktree.path);
    checked += 1;
    yield { dir: worktree.path, derived: true };
  }
}

/** The tree and marker path a block would be about, or null for *no opinion*.
 *
 * A behaviour-preserving extraction of v1's sequence — ``currentTree`` →
 * protected-branch skip → ``hasWorkToClaim`` → ``hasFreshMarker`` — so that one
 * question can be asked of more than one directory. */
function verdictFor(dir) {
  const tree = currentTree(dir);
  if (tree === null) return null; // not a worktree, or git had no answer

  const top = git(dir, ["rev-parse", "--show-toplevel"]);
  const declared = top === null ? {} : declaredBranches(path.join(top, "CONTEXT.md"));
  const branch = git(dir, ["rev-parse", "--abbrev-ref", "HEAD"]);
  if (branch !== null && protectedBranches(declared, dir).has(branch)) return null;

  if (!hasWorkToClaim(dir, tree, declared)) return null;
  if (hasFreshMarker(tree, dir)) return null;
  return { tree, marker: markerPath(tree, dir) };
}

/** A path made safe to inject. Whitespace-collapsed and bounded, the existing
 * ``failOpen`` idiom, because ``reason`` is written straight into the model's
 * context. */
function reportable(value) {
  return String(value).replace(/\s+/g, " ").slice(0, MAX_REPORTED_PATH);
}

function block(reason) {
  process.stdout.write(JSON.stringify({ decision: "block", reason: `${TAG} ${reason}` }));
}

function allow() {
  process.stdout.write(JSON.stringify({ continue: true }));
}

function main() {
  const input = readStdin();
  const sessionCwd = input.cwd || process.cwd() || process.env.CLAUDE_PROJECT_DIR;

  const claim = triggerText(input);
  if (!claimsCompletion(claim)) return allow();

  for (const candidate of candidates(input, sessionCwd)) {
    const verdict = verdictFor(candidate.dir);
    if (verdict === null) continue;

    if (input.stop_hook_active === true) {
      // The platform re-entry flag, checked *after* a candidate qualifies so the
      // notice still names the tree it would have blocked on. Exactly one
      // additional turn per stop-chain is the ceiling of a Stop hook — scanning
      // several worktrees does not raise it — and re-blocking would wedge a
      // session whose gate is genuinely red.
      process.stderr.write(
        `${TAG} not re-blocking: no gate marker covers tree ${verdict.tree.slice(0, 12)}, ` +
          "but stop_hook_active is set and one block per stop-chain is the ceiling.\n"
      );
      return allow();
    }

    // Everything interpolated below is hook-owned constants, a tree oid, and a
    // path git printed — never the transcript string that selected it.
    const where = reportable(candidate.dir);
    const scope = candidate.derived
      ? `That directory is a worktree this session worked in rather than the ` +
        `current directory. `
      : "";
    return block(
      `This turn claims the work is finished, but no gate marker covers the current ` +
        `tree ${verdict.tree.slice(0, 12)} in ${where}. ${scope}The gate has not been ` +
        `run green over these exact bytes — a marker from before the last edit is not ` +
        `evidence about them. Run the repo verify command (CONTEXT.md commands.verify) ` +
        `in ${where}, read its output, and name the test that proves each acceptance ` +
        `criterion; then say you are done. Expected marker: ${reportable(verdict.marker)}. ` +
        `If the gate is red and you cannot fix it, say so plainly instead of claiming ` +
        `completion.`
    );
  }
  return allow();
}

if (require.main === module) {
  try {
    main();
  } catch (err) {
    // The hook could not run, so it has no opinion. Allow, but loudly — a
    // disarmed enforcement hook must not look like a clean pass.
    failOpen("crashed before it could decide", err);
    process.stdout.write(JSON.stringify({ continue: true }));
  }
}

// Exported so ``test_gate_marker_contract.py`` can execute this hook copy of the
// contract against the Python writer. The tree is computed in two languages and
// the path in three, which is exactly the shape that drifts silently; an
// equivalence test that runs all of them is what catches it. The
// ``require.main === module`` guard above means importing for that introspection
// never runs the hook.
module.exports = { markerPath, maxAgeSeconds, currentTree, CLAIM_PATTERNS };
