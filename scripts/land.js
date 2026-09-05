#!/usr/bin/env node
/**
 * The landing decision — the three cases, read from git rather than from prose.
 *
 * A verdict binds to a tree and the integration branch moves while the gate
 * runs. Under the v5 rule every move sent a run back through reconcile, delta
 * review, the gate, the verdict and the push, each opening a new window of the
 * same width: modelled at 7.4 attempts to land at eight pushes an hour. The
 * landing posture keeps the guarantee and drops the exponential by asking, at
 * push time, which of exactly three things happened:
 *
 *   1. the tip has not moved — push;
 *   2. the tip moved and git merged it cleanly — push, because
 *      `hooks/push-target-guard.js` accepts a merge git alone produced over a
 *      gated parent, so nothing is re-run and nothing is re-reviewed;
 *   3. the tip moved and the merge conflicts — the resolution bytes are the only
 *      thing nobody has verified, so re-gate over exactly those and push.
 *
 * **Why a script and not the four paragraphs it retires.** What it replaces was a
 * low-freedom sequence of git invocations written as prose in
 * `skills/build/SKILL.md`: read on every run, costing context every time, and
 * deviable anyway. What stays in the workflow is the part that needs judgment —
 * when it applies, and what to do with each answer.
 *
 * **This script never pushes a branch, and that is not an oversight.** It is
 * invoked as one Bash command, so a branch push it made internally would be
 * invisible to the PreToolUse guard: the landing script would become the way
 * around the guard it exists to satisfy. It decides, it merges, and it *prints*
 * the push for the agent to run through the tool the hook can see. One
 * adjudicator, and it stays the hook.
 *
 * What it does push is `refs/harness/*` and nothing else — `done` publishes a
 * gate record and advances the green pointer. Both live outside `refs/heads/`,
 * neither can move a branch, and nothing reads either as authorisation. So the
 * invariant is *no verb pushes a branch*, and that is what
 * `tests/unit/test_land_script.py` measures over **every** verb. "Never pushes"
 * was the stronger sentence and the weaker guard: it left the one verb that
 * reaches a remote outside the check that named it.
 *
 * **It never runs the gate either.** Law 3 obliges the *agent* to run the gate
 * and read its output; a script that swallowed the run would take the reading
 * with it. `plan` names the scope, the agent runs `gate-marker.js run --scope …`
 * and reads it, `finish` re-checks and hands over the push.
 *
 * Subcommands, each printing exactly one JSON object on stdout:
 *
 *     land.js plan   [--repo <dir>] [--remote <name>] [--branch <name>] [--attempt <n>]
 *     land.js finish [--repo <dir>] [--remote <name>] [--branch <name>] [--attempt <n>]
 *     land.js done   [--repo <dir>] [--remote <name>] [--branch <name>]
 *
 * `decision` is one of `push`, `resolve`, `hold` or `refused`. Exit 0 for a
 * decision the caller can act on, 2 for one it cannot, 3 when the thing that had
 * to run could not, 64 for usage — the vocabulary `scripts/gate-marker.js` fixed
 * and this file does not extend.
 *
 * Node standard library only, CommonJS. Ships from the plugin root and is **not**
 * materialized into a consumer repo: `/harness:init` hydrates `gate-marker.js`
 * and `harness-config.js` as a closed pair because `verify.sh` invokes the marker
 * helper locally, and widening that set is a change to `init`.
 */
"use strict";

const path = require("node:path");
const { spawnSync } = require("node:child_process");

//: The vocabulary `scripts/gate-marker.js` fixed. Reused rather than extended:
//: a caller reading two of these scripts should read one convention.
const EXIT_REFUSED = 2;
const EXIT_UNAVAILABLE = 3;
const EXIT_USAGE = 64;

//: Reconciliation is bounded at two attempts (`skills/build/SKILL.md`): spend
//: both and the ticket is held rather than tried a third time.
const MAX_ATTEMPTS = 2;

//: The delimiter `-z` uses. Written as an escape, never as the byte itself: a
//: literal NUL in source makes git treat the whole file as binary, so the diff
//: a reviewer reads is `Bin 0 -> 14013 bytes` and nothing else.
const NUL = "\u0000";

