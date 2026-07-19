# Pre-publication disclosure & operating-model review — 2026-07-19

**Ticket:** CAL-1189 · **Scope:** go/no-go readiness for making the `harness`
repository public · **Reviewer:** harness verb loop (`/harness run CAL-1189`).

This is a **one-off pre-publication review**, not an `/assess` steward pass — it
lives in `assessments/` with the other review reports but is not part of the
code/system/code-deep retention rotation (do not fold it into `LOG.md`).

It reviews the **current tree at HEAD `9034207`** and the **complete git history**
(818 commits). It does *not* make the repository public, rewrite history, rotate
credentials, or change the license — all four are out of scope per the ticket.

---

## Recommendation

**`ready after listed fixes`.**

There are **no blockers**: no real credential or private key exists in the current
tree or anywhere in git history, and the tree carries no personal home path, IP,
machine name, or email beyond what publishing under the owner's own GitHub account
inherently exposes. The repository has already been deliberately engineered for
publication (the 2026-07-06 open-sourcing scrub, CAL-1027, plus gate-enforced
guards), and its public-facing docs handle over-trust and turnkey-support
expectations unusually well.

The "listed fixes" are a short set of **reputation-shaping / accuracy revisions**,
none of which is a hard gate. The one I would not publish without a human
consciously approving is the **negative characterization of a named external
vendor** in a retired design doc (§Should-do 1). The operator may downgrade any
should-do to "accept as-is"; the review's recommendation is to action the short
list — chiefly items 1–3 — before flipping visibility.

---

## AC-1 — Current-tree secret scan

**Tools/commands run:**

- `uvx detect-secrets scan --all-files` (Yelp detect-secrets, ephemeral via `uvx`).
- Targeted pattern grep over tracked files for provider tokens
  (`lin_api_`, `sk-ant-`, `AKIA…`, `gh[pousr]_…`, `xox[baprs]-…`, JWT `eyJ….….…`,
  `-----BEGIN … PRIVATE KEY-----`).
- `git ls-files | grep -E '(^|/)\.env($|\.)'` to confirm no env file is tracked.

**Result: no real credentials.** `detect-secrets` returned 5 hits, all confirmed
non-secret:

| File:line | Flagged as | What it actually is |
|---|---|---|
| `.codex/agents/python-dev.toml:72` | Secret Keyword | the word "Secrets:" in a guidance sentence |
| `tests/unit/test_cli_doctor.py:580` | Secret Keyword | `"sk-test"` placeholder in a test env |
| `tests/unit/test_cli_review.py:388` | Secret Keyword | the test-string literal `INTERNAL_CHAIN_OF_THOUGHT_THAT_MUST_NOT_LEAK` |
| `tests/unit/test_license_boundary.py:79` | Hex High Entropy | the SHA-256 checksum of the AGPL body (a pinned constant) |
| `tests/unit/test_promotion_pr.py:122` | Hex High Entropy | `"abc1234def"`, a fake gated SHA in a test |

No `.env` / `.env.*` is tracked; `.gitignore:22-23` ignores both. The only sample
credential in docs is the obvious placeholder `lin_api_xxxxxxxxxxxxxxxx`
(`commands/harness.md`).

**Standing control:** `tests/unit/test_secret_hygiene.py` fails the gate if any
dotenv / private-key / keystore file is ever committed, and pins the `.gitignore`
rules — the tree stays clean going forward, not just today.

## AC-2 — Git-history secret scan

