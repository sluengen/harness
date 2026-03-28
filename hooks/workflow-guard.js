#!/usr/bin/env node

/**
 * Workflow Guard Hook (PreToolUse)
 *
 * Soft advisory warning when editing source code outside of a pipeline task
 * (i.e., not in a git worktree). Catches accidental off-pipeline edits.
 *
 * Never blocks — purely advisory.
 * Inspired by GSD's workflow-guard pattern.
 */

const fs = require("fs");
const path = require("path");
const { execSync } = require("child_process");

// Directories containing source code that should go through the pipeline
const PROTECTED_DIRS = ["app/", "frontend/src/", "tests/"];

// Files that are always safe to edit directly
const SAFE_PATTERNS = [
  /^\.claude\//,
  /^\.github\//,
  /^specs\//,
  /^context\//,
  /^bugs\//,
  /^reviews\//,
  /^hooks\//,
  /CLAUDE\.md$/,
  /manifest\.yaml$/,
  /roadmap\.md$/,
  /\.gitignore$/,
  /\.env/,
  /settings\.json$/,
  /package\.json$/,
  /pyproject\.toml$/,
];

function isInWorktree() {
  try {
    // In a linked worktree, .git is a file containing "gitdir: ...", not a directory
    const gitPath = path.join(process.cwd(), ".git");
    const stat = fs.statSync(gitPath);
    return stat.isFile(); // File = worktree, Directory = main repo
  } catch {
    return false;
  }
}

function isOnMainBranch() {
  try {
    const branch = execSync("git rev-parse --abbrev-ref HEAD", {
      encoding: "utf8",
      timeout: 5000,
    }).trim();
    return branch === "main" || branch === "master";
  } catch {
    return false;
  }
}

function main() {
  let input;
  try {
    input = JSON.parse(fs.readFileSync("/dev/stdin", "utf8"));
  } catch {
    process.stdout.write(JSON.stringify({ continue: true }));
    return;
  }

  const toolName = input.tool_name || "";

  // Only check Write and Edit
  if (toolName !== "Write" && toolName !== "Edit") {
    process.stdout.write(JSON.stringify({ continue: true }));
    return;
  }

  const toolInput = input.tool_input || {};
  const filePath = toolInput.file_path || "";

  // Normalize to relative path
  const cwd = process.cwd();
  const relativePath = filePath.startsWith(cwd)
    ? filePath.slice(cwd.length + 1)
    : filePath;

  // Skip safe patterns
  if (SAFE_PATTERNS.some((p) => p.test(relativePath))) {
    process.stdout.write(JSON.stringify({ continue: true }));
    return;
  }

  // Check if editing a protected directory
  const isProtected = PROTECTED_DIRS.some((dir) => relativePath.startsWith(dir));
  if (!isProtected) {
    process.stdout.write(JSON.stringify({ continue: true }));
    return;
  }

  // If we're in a worktree or not on main, it's fine — pipeline is being followed
  if (isInWorktree() || !isOnMainBranch()) {
    process.stdout.write(JSON.stringify({ continue: true }));
    return;
  }

  // On main, editing source code, not in a worktree — warn
  const result = {
    continue: true,
    additionalContext:
      `[WORKFLOW GUARD — direct edit on main] ` +
      `You are editing ${relativePath} directly on main outside of a pipeline task. ` +
      `This change won't be tracked in the manifest or go through the reviewer. ` +
      `Consider creating a branch or manifest entry first. ` +
      `If this is an intentional quick fix, proceed — but commit with a clear message.`,
  };

  process.stdout.write(JSON.stringify(result));
}

main();
