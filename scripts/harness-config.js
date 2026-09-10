"use strict";
//
// The one reader of a repo's Harness configuration (#537 AC-2).
//
// Until this module the repo carried three hand-rolled readers of the same
// subject: ``declaredBranches`` in ``hooks/push-target-guard.js`` and again in
// the Stop hook, and a ``commands.verify`` reader in the gate marker helper.
// Every parser bug the tree has recorded lived in one of the three — a flow
// mapping read as nothing (#487), a comma inside a quoted value cutting the
// value in half and a comment after a key skipping the block beneath it (#488),
// a quote-tracking stripper turning an unpaired quote into an executable
// fragment (#510). #457 held the two hook copies *equivalent* to each other,
// which is why #488 was invisible: both were wrong identically. One reader is
// what removes the class; equivalence cannot.
//
// **Why it lives in ``scripts/`` and not ``hooks/lib/``.** The reason this
// comment gave until #621 was that the marker helper beside it was materialized
// *into a consumer repo* while the hooks ran from the plugin root, making
// ``scripts/`` the one directory both could reach. ADR 0022 point 1 abolishes
// that: the plugin no longer writes any executable it owns into a consumer, and
// that helper is deleted. The placement survives on a different reason.
//
// That reason is ``hooks/``. #436 declined a shared hooks library because
// ``test_hooks_fail_open_is_loud`` and ``test_hooks_module_type`` scan
// ``hooks/*.js`` non-recursively **as hooks** — a library sitting there is
// either read as a hook and fails those guards, or forces an exemption into
// both. This module is not in that directory, so their meaning is unchanged and
// #436's decision stands. Its consumers now span two directories either way —
// ``scripts/`` siblings require it as ``./harness-config.js`` and the hooks as
// ``../scripts/harness-config.js`` — so wherever it sits one side reaches
// across. ``scripts/`` is where that costs nothing.
//
// #436's second reason — "a shared module's own load failure would disarm both
// enforcement hooks together" — is narrower since #621, because only one
// enforcement hook is left. ``test-lock-guard.js`` requires this module inside a
// ``try`` and a load failure degrades it to an inactive lock; the push guard is
// advisory now and degrades to its conservative fallback set, which over-warns.
// Neither degrades to silence pretending to be a pass.
//
// No dependencies, by constraint: hooks run from a plugin cache with no install
// step. This is a small reader of a small, declared configuration map, not a
// YAML implementation — every spelling it cannot read is reported rather than
// half-parsed, because a silently mis-derived branch name is a push the guard
// does not stop.

const fs = require("node:fs");
const path = require("node:path");

//: The configuration sources, in precedence order. ``harness.yaml`` is where
//: #537 moves the block to; the three markdown spines are read behind it because
//: consuming repos have not migrated and their hooks must keep working on the
//: day this lands.
//:
//: **One reader walks this list, and its rule is its own.** :func:`readMap`
//: searches on until a source *declares* the key, because a missing ``branches:``
//: block falls back to a conservative set and a repo mid-migration has its
//: declaration in a later file. Until #621 a second reader took the first source
//: that merely *existed* and refused there — that was ``gateCommand``, whose
//: value decided what could mint evidence, and it left with the marker. Nothing
//: here fails closed on the first source any more.
const SOURCES = ["harness.yaml", "AGENTS.md", "CLAUDE.md", "CONTEXT.md"];

//: The two quote characters, written as escapes rather than as themselves. The
//: repo's source scanners blank string-literal contents to count delimiters, and
//: a lone quote inside a pattern throws their offsets off.
const DOUBLE = "\x22";
const SINGLE = "\x27";

//: One ``key: value`` pair. Matched against the ``\r``-stripped raw line: a
//: trailing ``(.*)$`` cannot cross a ``\r``, because JavaScript counts it as a
//: line terminator, so a CRLF spine lost its whole block until #488.
//: A key may carry dots (#588). ``queue.projects.<name>.wip_limit`` is the path
//: the spine names for a per-project override, and this reader is flat by
//: design — a genuinely nested block is refused whole rather than half-read —
//: so the path is spelled as one key. Widening only ever makes a previously
//: unreadable line readable; nothing that parsed before parses differently.
const PAIR = /^\s*([A-Za-z_][A-Za-z0-9_.-]*)\s*:\s*(.*)$/;

//: A key opening a block at the top level of the configuration map. Anchored at
//: column 0: an indented ``commands:`` is an example inside prose or a nested
//: mapping, and reading one would let a document's illustration decide what a
//: run treats as the repository's declaration.
function topLevelKey(name) {
  return new RegExp(`^${name}\\s*:(.*)$`);
}

