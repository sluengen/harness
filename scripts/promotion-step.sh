#!/usr/bin/env bash
# The nightly `dev -> main` promotion, as one shell.
#
# It lives here rather than inside the workflow's `run:` block so a test can
# *execute* it against stubbed git instead of reading its text
# (specs/architecture-principles.md -> "CI logic lives in a script, not in a
# `run:` block"). The executing guard is
# tests/unit/test_promotion_step_script.py.
#
# Extracting the shell split which ref supplies it, so note where each half comes
# from. GitHub reads a scheduled workflow from the default branch (`main`), while
# `actions/checkout` fills $GITHUB_WORKSPACE from `ref: dev` and a `run:` step's
# working directory is that checkout — so `main`'s workflow invokes `dev`'s copy
# of this file, where the inline block it replaced came wholly from `main`. A
# change here therefore reaches the next nightly as soon as it lands on `dev`,
# rather than waiting to be promoted the rest of the way.
#
# ADR 0015 retires the `harness promote` verb, not the promotion; ADR 0003 as
# amended (ADR 0017 D6) retires this repo's `staging` role, so the hop is
# `dev -> main` — recorded as this repo's topology in specs/infrastructure.md.
# ADR 0003's 2026-08-19 amendment changes *how* that hop lands: `main` is
# protected and requires a pull request, so `github-actions[bot]` cannot update
# refs/heads/main at all (GH006) and this step never once succeeded by pushing.
# It now opens — or reuses — a pull request whose head is `dev` itself and
# merges it through the API. Head-is-`dev` is load-bearing: that commit already
# carries the green lint-and-test raised by the ordinary `push: dev` trigger, so
# the required check is satisfied with no new run, no approval, and no new
# credential.
#
# The properties that matter, re-expressed for that mechanism:
#
#   * the gate decides, and only a green gate opens or merges anything;
#   * nothing is ever repaired, merged locally, or forced — the job stops and
#     reports, and a pull request it refused is left open for the next run;
#   * what lands is exactly the tree the gate certified — checked before by a
#     content-divergence pre-condition, bound during by the merge's server-side
#     head-SHA match, and checked after by containment plus tree identity. The
#     post-conditions *detect* rather than prevent: `main` has already moved
#     when they run, which the record states rather than papers over.
#
# Fast-forward-only publishing is retired with the push that carried it. A pull
# request merge necessarily puts a commit on `main` that `dev` does not contain,
# so ancestry cannot be the invariant; tree identity is, and it is the property
# the fast-forward rule was standing in for all along.
#
# Four environment inputs, all supplied by Actions and all required:
# GITHUB_WORKSPACE (the checkout the gate runs in), RUNNER_TEMP (where the gate
# log and the PR body are written), GITHUB_REPOSITORY (owner/repo, single-
# sourced into every API call) and GH_TOKEN (the job-scoped GITHUB_TOKEN the
# workflow forwards). They are asserted below before anything else, which is the
# fail-closed direction; `set -u` is the backstop, not the check. GH_TOKEN's
# assertion prints its message, never its value.
set -euo pipefail

: "${GITHUB_WORKSPACE:?the promotion step needs GITHUB_WORKSPACE (the checkout to gate and promote)}"
: "${RUNNER_TEMP:?the promotion step needs RUNNER_TEMP (where the gate log is captured)}"
: "${GITHUB_REPOSITORY:?the promotion step needs GITHUB_REPOSITORY (owner/repo, for every API call)}"
: "${GH_TOKEN:?the promotion step needs GH_TOKEN (what gh authenticates with; never echoed)}"

#: The hop. Named rather than inlined so the two branches appear once each and
#: the ::error:: annotations can say which ref stalled.
SOURCE_BRANCH="dev"
TARGET_BRANCH="main"

#: `owner/repo`, single-sourced into every `gh` call site.
REPO="$GITHUB_REPOSITORY"

#: The check `main`'s protection requires. It is `.github/workflows/ci.yml`'s
#: job key; the correspondence is pinned by the executed guard.
REQUIRED_CHECK="lint-and-test"
CHECK_WAIT_SECONDS="${PROMOTION_CHECK_WAIT_SECONDS:-1200}"
CHECK_POLL_SECONDS="${PROMOTION_CHECK_POLL_SECONDS:-20}"

cd "$GITHUB_WORKSPACE"

candidate="$(git rev-parse HEAD)"

# A pull request cannot create its base branch, so a missing target is a loud
# refusal rather than the silent first promotion a push used to perform.
if ! git ls-remote --exit-code --heads origin "$TARGET_BRANCH" >/dev/null 2>&1; then
  echo "::error::origin has no $TARGET_BRANCH branch, so there is nothing to open a pull request against; $SOURCE_BRANCH@$candidate was not promoted. Create $TARGET_BRANCH by hand."
  exit 1
