#!/usr/bin/env node
/**
 * The plugin's one version, raised once per release cycle, by the build that
 * starts the cycle.
 *
 * `claude plugins update` compares the manifest **version string** and nothing
 * else — the `gitCommitSha` it records is never consulted for a plugin whose
 * manifest declares a version. So a cycle that ships content at the released
 * version does not under-report: it delivers nothing, and the consumer is told
 * it is already current. That happened on 2026-09-05 (`a609d5b`). #556 gave the
 * bump to the builder and enforced it with a 713-line guard; #588 deleted both,
 * on a plan to bump at the release hop that could not work — a commit written
 * with `GITHUB_TOKEN` raises no workflow run, so the bumped head would carry no
 * required check and the nightly would wedge permanently. The bump was left with
 * no owner. This is the owner.
 *
 * `/build` step 1 runs it in the new worktree, **before the first edit of the
 * change it is about to build**. Three consequences, and each is why some other
 * home was rejected:
 *
 *   - The raise lands inside the tree the gate certifies and the reviewer reads,
 *     so law 3 covers it and no second commit follows the verdict. That is why
 *     it is not in the landing step, which mutates no content file and must not
 *     start: the gate's evidence is green over exactly the bytes it ran on, so a
 *     content edit after it invalidates the run that licensed the push (law 3).
 *   - It happens without anyone remembering, which is why it is not a sentence
 *     in a spine.
 *   - It *does the job* rather than detecting that nobody did it, which is why
 *     there is no gate stage asserting the version relation. That guard existed,
 *     ran 713 lines, skipped on every `push: dev` because a bare checkout could
 *     not resolve the ref it needed, and then failed the one promotion it did
 *     run on (#580, run 34046398127). A mechanism where a number would do (P0).
 *
 * **The level is minor, and this script never decides otherwise.** The
 * compatibility grammar carried a `patch` level — "wording only, no behaviour
 * change" — from before ADR 0015: with a runtime, a reworded skill body changed
 * nothing a consumer executed. The runtime is gone and the shipped product is
 * prose, so a reworded body *is* a behaviour change, and #590 retired the
 * level. A raise above the floor is a judgment about the whole diff,
 * available only at review time
 * (`skills/review-discipline/references/certifying.md`), and is a hand edit to
 * the homes inside the candidate. A `--level` flag would invite a guess at step
 * 1, which is why there is not one.
 *
 * **What a home is, and why membership is earned rather than assumed.** `/build`
 * step 1 is shipped guidance: calibrate, nano-erp and lab-book run it too, and
 * each carries an `AGENTS.md` `spine:generated` marker naming the harness
 * version that hydrated it. A writer that raised every marker it found would
 * rewrite three repos' record of which guidance they are running, silently, on
 * their next build. So membership is **positive identification, never absence**:
 *
 *     This assumes a plugin source shaped like ours: one manifest at
 *     `.claude-plugin/plugin.json` naming the plugin, and any `spine:generated`
 *     marker naming that same plugin is one of its version homes. A repo that
 *     publishes a plugin by another route is outside the set, and stays outside
 *     by not carrying that manifest.
 *
 * A repo authoring its own plugin gets its own manifest raised and its
 * `harness@x.y.z` marker left alone — the mechanism generalising correctly, not
 * a leak.
 *
 * **A declared release ref that will not resolve refuses.** The two exit-0
 * no-ops — `no-plugin-manifest` and `no-release-branch` — are the cases where
 * the obligation *cannot exist*, not cases where it applies and was waived, and
 * both print a payload rather than falling silent. That is the whole difference
 * from the `NO_RELEASE_REF` skip this replaces.
 *
 * Usage, printing exactly one JSON object on stdout:
 *
 *     plugin-version.js [--repo <dir>] [--remote <name>]
 *
 * `case` is the machine token and `reason` is a sentence.
 * Exit 0 for an answer the caller can act on, 2 for a refusal, 3 when the thing
 * that had to run could not, 64 for usage — the vocabulary the retired marker
 * fixed and this file does not extend.
 *
 * Node standard library only, CommonJS. Ships from the plugin root and is **not**
 * materialized into a consumer repo, so the checkout it edits is named with
 * `--repo` rather than inferred from where this file sits.
 */
"use strict";

const fs = require("fs");
const path = require("path");
const { spawnSync } = require("child_process");

const EXIT_REFUSED = 2;
const EXIT_UNAVAILABLE = 3;
const EXIT_USAGE = 64;

//: The updater-facing manifest, and the file whose presence says "this repo is a
//: plugin source". Absence is the consumer-repo answer, not a fault.
const CLAUDE_MANIFEST = ".claude-plugin/plugin.json";