//: A one-line yaml **flow mapping**. The body excludes braces, so only a flat
//: mapping is accepted: a nested one is left to the unreadable notice rather
//: than half-parsed, and a flow *sequence* declares no keys to begin with.
function flowMapping(name) {
  return new RegExp(`^${name}\\s*:\\s*\\{([^{}]*)\\}\\s*(?:#.*)?$`);
}

//: One pair inside a flow-mapping body, scanned rather than split. The body used
//: to be cut on every comma, which is wrong for a comma inside a quoted value:
//: ``{release: "has,comma"}`` yielded the fragment ``"has`` — a name no branch
//: can have — and dropped the name actually declared (#488). The value
//: alternation tries both quoted forms before the bare one, so a quoted value is
//: taken whole and only an unquoted value stops at a comma.
const FLOW_PAIR = /\s*([A-Za-z_][A-Za-z0-9_.-]*)\s*:\s*(\x22[^\x22]*\x22|\x27[^\x27]*\x27|[^,]*)\s*/y;

//: The yaml indicators that make a value something other than the plain or
//: quoted scalar this reader understands: block and folded scalars, an anchor,
//: an alias, a flow mapping, a flow sequence. Refused rather than returned — a
//: line reader hands back the indicator itself, and a silent mis-derivation is
//: worse than a loud refusal (#510).
const INDICATOR = /^[|>&*{[]/;

/** Classify ``raw`` as a yaml scalar: ``{value, quoted, malformed}``.
 *
 * ``value`` keeps its quotes attached, so :data:`INDICATOR` reads the same
 * characters yaml would.
 *
 * **Quoting is recognised only where yaml recognises it — at the first character
 * of the value** (#510). A reader that tracked quote state anywhere had two
 * failures at once: ``verify: echo it's fine # x`` is a legal plain scalar whose
 * apostrophe is ordinary text, and that reader never cut the comment; and
 * ``verify: "a" && "b"`` has even parity, so stripping "one surrounding pair"
 * deleted two quotes that never delimited the whole value, leaving a fragment
 * ``sh`` re-tokenises into a different command.
 *
 * **In a plain scalar a ``#`` opens a comment only when whitespace precedes it**,
 * which is what yaml says. The two hook readers this module replaces cut at
 * ``indexOf("#")`` instead, so ``integration: dev#1`` declared a branch named
 * ``dev#1`` and they read ``dev`` — a branch the push guard then does not
 * protect. In a quoted scalar the ``#`` is inside the quotes and is data.
 */
function withoutComment(raw) {
  const text = String(raw).trim();
  const opener = text[0];
  if (opener !== DOUBLE && opener !== SINGLE) {
    for (let i = 0; i < text.length; i += 1) {
      if (text[i] === "#" && (i === 0 || /\s/.test(text[i - 1]))) {
        return { value: text.slice(0, i).trim(), quoted: false, malformed: false };
      }
    }
    return { value: text, quoted: false, malformed: false };
  }
  const close = text.indexOf(opener, 1);
  if (close === -1) return { value: text, quoted: true, malformed: true };
  const rest = text.slice(close + 1);
  // Only whitespace, or whitespace and a comment, may follow the closing quote.
  if (rest.trim() !== "" && !/^\s+#/.test(rest)) {
    return { value: text, quoted: true, malformed: true };
  }
  return { value: text.slice(0, close + 1), quoted: true, malformed: false };
}

/** ``value`` with its enclosing quote pair removed.
 *
 * Applied **only** to a value :func:`withoutComment` classified as one whole
 * enclosing quoted scalar. Its own first/last test is belt and braces: on a
 * value that merely begins and ends with a quote without being delimited by one
 * — ``"a" && "b"`` — that test is true and the result is a fragment.
 */
function unquote(value) {
  const first = value[0];
  const last = value[value.length - 1];
  if (value.length >= 2 && (first === DOUBLE || first === SINGLE) && last === first) {
    return value.slice(1, -1);
  }
  return value;
}

/** The plain string a scalar declares, or ``null`` when it declares none this
 * reader will hand back: empty, malformed quoting, or a yaml indicator. */
function plainScalar(raw) {
  const scalar = withoutComment(raw);
  if (scalar.malformed) return null;
  if (scalar.value === "" || INDICATOR.test(scalar.value)) return null;
  return (scalar.quoted ? unquote(scalar.value) : scalar.value) || null;
}

/** The yaml a source declares.
 *
 * A ``.yaml``/``.yml`` source is yaml throughout. A markdown spine declares its
 * configuration inside a fenced ``yaml`` block, and **only** the fenced blocks
 * are read: the three parsers this module replaces scanned the whole file, so a
 * ``branches:`` line in a prose example could decide the protected set. Every
 * spine the guidance has ever written fences the block, so nothing real loses a
 * declaration by this.
 *
 * A spine that declares a key **outside** any fence is the case that would go
 * silent: the extraction is empty, so the caller falls back with nothing on
 * stderr — the exact #487 harm the unreadable notice exists to prevent.
 * :func:`unfencedDeclaration` is what stops that, and :func:`readMap` reports
 * through it. The narrowing is still right; it just has to be audible.
 */
function configText(source, text) {
  if (/\.ya?ml$/i.test(source)) return text;
  const blocks = [];
  let open = false;
  for (const raw of text.split("\n")) {
    const line = raw.replace(/\r$/, "");
    if (/^\s*```/.test(line)) {
      // The opening fence names the language; the closing fence names nothing.
      open = open ? false : /^\s*```\s*ya?ml\s*$/i.test(line);
      continue;
    }
    if (open) blocks.push(line);
  }
  return blocks.join("\n");
}

/** True when ``text`` declares ``name`` at the top level somewhere the fenced
 * extraction did not reach — a markdown source whose configuration is outside any
 * ``yaml`` fence. Read from the **raw** text, and asked only when the fenced
 * extraction found nothing, so it can never widen what is parsed: its whole job
 * is to tell a silent miss from an honest absence.
 */
function unfencedDeclaration(text, name) {
  const KEY = topLevelKey(name);
  const FLOW = flowMapping(name);
  return text
    .split("\n")
    .some((raw) => {
      const line = raw.replace(/\r$/, "");
      return KEY.test(line) || FLOW.test(line.trim());
    });
}

/** Every top-level mapping declared under ``name``, as ``{key: value}``.
 *
 * Both legal spellings are read — the indented block and the one-line flow
 * mapping (#487) — and a quoted value in either is taken whole (#488). Any
 * spelling this reader cannot read yields ``null``, never a partial map: a
 * half-read ``branches:`` block is a branch the push guard silently stops
 * protecting.
 *
 * The **first** declaration wins, matching the block arm's own stop at the end
 * of the first block it finds. :func:`declaredVerify` deliberately does not
 * share that rule; see its own docstring.
 */
function blockMap(text, name) {
  const KEY = topLevelKey(name);
  const FLOW = flowMapping(name);
  const found = {};
  let declares = false;
  let entryIndent = -1;
  let inBlock = false;
  for (const raw of text.split("\n")) {
    const line = raw.replace(/\r$/, "");
    // Tabs are expanded for the indentation measurement **only**. Expanding
    // across the whole line rewrote a tab inside a declared value into two
    // spaces before the value was read, so the runner launched a command the
    // spine does not declare (#510).
    const tabsExpanded = line.replace(/\t/g, "  ");
    const lead = tabsExpanded.length - tabsExpanded.trimStart().length;
    const trimmed = line.trim();
    if (!inBlock) {
      const flow = FLOW.exec(trimmed);
      if (flow) {
        declares = true;
        return readFlowBody(flow[1]);
      }
      const key = KEY.exec(line);
      if (key === null) continue;
      declares = true;
      // A block opens when the key carries no value — asked through
      // :func:`withoutComment`, so the helper that decides comments on values
      // decides them in this position too. Requiring a literally empty key made
      // ``branches:   # a comment`` skip the mapping beneath it (#488).
      if (withoutComment(key[1]).value !== "") return null;
      inBlock = true;
      continue;
    }
    if (trimmed === "" || trimmed.startsWith("#")) continue;
    if (lead === 0) break; // back at the top level: the block ended
    if (entryIndent === -1) entryIndent = lead;
    if (lead !== entryIndent) return null;
    const pair = PAIR.exec(line);
    if (pair === null) return null;
    const value = plainScalar(pair[2]);
    if (value === null || Object.hasOwn(found, pair[1])) return null;
    found[pair[1]] = value;
  }
  if (!declares) return {};
  return Object.keys(found).length ? found : null;
}

/** The pairs inside a flow-mapping body, or ``null`` if any of it is unreadable. */
function readFlowBody(body) {
  const found = {};
  let cursor = 0;
  while (cursor < body.length) {
    FLOW_PAIR.lastIndex = cursor;
    const match = FLOW_PAIR.exec(body);
    if (match === null || match.index !== cursor) return null;
    const value = plainScalar(match[2]);
    if (value === null || Object.hasOwn(found, match[1])) return null;
    found[match[1]] = value;
    cursor = FLOW_PAIR.lastIndex;
    if (cursor === body.length) break;
    if (body[cursor] !== ",") return null;
    cursor += 1;
    if (cursor === body.length) return null; // a trailing comma declares nothing
  }
  return Object.keys(found).length ? found : null;
}

/** Every configuration source present under ``top``, in precedence order, as
 * ``{source, text}``. ``text`` is ``null`` for a source that exists but cannot be
 * read — a distinction both callers depend on and neither may skip past. */
function configSources(top) {
  const present = [];
  for (const name of SOURCES) {
    const source = path.join(top, name);
    try {
      // ``lstatSync`` distinguishes a missing source from a dangling link. A
      // link is still a declaration path, so treating it as missing would let an
      // unreadable ``harness.yaml`` select a stale spine instead.
      fs.lstatSync(source);
    } catch (err) {
      if (err && err.code === "ENOENT") continue;
      present.push({ source, text: null, raw: null });
      continue;
    }
    try {
      const raw = fs.readFileSync(source, "utf8");
      present.push({ source, text: configText(name, raw), raw });
    } catch (err) {
      void err;
      present.push({ source, text: null, raw: null });
    }
  }
  return present;
}

/** Read one top-level mapping out of the repo at ``top``.
 *
 * **The sources are searched, and the first that declares ``name`` answers.** A
 * source that is readable and simply carries no such block is not an answer of
 * "nothing" — a repo mid-migration has its spine and its ``CONTEXT.md`` side by
 * side, and the block is in one of them. The rule is the failure economics, not
 * an oversight: a missing ``branches:`` block falls back to a conservative set
 * that over-protects, which is cheap. The retired ``gateCommand`` stopped at the
 * first source that existed for the opposite reason — its value decided what
 * could mint evidence — and that reason left with it at #621.
 *
 * A source that exists but cannot be read, or that declares ``name`` in a
 * spelling this reader cannot parse, is **reported and stepped over** — the
 * shipped behaviour of the two parsers this replaces, kept deliberately. Nothing
 * is silent about it, because the notice names every such file, and the repo
 * whose spine is broken but whose ``CONTEXT.md`` still declares its real
 * integration branch keeps that branch protected rather than falling back to a
 * set that does not contain it.
 *
 * ``onUnreadable`` is called once with that source's path. Reporting is the
 * point of having it: without the notice, a declaration the parser could not
 * read is indistinguishable from one that agrees with the fallback (#487). Each
 * caller passes its own reporter so it keeps its own stderr tag.
 */
function readMap(top, name, onUnreadable) {
  for (const selected of configSources(top)) {
    if (selected.text === null) {
      if (onUnreadable) onUnreadable(selected.source);
      continue;
    }
    const map = blockMap(selected.text, name);
    if (map === null) {
      if (onUnreadable) onUnreadable(selected.source);
      continue;
    }
    if (Object.keys(map).length) return map;
    // Nothing was found. That is ordinary for a source carrying no such block —
    // and a silent miss for one that declares it outside a fence, which is the
    // one case the fenced narrowing can hide.
    if (selected.raw !== null && unfencedDeclaration(selected.raw, name)) {
      if (onUnreadable) onUnreadable(selected.source);
    }
  }
  return {};
}

/** The ``branches:`` map the repo at ``top`` declares — the branch roles. */
function declaredBranches(top, onUnreadable) {
  return readMap(top, "branches", onUnreadable);
}

/** The ``paths:`` map the repo at ``top`` declares — the tree's named directories.
 *
 * Read by ``hooks/test-lock-guard.js`` for ``paths.tests``, which is the only
 * thing that tells the test lock which files it governs. Guessing that set
 * instead would make the hook a false-deny factory, so an undeclared ``paths:``
 * leaves the lock inactive rather than protecting a directory nobody named.
 */
function declaredPaths(top, onUnreadable) {
  return readMap(top, "paths", onUnreadable);
}

// The public surface, narrowed to two at #621. `declaredBranches` serves the
// push-target advisory and `plugin-version.js`; `declaredPaths` serves the test
// lock. The other nine went with their consumers — the marker helper, the Stop
// hook and the refusing push guard — and `queueSettings`, `declaredLoop` and
// `declaredCommands` went because they never had a runtime consumer at all, only
// tests. An export with neither a caller nor a contract is a maintenance
// obligation for nobody.
//
// **Narrower, not looser.** Both survivors are read by a guard deciding
// something, so the scalar, flow-mapping and `onUnreadable` layers below are
// untouched: every spelling this reader cannot parse is still reported whole
// rather than half-read (#487, #488, #510).
module.exports = {
  declaredBranches,
  declaredPaths,
};
