#!/usr/bin/env node
// guidance:hook-git-push-guard@0.3.0
/**
 * Git force-push guard (PreToolUse: Bash).
 *
 * Denies a Bash tool call that force-pushes. CAL-1001 closed the ``+refspec``
 * bypass with ``Bash(...)`` deny globs in ``.claude/settings.json``, but globs
 * over the raw command string cannot cover the full class: short-flag bundles
 * (``-f``, ``-fq``, ``-qf``), ``--force`` in a trailing position, a ``+refspec``
 * with the remote omitted, and ``git -c … push`` / ``git -C … push`` reordering
 * all slip past a fixed glob set. This hook *tokenizes* the command instead and
 * decides from the parse. The deny globs stay as belt-and-braces; this is the
 * parser layer on top (CAL-1031).
 *
 * A command is a force-push when a ``git push`` sub-command carries any of:
 *   - ``--force`` (any position),
 *   - ``--force-with-lease`` (plain or ``=<value>``),
 *   - a short-flag bundle containing ``f`` (``-f``, ``-fq``, ``-qf`` …), or
 *   - a refspec operand beginning with ``+`` (``+HEAD:dev``).
 *
 * **Command substitution.** ``$(…)`` and backticks execute inline, so
 * ``git push origin $(echo dev) --force`` really force-pushes and
 * ``git $(echo push) --force origin dev`` hides the sub-command from a naive
 * split (and from the raw-string deny globs). The lexer therefore captures a
 * substitution as an *opaque token* (it does not sever the surrounding command)
 * and also records its body, which is analysed recursively so an inner
 * ``echo $(git push --force)`` is caught too. When a command substitution lands
 * in a position that decides push-ness or a force form (the sub-command slot, or
 * any ``git push`` argument), the guard **fails closed** — it cannot statically
 * prove the expansion is safe. (Plain parameter expansion — ``$VAR`` / ``${VAR}``
 * — is a weaker, contrived class and is deliberately out of scope: closing it
 * would deny every ``git push origin $BRANCH``.)
 *
 * **Nested shell scripts.** ``sh -c "<script>"`` / ``bash -c`` (and bundled
 * ``-lc`` etc.) and ``eval "<script>"`` run their string argument as a shell
 * command, so ``sh -c "git push --force origin dev"`` force-pushes while the
 * outer command's executable is ``sh``. The guard extracts that inline script
 * and analyses it recursively with the same lexer.
 *
 * **ANSI-C quoting.** ``$'…'`` decodes backslash escapes (``$'\x67it'`` → ``git``),
 * which would otherwise obfuscate ``git`` / ``push`` / ``--force`` past both this
 * hook and the raw-string deny globs. The lexer decodes ``$'…'`` (hex, octal,
 * unicode and the standard letter escapes) so the real word is seen. There is no
 * false-positive cost — no legitimate push hex-escapes its words.
 *
 * **Command wrappers and path-qualified executables.** A wrapper runs its
 * operands as the real command, so ``nohup git push --force …`` force-pushes
 * while the outer executable is ``nohup``; and ``/usr/bin/git`` is the same
 * program as ``git``. The guard therefore matches executables on their
 * **basename** (as it already did for nested shells) and resolves past a leading
 * wrapper to the command it runs. Because a wrapper may carry its own options and
 * even a mandatory operand (``timeout 60 git …``, ``nice -n 5 git …``), the guard
 * **scans** the wrapper's operands for the command rather than modelling each
 * wrapper's option grammar — one unmodelled option would silently re-open the
 * class, which is the failure this design rules out. The scan runs only when a
 * wrapper prefix is present, so ``echo git push --force …`` (which merely prints)
 * is untouched.
 *
 * **Brace groups and functions.** ``{ git push --force; }`` and
 * ``f() { git push --force; }; f`` run their body in the current shell, so the
 * force-push is inline and literal — the lexer treats a word-boundary ``{`` / ``}``
 * as a command separator (like ``(`` / ``)``) so the body command is analysed.
 *
 * **A shell fed a script it can't read.** A bare shell (``sh`` / ``bash`` / …
 * with no ``-c``) that reads its script from **stdin via a pipe** (``… | bash``),
 * a **here-string / heredoc** (``sh <<< …``, ``sh <<EOF``) or a **process
 * substitution** (``bash <(…)``) runs a script the hook cannot resolve
 * statically. Such an invocation **fails closed**, matching the
 * command-substitution policy.
 *
 * **Explicit scope boundary.** A shell is Turing-complete, so no static parser
 * can catch every way to reach ``git push --force``. Beyond the classes above,
 * these are deliberately **out of scope** — closing them is undecidable or would
 * deny broad legitimate use, and the hook is defence-in-depth atop the deny globs
 * and (once the repo is public) server-side branch protection, not the sole gate:
 *   - parameter expansion of the command or its flags (``g=git; $g push --force``;
 *     ``F=--force; git push $F …``) — same class as the ``$VAR`` refspec case;
 *   - a shell running a script **file** whose contents are unknowable
 *     (``bash deploy.sh``);
 *   - arbitrary generation / decoding of the command text (``base64 -d``, a
 *     built-up string), and a dispatcher that runs a command it *builds* rather
 *     than one written literally in the call (``find -exec``; ``xargs`` fed a
 *     generated command). The literal ``xargs git push --force …`` spelling **is**
 *     caught — it is a wrapper, not a generated command — but a dispatcher
 *     assembling the push from its input is not statically knowable.
 * Adding a new obfuscation vector to this list (with a one-line justification) is
 * a valid resolution — the hook must never *silently* miss a class.
 *
 * **Authoritative control.** This hook is defence-in-depth, not the control of
 * record. It is a denylist parser over a Turing-complete surface, so its coverage
 * is inherently a moving target — the class above was found *after* four rounds of
 * hardening. The authoritative protection for the branches that matter is
 * **server-side branch protection** on ``dev``/``main``, which no client-side
 * parse can be argued past; this hook narrows the window until that is in place
 * and remains useful afterwards only as fast local feedback.
 *
 * On a force-push it emits the current PreToolUse deny contract
 * (``hookSpecificOutput.permissionDecision: "deny"``, exit 0). Otherwise it
 * defers to the normal permission flow (``{continue:true}`` — it does NOT
 * pre-approve, so the deny globs and normal checks still apply). It fails open
 * on any internal error, matching the repo's other hooks: the deny globs remain
 * the backstop, so a crashing guard must not wedge every Bash call.
 */
