#!/usr/bin/env node
// size: one deny decision over a `git push`, which needs the whole path from
// tokens to verdict in one place — refspec parsing, `-C`/`--git-dir` directory
// resolution, the spine branch declaration, and the tree/marker evidence.
// #436 declined a shared `hooks/lib/`, so the marker reading this shares with
// `gate-evidence-guard.js` is duplicated by that decision rather than by
// accident. What that decision did not remove is a dependency on one flat
// sibling: the shell lexer comes from `git-push-guard.js`, and deleting that
// file disarms this guard completely. `main()` therefore checks the sibling is
// there before requiring it, so the disarm is announced by name instead of
// arriving as a crash notice. Filed as #444.
/**
 * Push-target guard (PreToolUse: Bash) — #436.
 *
 * The sibling ``git-push-guard.js`` refuses a push that *rewrites* history. This
 * one refuses a push that *lands unverified work*: a ``git push`` whose **target**
 * is a protected branch is denied unless a gate marker covers the tree of the
 * commit being pushed.
 *
 * **The marker is the authorisation.** ``scripts/verify.sh`` writes
 * ``<git-common-dir>/harness/gate/<tree-oid>.json`` on green, named after the git
 * tree object it verified. ``commands/build.md`` already refuses to integrate
 * unless ``git rev-parse HEAD^{tree}`` equals the tree its gate ran over, so the
 * tree the gate covered and the tree a push carries are the same object by the
 * process's own rule. This hook checks that equality mechanically.
 *
 * **No command-based exemption, and none is needed.** ``/build``, ``/routine``
 * and ``/promote`` all push a tree the gate has already covered, so they
 * authorise themselves by the only evidence a hook can actually verify. A hook
 * cannot see which slash command is driving the session, and building
 * enforcement on a claim it cannot check would be theatre.
 *
 * **One shell parser, not two.** The lexer, wrapper resolution and substitution
 * detection are imported from ``git-push-guard.js``. A second naive parser would
 * be walked past by ``sh -c "git push origin HEAD:dev"`` — a push the force guard
 * catches and this one would not. The require is **lazy, inside main()**: a
 * top-level sibling require sits outside the try that owns the fail-open path, so
 * an ESM-root load failure would turn "approve loudly" into "crash before writing
 * stdout" (the contract #303 forbids). The sibling's *existence* is checked
 * before the require, because the two failures are worth different messages: a
 * broken module is a bug in this bundle, while a missing one means this guard is
 * disarmed and one named file restores it. Without the check both arrive as the
 * generic crash notice, and the total loss of push-target enforcement reads as an
 * ordinary hook error.
 *
 * **Fail open or fail closed, split three ways.**
 *   1. The hook could not run (crash, unparseable stdin, failed require) — it has
 *      no opinion: pass through, loudly, on stderr.
 *   2. The hook ran but could not establish the facts (git unavailable, an
 *      unresolvable source, a shell expansion in a refspec, a push directory
 *      that is not spelled as a literal path, a directory-stack shape the
 *      tracking does not model, a ``--git-dir``/``GIT_DIR=`` operand aiming the
 *      push at a repository the tracking does not follow) — **deny**.
 *      Cheap-to-clear guards fail closed: one gate run clears a false deny,
 *      while a false allow is the irreversible act. The directory tracking
 *      itself follows ``cd``, ``pushd``/``popd`` (a literal target moves the
 *      directory and a bare ``popd`` restores it; rotations, flags and
 *      expansion targets are unknowable, #477) and ``git -C``.
 *   3. The hook ran, established the facts, and found no evidence — **deny**. Not
 *      a fall-open at all; it is the decision the hook exists to make.
 *
 * **Two predicates, and they are not interchangeable.** A directory slot is
 * decided by a whitelist (:func:`isLiteralDir`) and a refspec by a blacklist of
 * expansions (:func:`isUnreadable`). The asymmetry is forced by the vocabularies:
 * a refspec legitimately carries ``~``, ``^``, ``{`` and ``}`` (``HEAD~1``,
 * ``HEAD^``, ``HEAD@{0}``), so a whitelist there would refuse ordinary pushes,
 * while a directory has no such need and a blacklist there has no completion
 * condition — #436 closed four expansion shapes, #452 a fifth, its review two
 * more, and a glob was still walking through in 0.3.0 (#462). State 2's
 * "cheap to clear" is narrower for the whitelist than for the rest of it: a
 * directory whose name carries a *quoted* metacharacter (``cd "release (2)"``)
 * was allowed in 0.3.0 and is refused here, and neither a gate run nor a
 * respelling clears that one — only moving the checkout does.
 *
 * **Deny, not ask.** Whether a hook ``ask`` overrides an existing
 * ``permissions.allow`` entry is not documented clearly enough to bet enforcement
 * on, and the settings file carries ``Bash(git push origin dev)``. Deny-over-allow
 * precedence is what the force-push guard already relies on in production, and an
 * enforcement decision must be deterministic in an unattended run.
 *
 * **Honest limit.** This is evidence plumbing, not an authority. It reads a file
 * any process with write access to the repository can create, and it runs in the
 * same trust domain as the agent it checks. The authoritative control is
 * server-side branch protection, which no client-side hook can be argued past.
 * What this buys is that the default path now requires the gate to have run over
 * the exact bytes being pushed, and that manufacturing the evidence is a
 * discrete, deliberate, transcript-visible act rather than a silent omission.
 * Note the residual: state 1 above disarms this guard entirely, and unlike the
 * force-push guard it has no ``permissions.deny`` glob behind it — nothing in
 * that block covers a push to ``dev`` by target.
 */
