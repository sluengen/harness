#!/usr/bin/env node

/**
 * Context Monitor Hook (PostToolUse)
 *
 * Monitors context window usage and warns agents when context is running low.
 * Inspired by GSD's context monitoring pattern, adapted for our pipeline.
 *
 * Thresholds:
 *   - 35% remaining → WARNING: finish current task and commit
 *   - 25% remaining → CRITICAL: commit, summarize state, stop
 *
 * Debounced to every 5 tool uses to avoid spam.
 * Critical warnings bypass debounce when escalating from warning level.
 */

const fs = require("fs");
const path = require("path");
const os = require("os");

const WARNING_THRESHOLD = 0.35;
const CRITICAL_THRESHOLD = 0.25;
const DEBOUNCE_INTERVAL = 5;
const STALENESS_SECONDS = 60;

function main() {
  let input;
  try {
    input = JSON.parse(fs.readFileSync("/dev/stdin", "utf8"));
  } catch {
    process.stdout.write(JSON.stringify({ continue: true }));
    return;
  }

  const sessionId = input.session_id || "unknown";
  const metricsPath = path.join(os.tmpdir(), `claude-ctx-${sessionId}.json`);
  const counterPath = path.join(os.tmpdir(), `claude-ctx-counter-${sessionId}.json`);

  // Read and increment tool use counter
  let counter = 0;
  let lastLevel = "none";
  try {
    const counterData = JSON.parse(fs.readFileSync(counterPath, "utf8"));
    counter = (counterData.count || 0) + 1;
    lastLevel = counterData.level || "none";
  } catch {
    counter = 1;
  }

  // Check for context metrics file
  let metrics;
  try {
    metrics = JSON.parse(fs.readFileSync(metricsPath, "utf8"));
  } catch {
    // No metrics available — save counter and continue silently
    fs.writeFileSync(counterPath, JSON.stringify({ count: counter, level: lastLevel }));
    process.stdout.write(JSON.stringify({ continue: true }));
    return;
  }

  // Staleness check
  const age = (Date.now() - (metrics.timestamp || 0)) / 1000;
  if (age > STALENESS_SECONDS) {
    fs.writeFileSync(counterPath, JSON.stringify({ count: counter, level: lastLevel }));
    process.stdout.write(JSON.stringify({ continue: true }));
    return;
  }

  const remaining = metrics.remaining_percentage || 1.0;
  let currentLevel = "none";
  let message = null;

  if (remaining <= CRITICAL_THRESHOLD) {
    currentLevel = "critical";
  } else if (remaining <= WARNING_THRESHOLD) {
    currentLevel = "warning";
  }

  // Debounce: only warn every N tool uses, unless escalating severity
  const isEscalation = currentLevel === "critical" && lastLevel !== "critical";
  const isDebounceTick = counter % DEBOUNCE_INTERVAL === 0;

  if (currentLevel !== "none" && (isDebounceTick || isEscalation)) {
    if (currentLevel === "critical") {
      message =
        `[CONTEXT CRITICAL — ${Math.round(remaining * 100)}% remaining] ` +
        "Context window nearly exhausted. Commit your current work immediately, " +
        "write a handoff summary (run /pause-work), and stop. " +
        "Do not start new tasks.";
    } else {
      message =
        `[CONTEXT WARNING — ${Math.round(remaining * 100)}% remaining] ` +
        "Context window running low. Finish your current task, commit, " +
        "and consider wrapping up. If more work remains, commit and " +
        "note what's left so the next session can pick up.";
    }
  }

  // Save counter and level
  fs.writeFileSync(counterPath, JSON.stringify({ count: counter, level: currentLevel }));

  const result = { continue: true };
  if (message) {
    result.additionalContext = message;
  }
  process.stdout.write(JSON.stringify(result));
}

main();