function git(args, cwd, statuses) {
  const allowed = statuses || [0];
  const result = spawnSync("git", args, { cwd, encoding: "utf8" });
  if (result.error || result.status === null || !allowed.includes(result.status)) {
    return null;
  }
  return String(result.stdout);
}

function line(args, cwd) {
  const out = git(args, cwd);
  return out === null ? null : out.trim();
}

/** A fact about the repository refused the operation — reported as a decision. */
class Refused extends Error {}

/** The thing that had to run could not — infrastructure, never a decision. */
class Unavailable extends Error {}

function config() {
  try {
    return require(path.join(__dirname, "harness-config.js"));
  } catch (err) {
    throw new Unavailable(`the shared configuration reader could not be loaded: ${err.message}`);
  }
}

function refsHelper() {
  try {
    return require(path.join(__dirname, "harness-refs.js"));
  } catch (err) {
    throw new Unavailable(`the ref helper could not be loaded: ${err.message}`);
  }
}

/** The repository, the remote and the branch this landing is about. */
function context(options) {
  const cwd = options.repo || process.cwd();
  const top = line(["rev-parse", "--show-toplevel"], cwd);
  if (top === null) throw new Refused("not inside a git work tree");
  const remote = options.remote || "origin";
  const declared = config().declaredBranches(top);
  const roles = declared ? Object.values(declared) : [];
  const branch = options.branch || (declared && declared.integration);
  if (!branch) {
    throw new Refused(
      "no branch to land on: pass --branch, or declare `branches.integration` in harness.yaml"
    );
  }
  if (options.branch && roles.length && !roles.includes(options.branch)) {
    throw new Refused(
      `${JSON.stringify(options.branch)} is not a branch role this repo declares, so landing on ` +
        "it is not a shape this script decides"
    );
  }
  return { cwd: top, remote, branch };
}

/** Refuse anything that is not a clean checkout on a branch of its own. */
function requireCleanCheckout(cwd) {
  const status = git(["status", "--porcelain=v1", "-z"], cwd);
  if (status === null) throw new Unavailable("git could not report the working tree state");
  if (status !== "") {
    throw new Refused(
      "the working tree is not clean, so the tree that would land is not the tree any " +
        "gate ran over"
    );
  }
  if (line(["symbolic-ref", "--quiet", "HEAD"], cwd) === null) {
    throw new Refused("HEAD is detached, so there is no candidate branch to land");
  }
}

function tipRef(ctx) {
  return `refs/remotes/${ctx.remote}/${ctx.branch}`;
}

/** True when HEAD already contains the tip — case 1, nothing to reconcile. */
function containsTip(ctx) {
  return git(["merge-base", "--is-ancestor", tipRef(ctx), "HEAD"], ctx.cwd) !== null;
}

function conflictedPaths(cwd) {
  const out = git(["diff", "--name-only", "--diff-filter=U", "-z"], cwd);
  return out === null ? [] : out.split(NUL).filter(Boolean);
}

/** Quote one operand for the shell command `plan` prints.
 *
 * The only place in the shipped set that needs this, and there is no sibling copy
 * to share with: `scripts/gate-marker.js` assembles no command *from operands* —
 * the string it hands `sh -c` is the declared scalar verbatim, and the paths go
 * as data on the environment, which is what ADR 0018's amendment records. This
 * file is different because its output *is* a command line, meant for an agent to
 * run through Bash, and its operands are filenames git chose.
 */
