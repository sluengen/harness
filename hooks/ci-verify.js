#!/usr/bin/env node

/**
 * CI Verify Hook (PostToolUse on Bash)
 *
 * Detects `git push` commands and reminds Claude to verify CI
 * before proceeding. Outputs the current branch and PR number so Claude
 * can poll checks without manual intervention.
 */

const { execSync } = require("child_process");
const fs = require("fs");

function main() {
  let input;
  try {
    input = JSON.parse(fs.readFileSync("/dev/stdin", "utf8"));
  } catch {
    return;
  }

  // Only trigger on Bash tool
  if (input.tool_name !== "Bash") return;

  const command = (input.tool_input?.command || "").trim();

  // Detect git push (direct or chained with && or ;)
  const isPush = /\bgit\s+push\b/.test(command);
  if (!isPush) return;

  // Get the current branch
  let branch;
  try {
    branch = execSync("git branch --show-current", {
      encoding: "utf8",
      timeout: 5000,
    }).trim();
  } catch {
    return;
  }

  // Skip pushes to main/staging directly (no PR to check)
  if (branch === "main" || branch === "staging" || branch === "master") return;

  // Try to find the PR number for this branch
  let prNumber = "";
  try {
    const prJson = execSync(
      `gh pr list --head "${branch}" --json number --jq '.[0].number'`,
      { encoding: "utf8", timeout: 10000 }
    ).trim();
    if (prJson && prJson !== "null") {
      prNumber = prJson;
    }
  } catch {
    // gh might fail if no PR exists yet — that's fine
  }

  const prInfo = prNumber ? `PR #${prNumber}` : "this branch (PR may still be creating)";

  // Output the reminder
  console.log(
    JSON.stringify({
      result: [
        `[ci-verify] Pushed to ${branch}. Verify CI passes for ${prInfo} before proceeding.`,
        `Follow the ci-verification skill: poll checks, fetch errors on failure, fix and re-push.`,
      ].join("\n"),
    })
  );
}

main();
