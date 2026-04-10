#!/usr/bin/env node

/**
 * Pipeline Guard Hook (PreToolUse)
 *
 * Advisory warning when editing source code on a feature branch without
 * a corresponding pipeline proposal in specs/changes/.
 *
 * Catches the scenario where the orchestrator jumps straight to code
 * without creating a change folder and proposal first.
 *
 * Never blocks — purely advisory. Debounced to fire once per session.
 *
 * PROJECT: Edit PROTECTED_DIRS below to match your project's source layout.
 */

const fs = require("fs");
const path = require("path");
const { execSync } = require("child_process");

// Directories containing source code that should go through the pipeline.
// PROJECT: Adjust these paths to match your project structure.
const PROTECTED_DIRS = [
  "src/",        // generic JS/TS projects
  "app/",        // Python (FastAPI, Django, etc.)
  "lib/",        // library source
  "frontend/src/", // full-stack projects with a frontend subdir
  "tests/",
];

// Files that are always safe to edit directly
const SAFE_PATTERNS = [
  /^\.claude\//,
  /^\.github\//,
  /^specs\//,
  /^context\//,
  /^bugs\//,
  /^reviews\//,
  /^hooks\//,
  /^releases\//,
  /^strategy\//,
  /CLAUDE\.md$/,
  /manifest\.yaml$/,
  /\.gitignore$/,
  /\.env/,
  /settings\.json$/,
  /package\.json$/,
  /pyproject\.toml$/,
];

// Debounce: only warn once per session
const MARKER_FILE = path.join("/tmp", "claude-pipeline-guard-warned");

function hasWarned() {
  try {
    const stat = fs.statSync(MARKER_FILE);
    const ageMs = Date.now() - stat.mtimeMs;
    return ageMs < 2 * 60 * 60 * 1000;
  } catch {
    return false;
  }
}

function markWarned() {
  try {
    fs.writeFileSync(MARKER_FILE, String(Date.now()));
  } catch {
    // ignore
  }
}

function getCurrentBranch() {
  try {
    return execSync("git rev-parse --abbrev-ref HEAD", {
      encoding: "utf8",
      timeout: 5000,
    }).trim();
  } catch {
    return null;
  }
}

function isInWorktree() {
  try {
    const gitPath = path.join(process.cwd(), ".git");
    const stat = fs.statSync(gitPath);
    return stat.isFile(); // File = worktree, Directory = main repo
  } catch {
    return false;
  }
}

function branchHasProposal() {
  // Check if any specs/changes/*/proposal.md exists on this branch
  // relative to its upstream base (staging or main).
  const bases = ["origin/staging", "origin/main"];
  for (const base of bases) {
    try {
      const mergeBase = execSync(`git merge-base ${base} HEAD`, {
        encoding: "utf8",
        timeout: 5000,
      }).trim();

      const count = parseInt(
        execSync(`git rev-list --count ${mergeBase}..HEAD`, {
          encoding: "utf8",
          timeout: 5000,
        }).trim(),
        10
      );

      if (count === 0) {
        break;
      }

      const diff = execSync(
        `git diff --name-only ${mergeBase}..HEAD -- "specs/changes/"`,
        { encoding: "utf8", timeout: 5000 }
      ).trim();
      return diff.split("\n").some((f) => f.endsWith("/proposal.md"));
    } catch {
      continue;
    }
  }

  // Fallback: check git status for staged/unstaged proposal.md files
  try {
    const status = execSync(
      'git status --porcelain -- "specs/changes/*/proposal.md"',
      { encoding: "utf8", timeout: 5000 }
    ).trim();
    if (status.length > 0) return true;
  } catch {
    // ignore
  }

  return false;
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

  // Only check protected source directories
  const isProtected = PROTECTED_DIRS.some((dir) => relativePath.startsWith(dir));
  if (!isProtected) {
    process.stdout.write(JSON.stringify({ continue: true }));
    return;
  }

  // Skip if on main (workflow-guard.js handles that case)
  const branch = getCurrentBranch();
  if (!branch || branch === "main" || branch === "master") {
    process.stdout.write(JSON.stringify({ continue: true }));
    return;
  }

  // Skip if in a worktree (agent-managed, pipeline is assumed)
  if (isInWorktree()) {
    process.stdout.write(JSON.stringify({ continue: true }));
    return;
  }

  // Skip if already warned this session
  if (hasWarned()) {
    process.stdout.write(JSON.stringify({ continue: true }));
    return;
  }

  // Check if a pipeline proposal exists for this branch's work
  if (branchHasProposal()) {
    process.stdout.write(JSON.stringify({ continue: true }));
    return;
  }

  // No proposal found — warn
  markWarned();

  const result = {
    continue: true,
    additionalContext:
      `[PIPELINE GUARD — no proposal found] ` +
      `You are editing source code (${relativePath}) on branch '${branch}' ` +
      `but no specs/changes/*/proposal.md exists for this work. ` +
      `This means the pipeline has been bypassed — no proposal, no reviewer, no manifest tracking. ` +
      `Use /start-task <task-id> to enter the pipeline, or create a change folder with a proposal ` +
      `before writing code. If this is an intentional hotfix, proceed — but document why.`,
  };

  process.stdout.write(JSON.stringify(result));
}

main();
