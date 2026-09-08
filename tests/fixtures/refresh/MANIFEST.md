# Fixture provenance

Corpus for `--refresh` direct-use evidence (#592). Each real (non-synthetic)
fixture is a byte-exact extraction from a named commit in a named source repo,
verifiable with `git -C <source repo> show <sha>:<source path>`. Synthetic
fixtures are authored for this ticket and carry no source commit; each says
what it was derived from and why.

`tests/unit/test_refresh_fixtures_manifest.py` recomputes the SHA-256 of every
row below not marked synthetic and asserts it matches this table, in both
directions (a row with no file on disk, or a file with no row, both fail).

| fixture path | source repo | commit SHA | source path | SHA-256 | bytes |
|---|---|---|---|---|---|
| `nano-erp-prefix/scripts/verify.sh` | `/Users/scottluengen/Code/nano-erp` | `7193e8134fdedf104b87da0acc9372cc60e04ca2` | `scripts/verify.sh` | `ead1cefc0d9c7ce7fc59d3b0bda02c2b96ebc3cadee5d9552ec72c8f372a5e12` | 1891 |
| `nano-erp-prefix/harness.yaml` | `/Users/scottluengen/Code/nano-erp` | `7193e8134fdedf104b87da0acc9372cc60e04ca2` | `harness.yaml` | `a72aa4193ae0a074edd519604f87c536de8c14f6b709e027addd5c29541a6781` | 2497 |
| `nano-erp-prefix/package.json` | `/Users/scottluengen/Code/nano-erp` | `7193e8134fdedf104b87da0acc9372cc60e04ca2` | `package.json` | `96d122ee965dd2813e82a4aa6f0237294e3702fc94bd9021191a6006bf588d6e` | 3403 |
| `nano-erp-prefix/scripts/gate/gate-marker.js` | `/Users/scottluengen/Code/nano-erp` | `7193e8134fdedf104b87da0acc9372cc60e04ca2` | `scripts/gate/gate-marker.js` | `10dbb7035661533800d8d663c7e87553c59b59a82ac8d5d633c634fa11f0a8bb` | 39987 |
| `nano-erp-prefix/scripts/gate/harness-config.js` | `/Users/scottluengen/Code/nano-erp` | `7193e8134fdedf104b87da0acc9372cc60e04ca2` | `scripts/gate/harness-config.js` | `d71e1c3523ff0544253f83512595fbc63ec5e0c541ba5b34ae2aca3ac557c467` | 23556 |
| `nano-erp-prefix/scripts/gate/package.json` | `/Users/scottluengen/Code/nano-erp` | `7193e8134fdedf104b87da0acc9372cc60e04ca2` | `scripts/gate/package.json` | `6072e24a87bc9dba230a7a4973e7207d031d96bcc0f8b841c28a46bb416e0e61` | 460 |
| `calibrate-prefix/scripts/verify.sh` | `/Users/scottluengen/Code/calibrate` | `d457c7b993878e227722f89b29b55ba063225954` | `scripts/verify.sh` | `252f46d6c1b5adb2ca5a3630f5abf2632f568fba1b29ca3d23152e12931e6c60` | 142480 |
| `calibrate-prefix/harness.yaml` | `/Users/scottluengen/Code/calibrate` | `d457c7b993878e227722f89b29b55ba063225954` | `harness.yaml` | `4907ac233347be0a7c9f5c8f90315d3febdeb0d8c7510d63a0ac1d52ed8d65da` | 4534 |
| `nano-erp-migrated/scripts/verify.sh` | `/Users/scottluengen/Code/nano-erp` | `016673ca5fa0f7156f6b4ab1b436afaf7d821d2a` | `scripts/verify.sh` | `c301a15becbb6510389ccd5452387a6c6d35596257c06947be3404cc90265754` | 2298 |
| `nano-erp-migrated/harness.yaml` | `/Users/scottluengen/Code/nano-erp` | `016673ca5fa0f7156f6b4ab1b436afaf7d821d2a` | `harness.yaml` | `a72aa4193ae0a074edd519604f87c536de8c14f6b709e027addd5c29541a6781` | 2497 |
| `nano-erp-migrated/package.json` | `/Users/scottluengen/Code/nano-erp` | `016673ca5fa0f7156f6b4ab1b436afaf7d821d2a` | `package.json` | `96d122ee965dd2813e82a4aa6f0237294e3702fc94bd9021191a6006bf588d6e` | 3403 |
| `calibrate-migrated/scripts/verify.sh` | `/Users/scottluengen/Code/calibrate` | `67b690345928972adf2601ce952bf111c8e855eb` | `scripts/verify.sh` | `38aeb6f097dd0b15178b11b112f67a22e9948aa928871a26b0ba87d8d8274b0a` | 144832 |
| `unclassifiable/scripts/verify.sh` | — | — | — | `9f2d9c25ca576353c8ca0901aa2d648064322bdf5ef9b18a9f9e71e2df6ce839` | 1372 |
| `design-twin-diverged/.claude/rules/design-system.md` | `/Users/scottluengen/Code/calibrate` | `67b690345928972adf2601ce952bf111c8e855eb` | `.claude/rules/design-system.md` | `6a80ca72b519240f2e3356595f6dc315d37e1a203c8f21eee1e17a50e7434fc7` | 8055 |
| `design-twin-diverged/design/AGENTS.md` | `/Users/scottluengen/Code/calibrate` | `67b690345928972adf2601ce952bf111c8e855eb` | `design/AGENTS.md` | `979056294190db65833f2aa20a3a78e6dcd4517d6791042f5d766f6b951b5b85` | 4309 |
| `design-twin-diverged/harness.yaml` | `/Users/scottluengen/Code/calibrate` | `67b690345928972adf2601ce952bf111c8e855eb` | `harness.yaml` | `4907ac233347be0a7c9f5c8f90315d3febdeb0d8c7510d63a0ac1d52ed8d65da` | 4534 |
| `design-twin-absent/harness.yaml` | `/Users/scottluengen/Code/nano-erp` | `016673ca5fa0f7156f6b4ab1b436afaf7d821d2a` | `harness.yaml` | `a72aa4193ae0a074edd519604f87c536de8c14f6b709e027addd5c29541a6781` | 2497 |
| `design-twin-absent/design/README.md` | `/Users/scottluengen/Code/nano-erp` | `016673ca5fa0f7156f6b4ab1b436afaf7d821d2a` | `design/README.md` | `6bb1fecdd2b29e111369f376fc9616bcc46a112926b537a5add94faa7abcbb52` | 5459 |
| `design-twin-matching/.claude/rules/design-system.md` | — | — | — | `662cb369dd0a5cc50789a741c03fbd62cd98ff991085ec9c76a3ebd74b8d922c` | 6454 |
| `design-twin-matching/design/AGENTS.md` | — | — | — | `3f277521424ef829c735c6a980b954e766871b14caa6409eb456f4e2e0f6b4dc` | 5528 |
| `gitignore-prepopulated/.gitignore` | `/Users/scottluengen/Code/nano-erp` | `016673ca5fa0f7156f6b4ab1b436afaf7d821d2a` | `.gitignore` | `88d80fc18c22e97bf552cddbc3d22a1954376ea237d7c3abc5ec121338841c82` | 4595 |
| `gitignore-partial/.gitignore` | — | — | — | `99cc455e4e3c9f4067a28e4f90f78e9e6713c73fdb8a7ba12f93cb36014fde7c` | 410 |

## Synthetic fixtures

- **`unclassifiable/scripts/verify.sh`** — synthetic, hand-authored for #592. Not derived from any
  real repo; a minimal file exercising exactly the shapes `refresh.md`'s runner-flag
  sweep must tell apart. Five lettered sites:
  - **(a)** `check_runner() { if [ "${HARNESS_GATE_MARKER_RUNNER:-}" = "1" ]; then ... }` —
    inside a shell function body; the caller that reaches it is consumer-owned and this
    step never opens it. Must be reported, never rewritten.
  - **(b)** `if [ "${HARNESS_GATE_MARKER_RUNNER:-}" = "$expected_runner" ]` — compared
    against another variable, not the literal `1`. No translation is available. Must be
    reported, never rewritten.
  - **(c)** `case "${HARNESS_GATE_MARKER_RUNNER:-}" in 1) ... ;; esac` — a `case`
    statement, not a `[ ]`/`[[ ]]`/`test` comparison. Must be reported, never rewritten.
  - **(d)** `MODE="${HARNESS_GATE_MARKER_RUNNER:-0}"` followed later by
    `if [ "$MODE" = "1" ]` — the variable is read once by assignment and tested again
    under another name; the read this step can classify is the assignment's default
    expansion, not a direct comparison against the literal. Must be reported, never
    rewritten.
  - **(e)** `if [ "${HARNESS_GATE_MARKER_RUNNER:-}" != "1" ]; then exec node
    scripts/gate-marker.js run; fi` — an ordinary top-level public-path guard, the one
    shape the rule already knows how to translate. **Must be rewritten** to
    `[ -z "${HARNESS_GATE_MARKER_RUNNER:-}" ]`. Without this site, a run that reported
    zero rewrites here would be indistinguishable from a run that gave up on the whole
    file — (e) is what proves "left four alone" and "touched nothing" apart.

- **`design-twin-matching/.claude/rules/design-system.md`** and
  **`design-twin-matching/design/AGENTS.md`** — synthetic, both generated from this
  repo's own `templates/rules/design-system.md` (the current template, post-#547) for
  #592. The Claude form keeps the template's frontmatter and preamble (lines 1-27) with
  the two placeholder globs filled with plausible values (`design/**`, `app/**/*.tsx`);
  the Codex form replaces the frontmatter and preamble with a short host-appropriate
  intro of the same kind `init` step 4 writes. Both carry the template's own text
  verbatim from the first `##` heading (`## The two-stage lookup, before any visual
  change`) to the end of the file — confirmed byte-identical by diffing that region
  between the two files (`diff` exit 0). This is the AC-5 must-differ control: refresh
  must report *nothing* when run against a twin pair whose shared regions already match.

- **`gitignore-partial/.gitignore`** — synthetic, hand-authored for #592. Carries two of
  the four harness gate-ignore patterns (`.harness/`, `.worktrees/`), hand-written with
  no `harness:gate-ignore:begin`/`:end` markers, and omits the other two (`.evidence/`,
  `.claude/worktrees/`). A refresh run against this file must append exactly the two
  missing patterns, wrapped in the marker comments, and leave the two pre-existing lines
  untouched and outside any marker.

## Notes

- `nano-erp-prefix/harness.yaml` and `nano-erp-prefix/package.json` are byte-identical to
  their `nano-erp-migrated` counterparts (confirmed: `diff` between the two commits'
  `harness.yaml` and between the two commits' `package.json` both exit 0) — the #559
  fix changed `scripts/verify.sh` and relocated the gate helpers under `scripts/gate/`,
  not these two files. The identical hashes above are correct, not a copy-paste error.
- `nano-erp-migrated`, `design-twin-absent`, `gitignore-prepopulated` and
  `design-twin-diverged/harness.yaml` all read from each repo's current checkout tip
  rather than a commit fixed in the ticket, per the brief's "or just use the repo's
  current working tree" allowance; both source repos' working trees were confirmed clean
  (`git status --short` empty) for every path extracted, and the commit SHA recorded
  above is that tip, captured at extraction time (2026-09-08). `calibrate-prefix` and
  `calibrate-migrated`'s SHAs were similarly re-confirmed via `git rev-parse` this
  session rather than assumed from the ticket text.