"use strict";

/** Capture a ``$(…)`` body from ``start`` (just past ``$(``) to its matching
 * ``)``, honouring nested ``(``/``)``. Returns ``[body, indexAfterClose]``. */
function captureParenSub(s, start) {
  let depth = 1;
  let j = start;
  let body = "";
  while (j < s.length && depth > 0) {
    const ch = s[j];
    if (ch === "(") depth++;
    else if (ch === ")") {
      depth--;
      if (depth === 0) {
        j++;
        break;
      }
    }
    body += ch;
    j++;
  }
  return [body, j];
}

//: The single-letter ANSI-C escapes (``$'\n'`` etc.).
const ANSI_C_LETTER = {
  n: "\n",
  t: "\t",
  r: "\r",
  a: "\x07",
  b: "\b",
  f: "\f",
  v: "\v",
  e: "\x1b",
  E: "\x1b",
  "\\": "\\",
  "'": "'",
  '"': '"',
  "?": "?",
};

/** Decode an ANSI-C ``$'…'`` body from ``start`` (just past ``$'``) to its
 * closing ``'``, resolving ``\xHH``, octal ``\ooo``, ``\uHHHH`` / ``\UHHHHHHHH``
 * and the letter escapes. Returns ``[decoded, indexAfterClose]``. Decoding is
 * what defeats hex/octal obfuscation of ``git`` / ``push`` / ``--force``. */
