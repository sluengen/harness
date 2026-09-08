#!/usr/bin/env bash
# verify.sh — change-aware lint / type / test gate.
#
# Runs only the gates relevant to what changed, so the local build loop
# (/build) proves whatever a ticket touched — backend, mobile, or the
# design system — without spinning up Docker for a pure-mobile change or
# skipping the mobile checks for a frontend change.
#
# Usage:
#   bash scripts/verify.sh                 # auto-detect scope vs `dev`
#   VERIFY_SCOPE=mobile bash scripts/verify.sh
#   VERIFY_ALL=1 bash scripts/verify.sh    # run everything (CI)
#
# A default or VERIFY_ALL invocation delegates to the plugin's Node gate
# runner (`exec node scripts/gate-marker.js run`, CAL-1662): it resolves
# `commands.verify` out of harness.yaml (this script), spawns it with
# HARNESS_GATE_MARKER_RUNNER set to the repository identity, and owns
# preflight, tree computation and marker emission. VERIFY_SCOPE, VERIFY_PRINT_SCOPE and a test-spawned run
# bypass it — see the block right after `cd "$REPO_ROOT"` below.
#
# Scope resolution (first match wins):
#   1. VERIFY_SCOPE   — explicit comma list, or "all" (e.g. "backend,mobile")
#   2. VERIFY_ALL=1   — run every gate
#   3. auto-detect    — `git diff` of changed paths vs ${VERIFY_BASE:-dev}
#                       (committed-since-base + staged + unstaged + untracked)
# The base is resolved through a candidate list — `<name>` and `origin/<name>` —
# so a checkout with no local `dev` (fresh single-branch clone, CI checkout) still
# has a base. EVERY candidate that resolves is kept, and the changed-path set is
# the UNION of their diffs, so two candidates that have diverged can only ADD an
# arm and never remove one (CAL-1570). When NO candidate resolves, auto-detect is
# fatal: it cannot tell "nothing changed" from "nothing was compared". It is fatal
# too when a candidate resolved but its merge-base cannot be diffed against HEAD,
# for the same reason. Under an explicit VERIFY_SCOPE / VERIFY_ALL neither is
# fatal — no conclusion rests on the base there, and that is what keeps the CI
# workflows (which supply their own scope and check out a single ref) working.
# When auto-detect RESOLVES a base and finds no mapped paths (clean tree, or only
# unmapped files such as docs/specs), it falls back to the backend gate — the
# legacy default.
#
# Path → area mapping:
#   mobile/                                            → mobile
#   mobile/app/                                        → mobile + rawlint + controlplane
#       (the route tree; the control plane's App Flow area derives its whole
#        node set from it)
#   mobile/{components,lib,store}/ mobile/app.json     → mobile + rawlint
#       (the rest of the raw-value lint's SCAN_ROOTS — the lint reads them, so
#        a change there must run it, but nothing is generated from them and they
#        do not pay the heavy design gate)
#   design/                                            → design + mobile + engine
#       (built tokens feed the mobile typecheck, so a token change must
#        re-run the mobile gate; and the design corpus is what the control
#        plane's design engine parses, so a doc change must re-run the
#        round-trip guard that now lives there — CAL-1262)
#   design/… declared a `subject`                       → + assurance
#       (ADDITIVE to whichever design arm the path already takes, per
#        tests/assurance_cohort.txt. A cohort module can be broken by an edit to a
#        design artifact it reads, and none of design + mobile + engine runs a
#        Python test — CAL-1657)
#   .github/dependabot.yml                             → ghconfig
#       (schema-validated against a vendored copy; its breakage is silent —
#        GitHub just stops opening update PRs)
#   .github/ (workflows, everything else)              → assurance
#       (no schema check — a bad workflow fails visibly on its next run; this
#        runs the committed-text tests that already pin the workflows)
#   assessments/ specs/ decisions/ strategy/           → records, OR assurance
#   CLAUDE.md AGENTS.md harness.yaml                   → records, OR assurance
#       (the record and guidance contracts — CAL-1545. None of these matched any
#        arm before; they reached the empty-scope backend fallback, so alone they
#        cost the whole product suite and bundled with a mapped change they
#        escaped every gate.
#        WHICH of the two, per tests/assurance_cohort.txt: a path a `subject`
#        record covers keeps `assurance`, because a cohort module can be broken
#        by an edit to it; a path no `subject` covers takes `records`, whose gate
#        runs tests/guidance/ alone. Covered today: CLAUDE.md, AGENTS.md,
#        harness.yaml, the whole specs/features/ tree, and two specs/proposals/
#        files — so what
#        actually gets cheap is assessments/, strategy/, decisions/ and the rest
#        of specs/proposals/. CAL-1647)
#   catalog/                                           → catalog
#   catalog/tests/ingestion/ported_behaviours.py       → catalog + backend
#       (the port manifest: the catalog gate checks its declared entries
#        exist, the root suite checks it is complete against tests/crawler/)
#   app/ alembic/ crawler/                             → backend
#   tests/                                             → backend, OR assurance
#       (per tests/assurance_cohort.txt — a cohort test module or a declared
#        shared helper takes assurance, everything else backend. CAL-1545. Two
#        modules are matched BY NAME ahead of that rule and take a third area:
#        the two rows below are the whole of the exception)
#   tests/test_github_config_gate.py                   → assurance + ghconfig
#   tests/test_cal1505_sdk_decided_packages.py         → backend + ghconfig
#       (both own .github/dependabot.yml rules, so a config change has to run
#        them. The CAL-1505 module derives its subject set from an npm install,
#        so it is deliberately outside the cohort and takes `backend` where its
#        sibling takes `assurance` — CAL-1505. Both of those arms call
#        `ensure_node_modules mobile`, because a test that reads an install needs
#        an arm that makes one)
#   alembic.ini compose.yaml Dockerfile*               → backend
#   scripts/verify.sh                                  → assurance
#   scripts/gate-marker.js scripts/harness-config.js scripts/package.json
#     scripts/worker_budget.py scripts/checks/{eas_build_gate,
#     ios_release_gate,railway_env_preflight,release_provenance}.py
#                                                      → assurance
#       (each pinned only by cohort modules; the assurance arm lints scripts/ too)
#   (nothing maps to ios-release — see below)
#   pyproject.toml *.lock                              → backend + lockcheck
#       (lockcheck recompiles requirements*.lock from pyproject.toml and fails
#        on drift — the Docker image installs from requirements*.lock while the
#        backend gate's `uv run` uses uv.lock, so they can diverge silently)
#   mobile/package.json mobile/package-lock.json       → mobile + npmlock
#       (npmlock is lockcheck's npm counterpart: it regenerates
#        mobile/package-lock.json from mobile/package.json in a temp dir and
#        fails on drift. Ordered BEFORE the mobile/* arm, and it keeps `mobile`
#        so a manifest change still runs the mobile gate — CAL-1501)
#
# The mobile arm has a SECOND dimension (CAL-1651): WHICH of the seven jest
# projects mobile/jest.config.js declares it runs. The mapping above decides
# whether the mobile gate runs at all; detect_jest_projects decides what its jest
# step is pointed at, by the same ordered first-match `case` idiom over the same
# changed-file set. The two are independent — this added a dimension and re-cut no
# arm — and only auto-detection restricts: under VERIFY_SCOPE / VERIFY_ALL every
# project runs, as before.
#
# The ios-release arm (CAL-1303) is deliberately unreachable by both of the
# automatic routes. NO path mapping selects it, and VERIFY_ALL=1 does NOT include
# it. It builds a real iOS Release artifact with xcodebuild and launches it on a
# simulator: ~16-19 minutes, and it needs a Mac with Xcode, CocoaPods and a
# simulator runtime. Rolled into VERIFY_ALL it would add that to promotion-gate.yml
# and to the nightly promotion, both of which run on ubuntu-latest hosts where the
# check correctly reports `unavailable` (exit 3) — a red release gate on every
# promotion, cleared by nothing. It exists here so the capability is discoverable
# from the file that lists this repo's gates, and so tests/test_verify_sh_scope.py
# can pin both directions:
#
#   VERIFY_SCOPE=ios-release bash scripts/verify.sh   # the only way in
#
# Dry run:  VERIFY_PRINT_SCOPE=1 bash scripts/verify.sh
#   Prints the resolved scope and exits without running any gate.
#
# Worker budget (CAL-1646). Every arm that spawns workers — mobile (jest),
# controlplane (vitest), backend and assurance (pytest), catalog (a nested gate)
# — runs through `budget_run`, which takes a share of a machine-wide token pool
# in the git common directory and hands the count to the command in
# VERIFY_WORKER_TOKENS. The budget defaults to the machine's core count and a run
# that cannot be budgeted WAITS rather than proceeding unbounded. See
# scripts/worker_budget.py; VERIFY_WORKER_BUDGET overrides the size,
# `python3 scripts/worker_budget.py status` shows who holds the pool.
#
# Backend gate — two modes (unchanged from the original verify.sh):
#   DATABASE_URL set   — daemonless: lint + tests via `uv run` against the
#                        provided Postgres, no Docker. Used by the harness
#                        (CAL-537) to avoid Docker-in-Docker.
#   DATABASE_URL unset — compose: bring up Postgres via `docker compose up db`
#                        and run tests inside the backend container.
#
# Why DATABASE_URL points to host.docker.internal in the compose path:
#   The backend container connects to the compose-network 'db' hostname by
#   default. In some environments (e.g. Docker Desktop) the embedded
#   compose-network DNS does not resolve correctly from run containers.
#   Overriding DATABASE_URL to host.docker.internal bypasses compose DNS and
#   connects via the port db exposes to the host (5432).

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

# ----- the public path (CAL-1662) -----
# The plugin's Node runner owns preflight, tree computation and marker emission.
# It resolves the command it launches from `commands.verify` in harness.yaml, sets
# HARNESS_GATE_MARKER_RUNNER on it — to the repository identity, not a constant
# (ADR 0018) — and writes a marker only after that command
# exits 0 — so this script's whole gate becomes the runner's child and the marker
# contract lives in exactly one implementation.
#
# Four states take the internal path instead, each predicate hoisted VERBATIM from
# the place it already lives so two readings of one variable cannot drift apart:
#   HARNESS_GATE_MARKER_RUNNER  we ARE the child (gate-marker.js:724 sets it, to
#                               this repository's identity — so both readings of
#                               it in this file test emptiness, never a literal)
#   VERIFY_SCOPE                an area selection (:1070) — a partial gate
#                               authorises no landing, so it earns no marker
#   VERIFY_PRINT_SCOPE          the dry run (:1125) — it exits before any arm, and
#                               a marker for it would name a tree nothing verified
#   PYTEST_CURRENT_TEST         spawned from a test (D15/CAL-1504) — hoisted here
#                               from the old foot-of-file guard, which is strictly
#                               stronger: there is now no path from a test-spawned
#                               run to any code that can write a marker
# VERIFY_ALL is deliberately NOT here: it runs MORE than a default run, so a full
# run must earn the evidence a default run earns.
#
# `:-` on every expansion because of `set -u` at :162 — a bare expansion would abort
# every run whose variable happens to be unset, which is the ordinary case for all
# four.
if [ -z "${HARNESS_GATE_MARKER_RUNNER:-}" ] \
  && [ -z "${VERIFY_SCOPE:-}" ] \
  && [ "${VERIFY_PRINT_SCOPE:-0}" != "1" ] \
  && [ -z "${PYTEST_CURRENT_TEST:-}" ]; then
  exec node scripts/gate-marker.js run
fi

run_backend=0
run_assurance=0
run_mobile=0
run_design=0
run_lockcheck=0
run_npmlock=0
run_openapi=0
run_rawlint=0
run_controlplane=0
run_ghconfig=0
run_engine=0
run_flowmap=0
run_catalog=0
run_records=0
run_ios_release=0

# The jest projects the mobile arm restricts itself to (CAL-1651), as a comma
# list. EMPTY means unrestricted — every project runs and mobile_gate invokes jest
# exactly as it did before this existed. Only auto-detection ever sets it; see
# detect_jest_projects.
JEST_PROJECTS=""

# Set area flags from a comma list (or "all").
# NOTE: `all` deliberately omits ios-release. See the header — it is a
# 16-19 minute native build that reports `unavailable` on every CI host this
# repository uses, so rolling it into "everything" would redden every promotion.
set_from_list() {
  case ",$1," in *,all,*) run_backend=1; run_assurance=1; run_mobile=1; run_design=1; run_lockcheck=1; run_npmlock=1; run_openapi=1; run_rawlint=1; run_controlplane=1; run_ghconfig=1; run_engine=1; run_flowmap=1; run_catalog=1; run_records=1; return;; esac
  case ",$1," in *,backend,*) run_backend=1;; esac
  case ",$1," in *,assurance,*) run_assurance=1;; esac
  case ",$1," in *,mobile,*) run_mobile=1;; esac
  case ",$1," in *,design,*) run_design=1;; esac
  case ",$1," in *,lockcheck,*) run_lockcheck=1;; esac
  case ",$1," in *,npmlock,*) run_npmlock=1;; esac
  case ",$1," in *,openapi,*) run_openapi=1;; esac
  case ",$1," in *,rawlint,*) run_rawlint=1;; esac
  case ",$1," in *,controlplane,*) run_controlplane=1;; esac
  case ",$1," in *,ghconfig,*) run_ghconfig=1;; esac
  case ",$1," in *,engine,*) run_engine=1;; esac
  case ",$1," in *,flowmap,*) run_flowmap=1;; esac
  case ",$1," in *,catalog,*) run_catalog=1;; esac
  case ",$1," in *,records,*) run_records=1;; esac
  case ",$1," in *,ios-release,*) run_ios_release=1;; esac
}

# ----- the assurance cohort (CAL-1545) -----
# Membership is single-sourced in this data file and read by BOTH arms below:
# assurance_gate runs its `test` records, backend_gate passes --ignore= for
# exactly the same records. Disjointness is therefore structural — there is no
# second list that can disagree with the first.
#
# Read with `awk`, deliberately. tests/test_verify_sh_scope.py::_run_with_shims
# puts a fake `uv` on PATH and runs THIS script against the REAL repository to
# measure which tools a scope invokes. A derivation that went through
# `uv run python` would return the empty set under that shim, the arm would hand
# pytest no paths at all, and the dispatch tests would report green over an arm
# that did nothing — the false-green shape recorded in
# specs/features/deployment-gates.md. `awk` is POSIX and no fixture shims it.
ASSURANCE_MANIFEST="tests/assurance_cohort.txt"

# The cohort's test modules, one repo-relative path per line.
#
# A missing manifest yields nothing rather than an error: the fixture repositories
# in tests/ carry a copy of this script without necessarily carrying a manifest,
# and scope detection there must still work. The callers below are what fail
# closed on an empty result — an arm that would run pytest with no paths, or a
# backend arm that would silently stop excluding the cohort, has to say so.
assurance_modules() {
  [ -f "$ASSURANCE_MANIFEST" ] || return 0
  awk '$1 == "test" { print $2 }' "$ASSURANCE_MANIFEST"
}

# Does a changed path belong to the arm? True for a cohort test module and for a
# declared shared helper: every module importing a helper is in the cohort, so an
# edit to one must reach the arm that runs them.
is_assurance_path() {
  [ -f "$ASSURANCE_MANIFEST" ] || return 1
  awk -v p="$1" \
    '($1 == "test" || $1 == "helper") && $2 == p { found = 1 } END { exit !found }' \
    "$ASSURANCE_MANIFEST"
}

# Is a changed path COVERED by a declared SUBJECT of the cohort — named by a
# `subject` record, or sitting under one that names a directory? Its caller is the
# record arm in detect_scope (CAL-1647): an edit to a covered record can break a
# cohort module, so it keeps the whole arm, while the record surfaces no subject
# covers are pinned by tests/guidance/ alone and take the cheap `records` arm.
#
# The semantics mirror `_matches()` in tests/assurance_cohort.py, which is what
# the membership contract derives with — exact match, or a prefix match when the
# declared subject ends in `/` (a directory subject such as .github/workflows/ or
# specs/features/). Two readers of one manifest that disagreed about what a record
# MEANS would put a module in the cohort while routing its subject elsewhere.
#
# ONE branch of `_matches()` is deliberately not mirrored: it also accepts
# `path.endswith("/" + subject)`. That branch exists for the derivation alone,
# where a `REPO_ROOT / "scripts" / "verify.sh"` divide-chain loses its
# non-constant root and has to resolve against a repo-relative subject. Applying
# it to a CHANGED PATH would make any file whose tail matched a subject take the
# cohort — a `docs/CLAUDE.md` would route as the guidance file it is not. Routing
# reads whole repo-relative paths, so it needs no such recovery.
#
# Missing manifest returns false, exactly as is_assurance_path does and for the
# same reason: the fixture repositories in tests/ carry this script without
# necessarily carrying a manifest, and routing there must still resolve. False is
# the safe answer — it selects the cheap arm, which still runs, rather than
# silently claiming a record is covered by the cohort.
is_assurance_subject() {
  [ -f "$ASSURANCE_MANIFEST" ] || return 1
  awk -v p="$1" '
    $1 == "subject" {
      s = $2
      if (s ~ /\/$/) {
        if (p == substr(s, 1, length(s) - 1) || index(p, s) == 1) found = 1
      } else if (p == s) {
        found = 1
      }
    }
    END { exit !found }' "$ASSURANCE_MANIFEST"
}