**Tools/commands run** (against the main checkout, where `.git` holds full history
— a worktree's `.git` is a pointer file and cannot be scanned):

- **`gitleaks` (official image, entropy + rule scan of all history)** — the exact
  command RUNBOOK.md documents:
  ```
  docker run --rm -v "$(pwd):/repo:ro" \
    -e GIT_CONFIG_COUNT=1 -e GIT_CONFIG_KEY_0=safe.directory -e GIT_CONFIG_VALUE_0='*' \
    ghcr.io/gitleaks/gitleaks:latest git --log-opts="--all" --no-banner /repo
  ```
  → **523 commits scanned, ~8.82 MB, `no leaks found`.** (818 total commits, 523
  with diff content; merge commits carry no new content.) This refreshes the
  **2026-07-06 audit of record** (gitleaks v8.30.1, 397 commits, 0 findings) against
  the larger present-day history — still 0.
- **`.env` / key-file history check** —
  `git log --all --full-history -- '.env' '.env.*' '*.pem' '*.key' 'id_rsa*' 'id_ed25519*' '*.p12' '*.pfx'`
  → **empty**: no env file or private key was ever committed at any point.
- **Provider-pattern sweep across all history diffs** —
  `git log -p --all -U0 | grep -aoE '<provider patterns>'` → **no matches**; a
  secret-keyword-assignment sweep surfaced only test fixtures (`tok-fresh`,
  `tok-stale`, the placeholder `ghp_secret`, `s3cr3t`, `env-secret`), no real values.

**Result: no `.env`, private key, API key, OAuth token, or high-entropy credential
was ever committed.** No history rewrite is required on secret grounds.

**One non-secret history note (LOW):** the current tree is scrubbed of private
surfaces and guarded (`tests/unit/test_no_private_surfaces.py`), but **git history
retains pre-scrub surfaces** that predate the CAL-1027 scrub:

*(The literals are described generically below — this report is a tracked file, so
it must not reproduce the exact private surfaces its own subject is; the
`test_no_private_surfaces` guard enforces that, and correctly flagged an earlier
draft that quoted them verbatim.)*

| Surface (generic form) | Commits in history | Sensitivity |
|---|---|---|
| the current Linear **workspace URL** (`linear.app/<slug>`) | 5 | reveals the private tracker org slug + that tickets map to `CAL-xxxx` (both 404 for an unauthenticated reader) |
| the **legacy workspace URL** (pre-rename slug) | 16 | same, pre-rename |
| the operator's **personal home path** (`/Users/<username>`) | 12 | reveals the macOS username (already visible via commit-author identity) |

The exact literals are the ones pinned in `tests/unit/test_no_private_surfaces.py`
(`_WORKSPACE_URL`, `_WORKSPACE_URL_LEGACY`, `_PERSONAL_PATH`). None is a credential;
impact is low. The on-record decision is to **keep full
history** (RUNBOOK.md §Pre-public secret audit), which was reasoned on *secrets*.
It did not explicitly weigh these non-secret personal/workspace surfaces. See
Should-do 4.

## AC-3 — Personal & operational disclosure across docs

Reviewed `README.md`, `SECURITY.md`, `RUNBOOK.md`, `CONTEXT.md`, `CLAUDE.md`,
`CONTRIBUTING.md`, `ONBOARDING.md`, `BOOTSTRAP.md`, `RELEASING.md`, `AGENTS.md`,
`GEMINI.md`, and the `.claude/`, `.codex/`, `commands/`, `agents/`, `skills/`,
`specs/` (incl. `proposals/`, `retired/`, `decisions/`), and `assessments/` trees.

**No remove-before-public personal data.** No personal email, home path
(`/Users/<name>`), machine hostname (`raspberrypi`, etc.), private/Tailscale IP
(`100.x`/`192.168.x`/`10.x`), or personal-tool reference (`mlx-llm` as a personal
setup) appears in the tracked tree. Grep across the tree for all of these returned
zero. Home-path references in docs are all generic `~/` form.

**What *is* disclosed, classified:**

- **ACCEPTABLE (inherent to a public repo):**
  - GitHub owner slug `sluengen/harness` and clone URLs (`README.md`, `ONBOARDING.md`,
    `BOOTSTRAP.md`, `docker/Dockerfile`, `specs/infrastructure.md`, `registry.yaml`,
    the release workflow). This is the repo's own address.
  - Copyright name **Scott Luengen** (`LICENSE`, `LICENSE-GUIDANCE`, `pyproject.toml`)
    and first-name decision attributions in `specs/` — standard authorship on one's
    own project.
  - Named auth *mechanisms* with no values: macOS Keychain OAuth, `~/.codex` mount,
    `CLAUDE_CODE_OAUTH_TOKEN`, `.env`-sourced `LINEAR_API_KEY` (documented gitignored).
  - Internal engineering history in `assessments/` (CAL ids, PR numbers, test counts)
    — normal, no fragility an attacker can weaponize, no personal/secret data.
  - **`SECURITY.md:27-36` is a positive:** it correctly disclaims the ledger as a
    security control (see AC-6).

- **REVISE-BEFORE-PUBLIC (reputation-shaping; see Should-do):**
  - `specs/retired/hermes-orchestration.md:58` — a negative supply-chain/vendor-risk
    characterization of a **named external company (Nous)**. (Should-do 1.)
  - Repeated `Nous` / `Hermes` integration references across `specs/retired/` and
    `specs/proposals/harness-as-tool.md` — exposes an adjacent private-project
    ecosystem; reads as unpolished-internal. (Should-do 2.)
  - `specs/proposals/borrow-from-ponytail.md:14-20` — a negative verdict ("do not
    install it", "net-negative") on a **named third-party author's public tool**.
    Fair technical critique, but review the tone. (Should-do 2.)
  - `RUNBOOK.md:24-59` — names the operator's out-of-repo scheduled-trigger files
    and their drift war-story. RUNBOOK explicitly declares itself an app-operator doc
    ("not distributed guidance"), which contains the concern; low priority. (Optional.)
  - `specs/local-orchestrator-stack.md:154` — documents an **unauthenticated local
    MLX inference server** (caveated: bound to localhost, flagged as an unvalidated
    spike). (Optional.)

## AC-4 — Operating-model exposure: generic vs repository-specific

**Generic / convergent — NOT meaningful IP or competitive leakage** (and correctly
not treated as such): test-driven development, spec-driven development, Linear as
the tracker, the `dev → staging → main` branch topology, worktree-per-run, a SQLite
run ledger, and review-before-merge gating. These are industry-standard or
convergent practices; publishing them discloses nothing a competitor could not
independently arrive at.

**Repository-specific / unusually explicit — but intentional and non-sensitive:**

- **The core novel method is *meant* to be read.** The SHA-bound review verdict, the
  append-only ledger as audit trail, and the builder/recorder separation are the
  project's thesis; the README, SPEC, and `harness-as-tool` proposal publish them on
  purpose. This is contribution, not leakage.
- **The autonomous unattended-loop posture is unusually explicit.** `settings/harness.json`
  / `.claude/settings.json` `autoMode.allow` enumerates exactly what the loop may do
  unattended — push reviewed work to `dev`, defer a ticket, file `/assess` findings,
  run worktree housekeeping, `harness close` (merge/push/transition), commit an
  advisory `/assess` report. This is deliberately public (the README changelog frames
  "the unattended-run posture ships to consumers"). It is reputation-relevant — a
  reader learns the maintainer runs agents that push and close tickets autonomously —
  but it is honestly framed and carries no secret. Acceptable.
- **Future/experimental directions are visible** (Hermes as a design-only/retired
  dispatcher; an OpenCode+MLX local-orchestrator spike). These are marked retired or
  hypothesis-only. Mild "shows the roadmap" exposure; not sensitive. The one edge is
  the named-vendor framing in those docs — see Should-do 1–2.

The operating model, in short, is **mostly generic practice plus a deliberately
published novel audit method**. No operating-model disclosure rises to a blocker.

## AC-5 — License split (AGPL engine + MIT guidance)

**Structure.** Engine (`harness/` CLI + build/container tooling) is **AGPL-3.0-only**
(`LICENSE`); the guidance the installer copies into consuming repos (`agents/`,
`commands/`, `hooks/`, `process/`, `settings/`, `skills/`, `templates/`) is **MIT**
(`LICENSE-GUIDANCE`). The boundary is not hand-maintained prose — it is the `files:`
block of `registry.yaml`, held in correspondence by `tests/unit/test_license_boundary.py`,
which also pins the AGPL body's SHA-256 so the operative text stays verbatim.

**Assessment:**

- **Adoption — well-designed.** The part that is physically copied into an adopter's
  repo is MIT, so the methodology can be installed into *any* codebase, including a
  proprietary one, and encumbers nothing. Copyleft never reaches into an adopter's
  code. This is the correct split for a guidance-distribution model and removes the
  main adoption barrier AGPL would otherwise create.
- **Profile.** AGPL on the engine signals strong copyleft; some organizations
  policy-ban AGPL outright. But the chilling effect is bounded to those who would
  modify/redistribute the *engine* or run it as a network service — a self-hosted
  dogfood tool with effectively one consumer today. Low practical downside.
- **Commercial optionality — deliberately preserved.** Two mechanisms keep a future
  commercial exception or relicense open: (1) copyright sits with a **single holder**;
  (2) `CONTRIBUTING.md` requires an inbound **relicensing + patent grant**, so the
  option survives even after outside PRs merge. `CONTRIBUTING.md:67-76` explains the
  unusual relicensing grant plainly and offers an opt-out. This is the one item worth
  a conscious call: AGPL-plus-CLA-relicensing is sometimes read by the OSS community
  as open-core / rug-pull optionality. It is already mitigated by the candid
  explanation; no change required, flagged for awareness.
- **Optional cosmetic:** confirm GitHub's license detection shows **AGPL-3.0-only**
  (not "Other") after publishing — the short preamble before the AGPL body can lower
  the licensee match score. Purely a badge concern. (Optional.)

**License raises no blocker and needs no clearer explanation than it already has.**

## AC-6 — User-expectation risk (over-trust / turnkey support)

**Already handled well — this is a strength, not a gap.**

- **Turnkey expectation** is defused at the top of the README (`## Is this turnkey?
  No — it's dogfood infrastructure`, `README.md:31`) and repeated in `CONTRIBUTING.md`
  and `SECURITY.md` ("single-maintainer", "best-effort", "no service-level guarantee").
- **Over-trust as a security boundary** is explicitly disclaimed:
  `SECURITY.md:27-36` states the ledger is "**not** a cryptographic attestation …
  anything with write access … can append, alter, or delete an event … Do not build a
  security control on top of it." This is exactly the right anti-over-trust language,
  prominently placed.
- **No bug bounty / no support SLA** is stated plainly (`SECURITY.md:38-41`,
  `CONTRIBUTING.md`).

**One accuracy gap (should-do):** `README.md:46` and `CONTEXT.md:67` describe the
`review` verb as "**run Codex** against the worktree HEAD," but the actual **default
review engine is Claude** — `--engine codex` is a host-only cross-model option
(ADR 0002; `commands/harness.md:65,85,91`: "engine defaults to claude"). A public
reader would misunderstand which model reviews their code. Precise fix in Should-do 3.

---

## AC-6 (continued) — Recommended pre-publication actions

### Blocker (must fix before the visibility flip)

**None.** No secret, credential, private key, or remove-before-public personal datum
exists in the tree or history.

### Should-do (recommended before public; the operator makes the final call on each)

1. **Soften or genericize the negative characterization of the named vendor "Nous"**
   in `specs/retired/hermes-orchestration.md:58` (and the related integration framing
   at `:96,104,110`). Publishing a negative supply-chain/vendor-risk judgment about a
   real, named, smaller company is the single item I would want consciously approved
   before it is public. Options: replace "Nous" with a generic "a third-party runtime
   vendor," or move the risk note to neutral language. This doc is *retired*, which
   makes editing or trimming it cheap.
2. **Review the tone of third-party critiques.** `specs/proposals/borrow-from-ponytail.md:14-20`
   gives a named external author's public tool a "do not install / net-negative"
   verdict. Keep the technical conclusion; soften the framing, or genericize the name.
3. **Correct the review-engine description** in `README.md:46` and `CONTEXT.md:67`:
   the default review engine is **Claude**, not Codex (`--engine codex` is a host-only
   option). One-line fix in each; high-confidence accuracy improvement.
4. **Make the git-history disclosure decision explicit.** History retains the private
   Linear workspace URL (current slug ×5, legacy slug ×16) and the operator home
   path (×12) in pre-scrub commits. Either (a) record in RUNBOOK's
   pre-public section that these *non-secret* surfaces are knowingly accepted (low
   impact — the URLs 404 for outsiders and the username is already in commit
   authorship), or (b) if the workspace slug is considered sensitive, scrub just these
   literals from history (`git filter-repo`) before the flip. Recommendation: (a) —
   accept and document; the cost of a history rewrite is not justified by the impact.

### Optional (nice-to-have polish)

- Add a one-line note (in `README` or a settings comment) framing the `Bash(*)` allow
  + broad `autoMode` posture, so a reader of a repo that markets gate discipline reads
  it as deliberate (it is: the destructive-git deny-list guards it, and `claude -p`
  auto-approves only what is not denied) rather than as a lapse.
- Add a short security note to `specs/local-orchestrator-stack.md` that the MLX server
  spike must stay localhost-bound and is unauthenticated by design (it is already
  caveated; this makes it unmissable).
- After publishing, confirm the GitHub license badge reads **AGPL-3.0-only**, not
  "Other" (preamble-before-body can lower the detection score).

---

## Evidence summary

| Category | Method | Result |
|---|---|---|
| Current-tree secrets | `uvx detect-secrets scan --all-files` + provider grep | 0 real (5 placeholders/checksums) |
| History secrets | `gitleaks` (all history, 523 commits/8.82 MB) + `.env`/key file-history + provider-diff grep | 0 leaks; no env/key ever committed |
| Personal data in tree | multi-pattern grep (email/path/IP/host/tool) | 0 (only owner slug + copyright name) |
| Private surfaces in tree | `test_no_private_surfaces.py` (gate-enforced) | clean |
| Private surfaces in history | `git log -S` on 3 literals | present (non-secret, LOW — Should-do 4) |
| License boundary | `LICENSE` / `LICENSE-GUIDANCE` / `registry.yaml` / `test_license_boundary.py` | sound; optionality preserved |
| Over-trust / turnkey | `README.md` / `SECURITY.md` / `CONTRIBUTING.md` read | well-handled (1 accuracy fix) |

**Standing guards that keep this true going forward:** `test_secret_hygiene.py`
(no env/key file may be committed), `test_no_private_surfaces.py` (no workspace URL
or personal path in the tracked tree), `test_license_boundary.py` (the MIT/AGPL
boundary matches `registry.yaml` and the AGPL text is verbatim).

## Final recommendation

**`ready after listed fixes`** — no blockers; action Should-do 1–3 (and decide
Should-do 4) before flipping visibility. Every should-do is downgradable to
"accept as-is" at the operator's discretion; the review recommends doing the short
list first, chiefly the named-vendor softening (1) and the engine-default accuracy
fix (3).