"use strict";

const fs = require("fs");
const path = require("path");
const { spawnSync } = require("child_process");

const TAG = "[PUSH-TARGET-GUARD]";

//: The freshness bound, mirrored from ``scripts/gate_marker.py``. Its purpose is
//: toolchain drift under an unchanged tree, not session scope. The equivalence
//: with the Python parser is measured by ``test_gate_marker_contract.py``.
const MAX_AGE_ENV = "HARNESS_GATE_MARKER_MAX_AGE_SECONDS";
const DEFAULT_MAX_AGE_SECONDS = 86400;

//: Where markers live under the git common directory.
const MARKER_SUBDIR = ["harness", "gate"];

//: The one sibling this hook depends on. Named once, so the existence check and
//: the message it emits cannot disagree about which file is missing.
const SIBLING_PARSER = "git-push-guard.js";

//: Used when a repo declares no branches. Deliberately over-broad: a false deny
//: is recoverable in one command (run the gate), a false allow lands unverified
//: work on the integration branch of a repo that told the guidance nothing about
//: itself. ``workflow-guard.js`` hardcodes the same vocabulary — the two answer
//: the same question about a branch name, and answering it differently is how
//: ``staging`` became a branch you could edit source on directly and could not
//: push to. It cannot import this set (that would give the advisory hooks a
//: sibling dependency the bundle keeps to exactly one), so
//: ``test_workflow_guard_hook`` derives its corpus from this export instead:
//: adding a name here is what makes that hook's list red.
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

//: ``git push`` options that consume the following token, so an option argument
//: is never mistaken for the remote or a refspec.
const PUSH_OPTS_WITH_ARG = new Set(["-o", "--push-option", "--receive-pack", "--exec", "--repo"]);

//: Recursion bound, matching the sibling guard's pathological-nesting backstop.
const MAX_DEPTH = 16;

/**
 * Fail open, loudly. See the identical helper in the other hooks (#303): the
 * approving payload still goes out, but stderr says this hook did not run, so a
 * silently-disarmed guard is distinguishable from a deliberate pass-through. Built
 * from hook-owned constants and `err.message` only — never the payload, which carries
 * the very Bash command under inspection. Inlined per hook on purpose: a shared module
 * would be a load-time dependency whose own failure is the class being reported on.
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

/** Run git in ``dir`` and return its trimmed stdout, or null.
 *
 * Null means *git said no* — a ref that does not resolve, a directory that is
 * not a checkout, a git that could not be spawned at all. Every one of those is
 * a decision input for this guard (state 2 above closes), not an internal error,
 * so they collapse to one value deliberately rather than by accident. */
function git(dir, args) {
  try {
    const res = spawnSync("git", args, { cwd: dir, encoding: "utf8" });
    if (res.error || res.status !== 0) return null;
    return String(res.stdout).trim();
  } catch (err) {
    // A probe that cannot run is an input to the deny decision, not a crash:
    // this guard fails closed on facts it could not establish.
    void err;
    return null;
  }
}

/** The freshness bound, or the default. An unusable value reads as *unset*:
 * "never fresh" would wedge every push behind a gate run that can never satisfy
 * it, and "always fresh" would disarm the bound. Strict digits only, so this
 * agrees with Python's ``int()`` on the degenerate spellings. */
function maxAgeSeconds() {
  const raw = process.env[MAX_AGE_ENV];
  if (!/^[0-9]+$/.test(String(raw))) return DEFAULT_MAX_AGE_SECONDS;
  const value = Number.parseInt(raw, 10);
  return value > 0 ? value : DEFAULT_MAX_AGE_SECONDS;
}

/** Where ``tree``'s marker lives, or null outside a repository.
 *
 * The **common** directory, so a gate run in a detached gate worktree writes a
 * marker the build worktree can read — two worktrees at the same tree oid have
 * byte-identical content, so that visibility is correct, not merely convenient. */
function markerPath(tree, cwd) {
  const common = git(cwd, ["rev-parse", "--path-format=absolute", "--git-common-dir"]);
  if (common === null) return null;
  let real = common;
  try {
    real = fs.realpathSync(common);
  } catch (err) {
    // The common dir was reported but cannot be resolved; use it verbatim
    // rather than losing the answer. Deliberately not reported: a path that
    // does not resolve simply yields no marker, which the caller handles.
    void err;
  }
  return path.join(real, ...MARKER_SUBDIR, `${tree}.json`);
}