function captureAnsiC(s, start) {
  let j = start;
  let out = "";
  while (j < s.length && s[j] !== "'") {
    if (s[j] === "\\" && j + 1 < s.length) {
      const e = s[j + 1];
      let m;
      if (e === "x" && (m = /^[0-9A-Fa-f]{1,2}/.exec(s.slice(j + 2)))) {
        out += String.fromCharCode(parseInt(m[0], 16));
        j += 2 + m[0].length;
      } else if (e >= "0" && e <= "7" && (m = /^[0-7]{1,3}/.exec(s.slice(j + 1)))) {
        out += String.fromCharCode(parseInt(m[0], 8) & 0xff);
        j += 1 + m[0].length;
      } else if (e === "u" && (m = /^[0-9A-Fa-f]{1,4}/.exec(s.slice(j + 2)))) {
        out += String.fromCharCode(parseInt(m[0], 16));
        j += 2 + m[0].length;
      } else if (e === "U" && (m = /^[0-9A-Fa-f]{1,8}/.exec(s.slice(j + 2)))) {
        out += String.fromCodePoint(parseInt(m[0], 16));
        j += 2 + m[0].length;
      } else if (e in ANSI_C_LETTER) {
        out += ANSI_C_LETTER[e];
        j += 2;
      } else {
        out += e; // unknown escape: keep the char literally
        j += 2;
      }
    } else {
      out += s[j];
      j++;
    }
  }
  return [out, j + 1]; // skip the closing quote
}

/** Capture a backtick body from ``start`` (just past the opening backtick) to
 * the next unescaped backtick. Returns ``[body, indexAfterClose]``. */
function captureBacktick(s, start) {
  let j = start;
  let body = "";
  while (j < s.length && s[j] !== "`") {
    if (s[j] === "\\" && j + 1 < s.length) {
      body += s[j + 1];
      j += 2;
    } else {
      body += s[j];
      j++;
    }
  }
  return [body, j + 1];
}

/** Capture a ``${…}`` parameter expansion from ``start`` (just past ``${``) to
 * its matching ``}``. Returns ``[text, indexAfterClose]``. Kept opaque so a
 * word-boundary ``{`` separator never severs a ``${VAR}``; not recursed into (a
 * parameter is a value, not a command). */
function captureParam(s, start) {
  let depth = 1;
  let j = start;
  let text = "";
  while (j < s.length && depth > 0) {
    const ch = s[j];
    if (ch === "{") depth++;
    else if (ch === "}") {
      depth--;
      if (depth === 0) {
        j++;
        break;
      }
    }
    text += ch;
    j++;
  }
  return [text, j];
}

/** Lex a shell command string.
 *
 * Returns ``{commands, substitutions}``. ``commands`` is a list of
 * ``{tokens, pipedInto}`` objects, split on the separators ``; & | ( ) { }`` and
 * newline (``{`` / ``}`` only at a word boundary, so a brace group's body is its
 * own command); ``pipedInto`` marks a command that is the sink of a ``|`` (its
 * stdin is another command's output). ``substitutions`` is the list of ``$(…)`` /
 * backtick bodies, kept for recursive analysis. Single/double quotes, backslash
 * escapes and ``#`` comments are honoured; ``$(…)`` and ``${…}`` are captured as
 * opaque tokens so they never sever the surrounding command. A pragmatic lexer
 * for *detecting* a git-push invocation, not a full shell parser. */
