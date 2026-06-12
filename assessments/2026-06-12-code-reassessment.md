# Code reassessment — 2026-06-12 (verification + new-surface audit)

**Domain:** code (adversarial steward pass, via `/assess`)
**Branch:** `dev` @ `794711a`
**Scope:** a deeper re-assessment after the scheduled routine cleared the 2026-06-11 backlog (CAL-586–603) and an autonomous 2026-06-12 pass shipped CAL-605–614. Two jobs: (1) adversarially **verify** the prior fixes genuinely landed and are complete; (2) audit the **new, least-reviewed surface** (CAL-585 Hermes launch handle, two-entrypoint image, launcher_client, trigger.py, the query.py split). Complements `assessments/2026-06-12-code.md` (autonomous — store.py/timestamp/empty-module cluster); non-overlapping.
**Verification gate (fresh):** `bash scripts/verify.sh` → **566 passed, exit 0** (after clearing stale local `intake/__pycache__` bytecode — see CODE-3).
**Method:** direct read + mutation-check of the gate core (`close.py`), four independent adversarial sub-audits (new-code/security, docs/spec verification, refactor/dead-code completeness, test health).

## Summary

**The remediation held — this codebase is in genuinely good shape, and that is the headline.** Every 2026-06-11 finding is verifiably fixed, not cosmetically: the CAL-586 close gate now refuses a dirty worktree *before* any side effect and no longer auto-commits (mutation-verified — neutralising the gate turns the test red); the doc cluster CAL-591–595 are real rewrites/retirements; the dead-code removals (CAL-607–614) are source-complete and grep-locked; the new launcher/two-entrypoint security property (caller never controls mount/image/privilege/env) holds and is tested against the real built image. The test suite proves its behaviour rather than asserting truthiness.

The new surface is largely clean. This pass found **one Medium** (a retired command still advertised on the launcher control boundary), **three Low**, and **one Medium insight**. No Critical/High; no regression introduced by the remediation waves.

**Verification of the prior backlog:**

| Prior finding | Verdict |
|---|---|
| CAL-586 close gate dirty-worktree bypass | **Fixed & mutation-verified** — `dirty_worktree` refusal, no auto-commit (`close.py:188-208`; `test_cli_close.py:300,330`) |
| CAL-587 cancel vestigial | **Fixed** — redefined to abandon-an-open-run (status flip + `workflow_failed`), zero pid/SIGTERM (`test_cli_cancel.py:205,218`) |
| CAL-589 / 607 / 608 dead fields | **Fixed** — `current_node`/`pr_url`/`report_path`/`node_info` gone; CAL-607 now a *property* guard (every artifact key must be a declared `BaseState` field) |
| CAL-591–595 doc drift | **Fixed & complete** — README/CONTEXT verb-model rewrites, 7 engine specs bannered, AUTHORING/`build-workflow` retired, minor refs corrected |
| CAL-601 intake | **Fixed** — `intake/` source retired; `trigger.py` is the read-only ledger-observing replacement |
| CAL-602 mypy pin | **Fixed** — single pin |
| CAL-603 surface lock | **Fixed & strong** — derives the documented surface from SPEC §11 + `commands/harness.md`, compares to the live Typer app, bans retired commands |

**Findings:** 1 Medium · 3 Low. **Insights:** 1.

---

## Findings

### CODE-1 — launcher control socket advertises a retired `decision` op (surface drift on the security boundary) — **[Medium]**
- **What:** `decision` is a live launcher operation — in `OPERATIONS`, `_REQUIRED`, and `_verb_command` (returns `["decision", run_id, value]`), and the client maps a `decision` verb to it — but `harness decision` is a **retired** CLI command: it is not registered in the Typer app, and `test_cli_surface_locked.py:70` lists it in `RETIRED_COMMANDS`. Any `decision` request over the socket launches a container that runs `harness decision …`, which Typer rejects (exit 2). It can only ever fail.
- **Where:** `harness/launcher.py:88,163,239-240`; `harness/launcher_client.py:125-133`; contradicted by `harness/cli/__init__.py` (not registered) and `tests/unit/test_cli_surface_locked.py:70`.
- **Why:** Dead/broken surface on the least-reviewed, most security-sensitive boundary (code-quality dead-code rule). The deeper issue: the CAL-603 surface lock guards the *CLI registration* but never the *launcher's* `OPERATIONS`, so the launcher surface silently drifted wider than the CLI it dispatches to.
- **How:** Drop `decision` from `OPERATIONS` (`:88`), `_REQUIRED`/`_OPTIONAL` (`:163,174`), `_verb_command` (`:239-240`), and the client branch (`launcher_client.py:125-133`), plus their unit-test cases. Then close the gap that allowed it: add a test asserting `launcher.OPERATIONS` minus the read/control ops is a subset of the registered CLI verb surface (reuse `_registered_surface()` from the surface-lock test).