//: The candidate homes, in the order a payload reports them. Each is a *candidate*
//: — a file becomes a home only by naming the plugin the manifest above names.
//:
//: `CLAUDE.md` sits beside `AGENTS.md` because #558 made it the whole of the spine
//: copied verbatim — marker included — rather than an `@AGENTS.md` pointer. The
//: two files are held byte-equal over the copied region by
//: `tests/unit/test_spine_template_parity.py`, and the version line is the one
//: line every raise touches, so a bump that skipped the copy would red the gate on
//: the cycle's very next build. It earns membership the same way every other
//: marker does: a pre-#558 pointer carries no marker and is skipped, and a repo
//: with no `CLAUDE.md` has one fewer home rather than a missing one.
const CANDIDATES = [
  { path: CLAUDE_MANIFEST, kind: "manifest" },
  { path: ".codex-plugin/plugin.json", kind: "manifest" },
  { path: "AGENTS.md", kind: "marker" },
  { path: "CLAUDE.md", kind: "marker" },
  { path: "templates/spine.md", kind: "marker" },
];

//: `X.Y.Z`, digits only, no leading zeros — the same shape
//: `tests/unit/test_spine_template_parity.py` already refuses everything outside
//: of. A prerelease would need SemVer §11 precedence (a prerelease sorts *below*
//: its release) to order correctly, and an ordering nobody specified writes a
//: wrong version silently. A narrow grammar that refuses is honest; a wide one
//: that guesses is not.
const SEMVER = /^(?:0|[1-9]\d*)(?:\.(?:0|[1-9]\d*)){2}$/;