function lex(command) {
  const commands = [];
  const substitutions = [];
  let cur = [];
  let token = "";
  let hasToken = false;
  let curPiped = false; // is the command being built the sink of a '|'?
  let nextPiped = false; // does the next command follow a single '|'?
  let i = 0;
  const n = command.length;

  const endToken = () => {
    if (hasToken) {
      cur.push(token);
      token = "";
      hasToken = false;
    }
  };
  const endCommand = () => {
    endToken();
    if (cur.length) {
      commands.push({ tokens: cur, pipedInto: curPiped });
      cur = [];
    }
    curPiped = nextPiped;
    nextPiped = false;
  };

  while (i < n) {
    const c = command[i];

    if (c === "$" && command[i + 1] === "'") {
      const [decoded, next] = captureAnsiC(command, i + 2);
      token += decoded;
      hasToken = true;
      i = next;
      continue;
    }
    if (c === "$" && command[i + 1] === "(") {
      const [body, next] = captureParenSub(command, i + 2);
      substitutions.push(body);
      token += "$(" + body + ")";
      hasToken = true;
      i = next;
      continue;
    }
    if (c === "$" && command[i + 1] === "{") {
      const [text, next] = captureParam(command, i + 2);
      token += "${" + text + "}";
      hasToken = true;
      i = next;
      continue;
    }
    if (c === "`") {
      const [body, next] = captureBacktick(command, i + 1);
      substitutions.push(body);
      token += "`" + body + "`";
      hasToken = true;
      i = next;
      continue;
    }
    if (c === "'") {
      hasToken = true;
      i++;
      while (i < n && command[i] !== "'") {
        token += command[i];
        i++;
      }
      i++; // closing quote
      continue;
    }
    if (c === '"') {
      hasToken = true;
      i++;
      while (i < n && command[i] !== '"') {
        if (command[i] === "$" && command[i + 1] === "(") {
          const [body, next] = captureParenSub(command, i + 2);
          substitutions.push(body);
          token += "$(" + body + ")";
          i = next;
        } else if (command[i] === "`") {
          const [body, next] = captureBacktick(command, i + 1);
          substitutions.push(body);
          token += "`" + body + "`";
          i = next;
        } else if (command[i] === "\\" && i + 1 < n && "\"\\$`".includes(command[i + 1])) {
          token += command[i + 1];
          i += 2;
        } else {
          token += command[i];
          i++;
        }
      }
      i++; // closing quote
      continue;
    }
    if (c === "\\") {
      if (i + 1 < n) {
        if (command[i + 1] !== "\n") {
          token += command[i + 1];
          hasToken = true;
        }
        i += 2;
        continue;
      }
      i++;
      continue;
    }
    // '#' starts a comment only at the beginning of a word.
    if (c === "#" && !hasToken) {
      while (i < n && command[i] !== "\n") i++;
      continue;
    }
    // Word-boundary '{' / '}' are brace-group delimiters (a brace group runs its
    // body in the current shell) — separate so the body is its own command. Only
    // at a word boundary: '${…}' is consumed above, and 'dev{a,b}' keeps '{' as
    // an ordinary char mid-token.
    if ((c === "{" || c === "}") && !hasToken) {
      endCommand();
      i++;
      continue;
    }
    // Command separators (bare '(' / ')' are subshell grouping — '$(' was
    // already consumed as a substitution above). A single '|' pipes the next
    // command's stdin from this one's output.
    if (c === "\n" || c === ";" || c === "&" || c === "|" || c === "(" || c === ")") {
      const doubled =
        (c === "&" && command[i + 1] === "&") || (c === "|" && command[i + 1] === "|");
      if (c === "|" && !doubled) nextPiped = true;
      endCommand();
      if (doubled) i++;
      i++;
      continue;
    }
    if (c === " " || c === "\t" || c === "\r") {
      endToken();
      i++;
      continue;
    }
    token += c;
    hasToken = true;
    i++;
  }
  endCommand();
  return { commands, substitutions };
}

// A leading ``NAME=value`` environment assignment.
const ASSIGNMENT = /^[A-Za-z_][A-Za-z0-9_]*=/;
// Leading command wrappers whose remaining args are still the real command:
// ``nohup git push --force …`` really force-pushes. A wrapper may carry its own
// options and even a mandatory operand (``timeout 60 git …``), so stripping the
// wrapper name alone does not reach the command — see :func:`resolveCommand`.
const WRAPPERS = new Set([
  "env",
  "nohup",
  "command",
  "exec",
  "nice",
  "ionice",
  "setsid",
  "stdbuf",
  "timeout",
  "xargs",
  "sudo",
  "doas",
]);
// git *global* options that consume the following token as their argument, so
// the sub-command is not mistaken for that argument.
const GIT_GLOBAL_WITH_ARG = new Set([
  "-C",
  "-c",
  "--git-dir",
  "--work-tree",
  "--namespace",
  "--super-prefix",
  "--config-env",
]);

/** True if a token carries a command substitution (``$(…)`` or backticks) — an
 * inline-executed expansion the guard cannot resolve statically. */
function hasCommandSubstitution(token) {
  return token.includes("$(") || token.includes("`");
}

// Shells that run an inline script from ``-c`` (matched on the executable's
// basename, so ``/bin/sh`` counts).
const SHELLS = new Set(["sh", "bash", "zsh", "dash", "ash", "ksh"]);

/** Drop leading ``NAME=value`` assignments and ``env`` wrappers. */
function stripPrefixes(tokens) {
  let i = 0;
  let sawWrapper = false;
  while (i < tokens.length && (ASSIGNMENT.test(tokens[i]) || WRAPPERS.has(basename(tokens[i])))) {
    if (!ASSIGNMENT.test(tokens[i])) sawWrapper = true;
    i++;
  }
  return { tokens: tokens.slice(i), sawWrapper };
}