# The diff base, resolved once (CAL-1365).
#
# BASE_NAME is what the caller asked for; the candidates tried are that name and
# then `origin/<name>`. A checkout with no local `dev` — a fresh single-branch
# clone, a CI checkout, a clone whose only local branch is the feature branch —
# still has the remote-tracking ref, and that is the whole fix: `dev` alone
# resolved to nothing there. (A git worktree is NOT such a checkout; worktrees
# share the parent repo's refs, so `dev` resolves whenever any checkout has it.)
#
# EVERY resolvable candidate is kept, and their diffs are UNIONED (CAL-1570).
# The old rule took the first candidate that resolved, local before `origin/`, on
# the reasoning that "a stale local `dev` puts the merge-base further back, so the
# diff is WIDER". That holds only for a local `dev` BEHIND its remote. A local
# `dev` AHEAD of `origin/dev` — the developer committed to `dev`, branched from
# it, and never pushed — gives a NEWER merge-base and therefore a NARROWER diff,
# so first-success silently dropped every arm the other candidate would have
# selected and the run still minted a gate marker over the unchecked surface.
#
# Union, not an ordering: no ordering can be right in both directions, and the
# union is a superset of what either candidate selects alone. Divergence between
# candidates can therefore ADD a check and can never remove one.
#
# Merge-bases, not candidate TIPS. `git diff origin/dev..HEAD` would report every
# path `dev` changed since the fork as if this branch had changed it — noise that
# grows with the integration branch, not conservatism.
#
# A candidate counts as resolved when `git merge-base <candidate> HEAD` SUCCEEDS,
# not when `git rev-parse --verify` does. A ref can exist and share no history
# with HEAD (an unrelated orphan branch), and rev-parse is happy with that while
# the operation every caller actually needs still fails. That is also why a
# resolved-but-unrelated candidate is not a hazard here: resolution IS the
# relatedness test, and under the union an extra candidate could only add paths.
BASE_NAME="${VERIFY_BASE:-dev}"
BASE_MERGE_BASES=""  # space-separated DISTINCT merge-base shas; empty when none
BASE_RESOLVED=""     # "" = not yet attempted, "yes" / "no" = the cached answer

# Resolve the base snapshot, memoized. Returns 0 when at least one candidate
# resolved (BASE_MERGE_BASES holds their distinct merge-bases), 1 when none did.
# Memoized because changed_files() has two callers — detect_scope and size_gate —
# which must never disagree about the base, and because `git merge-base` should
# not be re-run per call. The cache is seeded from the top-level shell before
# scope resolution, so the subshells that changed_files() runs in inherit the
# answer rather than recomputing it.
#
# Plain scalars rather than arrays for exactly that reason: shas are hex and
# refnames carry no spaces, so a space-separated scalar is unambiguous and
# inherits by copy into every subshell.
resolve_base() {
  if [ -n "$BASE_RESOLVED" ]; then
    if [ "$BASE_RESOLVED" = "yes" ]; then return 0; else return 1; fi
  fi
  local cand mb
  for cand in "$BASE_NAME" "origin/$BASE_NAME"; do
    if mb="$(git merge-base "$cand" HEAD 2>/dev/null)" && [ -n "$mb" ]; then
      case " $BASE_MERGE_BASES " in
        *" $mb "*) ;;  # two candidates can share a fork point; diff it once
        *) BASE_MERGE_BASES="${BASE_MERGE_BASES:+$BASE_MERGE_BASES }$mb" ;;
      esac
    fi
  done
  if [ -n "$BASE_MERGE_BASES" ]; then
    BASE_RESOLVED="yes"
    return 0
  fi
  BASE_RESOLVED="no"
  return 1
}

# Echo the newline-separated set of paths the working tree changed vs the base
# ref: committed-since-EVERY-frozen-merge-base + unstaged + staged + untracked.
# Shared by detect_scope (path→area mapping) and size_gate (mobile source size
# check) so both reason about exactly the same changed-file set — the memo exists
# so those two can never disagree about the base, and a second base for one of
# them would reintroduce that hazard on the wider side.
changed_files() {
  {
    if resolve_base; then
      local mb
      for mb in $BASE_MERGE_BASES; do
        # `|| true` so one broken comparison cannot abort the group under `set -e`
        # and silently drop the working-tree sources below it — that would NARROW
        # the set, the exact direction this whole mechanism exists to prevent. The
        # auto-detect branch refuses to continue at all in that case
        # (require_diffable_bases, below); under a declared scope no conclusion
        # rests on the base, so it contributes nothing and the run proceeds.
        git diff --name-only "$mb"..HEAD || true
      done
    fi
    git diff --name-only
    git diff --name-only --cached
    git ls-files --others --exclude-standard
  } 2>/dev/null | sort -u
}

# Every frozen merge-base must actually be diffable against HEAD. Called only
# from the auto-detect branch, before any arm and therefore before any marker:
# a run that cannot compare what it froze cannot claim to have mapped the change,
# and changed_files() would otherwise absorb the failure as zero extra paths —
# i.e. as a narrower scope, reported green.
require_diffable_bases() {
  local mb
  for mb in $BASE_MERGE_BASES; do
    if ! git diff --name-only "$mb"..HEAD >/dev/null; then
      echo "ERROR: the diff base resolved to merge-base '${mb}', but that could not be" >&2
      echo "       diffed against HEAD. Scope auto-detection derives every arm it runs" >&2
      echo "       from that comparison, so this run cannot tell 'nothing changed' from" >&2
      echo "       'nothing was compared' — and it will not guess a gate." >&2
      echo "       Repair the repository (git fsck), or state the scope yourself:" >&2
      echo "         VERIFY_SCOPE=... / VERIFY_ALL=1" >&2
      return 1
    fi
  done
  return 0
}

