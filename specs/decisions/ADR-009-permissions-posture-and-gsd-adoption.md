# ADR-009: Permissions Posture and Selective GSD Pattern Adoption

**Date:** 2026-03-23
**Status:** Accepted
**Context:** Evaluating a shift from allowlist-based permissions to branch-isolation-based trust, and identifying reusable patterns from the GSD (get-shit-done) open-source framework.

---

## Part 1: Permissions Posture

### Decision

**Replace the allowlist with `Bash(*)` gated by mandatory worktree isolation.**

The safety model shifts from "ask before each bash command" to "everything happens on a disposable branch in an isolated filesystem."

### How It Works

| Layer | Control | Enforced by |
|-------|---------|-------------|
| **Filesystem isolation** | All file-modifying agents run in worktrees (`isolation: "worktree"`) | CLAUDE.md rules + orchestrator |
| **Branch isolation** | All work happens on feature branches, never on main | Deny rules (retained) + CLAUDE.md |
| **Destructive git ops** | Force push, hard reset, branch -D remain denied | `settings.json` deny list (retained) |
| **PR merge gate** | PRs require human review before merge | `settings.json` deny + branch protection |
| **Network boundary** | No secrets in agent environment; outbound calls limited to known services | Environment hygiene |
| **Reviewer gate** | Code reviewed before deploy; second FAIL halts pipeline | Escalation levels |

### settings.json

```json
{
  "permissions": {
    "deny": [
      "Bash(git push --force *)",
      "Bash(git push * --force *)",
      "Bash(git push --force-with-lease *)",
      "Bash(git push * --force-with-lease *)",
      "Bash(git -C * push --force *)",
      "Bash(git -C * push * --force *)",
      "Bash(git -C * push --force-with-lease *)",
      "Bash(git -C * push * --force-with-lease *)",
      "Bash(git reset --hard *)",
      "Bash(git -C * reset --hard *)",
      "Bash(git merge * main)",
      "Bash(git merge * main *)",
      "Bash(git -C * merge * main)",
      "Bash(git -C * merge * main *)",
      "Bash(gh pr merge *)"
    ],
    "allow": [
      "Read",
      "Write",
      "Edit",
      "Bash(*)"
    ]
  }
}
```

The deny list stays. The allowlist collapses to `Bash(*)`. Deny rules are evaluated first, so the dangerous operations remain blocked.

### What We Gain

1. **Fully autonomous pipeline runs.** Dev and reviewer agents run start-to-finish without permission interrupts.
2. **Zero allowlist maintenance.** New tools don't require a settings update.
3. **Honesty about actual posture.** Chained command patterns already permitted arbitrary execution.
4. **Faster iteration.** The bottleneck is human availability at permission prompts, not agent capability.

### What We Lose

1. **Visibility into bash commands before execution.** Unfamiliar commands no longer prompt.
2. **Gut-check moments.** Some permission prompts have caught mistakes.

---

## Part 2: Selective GSD Pattern Adoption

### Philosophy

GSD is a generic framework solving the same problems we solve with our pipeline. We don't need the framework — our pipeline is more purpose-built and already works. But GSD has solved several problems we hadn't addressed yet, and some of their patterns are worth lifting.

### Patterns Adopted

#### 1. Context Monitor Hook
A `PostToolUse` hook that reads context usage metrics and injects warnings at 35% (warning) and 25% (critical) remaining context. Debounced to avoid spam.

#### 2. Prompt Injection Scanner
A `PreToolUse` hook that scans file writes for prompt injection patterns (instruction override, role-play, system marker injection, suspicious Unicode). Advisory only.

#### 3. Session Pause/Resume
A `/pause-work` command that captures current position, completed work, remaining work, decisions, and blockers into a handoff file, then commits as WIP.

#### 4. Forensics Command
A `/forensics` command that analyses git history, file system state, and project artifacts to diagnose what went wrong in a failed run. Read-only.

#### 5. Workflow Guard Hook
A `PreToolUse` hook that detects edits to source code outside of a pipeline task context. Advisory only.

### Patterns Skipped

| GSD Pattern | Why we skip it |
|---|---|
| `.planning/` directory structure | We have `specs/`, `manifest.yaml`, and `reviews/` |
| Wave-based parallel execution | Tasks scoped small enough for single-agent execution per worktree |
| Multi-runtime support | Claude Code only |
| Discussion phase commands | PM agent + L2 checkpoints handle requirements |
| Full command set (57 commands) | Cherry-pick, don't wholesale |
| Profile/user profiling | Single-user system |
| Global installation | Project-scoped config preferred |

---

## Summary

Both changes reinforce the same principle: **the branch is the boundary, not the permission prompt.** Agents operate freely within their isolated workspace; humans review at the PR gate.