//: The one `"version": "…"` site in a manifest. Collected over the whole file and
//: required to be unique: a future manifest carrying a nested `version` refuses
//: loudly rather than having its first hit silently rewritten.
const MANIFEST_SITE = /("version"\s*:\s*")([^"]*)(")/g;

//: The generated marker, with `test_spine_template_parity.py`'s `_BEGIN` spelling
//: and its literal `harness` generalised to a capture. Structurally identical
//: otherwise — line-anchored with indent and trailing-whitespace tolerance, and
//: `\s` between the tokens — so no marker that guard can see is invisible to this
//: writer (#484, #487: a parser must accept every legal spelling its subject
//: already contains). Line anchoring is the counterfeited-delimiter remedy, and
//: the shape it defends against is a **whole marker quoted mid-sentence** —
//: `tests/unit/test_spine_template_parity.py:121` carries one today, and a home is one
//: sentence away from carrying one. Unanchored, that quotation is a second site
//: and the home refuses as `home-unwritable` rather than raising at all. The bare
//: word `spine:generated` at `AGENTS.md:3` is *not* the threat: it carries no
//: `<!--`, so no pattern here could match it anchored or not. That distinction
//: was a false mechanism claim in this comment until a surviving mutant found it.
//:
//: Group 1 is everything up to and including the `@`, so the version's span is
//: `m.index + m[1].length` for `m[3].length` bytes. Only that span is replaced —
//: interior spacing, the marker's own name and the line's whitespace all survive
//: byte for byte.
const MARKER_SITE =
  /^([ \t]*<!--\s*spine:generated:begin\s+([^\s@>]+)@)([^\s>]+)(\s*-->[ \t]*)$/gm;

/** A fact about the repository refused the operation — reported as a payload. */
class Refusal extends Error {
  constructor(payload) {
    super(String(payload.reason || payload.case));
    this.payload = payload;
  }
}

/** The thing that had to run could not — infrastructure, never a decision. */
class Unavailable extends Error {}

function git(args, cwd, allowFailure) {
  const result = spawnSync("git", args, { cwd, encoding: "utf8" });
  if (result.error) {
    throw new Unavailable(`git could not be run: ${result.error.message}`);
  }
  if (result.status !== 0) {
    if (allowFailure) return null;
    throw new Unavailable(
      `git ${args[0]} failed (${result.status}): ${String(result.stderr).trim()}`
    );
  }
  return String(result.stdout);
}

function config() {
  try {
    return require(path.join(__dirname, "harness-config.js"));
  } catch (err) {
    throw new Unavailable(
      `the shared configuration reader could not be loaded: ${err.message}`
    );
  }
}

function report(payload) {
  process.stdout.write(`${JSON.stringify(payload, null, 2)}\n`);
}

/** `[major, minor, patch]`, or `null` where the string is outside the grammar. */
function parseVersion(text) {
  if (!SEMVER.test(text)) return null;
  return text.split(".").map((part) => Number.parseInt(part, 10));
}

//: Element-wise on integers, never as strings — the reader's own `queueSettings`
//: records why ("10" sorts below "6").
function compare(left, right) {
  for (let i = 0; i < 3; i += 1) {
    if (left[i] !== right[i]) return left[i] < right[i] ? -1 : 1;
  }
  return 0;
}

//: Patch is zeroed, not carried: `8.0.7` becomes `8.1.0`. `minor + 1` alone is
//: the natural wrong write, and it has a test of its own.
function raised([major, minor]) {
  return `${major}.${minor + 1}.0`;
}

/** Every site a candidate carries: the plugin it names, and the version's span. */
function sites(text, kind) {
  const pattern = kind === "manifest" ? MANIFEST_SITE : MARKER_SITE;
  pattern.lastIndex = 0;
  const found = [];
  let match = pattern.exec(text);
  while (match !== null) {
    found.push({
      name: kind === "manifest" ? null : match[2],
      version: kind === "manifest" ? match[2] : match[3],
      start: match.index + match[1].length,
    });
    match = pattern.exec(text);
  }
  return found;
}

/** The plugin a manifest names, read as JSON — parse to read, substring to write. */
function manifestName(text, home) {
  try {
    return JSON.parse(text).name;
  } catch (err) {
    throw new Refusal({
      bumped: false,
      case: "home-unreadable",
      home,
      reason: `${home} is not readable as JSON: ${err.message}`,
    });
  }
}

/**
 * The homes this repo actually carries, each with its version and the span to
 * rewrite — validated before anything is written, so a refusal never leaves a
 * partial write behind.
 */
function readHomes(top, plugin) {
  const homes = [];
  for (const candidate of CANDIDATES) {
    const absolute = path.join(top, candidate.path);
    if (!fs.existsSync(absolute)) continue;
    let text;
    try {
      text = fs.readFileSync(absolute, "utf8");
    } catch (err) {
      throw new Unavailable(`${candidate.path} could not be read: ${err.message}`);
    }

    //: Membership, earned. A manifest belongs when it names this plugin; a marker
    //: belongs when the name it carries does. Everything else is another repo's
    //: file that happens to share a shape.
    if (candidate.kind === "manifest" && manifestName(text, candidate.path) !== plugin) {
      continue;
    }
    const found = sites(text, candidate.kind).filter(
      (site) => candidate.kind === "manifest" || site.name === plugin
    );
    if (candidate.kind === "marker" && found.length === 0) continue;

    if (found.length !== 1) {
      throw new Refusal({
        bumped: false,
        case: "home-unwritable",
        home: candidate.path,
        found: found.length,
        reason:
          `${candidate.path} carries ${found.length} version sites, so there is ` +
          "no single one to rewrite",
      });
    }
    const site = found[0];
    if (parseVersion(site.version) === null) {
      throw new Refusal({
        bumped: false,
        case: "unreadable-version",
        home: candidate.path,
        carried: site.version,
        reason:
          `${candidate.path} carries ${JSON.stringify(site.version)}, which is not ` +
          "X.Y.Z with no leading zeros",
      });
    }
    homes.push({ ...candidate, absolute, text, ...site });
  }
  return homes;
}

/** One version across every home, or a refusal naming what each carries. */
function agreedVersion(homes) {
  const carried = {};
  for (const home of homes) carried[home.path] = home.version;
  const distinct = new Set(Object.values(carried));
  if (distinct.size !== 1) {
    throw new Refusal({
      bumped: false,
      case: "homes-disagree",
      carried,
      reason:
        "the version homes do not agree, so there is no single version to raise " +
        "— most likely a prior run that wrote some homes and not others",
    });
  }
  return homes[0].version;
}

/** The release branch's commit and declared version. */
function readRelease(top, remote, branch) {
  //: The whole remote, not `<remote> <branch>`: a refspec naming a branch the
  //: remote does not carry makes `git fetch` itself fail, which would report an
  //: infrastructure fault for what is really a resolvable question about a ref.
  //: Fetching the remote separates the two — a failure here is the network or the
  //: remote, and a ref that is still missing afterwards is the refusal below.
  git(["fetch", "--quiet", remote], top);
  const ref = `refs/remotes/${remote}/${branch}`;
  const commit = git(["rev-parse", "--verify", "--quiet", `${ref}^{commit}`], top, true);
  if (commit === null) {
    throw new Refusal({
      bumped: false,
      case: "release-unresolvable",
      ref,
      reason:
        `${ref} does not resolve after fetching ${remote}, so the released ` +
        "version cannot be read — the release role is declared in harness.yaml",
    });
  }
  //: No fallback to a local `refs/heads/<branch>`. The operand has to be what a
  //: consumer can pull; a local release branch in a build worktree is routinely
  //: absent or stale, and a quiet degradation to it is how a wrong version ships.
  const text = git(["show", `${ref}:${CLAUDE_MANIFEST}`], top, true);
  let version = null;
  if (text !== null) {
    try {
      version = JSON.parse(text).version;
    } catch (err) {
      version = null;
    }
  }
  if (typeof version !== "string") {
    throw new Refusal({
      bumped: false,
      case: "release-manifest-unreadable",
      ref,
      reason: `${ref}:${CLAUDE_MANIFEST} is absent, unparseable, or declares no version`,
    });
  }
  if (parseVersion(version) === null) {
    throw new Refusal({
      bumped: false,
      case: "unreadable-version",
      home: `${ref}:${CLAUDE_MANIFEST}`,
      carried: version,
      reason:
        `the release branch carries ${JSON.stringify(version)}, which is not ` +
        "X.Y.Z with no leading zeros",
    });
  }
  return { ref, commit: commit.trim(), version };
}

function write(homes, next) {
  for (const home of homes) {
    const patched =
      home.text.slice(0, home.start) +
      next +
      home.text.slice(home.start + home.version.length);
    fs.writeFileSync(home.absolute, patched, "utf8");
  }
}

function run(options) {
  const remote = options.remote || "origin";
  const top = git(["rev-parse", "--show-toplevel"], options.repo || process.cwd(), true);
  if (top === null) {
    throw new Refusal({
      bumped: false,
      case: "not-a-work-tree",
      reason: `${options.repo || process.cwd()} is not inside a git work tree`,
    });
  }
  const root = top.trim();

  //: Before any network. A consumer repo pays one `existsSync` and exits.
  if (!fs.existsSync(path.join(root, CLAUDE_MANIFEST))) {
    report({
      bumped: false,
      case: "no-plugin-manifest",
      reason: `${CLAUDE_MANIFEST} is absent, so this repo publishes no plugin version`,
    });
    return 0;
  }
  const plugin = manifestName(
    fs.readFileSync(path.join(root, CLAUDE_MANIFEST), "utf8"),
    CLAUDE_MANIFEST
  );

  const branch = config().declaredBranches(root).release;
  if (!branch) {
    report({
      bumped: false,
      case: "no-release-branch",
      reason: "harness.yaml declares no branches.release, so there is no released version",
    });
    return 0;
  }

  const homes = readHomes(root, plugin);
  const current = agreedVersion(homes);
  const release = readRelease(root, remote, branch);
  const order = compare(parseVersion(current), parseVersion(release.version));

  if (order > 0) {
    report({
      bumped: false,
      case: "already-ahead",
      from: current,
      release,
      reason:
        "the integration branch already carries a version above the release " +
        "branch's, so this cycle's bump has been made",
    });
    return 0;
  }

  if (order < 0) {
    //: The version relation alone cannot tell these apart, and only one is a
    //: fault. A worktree cut from a base behind the commit that carried the bump
    //: reads a higher release version over its own base — before #621 a lagging
    //: green pointer was the usual way to end up there, and a stale local fetch
    //: is the way that remains. That is a rebase. Content on the release branch
    //: that the integration history does not contain is `promotion-step.sh`'s own
    //: divergence condition, and that is the fault. Ancestry is the discriminator.
    const stale =
      git(["merge-base", "--is-ancestor", "HEAD", release.commit], root, true) !== null;
    throw new Refusal(
      stale
        ? {
            bumped: false,
            case: "stale-base",
            from: current,
            release,
            reason:
              "the release branch already contains this checkout's HEAD and " +
              "carries a higher version, so this worktree's base predates the " +
              "last release",
            next: "rebase onto the integration tip and re-run",
          }
        : {
            bumped: false,
            case: "release-ahead",
            from: current,
            release,
            reason:
              "the release branch carries a higher version over content the " +
              "integration branch's history does not contain",
            next: "reconcile the branches; do not raise the integration version to match",
          }
    );
  }

  const next = raised(parseVersion(current));
  write(homes, next);
  report({
    bumped: true,
    case: "raised",
    from: current,
    to: next,
    release,
    homes: homes.map((home) => home.path),
  });
  return 0;
}

function parse(argv) {
  const options = {};
  for (let i = 0; i < argv.length; i += 1) {
    const match = /^--(repo|remote)$/.exec(argv[i]);
    if (!match || argv[i + 1] === undefined) return null;
    options[match[1]] = argv[i + 1];
    i += 1;
  }
  return options;
}

function usage(message) {
  process.stderr.write(
    `plugin-version: ${message}\n` +
      "usage: plugin-version.js [--repo <dir>] [--remote <name>]\n"
  );
  return EXIT_USAGE;
}

function main(argv) {
  const options = parse(argv);
  if (options === null) return usage("unreadable options");
  try {
    return run(options);
  } catch (err) {
    if (err instanceof Refusal) {
      report(err.payload);
      return EXIT_REFUSED;
    }
    if (err instanceof Unavailable) {
      process.stderr.write(`plugin-version: ${err.message}\n`);
      return EXIT_UNAVAILABLE;
    }
    throw err;
  }
}

if (require.main === module) {
  process.exitCode = main(process.argv.slice(2));
}

module.exports = { EXIT_REFUSED, EXIT_UNAVAILABLE, EXIT_USAGE, main };