### CODE-2 — control socket created world-connectable on the macOS fallback path — **[Low]**
- **What:** Neither the socket nor its parent dir is permission-restricted: `create_server` does `path.parent.mkdir(parents=True, exist_ok=True)` with no `mode`, and binds with no `umask`/`chmod`. On Linux the socket lives under `$XDG_RUNTIME_DIR` (`/run/user/$UID`, 0700) which protects it; on **macOS** (the documented target) `XDG_RUNTIME_DIR` is unset, so it falls back to `~/.harness/control.sock`, created `srwxr-xr-x` (confirmed on this host). macOS honours `AF_UNIX` mode bits, so another local account/process could `connect()` and drive verb launches.
- **Where:** `harness/launcher.py:416-420`; fallback at `harness/cli/serve.py:34-47`.
- **Why:** Defense-in-depth for the "single-user, filesystem-permissioned" access model the docstrings claim. **Not exploitable under the stated single-user-personal-machine threat model** (`specs/hermes-orchestration.md:185,191`) — hence Low — but the macOS path lacks the 0700 protection the Linux path inherits for free.
- **How:** `path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)` and `os.chmod(path, 0o600)` after bind (or wrap in `os.umask(0o077)`). Test: `stat(socket).st_mode & 0o077 == 0`.

### CODE-3 — retirement guard tests scan the raw filesystem, so local bytecode cruft fails the canonical gate — **[Low]**
- **What:** `test_engine_retired.py::test_intake_files_removed` / `test_intake_package_not_importable` assert `intake/` is gone by checking the **filesystem**. A leftover `intake/__pycache__/` (stale `.pyc` from before CAL-601) makes `intake/` exist on disk, so `bash scripts/verify.sh` fails locally (**2 failed** on this host) even though the committed source is correct (`git ls-files intake/` is empty; the Docker gate is green). This is the **same class** as the `.DS_Store` papercut fixed in PR #72 — a guard that scans the working tree rather than git-tracked state.
- **Where:** `tests/unit/test_engine_retired.py` (the two intake checks). Reproduced + cleared here (`git clean -fdx intake/` → gate green at 566).
- **Why:** The canonical local gate must be trustworthy; spurious red on cruft trains developers to ignore it (and masked a real 2-test failure on first run this pass).
- **How:** Assert against git-tracked state (`git ls-files intake/` empty), or ignore `__pycache__`/dotfiles when checking for the directory's absence — mirroring the dotfile skip already added to `test_package_hygiene.py`.

### DOC-1 — `harness/trigger.py` missing from the as-built module inventory in SPEC §4 — **[Low]**
- **What:** `harness/trigger.py` (the CAL-585 Hermes-trigger stand-in; `HermesTrigger`, `agent_run_command`) is live and git-tracked, but SPEC §4.9 — the section whose banner promises to be read "as current" (`SPEC.md:102`) — documents its siblings `harness.launcher` / `harness.launcher_client` / `harness.workspace` and omits `harness.trigger`.
- **Where:** `SPEC.md:268-274` (§4.9 ends at the `:275` rule with no trigger mention); module at `harness/trigger.py`.
- **Why:** The as-built module list has a hole in the one section that promises to be current; an agent reading §4 to learn the live module set won't find the module that drives the autonomous path. (It is conceptually described elsewhere — `specs/hermes-orchestration.md` and the §1–2 "trigger slot" prose — so it is not undocumented, only missing from the §4 inventory.)
- **How:** Add a line to §4.9 naming `harness.trigger` as the local stand-in for the Hermes/human launch handle, pointing at `specs/hermes-orchestration.md`.

---

## Systemic insight

### CODE-INSIGHT-1 — guard/absence tests must assert against git-tracked state, not the raw working tree — **[Medium]**
- **Edit:** Add a principle to `test-driven-development` / `code-quality`: a test that proves a file/module was *removed* (or that a tree contains only source) must derive its set from `git ls-files` (or explicitly ignore `__pycache__`, dotfiles, and other untracked cruft) — never `Path.rglob`/`Path.exists` over the working tree. The canonical local gate (`scripts/verify.sh`) must not depend on the cleanliness of a developer's untracked files.
- **Why / evidence:** This is now a **recurring** class: the `.DS_Store` papercut (PR #72, fixed reactively in `test_package_hygiene.py`) and CODE-3 (`intake/__pycache__` tripping `test_engine_retired.py`) are the same bug in two guards. The fix prevents the next retirement's guard from inheriting it. A one-shot helper (`tracked_files_under(path)`) shared by both guard families would make the principle enforceable rather than aspirational.

---

## What is genuinely strong (verified, not assumed)

- **The CAL-586 gate fix is real and self-enforcing** — `close` refuses `dirty_worktree` before any side effect; `_merge_and_push` no longer auto-commits. Mutation-verified: neutralising the dirty check turns exactly the right tests red.
- **Security on the new autonomous path holds** — the launcher op/param allowlist makes `privileged`/`volumes`/`image`/`env`/`network`/`user` inexpressible; only the realpath-resolved, allowlist-checked, colon-rejected repo path reaches the docker-option region; credentials are injected by name (never argv/logs) and credential *mounts* are scoped to verb containers, not the agent container. Tested against the **real built image** (8/8 integration tests run here).
- **The dead-code/refactor waves are source-complete** — `run_git`/`rev_parse_head`/`iso_z` single-sourced and grep-locked; the query.py split is a thin facade over genuinely-shared modules, no over-split, no circular imports; CAL-607 is now a schema *property* guard, not a hardcoded absence.
- **Docs are reconciled, and the reconciliation is enforced** — the supersede-banner strategy works because `test_cli_surface_locked.py` makes only banner-declared-current sections track the code.

---

*Filed 2026-06-12 in Harness v3 — all actionable, none `decision`-labelled: CODE-1 → CAL-616 · CODE-2 → CAL-617 · DOC-1 → CAL-618 · CODE-INSIGHT-1 (subsumes CODE-3) → CAL-619. The scheduled routine works the backlog one issue at a time.*