/** True iff a marker for ``tree`` exists in ``dir``'s repository and is fresh. */
function hasFreshMarker(tree, dir) {
  const marker = markerPath(tree, dir);
  if (marker === null) return false;
  try {
    return Date.now() - fs.statSync(marker).mtimeMs < maxAgeSeconds() * 1000;
  } catch (err) {
    // A missing marker is the decision this guard exists to make, not an error.
    void err;
    return false;
  }
}

/** Strip a matching pair of surrounding quotes. Written without quote
 * characters inside a regex on purpose — the repo's hook source scanners blank
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

//: One ``key: value`` pair, in either spelling of the block.
const PAIR = /^\s*([A-Za-z_][A-Za-z0-9_-]*)\s*:\s*(.*)$/;

//: ``branches:`` written as a yaml **flow mapping** on one line — valid yaml a
//: real loader reads identically to the block form, which the line scanner below
//: read as nothing until #487. The body excludes braces, so only a flat mapping
//: is accepted: a nested one (``{a: {b: c}}``) is left to the unreadable notice
//: rather than half-parsed, and a flow *sequence* (``[a, b]``) declares no
//: branch names to begin with. The trailing group is the comment yaml allows
//: after the closing brace. A flow mapping wrapped across several lines is out
//: of scope too — every spelling left out lands on the unreadable notice below
//: rather than on a silent empty parse, which is the whole point of having it.
const BRANCHES_FLOW = /^branches:\s*\{([^{}]*)\}\s*(?:#.*)?$/;

//: Any line that opens a ``branches:`` key, whatever follows it. Wider than
//: either arm above on purpose: a declaration this parser cannot read is the
//: thing worth reporting, so the detector must not be the parser.
const BRANCHES_KEY = /^branches\s*:/;

//: One ``key: value`` pair inside a **flow mapping body**, scanned rather than
//: split. The body used to be cut on every comma, which is wrong for a comma
//: inside a quoted value: ``{release: "has,comma"}`` yielded the fragment
//: ``"has`` — a name opening with a quote character, which no branch can be —
//: and dropped the name actually declared (#488). Both hooks were wrong
//: identically, so the two-parser equivalence could not see it and no notice
//: fired.
//:
//: The value alternation tries both quoted forms before the bare one, so a
//: quoted value is taken whole and only an unquoted value stops at a comma. The
//: quote characters are written as ``\x22``/``\x27`` on purpose, for the same
//: reason ``stripQuotes`` avoids them: the repo's hook source scanners blank
//: string literals to count braces, and a lone quote inside a pattern throws
//: their offsets off. Every match includes its key, so no match is zero-length
//: and the global scan always advances.
const FLOW_PAIR = /([A-Za-z_][A-Za-z0-9_-]*)\s*:\s*(\x22[^\x22]*\x22|\x27[^\x27]*\x27|[^,]*)/g;


//: Files already reported as unreadable, so a hook that resolves its declaration
//: at more than one call site says it once. Process-scoped, and a hook process
//: handles exactly one invocation.
const reportedUnreadable = new Set();

/**
 * Say once, on stderr, that ``file`` declares branches this parser could not
 * read. Same posture and the same ``TAG`` as ``failOpen``: the caller carries on
 * with whatever it can read instead, stdout and the exit status are untouched,
 * and nothing from the payload is echoed. Without it, an unreadable declaration
 * is indistinguishable from a readable one in every repo whose branch names
 * happen to match the fallback (#487).
 *
 * What the notice may claim is bounded by what the caller then does, and the
 * caller has two things left to try: ``CONTEXT.md`` behind an unreadable spine,
 * then ``FALLBACK_PROTECTED``. A repository part-way through the v5 migration
 * reaches the first, so a line asserting the conservative set is in force would
 * be false exactly where an operator acts on it. It reports the one thing true
 * in every case — this file's declaration is not what is being protected — and
 * ``test_hooks_unreadable_declaration_is_loud.py`` measures the bound.
 */
function noticeUnreadableDeclaration(file) {
  const name = String(file);
  if (reportedUnreadable.has(name)) return;
  reportedUnreadable.add(name);
  process.stderr.write(
    `${TAG} unreadable-declaration: ${name.replace(/\s+/g, " ").slice(0, 200)}: ` +
      "declares branches: but no names could be read from it; " +
      "the branches it names are not the ones being protected\n"
  );
}

/** The branch names declared under ``branches:`` in a repo's spine.
 *
 * The spine is ``CLAUDE.md`` (v5); ``CONTEXT.md`` is read as the fallback for a
 * repo hydrated before the spine absorbed it. An empty parse falls through, so
 * a repo whose CLAUDE.md carries no ``branches:`` block still finds its config.
 *
 * A small line parser: the file is markdown with a fenced yaml block, so a real
 * yaml load would need a dependency this surface does not have. Every value
 * under the block counts — ``integration``, ``staging``, ``release`` and any key
 * a repo invents — because the question is which branches the repo treats as
 * shared, not which role it assigned them.
 *
 * Two spellings of the same declaration are read: the indented block, and the
 * one-line flow mapping (#487). The first ``branches:`` key wins; a second one
 * later in the file is not merged, matching how the block arm already stops at
 * the end of the first block it finds.
 *
 * A ``branches:`` key that yields no names — a hand-edited sequence, a spelling
 * nobody anticipated, or a declaration that really is empty — is reported once on
 * stderr and then falls through to the caller's fallback. Reporting an
 * explicitly empty declaration is deliberate: the fallback protects a set the
 * repo did not ask for either way, and that divergence is the thing worth
 * seeing. */
