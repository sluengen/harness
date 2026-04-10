# CI Verification

After every `git push` to a PR branch, verify that all CI checks pass before proceeding. If anything fails, fix it and re-push. Do not declare a task complete or move to the next pipeline stage until CI is green.

## Trigger

The `ci-verify` hook fires after `git push` and provides the branch name and PR number. When you see its output, follow this skill.

## Verification loop

### 1. Wait for checks to register

```bash
sleep 10
```

CI needs a few seconds to pick up the push.

### 2. Poll for check completion

```bash
gh pr checks <PR#> --watch --fail-fast
```

This blocks until all checks complete or one fails. Use a 10-minute timeout on the Bash call.

If `--watch` is not available or times out, poll manually:

```bash
gh pr checks <PR#>
```

Repeat every 30 seconds until no checks show "pending" or "in_progress".

### 3. On success

All checks pass — proceed with the pipeline. No action needed.

### 4. On failure — fetch error details

Identify which check failed from the `gh pr checks` output, then fetch logs:

**GitHub Actions failure:**

```bash
# Find the failed run
gh run list --branch <branch> --limit 3 --json databaseId,status,conclusion,name

# Get failed step logs
gh run view <run-id> --log-failed
```

If a CI doctor job ran, it may also post a categorised failure comment on the PR:

```bash
gh pr view <PR#> --comments --json comments --jq '.comments[-1].body'
```

### 5. Fix the error

Read the error output. Common failure categories:

| Category | Typical cause | Fix approach |
|----------|--------------|--------------|
| TypeScript (`tsc`) | Type errors in `.ts`/`.tsx` files | Read the file, fix the type, run `npx tsc --noEmit` locally |
| Lint (`ruff`) | Python lint violations | Run `ruff check . --fix`, review changes |
| Test failure | Assertion mismatch, missing mock | Run the specific test locally, fix |
| Dependency | Missing import or package | Check `pyproject.toml` or `package.json` |
| Build (`vite build`) | Import errors, missing exports | Run `npm run build` locally |

After fixing:
- Run the relevant local check (test suite, lint, tsc) to confirm the fix
- Commit with a descriptive message referencing the CI failure
- Push

### 6. Re-verify

After pushing the fix, the hook fires again. Follow the same loop. Repeat until green.

### 7. Escalate

If the same check fails 3 times after fixes, stop and present the full error to the user. Something structural may be wrong that needs human judgment.

## Important

- **Never skip verification.** A task is not done until CI is green.
- **Fix locally first.** Always reproduce and verify the fix locally before pushing.
- **Don't suppress errors.** Fix the root cause, don't add `// @ts-ignore` or skip tests.