fi
git fetch --no-tags --quiet origin "+refs/heads/$TARGET_BRANCH:refs/remotes/origin/$TARGET_BRANCH"

# Nothing to promote is a clean night, not a red job: GitHub answers a pull
# request with no commits between the refs with a 422, and this is the same
# predicate evaluated locally first. Before the gate, so an empty night does not
# spend twenty minutes proving it.
if git merge-base --is-ancestor "$candidate" "refs/remotes/origin/$TARGET_BRANCH"; then
  echo "$TARGET_BRANCH already contains $SOURCE_BRANCH@$candidate; nothing to promote."
  exit 0
fi

# The pre-condition that replaces the retired fast-forward check (ADR 0003 as
# amended 2026-08-19). A pull request merge puts a commit on $TARGET_BRANCH that
# $SOURCE_BRANCH does not contain, so ancestry can no longer be the invariant;
# tree identity is. Relative to their merge base, $TARGET_BRANCH must contribute
# no content — exactly the condition under which the merge is content-trivial,
# i.e. tree(merge) == tree(candidate). It reopens the moment a hotfix landed on
# $TARGET_BRANCH reaches $SOURCE_BRANCH, and has no exemption to go stale.
base="$(git merge-base "refs/remotes/origin/$TARGET_BRANCH" "$candidate")"
if ! git diff --quiet "$base" "refs/remotes/origin/$TARGET_BRANCH"; then
  echo "::error::$TARGET_BRANCH carries content $SOURCE_BRANCH@$candidate's history does not, so merging would not leave $TARGET_BRANCH's tree equal to the gated one; $TARGET_BRANCH was not advanced. Merge $TARGET_BRANCH into $SOURCE_BRANCH by hand."
  exit 1
fi

# The gate's exit code is *observed*, never rounded. `set +e` around it only so a
# red gate reaches the report below instead of aborting the script anonymously;
# `set -e` is restored immediately after.
gate_log="$RUNNER_TEMP/promotion-gate-$candidate.log"
set +e
bash scripts/verify.sh > "$gate_log" 2>&1
gate_exit=$?
set -e

if [ "$gate_exit" -ne 0 ]; then
  tail -n 40 "$gate_log"
  echo "::error::The gate exited $gate_exit on $SOURCE_BRANCH@$candidate; $TARGET_BRANCH was not advanced. No automated repair is permitted."
  exit 1
fi

# The gate certified one SHA, but a pull request's head is the *branch*. This is
# the early, named refusal for a push that landed while the gate ran; the
# residual window between here and the merge is closed server-side by the
# merge's own head-SHA match. Nothing is repaired — tonight does not promote.
remote_head="$(git ls-remote --heads origin "$SOURCE_BRANCH" | awk 'NR == 1 { print $1 }')"
if [ "$remote_head" != "$candidate" ]; then
  echo "::error::$SOURCE_BRANCH now points at $remote_head, not the gated $candidate, so a pull request from it would carry ungated commits; $TARGET_BRANCH was not advanced."
  exit 1
fi

# Reuse before create: last night's refused promotion leaves its pull request
# open, and a second one from the same head would be refused by GitHub anyway.
# `gh` does the jq, so one line of `<number> <isDraft> <headRefOid>` comes back.
pr_line="$(gh pr list --repo "$REPO" --head "$SOURCE_BRANCH" --base "$TARGET_BRANCH" --state open \
  --json number,isDraft,headRefOid \
  --jq '.[] | "\(.number) \(.isDraft) \(.headRefOid)"' | awk 'NR == 1')"

if [ -n "$pr_line" ]; then
  pr="$(printf '%s\n' "$pr_line" | awk '{ print $1 }')"
  pr_draft="$(printf '%s\n' "$pr_line" | awk '{ print $2 }')"
  pr_head="$(printf '%s\n' "$pr_line" | awk '{ print $3 }')"
  # Head `dev` into base `main` *is* the promotion by definition, so reusing a
  # human's pull request is benign — but only when it is mergeable and its head
  # is the SHA this run gated. Anything else is refused, never amended.
  if [ "$pr_draft" != "false" ] || [ "$pr_head" != "$candidate" ]; then
    echo "::error::the open $SOURCE_BRANCH -> $TARGET_BRANCH pull request #$pr is not this run's promotion (draft=$pr_draft, head=$pr_head, gated candidate=$candidate); $TARGET_BRANCH was not advanced."
    exit 1
  fi