function declaredBranches(contextFile) {
  let text;
  try {
    text = fs.readFileSync(contextFile, "utf8");
  } catch (err) {
    // No spine is the ordinary case in a repo that has not adopted the
    // guidance; the conservative fallback set applies and that is not an error.
    void err;
    return [];
  }
  const found = [];
  let declares = false;
  let indent = -1;
  for (const raw of text.split("\n")) {
    // ``\r`` first, then tabs. Splitting on ``\n`` leaves a CRLF file's lines
    // ending in ``\r``, and ``PAIR``'s trailing ``(.*)$`` cannot cross one —
    // JavaScript counts it as a line terminator, so ``PAIR.exec("  a: b\r")``
    // was ``null`` and every block declaration in a CRLF spine parsed to nothing
    // while the same declaration in the flow spelling parsed fine (#488). The
    // flow arm never saw it because it runs against ``line.trim()``.
    const line = raw.replace(/\r$/, "").replace(/\t/g, "  ");
    const lead = line.length - line.trimStart().length;
    if (indent === -1) {
      const trimmed = line.trim();
      if (!BRANCHES_KEY.test(trimmed)) continue;
      declares = true;
      const flow = BRANCHES_FLOW.exec(trimmed);
      if (flow) {
        for (const match of flow[1].matchAll(FLOW_PAIR)) {
          const value = scalar(match[2]);
          if (value) found.push(value);
        }
        break; // a flow mapping is the whole declaration
      }
      // A block opens when the key carries **no value** — asked through
      // ``scalar``, so the one helper that already decides comments decides them
      // in this position too. The old test was ``/^branches:\s*$/`` against the
      // trimmed line, and yaml permits a comment after any key, so
      // ``branches:   # the shared ones`` skipped the perfectly ordinary mapping
      // beneath it and fell back (#488). This repo's own spine writes inline
      // comments on sibling lines of this very block — ``branches.release``
      // among them, inside the very mapping this arm is trying to read.
      //
      // Asking the value rather than widening the key pattern is what keeps the
      // spellings that must stay unreadable unreadable: ``branches: lonely-lane``
      // and ``branches: [main, staging]`` both yield a non-empty scalar and so
      // are not blocks, and land on the notice as before.
      if (scalar(trimmed.replace(BRANCHES_KEY, "")) === "") indent = lead;
      continue;
    }
    if (!line.trim()) continue;
    if (lead <= indent) break; // the block ended
    const match = PAIR.exec(line);
    if (!match) continue;
    const value = scalar(match[2]);
    if (value) found.push(value);
  }
  if (declares && found.length === 0) noticeUnreadableDeclaration(contextFile);
  return found;
}