/** The basename of an executable token: ``/usr/bin/git`` → ``git``. The guard
 * matches executables on their basename, since a path-qualified spelling runs
 * the same program. */
function basename(token) {
  return token.split("/").pop();
}

/** The tokens of the real command, resolved past any wrapper prefix.
 *
 * A wrapper's own options — and, for ``timeout``, a mandatory ``DURATION``
 * operand — sit between the wrapper and the command, so ``stripPrefixes`` alone
 * leaves ``timeout 60 git push --force`` pointing at ``60``. Rather than model
 * each wrapper's option grammar (the brittle half: one unmodelled option
 * silently re-opens the class), scan the wrapper's operands for the real
 * command. The scan applies **only** when a wrapper prefix was actually present,
 * so an ordinary command is untouched — ``echo git push --force …`` prints a
 * string and is not a wrapper, so it is never scanned. Failure mode is
 * deliberate: an over-broad match denies a command that was not a force-push,
 * which is recoverable; an under-broad one lets a force-push through, which is
 * not. */
function resolveCommand(rawTokens) {
  const { tokens, sawWrapper } = stripPrefixes(rawTokens);
  if (tokens.length === 0 || isGit(tokens[0]) || !sawWrapper) return tokens;
  const k = tokens.findIndex(isGit);
  return k > 0 ? tokens.slice(k) : tokens;
}

/** True if an executable token invokes ``git``, by basename — so ``git``,
 * ``/usr/bin/git`` and ``./git`` all match. (ANSI-C spellings such as
 * ``$'\x67it'`` are already decoded to ``git`` by the lexer.) */
function isGit(token) {
  return basename(token) === "git";
}

/** Inline shell scripts a command runs as its own shell — the ``-c`` argument
 * of ``sh``/``bash``/… and the joined arguments of ``eval`` — to be analysed
 * recursively. Without this, ``sh -c "git push --force …"`` would pass because
 * the outer executable is ``sh``, not ``git``. */
function nestedScripts(rawTokens) {
  const { tokens } = stripPrefixes(rawTokens);
  if (tokens.length === 0) return [];
  const exec = basename(tokens[0]);
  if (SHELLS.has(exec)) {
    for (let k = 1; k < tokens.length; k++) {
      const t = tokens[k];
      if (/^-[A-Za-z]*c[A-Za-z]*$/.test(t)) {
        // ``-c`` (possibly bundled, e.g. ``-lc``): the next token is the script.
        return k + 1 < tokens.length ? [tokens[k + 1]] : [];
      }
      if (!t.startsWith("-")) break; // first operand, no ``-c``: a script *file*, not inline
    }
    return [];
  }
  if (exec === "eval") return [tokens.slice(1).join(" ")];
  return [];
}

/** True if a command is a bare shell (``sh``/``bash``/… with no ``-c`` script)
 * that reads its script from a channel the hook cannot resolve statically: its
 * stdin is piped from another command (``… | bash``), or it has an input
 * redirect — a here-string (``sh <<< …``), heredoc (``sh <<EOF``) or process
 * substitution (``bash <(…)``). Such an invocation runs an unknown script, so
 * the guard fails closed (mirroring the command-substitution policy). A bare
 * shell running a script *file* (``bash deploy.sh`` — no pipe, no redirect) is
 * out of scope: its contents are unknowable and denying it is too broad. */
function isBareShellFedExternally(tokens, pipedInto) {
  const stripped = stripPrefixes(tokens);
  if (stripped.tokens.length === 0) return false;
  if (!SHELLS.has(basename(stripped.tokens[0]))) return false;
  if (nestedScripts(tokens).length > 0) return false; // has a -c script; analysed directly
  const hasInputRedirect = stripped.tokens.some((t) => t.includes("<"));
  return pipedInto || hasInputRedirect;
}

/** True if a single command's tokens are a ``git push`` that force-pushes (or a
 * ``git`` command whose push-ness / force form is obscured by a command
 * substitution the guard fails closed on). */