# Echo a comma list of areas touched by the working tree vs the base ref.
detect_scope() {
  local files areas=""
  files="$(changed_files)"
  [ -n "$files" ] || return 0
  while IFS= read -r f; do
    [ -z "$f" ] && continue
    case "$f" in
      # The record surfaces (CAL-1545): the specs, decisions, assessments and
      # strategy trees, plus the two guidance files. None of them matched ANY arm
      # before — they reached detect_scope, contributed nothing, and landed in the
      # empty-scope backend fallback. Alone that ran the whole product suite and a
      # Postgres to verify a prose edit; bundled with a mapped change the fallback
      # never fired and they escaped every gate, the same masking hole the
      # crawler/ and scripts/ arms exist to close.
      #
      # `assurance` was the area that owned all of them: CLAUDE.md and AGENTS.md
      # are pinned byte-for-byte by tests/guidance/test_repo_agent_guidance.py,
      # and the release/workflow record contracts are pinned by the rest of the
      # cohort. No database, no token build.
      #
      # It is now the DECLARED-SUBJECT half of them (CAL-1647). The whole cohort
      # for a prose edit was the arm most commits already select; what pins the
      # UNDECLARED record trees is tests/guidance/ — the ADR numbering rule and
      # that byte-copy — which is a second of work, and `records` below is the arm
      # that runs exactly it.
      #
      # The narrowing is bounded by the MANIFEST, not by a glob, and that is what
      # makes it safe. A `subject` record in tests/assurance_cohort.txt answers
      # the question this arm asks: which artifacts can an edit BREAK a cohort
      # module over? That is wider than the question the AST derivation asks —
      # which single artifact does a module name as a path literal — because a
      # module that globs a tree joins the cohort through one literal and then
      # guards every file it finds. tests/test_cal1566_retired_tile_system_not_current.py
      # is the live case: it names specs/features/coffee-art.md exactly AND runs
      # `(REPO_ROOT / "specs" / "features").glob("*.md")` over the whole tree, so
      # the manifest carries the file record and the TREE record beside it. A
      # blanket `specs/*` re-route would leave that guard running on the one file
      # the literal names and off every other feature spec. So the arm asks the
      # manifest per file, the same shape as the tests/* arm below: routing and
      # invocation read the same bytes.
      #
      # CLAUDE.md and AGENTS.md therefore keep the full arm because the manifest
      # DECLARES them, not because this pattern names them. There is deliberately
      # no literal carve-out for the two: the mechanism is the point, and a
      # carve-out would keep them covered while the next declared record was not.
      #
      # What the ticket makes cheap, stated at its real size so nobody reads this
      # arm as "specs/ got cheap": assessments/, strategy/, decisions/, and
      # specs/proposals/ except the two declared coffee-art proposals.
      # specs/features/ is a declared TREE subject and still pays the full cohort,
      # exactly as it did before this ticket.
      #
      # Ordered FIRST, and it still has to be. `pyproject.toml|*.lock` at the foot
      # of this block is an UNANCHORED suffix glob, so a `specs/foo.lock` would
      # otherwise match it and take backend,lockcheck. Nothing else in the block
      # can match these paths, so the position costs nothing and closes that one.
      assessments/*|specs/*|decisions/*|strategy/*|CLAUDE.md|AGENTS.md|harness.yaml)
        if is_assurance_subject "$f"; then areas="$areas,assurance"
        else areas="$areas,records"; fi ;;
      # This repo's own .claude/ surface (2026-09-06): the session-start hook and
      # settings.json. Both were already DECLARED subjects of the cohort, and
      # neither routed anywhere — `is_assurance_subject` is only consulted from
      # the record arm above, whose pattern does not reach .claude/, so an edit to
      # either matched nothing and took the empty-scope backend fallback. That
      # fallback `--ignore`s the cohort, so the modules that measure these files
      # were the ones it skipped. Same `subject`-driven test as the record arm
      # rather than a blanket `.claude/*` → assurance, so what routes here is the
      # manifest's business and not a second list that can disagree with it: an
      # undeclared .claude/ path keeps today's behaviour and adds no area.
      .claude/*)
        if is_assurance_subject "$f"; then areas="$areas,assurance"; fi ;;
      # The .github/ config surface (CAL-1244). Nothing matched it before, so a
      # change here detected NO scope and fell through to the empty-scope backend
      # fallback — a gate blind to the change — or, bundled with a mapped change,
      # escaped every gate (the masking hole the crawler/ and scripts/ arms closed).
      #
      # dependabot.yml earns its OWN area rather than backend, for two reasons.
      # Its failure mode is silent: GitHub reports a config error on a settings
      # page nobody watches and simply stops opening update PRs, which looks
      # exactly like a quiet week. And routing it to backend would be
      # indistinguishable from the fallback it already reached, so no test could
      # tell the arm from its absence. The check is a dependency-free schema
      # validation, so the area costs no Docker and no Postgres.
      # GitHub accepts either suffix for this file.
      .github/dependabot.yml|.github/dependabot.yaml) areas="$areas,ghconfig" ;;
      # The workflows beside it fail VISIBLY on their next run, so they get no
      # schema check — they take the area that runs the committed-text tests
      # already pinning them (test_cal939_promotion_gate_workflow.py,
      # test_railway_migrate_release_command.py, test_promotion_preflight_wiring.py,
      # test_cal1291_eas_build_workflow.py, test_cal1541_shell_lexer.py, …), so
      # those run on the change that can break them rather than only via the
      # fallback. That area was `backend` until CAL-1545; every one of those
      # modules is now in the assurance cohort, so the same reasoning points here
      # and a workflow edit stops costing a Postgres and the whole product suite.
      .github/*) areas="$areas,assurance" ;;
      # The check, its vendored schema, and its own test must select the gate that
      # runs them — the CAL-1066 lesson (scripts/checks/mobile-file-size's test
      # rotted for months because nothing selected it). All three also match
      # broader arms below (scripts/*.py, tests/*), so they are ordered first.
      # The script keeps a second area as well: `case` stops at the first match,
      # so without it the later scripts/*.py arm never fires and no lint would run
      # on a change to the check itself — and here the local gate is the real gate
      # (CLAUDE.md). That second area was `backend` until CAL-1545; it is now
      # `assurance`, which lints scripts/ and tests/ and runs
      # tests/test_github_config_gate.py — the module that owns this check and is
      # in the cohort. Every sibling specialised arm keeps the same shape
      # (gen-api.sh → backend,openapi; dump-openapi-controlplane.py →
      # backend,controlplane). The vendored JSON is data, not linted Python, so it
      # takes ghconfig alone and a schema edit stays cheap.
      scripts/checks/github_config.py) areas="$areas,assurance,ghconfig" ;;
      scripts/checks/schemas/*) areas="$areas,ghconfig" ;;
      tests/test_github_config_gate.py) areas="$areas,assurance,ghconfig" ;;
      # Its CAL-1505 sibling, and `backend` rather than `assurance` on purpose.
      # The module derives the SDK-decided package set from
      # mobile/node_modules/expo/, an npm INSTALL, so it is deliberately absent
      # from tests/assurance_cohort.txt — the assurance job installs no Node and
      # every one of these tests would be red there while green on every machine
      # that runs the local gate. `backend` is the arm that lints tests/ and runs
      # this module unfiltered (backend_gate --ignores only cohort members). Both
      # arms establish that install themselves — see ghconfig_gate's header for
      # the night that proved they have to. Ordered with its sibling above, ahead
      # of the manifest-driven tests/* arm, so the `ghconfig` half wins.
      tests/test_cal1505_sdk_decided_packages.py) areas="$areas,backend,ghconfig" ;;
      # A hand-edit of the generated mobile API client must be re-checked against
      # the backend contract — match it BEFORE the broader mobile/* arm.
      mobile/generated/*) areas="$areas,mobile,openapi" ;;
      # mobile/app/** IS the Expo Router route tree. The control plane's App
      # Flow area derives its ENTIRE node set from this directory
      # (discover_screens() in app/services/controlplane_app_flow.py), so a
      # route add/rename/delete must select controlplane — otherwise the
      # scorecard-drift test that catches an unscored new screen never runs on
      # the change that causes the drift (CAL-1217). Deliberately narrow: only
      # the route tree, not all of mobile/*, so the common mobile path does not
      # pay the controlplane gate. Ordered BEFORE the mobile/* arm.
      # It is also a raw-value SCAN_ROOT, so it earns rawlint as well.
      #
      # This arm USED to select `design` too (CAL-1064), because
      # design/build/flows.html was generated from this same directory by
      # design/tooling/flows.mjs and guarded by flows:check under the design
      # gate. CAL-1228 deleted that walker and its artifact — the App Flow area
      # renders the map live — so nothing under design/ is generated from the
      # route tree any more, and keeping the arm would charge every route
      # ticket the token-build gate for nothing.
      mobile/app/*) areas="$areas,mobile,rawlint,controlplane" ;;
      # The other five roots the raw-value lint reads (SCAN_ROOTS in
      # design/tooling/lint/no-raw-values.mjs). Nothing is GENERATED from them,
      # so they do not earn the heavy design gate — but the lint scans them, and
      # for a long time nothing selected it: a raw value introduced under lib/,
      # components/ or store/ shipped green and then detonated on the next
      # person to touch a route file. dev was red for two tickets that way
      # (CAL-1076 lib, CAL-1065 components) before CAL-1066 surfaced it. The
      # lint is a dependency-free regex scan, so selecting it costs ~nothing —
      # that is why it splits out of design rather than widening design.
      # Keep in step with SCAN_ROOTS: tests/test_verify_sh_scope.py derives its
      # assertions from that export and fails if a root has no arm here.
      # app.config.ts joins its static half here: the two are one resolved Expo
      # config, so it can override the colours app.json is scanned for and must
      # not be the unread half (CAL-1086). It cannot match the mobile/app/* arm
      # above — that needs a literal slash after `app` — so without this it falls
      # through to plain mobile/* and the lint never runs.
      # Ordered BEFORE the mobile/* arm.
      mobile/components/*|mobile/lib/*|mobile/store/*|mobile/app.json|mobile/app.config.ts)
        areas="$areas,mobile,rawlint" ;;
      # The npm manifest pair (CAL-1501). Nothing gated it: lockcheck recompiles
      # requirements*.lock from pyproject.toml (Python only), and
      # scripts/checks/ensure-node-modules.mjs proves an INSTALL matches the
      # lockfile, never that the lockfile follows from its manifest. So a
      # package-lock.json that no longer follows from package.json shipped green
      # — release commit 4e925dd dropped `"dev": true` from the
      # node_modules/fsevents entry, the marker that says the package is reached
      # only through devDependencies, and it survived two promotions.
      #
      # Its own area, for the same reason lockcheck splits out of backend: the
      # pair alone selects it, so an ordinary mobile change does not pay for a
      # registry round-trip. It KEEPS `mobile` because it is ordered before the
      # mobile/* arm below and first match wins — without it a manifest change
      # would silently stop running the mobile gate.
      mobile/package.json|mobile/package-lock.json) areas="$areas,mobile,npmlock" ;;
      mobile/*) areas="$areas,mobile" ;;
      # Built tokens feed the mobile typecheck, so a token change re-runs the
      # mobile gate. `engine` is the CAL-1262 half: the design corpus is the
      # SUBJECT of the control plane's design engine, and CAL-1225 moved the
      # ADR-025 byte-identical round-trip guard (check.mjs) out of
      # design/tooling/workbench/ into controlplane/engine/, unchained from
      # design/package.json's tokens:lint. Until this arm named it, a design-doc
      # edit selected no gate that owns any invariant over design/ content — the
      # guard could not run on the only change that can break it. It is a
      # distinct area rather than `controlplane` because the control-plane gate
      # also runs tsc/eslint/vitest/openapi-drift, which a prose edit cannot
      # affect and which need controlplane/node_modules; the arms a design edit
      # needs are dependency-free node scripts (see engine_gate).
      # design/07-flows/*.md is the CORPUS of a backend test, and the only design
      # sub-tree that is (CAL-1581). app/services/controlplane_app_flow.py reads
      # those docs and the live Expo route tree together and
      # tests/services/test_controlplane_app_flow.py pins the graph that comes
      # out — so a flow-doc edit must select an arm able to run that module.
      # design+mobile+engine cannot: none of them runs a Python test. Three
      # commits grew the onboarding flow on 2026-08-27, each edited
      # design/07-flows/onboarding.md, each gated green on those three areas, and
      # dev went red on the next unrelated backend change.
      #
      # `flowmap` rather than `backend` for the same reason engine_chain_gate and
      # app_flow_scorecard_gate are their own arms: the pin is sub-second pure
      # Python over the working tree, and the backend arm is the whole suite
      # against a real Postgres. Charging a prose edit for that would be the
      # saving the specialised arms exist to make, thrown away.
      #
      # Ordered BEFORE the generic design/* arm below — first match wins — and
      # ADDITIVE to it: a flow doc is still design content, so it keeps the token
      # build, the mobile typecheck and the round-trip guard.
      #
      # Both design arms then ask the manifest (CAL-1657), the same
      # `subject`-driven test the record and .claude/* arms above already use.
      # tests/assurance_cohort.txt declares design/04-primitives/coffee-tile/spec.md
      # a subject: tests/test_cal1566_retired_tile_system_not_current.py reads it,
      # is a cohort member, and backend_gate therefore --ignores that module out of
      # the backend arm. Routing sent the file through the generic design/* arm to
      # design+mobile+engine, none of which runs a Python test, so the guard ran on
      # the three coffee-art RECORDS it also names (they reach `assurance` through
      # the record arm) and was inert on the design artifact — the CAL-1066 shape,
      # a check whose test nothing selects.
      #
      # Appended INSIDE each arm rather than added as a third arm ahead of them.
      # An arm ordered ahead of BOTH would strip `flowmap` from a declared
      # design/07-flows/* subject; one placed BETWEEN them could never be reached by
      # a flows subject at all. Appending is additive by construction — the areas
      # each arm already contributes are untouched — and it keeps the property the
      # record arm was built for: each arm asks the manifest itself rather than a
      # second list that can disagree with it, so an undeclared design path keeps
      # today's behaviour and adds no area.
      design/07-flows/*)
        areas="$areas,design,mobile,engine,flowmap"
        if is_assurance_subject "$f"; then areas="$areas,assurance"; fi ;;
      design/*)
        areas="$areas,design,mobile,engine"
        if is_assurance_subject "$f"; then areas="$areas,assurance"; fi ;;
      # controlplane/'s OWN OpenAPI contract source (app/routers/controlplane.py,
      # app/schemas/controlplane.py) — matched BEFORE the generic app/* arm so a
      # change here also re-runs the control-plane gate (its own drift check
      # against controlplane/src/generated/api.ts, CAL-1183), not the mobile
      # openapi gate: controlplane's routes are flag-gated and never appear in
      # the unflagged app.openapi() the mobile drift gate dumps.
      app/routers/controlplane.py|app/schemas/controlplane.py) areas="$areas,backend,controlplane" ;;
      # app/** is the source of the OpenAPI contract, so a route/schema change
      # also re-verifies the generated client is in sync (openapi). The other
      # backend paths (alembic/tests/crawler) do not feed the contract.
      app/*) areas="$areas,backend,openapi" ;;
      # The cohort manifest itself (CAL-1545). It decides BOTH arms' composition,
      # so an edit must run the arm carrying the membership contract able to
      # refuse it — tests/test_assurance_cohort_membership.py, which re-derives
      # the cohort and fails on an undeclared consumer or a stale member.
      tests/assurance_cohort.txt) areas="$areas,assurance" ;;
      # The EY parity CASE TABLE (CAL-1635) — the one thing under tests/ with a
      # reader outside the backend gate, so ordered BEFORE the generic tests/*
      # arm below for the same reason as the three arms above.
      #
      # tests/fixtures/ey_parity.json holds the shared cases for the CAL-128
      # extraction-yield parity obligation between
      # app/services/brew_calculations.py::compute_extraction_yield and
      # mobile/lib/brewPayload.ts::computeExtractionYield. The backend gate owns
      # one half (tests/test_brew_calculations_parity.py, plus the API pass in
      # tests/test_cal489_api_ey_parity.py); the MOBILE gate owns the half it
      # cannot see — that the client still agrees with those same rows
      # (mobile/lib/__tests__/eyParity.test.ts). Under plain `backend` the very
      # commit the mobile arm exists to catch — the rule and the fixture edited
      # together, which keeps the backend suite green by construction — would
      # pass the gate while the client's half never ran, and a client silently
      # diverged from the server would ship green.
      tests/fixtures/ey_parity.json) areas="$areas,backend,mobile" ;;
      # The BREW-RATIO parity CASE TABLE (CAL-1633) — the second file under
      # tests/ with a reader outside the backend gate, and here for exactly the
      # reason the arm above is.
      #
      # tests/fixtures/brew_ratio_parity.json holds the shared cases for the
      # ADR-038 C6 obligation between the generated column Brew.brew_ratio
      # (app/models/brew.py) and its capture-time mirror
      # mobile/lib/ratio.ts::brewRatioValue. The backend gate owns the half that
      # measures the column itself against real Postgres
      # (tests/test_brew_ratio_parity.py); the MOBILE gate owns the half it
      # cannot see — that the client still agrees with those same rows
      # (mobile/lib/__tests__/brewRatioParity.test.ts). Under plain `backend` the
      # very commit this pair exists to catch — the column's expression and the
      # fixture edited together, which keeps the backend suite green by
      # construction — would pass the gate while the client's half never ran.
      tests/fixtures/brew_ratio_parity.json) areas="$areas,backend,mobile" ;;
      # tests/* cannot be a static arm (CAL-1545). A cohort module must select
      # `assurance` and an ordinary product test must select `backend`, and the
      # cohort is manifest-derived — a literal list here would be exactly the
      # second hand-kept copy the single-source rule exists to prevent. So the arm
      # asks the manifest per changed file: the routing and the invocation read
      # the same bytes and cannot disagree. Cost: one `awk` per changed test file.
      # Ordered AFTER tests/test_github_config_gate.py above so that arm's
      # `ghconfig` half still wins, and BEFORE alembic/crawler below.
      tests/*)
        if is_assurance_path "$f"; then areas="$areas,assurance"
        else areas="$areas,backend"; fi ;;
      alembic/*|crawler/*) areas="$areas,backend" ;;
      # The whole controlplane/ package (SPA + its own scripts) — its gate is
      # self-contained (no-raw-values, tsc, eslint, vitest, its own openapi
      # drift check) and does not need the design token build or Postgres.
      # The relocated ERD artifact (CAL-1227). Its drift guard is the PYTHON
      # measuring test tests/test_erd.py, which runs in the backend gate — so a
      # change here must select backend as well, or the one check that proves
      # the file still matches Base.metadata never runs. Ordered BEFORE the
      # generic controlplane/* arm.
      controlplane/data/*) areas="$areas,backend,controlplane" ;;
      controlplane/*) areas="$areas,controlplane" ;;
      # catalog/ (CAL-1250, ADR-031): an isolated, independently deployable
      # Python project — its own pyproject.toml, own tests, own verify.sh. A
      # change anywhere under it must select ITS gate (catalog_gate below),
      # not the root backend gate: catalog/ is excluded from root pytest's
      # testpaths and from the root package.find allowlist (design doc §8),
      # so nothing else would ever run its suite.
      # The Catalog's PORT MANIFEST (CAL-1254 AC-3) — the one file under
      # catalog/ that must select both gates, so ordered BEFORE the generic
      # catalog/* arm. It declares which Catalog test carries each legacy
      # crawler safety behaviour, and its invariant is checked from two sides
      # that live in different suites: the catalog gate proves every DECLARED
      # counterpart exists, while the ROOT suite's
      # tests/test_catalog_port_manifest_is_current.py proves every test in
      # tests/crawler/ is accounted for. Under plain `catalog` a change that
      # deleted a manifest entry AND its Catalog test would pass the catalog
      # gate — whose half only checks declared entries — while the completeness
      # half never ran, and a dropped SSRF or robots port would ship green.
      # Same "edit the artifact, re-run the gate that owns its invariant"
      # pattern as controlplane/data/* and scripts/dump-openapi.py above.
      catalog/tests/ingestion/ported_behaviours.py) areas="$areas,catalog,backend" ;;
      # The Catalog's COMMITTED CONTRACT (CAL-1252) — the second file under
      # catalog/ that must select both gates, and ordered BEFORE the generic
      # catalog/* arm for the same reason as the port manifest above. The
      # catalog gate owns its drift half (test_openapi_drift.py: the committed
      # document equals what the app serves), while the ROOT suite's
      # tests/test_discovery_signal_contract_parity.py owns the other half —
      # that the Calibrate publisher's payload still matches the contract. The
      # two projects may not import each other, so this file is the ONLY
      # channel between them; under plain `catalog` a change to the event
      # schema made purely inside catalog/ would pass the catalog gate while
      # nothing ever re-checked the sender, and a silently incompatible
      # publisher would ship green.
      catalog/openapi.json) areas="$areas,catalog,backend" ;;
      # The Catalog's LEGACY FIXTURES (CAL-1251) — the third thing under
      # catalog/ that must select both gates, and ordered BEFORE the generic
      # catalog/* arm for the same reason as the two above.
      #
      # catalog/tests/legacy/fixtures/ holds committed copies of
      # crawler/data/{roaster_list,roasters}.json plus a conformance corpus whose
      # expected documents are produced by the LEGACY rules. The Catalog gate
      # owns one half (its projection reproduces those bytes); the ROOT suite
      # owns the two halves it cannot see — that the fixtures still match
      # crawler/data/ (tests/test_catalog_legacy_fixture_is_current.py) and that
      # each expected document is really what crawler/ produces
      # (tests/test_legacy_conformance_corpus_is_current.py). Under plain
      # `catalog`, a change that edited a fixture AND the Catalog test reading it
      # would pass the catalog gate while both root halves never ran, and a
      # drifted compatibility oracle would ship green.
      catalog/tests/legacy/fixtures/*) areas="$areas,catalog,backend" ;;
      catalog/*) areas="$areas,catalog" ;;
      # The isolated OpenAPI dump controlplane's OWN drift gate shells out to
      # (check-openapi-drift.sh → gen-api.sh → dump-openapi-controlplane.py).
      # Editing it must re-run that gate, or a codegen bug ships unverified.
      # Ordered BEFORE the scripts/*.py arm so this wins over plain backend.
      scripts/dump-openapi-controlplane.py) areas="$areas,backend,controlplane" ;;
      # The OpenAPI codegen the drift gate itself shells out to (openapi_drift_gate
      # → scripts/gen-api.sh → scripts/dump-openapi.py). Editing the generator must
      # re-run the drift gate against the committed client, or a codegen bug ships
      # unverified. Ordered BEFORE the scripts/*.py arm so dump-openapi.py wins
      # openapi rather than falling through to plain backend.
      scripts/gen-api.sh|scripts/dump-openapi.py) areas="$areas,backend,openapi" ;;
      # The mobile size check + its unit test run under the mobile gate (size_gate),
      # so editing either must select mobile — otherwise nothing runs them. Nothing
      # did: the check's test asserted brew/index.tsx was unmarked long after
      # CAL-1018 marked it, and no gate ever noticed (CAL-1066). Ordered before the
      # broader scripts/* arms; deliberately named rather than scripts/checks/*,
      # which also holds design (ds-freshness) and non-mobile checks.
      scripts/checks/mobile-file-size.sh|scripts/checks/mobile-file-size.test.sh)
        areas="$areas,mobile" ;;
      # The node_modules freshness guard + its unit test (CAL-1274). `mobile` runs
      # both — the self-test in the dispatch below, and the guard itself against a
      # real install — and the second area runs the pytest end-to-end tests in
      # tests/test_verify_sh_scope.py that drive this script. That was `backend`
      # until CAL-1545 and is now `assurance`, which is where that module runs.
      # Named explicitly for the same reason as the size check above:
      # scripts/checks/ also holds design and non-node checks, so the directory is
      # the wrong granularity. Ordered before the broader scripts/* arms.
      scripts/checks/ensure-node-modules.mjs|scripts/checks/ensure-node-modules.test.mjs)
        areas="$areas,assurance,mobile" ;;
      # The declared assurance SUBJECT scripts (CAL-1545) — the materialised gate
      # runner trio (CAL-1662), the worker budget, and the release/promotion
      # checks. Each is pinned only by cohort modules (test_cal1662_gate_runner,
      # test_eas_build_gate, test_ios_release_gate, test_railway_env_preflight,
      # test_release_provenance, test_bare_python3_interpreter_floor), and
      # `assurance` lints scripts/ too, so nothing is lost by not selecting
      # backend. Named rather than scripts/checks/* — that directory also holds
      # the design, mobile and node checks — and ordered before the broad
      # scripts/*.py arm below, which stays `backend` for ordinary
      # seed/backfill/ERD scripts. `scripts/` has no other `*.js`/`*.json` arm,
      # so without this an edit to the trio would map to nothing.
      scripts/gate-marker.js|scripts/harness-config.js|scripts/package.json|scripts/worker_budget.py|scripts/checks/eas_build_gate.py|scripts/checks/ios_release_gate.py|scripts/checks/railway_env_preflight.py|scripts/checks/release_provenance.py)
        areas="$areas,assurance" ;;
      # Other ops scripts (container entrypoint, seed/backfill/ERD Python, …) are
      # backend infra but do not feed the API contract → backend only. Without a
      # mapping a bundled mobile change would mask them out of every gate.
      scripts/docker-entrypoint.sh|scripts/*.py) areas="$areas,backend" ;;
      alembic.ini|compose.yaml) areas="$areas,backend" ;;
      # The gate itself (CAL-1545). It took `backend` — the whole product suite and
      # a Postgres — to verify a change to a shell script. The four modules that
      # actually DRIVE its arms (test_verify_sh_scope, test_verify_sh_daemonless,
      # test_verify_sh_worktree, test_cal1282_verify_sh_compose_migrate) are all in
      # the assurance cohort, and both promotion boundaries run VERIFY_ALL=1, which
      # selects every area. What is genuinely given up is the incidental app/
      # coverage a verify.sh edit used to buy; that trade is recorded in
      # specs/features/deployment-gates.md rather than left to be rediscovered.
      scripts/verify.sh) areas="$areas,assurance" ;;
      # The Railway service configs. Each is pinned by a committed-text test in
      # the ROOT suite (test_railway_migrate_release_command.py for railway.json,
      # test_cal1252_publisher_railway_config.py for railway.publisher.json), so
      # a change here must run the backend gate. Alone it would fall through to
      # the default-scope branch and be fine; bundled with a mobile-only change
      # the detector selects `mobile`, the default never applies, and the pin
      # never runs — the same masking hole the port-manifest and openapi.json
      # arms above each exist to close.
      railway*.json) areas="$areas,backend" ;;
      Dockerfile*) areas="$areas,backend" ;;
      # A dependency-surface change also runs the lockfile-sync gate (below):
      # requirements*.lock — what the Docker image installs — can drift from
      # pyproject.toml/uv.lock silently. *.lock matches both requirements*.lock
      # and uv.lock; either changing means re-verify the compiled lock.
      pyproject.toml|*.lock) areas="$areas,backend,lockcheck" ;;
    esac
  done <<< "$files"
  printf '%s' "$areas"
}

# Echo a comma list of the jest projects the mobile arm must run for this working
# tree — the mobile arm's second dimension (CAL-1651).
#
# The mobile arm is the gate's largest cost centre — 51% of all gate seconds, the
# figure specs/proposals/mobile-gate-arm-cost.md was accepted on — and it ran all
# seven of mobile/jest.config.js's projects on every mobile change. How often it
# fires is measured here rather than quoted, and every commit-share figure in this
# block comes from the same run: each commit of `git log origin/dev --name-only`
# replayed through THIS script one file-list at a time under VERIFY_PRINT_SCOPE=1,
# so the answers are the gate's own. At 2026-09 that selects the mobile arm on 275
# of origin/dev's 751 commits (37%). The proposal's "62% of commits" does not
# reproduce on that denominator — but the difference is the BASIS, not a bad
# number: `git log --name-only` prints a combined diff for a merge, empty for an
# ordinary one, so merges mostly drop out of the numerator while staying in the
# denominator. Over NON-MERGE commits, the population a developer actually
# experiences, the CAL-1651 review's re-measurement of the same history gives 51%
# (276 of 539), and 62% over the last 91 — which reproduces the proposal's figure.
# So it is most likely a recent-window non-merge rate rather than a wrong one, and
# the 37% above is a full-history all-commits rate; which basis to quote is an open
# question for the proposal (see specs/features/deployment-gates.md, "How often the
# mobile arm fires").
# Measured on dev @ 6b0b715 (4-core, idle): lib 114s / art-pixel 211s /
# export-manifest 26s / components 21s / screens 6s / art 3s / build-config 3s;
# jest total 376s. `art-pixel` is 56% of that for 1.7% of the tests, and its nine
# suites live wholly in mobile/components/art/ (3) and mobile/components/share/
# (6), rendering through mobile/lib/coffeeArt/ and mobile/lib/shareCard/. A change
# that cannot reach the rasteriser should not pay to rasterise.
#
# EMPTY output means UNRESTRICTED — every project runs, and mobile_gate invokes
# jest exactly as it did before this function existed. That is the fail-safe
# direction, and three things resolve to it: an explicit VERIFY_SCOPE / VERIFY_ALL
# (which never calls this at all), a non-mobile path that selects the mobile arm
# anyway (design/*, the two mobile checks under scripts/, the EY parity case table
# under tests/fixtures/ — each has its OWN arm below setting the flag, because a
# path that merely matches nothing leaves the rest of the diff's narrower
# selection standing), and the catch-all at the foot of the block.
#
# `lib` is named by EVERY arm, deliberately. It is the only project that
# contributes to the enforced coverage floor — jest.config.js's
# collectCoverageFrom is lib/**/*.ts and every other project sets
# coveragePathIgnorePatterns over <rootDir>/lib/ — so a selection without it would
# run the gate with the ratchet silently unevaluated, which is not a lowered floor
# but an absent one. Measured for this ticket: `--selectProjects lib` reproduces
# the full seven-project run's coverage summary exactly (statements 5692/5853,
# branches 2573/2769, functions 1154/1239, lines 4933/5051).
#
# Same ordered first-match `case` idiom as detect_scope, and the same rule for
# reading it: a path matching an early arm never reaches a later one, so an arm
# that also needs a later arm's project names it itself.
detect_jest_projects() {
  local files f raw="" unrestricted=0
  files="$(changed_files)"
  [ -n "$files" ] || return 0
  while IFS= read -r f; do
    [ -z "$f" ] && continue
    case "$f" in
      # THE NON-MOBILE PATHS THAT SELECT THE MOBILE ARM. detect_scope routes five
      # things outside mobile/ into the mobile gate: the whole design/ tree (built
      # tokens feed the mobile typecheck), the two checks under scripts/checks/
      # that the mobile gate itself runs, each a source/self-test pair, and the
      # two parity case tables tests/fixtures/ey_parity.json and
      # tests/fixtures/brew_ratio_parity.json, whose client halves ride the mobile
      # gate (mobile/lib/__tests__/eyParity.test.ts,
      # mobile/lib/__tests__/brewRatioParity.test.ts) — eight arms for
      # five subjects. None of them can be routed by the mobile arms
      # below, and leaving them unmatched does NOT leave the selection alone — it
      # leaves whatever the rest of the diff selected, which is a narrowing. A
      # design token reaches the rasteriser (design/build/tokens → @ds/tokens →
      # mobile/lib/theme.ts → lib/coffeeArt/render.ts, lib/shareCard/render.ts,
      # components/art/, components/share/), so the common UI shape — move a token
      # AND a component in one commit — deselected art-pixel on exactly the change
      # that can repaint every raster in the app. Blast radius unknowable from the
      # path, therefore unrestricted, the same answer the catch-all gives mobile
      # infrastructure. tests/test_verify_sh_scope.py derives this set from
      # detect_scope's own arms, so a sixth one fails there before it can ship —
      # which is how both fixtures got here: CAL-1635 added ey_parity.json's
      # detect_scope arm on dev while this block was in review, and the derived
      # guard failed on the merge rather than letting a bundled EY change narrow
      # the mobile arm; CAL-1633 added brew_ratio_parity.json's arm and the same
      # guard reddened first, before this line was written.
      design/*|scripts/checks/mobile-file-size*.sh|scripts/checks/ensure-node-modules*.mjs|\
      tests/fixtures/ey_parity.json|tests/fixtures/brew_ratio_parity.json)
        unrestricted=1 ;;
      # THE SKIA RENDERER'S IMPORT CLOSURE: the two component directories holding
      # every `.skia.` and `.skia.pixel.` suite, the two pure renderer packages
      # they drive, and the six lib modules those suites import DIRECTLY to build
      # what they raster (a tile, a card's content model, a palette).
      #
      # This list is not a judgement about which files "look like" renderer code.
      # tests/test_verify_sh_scope.py parses the suites' own import specifiers and
      # fails if any resolved module is missing from here, so the arm and the
      # closure cannot disagree. That guard exists because this list was already
      # wrong when it shipped — lib/shareCard/ was absent while four suites raster
      # it (ShareCard.skia.pixel, ShareCardTone.skia.pixel, ShareCardLayers.skia,
      # shareCardFonts.skia) — and a hand-fix would not have stopped the next one.
      # Cost of the closure, measured the way this function's header describes: of
      # the 275 commits that select the mobile arm, 28 (10%) touch one of the six,
      # and 13 (5%) pay art-pixel ONLY because they do — the other 15 would have
      # paid through a renderer directory or a widening path anyway. That is this
      # ARM'S OWN price and not the gate's overall rate: the two renderer
      # directories above and the widening catch-all below select art-pixel too, so
      # end to end 114 of the 275 (41%) skip its 211s while 161 (59%) still pay,
      # 128 of those because something in the commit widened the whole selection.
      # What the guard cannot reach is the TRANSITIVE closure, and that residual is
      # what the widening catch-all at the foot exists for.
      #
      # `components` and `screens` come too: first match wins, so this arm has to
      # name whatever the mobile/components/* and mobile/lib/* arms below would
      # have given these same paths — components/art/ and components/share/ hold
      # ORDINARY component suites that the `components` project's glob reaches, and
      # a screen renders a coffee tile.
      mobile/components/art/*|mobile/components/share/*|\
      mobile/lib/coffeeArt/*|mobile/lib/shareCard/*|\
      mobile/lib/theme.ts|mobile/lib/cardContent.ts|mobile/lib/coffees.ts|\
      mobile/lib/brewCoffee.ts|mobile/lib/brewPayload.ts|mobile/lib/flavourTaxonomy.ts)
        raw="$raw,lib,components,screens,art,art-pixel,export-manifest" ;;
      # The screen-wiring suites and the export-manifest suite. Test files, not
      # bundled app source, so neither reaches the other's project.
      mobile/__tests__/screens/*) raw="$raw,lib,screens" ;;
      mobile/__tests__/export/*) raw="$raw,lib,export-manifest" ;;
      # `export-manifest` rides along with every arm over BUNDLED source, not just
      # with its own test file. mobile/__tests__/export/fontManifest.test.js
      # measures the artifact `expo export` produces — the exact set of font faces
      # it ships — and the defect it was written for is a module importing an
      # `@expo-google-fonts/<family>` package ROOT, which drags in all 18 or 6
      # faces of that family behind a `require` Metro cannot tree-shake. That
      # import can be added in any file the bundle reaches: app/, components/ or
      # lib/. Narrowing this to its own test file would leave the 24-TTF payload
      # invisible until promotion, which is the masking shape the whole gate is
      # built against. 26s of the 376.
      #
      # `screens` rides along for the same reason one level down: a screen suite
      # renders real route modules, which pull components in transitively, so a
      # component change can break one. 6s of the 376 — the risk is not worth
      # carrying at that price.
      mobile/components/*) raw="$raw,lib,components,screens,export-manifest" ;;
      # The Expo Router route tree: `screens` runs against it, and app/_layout.tsx
      # is where the font faces the export asserts on are registered.
      mobile/app/*) raw="$raw,lib,screens,export-manifest" ;;
      # A lib module's consumers run with it: 69 of the 94 component suites import
      # lib/, and the screen suites reach it through the components they render.
      # components 21s + screens 6s is 7% of a 376s run, against `art-pixel`'s 211s
      # (56%) which is the saving this block exists for and which this arm still
      # does not buy.
      mobile/lib/*) raw="$raw,lib,components,screens,export-manifest" ;;
      # mobile/jest/__tests__/ — and ONLY that subdirectory — is `build-config`'s
      # own subject: jest.config.js names `<rootDir>/jest/__tests__/**/*.test.js` in
      # that project's testMatch and no other project runs those files, so a change
      # to one changes no runtime and the 3s arm is worth having.
      #
      # The REST of mobile/jest/ is deliberately NOT here. It is the runtime wiring
      # of every OTHER project — skia-environment.js is art/art-pixel's
      # testEnvironment, mocks/react-native-skia.tsx is the components and screens
      # Skia stub, portable-transform.js is every project's transform,
      # zoned-environment.js is `lib`'s environment, allow-transform.js builds the
      # shared transformIgnorePatterns, console-error-guard.js backs the guard every
      # React-rendering project loads. The first pass mapped the whole directory
      # here, so editing the CanvasKit environment DESELECTED the two CanvasKit
      # projects; those files now fall through to the infrastructure catch-all
      # below, and tests/test_verify_sh_scope.py derives that set from the directory
      # so a new wiring file cannot re-open the hole.
      mobile/jest/__tests__/*) raw="$raw,lib,build-config" ;;
      # THE CONSERVATIVE-WIDENING RULE, and the anti-masking half of this block.
      # A path under mobile/ that matched none of the arms above is mobile
      # INFRASTRUCTURE — jest.config.js, tsconfig.json, package.json,
      # babel.config.js, metro.config.js, the jest.setup.* files, and the runtime
      # wiring under mobile/jest/ that the arm above deliberately leaves unmatched —
      # whose blast radius is not knowable from the path. mobile/store/ and
      # mobile/generated/ land here too, and correctly: nothing tests either
      # directly and everything reads them. So they widen to every project rather
      # than narrowing to `lib`.
      # The rule this encodes: divergence from the arms above may only ever WIDEN
      # the selected set, never narrow it.
      mobile/*) unrestricted=1 ;;
    esac
  done <<< "$files"
  if [ "$unrestricted" = 1 ]; then return 0; fi
  # Normalise: dedupe, and emit in mobile/jest.config.js's own declaration order
  # so the selection reads the same whatever order the diff arrived in. This list
  # is also the ONE place the project names are written down, and
  # tests/test_verify_sh_scope.py pins it against the displayNames that file
  # declares — a new jest project therefore cannot be added without an arm here,
  # which is the masking hole this block would otherwise open on itself.
  # Matched comma-delimited, because `art` is a prefix of `art-pixel`.
  local out="" p
  for p in lib components art art-pixel screens build-config export-manifest; do
    case ",$raw," in *",$p,"*) out="${out:+$out,}$p" ;; esac
  done
  printf '%s' "$out"
}

# ----- resolve scope -----
# Resolve the base HERE, in the top-level shell, before anything consults it:
# changed_files() runs inside command substitutions and process substitutions,
# which are subshells, so a resolution performed there would be thrown away and
# repeated. Failure is not handled here — it means different things per branch
# below — so it is swallowed and read back off the memo.
resolve_base || true

if [ -n "${VERIFY_SCOPE:-}" ]; then
  set_from_list "$VERIFY_SCOPE"
elif [ "${VERIFY_ALL:-0}" = "1" ]; then
  run_backend=1; run_assurance=1; run_mobile=1; run_design=1; run_lockcheck=1; run_npmlock=1; run_openapi=1; run_rawlint=1; run_controlplane=1; run_ghconfig=1; run_engine=1; run_flowmap=1; run_catalog=1; run_records=1
else
  # Auto-detect is the ONE branch where a scope conclusion depends on the base,
  # so it is the one branch where an unresolvable base is fatal (CAL-1365).
  #
  # It used to be silently survivable: `git merge-base … || true` turned an
  # unresolvable base into an empty one, the committed-since-base arm contributed
  # nothing, and for work already committed there were no working-tree paths
  # either — so detect_scope saw zero changed paths, took the empty-diff fallback
  # below, and ran the backend gate over a diff it had never looked at. It
  # reported green having tested nothing relevant.
  #
  # Those are two different states and the fallback message can only describe one
  # of them. "No scoped changes detected" told an operator the tree was clean when
  # in fact nothing had been compared, and left them no way to guess the remedy.
  #
  # Fatality stops here on purpose. Every CI invocation supplies its own scope
  # (VERIFY_SCOPE / VERIFY_ALL=1) and runs on a checkout with neither a local
  # `dev` nor an `origin/dev`; making resolution fatal unconditionally would turn
  # the promotion gate red on every run. Where the caller stated the scope, no
  # conclusion rests on the base.
  if ! resolve_base; then
    echo "ERROR: cannot resolve the diff base '${BASE_NAME}' (tried '${BASE_NAME}' and 'origin/${BASE_NAME}')." >&2
    echo "       Scope auto-detection compares HEAD against that base, so without it this run" >&2
    echo "       cannot tell 'nothing changed' from 'nothing was compared' — and it will not" >&2
    echo "       guess a gate. Fetch the base branch, or point VERIFY_BASE at a ref this" >&2
    echo "       checkout has:" >&2
    echo "         VERIFY_BASE=origin/main bash scripts/verify.sh" >&2
    echo "       Or state the scope yourself: VERIFY_SCOPE=... / VERIFY_ALL=1." >&2
    exit 1
  fi
  # The second fatality, for the same reason as the first: a frozen merge-base
  # that cannot be diffed contributes zero paths, which is indistinguishable from
  # "that candidate changed nothing" and NARROWS the scope (CAL-1570). Checked
  # here, before any arm, so a run in that state exits non-zero without ever
  # reaching the gate marker at the foot of this file.
  require_diffable_bases || exit 1
  detected="$(detect_scope)"
  if [ -n "$detected" ]; then
    set_from_list "$detected"
    # The jest project dimension (CAL-1651) — auto-detect ONLY. Under an explicit
    # VERIFY_SCOPE or VERIFY_ALL the selection stays unrestricted: those callers
    # stated the scope, and both promotion boundaries and every CI job run
    # verify.sh that way over a checkout that resolves no base, so a restriction
    # there would be derived from a diff nobody looked at.
    JEST_PROJECTS="$(detect_jest_projects)"
  else
    echo "==> No scoped changes detected vs ${BASE_NAME}; running backend gate (default)."
    run_backend=1
  fi
fi

if [ "${VERIFY_PRINT_SCOPE:-0}" = "1" ]; then
  echo "scope: backend=${run_backend} assurance=${run_assurance} mobile=${run_mobile} design=${run_design} lockcheck=${run_lockcheck} npmlock=${run_npmlock} openapi=${run_openapi} rawlint=${run_rawlint} controlplane=${run_controlplane} ghconfig=${run_ghconfig} engine=${run_engine} flowmap=${run_flowmap} catalog=${run_catalog} records=${run_records} ios-release=${run_ios_release}"
  # The mobile arm's jest projects, on a line of their OWN (CAL-1651). The line
  # above is parsed as `name=<int>` pairs by tests/test_verify_sh_scope.py, and a
  # comma list of project names is not an integer. `all` is the wire form of the
  # unrestricted state — the one in which mobile_gate runs `npm run verify:core`
  # unchanged.
  echo "jest-projects: ${JEST_PROJECTS:-all}"
  exit 0
fi

# ----- gates -----
# Build the design tokens once when any gate needs them — both the mobile
# typecheck (@ds/tokens) and the design raw-value lint read the built tokens.
# Building here (rather than inside each gate) avoids rebuilding twice on a
# design-scope run, which selects both the design and mobile gates.
# Prove a node package's install matches its lockfile before a gate runs against
# it (CAL-1274). This replaces `[ -d node_modules ] || npm ci`, which is a
# PRESENCE check: a node_modules whose contents no longer matched
# package-lock.json was accepted, the gate ran anyway, and it reported green
# having tested against the wrong dependency tree — mobile/ sat at
# @testing-library/react-native 13.3.3 under a lockfile resolving 14.0.1, across
# that library's breaking 13→14 boundary, and verify.sh passed. It is the
# node-side counterpart of lockcheck_gate, which closes the same silent-drift hole
# on requirements*.lock.
#
# The check fails closed and NAMES the divergence rather than silently
# reinstalling: a reinstall would be better than today and still wrong, because it
# hides that the tree was ever stale and nobody learns which green run was not
# evidence. An absent node_modules is still just installed — that is the ordinary
# fresh-worktree case and the one behaviour carried over from the old idiom.
#
# A script rather than a shell function here so scripts/gen-api.sh — a separate
# file with the same hole — shares the implementation instead of copying it.
ensure_node_modules() {
  node "$REPO_ROOT/scripts/checks/ensure-node-modules.mjs" "$1"
}

# The machine-wide worker budget (CAL-1646). Nothing bounded how many processes a
# gate run spawns, and concurrent worktrees are the normal way work happens here:
# jest self-parallelises to cores-1, so three concurrent mobile arms put nine jest
# workers on a four-core machine, on top of each run's eslint, tsc and Postgres.
#
# `budget_run <max> <command...>` acquires up to <max> tokens from a pool in the
# git COMMON dir — shared by every worktree of this clone — and EXECS the command
# with VERIFY_WORKER_TOKENS set to the count it got. The command becomes the lock
# holder, so the kernel returns the whole allocation however it dies; that is why
# there is no release trap here, which matters because bash allows one EXIT trap
# and snapshot_artifacts already installs it.
#
# Blocking, per the proposal's decision 1: a run WAITS rather than logging and
# proceeding, because a budget that can be exceeded does not bound load, which is
# half of what this exists to fix. See scripts/worker_budget.py for the
# deadlock-freedom argument and the re-entrancy marker that keeps the assurance
# arm — which spawns this very script dozens of times — from queueing behind
# itself.
# `budget_run exclusive <command...>` (CAL-1653) maps to `--max all --exclusive`:
# the command runs only once it holds EVERY token, so nothing else budgeted on
# this machine — in any worktree — runs beside it. The one arm that asks is the
# art-pixel phase of mobile_gate, whose budget assertion is a wall-clock ratio.
# The wrapper is named by its LITERAL relative path and invoked from the repo
# root: that is how tests/test_bare_python3_interpreter_floor.py discovers a
# bare-`python3` script and holds it to the 3.9 floor, and a path in a shell
# variable would be invisible to that sweep. Two arms run their command from a
# subdirectory (`pushd mobile`, `pushd controlplane`), so the caller's directory
# is handed back with --chdir. The `cd` is in a subshell, so it never escapes and
# cannot disturb the pushd stack.
budget_run() {
  local max="$1" here="$PWD" exclusive=""; shift
  if [ "$max" = exclusive ]; then max=all; exclusive=--exclusive; fi
  ( cd "$REPO_ROOT" && python3 scripts/worker_budget.py run --max "$max" ${exclusive:+"$exclusive"} --chdir "$here" -- "$@" )
}

build_tokens() {
  echo "==> Building design tokens"
  ensure_node_modules design
  pushd design >/dev/null
  npm run tokens:build
  popd >/dev/null
}

# Snapshot the committed build artifacts BEFORE build_tokens overwrites them, so
# the drift guard (design/tooling/check.mjs, run via tokens:lint → tokens:check)
# compares a regeneration against the *committed* working-tree bytes rather than
# the just-rebuilt ones. Without this, build_tokens rewrites
# build/tokens.{json,ts,css} with fresh bytes first, so the check would compare
# fresh-vs-fresh and never see committed-artifact drift — the guard would be dead
# inside verify.sh (CAL-725 established the ordering on the html artifacts;
# CAL-744 extended it to the token artifacts, and CAL-1229's deletion of
# build/content.html leaves them as the only ones). check.mjs reads
# DRIFT_REF_DIR as the comparison reference when set; the snapshot pins it
# order-independently.
#
# CRITICAL: snapshot_artifacts MUST run BEFORE build_tokens. If a future change
# reorders these, the drift guard silently stops working inside verify.sh.
snapshot_artifacts() {
  DRIFT_REF_DIR="$(mktemp -d)"
  export DRIFT_REF_DIR
  for f in design/build/tokens.json design/build/tokens.ts design/build/tokens.css; do
    [ -f "$f" ] && cp "$f" "$DRIFT_REF_DIR/"
  done
  # Clean up the snapshot dir on exit (success or failure).
  trap 'rm -rf "$DRIFT_REF_DIR"' EXIT
}

design_gate() {
  echo "==> Design gate (token build, artifact drift, raw-value lint)"
  pushd design >/dev/null
  npm run tokens:lint
  popd >/dev/null
}

# The raw-value lint on its own, for a mobile change that the design gate does
# not cover (CAL-1085). design/tooling/lint/no-raw-values.mjs scans mobile
# source for un-tokenized colours and size literals; it imports nothing but node
# builtins and reads no built artifact, so it runs without `npm ci` and without
# a token build — cheap enough that every change to a file it reads can pay for
# it. That is the whole reason the lint splits out of design_gate instead of
# mobile/* widening into it: the checks that need the token build (artifact
# drift) stay behind design/*, while the check that reads mobile source is
# selected by mobile source changing.
#
# Its own unit test runs first: the lint's exemption logic is what decides
# whether a violation is reported at all, and nothing else runs that test on a
# mobile-only change (the same gap that let scripts/checks/mobile-file-size's
# test rot unnoticed until CAL-1066).
raw_value_gate() {
  echo "==> Raw-value lint (mobile source)"
  node design/tooling/lint/no-raw-values.test.mjs
  node design/tooling/lint/no-raw-values.mjs
}

# The typecheck / lint / jest arm.
#
# verify:core's three steps, in its order, with the jest step run in TWO PHASES
# (CAL-1653): every selected project but art-pixel under the ordinary budget,
# then art-pixel alone with the pool held exclusively and jest in-band. The
# steps are inlined rather than run as `npm run verify:core` because that chain
# lives inside package.json and has nowhere to put a jest flag (CAL-1651), so
# tests/test_verify_sh_scope.py::test_verify_core_still_chains_the_three_steps_the_gate_inlines
# pins verify:core's literal: a fourth step added there, or a reordering, reddens
# that test rather than silently making the gate run a different sequence from
# the one a developer runs by hand.
#
# Why art-pixel is separated: its budget suite asserts a wall-clock RATIO taken
# in one worker, and CAL-1621 measured that ratio wrong (1.70 and 1.64 against
# a 1.95 bound) under jest's own parallelism inside an ordinary full gate. A
# sibling Skia worker on a neighbouring core shares memory bandwidth and the
# CanvasKit heap, which a ratio of two timings cannot cancel — hence --runInBand
# within jest, and `budget_run exclusive` across worktrees; that pairing is what
# the operator chose in specs/proposals/mobile-gate-arm-cost.md, open decision
# 1. --coverage=false is on the art-pixel phase only. Coverage is a root option
# scoped to lib/** and every non-lib project ignores lib/, so an art-pixel-only
# invocation instruments nothing and prints `Statements : Unknown% ( 0/0 )` —
# istanbul reads 0/0 as 100%, so the floor PASSES vacuously there (measured,
# CAL-1653 evidence E0: exit 0 either way). The flag keeps a floor report that
# compares nothing out of the log; the shared phase always carries lib, so the
# floor is enforced exactly once per run, where it measures something.
#
# Two shapes of the SELECTION, one shape of the arm. With a detected list the
# shared phase gets it minus art-pixel and the exclusive phase runs only if
# art-pixel was in it; unrestricted, the shared phase is `--ignoreProjects
# art-pixel` and the exclusive phase always runs. Arrays are expanded only when
# non-empty: the gate runs under bash 3.2's `set -u`, where "${empty[@]}" is an
# unbound-variable error.
mobile_gate() {
  echo "==> Mobile gate (typecheck + lint + test)"
  ensure_node_modules mobile
  pushd mobile >/dev/null
  # `npm run typecheck` and `npm run lint` are not budgeted: tsc and eslint are
  # single processes, and the budget excludes single-process arms so a
  # sub-second check never queues behind a 400-second suite.
  npm run typecheck
  npm run lint
  local -a shared=() phase_1=()
  local p pixel=0
  if [ -n "$JEST_PROJECTS" ]; then
    local -a projects
    # `--selectProjects` takes a space-separated name list, so the comma list is
    # split into an array rather than word-split unquoted under `set -u`.
    IFS=',' read -r -a projects <<< "$JEST_PROJECTS"
    for p in "${projects[@]}"; do
      if [ "$p" = art-pixel ]; then pixel=1; else shared+=("$p"); fi
    done
    if [ "${#shared[@]}" -gt 0 ]; then phase_1=(--selectProjects "${shared[@]}"); fi
    echo "==> jest phase 1: ${shared[*]:-none} (of the seven; see detect_jest_projects)"
  else
    pixel=1
    phase_1=(--ignoreProjects art-pixel)
    echo "==> jest phase 1: all but art-pixel (of the seven; see detect_jest_projects)"
  fi
  # `all`: jest is the single biggest consumer on this machine and takes the
  # whole budget when nothing else wants it. Its own maxWorkers reads
  # VERIFY_WORKER_TOKENS (mobile/jest.config.js). budget_run splits on the FIRST
  # `--`, so npm's own `--` reaches jest intact.
  if [ "${#phase_1[@]}" -gt 0 ]; then
    budget_run all npm run test -- "${phase_1[@]}"
  fi
  if [ "$pixel" = 1 ]; then
    echo "==> jest phase 2: art-pixel, in-band, with the worker pool held exclusively"
    budget_run exclusive npm run test -- --selectProjects art-pixel --runInBand --coverage=false
  fi
  popd >/dev/null
}

# Mobile file-size gate (CAL-995): warn when a CHANGED mobile/lib or mobile/app
# .ts/.tsx source crosses `engineering` → Structure's 500-line hard limit without a
# `// size:` justification marker — the reviewer's manual rule made into a
# build-time guard, alongside the token-drift and lockfile-drift gates.
#
# Hard-fail (SIZE_STRICT=1, armed by CAL-1066). The gate ran warning-first while a
# pre-existing unmarked overhang existed; that overhang is now gone — brew/index.tsx
# is marked (CAL-1018), the three brew screens are split-and-marked (CAL-1066), and
# test sources are exempt (their length is a case list, not logic). An over-limit
# mobile source must now either be split or carry a `// size:` justification.
# Scoped to the changed-file set (the same files detect_scope maps) so a diff that
# touches no oversized file stays silent.
#
# The check's own unit test runs alongside it. Nothing ran that test before, and it
# had rotted unnoticed — it still asserted brew/index.tsx was unmarked, which CAL-1018
# fixed. A gate that hard-fails the build should not be the one thing with an unrun
# test, so it is wired in here (see mobile-file-size.test.sh).
size_gate() {
  # Only reachable with an unresolvable base under an explicit VERIFY_SCOPE /
  # VERIFY_ALL — auto-detect exits above. That carve-out is what keeps CI working,
  # but it leaves changed_files() returning working-tree paths only, which after a
  # commit is the empty set: this check would then measure nothing and say
  # nothing. Warn rather than widen what it measures — a scope the caller stated
  # is not this gate's to second-guess (CAL-1365).
  if ! resolve_base; then
    echo "  WARNING: diff base '${BASE_NAME}' does not resolve here, so the mobile file-size check sees only uncommitted changes (none, once the work is committed); set VERIFY_BASE to a ref this checkout has." >&2
  fi
  local files=() f
  while IFS= read -r f; do
    [ -z "$f" ] && continue
    case "$f" in
      mobile/lib/*.ts|mobile/lib/*.tsx|mobile/app/*.ts|mobile/app/*.tsx)
        files+=("$f") ;;
    esac
  done < <(changed_files)
  [ "${#files[@]}" -gt 0 ] || return 0
  echo "==> Mobile file-size check self-test"
  bash "$REPO_ROOT/scripts/checks/mobile-file-size.test.sh" >/dev/null
  echo "==> Mobile file-size gate (${#files[@]} changed source file(s))"
  SIZE_STRICT=1 bash "$REPO_ROOT/scripts/checks/mobile-file-size.sh" "${files[@]}"
}

# Recompile one committed requirements lock and report whether it drifted from
# pyproject.toml. Seeds a temp copy of the committed lock as `uv pip compile`'s
# output target, so uv treats the existing pins as PREFERENCES and only a genuine
# dependency-surface change re-resolves — a fresh compile to an empty path would
# bump every transitive dep to its latest compatible version and report constant
# false drift. The 2-line autogenerated header (which records the output path) is
# stripped before diffing. Returns 0 = in sync, 1 = drift, 0 = could-not-verify
# (offline / resolve failure → warn and skip, never a false block).
#   $1 = committed lock path; $2 = extra compile flags (e.g. "--extra dev")
_check_one_lock() {
  local lock="$1" extra="$2"
  [ -f "$lock" ] || { echo "  (skip: $lock not present)"; return 0; }
  local tmp; tmp="$(mktemp)"
  cp "$lock" "$tmp"  # seed committed pins as preferences
  # shellcheck disable=SC2086  # $extra is an intentional word-split flag list
  # Same --python-platform/--python-version as scripts/refresh-deps.sh: the locks
  # target the python:3.11-slim image, so the check must resolve for that platform
  # rather than for the machine running the gate. Without this the gate is green on
  # macOS and red on Linux forever, because SQLAlchemy pulls greenlet only on Linux
  # (CAL-1236).
  if ! uv pip compile pyproject.toml $extra --python-platform linux --python-version 3.11 \
       --output-file "$tmp" --no-strip-extras --quiet >/dev/null 2>&1; then
    echo "  WARNING: could not recompile $lock to verify it (uv offline / resolve failed); skipping drift check" >&2
    rm -f "$tmp"; return 0
  fi
  if diff <(grep -v '^#' "$lock") <(grep -v '^#' "$tmp") >/dev/null 2>&1; then
    echo "  OK: $lock in sync with pyproject.toml"
    rm -f "$tmp"; return 0
  fi
  echo "  DRIFT: $lock is out of sync with pyproject.toml —" >&2
  diff <(grep -v '^#' "$lock") <(grep -v '^#' "$tmp") >&2 || true
  rm -f "$tmp"; return 1
}

# Lockfile-sync gate: the dev/prod Docker image installs from requirements*.lock
# (`pip install -r ...`), while the backend gate's `uv run` uses uv.lock. A dep
# added to pyproject.toml + uv.lock but never compiled into requirements*.lock
# therefore passes `uv run` yet is missing from the image — the container fails to
# import at startup and serves connection-refused (this happened with rapidfuzz).
# This gate closes that hole by recompiling the committed locks from pyproject.toml.
lockcheck_gate() {
  echo "==> Lockfile-sync gate (requirements*.lock vs pyproject.toml)"
  local fail=0
  _check_one_lock requirements.lock "" || fail=1
  _check_one_lock requirements-dev.lock "--extra dev" || fail=1
  if [ "$fail" = 1 ]; then
    echo "ERROR: a requirements lock is out of sync with pyproject.toml." >&2
    echo "       Regenerate both locks and rebuild the backend image:" >&2
    echo "         bash scripts/refresh-deps.sh && docker compose build backend" >&2
    return 1
  fi
}

# npm lockfile-sync gate: lockcheck's counterpart for the npm manifest pair
# (CAL-1501). Two guards existed and neither covered it — lockcheck recompiles
# requirements*.lock from pyproject.toml (Python only), and
# scripts/checks/ensure-node-modules.mjs proves an INSTALL matches the lockfile,
# not that the lockfile follows from its manifest. So a package-lock.json that no
# longer follows from package.json shipped green.
#
# Regenerates into a TEMP DIR and compares; it never rewrites the committed file,
# the rule openapi_drift_gate already follows. The committed lockfile is seeded
# there as npm's starting point rather than resolving from scratch, the same way
# _check_one_lock seeds the committed pins as preferences — and npm still
# recomputes the metadata it derives from package.json, which is what catches
# drift. Seeding is also the only form that works at all here: a from-scratch
# resolve of this manifest dies ERESOLVE on react-native's peerOptional
# @react-native/jest-preset.
#
# THE GENERATOR IS PINNED, and that is the load-bearing part of this gate rather
# than a detail of it. npm's output is version-dependent on byte-identical
# input: npm <= 11.6.2 writes `"dev": true` on the node_modules/fsevents entry
# and npm >= 11.7.0 does not. Unpinned, this gate reports the runner's npm
# version, not the repository — which is exactly how it blocked the 2026-08-21
# nightly promotion over a tree with nothing wrong in it, the committed lockfile
# having been hand-restored twice to the pre-11.7 form while CI ran 11.17.0.
# mobile/package.json's `packageManager` field is the single statement of which
# npm that is; `npx --yes` runs that exact one whatever is on PATH. An absent
# pin is a hard failure, never a fallback to PATH npm: a fallback would restore
# the same silent variability the pin exists to remove.
#
# Third outcome, deliberately mirroring _check_one_lock: `--package-lock-only`
# still contacts the registry to resolve, so a network/resolve failure WARNS and
# returns 0. Only genuine drift — the regeneration succeeded and the files
# differ — is a block. Collapsing the two would make every offline run a false
# red. The corollary is that a green npmlock arm is not by itself evidence the
# comparison ran: read the line, which says OK only when it did.
npmlock_gate() {
  echo "==> npm lockfile-sync gate (mobile/package-lock.json vs mobile/package.json)"
  local manifest="mobile/package.json" lock="mobile/package-lock.json"
  if [ ! -f "$manifest" ] || [ ! -f "$lock" ]; then
    echo "  (skip: $manifest and $lock are not both present)"
    return 0
  fi
  local pin
  pin="$(sed -n 's/^[[:space:]]*"packageManager"[[:space:]]*:[[:space:]]*"\(npm@[0-9][^"]*\)".*/\1/p' "$manifest" | head -1)"
  if [ -z "$pin" ]; then
    echo "ERROR: $manifest states no npm generator, so this gate has no oracle." >&2
    echo "       npm's lockfile output differs by npm version on identical input," >&2
    echo "       so an unpinned regeneration measures the runner. Pin it:" >&2
    echo "         \"packageManager\": \"npm@<version>\"   (in $manifest)" >&2
    return 1
  fi
  if ! command -v npx >/dev/null 2>&1; then
    echo "ERROR: npx is not on PATH, so the pinned generator ($pin) cannot be run." >&2
    echo "       Install Node (npx ships with npm) or run this gate on a host that has it." >&2
    return 1
  fi
  echo "  Regenerating with the pinned generator: $pin"
  local tmp; tmp="$(mktemp -d)"
  cp "$manifest" "$lock" "$tmp/"
  # Probe the generator before asking it to resolve anything, and CLASSIFY the
  # failure. Both a broken pin and a disconnected host make `npx` exit non-zero,
  # and collapsing them is how the pin acquires the failure mode it was added to
  # remove: `npm@99.99.99` from a typo can never be fetched, every run lands on
  # the warn branch, and the arm prints a skip and exits 0 forever. The pin
  # assertion in tests/test_verify_sh_scope.py cannot catch that — it reads the
  # field's shape, not whether the version exists.
  #
  # npm's own error code is the discriminator: a spec that resolves to no
  # published version is ETARGET/notarget, which is a defect in this repository's
  # manifest; anything else is the environment, which must still warn and pass.
  # Matched on the code words rather than a whole message, and defaulting to the
  # warn side, so an unfamiliar npm error is a skip rather than a false block.
  #
  # E404 is deliberately NOT in that list, and the difference is measurable: npm
  # says E404 for a registry that does not serve the package — a private mirror
  # answering an unauthenticated client, a mangled `registry=` in .npmrc — while
  # a version that is merely absent is always ETARGET. The pin's package name is
  # always `npm` (the field is parsed as npm@<version>), so a 404 on it cannot
  # mean the pin is wrong, and blocking on it sends the operator to fix a correct
  # field on a host where nothing was measurable either way.
  local probe_err probe_status=0
  probe_err="$( (cd "$tmp" && npx --yes "$pin" --version) 2>&1 >/dev/null )" || probe_status=$?
  if [ "$probe_status" != 0 ]; then
    if printf '%s' "$probe_err" | grep -qiE 'ETARGET|notarget|No matching version|Invalid Version|Invalid tag name'; then
      rm -rf "$tmp"
      echo "ERROR: the pinned generator $pin could not be fetched — no such npm version." >&2
      echo "       This gate cannot verify $lock with a generator that does not exist," >&2
      echo "       and it will not fall back to the npm on PATH. Fix the packageManager" >&2
      echo "       field in $manifest:" >&2
      printf '%s\n' "$probe_err" | sed 's/^/         /' >&2
      return 1
    fi
    echo "  WARNING: could not run the pinned generator $pin (npx offline / fetch failed); skipping drift check on $lock" >&2
    rm -rf "$tmp"; return 0
  fi
  if ! (cd "$tmp" && npx --yes "$pin" install --package-lock-only --ignore-scripts) >/dev/null 2>&1; then
    echo "  WARNING: could not regenerate $lock with $pin (npm offline / resolve failed); skipping drift check" >&2
    rm -rf "$tmp"; return 0
  fi
  if diff -q "$lock" "$tmp/package-lock.json" >/dev/null 2>&1; then
    echo "  OK: $lock follows from $manifest under $pin"
    rm -rf "$tmp"; return 0
  fi
  echo "  DRIFT: $lock does not follow from $manifest —" >&2
  diff -u "$lock" "$tmp/package-lock.json" >&2 || true
  rm -rf "$tmp"
  echo "ERROR: the committed npm lockfile is out of sync with its manifest." >&2
  echo "       Regenerate it with the SAME generator this gate measures with," >&2
  echo "       and commit the result:" >&2
  echo "         cd mobile && npx --yes $pin install --package-lock-only" >&2
  return 1
}

# Make the compose arm self-sufficient in whatever checkout it is running in
# (CAL-1514). Two things the arm needs were only ever set up in the MAIN
# checkout, by .claude/hooks/session-start.sh writing into CLAUDE_PROJECT_DIR — so every
# run in a git worktree, which is what /build and /routine create per ticket,
# read a green base as red:
#
#   1. host.docker.internal. The arm hands the test container a DSN naming that
#      host. Docker Desktop resolves it natively; Linux Docker Engine does not,
#      and the run dies at the entrypoint preflight with "could not translate
#      host name". The mapping is a compose override, and a worktree is a fresh
#      checkout that never received one.
#
#   2. The git dir. compose.yaml mounts `- .:/app`, and in a worktree /app/.git
#      is a FILE naming an absolute path outside that mount, so
#      `git rev-parse --git-common-dir` cannot answer inside the container.
#      Three tests in tests/test_verify_sh_daemonless.py make that call at
#      fixture setup and error rather than fail. Binding the resolved common dir
#      at its OWN absolute path is what makes the pointer resolve; read-write,
#      because that fixture writes <git-common-dir>/verify-env.
#
# It belongs to the gate rather than to the hook because the gate is what has to
# be self-sufficient: a hook that ran once, somewhere else, is not a
# precondition this script can assume. An existing compose.override.yaml is
# never touched — the main checkout's hook-written file, and any file a
# developer hand-edited, stay exactly as they are; this fills a gap, it does not
# own the file. The exclude entry goes in the SHARED common dir, so one entry
# covers the main checkout and every worktree of it, and nothing can commit the
# generated file or see it in `git status`.
compose_preflight() {
  local common
  common="$(git rev-parse --git-common-dir 2>/dev/null || true)"
  # Absolutise: git answers `.git` in an ordinary checkout and an absolute path
  # in a worktree, and the two are compared below.
  if [ -n "$common" ]; then
    common="$(cd "$common" 2>/dev/null && pwd || true)"
  fi

  if [ -n "$common" ] && ! grep -qx 'compose.override.yaml' "$common/info/exclude" 2>/dev/null; then
    mkdir -p "$common/info" && echo 'compose.override.yaml' >> "$common/info/exclude"
  fi

  # Spelled as an `if` rather than `[ -f … ] && return 0`: under `set -e` that
  # idiom yields the function's exit status if it is ever the last statement in
  # it, so a false test would abort the whole gate. This form cannot.
  if [ -f compose.override.yaml ]; then
    return 0
  fi

  cat > compose.override.yaml <<'EOF'
# GENERATED by scripts/verify.sh — local to this checkout, never committed (see
# <git-common-dir>/info/exclude). Docker Desktop resolves host.docker.internal
# natively; Linux Docker Engine does not, and the compose arm's DSN depends on
# the name. Delete it to test without the mapping.
services:
  backend:
    extra_hosts:
      - "host.docker.internal:host-gateway"
EOF
  local note="host-gateway mapping"
  if [ -n "$common" ] && [ "$common" != "$REPO_ROOT/.git" ]; then
    # Compose merges an override's volumes into the base service's mounts by
    # target, so declaring only what is added keeps `- .:/app` and the
    # site-packages volume intact.
    # Unquoted heredoc, so $common expands — which also means no backtick and no
    # other unescaped $ may appear in it.
    cat >> compose.override.yaml <<EOF
    # This checkout's git dir lives outside the source mount (.:/app) — a linked
    # worktree's .git is a FILE naming the path below. Read-write: the
    # verify_env_file fixture writes <git-common-dir>/verify-env.
    volumes:
      - "$common:$common"
EOF
    note="$note + git dir $common"
  fi
  echo "==> Wrote compose.override.yaml ($note)"
}

# Escape hatch: set DATABASE_URL and the backend gate skips Docker entirely,
# running ruff + pytest on the host against that Postgres. That is the arm to
# use wherever `docker compose build` cannot reach PyPI — see CLAUDE.md,
# "Tests and local database".
backend_gate() {
  echo "==> Backend gate (ruff + pytest)"
  # This arm runs the whole non-cohort suite, and one of its modules —
  # tests/test_cal1505_sdk_decided_packages.py — derives its subject set from
  # mobile/node_modules/expo/. See ghconfig_gate's header for the night that
  # proved a precondition nobody establishes is not a precondition. The compose
  # path below bind-mounts this checkout at /app, so the container reads the
  # install this line makes on the host.
  ensure_node_modules mobile
  echo "==> Lint"
  uv run --extra dev ruff check .
  # The assurance cohort runs in its OWN arm (CAL-1545), so exclude it here.
  # --ignore rather than a pytest marker, deliberately. A marker fails OPEN: a
  # manifest member left unmarked would run in backend only, and the assurance arm
  # would silently stop covering its subject — the one failure direction that
  # change exists to prevent. A marker would also force pyproject's addopts to
  # carry `-m 'not real_asgi and not assurance'` (pytest's -m is single-valued),
  # silently removing 18k lines from every hand-run `pytest`, which CLAUDE.md
  # documents as this repository's test command. --ignore also skips COLLECTION,
  # so the excluded modules are never even imported.
  #
  # Fail closed on an empty list. Reading no manifest is the fail-SAFE direction
  # for coverage — the cohort would simply run twice — but it makes "each module
  # runs in exactly one arm" silently false, and a quiet degradation is the shape
  # this repository keeps paying for. One line turns it into a named refusal.
  local ignores=() m
  while IFS= read -r m; do [ -n "$m" ] && ignores+=("--ignore=$m"); done < <(assurance_modules)
  if [ "${#ignores[@]}" -eq 0 ]; then
    echo "ERROR: $ASSURANCE_MANIFEST declares no assurance test modules, so this arm" >&2
    echo "       cannot exclude them and the cohort would run in both arms." >&2
    return 1
  fi
  # The DSN handover from .claude/hooks/session-start.sh (CAL-1467). A SessionStart hook
  # cannot export into the agent's later shells — each Bash call gets a fresh
  # shell from a profile snapshot taken at session start — so the hook writes the
  # DSN to a file in the git COMMON dir instead, where every worktree of the repo
  # sees it, nothing can commit it, and `git status` never shows it.
  #
  # A fallback, never an override: a harness or CI run that injected its own
  # per-run Postgres (CAL-537) must reach that one. And announced on stdout,
  # because an arm that changes meaning silently is worse than either arm.
  #
  # PARSED, not sourced: the gate reads a DSN out of this file, it does not
  # execute its contents.
  #
  # VERIFY_ENV_FILE names that file, so a caller can say "no DSN from anywhere"
  # by pointing it at a path that does not exist. Unsetting DATABASE_URL no
  # longer says that on its own: this fallback reads from the SHARED git common
  # dir, so on any machine whose session-start hook wrote the file — every
  # Claude-on-the-web session — a caller asking for the compose arm silently got
  # this one instead (CAL-1282's guard, defeated exactly that way). The
  # alternative, deleting the file for the duration of a test, mutates state
  # concurrent worktrees are reading.
  if [ -z "${DATABASE_URL:-}" ]; then
    local common dsn verify_env
    verify_env="${VERIFY_ENV_FILE:-}"
    if [ -z "$verify_env" ]; then
      common="$(git rev-parse --git-common-dir 2>/dev/null || true)"
      [ -n "$common" ] && verify_env="$common/verify-env"
    fi
    if [ -n "$verify_env" ] && [ -f "$verify_env" ]; then
      dsn="$(sed -n '/^DATABASE_URL=/{s/^DATABASE_URL=//p;q;}' "$verify_env")"
      if [ -n "$dsn" ]; then
        export DATABASE_URL="$dsn"
        echo "==> DATABASE_URL read from $verify_env"
      fi
    fi
  fi
  if [ -n "${DATABASE_URL:-}" ]; then
    # Postgres provided by the environment (harness per-run DB / CI service).
    # No Docker: run tests on the host against the real, provided Postgres.
    # CAL-1148: DATABASE_URL names a *server*, not the database under test —
    # conftest creates a per-run calibrate_test_<uuid> sibling on it, migrates
    # that with `alembic upgrade head`, and drops it, so no migration here and
    # nothing in the named database is touched. The role needs CREATEDB.
    echo "==> Tests (provided DATABASE_URL, no Docker)"
    # Under the budget AND in parallel, and those are one fact rather than two —
    # the same construction assurance_gate uses (CAL-1645, and see its header for
    # why the count is expanded where it is). `-n` is the number of tokens the pool
    # GRANTED, never one this arm chose for itself: `budget_run` sets
    # VERIFY_WORKER_TOKENS into the child only after acquiring, so the count is
    # expanded by a `bash -c` INSIDE the allocation — the one place both the grant
    # and pytest's argv exist. `exec` keeps the process doing the work the process
    # holding the tokens, so the kernel returns the whole allocation however it dies.
    #
    # `all` rather than the `1` this line carried before: this is the largest single
    # arm in the gate — 401s serial against 205s at -n 4 over identical counts on a
    # 4-core host — so it takes the whole budget when nothing else wants it, exactly
    # as mobile_gate and assurance_gate do, and queues behind a neighbour when
    # something does. The `-n`/`--max` pairing cannot come apart here because the
    # flag IS the grant.
    #
    # What makes the suite distributable was built for exactly this and had been
    # unused: tests/throwaway_db.py provisions a per-SESSION calibrate_test_<uuid>
    # sibling and holds advisory lock 1148 across sweep+create+connect to serialise
    # concurrent sessions on one server (CAL-1148). An xdist worker is a separate
    # process with its own pytest session, so it gets its own database by
    # construction rather than by luck. Coverage survives the split too — pytest-cov
    # combines the workers' data, and the 94% floor measured 96.76% at -n 4.
    #
    # `--dist loadgroup`, exactly as assurance_gate passes it and for the same
    # reason. It has a subject in this arm: tests/test_cal555_brews_anonymisation.py
    # walks ONE module-scoped database through 0001 -> seed -> 0002 -> back -> 0002
    # across successive tests, so which revision that database is in is the state
    # under test. Measured at `-n 4` without the flag: 3 runs out of 3 red, with
    # `RangeNotAncestorError` and tests asserting a schema no migration on their
    # worker had produced. `xdist_group` on the module states the constraint;
    # loadgroup is what makes the mark mean anything, and it distributes
    # everything unmarked exactly as `load` does — so it is not a cost paid by the
    # other 3300 tests.
    budget_run all bash -c 'exec uv run --extra dev pytest -n "$(gate_workers)" "$@"' pytest --dist loadgroup "${ignores[@]}"
  else
    # Local dev: no DB provided — bring real Postgres up via compose.
    [ -f .env ] || cp .env.example .env
    # Everything below runs containers against THIS checkout, so it needs the
    # host-gateway mapping and (in a worktree) the git dir (CAL-1514).
    compose_preflight
    echo "==> Starting database"
    docker compose up -d --wait db
    echo "==> Tests"
    # Override DATABASE_URL so the backend container reaches Postgres through the
    # host-exposed port rather than the compose-network 'db' alias.
    #
    # No --no-deps (CAL-1282). Since CAL-1190 what guarantees a migrated schema
    # is compose.yaml's `backend -> depends_on: migrate:
    # service_completed_successfully`, and --no-deps suppresses exactly that
    # resolution — so on a fresh pgdata volume the one-shot `migrate` service
    # never ran and the container's entrypoint preflight (python -m
    # app.db_health) failed before a single test executed. Deterministic on
    # every fresh worktree, which is the normal path under /build.
    #
    # The flag predates this repo's recorded history (git blame puts it on the
    # boundary commit, from when the entrypoint still ran migrations itself and
    # there was no dependency to suppress) and no reason for it was written
    # down. Dropping it costs nothing: `docker compose run` does not start the
    # target service, so resolving dependencies here starts only `db` (already
    # up) plus the one-shot `migrate`, which exits. compose.yaml stays the
    # single place the migration ordering is declared, rather than being
    # restated here.
    # Budgeted and parallel for the same reasons and with the same `all` as the
    # daemonless branch above: the tests run inside a container, but they run on
    # this machine's cores, and the pool is what every concurrent worktree shares.
    # `gate_workers` is evaluated on the HOST, inside the allocation — the container
    # holds no tokens and knows nothing of the pool — and reaches pytest as argv.
    #
    # Both modes or neither (CAL-1645 AC-1). A worker flag on one branch says
    # nothing about the other: they reach pytest through different processes and
    # share no line, so an arm parallel daemonlessly and serial under compose is not
    # a smaller improvement but two arms whose greens are not interchangeable. CI
    # and every Claude-on-the-web session take the branch above; a developer with no
    # DATABASE_URL takes this one.
    #
    # One long line rather than the three continuations it replaces. Several
    # derivations in tests/test_verify_sh_scope.py read this gate a raw line at a
    # time and shlex-split each — an unbalanced quote spread across continuations is
    # a line they cannot tokenize, and `_pytest_args_in` is loud about exactly that
    # rather than silently under-reading the gate.
    budget_run all bash -c 'exec docker compose run --rm -e DATABASE_URL=postgresql://calibrate:calibrate@host.docker.internal:5432/calibrate backend pytest -n "$(gate_workers)" "$@"' pytest --dist loadgroup "${ignores[@]}"
  fi
}

# The assurance gate (CAL-1545): this repository's tests OF ITSELF — gate dispatch,
# the gate-marker tooling, the workflow and release contracts, the guidance
# equivalence — run database-free, in their own arm.
#
# Why they are not in the backend suite. Measured on 2026-08-22
# (assessments/2026-08-22-process.md), the meta-test cohort was 30.8% of the
# backend gate's wall clock while being 17.9% of its lines, and none of it can be
# affected by an ordinary API or domain edit. The waste was making every product
# change pay for checks whose subjects had not moved. The arm is selected by the
# changes that CAN break it — see the record, workflow, tests/* and script arms in
# detect_scope — and by VERIFY_ALL=1, which is what both promotion boundaries set.
#
# Five flags, all load-bearing:
#   --noconftest  tests/conftest.py provisions a throwaway Postgres and runs
#                 `alembic upgrade head` for EVERY run (CAL-1148). Without this,
#                 an arm whose entire claim is "no database" would demand one to
#                 read a YAML file. It is the arm's CONTRACT, not a convenience:
#                 a future member needing a fixture earns an `exempt` record and
#                 stays in backend, rather than a carve-out in conftest.
#   --no-cov      pyproject's addopts adds --cov, and a partial run cannot meet
#                 the 94% floor by construction (the same pairing ghconfig_gate
#                 and engine_chain_gate already use).
#   -q            the cohort is ~1150 tests; the per-test dots are noise here.
#   -n <workers>  what makes the arm affordable (CAL-1644). It is the arm 85% of
#                 commits select, and its dominant cost is subprocess tests that
#                 each spawn the real verify.sh against their own throwaway
#                 repository. It distributes because almost none of it shares
#                 state — it touches no database by construction. Four workers on
#                 a 4-core host cut the arm by at least 3.5x over identical
#                 counts. Second-counts live in specs/features/deployment-gates.md
#                 and deliberately not here: that record reads this host's serial
#                 figure at roughly HALF an earlier reading over the same counts,
#                 and a number that moves by 2x between runs on one host is not
#                 one a shell comment can keep honest. The count itself comes from
#                 gate_workers() below, and since CAL-1646 landed it is the number
#                 of tokens the machine-wide budget GRANTED this arm — which is
#                 why the flag is expanded inside the budgeted child rather than
#                 on this line.
#   --dist loadgroup
#                 not the default `--dist load`, and not cosmetic. Two cohort
#                 modules drive the gate through `<git-common-dir>/verify-env`,
#                 which is machine-global — every worktree of this repository
#                 shares one common dir — so a fixture that owns it cannot be
#                 made per-worker. Under plain `load` those tests spread across
#                 workers and clobbered each other in both directions: measured
#                 6 runs out of 6 red, one worker's written DSN vanishing under
#                 another's teardown and the absence a control asserts being
#                 refilled mid-test. `xdist_group` on the module states the
#                 constraint; loadgroup is what makes the mark mean anything, and
#                 it distributes everything unmarked exactly as load does.
#
# ruff runs first, over scripts/ and tests/. Several paths that used to select
# `backend` for its `ruff check .` now select this arm instead
# (scripts/checks/github_config.py, the subject scripts, every cohort test
# module), so without this line a change to one of them would ship unlinted.
#
# Fails closed on an empty manifest. pyproject sets testpaths = ["tests"], so
# `pytest --noconftest --no-cov` with NO path arguments collects the entire suite
# without a conftest — hundreds of errors, or worse, a subset that passes and
# reads as this arm having verified something.

# How many parallel workers a gate arm may use.
#
# ONE named seam, deliberately, so the call sites below carry no policy. What the
# seam YIELDS changed when CAL-1646 landed. This comment used to promise that
# CAL-1646 would replace the body and that nothing calling it would change;
# neither half happened. That ticket put a blocking machine-wide token pool
# UNDERNEATH the arm instead (`budget_run`, above), and the pool hands the number
# of tokens it granted to the command in VERIFY_WORKER_TOKENS. So this function's
# job is no longer to CHOOSE a count — it is to report the one the budget already
# decided, and the call site had to change to evaluate it in the right place.
#
# WHERE it is evaluated is the whole integration. `scripts/worker_budget.py`
# blocks for one token and then tops up opportunistically without waiting again
# (D32), so an arm that asks for four may legitimately be handed two, and the
# grant is not known until after the wrapper has acquired. pytest takes its worker
# count on argv, not from the environment as jest and vitest do (D33), so a count
# computed BEFORE `budget_run` would let the arm spawn four workers against two
# tokens — the bound CAL-1646 exists to enforce, defeated in silence. That is what
# `export -f` below is for: the seam is called inside the budgeted child, which is
# the one place both the granted count and pytest's argv exist.
#
# There is deliberately no second override. VERIFY_WORKERS is gone; the knob that
# steers this arm is VERIFY_WORKER_BUDGET, which sizes the pool this reads its
# share of. Two overrides that can disagree are one bound and one way around it.
#
# An unusable reading is normalised to an explicit 1 rather than passed through,
# and the reason is that pytest-xdist ACCEPTS a non-positive `-n`: `-n 0` and
# `-n -1` both exit 0, create no workers at all, and report the same counts as
# `-n 4` (measured on tests/test_cal1541_shell_lexer.py — 151 passed, and the
# `created: N/N workers` line absent). An empty or zero count reaching `-n` would
# therefore de-parallelise this arm in silence — a slow green, not a loud red,
# with nothing on the output saying the cohort had stopped being distributed. An
# arm running with no tokens in its environment at all reads the same way and for
# the same reason: one worker, never the host's core count, because a run outside
# the pool must not help itself to the machine.
gate_workers() {
  local n="${VERIFY_WORKER_TOKENS:-}"
  case "$n" in
    ''|*[!0-9]*|0) n=1 ;;
  esac
  echo "$n"
}
# Exported so the budgeted child can call it: `budget_run` reaches the command
# through `python3 scripts/worker_budget.py`, which `execvpe`s with the
# environment it was handed, and bash carries an exported function in exactly
# that environment. Verified through the real wrapper, not assumed.
export -f gate_workers

assurance_gate() {
  echo "==> Assurance gate (gate/workflow/guidance meta-tests, no database)"
  local modules=() m
  while IFS= read -r m; do [ -n "$m" ] && modules+=("$m"); done < <(assurance_modules)
  if [ "${#modules[@]}" -eq 0 ]; then
    echo "ERROR: $ASSURANCE_MANIFEST declares no assurance test modules, so this arm" >&2
    echo "       would run pytest with no paths and collect the entire suite." >&2
    return 1
  fi
  echo "==> Lint (scripts + tests)"
  uv run --extra dev ruff check scripts tests
  # Under the budget AND in parallel, and those are one fact rather than two:
  # `-n` is the number of tokens the pool actually GRANTED, never a number this
  # arm chose for itself. `budget_run` sets VERIFY_WORKER_TOKENS into the child
  # only after acquiring, so the count is expanded by a `bash -c` INSIDE the
  # allocation — the one place both the grant and pytest's argv exist. `exec`
  # keeps the process doing the work the process holding the tokens, which is what
  # lets the kernel return the whole allocation however it dies (D31).
  #
  # `--max all`, which is what D34 named as the seam it left for this ticket: the
  # arm 85% of commits select is the dominant cost on this machine and takes the
  # whole budget when nothing else wants it, exactly as mobile_gate does. D34 also
  # recorded that nothing enforced the pairing between `-n` and `--max` — an arm
  # given `-n` without its `--max` would run xdist workers against a single token.
  # Here the pairing cannot come apart, because the flag IS the grant.
  #
  # The child shell's $0 is `pytest`, and every flag and the module list stay in
  # the OUTER argv rather than inside the quoted script. That is not cosmetic:
  # `_pytest_args_in` and `_budget_relevant_lines` in tests/test_verify_sh_scope.py
  # both shlex-split this line, key on a literal `pytest` token and read what
  # follows it. Flags moved inside the quoted script would be one opaque token to
  # both, and the arm's `--noconftest` / `--no-cov` / cohort-expansion assertions
  # would go vacuous rather than red.
  budget_run all bash -c 'exec uv run --extra dev pytest -n "$(gate_workers)" "$@"' pytest --dist loadgroup --noconftest --no-cov -q "${modules[@]}"
}

# OpenAPI drift gate: the committed mobile API client
# (mobile/generated/{openapi.json,api.ts}) is generated from the backend OpenAPI
# contract. A backend route/schema change that is never regenerated — or a
# hand-edit of the generated files — silently drifts the client from the contract,
# the exact failure ADR-013 exists to prevent. This gate regenerates BOTH
# artifacts to a temp dir via the one-command codegen (scripts/gen-api.sh, CAL-872)
# and diffs them against the committed copies, failing with a regenerate-and-commit
# remediation. It compares only — it never writes the committed files.
#
# Determinism (the precondition the gate blocks on): gen-api.sh dumps app.openapi()
# (route introspection only — no DB, no Docker; .env auto-loaded by
# pydantic-settings) and runs the pinned local openapi-typescript
# (mobile/node_modules/.bin), so output is byte-stable (verified, CAL-872/873).
# Env: dump-openapi.py imports app.main, which needs DATABASE_URL + SUPABASE_ISSUER
# present (the local .env / the CI backend job provide them); the TS step needs the
# mobile node_modules, which gen-api.sh installs if absent.
openapi_drift_gate() {
  echo "==> OpenAPI drift gate (generated client vs backend contract)"
  local tmp; tmp="$(mktemp -d)"
  # Regenerate to a temp dir — never the committed location.
  bash scripts/gen-api.sh "$tmp" >/dev/null
  local drift=0
  for f in openapi.json api.ts; do
    if ! diff -q "$tmp/$f" "mobile/generated/$f" >/dev/null 2>&1; then
      echo "  DRIFT: mobile/generated/$f differs from the regenerated backend contract" >&2
      drift=1
    fi
  done
  rm -rf "$tmp"
  if [ "$drift" = 1 ]; then
    echo "ERROR: the committed mobile API client is out of sync with the backend OpenAPI contract." >&2
    echo "       Regenerate and commit the client:" >&2
    echo "         npm run gen:api        # from mobile/  (or: bash scripts/gen-api.sh)" >&2
    return 1
  fi
  echo "  OK: mobile/generated/{openapi.json,api.ts} match the backend contract."
}

# App Flow scorecard coverage (CAL-1217). controlplane_gate below is
# controlplane/'s own self-contained `npm run verify` — it never reads
# mobile/app/ or the scorecard, so selecting controlplane alone (the
# mobile/app/* scope edge) would not actually run the check the ticket's
# problem statement needs: the pytest tests that assert scorecard coverage
# only run under backend_gate, which a mobile-only change never selects (and
# cannot select without dragging Postgres onto every route change). This is
# that check's DB-free, mobile-scoped counterpart — same
# scorecard_drift() the pytest tests call, so the invariant is one
# definition, not two that can disagree.
app_flow_scorecard_gate() {
  echo "==> App Flow scorecard coverage (route tree vs the committed registry)"
  uv run python scripts/checks/app-flow-scorecard.py
}

# The engine-chain pin (CAL-1283), the same shape as the scorecard gate above and
# for the same reason. engine_gate is skipped whenever controlplane is selected,
# on the premise that controlplane/package.json's `verify` chain already runs the
# same arms; CAL-1264 turned that premise into an assertion, but put it in tests/,
# which runs under the BACKEND gate. A controlplane/package.json edit resolves to
# `controlplane` alone — and the control-plane gate IS that npm chain, which
# cannot check itself. So the commit that dropped an arm passed the local gate and
# the pin fired later: at the two promotion boundaries (VERIFY_ALL=1 sets backend)
# and on the next unrelated change that happened to select backend, landing red on
# an innocent ticket.
#
# The scope map was never the problem — the file already selects the area that
# owns it. What was missing is a gate on that area able to run the check. This is
# it, and unlike the scorecard gate it needs no parallel check script: it runs the
# pytest that already owns the invariant, so there is one definition rather than
# two that can disagree.
#
# Three flags, all load-bearing, the first two exactly as ghconfig_gate uses them:
#   --noconftest  tests/conftest.py provisions a throwaway Postgres and runs
#                 `alembic upgrade head` on every run (CAL-1148); this scope
#                 deliberately selects no database. The marked tests use no
#                 fixture from it and still run WITH it in the full backend suite.
#   --no-cov      pyproject's addopts adds --cov, and a partial run cannot meet
#                 the 94% floor by construction.
#   -m            what keeps this cheap. The module as a whole takes tens of
#                 seconds — four runs spanned 40-49s, and a fifth under heavy load,
#                 on the then-121-test module, read 128s — because its end-to-end
#                 tests copy the design corpus into throwaway repos and run real
#                 node arms. Against ~0.5s for the marked subset: two orders of
#                 magnitude, whichever end of that spread holds. It
#                 also replaces addopts' `-m 'not real_asgi'` (pytest's -m is
#                 single-valued); this module carries no real_asgi test.
# The marked set is not a hand-kept list: tests/test_verify_sh_scope.py derives it
# from its own call graph and fails when a test that reads the chain is missing
# the marker — the CAL-1066 lesson applied to the selector itself.
#
# Deliberately NOT skipped when backend was selected, unlike engine_gate standing
# down for controlplane. A full run does execute the marked tests twice — once
# here, once inside the backend suite — and that costs about half a second. Buying
# it back means a second skip whose premise ("the backend suite runs this module
# unfiltered") would itself need pinning, which is the shape of the bug being
# fixed here. The duplication is the cheaper of the two.
engine_chain_gate() {
  echo "==> Engine-chain pin (controlplane's verify chain vs the arms engine_gate skips)"
  uv run --extra dev pytest --noconftest tests/test_verify_sh_scope.py -m enginechain --no-cov -q
}

# The design engine's design-corpus-coupled arms, run standalone for a change
# under design/ (CAL-1262). The engine lives in controlplane/engine/ since
# CAL-1225 (ADR-030) and its gate is controlplane's own `npm run verify` — so a
# design-doc edit, which selects design+mobile and never controlplane, ran none
# of the checks that own an invariant over design/ content. Chief among them the
# ADR-025 byte-identical round-trip guard: the editor's Save is a plain write
# through render(), so a doc the parser cannot reproduce is a doc the workbench
# would silently reformat. That guard could not run on the only change that can
# break it.
#
# Six arms, and the set is not a taste call: five of them BIND the live design
# root at module scope — `const <name> = … path.resolve(__dirname, '../../design')`
# — and read real docs or real tokens through it; check-control.mjs is the sixth
# and couples through the check.mjs subprocess it drives (see below).
# engine.parity.test.mjs and engine.server.test.mjs are both excluded because
# each reads the frozen pre-move corpus instead (CAL-1232 froze the parity one,
# CAL-1261 repointed the server one); one-process.test.mjs reads no corpus.
# tests/test_verify_sh_scope.py derives that set from the engine sources and
# fails if a new corpus-coupled module has no line here — the CAL-1066 lesson, and
# the durable form of this ticket's own root cause (a guard moved, the scope map
# did not follow). It matches the resolve EXPRESSION rather than one exact
# assignment line, because CAL-1261 respelled two of these bindings and the
# exact-literal form silently stopped seeing them.
#
# check-control.mjs is as load-bearing as check.mjs. ADR-030 states it plainly:
# the round-trip check alone is vacuous, because a force-opaque parser passes it.
# The control mutates the parser, asserts the gate goes RED naming the file, then
# restores it — so a green engine:check means something.
#
# engine.corpus-independence.test.mjs (CAL-1261) is here for the same reason: it
# copies design/ to a temp dir, drives a real save and a structural prose edit
# through the engine over the copy, and re-runs the other suites over it — so it
# measures the property a design edit is most likely to break, that ordinary use
# of the corpus does not redden this gate. Like check-control.mjs it mutates
# parse.mjs on disk and restores it, which is safe here only because the arms run
# sequentially under `set -e`.
#
# Invoked with `node` directly, like raw_value_gate: every arm imports only node
# builtins and repo-local modules, so this costs no `npm ci` and no
# controlplane/node_modules. That is also what makes the end-to-end test in
# tests/test_verify_sh_scope.py able to measure the gate at all — the other
# end-to-end tests shim `npm`, under which an `npm run`-based gate would be a
# silent no-op.
engine_gate() {
  echo "==> Design-engine gate (round-trip + control, over the design/ corpus)"
  node controlplane/engine/check.mjs
  node controlplane/engine/check-control.mjs
  node controlplane/engine/engine.test.mjs
  node controlplane/engine/engine.corpus-independence.test.mjs
  node controlplane/engine/search-index.test.mjs
  node controlplane/engine/token-view.test.mjs
}

# The flow-map pin (CAL-1581), the third arm of this shape after
# app_flow_scorecard_gate and engine_chain_gate, and closest to the second: it
# runs the pytest that already owns the invariant rather than a parallel check
# script, so there is one definition instead of two that can disagree.
#
# The whole module, not just the pinned test: 26 tests in 0.26-1.08s observed
# across eight runs on a loaded machine, so there is nothing to buy by narrowing.
# Six of them read a live input — the route tree, the flow corpus, or the
# committed scorecard. Of the other twenty, seventeen build a synthetic corpus
# under tmp_path and three are pure functions over literals; all twenty come
# along free. Counted on this tree, and behaviourally: mutating the live flow
# corpus reddens 1 of the 26, renaming a live route file reddens 4. The six are
# what the arm is for; the twenty are cheaper to carry than to separate.
# specs/features/deployment-gates.md carries the same figures and the cold-uv
# case, which is the one cost this band does not cover.
#
# Two flags, both exactly as engine_chain_gate uses them:
#   --noconftest  tests/conftest.py provisions a throwaway Postgres and runs
#                 `alembic upgrade head` on every run (CAL-1148). This module
#                 uses no fixture from it — the tests are pure, over tmp_path and
#                 the working tree — and this scope deliberately selects no
#                 database.
#   --no-cov      pyproject's addopts adds --cov, and one module cannot meet the
#                 94% floor by construction.
# tests/test_verify_sh_scope.py reads both off the shimmed argv, so an arm that
# quietly dropped either is caught rather than discovered on a red dev.
#
# Deliberately NOT skipped when backend was selected, unlike engine_gate standing
# down for controlplane. A full run does execute this module twice — once here,
# once inside the backend suite — for about a second. Buying that back means a
# skip whose premise ("the backend suite runs this module unfiltered") would
# itself need pinning, which is the shape of the bug being fixed here.
flowmap_gate() {
  echo "==> Flow-map pin (design/07-flows corpus + the live route tree)"
  uv run --extra dev pytest --noconftest tests/services/test_controlplane_app_flow.py --no-cov -q
}

# The record-surface pin (CAL-1647), the same shape as flowmap_gate above: it
# runs the pytest that already owns the invariant rather than a parallel check.
#
# The arm the record trees used to take is `assurance` — the whole cohort, and
# the arm most commits already select. What pins the trees this arm serves is
# this directory: tests/guidance/test_adr_numbering.py (the monotonic ADR-NNN
# rule over decisions/, reached through its CLAUDE.md literal) and
# tests/guidance/test_repo_agent_guidance.py (the CLAUDE.md/AGENTS.md byte copy).
#
# WHICH trees those are, at their real size: assessments/, strategy/, decisions/,
# and specs/proposals/ except the two coffee-art proposals the manifest declares.
# specs/features/ is NOT one of them — the manifest declares the whole tree a
# subject, because tests/test_cal1566_retired_tile_system_not_current.py globs it
# — so a feature-spec edit still takes the full cohort. The decision is made in
# the record arm of detect_scope, per file, against the manifest.
#
# The DIRECTORY is named, not a list of modules derived from the manifest. A
# derived list would reach pytest as "${modules[@]}", which
# tests/test_verify_sh_scope.py::_budget_relevant_lines reads as a pytest line
# with no `tests/`-prefixed argument — i.e. a whole-suite run — and would demand
# a `budget_run` wrapper that the seconds-long named arms (ghconfig, flowmap,
# this one) must not take. Naming the directory is also what makes
# test_every_module_the_records_arm_collects_is_in_the_cohort the control it is:
# a guidance module outside the cohort would run here without the conftest that
# provisions its database.
#
# Two flags, both exactly as flowmap_gate uses them:
#   --noconftest  tests/conftest.py provisions a throwaway Postgres and runs
#                 `alembic upgrade head` on every run (CAL-1148). These modules
#                 use no fixture from it — they read the working tree — and this
#                 scope deliberately selects no database.
#   --no-cov      pyproject's addopts adds --cov, and one directory cannot meet
#                 the 94% floor by construction.
#
# Deliberately NOT skipped when assurance was selected, for the reason
# flowmap_gate gives: a full run does execute tests/guidance/ twice — once here,
# once inside the cohort — for about a second, and buying that back means a skip
# whose premise ("the assurance arm runs this directory unfiltered") would itself
# need pinning, which is the shape of the bug being fixed here.
records_gate() {
  echo "==> Records gate (the record-surface pins: ADR numbering + the guidance byte-copy)"
  uv run --extra dev pytest --noconftest tests/guidance/ --no-cov -q
}

# controlplane/ is a self-contained package (own package.json, own node_modules)
# whose own `npm run verify` already chains everything the ticket promised
# (CAL-1183 AC-1/AC-3/AC-5): the no-raw-values self-test + check, tsc, eslint,
# vitest, and its own OpenAPI drift check (against controlplane/openapi.json,
# not mobile's). Needs no Postgres and no design token build — the isolated
# dump script (scripts/dump-openapi-controlplane.py) never imports app.config.
controlplane_gate() {
  echo "==> Control plane gate (no-raw-values + typecheck + lint + test + openapi drift)"
  ensure_node_modules controlplane
  pushd controlplane >/dev/null
  # `all`: the chain ends in vitest, which self-parallelises exactly as jest does.
  # controlplane/vite.config.ts reads VERIFY_WORKER_TOKENS for its maxWorkers.
  budget_run all npm run verify
  popd >/dev/null
}

# catalog/ gate (CAL-1250, ADR-031): the isolated Coffee Catalog service's own
# `bash catalog/scripts/verify.sh` — ruff + pytest + its own OpenAPI drift
# check, against its own Postgres (daemonless if catalog/scripts/verify.sh
# sees a DATABASE_URL, compose-brought-up otherwise). It is a separate
# top-level project (own pyproject.toml, own uv.lock, own test suite excluded
# from root's testpaths) — this is the ONLY thing that runs its gate, so a
# change under catalog/ that selected no area here would ship completely
# unverified (AC-1's "root gate must still cover it").
catalog_gate() {
  echo "==> Catalog gate (isolated service — catalog/scripts/verify.sh)"
  # `1`: the nested gate's own pytest is serial. Its acquisition also carries
  # HARNESS_WORKER_BUDGET_HELD into the child, so nothing inside that second gate
  # can queue behind the token this one holds.
  budget_run 1 bash catalog/scripts/verify.sh
}

# .github/ config gate (CAL-1244): validate .github/dependabot.yml against the
# vendored Dependabot v2 schema. This is the one file in .github/ whose breakage
# produces no signal anyone reads — GitHub flags it on a settings page and stops
# opening update PRs — so it is the one that needs a gate that can actually fail.
#
# The check's own test runs FIRST, the same shape as raw_value_gate: the check is
# a validator, so a test proving it goes red on a malformed config is the only
# thing standing between "the gate passed" and "the gate cannot fail". Nothing
# else runs that test on a .github/-only change (tests/ runs under the backend
# gate, which this scope deliberately does not select) — the exact rot that left
# scripts/checks/mobile-file-size's test asserting a stale fact for months.
#
# Two flags, both load-bearing rather than cosmetic:
#   --noconftest  tests/conftest.py provisions a throwaway Postgres database and
#                 runs `alembic upgrade head` for EVERY run (CAL-1148), so
#                 without this the config gate would demand a database to
#                 validate a YAML file — and this scope deliberately selects no
#                 database. The test file uses no fixture from that conftest, and
#                 it still runs WITH the conftest as part of the full backend
#                 suite, so nothing is skipped, only unbundled.
#   --no-cov      pyproject's addopts adds --cov, and a single-file run cannot
#                 meet the 94% floor by construction (the same reason the CI
#                 real_asgi step passes it).
# The schema itself needs no network: it is vendored and every $ref in it is
# local, which the test file measures rather than assumes. The arm as a whole is
# no longer network-free, because the paragraph below gives it an npm install to
# establish — but only in a tree that lacks one.
#
# Two test modules, and the split is not cosmetic (CAL-1505). The content rules
# that derive the SDK-decided package set read mobile/node_modules/expo/, an npm
# INSTALL — so they cannot live in tests/test_github_config_gate.py, which is an
# assurance cohort member and whose arm's CI job installs no Node. They sat there
# for one review cycle and reddened `assurance` on every pull request while the
# local gate, run in checkouts that have the install, stayed green.
# tests/test_cal1505_sdk_decided_packages.py is deliberately outside
# tests/assurance_cohort.txt for that reason; this arm and `backend` are the two
# that run it.
#
# Which is why this arm is no longer the npm-free one it used to advertise. The
# install those rules read is this arm's PRECONDITION, and an arm that states a
# precondition it does not establish is green only where something else happened
# to establish it. That held everywhere anyone looked — every developer checkout
# has the install, and the CI `backend` job runs `npm ci` in mobile/ before the
# gate — and it did not hold on 2026-08-28, when the nightly dev -> staging
# promotion gated its candidate in a fresh `git worktree`: eight tests failed on
# a missing pin list, in the FIRST arm dispatched, and `staging` did not advance.
# `ensure_node_modules` is the repository's answer to that everywhere else, so it
# is the answer here. It costs one `npm ci` in a tree that lacks the install and
# nothing at all in a tree that has it — including under VERIFY_ALL, where
# mobile_gate would pay for the same install anyway.
# tests/test_verify_sh_scope.py's site F derives the rule rather than listing
# these two arms, so the next module that starts reading an install cannot repeat
# it silently.
ghconfig_gate() {
  echo "==> GitHub config gate (dependabot.yml schema + the SDK-decided package rules)"
  ensure_node_modules mobile
  uv run --extra dev pytest --noconftest \
    tests/test_github_config_gate.py \
    tests/test_cal1505_sdk_decided_packages.py \
    --no-cov -q
  uv run python scripts/checks/github_config.py
}

# The native iOS Release artifact gate (CAL-1303). Selected ONLY by an explicit
# VERIFY_SCOPE=ios-release — see the header for why no path mapping and no
# VERIFY_ALL reaches it.
#
# Plain `python3`, deliberately: the check is stdlib-only on purpose, so it
# runs on a host that resolves no Python toolchain. It exits
# 0 pass / 1 fail / 2 internal / 3 unavailable, and `set -e` treats every one of
# those non-zero codes as a failed gate — including 3, because a host that cannot
# verify must not read as a host that verified.
ios_release_gate() {
  echo "==> iOS Release artifact gate (xcodebuild + simulator smoke; ~16-19 min)"
  python3 scripts/checks/ios_release_gate.py
}

# ----- preflight -----
# INTERNAL PATH ONLY. Its whole subject is the tree the RUNNER is about to compute:
# `currentTree`'s `git add -A` (gate-marker.js:257-289) is what would absorb a
# registered nested worktree, and the runner never calls preflight itself. A
# bypassed run mints no marker, so there is no tree for it to protect — and making
# it unconditional would put `node` on the critical path of the one verify.sh caller
# that has none (.github/workflows/verify.yml:150, VERIFY_SCOPE: assurance).
#
# The predicate is EMPTINESS, not the literal "1" this guard carried until
# harness 8.0.0. The runner now sets the variable to the REPOSITORY IDENTITY —
# `gate-marker.js` spawns the child with HARNESS_GATE_MARKER_RUNNER=<git common
# dir> so its own re-entry guard can compare identities rather than a constant
# (ADR 0018, harness #559). Against `= "1"` that is false in every real child,
# so the preflight was skipped SILENTLY while the runner went on to compute the
# tree the marker is named after — a false green, not a cosmetic drift. Emptiness
# is the one reading that holds under both regimes, and it is the same predicate
# the public path uses at :194, so the variable keeps one reading in this file.
#
# Ordering is preserved rather than argued: this runs in the child before any arm,
# and the parent computes the tree only after the child exits 0.
if [ -n "${HARNESS_GATE_MARKER_RUNNER:-}" ]; then
  echo "==> Gate preflight"
  node scripts/gate-marker.js preflight
fi

# ----- dispatch -----
# Tokens first (built once) so both the mobile typecheck and the design lint
# read a fresh build. Explicit `if` blocks (not `&& gate`) so a gate's own
# failure still propagates under `set -e` while an unselected gate is skipped.
#
# snapshot_artifacts MUST precede build_tokens: it captures the committed
# build/tokens.{json,ts,css}
# so the drift guard compares against them, not the bytes build_tokens is about to
# overwrite (CAL-725 + CAL-744 — see snapshot_artifacts).
# The freshness guard's own unit test, once, whenever a gate below is about to
# rely on it (CAL-1274). Nothing else runs it, and a check that hard-fails the
# build should not be the one thing with an unrun test — mobile-file-size's test
# rotted for months for exactly that reason (CAL-1066). Dependency-free node over
# temp fixtures, ~0.6s, so every run that trusts the guard can pay for it.
#
# FIRST in the dispatch, not in the middle of it. `ghconfig` and `backend` both
# call the guard now (see their arms), and `ghconfig` is the very next line — a
# self-test dispatched after its first caller proves nothing about that call.
if [ "$run_mobile" = 1 ] || [ "$run_design" = 1 ] || [ "$run_controlplane" = 1 ] \
  || [ "$run_ghconfig" = 1 ] || [ "$run_backend" = 1 ]; then
  echo "==> node_modules freshness guard (self-test)"
  node scripts/checks/ensure-node-modules.test.mjs
fi
# The .github config gate and lockfile-sync run first among the gates proper, in
# that order: both are cheap checks that fail fast before the heavier pytest /
# token-build gates.
if [ "$run_ghconfig" = 1 ]; then ghconfig_gate; fi
if [ "$run_lockcheck" = 1 ]; then lockcheck_gate; fi
# Its npm counterpart, next to it and for the same reason: cheap relative to the
# gates below, and a lockfile that does not follow from its manifest should fail
# before anything is built against it (CAL-1501).
if [ "$run_npmlock" = 1 ]; then npmlock_gate; fi
# The design-engine arms, BEFORE the token build (CAL-1262). Two reasons, both
# load-bearing. token-view.test.mjs compares design/03-tokens/tokens.json against
# the COMMITTED design/build/tokens.json, which build_tokens is about to
# overwrite — dispatched after it, that arm would compare canonical-vs-fresh and
# could never see a stale committed artifact, the same shape of silent death
# CAL-725 fixed one level up. And the arms are sub-second, so failing here fails
# fast. Skipped when controlplane was selected: its `npm run verify` already
# chains all six, exactly as the raw-value lint stands down when the design gate
# runs it.
if [ "$run_engine" = 1 ] && [ "$run_controlplane" != 1 ]; then engine_gate; fi
if [ "$run_mobile" = 1 ] || [ "$run_design" = 1 ]; then snapshot_artifacts; build_tokens; fi
if [ "$run_design" = 1 ]; then design_gate; fi
# Only when design did NOT run: its tokens:lint already ends in the same lint,
# so running the standalone too would just scan the tree twice.
if [ "$run_rawlint" = 1 ] && [ "$run_design" != 1 ]; then raw_value_gate; fi
if [ "$run_mobile" = 1 ]; then size_gate; fi
if [ "$run_mobile" = 1 ]; then mobile_gate; fi
if [ "$run_backend" = 1 ]; then backend_gate; fi
# After backend, before the openapi drift gate. It is cheap relative to the
# backend suite and needs nothing the gates above build, so its position buys
# nothing either way.
if [ "$run_assurance" = 1 ]; then assurance_gate; fi
if [ "$run_openapi" = 1 ]; then openapi_drift_gate; fi
if [ "$run_flowmap" = 1 ]; then flowmap_gate; fi
# Beside the other cheap named-module arms.
if [ "$run_records" = 1 ]; then records_gate; fi
if [ "$run_controlplane" = 1 ]; then app_flow_scorecard_gate; fi
if [ "$run_controlplane" = 1 ]; then engine_chain_gate; fi
if [ "$run_controlplane" = 1 ]; then controlplane_gate; fi
if [ "$run_catalog" = 1 ]; then catalog_gate; fi
# Last, and only ever under an explicit scope: it is by far the slowest arm, so
# every cheap gate above has already had its chance to fail the run.
if [ "$run_ios_release" = 1 ]; then ios_release_gate; fi

echo "==> All checks passed."