/** A ref name reduced to its branch name: ``refs/heads/dev`` becomes ``dev``. */
function branchName(ref) {
  return ref.replace(/^refs\/heads\//, "").replace(/^refs\/remotes\/[^/]+\//, "");
}

/** The set of branches a push must carry evidence to reach, resolved in ``dir``. */
function protectedBranches(dir) {
  const top = git(dir, ["rev-parse", "--show-toplevel"]);
  const fromSpine = top === null ? [] : declaredBranches(path.join(top, "CLAUDE.md"));
  const declared =
    fromSpine.length || top === null ? fromSpine : declaredBranches(path.join(top, "CONTEXT.md"));
  const names = declared.length ? declared : FALLBACK_PROTECTED;
  const set = new Set(names.map(branchName));
  const remoteHead = git(dir, ["symbolic-ref", "refs/remotes/origin/HEAD"]);
  if (remoteHead) set.add(branchName(remoteHead));
  return set;
}

/** Parse one command's tokens as a ``git push``, or return null.
 *
 * Returns ``{ dir, refspecs, isDelete, mirrors, movesAllRefs, tagsOnly }`` where ``dir``
 * is a ``git -C`` operand if one was given. A command substitution in the
 * sub-command slot is left to ``git-push-guard.js``, which already fails closed
 * on it — a second deny here would only re-deny a command already refused. */
function parsePush(rawTokens, parser) {
  const tokens = parser.resolveCommand(rawTokens);
  if (tokens.length === 0 || !parser.isGit(tokens[0])) return null;

  // ``GIT_DIR=…`` is an environment-assignment spelling of ``--git-dir`` that
  // ``resolveCommand`` strips with the other assignment prefixes, so it is read
  // off the raw tokens before resolution (#477). Scanned everywhere rather than
  // only in prefix position: ``env GIT_DIR=… git push`` interleaves it with a
  // wrapper, and a stray match in an operand slot costs only a cheap deny.
  let namesGitDir = rawTokens.some((token) => /^GIT_DIR=/.test(String(token)));

  let i = 1;
  let dir = null;
  while (i < tokens.length) {
    const token = tokens[i];
    if (parser.GIT_GLOBAL_WITH_ARG.has(token)) {
      if (token === "-C") dir = tokens[i + 1];
      if (token === "--git-dir") namesGitDir = true;
      i += 2;
      continue;
    }
    if (token.startsWith("--git-dir=")) namesGitDir = true;
    if (token.startsWith("-")) {
      i += 1;
      continue;
    }
    break;
  }
  if (i >= tokens.length || tokens[i] !== "push") return null;

  const operands = [];
  let isDelete = false;
  let mirrors = false;
  let movesAllRefs = false;
  let tagsOnly = false;
  let sawDoubleDash = false;
  for (let j = i + 1; j < tokens.length; j++) {
    const token = tokens[j];
    if (!sawDoubleDash && token === "--") {
      sawDoubleDash = true;
      continue;
    }
    if (!sawDoubleDash && token.length > 1 && token.startsWith("-")) {
      if (PUSH_OPTS_WITH_ARG.has(token)) j += 1;
      if (token === "--delete" || /^-[A-Za-z]*d[A-Za-z]*$/.test(token)) isDelete = true;
      if (token === "--mirror") mirrors = true;
      if (token === "--mirror" || token === "--all") movesAllRefs = true;
      if (token === "--tags") tagsOnly = true;
      continue;
    }
    operands.push(token);
  }
  // git push [<repository> [<refspec>...]] — the first operand is always the
  // repository, so a refspec can never claim that slot.
  return {
    dir,
    namesGitDir,
    refspecs: operands.slice(1),
    isDelete,
    mirrors,
    movesAllRefs,
    tagsOnly,
  };
}

//: The characters a directory token may be built from and still be read as the
//: path it looks like. A **whitelist**, so a syntax nobody has thought of yet
//: denies by default rather than being discovered in production.
//:
//: Space is admitted because the lexer honours quotes and backslash escapes, so
//: a space surviving into a post-lex token was quoted and is therefore literal
//: (``cd "my dir"``). Every code point at or above U+0080 is admitted because
//: every shell expansion trigger is ASCII by the POSIX grammar, so excluding
//: them would be a pure false-deny class for anyone whose paths are not English.
//: Deliberately absent: ``$`` and the backtick (expansion), ``~`` (home), ``*``,
//: ``?``, ``[``, ``]``, ``{``, ``}`` (globs and braces), and every other
//: metacharacter — a directory has no legitimate need of any of them.
const LITERAL_DIR_SAFE = /^[A-Za-z0-9._+@%,=:\-\/ \u{80}-\u{10FFFF}]+$/u;

/** True iff ``token`` is a directory this guard can read as a literal path.
 *
 * The whitelist half of the split described in the module docstring, and the
 * predicate for **both directory decision slots** — the ``cd`` target in
 * :func:`pushesIn` and the ``git -C`` operand in :func:`resolveDir`. It
 * *replaces* :func:`isUnreadable` at those two slots rather than layering over
 * it: it is strictly stronger there (``$``, the backtick and ``~`` are all
 * outside the safe class), and two conditions that catch the same input hide
 * each other from mutation.
 *
 * The defect it closes (#462, measured live against 0.3.0 with no marker
 * anywhere): ``cd .worktrees/work-* && git push origin HEAD:dev`` resolves
 * statically to a path that does not exist, so git answered nothing about it and
 * the push was allowed **with no marker check at all** — while the shell expands
 * the glob onto a real, unverified worktree. The same held for ``?``, ``[…]``,
 * ``{…}`` and for a glob in the ``git -C`` operand. A blacklist of expansions
 * has no completion condition, which is why this is inverted rather than widened.
 *
 * A non-string reads as unreadable rather than throwing: a throw here lands in
 * the crash arm, which fails **open**, so the degenerate command would be waved
 * through by the one path that must not wave anything through. The one input
 * that reaches this with a non-string is the ``undefined`` a bare ``cd`` yields
 * when :func:`pushesIn` looks for a target and finds none — not a bare
 * ``git -C``, which :func:`parsePush` abandons before it can name a directory,
 * because the token after ``-C`` is the last one and no ``push`` follows it. A
 * literal path that does not exist is still a
 * pass-through, as before — a literal token cannot become a different directory
 * at run time, and that is the property this predicate is about. */
function isLiteralDir(token) {
  if (typeof token !== "string") return false;
  return LITERAL_DIR_SAFE.test(token);
}

/** The directory a push actually runs in, given its ``git -C`` operand (or
 * null) and the directory the command has cd'd to (or null when that is itself
 * unknowable).
 *
 * ``git -C`` is **relative to the process's working directory**, so a relative
 * operand composes with the ``cd`` rather than replacing it. Resolving one
 * against the hook's own cwd instead is the same defect as ignoring the ``cd``,
 * one operand further along, and it fails in the dangerous direction: the hook's
 * cwd is usually the repo root, which usually *has* a marker, so a push from an
 * unverified worktree would be authorised by a tree nobody is pushing. A
 * relative operand with no known base stays null, which the caller denies.
 *
 * An operand that is not a literal path stays null for the same reason a ``cd``
 * target does — this is the *other* directory decision slot, and closing only
 * the ``cd`` one left the refusal one rewrite from being bypassed along the path
 * its own message recommends: ``git -C "$w" push`` is ``cd "$w" && git push``
 * one operand further along. */
function resolveDir(operand, cwd) {
  if (operand === null) return cwd;
  if (!isLiteralDir(operand)) return null;
  if (path.isAbsolute(operand)) return operand;
  return cwd === null ? null : path.resolve(cwd, operand);
}

/** True iff ``token`` carries a shell expansion, so its value is not knowable
 * before the command runs.
 *
 * Command substitution and parameter expansion are the same problem in a
 * decision slot: ``git push origin HEAD:$T`` reads statically as a push to a
 * branch called ``$T``, which no protected set contains, while the shell hands
 * git whatever ``T`` holds. The sibling guard's helper covers ``$(…)`` and
 * backticks because those are what a *force* flag can hide behind; a target has
 * the wider exposure, so a bare ``$`` counts here too. A leading ``~`` is the
 * third expansion a shell performs on a bare word and the one that reads least
 * like one, so it is named rather than left to be rediscovered.
 *
 * This governs the **refspec** slot in :func:`movements`, and only that one. The
 * directory slots were keyed on it until #462 and are now decided by
 * :func:`isLiteralDir` instead; a refspec cannot move to that whitelist, because
 * ``HEAD~1``, ``HEAD^`` and ``HEAD@{0}`` are ordinary spellings built from
 * characters a directory has no business carrying. Every arm here is separately
 * killable, and both killers moved into the refspec slot with the predicate:
 * ``$(…)`` is caught by the ``$`` arm alone, so a backtick **refspec** is the
 * only input left that proves the substitution arm is live, and a refspec with a
 * leading ``~`` the only one that proves the tilde arm is.
 * ``test_the_refspec_slot_keeps_its_own_expansion_predicate`` carries one of
 * each, and asserts the *reason* rather than the decision, because the two arms
 * fail differently once deleted. Measured: with the tilde arm gone, ``~1:main``
 * still denies — on the *source does not resolve to a tree* rule instead — so a
 * decision-only check certifies that arm's absence. With the substitution arm
 * gone, a backtick refspec is **allowed**, because the target it reads
 * statically is a branch name no protected set holds. The reason assertion is
 * what guards the tilde arm; the substitution arm's deletion is a live evasion
 * rather than a reworded refusal, and the decision alone would catch that one. */
function isUnreadable(token, parser) {
  return parser.hasCommandSubstitution(token) || token.includes("$") || token.startsWith("~");
}

/** Every ``git push`` reachable from ``command``, each with the directory it
 * would run in.
 *
 * The directory matters concretely: ``/build`` ships with
 * ``cd "$worktree_path" && git push origin HEAD:dev``, and resolving ``HEAD`` at
 * the session cwd reads the wrong branch — and could find a marker for a tree
 * nobody is pushing. So a ``cd`` preceding a push in the same lexed sequence
 * moves the directory, and a ``cd`` target that is not a literal path —
 * ``isLiteralDir``, so a glob or a brace as much as a ``$VAR`` — makes it
 * unknowable (``dir: null``, which the caller denies). A ``cd`` with no operand
 * at all is the same answer by the same predicate, which is why there is no
 * separate check for it: two conditions catching one input would hide each other
 * from mutation. That the shipped idiom is the *expansion* spelling is the whole
 * point: keying this on the narrower command-substitution predicate exempted the
 * one command it was written for. */
function pushesIn(command, startDir, parser, depth) {
  if (depth > MAX_DEPTH) return [];
  const found = [];
  const { commands, substitutions } = parser.lex(command);
  let dir = startDir;
  // The shell's directory stack, mirrored only as far as ``pushd <literal>`` /
  // bare ``popd`` build it (#477). A fresh stack per lexed sequence, and a
  // fresh one per nested script below, matches the shell: a child shell
  // inherits its parent's cwd but starts its own dirstack.
  let dirStack = [];
  for (const { tokens } of commands) {
    const resolved = parser.resolveCommand(tokens);
    const head = resolved.length ? parser.basename(resolved[0]) : "";
    if (head === "cd") {
      const target = resolved.slice(1).find((t) => !t.startsWith("-"));
      if (!isLiteralDir(target)) dir = null;
      else if (dir !== null) dir = path.resolve(dir, target);
      continue;
    }
    if (head === "pushd") {
      const operands = resolved.slice(1);
      const target = operands.find((t) => !t.startsWith("-") && !t.startsWith("+"));
      const shuffles = operands.some((t) => t.startsWith("-") || t.startsWith("+"));
      if (shuffles || target === undefined || !isLiteralDir(target)) {
        // A rotation (``pushd +2``), a flag (``-n`` does not move at all), a
        // bare ``pushd`` (swap) or an expansion target all rearrange the
        // shell's stack in ways this model does not mirror. After any of them
        // both the directory and the stack are unknowable.
        dir = null;
        dirStack = [];
      } else {
        dirStack.push(dir);
        dir = dir === null ? null : path.resolve(dir, target);
      }
      continue;
    }
    if (head === "popd") {
      // A rotation operand shuffles rather than pops; a popd with no matching
      // pushd in this model may be consuming a stack built by a shape the
      // model refused above. Both are unknowable; only the bare pop of a
      // tracked entry restores a directory.
      if (resolved.length > 1 || dirStack.length === 0) {
        dir = null;
        dirStack = [];
      } else {
        dir = dirStack.pop();
      }
      continue;
    }
    const push = parsePush(tokens, parser);
    if (push) found.push({ ...push, dir: resolveDir(push.dir, dir) });
    for (const script of parser.nestedScripts(tokens)) {
      found.push(...pushesIn(script, dir, parser, depth + 1));
    }
  }
  for (const body of substitutions) {
    found.push(...pushesIn(body, startDir, parser, depth + 1));
  }
  return found;
}

/** The ``{ source, target, isDelete }`` triples one push would move, or null
 * when a refspec carries a command substitution and cannot be read statically. */
function movements(push, dir, parser) {
  if (push.refspecs.length === 0) {
    if (push.tagsOnly) return []; // a tag is not a branch
    // ``--symbolic-full-name`` and not ``--abbrev-ref``: the abbreviated form of
    // an upstream is ``origin/dev``, which ``branchName`` cannot reduce (and must
    // not, or ``feature/x`` would reduce to ``x``). The full ref
    // ``refs/remotes/origin/dev`` it can, so a bare ``git push`` resolves to the
    // branch it will actually move rather than to a name no protected set holds.
    const upstream = git(dir, ["rev-parse", "--symbolic-full-name", "@{upstream}"]);
    const current = git(dir, ["rev-parse", "--abbrev-ref", "HEAD"]);
    const target = upstream !== null ? branchName(upstream) : current;
    if (target === null) return null;
    return [{ source: "HEAD", target, isDelete: push.isDelete }];
  }
  const moves = [];
  for (const raw of push.refspecs) {
    if (isUnreadable(raw, parser)) return null;
    const spec = raw.startsWith("+") ? raw.slice(1) : raw;
    const colon = spec.indexOf(":");
    if (colon === -1) {
      moves.push({ source: spec, target: branchName(spec), isDelete: push.isDelete });
      continue;
    }
    const source = spec.slice(0, colon);
    const target = spec.slice(colon + 1);
    // A ``:<name>`` refspec deletes ``<name>``, and so does ``<name>:`` (an
    // empty destination), so both arms report a delete rather than a move.
    moves.push({
      source,
      target: branchName(target || source),
      isDelete: push.isDelete || source === "" || target === "",
    });
  }
  return moves;
}

function deny(reason) {
  process.stdout.write(
    JSON.stringify({
      hookSpecificOutput: {
        hookEventName: "PreToolUse",
        permissionDecision: "deny",
        permissionDecisionReason: `${TAG} ${reason}`,
      },
    })
  );
}

/** Defer to the normal permission flow — do NOT pre-approve. */
function passThrough() {
  process.stdout.write(JSON.stringify({ continue: true }));
}

/** The refusal for a push this guard decided against, or null to allow it. */
function verdict(push, parser) {
  const dir = push.dir;
  if (dir === null) {
    return (
      "Blocked a push whose working directory cannot be resolved statically. A cd " +
      "target and a git -C operand are read only when every character in them is " +
      "one this guard can prove the shell will not act on; this one carries a " +
      "character outside that set, so the directory it lands in — and the tree " +
      "this push would carry — is unknowable. Spell the directory literally: a " +
      "git -C <path> is the same unknowable directory one operand further along, " +
      "and is refused here too."
    );
  }
  if (push.namesGitDir) {
    // Before the work-tree probe below: a --git-dir push runs against the
    // repository the operand names even from a cwd that is no repository at
    // all, so "not inside a work tree" must not read as "not my concern" (#477).
    return (
      "Blocked a push that names its repository with --git-dir (or GIT_DIR=). " +
      "The directory this guard resolves — cd, pushd/popd, git -C — is not the " +
      "one such a push runs against, so the marker check would read the wrong " +
      "repository. Spell it as `git -C <path> push`, which this guard resolves."
    );
  }
  if (git(dir, ["rev-parse", "--is-inside-work-tree"]) !== "true") return null;

  const guarded = protectedBranches(dir);
  const moves = movements(push, dir, parser);
  if (moves === null) {
    return (
      "Blocked a push whose refspec carries a shell expansion, or whose target " +
      "cannot be resolved. The branch it moves cannot be established before the " +
      "push runs, so there is nothing to check evidence against. Spell the " +
      "refspec literally."
    );
  }
  if (push.mirrors) {
    // Unconditional, and deliberately not conditioned on a protected branch
    // existing here. --mirror makes the remote match the local ref set, so a
    // protected branch this repo does **not** have is one --mirror deletes:
    // "no protected branch locally" is the most dangerous case, not the safe one.
    return (
      "Blocked a --mirror push. It makes the remote match this repository's refs " +
      "exactly, so it moves protected branches with no refspec naming them and " +
      "deletes any it does not hold locally. No gate evidence authorises that. " +
      "Push an explicit refspec."
    );
  }
  if (push.movesAllRefs) {
    // --all moves the local branches and nothing else, so a repo holding none of
    // the protected names has no protected target and a deny would be false.
    const anyProtected = [...guarded].some((name) => git(dir, ["rev-parse", "--verify", name]));
    if (anyProtected) {
      return (
        "Blocked a --all push. It moves every local branch, including protected " +
        "ones, with no refspec naming them — so there is no target to verify " +
        "and no tree to check. Push an explicit refspec."
      );
    }
  }
  for (const move of moves) {
    if (!guarded.has(move.target)) continue;
    if (move.isDelete) {
      return (
        `Blocked a delete of the protected branch ${JSON.stringify(move.target)}. ` +
        "No gate evidence authorises deleting a shared branch; a human must run it."
      );
    }
    const tree = git(dir, ["rev-parse", "--verify", `${move.source}^{tree}`]);
    if (tree === null) {
      return (
        `Blocked a push to the protected branch ${JSON.stringify(move.target)}: the ` +
        `source ${JSON.stringify(move.source)} does not resolve to a tree in ${dir}, ` +
        "so there is nothing to check evidence against."
      );
    }
    if (!hasFreshMarker(tree, dir)) {
      return (
        `Blocked a push to the protected branch ${JSON.stringify(move.target)}. No ` +
        `gate marker covers tree ${tree.slice(0, 12)} — the gate has not been run ` +
        `green over the exact bytes this push carries (looked for ` +
        `${markerPath(tree, dir)}). Run the repo verify gate in ${dir}, then push ` +
        "again. The gated tree is the authorisation; there is no exemption for a " +
        "particular command."
      );
    }
  }
  return null;
}

function main() {
  const input = readStdin();
  if ((input.tool_name || "") !== "Bash") return passThrough();
  const command = (input.tool_input && input.tool_input.command) || "";
  if (!command) return passThrough();

  // Lazy, inside main()'s try: a top-level sibling require sits outside the
  // fail-open path, turning an ESM-root load failure into a crash before stdout.
  // Existence first, so a *missing* sibling gets its own message: node names the
  // file in its module error too, but that arrives through the generic crash arm
  // and reads as a bug in this hook rather than as "this guard is disarmed and
  // git-push-guard.js is what restores it".
  const sibling = path.join(__dirname, SIBLING_PARSER);
  if (!fs.existsSync(sibling)) {
    failOpen(
      `the shell parser it requires is missing, so this guard is disarmed and refuses ` +
        `nothing until ${SIBLING_PARSER} is restored`,
      { message: `looked for ${sibling}` }
    );
    return passThrough();
  }
  const parser = require("./git-push-guard.js");

  const cwd = input.cwd || process.cwd();
  for (const push of pushesIn(command, cwd, parser, 0)) {
    const reason = verdict(push, parser);
    if (reason) return deny(reason);
  }
  passThrough();
}

if (require.main === module) {
  try {
    main();
  } catch (err) {
    // State 1: the hook could not run, so it has no opinion. Pass through, but
    // loudly — a disarmed enforcement hook must not look like a clean pass.
    failOpen("crashed before it could decide", err);
    process.stdout.write(JSON.stringify({ continue: true }));
  }
}

// Exported so ``test_gate_marker_contract.py`` can execute this hook's copy of
// the contract against the Python writer's. The path is computed in three
// languages and the freshness bound parsed in three, which is exactly the shape
// that drifts silently; an equivalence test that runs all three is what catches
// it. The ``require.main === module`` guard above means importing for that
// introspection never runs the hook.
// ``declaredBranches`` and ``protectedBranches`` are exported for the same
// reason and by the same argument, one duplication further along:
// the spine's ``branches:`` block is parsed here **and** in
// ``gate-evidence-guard.js``, and the two have already drifted in shape (an
// array here, a map there). Drift in what the two consider *protected* is
// silent in both directions — this guard would stop refusing a push the Stop
// hook still treats as shared, or refuse one it does not — so
// ``test_context_branch_parsing_contract.py`` executes both over one fixture
// corpus and compares the sets that fall out. The differing return shapes are
// deliberate and are not being unified; the equivalence test is the drift
// control the no-shared-lib decision asks for.
// ``isLiteralDir`` is exported so the over-denial floors drive the **production**
// predicate rather than a re-implementation of its character class: a test that
// re-applied the shipped class in its own loop would measure the class and agree
// with itself about everything else (#462).
module.exports = {
  isLiteralDir,
  markerPath,
  maxAgeSeconds,
  declaredBranches,
  protectedBranches,
  FALLBACK_PROTECTED,
};
