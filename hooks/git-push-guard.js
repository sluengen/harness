#!/usr/bin/env node
// guidance:hook-git-push-guard@0.1.0
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
 * On a force-push it emits the current PreToolUse deny contract
 * (``hookSpecificOutput.permissionDecision: "deny"``, exit 0). Otherwise it
 * defers to the normal permission flow (``{continue:true}`` — it does NOT
 * pre-approve, so the deny globs and normal checks still apply). It fails open
 * on any internal error, matching the repo's other hooks: the deny globs remain
 * the backstop, so a crashing guard must not wedge every Bash call.
 */
"use strict";

/** Lex a shell command string into a list of commands (each a list of tokens).
 *
 * Splits on the command separators ``; & | ( ) `` and newline, honours single
 * and double quotes and backslash escapes, and drops ``#`` comments. It is a
 * pragmatic lexer for *detecting* a git-push invocation, not a full shell
 * parser — it does not expand variables or command substitutions, but a
 * substitution's inner command still lexes as its own command because ``(`` and
 * a backtick are separators. */
function lex(command) {
  const commands = [];
  let cur = [];
  let token = "";
  let hasToken = false;
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
      commands.push(cur);
      cur = [];
    }
  };

  while (i < n) {
    const c = command[i];

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
        if (command[i] === "\\" && i + 1 < n && "\"\\$`".includes(command[i + 1])) {
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
    // Command separators.
    if (c === "\n" || c === ";" || c === "&" || c === "|" || c === "(" || c === ")" || c === "`") {
      endCommand();
      if ((c === "&" && command[i + 1] === "&") || (c === "|" && command[i + 1] === "|")) i++;
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
  return commands;
}

// A leading ``NAME=value`` environment assignment.
const ASSIGNMENT = /^[A-Za-z_][A-Za-z0-9_]*=/;
// Leading command wrappers whose remaining args are still the real command.
const WRAPPERS = new Set(["env"]);
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

/** Drop leading ``NAME=value`` assignments and ``env`` wrappers. */
function stripPrefixes(tokens) {
  let i = 0;
  while (i < tokens.length && (ASSIGNMENT.test(tokens[i]) || WRAPPERS.has(tokens[i]))) i++;
  return tokens.slice(i);
}

/** True if a single command's tokens are a ``git push`` that force-pushes. */
function isForcePush(rawTokens) {
  const tokens = stripPrefixes(rawTokens);
  if (tokens.length === 0 || tokens[0] !== "git") return false;

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
  if (i >= tokens.length || tokens[i] !== "push") return false;

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
      continue; // some other option
    }
    // an operand (a refspec): a leading '+' forces that refspec
    if (t.startsWith("+")) return true;
  }
  return false;
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
    `(a --force / -f / --force-with-lease flag, or a +<refspec>), which can overwrite history on a ` +
    `shared branch. Land work through a reviewed merge (the close verb), not a force-push. If a ` +
    `force-push is genuinely required, a human must run it.`;
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
  if (lex(command).some(isForcePush)) return deny(command);
  passThrough();
}

try {
  main();
} catch {
  // Fail open: the deny globs remain the backstop; never wedge every Bash call.
  process.stdout.write(JSON.stringify({ continue: true }));
}