function shellQuote(operand) {
  return `'${String(operand).split("'").join(`'\\''`)}'`;
}

function report(payload) {
  process.stdout.write(`${JSON.stringify(payload, null, 2)}\n`);
}

function pushCommand(ctx) {
  return `git push ${ctx.remote} HEAD:${ctx.branch}`;
}

function fetchTip(ctx) {
  if (git(["fetch", "--quiet", ctx.remote, ctx.branch], ctx.cwd) === null) {
    throw new Unavailable(`could not fetch ${ctx.remote}/${ctx.branch}`);
  }
  const tip = line(["rev-parse", "--verify", tipRef(ctx)], ctx.cwd);
  if (tip === null) throw new Refused(`${tipRef(ctx)} does not resolve`);
  return tip;
}

function attemptOf(options) {
  if (options.attempt === undefined) return 1;
  if (!/^[0-9]+$/.test(options.attempt)) throw new Refused("--attempt must be a positive integer");
  const attempt = Number.parseInt(options.attempt, 10);
  if (attempt < 1) throw new Refused("--attempt must be a positive integer");
  return attempt;
}

/** Decide the case, and perform the merge where there is one to perform. */
function plan(options) {
  const ctx = context(options);
  requireCleanCheckout(ctx.cwd);
  const tip = fetchTip(ctx);

  if (containsTip(ctx)) {
    report({
      decision: "push",
      case: "unchanged",
      branch: ctx.branch,
      tip,
      head: line(["rev-parse", "HEAD"], ctx.cwd),
      tree: line(["rev-parse", "HEAD^{tree}"], ctx.cwd),
      push_command: pushCommand(ctx),
    });
    return 0;
  }

  const attempt = attemptOf(options);
  if (attempt > MAX_ATTEMPTS) {
    report({
      decision: "hold",
      case: "attempts",
      branch: ctx.branch,
      tip,
      attempt,
      reason:
        `reconciliation is bounded at ${MAX_ATTEMPTS} attempts; hold the ticket rather than ` +
        "trying a third time",
    });
    return EXIT_REFUSED;
  }

  // Plain `git merge --no-ff`: no `-s`, no `-X`. The guard accepts a merge it can
  // recompute with `merge-tree`, which is always ort — a strategy option produces
  // a tree ort will not reproduce, and every byte of it then reads as authored.
  // That is the honest answer, because nothing verified the side it dropped.
  if (git(["merge", "--no-ff", "--no-edit", tipRef(ctx)], ctx.cwd, [0, 1]) === null) {
    throw new Unavailable("git merge could not run");
  }
  const conflicts = conflictedPaths(ctx.cwd);
  if (conflicts.length === 0) {
    if (git(["status", "--porcelain=v1", "-z"], ctx.cwd) !== "") {
      throw new Refused(
        "the merge neither completed nor conflicted, so this is not a shape this script decides"
      );
    }
    report({
      decision: "push",
      case: "clean-merge",
      branch: ctx.branch,
      tip,
      head: line(["rev-parse", "HEAD"], ctx.cwd),
      tree: line(["rev-parse", "HEAD^{tree}"], ctx.cwd),
      parents: (line(["rev-parse", "HEAD^@"], ctx.cwd) || "").split("\n").filter(Boolean),
      push_command: pushCommand(ctx),
    });
    return 0;
  }
  report({
    decision: "resolve",
    case: "conflict",
    branch: ctx.branch,
    tip,
    attempt,
    conflicts,
    // Quoted, because the workflow hands this string to Bash and the operands
    // are **filenames git chose**. A conflicted path carrying a space already
    // fails closed (the runner's own validation refuses the resulting argv), but
    // one carrying shell syntax would be executed. `scope_argv` is the same list
    // unquoted, for any caller that can spawn a vector instead.
    scope_command: ["node", path.join(__dirname, "gate-marker.js"), "run"]
      .map(shellQuote)
      .concat(conflicts.flatMap((entry) => ["--scope", shellQuote(entry)]))
      .join(" "),
    scope_argv: ["node", path.join(__dirname, "gate-marker.js"), "run"].concat(
      conflicts.flatMap((entry) => ["--scope", entry])
    ),
    next:
      "resolve every path above, commit the merge, run the scoped gate and read its " +
      "output, then `land.js finish`",
  });
  return 0;
}

/** After a resolution and its re-gate: has anything moved again? */
function finish(options) {
  const ctx = context(options);
  requireCleanCheckout(ctx.cwd);
  const tip = fetchTip(ctx);
  const attempt = attemptOf(options);
  if (!containsTip(ctx)) {
    const spent = attempt >= MAX_ATTEMPTS;
    report({
      decision: spent ? "hold" : "resolve",
      case: "tip-moved",
      branch: ctx.branch,
      tip,
      attempt,
      next: spent
        ? `reconciliation is bounded at ${MAX_ATTEMPTS} attempts; hold the ticket`
        : `run \`land.js plan --attempt ${attempt + 1}\``,
    });
    return EXIT_REFUSED;
  }
  report({
    decision: "push",
    case: "regated",
    branch: ctx.branch,
    tip,
    attempt,
    head: line(["rev-parse", "HEAD"], ctx.cwd),
    tree: line(["rev-parse", "HEAD^{tree}"], ctx.cwd),
    push_command: pushCommand(ctx),
  });
  return 0;
}