function commandForcePushes(rawTokens) {
  const tokens = resolveCommand(rawTokens);
  if (tokens.length === 0 || !isGit(tokens[0])) return false;

  // Walk past git's global options to the sub-command.
  let i = 1;
  while (i < tokens.length) {
    const t = tokens[i];
    if (GIT_GLOBAL_WITH_ARG.has(t)) {
      i += 2;
      continue;
    }
    if (t.startsWith("-")) {
      i += 1; // a ``--opt=value`` or standalone global flag
      continue;
    }
    break;
  }
  if (i >= tokens.length) return false;
  const subcommand = tokens[i];
  if (subcommand !== "push") {
    // The sub-command slot is a command substitution → it could resolve to
    // ``push`` with a force form. Fail closed.
    return hasCommandSubstitution(subcommand);
  }

  // Scan the push arguments for any force form.
  let sawDoubleDash = false;
  for (let j = i + 1; j < tokens.length; j++) {
    const t = tokens[j];
    if (!sawDoubleDash && t === "--") {
      sawDoubleDash = true;
      continue;
    }
    if (!sawDoubleDash && t.length > 1 && t.startsWith("-")) {
      if (t === "--force") return true;
      if (t === "--force-with-lease" || t.startsWith("--force-with-lease=")) return true;
      // short-flag bundle (single dash, letters only) containing 'f'
      if (/^-[A-Za-z]+$/.test(t) && t.includes("f")) return true;
      if (hasCommandSubstitution(t)) return true; // an option that could expand to a force flag
      continue;
    }
    // an operand (a refspec): a leading '+' forces that refspec …
    if (t.startsWith("+")) return true;
    // … and a substitution operand could expand to a +refspec or a force flag.
    if (hasCommandSubstitution(t)) return true;
  }
  return false;
}

/** True if ``command`` — or any command substitution or inline shell script
 * nested within it — force-pushes (or is a bare shell fed an unreadable script,
 * which fails closed). Recursion is bounded by the finite nesting depth. */
function forcePushAnywhere(command, depth = 0) {
  if (depth > 16) return false; // pathological-nesting backstop
  const { commands, substitutions } = lex(command);
  for (const { tokens, pipedInto } of commands) {
    if (commandForcePushes(tokens)) return true;
    if (isBareShellFedExternally(tokens, pipedInto)) return true;
    for (const script of nestedScripts(tokens)) {
      if (forcePushAnywhere(script, depth + 1)) return true;
    }
  }
  return substitutions.some((body) => forcePushAnywhere(body, depth + 1));
}

function readStdin() {
  try {
    return JSON.parse(require("fs").readFileSync(0, "utf8"));
  } catch {
    return {};
  }
}

function deny(command) {
  const reason =
    `[GIT-PUSH-GUARD] Blocked a force-push. The command ${JSON.stringify(command)} force-pushes ` +
    `(a --force / -f / --force-with-lease flag, or a +<refspec> — possibly via a command ` +
    `substitution), which can overwrite history on a shared branch. Land work through a reviewed ` +
    `merge (the close verb), not a force-push. If a force-push is genuinely required, a human ` +
    `must run it.`;
  process.stdout.write(
    JSON.stringify({
      hookSpecificOutput: {
        hookEventName: "PreToolUse",
        permissionDecision: "deny",
        permissionDecisionReason: reason,
      },
    })
  );
}

/** Defer to the normal permission flow — do NOT pre-approve. */
function passThrough() {
  process.stdout.write(JSON.stringify({ continue: true }));
}

function main() {
  const input = readStdin();
  if ((input.tool_name || "") !== "Bash") return passThrough();
  const command = (input.tool_input && input.tool_input.command) || "";
  if (forcePushAnywhere(command)) return deny(command);
  passThrough();
}

if (require.main === module) {
  try {
    main();
  } catch {
    // Fail open: the deny globs remain the backstop; never wedge every Bash call.
    process.stdout.write(JSON.stringify({ continue: true }));
  }
}

// The recognition sets whose *membership* decides push-ness. Exported so the
// guard's own test suite can derive its per-member deny corpus from the real
// values rather than restating them (CAL-1088) — a set cannot gain a member
// without a matching deny case. The ``require.main === module`` guard above means
// importing the module for this introspection never runs the hook (which would
// block reading stdin); run directly as a hook, ``main()`` still executes.
module.exports = { WRAPPERS, SHELLS, GIT_GLOBAL_WITH_ARG };