else
  # Deterministic facts only, and written to a *file*: the log lines below are
  # commit subjects, which are untrusted text and must never be interpolated
  # into a shell word.
  body_file="$RUNNER_TEMP/promotion-pr.md"
  {
    echo "Promoting \`$SOURCE_BRANCH@$candidate\` to \`$TARGET_BRANCH\`."
    echo
    echo "The verification gate exited $gate_exit on this exact candidate."
    echo
    echo "Run: ${GITHUB_SERVER_URL:-https://github.com}/$REPO/actions/runs/${GITHUB_RUN_ID:-unknown}"
    echo
    echo "Commits:"
    echo
    git log --oneline "refs/remotes/origin/$TARGET_BRANCH..$candidate"
  } > "$body_file"
  pr_url="$(gh pr create --repo "$REPO" --base "$TARGET_BRANCH" --head "$SOURCE_BRANCH" \
    --title "Promote $SOURCE_BRANCH@${candidate:0:12} to $TARGET_BRANCH" \
    --body-file "$body_file" | awk 'NF { line = $0 } END { print line }')"
  pr="${pr_url##*/}"
fi

# $pr goes straight into an API path below. Unvalidated, that is path
# injection, so it is checked before anything is built out of it.
case "$pr" in
  '' | *[!0-9]*)
    echo "::error::could not read a pull request number from GitHub's answer (got '$pr'); $TARGET_BRANCH was not advanced."
    exit 1
    ;;
esac

# Wait for the required check *on the candidate SHA* — the object a status check
# attaches to, and the reason the pull request's head is `dev` itself: that
# commit already carries the run raised by the ordinary `push: dev` trigger.
# "Latest by started_at" matches how branch protection scores a name with
# several runs, so a re-run after a flake does not strand the candidate.
#
# The empty observation is a **wait**, never a success: a renamed CI job or a
# typo in $REQUIRED_CHECK yields no runs forever, and that must produce a red
# night rather than a merge nothing checked.
poll_deadline=$(( $(date +%s) + CHECK_WAIT_SECONDS ))
check_state="no run of $REQUIRED_CHECK on $candidate yet"
while : ; do
  observed="$(gh api "repos/$REPO/commits/$candidate/check-runs?check_name=$REQUIRED_CHECK" \
    --jq '.check_runs | sort_by(.started_at) | .[-1:][] | "\(.status) \(.conclusion)"')"
  case "$observed" in
    "completed success")
      break
      ;;
    "completed "*)
      echo "::error::$REQUIRED_CHECK on $SOURCE_BRANCH@$candidate concluded '${observed#completed }', not success; $TARGET_BRANCH was not advanced and the pull request was left open."
      exit 1
      ;;
    "")
      check_state="no run of $REQUIRED_CHECK on $candidate yet"
      ;;
    *)
      check_state="$observed"
      ;;
  esac
  if [ "$(date +%s)" -ge "$poll_deadline" ]; then
    echo "::error::$REQUIRED_CHECK did not complete on $SOURCE_BRANCH@$candidate within ${CHECK_WAIT_SECONDS}s (last observed: $check_state); $TARGET_BRANCH was not advanced and the pull request was left open."
    exit 1
  fi
  sleep "$CHECK_POLL_SECONDS"
done

# `sha=` is the server-side head match: GitHub refuses with 409 if the pull
# request's head is no longer the gated candidate, which closes the window this
# script cannot. `merge_method=merge` and nothing else — a squash or a rebase
# rewrites content or SHAs, breaks tree(merge) == tree(candidate), and would
# re-present $SOURCE_BRANCH's commits every subsequent night.
merge_sha="$(gh api --method PUT "repos/$REPO/pulls/$pr/merge" \
  --raw-field merge_method=merge \
  --raw-field sha="$candidate" \
  --jq .sha)"

# The post-conditions, read on the SHA the API returned rather than on whatever
# refs/heads/$TARGET_BRANCH points at now, so a human pushing a second later
# cannot raise a false alarm. Honest about what they are: $TARGET_BRANCH has
# already moved, so these *detect* rather than prevent. The prevention is the
# pre-condition above plus the head match on the merge itself.
git fetch --no-tags --quiet origin "+$merge_sha:refs/promotion/merged"
if ! git merge-base --is-ancestor "$candidate" "$merge_sha"; then
  echo "::error::$TARGET_BRANCH's new head $merge_sha does not contain the gated $SOURCE_BRANCH@$candidate; the merge was not the promotion this run gated. Inspect $TARGET_BRANCH by hand."
  exit 1
fi
merged_tree="$(git rev-parse "$merge_sha^{tree}")"
candidate_tree="$(git rev-parse "$candidate^{tree}")"
if [ "$merged_tree" != "$candidate_tree" ]; then
  echo "::error::the merge commit's tree ($merged_tree) is not the gated candidate's tree ($candidate_tree), so what landed on $TARGET_BRANCH is not what the gate certified. Inspect $TARGET_BRANCH by hand."
  exit 1
fi

echo "Promoted $SOURCE_BRANCH@$candidate to $TARGET_BRANCH as $merge_sha (pull request #$pr)."