/** After the push landed: share the outcome, and advance the green pointer.
 *
 * The pointer names the last integration commit known green, so a new worktree
 * branches from a base that was verified rather than from a tip that may be red.
 * It advances on an **uncontended** landing only: where the merge conflicted, the
 * bytes that landed carry a resolution whose only evidence is a scoped gate, and
 * a scoped gate is not the whole-tree claim the pointer makes. And only once the
 * push has actually landed — this verb runs in the same session whose push the
 * guard may have refused.
 */
function done(options) {
  const ctx = context(options);
  const tree = line(["rev-parse", "HEAD^{tree}"], ctx.cwd);
  const head = line(["rev-parse", "HEAD"], ctx.cwd);
  if (tree === null || head === null) throw new Refused("HEAD does not resolve");
  const helper = refsHelper();
  const published = helper.publishGate({ tree, outcome: "green", remote: ctx.remote }, ctx.cwd);
  const parents = (line(["rev-parse", "HEAD^@"], ctx.cwd) || "").split("\n").filter(Boolean);
  let contended = parents.length > 2;
  if (parents.length === 2) {
    // Exit 1 is `merge-tree` reporting that the recomputed merge conflicts, which
    // is the whole question here: a landing whose merge conflicted carried a
    // resolution, and the pointer makes no claim about one. The guard asks a
    // different question of the same command — whether the *pushed tree* is the
    // one git would have produced — and that answer is the authorisation, which
    // is why it is not read here.
    const recomputed = spawnSync("git", ["merge-tree", "--write-tree", parents[0], parents[1]], {
      cwd: ctx.cwd,
      encoding: "utf8",
    });
    contended = recomputed.status !== 0;
  }
  // The pointer may only name a commit the shared branch actually carries.
  // `done` runs in the same session whose push may have been refused, or out of
  // order, and `worktree-isolation` hands this commit to every new worktree as
  // its base — a commit that never landed is not a base anybody can start from.
  const landed =
    git(["fetch", "--quiet", ctx.remote, ctx.branch], ctx.cwd) !== null &&
    git(["merge-base", "--is-ancestor", head, tipRef(ctx)], ctx.cwd) !== null;
  const advanced =
    contended || !landed
      ? false
      : helper.advanceGreen({ commit: head, remote: ctx.remote }, ctx.cwd);
  report({
    decision: "push",
    case: "done",
    branch: ctx.branch,
    tree,
    head,
    record_published: published,
    contended,
    landed,
    green_pointer_advanced: advanced,
  });
  return 0;
}

function parse(argv) {
  const options = {};
  for (let i = 0; i < argv.length; i += 1) {
    const match = /^--(repo|remote|branch|attempt)$/.exec(argv[i]);
    if (!match || argv[i + 1] === undefined) return null;
    options[match[1]] = argv[i + 1];
    i += 1;
  }
  return options;
}

const VERBS = { plan, finish, done };

function usage(message) {
  process.stderr.write(
    `land: ${message}\n` +
      "usage: land.js <plan|finish|done> [--repo <dir>] [--remote <name>] " +
      "[--branch <name>] [--attempt <n>]\n"
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
    return VERBS[verb](options);
  } catch (err) {
    if (err instanceof Refused) {
      report({ decision: "refused", reason: err.message });
      return EXIT_REFUSED;
    }
    if (err instanceof Unavailable) {
      process.stderr.write(`land: ${err.message}\n`);
      return EXIT_UNAVAILABLE;
    }
    throw err;
  }
}

if (require.main === module) {
  process.exitCode = main(process.argv.slice(2));
}

module.exports = { EXIT_REFUSED, EXIT_UNAVAILABLE, EXIT_USAGE, MAX_ATTEMPTS, main };
